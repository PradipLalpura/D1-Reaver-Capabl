"""LangGraph: compile → plan → discover → prefilter → research → enrich → verify → qualify → dedupe → export."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import TypedDict

from langgraph.graph import END, StateGraph

from connectors import backends
from data import cache
from engine.deterministic import (
    merge_leads,
    normalize_domain,
    normalize_name,
    summarize_attribute,
    to_csv,
    to_json,
)
from engine.judge import judge_lead
from engine.models import CompiledTarget, Evidence, LeadRecord, LeadState
from mesh import router
from provider import llm

MAX_QUERIES = 6
MAX_CANDIDATES = 60
PAGE_TTL = 24 * 3600
MAX_WAVES = 2  # waves 0..2, then honest shortfall — quota guard, raise only with measured need


class S(TypedDict, total=False):
    request: str
    desired_count: int
    output_format: str
    llm_chain: list
    business: dict
    spec: dict
    queries: list[str]
    pool: list[dict]
    wave: int
    candidates: list[dict]
    researched: list[dict]
    verdicts: list[dict]
    leads: list[dict]
    rejected: list[dict]
    why: dict
    result: dict
    steps: list[str]
    error: str


def _step(state: S, label: str) -> dict:
    return {"steps": [*state.get("steps", []), label]}


def _chain_of(state: S) -> list[tuple] | None:
    raw = state.get("llm_chain") or []
    out = [tuple(c) for c in raw if len(c) in (3, 4)]
    return out or None  # None → provider defaults (env → free-tier chain)


def _coerce_spec(raw: object, business: dict | None = None) -> dict | None:
    """Tolerant mapping: known keys coerced, unknowns dropped, gaps filled from geography/industry."""
    if not isinstance(raw, dict):
        return None
    get = lambda k, t: raw.get(k) if isinstance(raw.get(k), t) else (t() if t is not str else "")
    size_min = raw.get("size_min") if isinstance(raw.get("size_min"), int) else None
    size_max = raw.get("size_max") if isinstance(raw.get("size_max"), int) else None
    spec = {"geography": get("geography", str), "industry": get("industry", str),
            "size_min": size_min, "size_max": size_max,
            "signals": [s for s in get("signals", list) if isinstance(s, str)][:10],
            "exclusions": [s for s in get("exclusions", list) if isinstance(s, str)][:10],
            "criteria": [c for c in get("criteria", list) if isinstance(c, str)][:20]}
    if not spec["criteria"]:
        if spec["geography"]:
            spec["criteria"].append("located in " + spec["geography"])
        if spec["industry"]:
            spec["criteria"].append("operates in " + spec["industry"])
    business = business or {}
    buyer = str(business.get("ideal_buyer", "")).strip()[:200]
    if buyer and not any("serves" in c.lower() for c in spec["criteria"]):
        spec["criteria"].append("serves " + buyer)  # buyer-fit: seller context sharpens, never invents
    for breaker in business.get("dealbreakers", [])[:5]:
        if isinstance(breaker, str) and breaker.strip():
            spec["criteria"].append("must not be " + breaker.strip()[:200])
    # ponytail: buyer-fit is keyword-graded; semantic buyer matching needs richer evidence than pages usually carry
    try:
        return CompiledTarget.model_validate(spec).model_dump()
    except Exception:
        return None


def compile_node(state: S) -> dict:
    business = state.get("business") or {}
    seller = " ".join("%s: %s" % (k, v) for k, v in
                      (("business", business.get("business_name", "")),
                       ("sells", business.get("sells", "")),
                       ("ideal buyer", business.get("ideal_buyer", ""))) if v).strip()
    prompt = ("Extract the lead target as ONE JSON object with exactly these keys:"
              ' {"geography": str, "industry": str, "size_min": int|null, "size_max": int|null,'
              ' "signals": [str], "exclusions": [str], "criteria": [str, ...]}.'
              ' criteria = short testable requirements, e.g. ["located in Ahmedabad, India",'
              ' "operates in bakery"]. Unknown fields become "" or [].'
              + (" Seller context (adds buyer-fit criteria only): " + seller if seller else "")
              + " Request: " + state["request"])
    for attempt in range(2):
        try:
            spec = _coerce_spec(llm.chat_json("Return ONLY the JSON object.", prompt,
                                              chain=_chain_of(state)), business)
        except Exception:
            spec = None
        if spec and spec["criteria"]:
            return {**_step(state, "compile:ok"), "spec": spec, "error": ""}
    return {**_step(state, "compile:failed"), "error": "target compile failed: unusable model output"}


def plan_node(state: S) -> dict:
    spec = state["spec"]
    try:
        raw = llm.chat_json("Write 3-6 web search queries to find candidates. Return ONLY {queries[]}.",
                            str({k: v for k, v in spec.items() if v}), chain=_chain_of(state))
        queries = [q for q in raw.get("queries", []) if isinstance(q, str)][:MAX_QUERIES]
    except Exception:
        queries = ["%s %s" % (spec.get("industry", ""), spec.get("geography", ""))]
    queries = [q.strip() for q in queries if q.strip()][:MAX_QUERIES]
    industry, geo = spec.get("industry", ""), spec.get("geography", "")
    for fallback in ("%s in %s" % (industry, geo), "best %s %s" % (industry, geo),
                     "%s %s directory" % (industry, geo), "top %s %s" % (industry, geo),
                     "%s near %s" % (industry, geo), "%s %s reviews" % (industry, geo)):
        if len(queries) >= 6:
            break
        if fallback.strip() and fallback not in queries:
            queries.append(fallback)
    # ponytail: pad to 4 with template variants; smarter planning needs per-target cost data
    queries = queries[:MAX_QUERIES] or [state["request"][:200]]
    return {**_step(state, "plan:%d queries" % len(queries)), "queries": queries}


def discover_node(state: S) -> dict:
    seen: dict[str, dict] = {}
    fallbacks: list[dict] = []
    backends_hit: list[str] = []
    desired = state.get("desired_count", 20)
    target = min(int(desired * 2.5), MAX_CANDIDATES)
    order = ["tavily", "serper", "serpapi", "exa"]
    for round_no in range(2):  # two passes max: volume first, diversity second
        for index, query in enumerate(state["queries"]):
            if len(seen) >= target:
                break
            # rotate the lead backend per query so one index never owns the pool;
            # non-skipped backends stay available as fallbacks inside route()
            skip = order[: (index + round_no * 2) % len(order)]
            res = router.route("web_search", query, n=10, skip=skip)
            fallbacks.extend(res["fallbacks"])
            if not res["ok"]:
                continue
            if res["backend"] not in backends_hit:
                backends_hit.append(res["backend"])
            for item in res["items"]:
                url = item.get("url", "")
                if not url or url in seen:
                    continue
                seen[url] = {"name": item.get("title", ""), "domain": normalize_domain(url),
                             "url": url, "snippet": item.get("snippet", "")}
                if len(seen) >= MAX_CANDIDATES:
                    break
        if len(seen) >= target:
            break
    # ponytail: pool target 2.5x asked; bigger pools cost quota linearly — measure before raising
    out = {"pool": list(seen.values()), "wave": 0, "fallbacks": fallbacks,
           "backend": "+".join(backends_hit) or ""}
    if not out["pool"]:
        return {**_step(state, "discover:empty"), **out,
                "error": "no candidates discovered"}
    return {**_step(state, "discover:%d via %s" % (len(seen), out["backend"] or "?")), **out}


JUNK_HOSTS = ("tripadvisor.", "instagram.", "reddit.", "facebook.", "youtube.", "youtu.be",
                "x.com", "twitter.", "tiktok.", "pinterest.")
JUNK_PATHS = ("/search", "/questions", "/showtopic", "/media/", "/reel", "/shorts", "/hashtag")
DIRECTORY_HOSTS = ("justdial.", "zomato.", "indiamart.", "tradeindia.", "sulekha.", "yelp.")


def prefilter_node(state: S) -> dict:
    chunk = min(max(state.get("desired_count", 10), 10), 15)
    start = state.get("wave", 0) * chunk
    done_urls = {c.get("url") for c in state.get("researched", [])}
    seen_entities: set[str] = set()
    kept = []
    for cand in state.get("pool", [])[start:]:
        host, path = normalize_domain(cand["url"]), cand["url"].lower()
        if not cand["name"] or not cand["url"]:
            continue
        if any(h in host for h in JUNK_HOSTS) or any(p in path for p in JUNK_PATHS):
            continue  # threads/listicles/reels are content, not entities — universal rule, not industry logic
        if cand["url"] in done_urls:
            continue
        # same merchant researched twice wastes a wave: official domains dedupe by host,
        # directory hosts (many merchants, one host) dedupe by full path
        entity = cand["url"] if any(h in host for h in DIRECTORY_HOSTS) else host or cand["name"]
        if entity in seen_entities:
            continue
        seen_entities.add(entity)
        kept.append(cand)
        if len(kept) >= chunk:
            break
    if not kept:
        return {**_step(state, "prefilter:empty"), "candidates": [],
                "error": "candidate pool exhausted"}
    return {**_step(state, "prefilter:%d (wave %d)" % (len(kept), state.get("wave", 0))),
            "candidates": kept}


def extract_fields(url: str, text: str, chain: list[tuple] | None) -> dict:
    try:
        raw = llm.chat_json(
            "Extract JSON {industry, country, city, employee_count, hiring, signals[],"
            ' page_type}. page_type is one of business|directory|article|unknown: the page itself,'
            " not what it mentions. Missing fields become empty strings.",
            text[:3000], chain=chain)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def research_node(state: S) -> dict:
    import time as _time
    now = datetime.now(timezone.utc).isoformat()
    chain = _chain_of(state)
    researched = []
    for index, cand in enumerate(state["candidates"]):
        if index:
            _time.sleep(1)  # ponytail: politeness delay vs reader rate limits; async batching only if runs exceed demo patience
        key = cache.make_key("page", cand["url"])
        cached = cache.get(key)
        if cached is None:
            fetched = backends.jina_fetch(cand["url"])
            if fetched.status != "OK":
                researched.append({**cand, "attrs": {}, "fetch_note": fetched.note})
                continue
            text = fetched.items[0]["text"]
            cache.put(key, text, PAGE_TTL)
        else:
            text = cached if isinstance(cached, str) else ""
        host = normalize_domain(cand["url"])
        tier = 1 if cand["domain"] and host == cand["domain"] else 4
        fields = extract_fields(cand["url"], text, chain)
        attrs: dict[str, list[dict]] = {}
        for attr in ("industry", "country", "city", "employee_count", "hiring"):
            value = str(fields.get(attr, "") or "").strip()
            if value and value.lower() != "unknown":
                attrs[attr] = [Evidence(attribute=attr, value=value[:500], source=cand["url"],
                                        tier=tier, observed_at=datetime.now(timezone.utc),
                                        confidence=0.8 if tier == 1 else 0.5).model_dump(mode="json")]
        researched.append({**cand, "attrs": attrs, "observed_at": now,
                           "page_type": str(fields.get("page_type", "unknown")).lower()})
    # directory pages name real entities: mine ≤3 per wave for follow-ups (the list-to-lead bridge)
    mined = 0
    pool_urls = {c.get("url") for c in state.get("pool", [])}
    pool_additions = []
    for cand in researched:
        if mined >= 3 or cand.get("page_type") != "directory":
            continue
        try:
            raw = llm.chat_json(
                "List the companies/entities this directory page describes."
                " Return ONLY {entities: [{name, domain}]} with real domains from the text,"
                " max 10. No guessing.",
                (cache.get(cache.make_key("page", cand["url"])) or "")[:3000],
                chain=chain)
            entities = raw.get("entities", []) if isinstance(raw, dict) else []
        except Exception:
            continue
        for ent in entities:
            if not isinstance(ent, dict):
                continue
            domain = normalize_domain(str(ent.get("domain", "")))
            if not domain or "." not in domain:
                continue
            url = "https://" + domain
            if url in pool_urls:
                continue
            pool_urls.add(url)
            pool_additions.append({"name": str(ent.get("name", domain))[:200], "domain": domain,
                                   "url": url, "snippet": "mined from " + cand["url"]})
        mined += 1
    from evidence import rag
    for cand in researched:
        if cand.get("fetch_note"):
            cand["passages"] = []
        else:
            cached_text = cache.get(cache.make_key("page", cand["url"]))
            text = cached_text if isinstance(cached_text, str) else ""
            owner = normalize_domain(cand["url"]) or cand["name"]
            cand["passages"] = rag.store_passages(owner, rag.chunk(text)[:8]) if text else []
    usable = [r for r in researched if r["attrs"]]
    prior = {(c.get("url"), c.get("name")) for c in state.get("researched", [])}
    accumulated = [*state.get("researched", []),
                   *[r for r in researched if (r.get("url"), r.get("name")) not in prior]]
    pool = [*state.get("pool", []), *pool_additions[:MAX_CANDIDATES - len(state.get("pool", []))]]
    if not usable and not [c for c in state.get("researched", []) if c.get("attrs")]:
        if pool_additions:
            # directories yielded fresh entities: top up toward them instead of failing
            return {**_step(state, "research:mined %d entities" % len(pool_additions)),
                    "researched": accumulated, "pool": pool, "error": ""}
        return {**_step(state, "research:empty"), "researched": accumulated,
                "error": "no researchable evidence"}
    return {**_step(state, "research:%d new (%d total)" % (len(usable), len(accumulated))),
            "researched": accumulated, "pool": pool, "error": ""}


TECH_HINTS = ("software", "saas", "tech", "artificial intelligence", "ai ", "cloud", "fintech")

ENRICH_K = 8  # metered backends per wave cap; page evidence stays free and unlimited


def _gap_evidence(attr: str, value: str, source: str, tier: int, confidence: float) -> dict:
    return Evidence(attribute=attr, value=value[:500], source=source, tier=tier,
                    observed_at=datetime.now(timezone.utc),
                    confidence=confidence).model_dump(mode="json")


def enrich_node(state: S) -> dict:
    """Fill attribute gaps from every mesh backend. Page evidence always wins; enrichers only fill blanks.
    Best-effort: backend failures become notes, never run failures."""
    from evidence import rag
    spec = state.get("spec", {})
    industry_hint = str(spec.get("industry", "")).lower()
    tech_target = any(h in industry_hint for h in TECH_HINTS)
    fresh = [c for c in state.get("researched", []) if not c.get("_enriched") and not c.get("fetch_note")]
    fresh.sort(key=lambda c: len(c.get("attrs", {})))
    enriched = 0
    for cand in fresh:
        if enriched >= ENRICH_K:
            break
        if cand.get("page_type") in ("article", "directory"):
            cand["_enriched"] = True
            continue  # non-entities get mined, never enriched — metered quota only serves candidates
        missing = {"industry", "country", "city", "employee_count", "hiring",
                   "contact_email"} - set(cand["attrs"])
        if not missing:
            cand["_enriched"] = True
            continue
        notes = []
        if cand.get("domain") or cand.get("name"):
            firm = router.route("firmographic", cand["name"] or cand["domain"], n=1)
            orgs = firm["items"] if firm["ok"] else []
            if orgs:
                org = orgs[0]
                fill = {"industry": org.get("industry", ""),
                        "employee_count": str(org.get("size", "")),
                        "city": org.get("city", ""), "country": org.get("country", "")}
                for attr, value in fill.items():
                    if attr in missing and str(value).strip():
                        cand["attrs"][attr] = [_gap_evidence(attr, str(value), "apollo", 3, 0.6)]
                        missing.discard(attr)
            else:
                notes.append("apollo: " + (firm["fallbacks"][0]["note"] if firm["fallbacks"] else "no match"))
        if cand.get("domain") and "contact_email" in missing:
            found = router.route("email", cand["domain"], n=3, domain=cand["domain"])
            if found["ok"] and found["items"]:
                cand["attrs"]["contact_email"] = [_gap_evidence(
                    "contact_email", found["items"][0].get("email", ""), "hunter", 3, 0.6)]
                missing.discard("contact_email")
        if not (set(cand["attrs"]) & {"country", "city"}) and spec.get("geography"):
            local = router.route("local", "%s %s" % (cand["name"], spec["geography"]), n=1)
            if local["ok"] and local["items"]:
                country = (local["items"][0].get("title", "").split(",") or [""])[-1].strip()
                if country:
                    cand["attrs"].setdefault("country", [_gap_evidence("country", country, "osm", 3, 0.4)])
        if not (set(cand["attrs"]) & {"country", "city"}) and spec.get("geography"):
            # last resort: metered maps actor (budget-gated in router), max 3 places
            maps = router.route("structured", cand["name"], actor_kind="maps", run_input={
                "searchStringsArray": ["%s %s" % (cand["name"], spec["geography"])],
                "maxCrawledPlacesPerSearch": 3})
            if maps["ok"] and maps["items"]:
                first = maps["items"][0]
                city = str(first.get("city", "")).strip()
                addr = str(first.get("address", "")).strip()
                if city:
                    cand["attrs"].setdefault("city", [_gap_evidence("city", city, "apify-maps", 3, 0.5)])
                if addr and "country" not in cand["attrs"]:
                    cand["attrs"].setdefault("country", [_gap_evidence(
                        "country", addr.split(",")[-1].strip(), "apify-maps", 3, 0.4)])
        if tech_target and "industry" in missing:
            tech = router.route("tech", cand["name"], n=3)
            if tech["ok"]:
                token = normalize_name(cand["name"]).split(" ")[0] if cand["name"] else ""
                for repo in tech["items"]:
                    if token and token in str(repo.get("title", "")).lower():
                        cand["attrs"]["industry"] = [_gap_evidence(
                            "industry", "software: " + repo.get("title", ""), "github", 2, 0.5)]
                        break
        cand["_enriched"] = True
        if notes:
            cand["enrich_note"] = "; ".join(notes)
        enriched += 1
    # ponytail: passages stay page-bound; enricher values join qualification via attrs, not vector store
    for cand in state.get("researched", []):
        cand.pop("fetch_note", None)
    return {**_step(state, "enrich:%d" % enriched)}


def verify_node(state: S) -> dict:
    checked = []
    for cand in state["researched"]:
        summaries = []
        for attr, evs in cand["attrs"].items():
            items = [Evidence.model_validate(e) for e in evs]
            summaries.append(summarize_attribute(attr, items))
        checked.append({**cand, "verification": summaries})
    return {**_step(state, "verify:ok"), "researched": checked}


def qualify_node(state: S) -> dict:
    from engine.judge import attach_citations, restate
    criteria = state["spec"]["criteria"]
    verdicts = []
    for cand in state["researched"]:
        attrs = {attr: [Evidence.model_validate(e) for e in evs] for attr, evs in cand["attrs"].items()}
        status, confidence, details = judge_lead(criteria, attrs)
        details = attach_citations(details, cand.get("passages", []))
        status, confidence = restate(criteria, details)
        page_type = cand.get("page_type", "unknown")
        if page_type in ("article", "directory"):
            from engine.models import CriterionState, CriterionVerdict
            details = [*details, CriterionVerdict(criterion="is a target entity, not content",
                                                  state=CriterionState.FAIL,
                                                  reason="page is %s, not an entity" % page_type,
                                                  confidence=0.9, evidence=[])]
            status = "DISQUALIFIED"  # content/lists about targets are not targets (mined separately)
        verdicts.append({"name": cand["name"], "domain": cand["domain"], "url": cand["url"],
                         "country": next((e["value"] for e in cand["attrs"].get("country", [])), ""),
                         "city": next((e["value"] for e in cand["attrs"].get("city", [])), ""),
                         "industry": next((e["value"] for e in cand["attrs"].get("industry", [])), ""),
                         "employee_count": next((e["value"] for e in cand["attrs"].get("employee_count", [])), ""),
                         "state": status, "confidence": confidence,
                         "evidence_count": sum(len(v) for v in cand["attrs"].values()),
                         "sources": [cand["url"]],
                         "criteria": [d.model_dump(mode="json") for d in details]})
    prior = {(v["domain"], v["name"]) for v in state.get("verdicts", [])}
    fresh = [v for v in verdicts if (v["domain"], v["name"]) not in prior]
    all_verdicts = [*state.get("verdicts", []), *fresh]
    all_why = {**state.get("why", {}),
               **{v["domain"] or v["name"]: v["criteria"] for v in fresh}}
    return {**_step(state, "qualify:+%d (%d total)" % (len(fresh), len(all_verdicts))),
            "verdicts": all_verdicts, "why": all_why}


def topup_node(state: S) -> dict:
    """Next wave: clear the empty-wave error, advance offset."""
    return {**_step(state, "topup:wave %d" % (state.get("wave", 0) + 1)),
            "wave": state.get("wave", 0) + 1, "error": ""}


def need_topup(state: S) -> str:
    """Delivered enough? Waves left? Pool left? The count-fulfillment decision."""
    desired = state.get("desired_count", 20)
    verdicts = state.get("verdicts", [])
    cap = int(desired * 0.4)
    delivered = sum(1 for v in verdicts if v["state"] == "QUALIFIED") \
        + min(sum(1 for v in verdicts if v["state"] == "UNCERTAIN"), cap)
    if delivered >= desired:
        return "dedupe"
    chunk = min(max(desired, 10), 15)
    if state.get("wave", 0) >= MAX_WAVES:
        return "dedupe"
    if (state.get("wave", 0) + 1) * chunk >= len(state.get("pool", [])):
        return "dedupe"
    return "research"


def split_delivery(merged: list[dict], why: dict, desired: int) -> tuple[list[dict], list[dict]]:
    """Delivered = qualified + uncertain capped at 40% of asked. The rest go to rejected WITH reasons."""
    from engine.judge import summarize_verdict
    cap = int(desired * 0.4)
    qualified = [m for m in merged if m["state"] == "QUALIFIED"]
    uncertain = [m for m in merged if m["state"] == "UNCERTAIN"]
    disqualified = [m for m in merged if m["state"] == "DISQUALIFIED"]
    delivered = qualified + uncertain[:cap]
    for record in delivered:
        record["verdict_summary"] = summarize_verdict(why.get(record["domain"] or record["name"], []))
    rejected = []
    for record in disqualified + uncertain[cap:]:
        reasons = ["%s: %s" % (c["criterion"], c["reason"])
                   for c in why.get(record["domain"] or record["name"], [])
                   if c["state"] != "PASS"]
        rejected.append({"name": record["name"], "domain": record["domain"],
                         "state": record["state"], "reasons": reasons or ["no supporting evidence"]})
    return delivered, rejected


def dedupe_node(state: S) -> dict:
    if not state.get("verdicts"):
        return {**_step(state, "dedupe:empty"), "leads": [], "rejected": [], "why": {}}
    records = [LeadRecord(name=v["name"], domain=v["domain"], website=v["url"], city=v["city"],
                          country=v["country"], industry=v["industry"],
                          employee_count=v["employee_count"], state=LeadState(v["state"]),
                          confidence=v["confidence"], evidence_count=v["evidence_count"],
                          sources=v["sources"]) for v in state["verdicts"]]
    merged = merge_leads(records)
    why = state.get("why", {})
    merged_why = {}
    for record in merged:
        seen: dict[str, dict] = {}
        for key in (record.domain, record.name):
            for item in why.get(key, []):
                seen.setdefault(item["criterion"], item)
        merged_why[record.domain or record.name] = list(seen.values())
    merged_dicts = [m.model_dump(mode="json") for m in merged]
    desired = state.get("desired_count", 20)
    delivered, rejected = split_delivery(merged_dicts, merged_why, desired)
    out: dict = {**_step(state, "dedupe:%d->%d, deliver %d, reject %d"
                       % (len(records), len(merged), len(delivered), len(rejected))),
                 "leads": delivered, "rejected": rejected, "why": merged_why}
    if state.get("verdicts"):
        out["error"] = ""  # waves produced verdicts; stale empty-wave errors don't fail the run
    return out


def export_node(state: S) -> dict:
    records = [LeadRecord.model_validate(v) for v in state["leads"]]
    fmt = state.get("output_format", "csv")
    data = to_csv(records) if fmt == "csv" else to_json(records)
    conflicts = [{"lead": c["name"], "attribute": s["attribute"], "values": s.get("values", [])}
                 for c in state.get("researched", []) for s in c.get("verification", [])
                 if s.get("conflict")]
    desired = state.get("desired_count", 20)
    shortfall = max(desired - len(records), 0)
    return {**_step(state, "export:%s" % fmt),
            "result": {"ok": True, "format": fmt, "count": len(records), "data": data,
                       "why": state.get("why", {}), "conflicts": conflicts,
                       "rejected": state.get("rejected", []), "shortfall": shortfall,
                       "shortfall_note": ("source exhaustion after %d waves" % (MAX_WAVES + 1)
                                          if shortfall else ""),
                       "quota": {"calls": router.call_counts(),
                                 "metered": {"apollo": router.spent("apollo"),
                                             "apify": router.spent("apify")}},
                       "steps": state.get("steps", [])}}


def _has_error(state: S) -> bool:
    return bool(state.get("error"))


def build():
    graph = StateGraph(S)
    for name, fn in [("compile", compile_node), ("plan", plan_node), ("discover", discover_node),
                     ("prefilter", prefilter_node), ("research", research_node),
                     ("enrich", enrich_node), ("verify", verify_node), ("qualify", qualify_node),
                     ("topup", topup_node), ("dedupe", dedupe_node), ("export", export_node)]:
        graph.add_node(name, fn)
    graph.set_entry_point("compile")
    graph.add_conditional_edges("compile", lambda s: END if s.get("error") else "plan")
    graph.add_edge("plan", "discover")
    graph.add_conditional_edges("discover", lambda s: END if s.get("error") else "prefilter")
    graph.add_conditional_edges("prefilter", lambda s: END if s.get("error") else "research")
    graph.add_conditional_edges("research", _after_research,
                                {"verify": "enrich", "research": "topup", "dedupe": "dedupe"})
    graph.add_edge("enrich", "verify")
    graph.add_edge("verify", "qualify")
    graph.add_conditional_edges("qualify", need_topup, {"research": "topup", "dedupe": "dedupe"})
    graph.add_edge("topup", "research")
    graph.add_edge("dedupe", "export")
    graph.add_edge("export", END)
    return graph


def _after_research(state: S) -> str:
    return "verify" if not state.get("error") else need_topup(state)


def _app():
    from contextlib import contextmanager

    from langgraph.checkpoint.sqlite import SqliteSaver

    from connectors.keys import ROOT

    @contextmanager
    def open_app():
        # from_conn_string is a context manager in this langgraph version — app lives inside it
        with SqliteSaver.from_conn_string(os.path.join(ROOT, "data", "reaver_graph.db")) as saver:
            yield build().compile(checkpointer=saver)

    return open_app()


def run_prospect(request: str, desired_count: int = 20, output_format: str = "csv",
                 llm_chain: list | None = None, business_context: dict | None = None) -> dict:
    """End-to-end run. Thread id = request hash, so reruns resume from checkpoint + cache."""
    from data.cache import make_key
    from engine.models import BusinessContext
    try:
        business = BusinessContext.model_validate(business_context or {}).model_dump()
    except Exception:
        business = BusinessContext().model_dump()
    config = {"configurable": {"thread_id": make_key("prospect", request, desired_count, business)}}
    initial: S = {"request": request, "desired_count": desired_count,
                  "output_format": output_format, "llm_chain": llm_chain or [],
                  "business": business, "steps": []}
    with _app() as app:
        final = app.invoke(initial, config)
    if final.get("error"):
        return {"ok": False, "tool": "prospect", "error": final["error"],
                "steps": final.get("steps", [])}
    result = dict(final.get("result", {}))
    result["steps"] = final.get("steps", [])
    result["tool"] = "prospect"
    return result


def stream_prospect(request: str, desired_count: int = 20, output_format: str = "csv",
                    llm_chain: list | None = None, business_context: dict | None = None):
    """Yields real node-completion events ({node, steps}), then the final result dict. No fabricated progress."""
    from data.cache import make_key
    from engine.models import BusinessContext
    try:
        business = BusinessContext.model_validate(business_context or {}).model_dump()
    except Exception:
        business = BusinessContext().model_dump()
    config = {"configurable": {"thread_id": make_key("prospect", request, desired_count, business)}}
    initial: S = {"request": request, "desired_count": desired_count,
                  "output_format": output_format, "llm_chain": llm_chain or [],
                  "business": business, "steps": []}
    with _app() as app:
        for chunk in app.stream(initial, config):
            for node, update in chunk.items():
                yield {"node": node, "steps": (update or {}).get("steps", [])}
        final = app.get_state(config).values
    if final.get("error"):
        yield {"node": "result",
               "result": {"ok": False, "tool": "prospect", "error": final["error"],
                          "steps": final.get("steps", [])}}
    else:
        result = dict(final.get("result", {}))
        result["steps"] = final.get("steps", [])
        result["tool"] = "prospect"
        yield {"node": "result", "result": result}
