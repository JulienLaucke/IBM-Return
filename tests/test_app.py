import base64
import io
from PIL import Image
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
                db.execute("INSERT INTO users (id,email,password_hash,created) VALUES (3,'third@example.test','hash','now')")
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

    @staticmethod
    def photo(color='blue', fmt='PNG'):
        with Image.new('RGB', (80, 60), color) as image:
            data = io.BytesIO()
            image.save(data, format=fmt)
        mime = {'PNG': 'png', 'JPEG': 'jpeg', 'WEBP': 'webp'}[fmt]
        return 'data:image/' + mime + ';base64,' + base64.b64encode(data.getvalue()).decode()

    def test_optional_details_and_creator_profile(self):
        old = self.call('/api/shipments', cookie=COOKIE1)[1]['shipments'][0]
        self.assertEqual((old['model'], old['location'], old['imageUrl']), ('', '', ''))
        self.assertEqual(old['creatorEmail'], USERS[0]['email'])
        self.assertEqual(self.call('/api/auth/profile', 'POST', {'displayName': 'Julien'})[0], 401)
        self.assertEqual(self.call('/api/auth/profile', 'POST', {'displayName': 'Julien'}, COOKIE1, origin='https://other.example')[0], 403)
        self.assertEqual(self.call('/api/auth/profile', 'POST', {'displayName': 'Julien', 'id': 2}, COOKIE1)[0], 200)
        self.assertEqual(self.call('/api/auth/profile', 'POST', {'displayName': 'Georg'}, COOKIE2)[0], 200)
        self.assertEqual(self.call('/api/auth/me', cookie=COOKIE1)[1]['user']['displayName'], 'Julien')
        draft = dict(self.draft(), reason='Remote Onboarding', model='ThinkPad T14 Gen 4', location='Magdeburg', creator=1)
        item = self.call('/api/shipments', 'POST', draft, COOKIE2)[1]['shipment']
        self.assertEqual((item['creator'], item['creatorName']), (2, 'Georg'))
        for location in ['Frankfurt', 'Köln', 'München', '']:
            result = self.call('/api/shipments', 'PATCH', dict(item, location=location), COOKIE1)
            self.assertEqual(result[0], 200)
            item = result[1]['shipment']
            self.assertEqual((item['creatorName'], item['creator']), ('Georg', 2))
        self.assertEqual(self.call('/api/shipments', 'POST', dict(self.draft(), location='Berlin'), COOKIE1)[0], 400)
        self.assertEqual(self.call('/api/shipments', 'POST', dict(self.draft(), model='x' * 121), COOKIE1)[0], 400)
        # An older client does not clear details it does not know about.
        older = {key: value for key, value in item.items() if key not in ('model', 'location')}
        result = self.call('/api/shipments', 'PATCH', older, COOKIE1)
        self.assertEqual(result[1]['shipment']['model'], 'ThinkPad T14 Gen 4')
        self.stop()
        self.start()
        self.assertEqual(self.call('/api/auth/me', cookie=COOKIE2)[1]['user']['displayName'], 'Georg')
        self.assertTrue((Path(self.temp.name) / 'before-shipment-details.sqlite').is_file())

    def test_month_assignment_validation_and_shared_edits(self):
        old = self.call('/api/shipments', cookie=COOKIE1)[1]['shipments'][0]
        self.assertEqual(old['month'], '')
        self.assertEqual((old['shipped'], old['version']), ('2026-09-15', 3))
        draft = dict(self.draft(), reason='Remote Onboarding', month='2026-10')
        status, result, _ = self.call('/api/shipments', 'POST', draft, COOKIE1)
        self.assertEqual(status, 201)
        item = result['shipment']
        self.assertEqual((item['month'], item['shipped']), ('2026-10', '2026-09-15'))
        self.assertEqual(self.call('/api/shipments', 'POST', draft, COOKIE2)[0], 200)
        self.assertEqual(self.call('/api/shipments', 'POST', dict(draft, month='2026-11'), COOKIE2)[0], 409)
        # Older clients can record arrival without erasing the assigned month.
        older = {key: value for key, value in item.items() if key != 'month'}
        changed = self.call('/api/shipments', 'PATCH', dict(older, arrived='2026-09-20'), COOKIE2)[1]['shipment']
        self.assertEqual((changed['month'], changed['creator']), ('2026-10', 1))
        moved = self.call('/api/shipments', 'PATCH', dict(changed, month='2027-01'), COOKIE2)[1]['shipment']
        self.assertEqual(self.call('/api/shipments', 'PATCH', dict(changed, month=''), COOKIE1)[0], 409)
        self.stop()
        self.start()
        stored = next(row for row in self.call('/api/shipments', cookie=COOKIE1)[1]['shipments'] if row['id'] == item['id'])
        self.assertEqual(stored['month'], '2027-01')
        cleared = self.call('/api/shipments', 'PATCH', dict(moved, month=''), COOKIE1)[1]['shipment']
        self.assertEqual(cleared['month'], '')
        self.assertEqual(cleared['shipped'], draft['shipped'])
        for month in [None, 202610, {}, '2026-00', '2026-13', '2026-1', '0000-01', '2026-10-01', '2026-10\n']:
            with self.subTest(month=month):
                self.assertEqual(self.call('/api/shipments', 'POST', dict(self.draft(), month=month), COOKIE1)[0], 400)
        self.assertTrue((Path(self.temp.name) / 'before-shipment-months.sqlite').is_file())

    def test_month_migration_preserves_attachments(self):
        draft = dict(self.draft(), photo=self.photo(), pdf=self.pdf_attachment())
        item = self.call('/api/shipments', 'POST', draft, COOKIE1)[1]['shipment']
        photo = self.call(item['imageUrl'], cookie=COOKIE1)[1]
        pdf = self.call(item['pdfUrl'], cookie=COOKIE1)[1]
        self.stop()
        # Recreate the immediately preceding schema, which already had attachments.
        with sqlite3.connect(self.database) as db:
            db.execute('ALTER TABLE shipments DROP COLUMN month')
        backup = Path(self.temp.name) / 'before-shipment-months.sqlite'
        backup.unlink()
        self.start()
        migrated = next(row for row in self.call('/api/shipments', cookie=COOKIE2)[1]['shipments'] if row['id'] == item['id'])
        self.assertEqual(migrated, item)
        self.assertEqual(self.call(item['imageUrl'], cookie=COOKIE2)[1], photo)
        self.assertEqual(self.call(item['pdfUrl'], cookie=COOKIE2)[1], pdf)
        with sqlite3.connect(backup) as db:
            self.assertEqual(db.execute('SELECT data FROM shipment_pdfs').fetchone()[0], pdf)
            self.assertNotIn('month', [row[1] for row in db.execute('PRAGMA table_info(shipments)')])

    def test_image_lifecycle_access_and_atomic_updates(self):
        draft = dict(self.draft(), photo=self.photo())
        status, data, _ = self.call('/api/shipments', 'POST', draft, COOKIE1)
        self.assertEqual(status, 201)
        item = data['shipment']
        url = item['imageUrl']
        self.assertTrue(url)
        self.assertEqual(self.call(url)[0], 401)
        status, pixels, headers = self.call(url, cookie=COOKIE2)
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'image/jpeg')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        with Image.open(io.BytesIO(pixels)) as photo:
            self.assertEqual(photo.size, (80, 60))
            self.assertFalse(photo.getexif())
        self.assertEqual(self.call('/api/shipments', 'POST', draft, COOKIE1)[0], 200)
        self.assertEqual(self.call('/api/shipments', 'POST', dict(draft, photo=self.photo('red')), COOKIE2)[0], 409)
        changed = self.call('/api/shipments', 'PATCH', dict(item, photo=self.photo('red', 'WEBP')), COOKIE2)[1]['shipment']
        self.assertEqual(changed['creator'], 1)
        self.assertNotEqual(changed['imageUrl'], url)
        new_pixels = self.call(changed['imageUrl'], cookie=COOKIE1)[1]
        self.assertNotEqual(new_pixels, pixels)
        self.assertEqual(self.call('/api/shipments', 'PATCH', dict(item, photo=None), COOKIE1)[0], 409)
        self.assertEqual(self.call(changed['imageUrl'], cookie=COOKIE1)[1], new_pixels)
        # Omitted image keeps the stored photo across edits and restart.
        kept = self.call('/api/shipments', 'PATCH', dict(changed, tracking='updated'), COOKIE1)[1]['shipment']
        self.stop()
        self.start()
        self.assertEqual(self.call(kept['imageUrl'], cookie=COOKIE2)[1], new_pixels)
        removed = self.call('/api/shipments', 'PATCH', dict(kept, photo=None), COOKIE1)[1]['shipment']
        self.assertEqual(removed['imageUrl'], '')
        self.assertEqual(self.call(url, cookie=COOKIE2)[0], 404)
        added = self.call('/api/shipments', 'PATCH', dict(removed, photo=self.photo('green', 'JPEG')), COOKIE1)[1]['shipment']
        self.assertEqual(self.call('/api/shipments', 'DELETE', {'id': added['id'], 'version': added['version']}, COOKIE2)[0], 200)
        self.assertEqual(self.call(added['imageUrl'], cookie=COOKIE1)[0], 404)
        db = connect(self.database)
        try:
            self.assertEqual(db.execute('SELECT count(*) FROM shipment_images').fetchone()[0], 0)
        finally:
            db.close()

    def test_image_validation_and_metadata_removal(self):
        for photo in ['data:image/svg+xml;base64,PHN2Zy8+', 'data:image/png;base64,YmFk', {}, 'not-an-image']:
            self.assertEqual(self.call('/api/shipments', 'POST', dict(self.draft(), photo=photo), COOKIE1)[0], 400 if isinstance(photo, str) else 413)
        oversized = 'data:image/png;base64,' + base64.b64encode(b'x' * (5 * 1024 * 1024 + 1)).decode()
        self.assertEqual(self.call('/api/shipments', 'POST', dict(self.draft(), photo=oversized), COOKIE1)[0], 413)
        with Image.new('RGB', (1800, 300), 'yellow') as source:
            exif = Image.Exif()
            exif[315] = 'Synthetic private metadata'
            data = io.BytesIO()
            source.save(data, format='JPEG', exif=exif)
        photo = 'data:image/jpeg;base64,' + base64.b64encode(data.getvalue()).decode()
        item = self.call('/api/shipments', 'POST', dict(self.draft(), photo=photo), COOKIE1)[1]['shipment']
        with Image.open(io.BytesIO(self.call(item['imageUrl'], cookie=COOKIE2)[1])) as sanitized:
            self.assertLessEqual(max(sanitized.size), 1600)
            self.assertFalse(sanitized.getexif())
        self.assertEqual(len(self.call('/api/shipments', cookie=COOKIE1)[1]['shipments']), 2)

    @staticmethod
    def pdf_attachment(name='Versandlabel.pdf', padding=0):
        # A small valid one-page PDF with an xref table; no external fixture.
        objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
                   b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
                   b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>']
        content = b'%PDF-1.4\n'
        offsets = [0]
        for i, obj in enumerate(objects, 1):
            offsets.append(len(content))
            content += str(i).encode() + b' 0 obj\n' + obj + b'\nendobj\n'
        if padding:
            content += b'%' + b'x' * padding + b'\n'
        xref = len(content)
        content += b'xref\n0 4\n0000000000 65535 f \n'
        content += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
        content += f'trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
        return {'name': name, 'data': 'data:application/pdf;base64,' + base64.b64encode(content).decode()}

    def test_pdf_lifecycle_and_protected_download(self):
        attachment = self.pdf_attachment('Übergabe München.pdf')
        original = base64.b64decode(attachment['data'].split(',')[1])
        draft = dict(self.draft(), pdf=attachment, photo=self.photo())
        status, body, _ = self.call('/api/shipments', 'POST', draft, COOKIE1)
        self.assertEqual(status, 201)
        item = body['shipment']
        self.assertEqual(item['pdfName'], attachment['name'])
        self.assertTrue(item['imageUrl'])
        self.assertEqual(self.call(item['pdfUrl'])[0], 401)
        status, downloaded, headers = self.call(item['pdfUrl'], cookie=COOKIE2)
        self.assertEqual(status, 200)
        self.assertEqual(downloaded, original)
        self.assertEqual(headers['Content-Type'], 'application/pdf')
        self.assertIn('attachment;', headers['Content-Disposition'])
        self.assertIn("filename*=UTF-8''", headers['Content-Disposition'])
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(self.call('/api/shipments', 'POST', draft, COOKIE2)[0], 200)
        self.assertEqual(self.call('/api/shipments', 'POST', dict(draft, pdf=self.pdf_attachment('Other.pdf')), COOKIE2)[0], 409)
        kept = self.call('/api/shipments', 'PATCH', dict(item, tracking='updated'), COOKIE2)[1]['shipment']
        self.assertEqual(self.call(kept['pdfUrl'], cookie=COOKIE2)[1], original)
        replaced = self.call('/api/shipments', 'PATCH', dict(kept, pdf=self.pdf_attachment('Replacement.pdf')), COOKIE2)[1]['shipment']
        self.assertEqual(replaced['creator'], 1)
        self.assertNotEqual(replaced['pdfUrl'], kept['pdfUrl'])
        self.assertEqual(self.call('/api/shipments', 'PATCH', dict(kept, pdf=None), COOKIE1)[0], 409)
        self.assertEqual(self.call(replaced['pdfUrl'], cookie=COOKIE1)[0], 200)
        self.stop()
        self.start()
        self.assertEqual(self.call(replaced['pdfUrl'], cookie=COOKIE2)[1], original)
        removed = self.call('/api/shipments', 'PATCH', dict(replaced, pdf=None), COOKIE1)[1]['shipment']
        self.assertEqual((removed['pdfUrl'], removed['pdfName']), ('', ''))
        self.assertEqual(self.call(replaced['pdfUrl'], cookie=COOKIE2)[0], 404)
        self.assertEqual(self.call(removed['imageUrl'], cookie=COOKIE1)[0], 200)
        added = self.call('/api/shipments', 'PATCH', dict(removed, pdf=attachment), COOKIE1)[1]['shipment']
        self.assertEqual(self.call('/api/shipments', 'DELETE', {'id': added['id'], 'version': added['version']}, COOKIE1)[0], 200)
        self.assertEqual(self.call(added['pdfUrl'], cookie=COOKIE2)[0], 404)
        db = connect(self.database)
        try:
            self.assertEqual(db.execute('SELECT count(*) FROM shipment_pdfs').fetchone()[0], 0)
        finally:
            db.close()

    def test_pdf_validation_and_large_upload(self):
        old = self.call('/api/shipments', cookie=COOKIE1)[1]['shipments'][0]
        self.assertEqual((old['pdfName'], old['pdfUrl']), ('', ''))
        valid = self.pdf_attachment()
        for value in ['invalid', {'name': '../bad.pdf', 'data': valid['data']},
                      {'name': 'bad.pdf\r\nheader', 'data': valid['data']},
                      {'name': 'bad.html', 'data': valid['data']},
                      {'name': 'bad.pdf', 'data': self.photo()},
                      {'name': 'bad.pdf', 'data': 'data:application/pdf;base64,YmFk'}]:
            self.assertEqual(self.call('/api/shipments', 'POST', dict(self.draft(), pdf=value), COOKIE1)[0], 400)
        large = self.pdf_attachment(padding=8 * 1024 * 1024)
        result = self.call('/api/shipments', 'POST', dict(self.draft(), pdf=large, photo=self.photo()), COOKIE1)
        self.assertEqual(result[0], 201)
        self.assertGreater(len(self.call(result[1]['shipment']['pdfUrl'], cookie=COOKIE2)[1]), 8 * 1024 * 1024)
        oversized = self.pdf_attachment(padding=10 * 1024 * 1024)
        self.assertEqual(self.call('/api/shipments', 'POST', dict(self.draft(), pdf=oversized), COOKIE1)[0], 413)
        self.assertEqual(len(self.call('/api/shipments', cookie=COOKIE1)[1]['shipments']), 2)

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
