"""Actual loopback HTTP integration with synthetic local-only access grants.

Creates no external resources or production credentials. Separate from TLS,
cloud filesystem, actual browser/device, assistive-technology and user testing.
"""
from __future__ import annotations
import dataclasses
import http.client
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hosted_app import BoundedServer, Config, HostedService


def main():
    results = []
    with tempfile.TemporaryDirectory(prefix='touchline-http-integration-') as temp:
        service = HostedService(Config(Path(temp), 'http://127.0.0.1:8896', allow_local_http=True))
        server = BoundedServer(('127.0.0.1', 0), service)
        origin = f'http://127.0.0.1:{server.server_port}'
        service.config = dataclasses.replace(service.config, origin=origin)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(method, path, payload=None, cookie=None, csrf=None, headers=None, raw=None):
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=4)
            body = json.dumps(payload) if payload is not None else raw
            values = {'Host': f'127.0.0.1:{server.server_port}'}
            if method in {'POST', 'DELETE'}:
                values['Origin'] = origin
            if body is not None:
                values['Content-Type'] = 'application/json'
            if cookie:
                values['Cookie'] = cookie
            if csrf:
                values['X-CSRF-Token'] = csrf
            values.update(headers or {})
            conn.request(method, path, body=body, headers=values)
            response = conn.getresponse()
            status, response_headers, data = response.status, dict(response.getheaders()), response.read()
            conn.close()
            try:
                data = json.loads(data)
            except (ValueError, UnicodeError):
                data = data.decode('utf-8', errors='replace')
            return status, response_headers, data
        def check(label, condition):
            if not condition:
                raise AssertionError(label)
            results.append(label)
        try:
            status, headers, landing = request('GET', '/')
            check('public landing and CSP without signup', status == 200 and 'Content-Security-Policy' in headers and 'Access code' in landing)
            check('health ready minimal only', request('GET', '/healthz')[2]['mode'] == 'synthetic-recorded')
            for path in ['/playtest', '/api/state', '/api/session']:
                check('unauthenticated ' + path, request('GET', path)[0] == 401)
            for path in ['/admin', '/api/feedback', '/api/export', '/base/synthetic_match.jsonl', '/.env']:
                check('no private GET route ' + path, request('GET', path)[0] == 404)
            check('host validation', request('GET', '/', headers={'Host': 'attacker.invalid'})[0] == 403)
            code = 'synthetic-http-test-access-never-deploy-' + uuid4().hex
            service.add_grant(code, expires_at=int(time.time()) + 3600)
            check('cross-origin login blocked', request('POST', '/api/access', {'code': code}, headers={'Origin': 'https://attacker.invalid'})[0] == 403)
            check('oversized body rejected before auth allocation', request('POST', '/api/access', raw=' ' * 17000)[0] == 413)
            check('duplicate JSON fields rejected', request('POST', '/api/access', raw='{"code":"a","code":"b"}')[0] == 400)
            users = []
            for i in range(2):
                status, headers, body = request('POST', '/api/access', {'code': code})
                check(f'login {i} gives HttpOnly SameSite cookie', status == 200 and 'HttpOnly' in headers['Set-Cookie'] and 'SameSite=Strict' in headers['Set-Cookie'])
                users.append((headers['Set-Cookie'].split(';')[0], body['csrf']))
            def control(user, action, **extra):
                return request('POST', '/api/control', {'action': action, 'operation_id': uuid4().hex, **extra}, cookie=user[0], csrf=user[1])
            a, b = users
            check('authenticated playtest page', request('GET', '/playtest', cookie=a[0])[0] == 200)
            check('missing CSRF blocked', request('POST', '/api/control', {'action':'pattern','operation_id':uuid4().hex}, cookie=a[0])[0] == 403)
            pattern_a = control(a, 'pattern')[2]
            review_a = control(a, 'review_copy', case_id='P03')[2]
            advice_a = review_a['copy_review']['advice']
            check('recorded advisory remains unapproved', review_a['copy_review']['producer_copy_draft'] is None and review_a['copy_review']['live_available'] is False)
            check('public advice redacts binding and wire data', 'binding' not in advice_a and 'observed' not in advice_a and 'budget' not in advice_a)
            control(b, 'pattern')
            review_b = control(b, 'review_copy', case_id='P03')[2]
            check('advice IDs are scoped to each tester', advice_a['advice_id'] != review_b['copy_review']['advice']['advice_id'])
            check('another tester cannot approve a foreign advice ID', control(b, 'approve_copy', advice_id=advice_a['advice_id'])[0] == 409)
            approved_a = control(a, 'approve_copy', advice_id=advice_a['advice_id'])[2]
            check('explicit approval creates only a producer draft', approved_a['copy_review']['producer_copy_draft']['on_air'] is False and approved_a['publication'] == pattern_a['publication'])
            check('approval does not cross tester sessions', request('GET', '/api/state', cookie=b[0])[2]['copy_review']['producer_copy_draft'] is None)
            corrected = control(a, 'correct')[2]
            check('correction clears obsolete advice and approval', corrected['copy_review']['advice'] is None and corrected['copy_review']['producer_copy_draft'] is None)
            check('stale HTTP approval rejected', control(a, 'approve_copy', advice_id=advice_a['advice_id'])[0] == 409)
            reviewed_correction = control(a, 'review_copy', case_id='P04')[2]
            correction_advice = reviewed_correction['copy_review']['advice']
            check('model failure and deterministic correction explanation stay separate', correction_advice['raw_reason'] == 'contradicted_fact' and correction_advice['deterministic_classification']['reason'] == 'stale_revision')
            check('original strict NO_GO preserved', reviewed_correction['copy_review']['evaluation']['status'] == 'NO_GO' and reviewed_correction['copy_review']['evaluation']['strict_passes'] == 3)
            check('no hosted live inference route', control(a, 'infer')[0] == 400)
            other = control(b, 'pattern')[2]
            check('two HTTP users isolated', corrected['publication']['facts']['score']['Harbor Owls'] == 0 and other['publication']['facts']['score']['Harbor Owls'] == 1)
            check('no path injection', control(a, 'view', audience='casual', language='en', db_path='../other.sqlite3')[0] == 409)
            payload = {'feedback_id':uuid4().hex,'consent':True,'ratings':{'clarity':4,'usefulness':4,'trust':5},'role':'both','comment':'Synthetic HTTP check only.','viewport':'phone'}
            check('consented feedback stored privately', request('POST','/api/feedback',payload,cookie=a[0],csrf=a[1])[0] == 201)
            check('feedback cannot be listed by another tester', request('GET','/api/feedback',cookie=b[0])[0] == 404)
            request('DELETE','/api/feedback',cookie=b[0],csrf=b[1])
            with service.db() as db:
                check('other tester cannot delete feedback', db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0] == 1)
            request('DELETE','/api/feedback',cookie=a[0],csrf=a[1])
            with service.db() as db:
                check('own feedback deletion works', db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0] == 0)
            check('logout revokes server session', request('POST','/api/logout',{},cookie=a[0],csrf=a[1])[0] == 200 and request('GET','/api/state',cookie=a[0])[0] == 401)
            check('static assets served', all(request('GET',path)[0] == 200 for path in ['/static/site.css','/static/landing.js','/static/playtest.js']))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)
            service.close()
    print(json.dumps({'passed':len(results),'checks':results,'external_requests':0,'model_calls':0,'production_grants':0,'scope':'Actual loopback HTTP; no TLS/cloud/browser/device/user outcome proof'}, indent=2))


if __name__ == '__main__':
    main()
