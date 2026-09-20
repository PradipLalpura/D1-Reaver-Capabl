"""Capability router: ordered backends per fact type, fallback records, metered budgets, result cache."""
from __future__ import annotations

import os
import time
from collections import defaultdict

from connectors import backends
from data import cache

ROUTES = {
    "web_search": ["tavily", "serper", "serpapi", "exa"],
    "entity": ["exa", "tavily"],
    "tech": ["github"],
    "firmographic": ["apollo"],
    "email": ["hunter"],
    "structured": ["apify"],
    "page": ["jina"],
    "local": ["osm"],
    "video": ["youtube"],
}

METERED_BUDGET = {
    "apollo": int(os.environ.get("REAVER_APOLLO_BUDGET", "25")),
    "apify": int(os.environ.get("REAVER_APIFY_BUDGET", "5")),
}

SEARCH_TTL = 6 * 3600

_spent: dict[str, int] = defaultdict(int)
_last: dict[str, str] = {}
_stats: dict[str, dict] = {}
_calls: dict[str, int] = defaultdict(int)


def spent(backend: str) -> int:
    return _spent[backend]


def call_counts() -> dict[str, int]:
    """Per-backend attempt counts this process. Powers quota reporting, not billing."""
    return dict(_calls)


def last_state() -> dict[str, str]:
    return dict(_last)


def last_stats() -> dict[str, dict]:
    """Last-known per-backend outcome + latency. Memory only, never probed — quota-safe."""
    return {k: dict(v) for k, v in _stats.items()}


def _call(backend: str, query: str, n: int, **kw):
    if backend in METERED_BUDGET and _spent[backend] >= METERED_BUDGET[backend]:
        return {"status": "FAIL", "items": [], "note": "run budget exhausted (%d)" % METERED_BUDGET[backend]}
    direct = {"tavily": backends.tavily, "serper": backends.serper, "serpapi": backends.serpapi,
              "exa": backends.exa, "github": backends.github, "apollo": backends.apollo_org,
              "osm": backends.osm_search, "youtube": backends.youtube_search}
    if backend in direct:
        out = direct[backend](query, n)
    elif backend == "hunter":
        out = backends.hunter_domain(kw.get("domain", query), n)
    elif backend == "apify":
        out = backends.apify_run(kw.get("actor_kind", ""), kw.get("run_input", {}))
    elif backend == "jina":
        out = backends.jina_fetch(query)
    else:
        return {"status": "FAIL", "items": [], "note": "unknown backend"}
    if backend in METERED_BUDGET and out.status == "OK":
        _spent[backend] += 1
    _calls[backend] += 1
    _last[backend] = out.status + ": " + out.note
    _stats[backend] = {"status": out.status, "ms": out.latency_ms, "note": out.note,
                       "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    return {"status": out.status, "items": out.items, "note": out.note, "ms": out.latency_ms}


def route(fact: str, query: str, n: int = 5, cache_ttl: int = SEARCH_TTL, **kw) -> dict:
    """First healthy backend wins; every fallback recorded. OK results cached; failures never cached."""
    started = time.time()
    fallbacks: list[dict] = []
    skipped = set(kw.get("skip", []))
    key = cache.make_key("route", fact, query, n, kw.get("actor_kind", ""), kw.get("domain", ""))
    if fact in ("web_search", "entity", "local"):
        hit = cache.get(key)
        if hit is not None:
            hit = dict(hit)
            hit["cached"] = True
            return hit
    for backend in ROUTES.get(fact, []):
        if backend in skipped:
            continue
        # ponytail: apify/hunter/jina take kwargs, not (query, n) — dispatched inside _call, not worth a plugin framework
        out = _call(backend, query, n, **kw)
        if out["status"] == "OK":
            result = {"ok": True, "fact": fact, "backend": backend, "fallbacks": fallbacks,
                      "items": out["items"], "cached": False,
                      "ms": int((time.time() - started) * 1000)}
            if fact in ("web_search", "entity", "local"):
                cache.put(key, result, cache_ttl)
            return result
        fallbacks.append({"backend": backend, "status": out["status"], "note": out["note"]})
    return {"ok": False, "fact": fact, "backend": "", "fallbacks": fallbacks, "items": [],
            "cached": False, "ms": int((time.time() - started) * 1000)}
