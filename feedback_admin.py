"""Private operator CLI; never import into a public HTTP handler.

Run against the approved private mounted data directory. No web admin route,
automatic alerts, external uploads, CSV exports or credentials on command lines.
Grant creation is an explicit owner operation after deployment approval.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import sqlite3
import sys
from hosted_app import Config, HostedService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True, type=Path)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('list')
    export = sub.add_parser('export')
    export.add_argument('--output', required=True, type=Path)
    triage = sub.add_parser('triage')
    triage.add_argument('id')
    triage.add_argument('status', choices=['new', 'reviewing', 'actioned', 'dismissed'])
    sub.add_parser('purge')
    grant = sub.add_parser('grant')
    grant.add_argument('--role', required=True, choices=['friend', 'judge'])
    grant.add_argument('--expires', required=True, help='Exact UTC ISO8601 expiry, after required judging availability')
    grant.add_argument('--max-sessions', required=True, type=int)
    revoke = sub.add_parser('revoke')
    revoke.add_argument('id')
    args = parser.parse_args()
    root = args.data_dir.resolve()
    path = root / 'playtest.sqlite3'
    if not path.is_file():
        parser.error('Private playtest database is absent; no resource or database was created')
    if args.action == 'grant':
        # This branch creates a credential only when an approved operator explicitly runs it.
        try:
            expiry_time = datetime.fromisoformat(args.expires.replace('Z', '+00:00'))
            if expiry_time.tzinfo is None or expiry_time.utcoffset().total_seconds() != 0:
                raise ValueError()
            expiry = int(expiry_time.timestamp())
        except ValueError:
            parser.error('Use an explicit UTC timestamp ending in Z or +00:00')
        judge_minimum = int(datetime(2026, 11, 11, 8, 0, tzinfo=timezone.utc).timestamp())
        if args.role == 'judge' and expiry < judge_minimum:
            parser.error('Judge access must last through 2026-11-11 07:59 UTC; allow a safety margin')
        if input('Type CREATE APPROVED ACCESS to create one controlled access grant: ') != 'CREATE APPROVED ACCESS':
            parser.error('No grant created')
        svc = HostedService(Config(root, 'https://operator-only.invalid'))
        try:
            code = secrets.token_urlsafe(32)
            grant_id = svc.add_grant(code, role=args.role, expires_at=expiry, max_sessions=args.max_sessions)
            print(json.dumps({'grant_id': grant_id, 'access_code_show_once': code, 'role': args.role, 'expires_at': expiry}))
        finally:
            svc.close()
        return
    if args.action in {'list', 'export'}:
        # Read-only open for owner review. Excludes cookie/access/CSRF/session identifiers.
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        db.row_factory = sqlite3.Row
        try:
            rows = [dict(row) for row in db.execute('SELECT id,created_at,clarity,usefulness,trust,role,comment,viewport,status FROM feedback ORDER BY created_at DESC')]
        finally:
            db.close()
        output = '\n'.join(json.dumps(row, ensure_ascii=False) for row in rows) + ('\n' if rows else '')
        if args.action == 'list':
            sys.stdout.write(output)
        else:
            target = args.output.resolve()
            if target == path or root in target.parents:
                parser.error('Choose a private export path outside the live data directory')
            # Exclusive create avoids accidentally replacing an earlier owner export.
            with target.open('x', encoding='utf-8') as stream:
                stream.write(output)
            print(json.dumps({'exported_feedback': len(rows), 'format': 'JSONL'}))
        return
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA secure_delete=ON')
        if args.action == 'triage':
            result = db.execute('UPDATE feedback SET status=? WHERE id=?', (args.status, args.id))
            print(json.dumps({'updated': result.rowcount}))
        elif args.action == 'revoke':
            result = db.execute('UPDATE grants SET disabled=1 WHERE id=?', (args.id,))
            print(json.dumps({'revoked': result.rowcount}))
        else:
            if input('Type DELETE PLAYTEST FEEDBACK to remove stored feedback: ') != 'DELETE PLAYTEST FEEDBACK':
                parser.error('Feedback was preserved')
            result = db.execute('DELETE FROM feedback')
            # Preserve bounded retry tombstones, but remove content-derived
            # hashes immediately. A delayed client retry must not recreate
            # private feedback the owner explicitly deleted.
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='feedback_requests'").fetchone():
                db.execute('UPDATE feedback_requests SET deleted=1,payload_hash=NULL')
            print(json.dumps({'deleted': result.rowcount, 'note': 'Provider snapshots, exports and volume disposal are separate owner retention tasks.'}))


if __name__ == '__main__':
    main()
