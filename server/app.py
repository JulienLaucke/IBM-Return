import io
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
import re
import secrets
import time
from urllib.parse import urlsplit

from flask import Flask, Response, g, jsonify, request, send_file
from werkzeug.exceptions import HTTPException

from .database import connect, initialize, transaction
from .security import (digest, equal_secret, hash_password, normalize_email,
                       valid_email, valid_password, verify_password)
from .validation import ApiError, shipment_input, valid_version
from .images import image_input
from .attachments import pdf_input

FIELDS = 'id,name,carrier,reason,device,tracking,shipped,arrived,version,created,model,location,creator,month'
EDITABLE = ('name', 'carrier', 'reason', 'device', 'tracking', 'shipped', 'arrived', 'model', 'location', 'month')
SESSION_SECONDS = 8 * 60 * 60


def now_ms():
    return time.time_ns() // 1000000


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def create_app(*, database, origin, production=True, setup_token=None, static_dir):
    url = urlsplit(origin)
    if (url.scheme not in ('http', 'https') or not url.netloc or url.username or url.password
            or url.path or url.query or url.fragment or (production and url.scheme != 'https')):
        raise ValueError('APP_ORIGIN muss eine vollständige HTTPS-Origin ohne abschließenden Schrägstrich sein.')
    initialize(database)
    with connect(database) as initial:
        if not initial.execute('SELECT id FROM users LIMIT 1').fetchone() and (not isinstance(setup_token, str) or len(setup_token) < 32):
            initial.close()
            raise ValueError('Für die Ersteinrichtung ist SETUP_TOKEN mit mindestens 32 Zeichen erforderlich.')
    initial.close()
    app = Flask(__name__, static_folder=None)
    app.config.update(MAX_CONTENT_LENGTH=21 * 1024 * 1024, DATABASE=str(database))
    app.json.ensure_ascii = False
    cookie_name = '__Host-ibm_return' if production else 'ibm_return_dev'
    dummy_hash = hash_password(secrets.token_hex(24))
    root = Path(static_dir).resolve()

    def db():
        if 'database' not in g:
            g.database = connect(database)
        return g.database

    @app.teardown_appcontext
    def close_database(_error):
        connection = g.pop('database', None)
        if connection is not None:
            connection.close()

    def cleanup():
        db().execute('DELETE FROM sessions WHERE expires <= ?', (now_ms(),))
        db().execute('DELETE FROM rate_limits WHERE expires <= ?', (now_ms(),))

    def limited(key, limit):
        with transaction(db()):
            cleanup()
            hashed = digest(key)
            db().execute('INSERT INTO rate_limits (key,count,expires) VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1', (hashed, now_ms() + 15 * 60 * 1000))
            count = db().execute('SELECT count FROM rate_limits WHERE key=?', (hashed,)).fetchone()['count']
        if count > limit:
            raise ApiError('Zu viele Versuche. Bitte in 15 Minuten erneut versuchen.', 429)

    def require_session():
        token = request.cookies.get(cookie_name, '')
        user = None
        if re.fullmatch(r'[a-f0-9]{64}', token):
            user = db().execute('SELECT u.id,u.email,u.display_name,s.token_hash FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?', (digest(token), now_ms())).fetchone()
        if user is None:
            raise ApiError('Deine Sitzung ist abgelaufen. Bitte erneut anmelden.', 401)
        return user

    def body(*, attachments_allowed=False):
        if not request.headers.get('Content-Type', '').lower().startswith('application/json'):
            raise ApiError('JSON-Eingabe erforderlich.', 415)
        try:
            if not attachments_allowed and request.content_length and request.content_length > 16384:
                raise ApiError('Eingabe zu groß.', 413)
            raw = request.get_data()
            if not attachments_allowed and len(raw) > 16384:
                raise ApiError('Eingabe zu groß.', 413)
            value = json.loads(raw, parse_constant=lambda _v: (_ for _ in ()).throw(ValueError()))
        except (ValueError, UnicodeError):
            raise ApiError('Ungültige Eingabe.') from None
        if not isinstance(value, dict):
            raise ApiError('Ungültige Eingabe.')
        return value

    def set_cookie(response, token, age=SESSION_SECONDS):
        response.set_cookie(cookie_name, token, max_age=age, httponly=True, secure=production, samesite='Strict', path='/')
        return response

    def begin_session(user):
        # Caller holds the transaction that verified/updated the password hash.
        cleanup()
        db().execute('DELETE FROM sessions WHERE token_hash IN (SELECT token_hash FROM sessions WHERE user_id=? ORDER BY expires DESC LIMIT -1 OFFSET 4)', (user['id'],))
        token = secrets.token_hex(32)
        db().execute('INSERT INTO sessions (token_hash,user_id,expires) VALUES (?,?,?)', (digest(token), user['id'], now_ms() + SESSION_SECONDS * 1000))
        return set_cookie(jsonify(user={'email': user['email'], 'displayName': user['display_name']}), token)

    @app.before_request
    def check_request():
        if request.method not in ('GET', 'HEAD', 'POST', 'PATCH', 'DELETE'):
            raise ApiError('Methode nicht erlaubt.', 405)
        if request.method in ('POST', 'PATCH', 'DELETE') and request.headers.get('Origin') != origin:
            raise ApiError('Ungültiger Ursprung der Anfrage.', 403)

    @app.after_request
    def headers(response):
        response.headers.update({
            'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'same-origin',
            'X-Frame-Options': 'DENY', 'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'",
        })
        if production:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        if request.path.startswith('/api/') or response.status_code >= 400:
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(Exception)
    def handle_error(exc):
        if isinstance(exc, ApiError):
            status, message = exc.status, str(exc)
        elif isinstance(exc, HTTPException):
            status = exc.code or 500
            message = {404: 'Nicht gefunden.', 405: 'Methode nicht erlaubt.', 413: 'Eingabe zu groß.'}.get(status, 'Ungültige Anfrage.')
        else:
            logging.error('Request failed: %s', type(exc).__name__)
            status, message = 500, 'Die Anfrage konnte nicht verarbeitet werden. Bitte erneut versuchen.'
        response = jsonify(error=message)
        response.status_code = status
        if status == 429:
            response.headers['Retry-After'] = '900'
        return response

    @app.get('/api/health')
    def health():
        db().execute('SELECT 1').fetchone()
        return jsonify(ok=True)

    @app.route('/api/setup', methods=['GET', 'POST'])
    def setup():
        if request.method in ('GET', 'HEAD'):
            return jsonify(configured=bool(db().execute('SELECT id FROM users LIMIT 1').fetchone()))
        limited('setup:' + str(request.remote_addr), 8)
        if db().execute('SELECT id FROM users LIMIT 1').fetchone():
            raise ApiError('Die Einrichtung ist bereits abgeschlossen.', 409)
        raw = body()
        if not isinstance(raw.get('token'), str) or not setup_token or not equal_secret(raw['token'], setup_token):
            raise ApiError('Einrichtungsschlüssel ungültig.', 403)
        users = raw.get('users')
        if not isinstance(users, list) or len(users) != 2 or not all(isinstance(u, dict) for u in users):
            raise ApiError('Bitte genau zwei Konten einrichten.')
        users = [{'email': normalize_email(u.get('email')), 'password': u.get('password')} for u in users]
        if any(not valid_email(u['email']) or not valid_password(u['password']) for u in users) or users[0]['email'] == users[1]['email']:
            raise ApiError('Zwei unterschiedliche E-Mail-Adressen und Passwörter mit jeweils 12–128 Zeichen sind erforderlich.')
        hashes = [hash_password(u['password']) for u in users]
        with transaction(db()):
            if db().execute('SELECT id FROM users LIMIT 1').fetchone():
                raise ApiError('Die Einrichtung ist bereits abgeschlossen.', 409)
            for i, user in enumerate(users):
                db().execute('INSERT INTO users (id,email,password_hash,created) VALUES (?,?,?,?)', (i + 1, user['email'], hashes[i], timestamp()))
        return jsonify(ok=True), 201

    @app.post('/api/auth/login')
    def login():
        limited('login-peer:' + str(request.remote_addr), 30)
        raw = body()
        email = normalize_email(raw.get('email'))
        limited('login-email:' + email, 10)
        if not valid_email(email) or not isinstance(raw.get('password'), str):
            raise ApiError('E-Mail oder Passwort stimmt nicht.', 401)
        user = db().execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        valid = verify_password(raw['password'], user['password_hash'] if user else dummy_hash)
        with transaction(db()):
            if not user or not valid or db().execute('SELECT password_hash FROM users WHERE id=?', (user['id'],)).fetchone()['password_hash'] != user['password_hash']:
                raise ApiError('E-Mail oder Passwort stimmt nicht.', 401)
            db().execute('DELETE FROM rate_limits WHERE key=?', (digest('login-email:' + email),))
            response = begin_session(user)
        return response

    @app.get('/api/auth/me')
    def me():
        user = require_session()
        return jsonify(user={'email': user['email'], 'displayName': user['display_name']})

    @app.post('/api/auth/profile')
    def profile():
        user = require_session()
        name = body().get('displayName')
        if not isinstance(name, str) or len(name.strip()) > 80 or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in name):
            raise ApiError('Bitte einen Anzeigenamen mit maximal 80 Zeichen eingeben.')
        db().execute('UPDATE users SET display_name=? WHERE id=?', (name.strip(), user['id']))
        return jsonify(user={'email': user['email'], 'displayName': name.strip()})

    def shipment_result(row):
        result = dict(row)
        owner = db().execute('SELECT email,display_name FROM users WHERE id=?', (row['creator'],)).fetchone()
        result['creatorName'] = owner['display_name'] or owner['email']
        result['creatorEmail'] = owner['email']
        has_image = db().execute('SELECT 1 FROM shipment_images WHERE shipment_id=?', (row['id'],)).fetchone()
        result['imageUrl'] = f"/api/shipments/{row['id']}/image?v={row['version']}" if has_image else ''
        pdf = db().execute('SELECT name FROM shipment_pdfs WHERE shipment_id=?', (row['id'],)).fetchone()
        result['pdfUrl'] = f"/api/shipments/{row['id']}/pdf?v={row['version']}" if pdf else ''
        result['pdfName'] = pdf['name'] if pdf else ''
        return result

    @app.get('/api/shipments/<shipment_id>/image')
    def shipment_image(shipment_id):
        require_session()
        image = db().execute('SELECT data FROM shipment_images WHERE shipment_id=?', (shipment_id,)).fetchone()
        if not image:
            raise ApiError('Bild nicht gefunden.', 404)
        return Response(image['data'], content_type='image/jpeg', headers={'Content-Disposition': 'inline; filename="rechner.jpg"'})

    @app.get('/api/shipments/<shipment_id>/pdf')
    def shipment_pdf(shipment_id):
        require_session()
        pdf = db().execute('SELECT name,data FROM shipment_pdfs WHERE shipment_id=?', (shipment_id,)).fetchone()
        if not pdf:
            raise ApiError('PDF nicht gefunden.', 404)
        response = send_file(io.BytesIO(pdf['data']), mimetype='application/pdf',
                             download_name=pdf['name'], as_attachment=True,
                             conditional=False, etag=False, max_age=0)
        return response

    @app.post('/api/auth/logout')
    def logout():
        user = require_session()
        db().execute('DELETE FROM sessions WHERE token_hash=?', (user['token_hash'],))
        return set_cookie(jsonify(ok=True), '', 0)

    @app.post('/api/auth/password')
    def password():
        user = require_session()
        limited('password:' + str(user['id']), 10)
        raw = body()
        if not valid_password(raw.get('newPassword')) or not isinstance(raw.get('currentPassword'), str):
            raise ApiError('Das neue Passwort muss 12–128 Zeichen enthalten.')
        old = db().execute('SELECT password_hash FROM users WHERE id=?', (user['id'],)).fetchone()['password_hash']
        if not verify_password(raw['currentPassword'], old):
            raise ApiError('Das aktuelle Passwort stimmt nicht.')
        encoded = hash_password(raw['newPassword'])
        with transaction(db()):
            updated = db().execute('UPDATE users SET password_hash=? WHERE id=? AND password_hash=?', (encoded, user['id'], old))
            if not updated.rowcount:
                raise ApiError('Passwort wurde inzwischen geändert. Bitte erneut anmelden.', 409)
            db().execute('DELETE FROM sessions WHERE user_id=?', (user['id'],))
            response = begin_session(user)
        return response

    @app.route('/api/shipments', methods=['GET', 'POST', 'PATCH', 'DELETE'])
    def shipments():
        user = require_session()
        if request.method in ('GET', 'HEAD'):
            return jsonify(shipments=[shipment_result(row) for row in db().execute(f'SELECT {FIELDS} FROM shipments ORDER BY created DESC,id DESC')])
        raw = body(attachments_allowed=request.method in ('POST', 'PATCH'))
        if request.method == 'DELETE':
            if not isinstance(raw.get('id'), str) or not valid_version(raw.get('version')):
                raise ApiError('Ungültige Rücksendung.')
            if not db().execute('DELETE FROM shipments WHERE id=? AND version=?', (raw['id'], raw['version'])).rowcount:
                raise ApiError('Eintrag inzwischen geändert oder entfernt. Bitte die Liste aktualisieren.', 409)
            return jsonify(ok=True)
        # Older clients omit new optional fields: retain them on edits.
        if request.method == 'PATCH':
            previous = db().execute('SELECT model,location,month FROM shipments WHERE id=?', (raw.get('id') if isinstance(raw.get('id'), str) else '',)).fetchone()
            if previous:
                for key in ('model', 'location', 'month'):
                    raw.setdefault(key, previous[key])
        v = shipment_input(raw)
        photo = image_input(raw['photo']) if 'photo' in raw else None
        pdf = pdf_input(raw['pdf']) if 'pdf' in raw else None
        values = [v[key] for key in EDITABLE]
        status = 200
        with transaction(db()):
            if request.method == 'POST':
                existing = db().execute(f'SELECT {FIELDS} FROM shipments WHERE id=?', (v['id'],)).fetchone()
                if existing:
                    stored_photo = db().execute('SELECT data FROM shipment_images WHERE shipment_id=?', (v['id'],)).fetchone()
                    photo_conflict = 'photo' in raw and photo != (stored_photo['data'] if stored_photo else None)
                    stored_pdf = db().execute('SELECT name,data FROM shipment_pdfs WHERE shipment_id=?', (v['id'],)).fetchone()
                    pdf_conflict = 'pdf' in raw and pdf != (dict(stored_pdf) if stored_pdf else None)
                    if pdf_conflict or photo_conflict or any(v[key] != existing[key] for key in EDITABLE):
                        raise ApiError('Eintrag existiert bereits mit anderen Angaben.', 409)
                else:
                    db().execute('INSERT INTO shipments (name,carrier,reason,device,tracking,shipped,arrived,model,location,month,id,created,creator,updater) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (*values, v['id'], timestamp(), user['id'], user['id']))
                    status = 201
            else:
                if not valid_version(raw.get('version')):
                    raise ApiError('Ungültige Version.')
                result = db().execute('UPDATE shipments SET name=?,carrier=?,reason=?,device=?,tracking=?,shipped=?,arrived=?,model=?,location=?,month=?,updater=?,version=version+1 WHERE id=? AND version=?', (*values, user['id'], v['id'], raw['version']))
                if not result.rowcount:
                    raise ApiError('Dieser Eintrag wurde inzwischen geändert oder entfernt. Bitte die Liste aktualisieren.', 409)
            if 'photo' in raw:
                if photo is None:
                    db().execute('DELETE FROM shipment_images WHERE shipment_id=?', (v['id'],))
                else:
                    db().execute('INSERT INTO shipment_images (shipment_id,data) VALUES (?,?) ON CONFLICT(shipment_id) DO UPDATE SET data=excluded.data', (v['id'], photo))
            if 'pdf' in raw:
                if pdf is None:
                    db().execute('DELETE FROM shipment_pdfs WHERE shipment_id=?', (v['id'],))
                else:
                    db().execute('INSERT INTO shipment_pdfs (shipment_id,name,data) VALUES (?,?,?) ON CONFLICT(shipment_id) DO UPDATE SET name=excluded.name,data=excluded.data', (v['id'], pdf['name'], pdf['data']))
            result = shipment_result(db().execute(f'SELECT {FIELDS} FROM shipments WHERE id=?', (v['id'],)).fetchone())
        return jsonify(shipment=result), status

    @app.route('/', methods=['GET', 'POST', 'PATCH', 'DELETE'])
    @app.route('/<path:path>', methods=['GET', 'POST', 'PATCH', 'DELETE'])
    def static(path='index.html'):
        if path.startswith('api/'):
            raise ApiError('Nicht gefunden.', 404)
        if request.method not in ('GET', 'HEAD'):
            raise ApiError('Methode nicht erlaubt.', 405)
        file = (root / path).resolve()
        mime = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.woff2': 'font/woff2'}.get(file.suffix)
        if not file.is_relative_to(root) or not mime or not file.is_file() or path.startswith('api/'):
            raise ApiError('Nicht gefunden.', 404)
        response = Response(file.read_bytes(), content_type=mime)
        response.headers['Cache-Control'] = 'no-store' if file.suffix == '.html' else 'public, max-age=3600'
        return response

    return app
