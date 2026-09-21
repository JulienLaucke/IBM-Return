import concurrent.futures
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
import uuid

from werkzeug.serving import make_server, WSGIRequestHandler
from server.app import create_app
from server.database import backup_database, connect
from server.security import digest, hash_password, verify_password

ROOT = Path(__file__).resolve().parent.parent
ORIGIN = 'https://returns.example'
TOKEN = 'test-only-setup-token-' * 3
USERS = [{'email': 'one@example.test', 'password': 'First-testing-password-12'},
         {'email': 'two@example.test', 'password': 'Second-testing-password-34'}]
COOKIE1 = '__Host-ibm_return=' + 'a' * 64
COOKIE2 = '__Host-ibm_return=' + 'b' * 64
LEGACY_ID = '12345678-1234-1234-1234-123456789abc'


class QuietHandler(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / 'returns.sqlite'
        db = sqlite3.connect(self.database)
        db.executescript((ROOT / 'tests/fixtures/legacy.sql').read_text())
        db.close()
        self.start()

    def start(self, setup_token=None):
        self.app = create_app(database=self.database, origin=ORIGIN, production=True,
                              setup_token=setup_token, static_dir=ROOT / 'dist')
        self.server = make_server('127.0.0.1', 0, self.app, threaded=True, request_handler=QuietHandler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def tearDown(self):
        self.stop()
        self.temp.cleanup()

    def call(self, path, method='GET', data=None, cookie=None, origin=ORIGIN, raw=None, content_type='application/json'):
        headers = {}
        if cookie:
            headers['Cookie'] = cookie
        if method not in ('GET', 'HEAD') and origin:
            headers['Origin'] = origin
        payload = raw if raw is not None else (json.dumps(data) if data is not None else None)
        if payload is not None:
            headers['Content-Type'] = content_type
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=15)
        conn.request(method, path, payload, headers)
        response = conn.getresponse()
        body = response.read()
        status, response_headers = response.status, dict(response.getheaders())
        conn.close()
        try:
            body = json.loads(body)
        except (ValueError, UnicodeError):
            pass
        return status, body, response_headers

    def test_legacy_database_sessions_and_passwords(self):
        self.assertEqual(self.call('/api/setup')[1], {'configured': True})
        self.assertEqual(self.call('/api/auth/me', cookie=COOKIE1)[1]['user']['email'], USERS[0]['email'])
        data = self.call('/api/shipments', cookie=COOKIE2)[1]['shipments'][0]
        self.assertEqual((data['id'], data['version'], data['tracking']), (LEGACY_ID, 3, 'TEST-TRACKING'))
        status, data, headers = self.call('/api/auth/login', 'POST', USERS[0])
        self.assertEqual(status, 200)
        for attribute in ['__Host-ibm_return=', 'HttpOnly', 'Secure', 'SameSite=Strict']:
            self.assertIn(attribute, headers['Set-Cookie'])
        backup = Path(self.temp.name) / 'before-python-backend.sqlite'
        with sqlite3.connect(backup) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT version FROM shipments').fetchone()[0], 3)
        self.stop()
        self.start()
        self.assertEqual(self.call('/api/auth/me', cookie=COOKIE2)[0], 200)
        self.assertEqual(self.call('/api/shipments', cookie=COOKIE1)[1]['shipments'][0]['version'], 3)

    def test_one_time_setup(self):
        self.stop()
        self.database = Path(self.temp.name) / 'fresh.sqlite'
        self.start(TOKEN)
        self.assertEqual(self.call('/api/setup')[1], {'configured': False})
        self.assertEqual(self.call('/api/setup', 'POST', {'token': 'wrong', 'users': USERS})[0], 403)
        self.assertEqual(self.call('/api/setup', 'POST', {'token': TOKEN, 'users': USERS + [USERS[0]]})[0], 400)
        self.assertEqual(self.call('/api/setup', 'POST', {'token': TOKEN, 'users': USERS})[0], 201)
        self.assertEqual(self.call('/api/setup', 'POST', {'token': TOKEN, 'users': USERS})[0], 409)
        self.assertEqual(self.call('/api/auth/login', 'POST', USERS[1])[0], 200)
        db = connect(self.database)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO users VALUES (3,'third@example.test','hash','now')")
            self.assertNotIn(USERS[0]['password'], str([tuple(r) for r in db.execute('SELECT * FROM users')]))
        finally:
            db.close()

    def draft(self):
        return dict(id=str(uuid.uuid4()), name='Synthetic example', carrier='FedEx',
                    reason='Gerätetausch (4 Jahre)', device='TEST', tracking='', shipped='2026-09-15', arrived='')

    def test_shared_crud_and_conflicts(self):
        draft = self.draft()
        self.assertEqual(self.call('/api/shipments', 'POST', draft)[0], 401)
        status, data, _ = self.call('/api/shipments', 'POST', draft, COOKIE1)
        self.assertEqual(status, 201)
        shipment = data['shipment']
        self.assertEqual(self.call('/api/shipments', 'POST', draft, COOKIE2)[0], 200)
        self.assertEqual(self.call('/api/shipments', 'POST', dict(draft, name='Other'), COOKIE2)[0], 409)
        changed = dict(shipment, arrived='2026-09-16')
        self.assertEqual(self.call('/api/shipments', 'PATCH', changed, COOKIE2)[1]['shipment']['version'], 2)
        self.assertEqual(self.call('/api/shipments', 'PATCH', changed, COOKIE1)[0], 409)
        self.assertEqual(self.call('/api/shipments', 'DELETE', dict(id=shipment['id'], version=1), COOKIE1)[0], 409)
        self.assertEqual(self.call('/api/shipments', 'DELETE', dict(id=shipment['id'], version=2), COOKIE1)[0], 200)

    def test_concurrent_writes(self):
        draft = self.draft()
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda c: self.call('/api/shipments', 'POST', draft, c)[0], [COOKIE1, COOKIE2]))
        self.assertEqual(sorted(results), [200, 201])
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda c: self.call('/api/shipments', 'PATCH', dict(draft, version=1, arrived='2026-09-16'), c)[0], [COOKIE1, COOKIE2]))
        self.assertEqual(sorted(results), [200, 409])

    def test_validation_and_request_limits(self):
        for extra in [{'arrived': '2026-09-14'}, {'shipped': '2026-02-30'}, {'name': '  '}, {'carrier': 'Other'}, {'reason': None}, {'id': 'bad'}, {'name': '\ud800'}]:
            self.assertEqual(self.call('/api/shipments', 'POST', dict(self.draft(), **extra), COOKIE1)[0], 400)
        self.assertEqual(self.call('/api/shipments', 'DELETE', {'id': LEGACY_ID, 'version': True}, COOKIE1)[0], 400)
        self.assertEqual(self.call('/api/auth/login', 'POST', raw='{')[0], 400)
        self.assertEqual(self.call('/api/auth/login', 'POST', raw='[]')[0], 400)
        self.assertEqual(self.call('/api/auth/login', 'POST', raw='{}', content_type='text/plain')[0], 415)
        self.assertEqual(self.call('/api/auth/login', 'POST', raw='x' * 17000)[0], 413)

    def test_password_logout_and_expiry(self):
        result = self.call('/api/auth/password', 'POST', {'currentPassword': USERS[0]['password'], 'newPassword': 'New-testing-password-56'}, COOKIE1)
        self.assertEqual(result[0], 200)
        fresh = result[2]['Set-Cookie'].split(';')[0]
        self.assertEqual(self.call('/api/auth/me', cookie=COOKIE1)[0], 401)
        self.assertEqual(self.call('/api/auth/login', 'POST', USERS[0])[0], 401)
        self.assertEqual(self.call('/api/auth/login', 'POST', dict(USERS[0], password='New-testing-password-56'))[0], 200)
        self.assertEqual(self.call('/api/auth/logout', 'POST', {}, fresh)[0], 200)
        self.assertEqual(self.call('/api/auth/me', cookie=fresh)[0], 401)
        db = connect(self.database)
        db.execute('UPDATE sessions SET expires=0 WHERE token_hash=?', (digest('b' * 64),))
        db.close()
        self.assertEqual(self.call('/api/auth/me', cookie=COOKIE2)[0], 401)

    def test_access_origin_headers_and_static_files(self):
        self.assertEqual(self.call('/api/shipments')[0], 401)
        self.assertEqual(self.call('/api/auth/logout', 'POST', {}, COOKIE1, origin=None)[0], 403)
        self.assertEqual(self.call('/api/auth/logout', 'POST', {}, COOKIE1, origin='https://other.example')[0], 403)
        for path in ['/.env', '/data/returns.sqlite', '/server/app.py', '/api/unknown', '/%2e%2e/README.md']:
            self.assertEqual(self.call(path)[0], 404)
        self.assertEqual(self.call('/api/register', 'POST', USERS[0])[0], 404)
        status, html, headers = self.call('/')
        self.assertEqual(status, 200)
        self.assertIn(b'IBM@Return', html)
        self.assertEqual(headers['X-Frame-Options'], 'DENY')
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertEqual(self.call('/', 'HEAD')[1], b'')
        self.assertEqual(self.call('/api/health')[1], {'ok': True})

    def test_throttling(self):
        for _ in range(11):
            result = self.call('/api/auth/login', 'POST', {'email': 'missing@example.test', 'password': 'wrong'})
        self.assertEqual(result[0], 429)
        self.assertEqual(result[2]['Retry-After'], '900')

    def test_backup_and_password_roundtrip(self):
        target = Path(self.temp.name) / 'backup.sqlite'
        backup_database(self.database, target)
        with self.assertRaises(FileExistsError):
            backup_database(self.database, target)
        with sqlite3.connect(target) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        password = 'Test-password-ä-🔒'
        self.assertTrue(verify_password(password, hash_password(password)))


if __name__ == '__main__':
    unittest.main()
