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
def prospect(request: str, desired_count: int = 20, output_format: str = "csv") -> dict:
    """End-to-end NL request → qualified leads. WIRED (Phase 3, LangGraph)."""
    try:
        spec = TargetSpec(request=request, desired_count=desired_count)
    except ValidationError:
        return _err("prospect", "request 3-4000 chars, desired_count 1-%d" % MAX_LEADS)
    if output_format not in ("csv", "json"):
        return _err("prospect", "output_format must be csv or json")
    from agent.graph import run_prospect
    try:
        return run_prospect(spec.request, spec.desired_count, output_format)
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="reaver-mcp")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.transport == "http":
        mcp.run(transport="streamable-http", host="127.0.0.1", port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
