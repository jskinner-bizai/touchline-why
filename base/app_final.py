"""Recorded demo by default; explicit, bounded local inference is optional.

No SDK is imported and no provider is contacted unless --enable-model is set.
Even then, only the separate Run local model button starts a request. Durable
facts remain owned by M3; a model chooses a supplied candidate, never numbers.
"""
from __future__ import annotations

import argparse
import copy
import json
import threading
import time
from pathlib import Path
from http.server import ThreadingHTTPServer

from app_m3 import Desk, Handler, ROOT
from durable_controller import OPERATION_ID
from touchline_core import load_events


class FinalDesk(Desk):
    def __init__(self, events, db_path, *, selector=None, model_until_ms=0,
                 model_budget=None, preflight=None, clock=None):
        if preflight is not None and not callable(preflight):
            raise ValueError('Preflight must be a synchronous pure callback')
        # Set these before super(): future M3 initialization may call state().
        self.selector = selector
        self.selector_preflight = preflight
        self.model_until_ms = model_until_ms
        self.model_budget = model_budget
        self.live_clock = clock or (lambda: time.time_ns() // 1_000_000)
        self.live_calls = 0
        self.live_wall_ms = 0.0
        self.live_job = {'status': 'idle'}
        self.live_worker = None
        self.live_generation = 0
        self.live_overlay_id = None
        self.live_job_scope = None
        self.closed = False
        super().__init__(events, db_path)

    def _preflight(self, snapshot):
        # No selection token is allocated by a catalog eligibility check.
        request = {'candidates': copy.deepcopy(snapshot.get('candidates'))}
        if self.selector_preflight is None:
            # Controlled selectors in SDK-free tests use the shipped meaningful
            # candidate-ID policy. The actual CLI supplies adapter.preflight,
            # which additionally validates all catalog/evidence/schema limits.
            candidates = request['candidates']
            if not isinstance(candidates, list):
                return {'eligible': False, 'status': 'invalid_request', 'reason': 'Candidates must be a list.'}
            count = len(candidates)
            if count == 0:
                return {'eligible': False, 'status': 'no_candidates', 'reason': 'No current supplied pattern candidates.'}
            if count < 2:
                return {'eligible': False, 'status': 'insufficient_candidates',
                        'reason': f'candidate_id selection requires at least 2 valid supplied candidates; found {count}.'}
            return {'eligible': True, 'status': 'eligible', 'reason': f'{count} current candidates meet the 2-candidate minimum.'}
        try:
            result = self.selector_preflight(request)
        except Exception:
            return {'eligible': False, 'status': 'preflight_error', 'reason': 'Configured request preflight failed.'}
        if (not isinstance(result, dict) or type(result.get('eligible')) is not bool
                or not isinstance(result.get('status'), str) or not isinstance(result.get('reason'), str)):
            return {'eligible': False, 'status': 'preflight_error', 'reason': 'Configured request preflight returned an invalid result.'}
        return {key: copy.deepcopy(result[key]) for key in ('eligible', 'status', 'reason')}

    def _availability(self):
        budget = self.model_budget() if self.model_budget else None
        spent = max(self.live_wall_ms, (budget or {}).get('wall_spent_ms', 0))
        remaining = max(0.0, 50000 - spent)
        running = bool(self.live_worker and self.live_worker.is_alive())
        available = bool(self.selector and not self.closed and not running
                         and self.live_clock() < self.model_until_ms
                         and self.live_calls < 4 and remaining > 250
                         and not (budget or {}).get('cleanup_failed', False))
        return available, running, spent, budget

    def state(self):
        with self.lock:
            state = super().state()
            eligibility = self._preflight(state['envelope']['snapshot'])
            available, running, spent, budget = self._availability()
            available = available and eligibility['eligible']
            job = copy.deepcopy(self.live_job)
            scope = self.live_job_scope
            if scope and (scope['engine_epoch'] != state['envelope']['engine_epoch']
                          or scope['through_ms'] > state['envelope']['through_ms']):
                job.pop('result', None)
                job['result_withheld'] = 'Trace belongs to another replay epoch or a later event watermark.'
            state['live_inference'] = {
                'enabled': self.selector is not None, 'available': available,
                'eligibility_status': eligibility['status'], 'eligibility_reason': eligibility['reason'],
                'running': running, 'attempts': self.live_calls, 'max_calls': 4,
                'wall_spent_ms': round(spent, 3), 'wall_budget_ms': 50000,
                'per_call_timeout_ms': 12000, 'cutoff_ms': self.model_until_ms,
                'budget_scope': 'This explicitly enabled process; separate from four historical attempts.',
                'server_cancellation_verified': False,
                'job': job, 'adapter_budget': budget,
            }
            state['model_available'] = available
            state['real_model_calls'] = self.live_calls
            state['live_model_calls_this_milestone'] = self.live_calls
            pub = state['publication']
            selected_live = (not pub['card']['fallback'] and self.live_overlay_id is not None
                             and pub['provenance']['engine_overlay_id'] == self.live_overlay_id)
            if selected_live:
                pub['card']['replay_label'] = 'LIVE LOCAL MODEL SELECTION - deterministic facts'
                state['recorded_replay']['label'] = pub['card']['replay_label']
            elif (self.selector and self.live_job['status'] == 'accepted' and pub['card']['fallback']
                  and state['envelope']['reason'] == 'expired'
                  and self.live_overlay_id in state['envelope']['retracted_overlay_ids']):
                state['recorded_replay']['label'] = 'DETERMINISTIC VERIFIED FACTS - live selection no longer current'
            return state

    def control(self, value):
        if not isinstance(value, dict) or not isinstance(value.get('operation_id'), str) or not OPERATION_ID.fullmatch(value['operation_id']):
            raise ValueError('Operation ID required')
        command = {key: val for key, val in value.items() if key != 'operation_id'}
        operation_id = value['operation_id']
        with self.lock:
            if operation_id in self.operations:
                if self.operations[operation_id] != command:
                    raise ValueError('Conflicting operation ID')
                return self.state()
            if command.get('action') != 'infer':
                result = super().control(value)
                # Durable clones intentionally have no worker. This outer epoch
                # rejects callbacks after every successful intervening command.
                self.live_generation += 1
                return result
            if command != {'action': 'infer'}:
                raise ValueError('Unexpected fields')
            if self.durable.operation_command(operation_id) is not None:
                raise ValueError('Conflicting operation ID')
            # A stale/poisoned journal must fail before spending any call budget
            # or dispatching a provider request from old in-memory facts.
            current = self.durable.state()
            eligibility = self._preflight(current['envelope']['snapshot'])
            if not eligibility['eligible']:
                raise ValueError(f"Local selection ineligible: {eligibility['status']}: {eligibility['reason']}")
            available, _, _, _ = self._availability()
            if not available:
                raise ValueError('Local model disabled, busy, expired or exhausted')
            c = self.durable.controller
            request = c.engine.selection_request(c.audience, c.language)
            generation = self.live_generation
            self.live_job_scope = {'engine_epoch': request['engine_epoch'],
                                   'through_ms': request['snapshot']['upto_ms']}
            self.live_calls += 1
            self.operations[operation_id] = copy.deepcopy(command)
            if len(self.operations) > 500:
                self.operations.pop(next(iter(self.operations)))
            self.live_job = {'status': 'running', 'request_id': request['token_id'],
                             'started_at_ms': self.live_clock(), 'source': 'new local inference'}

            def run():
                started = time.monotonic()
                try:
                    result = self.selector(copy.deepcopy(request))
                    # The HTTP interface only accepts finite, bounded JSON.
                    if not isinstance(result, dict) or len(json.dumps(result, allow_nan=False).encode()) > 131072:
                        raise ValueError('Invalid bounded model result')
                except Exception as error:
                    result = {'status': 'model_error', 'selection': None,
                              'error_type': type(error).__name__, 'trace': []}
                elapsed = (time.monotonic() - started) * 1000
                with self.lock:
                    self.live_wall_ms += elapsed
                    status = 'stale_rejected'
                    if not self.closed and generation == self.live_generation:
                        try:
                            self.durable.state()  # verify before any result mutation
                        except (ValueError, RuntimeError):
                            status = 'durability_unavailable'
                        else:
                            engine = self.durable.controller.engine
                            try:
                                if result.get('status') == 'selected' and result.get('selection') is not None:
                                    engine.apply_selection(request, result['selection'])
                                    self.live_overlay_id = engine.view()['overlay_id']
                                    status = 'accepted'
                                else:
                                    status = 'timeout' if result.get('status') == 'timeout' else 'invalid_selection' if result.get('status') in {'invalid_output', 'invalid_selection', 'invalid_response'} else 'model_error'
                                    engine.fail_selection(request, reason=status)
                            except (ValueError, RuntimeError):
                                status = 'stale_or_invalid_rejected'
                    self.live_job = {'status': status, 'request_id': request['token_id'],
                                     'finished_at_ms': self.live_clock(), 'source': 'new local inference',
                                     'elapsed_ms': round(elapsed, 3), 'result': copy.deepcopy(result)}

            self.live_worker = threading.Thread(target=run, name='touchline-final-local-selection', daemon=True)
            self.live_worker.start()
            return self.state()

    def close(self):
        with self.lock:
            self.closed = True
            self.live_generation += 1
        # A provider may continue server-side after client cleanup. No server
        # cancellation is claimed; the existing adapter bounds client lifecycle.
        if self.live_worker:
            self.live_worker.join(timeout=12.5)
        self.durable.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8770)
    parser.add_argument('--db-path', type=Path, required=True)
    parser.add_argument('--enable-model', action='store_true')
    parser.add_argument('--model-until-ms', type=int, default=0,
                        help='Explicit local resource cutoff within 45 minutes')
    parser.add_argument('--model', choices=['gemma4:12b', 'qwen2.5:14b'], default='gemma4:12b',
                        help='An already installed, inspected tag; never downloaded here')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Unprivileged port required')
    selector = budget = preflight = None
    if args.enable_model:
        now = time.time_ns() // 1_000_000
        if not now < args.model_until_ms <= now + 45 * 60 * 1000:
            parser.error('Set an explicit future resource cutoff within 45 minutes')
        # Import only on opt-in. Construction never probes the provider.
        import asyncio
        from local_selection import CandidateSelector, SelectionConfig
        adapter = CandidateSelector(SelectionConfig(enabled=True, enabled_until_ms=args.model_until_ms,
                                                    model_id=args.model, max_calls=4, wall_budget_s=50))
        selector = lambda request: asyncio.run(adapter.select_candidate(request))
        budget = adapter.budget_status
        preflight = adapter.preflight
    args.db_path.parent.mkdir(parents=True, exist_ok=True)
    desk = FinalDesk(load_events(ROOT/'synthetic_match.jsonl'), args.db_path,
                     selector=selector, model_until_ms=args.model_until_ms, model_budget=budget, preflight=preflight)
    Handler.controller = desk
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    except BaseException:
        desk.close()
        raise
    print(f'Touchline Why http://127.0.0.1:{args.port}; local model opt-in={bool(selector)}; startup provider calls=0', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        desk.close()


if __name__ == '__main__':
    main()
