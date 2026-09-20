"""stdlib HTTP + SSRF guard. No requests, no new deps — urllib does the job."""
from __future__ import annotations

import ipaddress
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

MAX_BYTES = 2_000_000
TIMEOUT = 15


class _RedirectCap(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        seen = getattr(req, "_redir", 0)
        if seen >= 3:
            return None
        out = super().redirect_request(req, fp, code, msg, headers, newurl)
        if out is not None:
            out._redir = seen + 1
        return out


_OPENER = urllib.request.build_opener(_RedirectCap)


def _guard(url: str) -> None:
    parts = urllib.parse.urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("http(s) URL with host required")
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(parts.hostname))
    except socket.gaierror as exc:
        raise ValueError("DNS failed") from exc
    if not ip.is_global:
        raise ValueError("non-public host blocked")
    # ponytail: resolve-then-connect TOCTOU (DNS rebinding) unhandled; pin DNS or add egress proxy if the threat model grows


def call(url: str, *, method: str = "GET", payload: dict | None = None,
         headers: dict | None = None, timeout: int = TIMEOUT) -> dict:
    """Never raises for transport issues; reports them. Raises ValueError only for SSRF-guard blocks."""
    start = time.time()
    _guard(url)
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"User-Agent": "REAVER/phase2", **(headers or {})})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with _OPENER.open(req, timeout=timeout) as res:
            body = res.read(MAX_BYTES + 1)
        truncated = len(body) > MAX_BYTES
        return {"http": 200, "body": body[:MAX_BYTES], "truncated": truncated,
                "ms": int((time.time() - start) * 1000)}
    except urllib.error.HTTPError as exc:
        return {"http": exc.code, "body": exc.read(MAX_BYTES), "truncated": False,
                "ms": int((time.time() - start) * 1000)}
    except Exception as exc:  # timeout, refused, reset — reported, never raised
        return {"http": 0, "body": b"", "error": type(exc).__name__,
                "ms": int((time.time() - start) * 1000)}


def json_body(res: dict) -> dict | list | None:
    try:
        return json.loads(res["body"].decode("utf-8", "replace"))
    except (ValueError, KeyError):
        return None
