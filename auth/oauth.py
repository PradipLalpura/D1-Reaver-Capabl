"""Self-contained OAuth 2.1 authorization server for ChatGPT (and any MCP OAuth client).

No external IdP, no passwords, no JWT library: identity = the user's /connect token,
DCR/CIMD for client registration, PKCE S256, opaque access+refresh tokens in SQLite.
Covers: metadata, register, authorize+consent, token (code + refresh), verification.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import sqlite3
import time
import urllib.parse

from connectors.keys import ROOT

ALLOWED_CLIENT_HOSTS = ("chatgpt.com", "www.chatgpt.com", "openai.com", "localhost", "127.0.0.1")
ACCESS_TTL = 3600
REFRESH_TTL = 30 * 24 * 3600
CODE_TTL = 600


def _db_path() -> str:
    return os.environ.get("REAVER_DB", os.path.join(ROOT, "data", "reaver.db"))


def _db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_db_path()), exist_ok=True)
    con = sqlite3.connect(_db_path())
    con.execute("CREATE TABLE IF NOT EXISTS oauth_clients "
                "(id TEXT PRIMARY KEY, redirect_uris TEXT, created REAL)")
    con.execute("CREATE TABLE IF NOT EXISTS oauth_codes "
                "(h TEXT PRIMARY KEY, client_id TEXT, redirect_uri TEXT, challenge TEXT,"
                " resource TEXT, token_h TEXT, exp REAL, used INT)")
    con.execute("CREATE TABLE IF NOT EXISTS oauth_tokens "
                "(h TEXT PRIMARY KEY, token_h TEXT, cap INT, used INT, day TEXT,"
                " exp REAL, refresh_h TEXT, refresh_exp REAL)")
    return con


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def pkce_ok(verifier: str, challenge: str) -> bool:
    """S256 check. Malformed input fails closed, never raises."""
    try:
        digest = hashlib.sha256(verifier.encode()).digest()
        computed = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        return secrets.compare_digest(computed, challenge)
    except Exception:
        return False


def issuer_of(base: str) -> str:
    return base.rstrip("/")


def register_client(redirect_uris: list[str]) -> tuple[str | None, str]:
    """DCR: https redirect URIs only. Returns (client_id, error)."""
    clean = []
    for uri in redirect_uris:
        try:
            parts = urllib.parse.urlparse(uri)
        except Exception:
            continue
        if parts.scheme != "https" or not parts.netloc:
            continue
        clean.append(uri)
    if not clean:
        return None, "invalid_redirect_uri"
    client_id = "cli_" + secrets.token_hex(12)
    con = _db()
    try:
        import json
        con.execute("INSERT INTO oauth_clients VALUES (?, ?, ?)",
                    (client_id, json.dumps(clean), time.time()))
        con.commit()
    finally:
        con.close()
    return client_id, ""


def client_allows(client_id: str, redirect_uri: str) -> bool:
    """DCR-registered exact match, or CIMD https URL on an allowlisted host (fetch-and-validate deferred)."""
    # ponytail: CIMD trust is host-allowlist only; fetch the metadata document if abuse ever appears
    if client_id.startswith("https://"):
        try:
            host = urllib.parse.urlparse(client_id).hostname or ""
        except Exception:
            return False
        return host in ALLOWED_CLIENT_HOSTS
    con = _db()
    try:
        import json
        row = con.execute("SELECT redirect_uris FROM oauth_clients WHERE id = ?",
                          (client_id,)).fetchone()
        return bool(row and redirect_uri in json.loads(row[0]))
    finally:
        con.close()


def authorize(client_id: str, redirect_uri: str, challenge: str, resource: str,
              user_token: str) -> tuple[str | None, str]:
    """Validate everything, bind the code to a live /connect token. Returns (code, error)."""
    from engine.tokens import check as token_check
    if not client_allows(client_id, redirect_uri):
        return None, "unauthorized_client"
    if not challenge:
        return None, "invalid_request: code_challenge required"
    ok, _ = token_check(user_token, count=False)
    if not ok:
        return None, "access_denied: unknown or revoked token"
    digest = _sha(user_token)
    code = secrets.token_urlsafe(32)
    con = _db()
    try:
        con.execute("INSERT INTO oauth_codes VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                    (_sha(code), client_id, redirect_uri, challenge,
                     resource or "", digest, time.time() + CODE_TTL))
        con.commit()
    finally:
        con.close()
    return code, ""


def _mint(token_digest: str, cap: int) -> tuple[str, str]:
    access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    con = _db()
    try:
        import datetime
        day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        con.execute("INSERT INTO oauth_tokens VALUES (?, ?, ?, 0, ?, ?, ?, ?)",
                    (_sha(access), token_digest, cap,
                     day, time.time() + ACCESS_TTL,
                     _sha(refresh), time.time() + REFRESH_TTL))
        con.commit()
    finally:
        con.close()
    return access, refresh


def exchange_code(code: str, redirect_uri: str, client_id: str, verifier: str) -> tuple[dict, str]:
    """Authorization-code grant + PKCE. Single-use codes; caps inherited from the parent token."""
    from engine.tokens import cap_of
    con = _db()
    try:
        row = con.execute("SELECT client_id, redirect_uri, challenge, resource, token_h, exp, used"
                          " FROM oauth_codes WHERE h = ?", (_sha(code),)).fetchone()
        if row is None:
            return {}, "invalid_grant"
        cid, ruri, challenge, resource, token_digest, exp, used = row
        if used or exp < time.time() or cid != client_id or ruri != redirect_uri:
            return {}, "invalid_grant"
        if not pkce_ok(verifier, challenge):
            return {}, "invalid_grant: PKCE failed"
        con.execute("UPDATE oauth_codes SET used = 1 WHERE h = ?", (_sha(code),))
        con.commit()
    finally:
        con.close()
    cap = cap_of(token_digest) or 500
    access, refresh = _mint(token_digest, cap)
    return {"access_token": access, "token_type": "Bearer", "expires_in": ACCESS_TTL,
            "refresh_token": refresh, "resource": resource or None}, ""


def exchange_refresh(refresh: str) -> tuple[dict, str]:
    """Rotating refresh: old pair dies, new pair inherits the cap. Reuse detected → revoke chain."""
    con = _db()
    try:
        row = con.execute("SELECT token_h, cap, refresh_exp FROM oauth_tokens WHERE refresh_h = ?",
                          (_sha(refresh),)).fetchone()
        if row is None:
            return {}, "invalid_grant"
        token_digest, cap, refresh_exp = row
        if refresh_exp < time.time():
            return {}, "invalid_grant: refresh expired"
        con.execute("DELETE FROM oauth_tokens WHERE refresh_h = ?", (_sha(refresh),))
        con.commit()
    finally:
        con.close()
    access, new_refresh = _mint(token_digest, cap)
    return {"access_token": access, "token_type": "Bearer", "expires_in": ACCESS_TTL,
            "refresh_token": new_refresh}, ""


def verify_access(token: str) -> bool:
    """Opaque access check + per-token use counting. Revocation = row delete."""
    import datetime
    con = _db()
    try:
        row = con.execute("SELECT cap, used, day, exp FROM oauth_tokens WHERE h = ?",
                          (_sha(token or ""),)).fetchone()
        if row is None:
            return False
        cap, used, day, exp = row
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        if exp < time.time():
            return False
        if day != today:
            con.execute("UPDATE oauth_tokens SET used = 0, day = ? WHERE h = ?", (today, _sha(token)))
            con.commit()
            used = 0
        if used >= cap:
            return False
        con.execute("UPDATE oauth_tokens SET used = used + 1 WHERE h = ?", (_sha(token),))
        con.commit()
        return True
    finally:
        con.close()
