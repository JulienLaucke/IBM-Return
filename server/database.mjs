import { DatabaseSync } from 'node:sqlite';
import { mkdirSync, chmodSync } from 'node:fs';
import { dirname } from 'node:path';
export function openDatabase(file) {
  if (file !== ':memory:') mkdirSync(dirname(file), { recursive: true, mode: 0o700 });
  const db = new DatabaseSync(file, { timeout: 5000 });
  db.exec('PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;');
  if (file !== ':memory:') chmodSync(file, 0o600);
  db.exec(`CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY CHECK(id IN (1,2)), email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL, created TEXT NOT NULL
  );
  CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires INTEGER NOT NULL
  );
  CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
  CREATE TABLE IF NOT EXISTS rate_limits (
    key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires INTEGER NOT NULL
  );
  CREATE TABLE IF NOT EXISTS shipments (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, carrier TEXT NOT NULL, reason TEXT NOT NULL,
    device TEXT NOT NULL, tracking TEXT NOT NULL, shipped TEXT NOT NULL, arrived TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL,
    creator INTEGER NOT NULL REFERENCES users(id), updater INTEGER NOT NULL REFERENCES users(id)
  );
  CREATE INDEX IF NOT EXISTS shipments_created ON shipments(created);`);
  return db;
}
