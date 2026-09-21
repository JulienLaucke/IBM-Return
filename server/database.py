"""SQLite access without schema changes to existing installations."""
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY CHECK(id IN (1,2)), email TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password_hash TEXT NOT NULL, created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 expires INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS rate_limits (key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS shipments (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, carrier TEXT NOT NULL, reason TEXT NOT NULL,
 device TEXT NOT NULL, tracking TEXT NOT NULL, shipped TEXT NOT NULL, arrived TEXT NOT NULL,
 version INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL,
 creator INTEGER NOT NULL REFERENCES users(id), updater INTEGER NOT NULL REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS shipments_created ON shipments(created);
'''


def connect(path):
    db = sqlite3.connect(str(path), timeout=5, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA synchronous=FULL')
    return db


@contextmanager
def transaction(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.execute('COMMIT')
    except BaseException:
        db.execute('ROLLBACK')
        raise


def backup_database(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file():
        raise ValueError('Datenbank nicht gefunden.')
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Exclusive creation protects existing backups from replacement.
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src:
            with sqlite3.connect(destination) as target:
                src.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Die Sicherung konnte nicht geprüft werden.')
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    finally:
        if 'src' in locals():
            src.close()
        if 'target' in locals():
            target.close()


def initialize(path):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # A single Gunicorn worker initializes the database before accepting requests.
    backup = path.parent / 'before-python-backend.sqlite'
    if path.is_file() and not backup.exists():
        backup_database(path, backup)
    db = connect(path)
    try:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript(SCHEMA)
        os.chmod(path, 0o600)
    finally:
        db.close()
