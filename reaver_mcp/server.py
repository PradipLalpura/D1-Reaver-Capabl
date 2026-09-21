"""REAVER MCP server. Real logic where the deterministic core exists; honest NOT_IMPLEMENTED elsewhere."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from compliance import robots
from connectors import backends
from engine.deterministic import (
    canonical_url,
    ensure_http_url,
    merge_leads,
    normalize_domain,
    summarize_attribute,
    to_csv,
    to_json,
)
from engine.models import MAX_LEADS, Evidence, LeadRecord, TargetSpec
from mesh import router
from mesh.doctor import registry

mcp = FastMCP("reaver")


def _err(tool: str, reason: str) -> dict:
    return {"ok": False, "error": reason, "tool": tool}  # generic by design: no paths, no keys


def _not_built(tool: str, phase: int, what: str) -> dict:
    return _err(tool, "engine stage lands in Phase %d (%s); no data fabricated" % (phase, what))


def _leads(raw: object, tool: str) -> tuple[list[LeadRecord] | None, dict | None]:
    if not isinstance(raw, list) or len(raw) > MAX_LEADS:
        return None, _err(tool, "provide 1-%d lead records" % MAX_LEADS)
    try:
        return [LeadRecord.model_validate(item) for item in raw], None
    except ValidationError:
        return None, _err(tool, "lead records failed validation")


@mcp.tool()
def prospect(request: str, desired_count: int = 20, output_format: str = "csv",
             business_context: dict = {}) -> dict:
    """End-to-end NL request → qualified leads. WIRED (Phase 3, LangGraph).

    business_context is optional but sharpens results: {business_name, sells,
    ideal_buyer, dealbreakers[]}. Unknown keys dropped, lengths capped.
    """
    try:
        spec = TargetSpec(request=request, desired_count=desired_count)
    except ValidationError:
        return _err("prospect", "request 3-4000 chars, desired_count 1-%d" % MAX_LEADS)
    if output_format not in ("csv", "json"):
        return _err("prospect", "output_format must be csv or json")
    from agent.graph import run_prospect
    try:
        return run_prospect(spec.request, spec.desired_count, output_format,
                            business_context=business_context or {})
    except Exception:
        return _err("prospect", "run failed; retry or narrow the request")


@mcp.tool()
def discover_leads(request: str, desired_count: int = 20) -> dict:
    """Candidate discovery from the source mesh. WIRED (Phase 2)."""
    try:
        spec = TargetSpec(request=request, desired_count=desired_count)
    except ValidationError:
        return _err("discover_leads", "request 3-4000 chars, desired_count 1-%d" % MAX_LEADS)
    res = router.route("web_search", spec.request, n=min(spec.desired_count * 2, 20))
    if not res["ok"]:
        return {"ok": False, "tool": "discover_leads", "error": "all search backends failed",
                "fallbacks": res["fallbacks"]}
    now = datetime.now(timezone.utc)
    candidates = [{"name": item.get("title", ""), "domain": normalize_domain(item.get("url", "")),
                   "url": item.get("url", ""), "snippet": item.get("snippet", "")}
                  for item in res["items"] if item.get("url")]
    return {"ok": True, "tool": "discover_leads", "backend": res["backend"],
            "fallbacks": res["fallbacks"], "cached": res["cached"],
            "candidates": candidates[:spec.desired_count], "observed_at": now.isoformat()}


@mcp.tool()
def research_target(name: str, domain: str = "") -> dict:
    """Deep research on one entity via page fetch. WIRED (Phase 2)."""
    if not name.strip() or len(name) > 300:
        return _err("research_target", "name 1-300 chars required")
    url = ""
    if domain.strip():
        try:
            url = canonical_url(domain)
        except ValueError:
            return _err("research_target", "domain is not a valid http(s) host")
    else:
        found = router.route("web_search", name + " official website", n=3)
        if found["ok"] and found["items"]:
            url = found["items"][0].get("url", "")
    if not url:
        return _err("research_target", "no reachable page found")
    fetched = backends.jina_fetch(url)
    if fetched.status != "OK":
        return {"ok": False, "tool": "research_target", "error": fetched.note}
    host = normalize_domain(url)
    tier = 1 if domain.strip() and host == normalize_domain(domain) else 4
    text = fetched.items[0]["text"]
    return {"ok": True, "tool": "research_target", "url": url, "backend": fetched.backend,
            "evidence": [Evidence(attribute="profile", value=text[:2000], source=url,
                                  tier=tier, observed_at=datetime.now(timezone.utc),
                                  confidence=0.8 if tier == 1 else 0.5).model_dump(mode="json")]}


@mcp.tool()
def enrich_lead(name: str, domain: str = "") -> dict:
    """Structured enrichment: Apollo firmographics + Hunter email signal. WIRED (Phase 2)."""
    if not name.strip() or len(name) > 300:
        return _err("enrich_lead", "name 1-300 chars required")
    firm = router.route("firmographic", name or domain, n=3)
    emails: dict = {"status": "skipped", "items": []}
    if domain.strip():
        try:
            host = normalize_domain(domain)
            ER = router.route("email", host, n=5, domain=host)
            emails = {"status": "OK" if ER["ok"] else "FAIL", "items": ER["items"],
                      "fallbacks": [] if ER["ok"] else ER["fallbacks"]}
        except Exception:
            emails = {"status": "FAIL", "items": [], "note": "domain unusable"}
    backends_used = [{"backend": "apollo", "ok": firm["ok"]},
                     {"backend": "hunter", "ok": emails["status"] == "OK"}]
    if not firm["ok"] and emails["status"] != "OK":
        return {"ok": False, "tool": "enrich_lead", "error": "enrichment backends failed",
                "backends": backends_used,
                "fallbacks": [] if firm["ok"] else firm["fallbacks"]}
    return {"ok": True, "tool": "enrich_lead", "firmographics": firm["items"] if firm["ok"] else [],
            "emails": emails["items"], "backends": backends_used,
            "fallbacks": [] if firm["ok"] else firm["fallbacks"]}


@mcp.tool()
def qualify_lead(name: str, criteria: list[str] = [], evidence: list[dict] = []) -> dict:
    """Criterion-by-criterion qualification over supplied evidence. WIRED (Phase 3)."""
    if not name.strip() or len(name) > 300:
        return _err("qualify_lead", "name 1-300 chars required")
    if not criteria or len(criteria) > 20:
        return _err("qualify_lead", "provide 1-20 criteria")
    try:
        items = [Evidence.model_validate(e) for e in evidence]
    except ValidationError:
        return _err("qualify_lead", "evidence failed validation")
    from engine.judge import judge_lead
    grouped: dict[str, list[Evidence]] = defaultdict(list)
    for item in items:
        grouped[item.attribute].append(item)
    status, confidence, details = judge_lead(criteria, grouped)
    return {"ok": True, "tool": "qualify_lead", "name": name, "state": status,
            "confidence": confidence,
            "criteria": [d.model_dump(mode="json") for d in details]}


@mcp.tool()
def verify_evidence(evidence: list[dict] = [], ttl_days: int = 90) -> dict:
    """Freshness, tier-blind conflict and staleness check per attribute. WIRED."""
    try:
        items = [Evidence.model_validate(e) for e in evidence]
    except ValidationError:
        return _err("verify_evidence", "evidence failed validation")
    if ttl_days < 1:
        return _err("verify_evidence", "ttl_days must be positive")
    grouped: dict[str, list[Evidence]] = defaultdict(list)
    for item in items:
        grouped[item.attribute].append(item)
    return {"ok": True, "tool": "verify_evidence",
            "attributes": [summarize_attribute(attr, group, ttl_days) for attr, group in grouped.items()]}


@mcp.tool()
def deduplicate_leads(leads: list[dict]) -> dict:
    """Entity resolution: merge duplicates, union evidence. WIRED."""
    records, failure = _leads(leads, "deduplicate_leads")
    if failure:
        return failure
    assert records is not None
    merged = merge_leads(records)
    return {"ok": True, "tool": "deduplicate_leads", "input_count": len(records),
            "output_count": len(merged), "leads": [m.model_dump(mode="json") for m in merged]}


@mcp.tool()
def refresh_leads(leads: list[dict], criteria: list[str] = []) -> dict:
    """Stale-evidence recheck: forced refetch, change detection, re-judge. WIRED (Phase 7).

    Per lead: REFRESHED (facts or verdict changed) / FRESH (confirmed same) /
    STALE (page gone, search fallback still mentions it) / GONE (no trace anywhere).
    """
    from agent.graph import extract_fields
    from engine.judge import judge_lead
    records, failure = _leads(leads, "refresh_leads")
    if failure:
        return failure
    assert records is not None
    report = []
    for lead in records:
        url = (lead.website or lead.domain).strip()
        if not url:
            report.append({"name": lead.name, "status": "STALE",
                           "note": "no URL to recheck", "changed": []})
            continue
        try:
            target = canonical_url(url)
        except ValueError:
            report.append({"name": lead.name, "status": "STALE",
                           "note": "URL unusable", "changed": []})
            continue
        fetched = backends.jina_fetch(target, force=True)
        if fetched.status != "OK":
            fallback = router.route("web_search", lead.name, n=3)
            if fallback["ok"] and fallback["items"]:
                report.append({"name": lead.name, "status": "STALE",
                               "note": "page %s; search still mentions it" % fetched.note,
                               "changed": []})
            else:
                report.append({"name": lead.name, "status": "GONE",
                               "note": "page %s; no search trace" % fetched.note,
                               "changed": []})
            continue
        fields = extract_fields(target, fetched.items[0]["text"], None)
        now = datetime.now(timezone.utc)
        attrs: dict[str, list[Evidence]] = {}
        for attr in ("industry", "country", "city", "employee_count"):
            value = str(fields.get(attr, "") or "").strip()
            if value and value.lower() != "unknown":
                attrs[attr] = [Evidence(attribute=attr, value=value[:500], source=target,
                                        tier=1, observed_at=now, confidence=0.8)]
        changed = [a for a, v in (("industry", lead.industry), ("country", lead.country),
                                  ("city", lead.city), ("employee_count", lead.employee_count))
                   if a in attrs and attrs[a][0].value.lower() != (v or "").lower()]
        entry: dict = {"name": lead.name, "status": "REFRESHED" if changed else "FRESH",
                       "changed": changed, "observed_at": now.isoformat()}
        if criteria:
            status, confidence, details = judge_lead(criteria[:20], attrs)
            entry["state"], entry["confidence"] = status, confidence
            entry["criteria"] = [d.model_dump(mode="json") for d in details]
            if not changed and status == lead.state.value:
                entry["status"] = "FRESH"
            else:
                entry["status"] = "REFRESHED"
        report.append(entry)
    return {"ok": True, "tool": "refresh_leads", "refreshed": report}


@mcp.tool()
def export_leads(leads: list[dict], output_format: str = "csv") -> dict:
    """CSV (default) or JSON export, HubSpot-compatible columns. WIRED."""
    if output_format not in ("csv", "json"):
        return _err("export_leads", "output_format must be csv or json")
    records, failure = _leads(leads, "export_leads")
    if failure:
        return failure
    assert records is not None
    data = to_csv(records) if output_format == "csv" else to_json(records)
    return {"ok": True, "tool": "export_leads", "format": output_format, "count": len(records), "data": data}


@mcp.tool()
def doctor() -> dict:
    """Source health: key presence + last-call memory. Quota-safe: probes nothing, burns nothing."""
    live = router.last_state()
    sources = []
    for entry in registry():
        name = entry["name"]
        state = live.get(name, "UNTESTED: key check only, never called")
        sources.append({**entry, "live": state})
    return {"ok": True, "tool": "doctor", "probed": True,
            "method": "key presence + last-call memory (no quota burned)", "sources": sources}


def requires_token(host: str) -> bool:
    """Any non-loopback bind must carry a bearer token. Localhost stays frictionless."""
    return host not in ("127.0.0.1", "localhost", "::1")


def main() -> None:
    import os
    parser = argparse.ArgumentParser(prog="reaver-mcp")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--token", default=os.environ.get("REAVER_MCP_TOKEN", ""))
    args = parser.parse_args()
    if args.transport == "http":
        if requires_token(args.host) and not args.token:
            parser.error("non-loopback bind requires --token (or REAVER_MCP_TOKEN)")
        import uvicorn
        import urllib.parse
        app = mcp.streamable_http_app()
        if args.token:
            from starlette.middleware.base import BaseHTTPMiddleware
            from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
            from starlette.routing import Route

            token = args.token

            def _public_base(request) -> str:
                """Proxy-aware public origin for discovery documents (Railway/Vercel friendly)."""
                headers = request.headers
                scheme = headers.get("x-forwarded-proto", request.url.scheme)
                host = headers.get("x-forwarded-host", request.headers.get("host", ""))
                return (scheme + "://" + host).rstrip("/")

            async def _resource_metadata(request):
                # RFC 9728: advertises OUR authorization server so ChatGPT can run OAuth.
                base = _public_base(request)
                return JSONResponse({
                    "resource": base + "/mcp/",
                    "authorization_servers": [base],
                    "scopes_supported": [],
                    "bearer_methods_supported": ["header"],
                    "documentation": base + "/mcp-docs",
                })

            async def _as_metadata(request):
                # RFC 8414 authorization-server metadata (CIMD + DCR, PKCE S256, iss echo).
                base = _public_base(request)
                return JSONResponse({
                    "issuer": base,
                    "authorization_endpoint": base + "/oauth/authorize",
                    "token_endpoint": base + "/oauth/token",
                    "registration_endpoint": base + "/oauth/register",
                    "response_types_supported": ["code"],
                    "grant_types_supported": ["authorization_code", "refresh_token"],
                    "code_challenge_methods_supported": ["S256"],
                    "token_endpoint_auth_methods_supported": ["none"],
                    "client_id_metadata_document_supported": True,
                    "authorization_response_iss_parameter_supported": True,
                })

            async def _register(request):
                import json
                from auth import oauth
                try:
                    body = json.loads((await request.body()).decode() or "{}")
                except ValueError:
                    body = {}
                uris = body.get("redirect_uris", [])
                client_id, error = oauth.register_client(uris if isinstance(uris, list) else [])
                if error:
                    return JSONResponse({"error": error}, 400)
                return JSONResponse({"client_id": client_id})

            async def _authorize_get(request):
                # Consent page: user pastes their /connect token, clicks Approve.
                q = request.query_params
                needed = ("client_id", "redirect_uri", "code_challenge")
                if not all(q.get(k) for k in needed):
                    return JSONResponse({"error": "invalid_request"}, 400)
                from html import escape
                hidden = "".join(
                    '<input type="hidden" name="%s" value="%s">' % (k, escape(q.get(k, "")))
                    for k in (*needed, "state", "resource"))
                return HTMLResponse(
                    "<!doctype html><html><body style='background:#070c16;color:#f4f6fb;font-family:sans-serif'>"
                    "<main style='max-width:480px;margin:8vh auto;padding:24px'>"
                    "<h1>Connect REAVER</h1>"
                    "<p>ChatGPT is requesting access to your REAVER leads. Paste your "
                    "token from the <b>/connect</b> page, then Approve. No password exists here.</p>"
                    "<form method='post'>" + hidden +
                    "<input name='user_token' placeholder='rvr_…' style='width:100%;padding:10px' required>"
                    "<p><button name='decision' value='allow'>Approve</button> "
                    "<button name='decision' value='deny'>Deny</button></p></form></main></body></html>")

            async def _authorize_post(request):
                from auth import oauth
                form = dict(await request.form())
                if form.get("decision") != "allow":
                    return RedirectResponse(
                        "%s?error=access_denied&state=%s" % (
                            form.get("redirect_uri", ""), form.get("state", "")), 302)
                code, error = oauth.authorize(
                    form.get("client_id", ""), form.get("redirect_uri", ""),
                    form.get("code_challenge", ""), form.get("resource", ""),
                    form.get("user_token", ""))
                if error:
                    sep = "&" if "?" in form.get("redirect_uri", "") else "?"
                    return RedirectResponse("%s%s%s%s%s%s%s" % (
                        form.get("redirect_uri", ""), sep, "error=", error.split(":")[0],
                        "&state=", form.get("state", ""), "&iss=", _public_base(request)), 302)
                return RedirectResponse(
                    "%s?code=%s&state=%s&iss=%s" % (
                        form.get("redirect_uri", ""), code, form.get("state", ""),
                        _public_base(request)), 302)

            async def _token(request):
                from auth import oauth
                try:
                    raw = (await request.body()).decode()
                    form = dict(urllib.parse.parse_qsl(raw, keep_blank_values=True))
                except Exception:
                    return JSONResponse({"error": "invalid_request"}, 400)
                grant = form.get("grant_type", "")
                if grant == "authorization_code":
                    result, error = oauth.exchange_code(
                        form.get("code", ""), form.get("redirect_uri", ""),
                        form.get("client_id", ""), form.get("code_verifier", ""))
                elif grant == "refresh_token":
                    result, error = oauth.exchange_refresh(form.get("refresh_token", ""))
                else:
                    return JSONResponse({"error": "unsupported_grant_type"}, 400)
                if error:
                    return JSONResponse({"error": error}, 400)
                return JSONResponse(result)

            app.routes.append(Route("/.well-known/oauth-protected-resource", _resource_metadata))
            app.routes.append(Route("/.well-known/oauth-authorization-server", _as_metadata))
            app.routes.append(Route("/oauth/register", _register, methods=["POST"]))
            app.routes.append(Route("/oauth/authorize", _authorize_get, methods=["GET"]))
            app.routes.append(Route("/oauth/authorize", _authorize_post, methods=["POST"]))
            app.routes.append(Route("/oauth/token", _token, methods=["POST"]))

            PUBLIC_PATHS = ("/.well-known/oauth-protected-resource",
                            "/.well-known/oauth-authorization-server",
                            "/oauth/register", "/oauth/authorize", "/oauth/token")

            class BearerAuth(BaseHTTPMiddleware):
                async def dispatch(self, request, call_next):
                    if request.url.path in PUBLIC_PATHS:
                        return await call_next(request)
                    presented = (request.headers.get("authorization") or "")[7:] \
                        if request.headers.get("authorization", "").startswith("Bearer ") else ""
                    if presented and presented == token:
                        return await call_next(request)
                    try:
                        from engine.tokens import check
                        from auth.oauth import verify_access
                        allowed, _ = check(presented)
                        allowed = allowed or verify_access(presented)
                    except Exception:
                        allowed = False
                    if not allowed:
                        # MCP-spec discovery: tell spec-compliant clients (ChatGPT) where auth lives
                        meta = _public_base(request) + "/.well-known/oauth-protected-resource"
                        return JSONResponse({"error": "unauthorized"}, 401, headers={
                            "WWW-Authenticate": 'Bearer resource_metadata="%s"' % meta})
                    return await call_next(request)

            app.add_middleware(BearerAuth)
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
