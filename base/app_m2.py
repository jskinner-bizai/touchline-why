"""Local producer and independent overlay consumer. M1 app.py remains unchanged."""
from __future__ import annotations

import copy
import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4

from overlay_state import OverlayState
from touchline_core import load_events

ROOT = Path(__file__).resolve().parent


def now_ms():
    return time.time_ns() // 1_000_000


class Controller:
    def __init__(self, events, *, selector=None, model_until_ms=0, max_calls=4, initial_calls=0, model_budget=None, clock=now_ms):
        self.events = copy.deepcopy(events)
        self.clock = clock
        self.lock = threading.RLock()
        self.stream_id = uuid4().hex
        self.sequence = 0
        self.fingerprint = None
        self.publication = None
        self.generation = 0
        self.view_generation = 0
        self.audience, self.language = 'casual', 'en'
        self.selector, self.model_until_ms = selector, model_until_ms
        self.real_calls = initial_calls
        self.max_calls = max_calls
        self.model_budget = model_budget
        self.job = {'status': 'idle'}
        self.history = []
        self.worker = None
        self.reset()

    def reset(self):
        # Rewind presentation time, never approved facts. Reapply canonical
        # accepted corrections in their original order to preserve CAS lineage
        # and exact correction-ID idempotence. Build off to the side so a failed
        # reapplication cannot partially replace the current engine.
        previous = getattr(self, 'engine', None)
        corrections = list(previous._corrections.values()) if previous else []
        engine = OverlayState(self.events, through_ms=0, ttl_ms=20000, selection_ttl_ms=15000, clock=self.clock)
        for encoded in corrections:
            engine.correct(json.loads(encoded))
        self.engine = engine
        # The browser delivery sequence survives a rewind; a new engine epoch
        # prevents an old model response winning an identical-digest ABA race.
        self.generation += 1
        self.view_generation += 1
        self.position = 0
        self.times = sorted({event['at_ms'] for event in self.events})
        self.history.append({'at_ms': self.clock(), 'action': 'reset'})

    def _publication(self):
        self.engine.tick()
        envelope = self.engine.view(self.audience, self.language)
        key = (envelope['engine_epoch'], envelope['overlay_version'], self.audience, self.language)
        if key != self.fingerprint:
            self.sequence += 1
            card = copy.deepcopy(envelope['card'])
            if self.language == 'es':
                companion = envelope.get('english_companion')
                card['translation_en'] = companion.get('text', '') if isinstance(companion, dict) else companion or ''
            teams = envelope['snapshot']['match']['teams']
            totals = envelope['snapshot']['stats']['total']['teams']
            previous_id = self.publication['overlay_id'] if self.publication else None
            self.publication = {
                'schema_version': 'touchline.overlay.v1', 'stream_id': self.stream_id,
                'sequence': self.sequence, 'overlay_id': f'{envelope["overlay_id"]}-{self.view_generation}',
                'fact_id': envelope['fact_id'], 'state_digest': envelope['state_digest'],
                'issued_at_ms': envelope['issued_at_ms'], 'expires_at_ms': envelope['expires_at_ms'],
                'event_time': {'through_ms': envelope['through_ms'], **envelope['window']},
                'retracts': [previous_id] if previous_id else [], 'card': card,
                'facts': {'score': {team['name']: totals[team['id']]['goals'] for team in teams}, 'through_ms': envelope['through_ms']},
                'provenance': {**copy.deepcopy(envelope['provenance']), 'engine_overlay_id': envelope['overlay_id'], 'engine_schema_version': envelope['schema_version']},
            }
            self.fingerprint = key
        return copy.deepcopy(self.publication), envelope

    def state(self):
        with self.lock:
            publication, envelope = self._publication()
            budget = self.model_budget() if self.model_budget else None
            available = self.selector is not None and self.clock() < self.model_until_ms and self.real_calls < self.max_calls
            if budget and budget['wall_spent_ms'] + 250 >= budget['wall_budget_ms']:
                available = False
            return {'publication': publication, 'envelope': envelope, 'model_job': copy.deepcopy(self.job), 'model_budget': budget,
                    'history': copy.deepcopy(self.history[-30:]), 'audience': self.audience, 'language': self.language,
                    'model_available': available,
                    'real_model_calls': self.real_calls, 'model_limit': self.max_calls,
                    'position': self.position, 'positions': len(self.times)}

    def control(self, value):
        with self.lock:
            if not isinstance(value, dict) or 'action' not in value:
                raise ValueError('An action is required')
            action = value['action']
            if action == 'view':
                if set(value) != {'action', 'audience', 'language'} or value['audience'] not in {'casual', 'analyst'} or value['language'] not in {'en', 'es'}:
                    raise ValueError('Unsupported view')
                if (self.audience, self.language) != (value['audience'], value['language']):
                    self.audience, self.language = value['audience'], value['language']
                    self.view_generation += 1
            elif set(value) != {'action'}:
                raise ValueError('Unexpected action fields')
            elif action == 'reset':
                self.reset()
            elif action == 'next':
                position = min(self.position + 1, len(self.times) - 1)
                self.engine.advance(self.times[position])
                self.position = position
            elif action == 'finish':
                # One bounded deterministic transition. The durable owner
                # commits this complete final state under the caller's ID.
                self.engine.advance(self.times[-1])
                self.position = len(self.times) - 1
            elif action == 'pattern':
                if self.engine.view()['through_ms'] > 50000:
                    self.reset()
                self.engine.advance(50000)
                self.position = self.times.index(50000)
            elif action == 'duplicate':
                self.engine.ingest([self.events[1]])
            elif action == 'correct':
                # A declared synthetic late correction changes the recorded goal
                # to a saved shot. Same correction ID/body is idempotent.
                event = copy.deepcopy(next(e for e in self.events if e['id'] == 'e010'))
                if event['type'] != 'shot' or not event['goal']:
                    raise ValueError('Fixture correction target changed')
                event['goal'] = False
                self.engine.correct({'correction_id': 'late-shot-review', 'target_event_id': 'e010', 'expected_revision': 1, 'replacement': event})
            elif action in {'infer', 'inject_timeout'}:
                self._begin(action == 'inject_timeout')
            else:
                raise ValueError('Unsupported action')
            self.history.append({'at_ms': self.clock(), 'action': action})
            return self.state()

    def _begin(self, injected):
        if self.worker and self.worker.is_alive():
            raise ValueError('One selection request is already active')
        if not injected and (self.selector is None or self.clock() >= self.model_until_ms or self.real_calls >= self.max_calls):
            raise ValueError('Live model window is disabled, expired or exhausted')
        request = self.engine.selection_request(self.audience, self.language)
        if not request['candidates']:
            raise ValueError('No current pattern candidate; advance to the pattern moment')
        generation, view_generation = self.generation, self.view_generation
        if not injected:
            self.real_calls += 1
        self.job = {'status': 'running', 'injected': injected, 'request_id': request['token_id'], 'started_at_ms': self.clock()}

        def run():
            try:
                if injected:
                    time.sleep(0.35)
                    result = {'status': 'timeout', 'selection': None, 'elapsed_ms': 350, 'injected': True, 'trace': [], 'note': 'Declared timeout injection; no model request'}
                else:
                    result = self.selector(copy.deepcopy(request))
            except Exception as error:
                result = {'status': 'model_error', 'selection': None, 'error_type': type(error).__name__, 'trace': []}
            with self.lock:
                # Validation and publish are atomic against correction/reset/view.
                if (generation, view_generation) != (self.generation, self.view_generation):
                    status = 'stale_rejected'
                else:
                    try:
                        if result.get('selection') is not None:
                            self.engine.apply_selection(request, result['selection'])
                            status = 'accepted'
                        else:
                            reason = 'timeout' if result.get('status') == 'timeout' else 'invalid_selection' if result.get('status') in {'invalid_output', 'invalid_selection', 'invalid_response'} else 'model_error'
                            self.engine.fail_selection(request, reason=reason)
                            status = reason
                    except (ValueError, RuntimeError):
                        status = 'stale_or_invalid_rejected'
                self.job = {'status': status, 'injected': injected, 'request_id': request['token_id'], 'finished_at_ms': self.clock(), 'result': result}
                self.history.append({'at_ms': self.clock(), 'action': 'selection_result', 'status': status, 'injected': injected})
                self._publication()

        self.worker = threading.Thread(target=run, name='touchline-bounded-selection', daemon=True)
        self.worker.start()


class Handler(BaseHTTPRequestHandler):
    controller: Controller

    def log_message(self, fmt, *args):
        pass

    def _host(self):
        return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}

    def _reply(self, status, data, content_type='application/json; charset=utf-8'):
        body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        for key, value in {'Content-Type': content_type, 'Content-Length': str(len(body)), 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"}.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._host():
            return self._reply(403, {'error': 'Loopback host required'})
        parsed = urlsplit(self.path)
        if parsed.query:
            return self._reply(400, {'error': 'No query parameters supported'})
        if parsed.path in {'/api/state', '/api/overlay'}:
            state = self.controller.state()
            return self._reply(200, state if parsed.path == '/api/state' else state['publication'])
        files = {'/': ('producer.html', 'text/html'), '/overlay.html': ('overlay.html', 'text/html'), '/m2.css': ('m2.css', 'text/css'), '/producer.js': ('producer.js', 'text/javascript'), '/overlay_client.js': ('overlay_client.js', 'text/javascript'), '/overlay_view.js': ('overlay_view.js', 'text/javascript')}
        if parsed.path not in files:
            return self._reply(404, {'error': 'Unknown route'})
        name, kind = files[parsed.path]
        return self._reply(200, (ROOT / name).read_bytes(), kind + '; charset=utf-8')

    def do_POST(self):
        origin = self.headers.get('Origin')
        allowed = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
        if not self._host() or origin not in allowed or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            return self._reply(403, {'error': 'Same-origin local control required'})
        if self.path != '/api/control':
            return self._reply(404, {'error': 'Unknown route'})
        try:
            if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
                raise ValueError('JSON required')
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 2048:
                raise ValueError('Bounded request required')
            def pairs(items):
                result = {}
                for key, value in items:
                    if key in result:
                        raise ValueError('Duplicate JSON key')
                    result[key] = value
                return result
            value = json.loads(self.rfile.read(length), object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
            state = self.controller.control(value)
        except (ValueError, UnicodeError, TypeError):
            return self._reply(400, {'error': 'Invalid or unavailable control action'})
        return self._reply(200, state)


def main():
    raise SystemExit('app_m2.py is a controller library, not a standalone app. '
                     'Run python app_m3.py --db-path <scratch-path> for the recorded demo.')


if __name__ == '__main__':
    main()
