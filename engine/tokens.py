"""Per-user MCP tokens. SQLite + sha256, stdlib only. Plaintext exists once: at issuance."""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time

from connectors.keys import ROOT

DEFAULT_CAP = 500  # authenticated requests/day ≈ a few prospect runs; requests, not runs (see below)


def _db_path() -> str:
    return os.environ.get("REAVER_DB", os.path.join(ROOT, "data", "reaver.db"))


def _db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_db_path()), exist_ok=True)
    con = sqlite3.connect(_db_path())
    con.execute("CREATE TABLE IF NOT EXISTS tokens "
                "(h TEXT PRIMARY KEY, label TEXT, cap INT, used INT, day TEXT, created REAL, revoked INT)")
    return con


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def issue(label: str, cap: int = DEFAULT_CAP) -> str:
    """Returns plaintext ONCE. Only the hash is stored — a DB leak issues nothing usable."""
    label = str(label or "")[:80] or "unlabeled"
    cap = max(1, min(int(cap or DEFAULT_CAP), 100000))
    plaintext = "rvr_" + secrets.token_urlsafe(32)
    digest = hashlib.sha256(plaintext.encode()).hexdigest()
    con = _db()
    try:
        con.execute("INSERT INTO tokens VALUES (?, ?, ?, 0, ?, ?, 0)",
                    (digest, label, cap, _today(), time.time()))
        con.commit()
    finally:
        con.close()
    return plaintext


def check(token: str, count: bool = True) -> tuple[bool, str]:
    """(allowed, reason). Day rolls over automatically; revoked is forever.
    count=False validates without burning quota (used by the OAuth consent step)."""
    digest = hashlib.sha256((token or "").encode()).hexdigest()
    con = _db()
    try:
        row = con.execute("SELECT label, cap, used, day, revoked FROM tokens WHERE h = ?",
                          (digest,)).fetchone()
        if row is None:
            return False, "unknown token"
        label, cap, used, day, revoked = row
        if revoked:
            return False, "revoked"
        if day != _today():
            con.execute("UPDATE tokens SET used = 0, day = ? WHERE h = ?", (_today(), digest))
            con.commit()
            used = 0
        if used >= cap:
            return False, "daily cap exhausted"
        if count:
            con.execute("UPDATE tokens SET used = used + 1 WHERE h = ?", (digest,))
            con.commit()
        return True, label
    finally:
        con.close()


def revoke(label_or_prefix: str) -> int:
    con = _db()
    try:
        cur = con.execute("UPDATE tokens SET revoked = 1 WHERE label = ? OR h LIKE ?",
                          (label_or_prefix, label_or_prefix + "%"))
        con.commit()
        return cur.rowcount
    finally:
        con.close()


def cap_of(digest: str) -> int:
    """Cap lookup by stored hash (for OAuth binding). 0 = unknown/revoked."""
    con = _db()
    try:
        row = con.execute("SELECT cap, revoked FROM tokens WHERE h = ?", (digest,)).fetchone()
        if row is None or row[1]:
            return 0
        return row[0]
    finally:
        con.close()


def usage() -> list[dict]:
    con = _db()
    try:
        rows = con.execute("SELECT label, cap, used, day, created, revoked FROM tokens ORDER BY created").fetchall()
        return [{"label": label, "cap": cap, "used": used, "day": day,
                 "revoked": bool(revoked)} for label, cap, used, day, _, revoked in rows]
    finally:
        con.close()
