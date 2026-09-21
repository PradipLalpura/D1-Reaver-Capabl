"""REAVER Playground: landing + BYOK interface over the SAME engine. stdlib only.

Security: session keys live in server memory (30-min TTL), never touch disk/logs/client
beyond the password field that supplied them; every response is scanned for key leakage
before send (defense in depth — keys should never be in a response body at all).
"""
from __future__ import annotations

import html
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

SESSION_TTL = 30 * 60
DOWNLOAD_TTL = 5 * 60
RUNS_PER_HOUR = 10
MAX_BODY = 32 * 1024
PROVIDERS = ("groq", "gemini", "openrouter", "openai", "anthropic", "custom")

SESSIONS: dict[str, dict] = {}
DOWNLOADS: dict[str, dict] = {}
RUN_COUNT: dict[str, list[float]] = {}
GUARD = threading.Lock()

# single source for UI assets: repo-root static/ (Vercel serves it, Python serves it locally)
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")


def new_sid() -> str:
    return secrets.token_urlsafe(24)


def sweep() -> None:
    now = time.time()
    for sid in [s for s, v in SESSIONS.items() if v["created"] + SESSION_TTL < now]:
        SESSIONS.pop(sid, None)
    for token in [t for t, v in DOWNLOADS.items() if v["exp"] < now]:
        DOWNLOADS.pop(token, None)


def valid_slot(slot: object) -> tuple[str, str, str, str] | None:
    """(provider, model, key, base_url). Custom endpoints must be https; base travels, never logs."""
    if not isinstance(slot, dict):
        return None
    provider = str(slot.get("provider", "")).lower()
    model = str(slot.get("model", "")).strip()
    key = str(slot.get("key", "")).strip()
    base = str(slot.get("base_url", "")).strip().rstrip("/")
    if provider not in PROVIDERS or not (1 <= len(model) <= 100) or len(key) < 8:
        return None
    if provider == "custom" and not base.startswith("https://"):
        return None
    return provider, model, key, base


def check_rate(ip: str) -> bool:
    """True when the IP may run. Sliding 1-hour window, in-memory."""
    now = time.time()
    with GUARD:
        window = [t for t in RUN_COUNT.get(ip, []) if now - t < 3600]
        if len(window) >= RUNS_PER_HOUR:
            RUN_COUNT[ip] = window
            return False
        RUN_COUNT[ip] = window + [now]
        return True


def scrub(text: str) -> str:
    """Last line of defense: redact anything resembling a supplied key from outbound bodies."""
    for session in SESSIONS.values():
        for slot in ("primary", "fallback"):
            key = (session.get(slot) or [None, None, None])[2]
            if key and len(key) >= 8 and key in text:
                text = text.replace(key, "[REDACTED]")
    return text


def _preview(result: dict) -> list[dict]:
    """First 8 lead rows as parsed JSON (server-side csv parse — no naive client splitting)."""
    import csv
    import io
    if result.get("format") == "json":
        try:
            return json.loads(result["data"])[:8]
        except ValueError:
            return []
    try:
        return list(csv.DictReader(io.StringIO(result["data"])))[:8]
    except (csv.Error, ValueError):
        return []


class Handler(BaseHTTPRequestHandler):
    server_version = "REAVER/4"

    def log_message(self, *args):  # method + path + status only; bodies never logged
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json", stream: bool = False) -> None:
        if not stream and ctype.startswith("text/html"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        if not stream:
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, scrub(json.dumps(obj)).encode())

    def _body(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return None
        if length <= 0 or length > MAX_BODY:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            return None

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            return self._page("landing.html")
        if path == "/playground":
            return self._page("playground.html")
        if path == "/mcp-docs":
            return self._page("mcp.html")
        if path == "/favicon.ico":
            return self._brand("Favicon.png", "image/png")
        if path == "/img/logo":
            return self._brand("Primary logo without BG.png", "image/png")
        if path == "/api/health":
            from mesh.doctor import registry
            from mesh.router import last_stats
            from connectors.keys import keys, KEY_NAMES
            from provider.llm import KEY_NAMES_LLM
            stats = last_stats()
            out = []
            for entry in registry():
                present = bool(keys(*KEY_NAMES.get(entry["name"], ()))) if entry["name"] in KEY_NAMES else None
                out.append({**entry, "key_present": present,
                            "last": stats.get(entry["name"], {"status": "UNTESTED"})})
            providers = [{"name": name, "key_present": bool(keys(*knames))}
                         for name, knames in KEY_NAMES_LLM.items()]
            return self._json(200, {"ok": True, "sources": out, "providers": providers})
        if path.startswith("/api/download/"):
            return self._download(path.rsplit("/", 1)[-1])
        if path.startswith("/static/"):
            return self._static(path.rsplit("/", 1)[-1])
        if "text/html" in (self.headers.get("Accept") or ""):
            return self._not_found_page()
        return self._json(404, {"ok": False, "error": "unknown path"})

    def _brand(self, name: str, ctype: str) -> None:
        """Serve brand art from logos/ — strict allowlist, no path traversal possible."""
        import os
        if name not in ("Favicon.png", "Primary logo without BG.png", "Primary logo.png"):
            return self._json(404, {"ok": False, "error": "unknown path"})
        base = os.path.join(os.path.dirname(STATIC_DIR), "logos")
        try:
            with open(os.path.join(base, name), "rb") as handle:
                self._send(200, handle.read(), ctype)
        except OSError:
            self._json(404, {"ok": False, "error": "asset missing"})

    def _not_found_page(self) -> None:
        import os
        try:
            with open(os.path.join(STATIC_DIR, "404.html"), "rb") as handle:
                self._send(404, handle.read(), "text/html")
        except OSError:
            self._json(404, {"ok": False, "error": "unknown path"})

    def _page(self, name: str) -> None:
        import os
        target = os.path.join(STATIC_DIR, name)
        try:
            with open(target, "rb") as handle:
                self._send(200, handle.read(), "text/html")
        except OSError:
            self._json(404, {"ok": False, "error": "page missing"})

    def _static(self, name: str) -> None:
        import os
        if name not in ("app.js", "site.js", "mcp.js", "style.css", "favicon.png", "logo.png"):
            if "text/html" in (self.headers.get("Accept") or ""):
                return self._not_found_page()
            return self._json(404, {"ok": False, "error": "unknown path"})
        ctype = {"js": "application/javascript", "css": "text/css",
                 "png": "image/png"}.get(name.rsplit(".", 1)[-1], "application/octet-stream")
        ctype = "application/javascript" if name.endswith(".js") else "text/css"
        try:
            with open(os.path.join(STATIC_DIR, name), "rb") as handle:
                self._send(200, handle.read(), ctype)
        except OSError:
            self._json(404, {"ok": False, "error": "asset missing"})

    def _download(self, token: str) -> None:
        with GUARD:
            item = DOWNLOADS.pop(token, None)
        if item is None or item["exp"] < time.time():
            return self._json(404, {"ok": False, "error": "download expired"})
        data = item["data"].encode("utf-8")
        ctype = "text/csv" if item["format"] == "csv" else "application/json"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Disposition",
                         'attachment; filename="reaver-leads.%s"' % item["format"])
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/session":
            sweep()
            sid = new_sid()
            SESSIONS[sid] = {"created": time.time(), "primary": None, "fallback": None,
                             "lock": threading.Lock()}
            return self._json(200, {"ok": True, "session_id": sid})
        body = self._body()
        if body is None:
            return self._json(400, {"ok": False, "error": "invalid json body"})
        if path == "/api/keys":
            return self._keys(body)
        if path == "/api/run":
            return self._run(body)
        return self._json(404, {"ok": False, "error": "unknown path"})

    def do_DELETE(self) -> None:  # noqa: N802
        if urlparse(self.path).path == "/api/session":
            body = self._body() or {}
            SESSIONS.pop(str(body.get("session_id", "")), None)
            return self._json(200, {"ok": True, "cleared": True})
        return self._json(404, {"ok": False, "error": "unknown path"})

    def _session(self, body: dict) -> dict | None:
        sweep()
        session = SESSIONS.get(str(body.get("session_id", "")))
        return session if session and session["created"] + SESSION_TTL >= time.time() else None

    def _keys(self, body: dict) -> None:
        session = self._session(body)
        if session is None:
            return self._json(401, {"ok": False, "error": "unknown or expired session"})
        primary, fallback = valid_slot(body.get("primary")), valid_slot(body.get("fallback"))
        if primary is None or fallback is None:
            return self._json(400, {"ok": False, "error": "primary + fallback each need provider, model, key"})
        session["primary"], session["fallback"] = primary, fallback
        # the key VALUES are never echoed back — only which provider/model was stored
        return self._json(200, {"ok": True, "primary": primary[:2], "fallback": fallback[:2]})

    def _run(self, body: dict) -> None:
        from agent.graph import stream_prospect
        session = self._session(body)
        if session is None:
            return self._json(401, {"ok": False, "error": "unknown or expired session"})
        if session["primary"] is None:
            return self._json(400, {"ok": False, "error": "supply keys first"})
        request = str(body.get("request", ""))
        try:
            desired = int(body.get("desired_count", 20))
        except (ValueError, TypeError):
            return self._json(400, {"ok": False, "error": "bad desired_count"})
        output_format = str(body.get("output_format", "csv"))
        if not (3 <= len(request) <= 4000) or not (1 <= desired <= 200) \
                or output_format not in ("csv", "json"):
            return self._json(400, {"ok": False, "error": "bad request shape"})
        if not check_rate(self.client_address[0]):
            return self._json(429, {"ok": False, "error": "rate limited; try later"})
        if not session["lock"].acquire(blocking=False):
            return self._json(409, {"ok": False, "error": "session busy"})
        try:
            chain = [session["primary"], session["fallback"]]
            business = body.get("business_context") if isinstance(body, dict) else None
            events = stream_prospect(request, desired, output_format, llm_chain=chain,
                                     business_context=business if isinstance(business, dict) else {})
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            for event in events:
                node, result = event.get("node"), event.get("result")
                if result is not None and result.get("ok"):
                    token = secrets.token_urlsafe(24)
                    with GUARD:
                        DOWNLOADS[token] = {"data": result["data"], "format": result["format"],
                                            "exp": time.time() + DOWNLOAD_TTL}
                    payload = {"node": "result", "ok": True, "format": result["format"],
                               "count": result["count"], "steps": result.get("steps", []),
                               "why": result.get("why", {}), "rows": _preview(result),
                               "conflicts": result.get("conflicts", []),
                               "rejected": result.get("rejected", []),
                               "shortfall": result.get("shortfall", 0),
                               "shortfall_note": result.get("shortfall_note", ""),
                               "quota": result.get("quota", {}),
                               "download": token}
                elif result is not None:
                    payload = {"node": "result", "ok": False, "error": result.get("error", "run failed"),
                               "steps": result.get("steps", [])}
                else:
                    payload = {"node": node, "steps": event.get("steps", [])}
                self.wfile.write(("data: " + scrub(json.dumps(payload)) + "\n\n").encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            session["lock"].release()


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="reaver-playground")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("REAVER playground on http://%s:%d" % (args.host, args.port), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
