"""Recorded claim-review advice over the existing durable broadcast desk.

No provider SDK is imported, configured, probed or called by this entry point.
Producer approval creates a transient copy draft, never an on-air publication.
"""
from __future__ import annotations

import argparse
import copy
from http.server import ThreadingHTTPServer
from pathlib import Path

from app_final import FinalDesk
from app_m3 import Handler, ROOT
from advisory_review import AdvisoryReview
from durable_controller import OPERATION_ID
from touchline_core import load_events


COPY_ACTIONS = frozenset({'review_copy', 'approve_copy', 'clear_copy'})


class AdvisoryDesk(FinalDesk):
    """One advisory service per desk; no shared tester/model/approval state."""

    def __init__(self, events, db_path, *, evidence_root=None):
        self.copy_review = AdvisoryReview(evidence_root or ROOT / 'evidence/claim-review')
        self.copy_operations = {}
        # No selector, cutoff, model budget or provider opt-in exists here.
        super().__init__(events, db_path)

    def state(self):
        with self.lock:
            state = super().state()
            state['copy_review'] = self.copy_review.state(state)
            return state

    def control(self, value):
        if (not isinstance(value, dict) or not isinstance(value.get('operation_id'), str)
                or not OPERATION_ID.fullmatch(value['operation_id'])):
            raise ValueError('Operation ID required')
        command = {key: copy.deepcopy(item) for key, item in value.items() if key != 'operation_id'}
        operation_id = value['operation_id']
        with self.lock:
            if command.get('action') not in COPY_ACTIONS:
                if operation_id in self.copy_operations:
                    raise ValueError('Operation ID belongs to a copy-review command')
                already_processed = operation_id in self.operations
                result = super().control(value)
                if command.get('action') in {'timeout', 'recover'} and not already_processed:
                    # A completed failure/recovery invalidates copy even if
                    # facts are unchanged. Validate the command first and keep
                    # retries idempotent; no publication-sequence binding.
                    self.copy_review.invalidate()
                    return self.state()
                return result
            if operation_id in self.operations or self.durable.operation_command(operation_id) is not None:
                raise ValueError('Operation ID belongs to an existing replay command')
            previous = self.copy_operations.get(operation_id)
            if previous is not None and previous != command:
                raise ValueError('Conflicting copy-review operation ID')
            # Read and validate current durable facts under the same lock used
            # for controls, then approve against that exact fresh context.
            current = super().state()
            self.copy_review.control(value, current)
            self.copy_operations[operation_id] = command
            if len(self.copy_operations) > 500:
                self.copy_operations.pop(next(iter(self.copy_operations)))
            return self.state()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8786)
    parser.add_argument('--db-path', type=Path, required=True)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Unprivileged port required')
    args.db_path.parent.mkdir(parents=True, exist_ok=True)
    desk = AdvisoryDesk(load_events(ROOT / 'synthetic_match.jsonl'), args.db_path)
    Handler.controller = desk
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    except BaseException:
        desk.close()
        raise
    print(f'Touchline Why http://127.0.0.1:{args.port}; recorded advisory only; live unavailable; provider calls=0', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        desk.close()


if __name__ == '__main__':
    main()
