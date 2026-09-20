"""sqlite3 key-value cache with TTL. stdlib only. DB file is gitignored."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time

from connectors.keys import ROOT

DB = os.path.join(ROOT, "data", "reaver.db")


def _db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT, exp REAL)")
    return con


def get(key: str) -> object | None:
    con = _db()
    try:
        row = con.execute("SELECT v, exp FROM kv WHERE k = ?", (key,)).fetchone()
        if row is None:
            return None
        value, exp = row
        if exp < time.time():
            con.execute("DELETE FROM kv WHERE k = ?", (key,))
            con.commit()
            return None
        return json.loads(value)
    finally:
        con.close()


def put(key: str, value: object, ttl_seconds: int) -> None:
    con = _db()
    try:
        con.execute("REPLACE INTO kv (k, v, exp) VALUES (?, ?, ?)",
                    (key, json.dumps(value), time.time() + ttl_seconds))
        con.commit()
    finally:
        con.close()


def make_key(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()
