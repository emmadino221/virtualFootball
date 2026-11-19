"""Licence keys issued from the website's owner section.

Keys in VALID_KEYS (the environment) never expire. Keys issued on the website are stored here
as SHA-256 hashes with an expiry time, so access can be granted, extended and revoked without
editing the environment or restarting the service. The plain key is never stored here.
"""
import hashlib
import sqlite3
from contextlib import contextmanager
import threading
import time


def key_hash(key):
    return hashlib.sha256(f"virtual-licence-v1:{key}".encode()).hexdigest()


class Licences:
    def __init__(self, db_path, clock=time.time):
        self.db_path = str(db_path)
        self.clock = clock
        self.lock = threading.Lock()
        self.cache = {}            # hash -> (expires_at_seconds, revoked)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS extension_licences (
                key_hash TEXT PRIMARY KEY, account TEXT NOT NULL, expires_at REAL NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL)""")
        self.reload()

    @contextmanager
    def _connect(self):
        # Commit and always close: "with sqlite3.connect()" alone leaves the connection open.
        db = sqlite3.connect(self.db_path, timeout=20)
        try:
            with db:
                yield db
        finally:
            db.close()

    def reload(self):
        with self._connect() as db:
            rows = db.execute("SELECT key_hash, expires_at, revoked FROM extension_licences").fetchall()
        with self.lock:
            self.cache = {h: (expires, bool(revoked)) for h, expires, revoked in rows}

    def is_valid(self, key):
        if not isinstance(key, str) or not key:
            return False
        with self.lock:
            entry = self.cache.get(key_hash(key))
        return bool(entry) and not entry[1] and entry[0] > self.clock()

    def grant(self, key, account, expires_at):
        """Create or extend a licence; expires_at is in seconds since the epoch."""
        if not isinstance(key, str) or not 16 <= len(key) <= 200:
            raise ValueError("Invalid licence key.")
        if not isinstance(expires_at, (int, float)) or expires_at <= self.clock():
            raise ValueError("The expiry must be in the future.")
        hashed, now = key_hash(key), self.clock()
        with self._connect() as db:
            db.execute("""INSERT INTO extension_licences VALUES (?,?,?,0,?)
                ON CONFLICT(key_hash) DO UPDATE SET account=excluded.account, expires_at=excluded.expires_at,
                revoked=0, updated_at=excluded.updated_at""", (hashed, str(account)[:254], float(expires_at), now))
        with self.lock:
            self.cache[hashed] = (float(expires_at), False)

    def revoke(self, key):
        hashed = key_hash(key)
        with self._connect() as db:
            db.execute("UPDATE extension_licences SET revoked=1, updated_at=? WHERE key_hash=?", (self.clock(), hashed))
        with self.lock:
            if hashed in self.cache:
                self.cache[hashed] = (self.cache[hashed][0], True)
