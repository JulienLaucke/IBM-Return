import getpass
import os
from pathlib import Path
import sys
from dotenv import load_dotenv
from .database import connect, transaction
from .security import hash_password, normalize_email, valid_password


def main():
    if not sys.stdin.isatty():
        raise SystemExit('Bitte in einem interaktiven Terminal ausführen.')
    load_dotenv()
    database = Path(os.environ.get('DATA_DIR', 'data')) / 'returns.sqlite'
    if not database.is_file():
        raise SystemExit('Datenbank nicht gefunden.')
    email = normalize_email(input('E-Mail des bestehenden Kontos: '))
    password = getpass.getpass('Neues Passwort (Eingabe verborgen): ')
    if not valid_password(password):
        raise SystemExit('Passwort muss 12–128 Zeichen enthalten.')
    db = connect(database)
    try:
        user = db.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone()
        if not user:
            raise SystemExit('Dieses Konto existiert nicht.')
        encoded = hash_password(password)
        with transaction(db):
            db.execute('UPDATE users SET password_hash=? WHERE id=?', (encoded, user['id']))
            db.execute('DELETE FROM sessions WHERE user_id=?', (user['id'],))
        print('Passwort geändert. Bestehende Sitzungen wurden abgemeldet.')
    finally:
        db.close()


if __name__ == '__main__':
    main()
