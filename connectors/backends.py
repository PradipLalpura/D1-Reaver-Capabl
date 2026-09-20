"""One function per backend, identical contract. Defensive parsing: shapes verified live, fields .get() with defaults."""
from __future__ import annotations

import shutil
import subprocess
import urllib.parse

from compliance import robots
from connectors import http
from connectors.keys import BackendResult, keys


def _try_keys(key_names: list[str], attempt) -> BackendResult:
    """Primary → fallback key. Reports which position worked; values never surface."""
    available = keys(*key_names)
    if not available:
        return BackendResult("", "UNAVAILABLE", note="no key configured")
    last: BackendResult | None = None
    for position, key in enumerate(available):
        last = attempt(key)
        last.note = ("primary key: " if position == 0 else "fallback key: ") + last.note
        if last.status == "OK":
            return last
    assert last is not None
    return last


def _snippets(backend: str, res: dict, rows: list, note: str) -> BackendResult:
    return BackendResult(backend, "OK" if res["http"] == 200 else "FAIL",
                         items=rows, latency_ms=res.get("ms", 0), note=note)


def tavily(query: str, n: int = 5) -> BackendResult:
    def attempt(key: str) -> BackendResult:
        res = http.call("https://api.tavily.com/search",
                        method="POST", headers={"Authorization": "Bearer " + key},
                        payload={"query": query, "max_results": n, "search_depth": "basic",
                                 "include_answer": False})
        if res["http"] == 401:
            return BackendResult("tavily", "FAIL", note="auth rejected (401)")
        data = http.json_body(res) or {}
        rows = [{"title": r.get("title", ""), "url": r.get("url", ""),
                 "snippet": (r.get("content") or "")[:500]} for r in data.get("results", [])]
        return _snippets("tavily", res, rows, "http %s" % res["http"])
    out = _try_keys(["TAVILY_PRIMARY_KEY", "TAVILY_FALLBACK_KEY"], attempt)
    out.backend = "tavily"
    return out


def serper(query: str, n: int = 5) -> BackendResult:
    def attempt(key: str) -> BackendResult:
        res = http.call("https://google.serper.dev/search", method="POST",
                        headers={"X-API-KEY": key}, payload={"q": query, "num": n})
        if res["http"] in (401, 403):
            return BackendResult("serper", "FAIL", note="auth rejected (%s)" % res["http"])
        data = http.json_body(res) or {}
        rows = [{"title": r.get("title", ""), "url": r.get("link", ""),
                 "snippet": (r.get("snippet") or "")[:500]} for r in data.get("organic", [])]
        return _snippets("serper", res, rows, "http %s" % res["http"])
    out = _try_keys(["SERPER_PRIMARY_KEY", "SERPER_FALLBACK_KEY"], attempt)
    out.backend = "serper"
    return out


def serpapi(query: str, n: int = 5) -> BackendResult:
    def attempt(key: str) -> BackendResult:
        url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(
            {"q": query, "num": n, "api_key": key})
        res = http.call(url)
        if res["http"] in (401, 403):
            return BackendResult("serpapi", "FAIL", note="auth rejected (%s)" % res["http"])
        data = http.json_body(res) or {}
        if isinstance(data, dict) and data.get("error"):
            return BackendResult("serpapi", "FAIL", note=str(data["error"])[:120])
        rows = [{"title": r.get("title", ""), "url": r.get("link", ""),
                 "snippet": (r.get("snippet") or "")[:500]}
                for r in (data.get("organic_results", []) if isinstance(data, dict) else [])]
        return _snippets("serpapi", res, rows, "http %s" % res["http"])
    out = _try_keys(["SERP_PRIMARY_KEY", "SERP_FALLBACK_KEY"], attempt)
    out.backend = "serpapi"
    return out


def exa(query: str, n: int = 5) -> BackendResult:
    def attempt(key: str) -> BackendResult:
        res = http.call("https://api.exa.ai/search", method="POST",
                        headers={"x-api-key": key},
                        payload={"query": query, "numResults": n,
                                 "contents": {"text": {"maxCharacters": 500}}})
        if res["http"] in (401, 403):
            return BackendResult("exa", "FAIL", note="auth rejected (%s)" % res["http"])
        data = http.json_body(res) or {}
        rows = [{"title": r.get("title", ""), "url": r.get("url", ""),
                 "snippet": ((r.get("text") or "")[:500])} for r in data.get("results", [])]
        return _snippets("exa", res, rows, "http %s" % res["http"])
    out = _try_keys(["EXA_PRIMARY_KEY", "EXA_FALLBACK_KEY"], attempt)
    out.backend = "exa"
    return out


def github(query: str, n: int = 5) -> BackendResult:
    token = keys("GITHUB_ACCESS_TOKEN")
    headers = {"Authorization": "Bearer " + token[0]} if token else {}
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
        {"q": query, "per_page": min(n, 10)})
    res = http.call(url, headers=headers)
    if res["http"] in (401, 403):
        return BackendResult("github", "FAIL", latency_ms=res.get("ms", 0), note="auth/rate rejected")
    data = http.json_body(res) or {}
    rows = [{"title": r.get("full_name", ""), "url": r.get("html_url", ""),
             "snippet": (r.get("description") or "")[:500]} for r in data.get("items", [])]
    note = "authenticated" if token else "anonymous (lower rate limit)"
    return _snippets("github", res, rows, "http %s, %s" % (res["http"], note))


def apollo_org(query: str, n: int = 3) -> BackendResult:
    """Firmographics. Metered — router enforces the per-run budget before calling."""
    def attempt(key: str) -> BackendResult:
        res = http.call("https://api.apollo.io/v1/organizations/search", method="POST",
                        headers={"x-api-key": key},
                        payload={"q_organization_name": query, "page": 1, "per_page": min(n, 10)})
        if res["http"] in (401, 403):
            return BackendResult("apollo", "FAIL", note="auth/plan rejected (%s)" % res["http"])
        data = http.json_body(res) or {}
        orgs = data.get("organizations", []) or data.get("accounts", [])
        rows = [{"name": o.get("name", ""), "domain": o.get("primary_domain") or o.get("website_url", ""),
                 "industry": o.get("industry", ""), "size": str(o.get("estimated_num_employees", "")),
                 "city": o.get("city", ""), "country": o.get("country", "")} for o in orgs]
        return _snippets("apollo", res, rows, "http %s" % res["http"])
    out = _try_keys(["APOLLO_API_KEY"], attempt)
    out.backend = "apollo"
    return out


def hunter_domain(domain: str, n: int = 3) -> BackendResult:
    """Email verification signal. Metered — router enforces the per-run budget before calling."""
    available = keys("HUNTER_API_KEY")
    if not available:
        return BackendResult("hunter", "UNAVAILABLE", note="no key configured")
    url = "https://api.hunter.io/v2/domain-search?" + urllib.parse.urlencode(
        {"domain": domain, "limit": min(n, 10), "api_key": available[0]})
    res = http.call(url)
    if res["http"] in (401, 403):
        return BackendResult("hunter", "FAIL", note="auth rejected (%s)" % res["http"])
    data = (http.json_body(res) or {}).get("data", {})
    rows = [{"email": e.get("value", ""), "confidence": e.get("confidence", 0),
             "type": e.get("type", "")} for e in data.get("emails", [])]
    return _snippets("hunter", res, rows, "http %s" % res["http"])


APIFY_ALLOWLIST = {
    "maps": "apify/google-maps-scraper",
    "crawler": "apify/website-content-crawler",
}
# ponytail: 2 actors; more only after a demo target proves unreachable without them


def apify_run(actor_kind: str, run_input: dict) -> BackendResult:
    """Generic actor runner. Allowlisted actors only; spend cap enforced by the router."""
    actor = APIFY_ALLOWLIST.get(actor_kind)
    if actor is None:
        return BackendResult("apify", "FAIL", note="actor not allowlisted")
    available = keys("APIFY_PRIMARY_KEY", "APIFY_FALLBACK_KEY", "APIFY_FALLBACK_KEY_2")
    if not available:
        return BackendResult("apify", "UNAVAILABLE", note="no key configured")
    key = available[0]
    base = "https://api.apify.com/v2/acts/%s/runs?token=%s" % (actor.replace("/", "~"), key)
    started = http.call(base, method="POST", payload=run_input)
    data = http.json_body(started) or {}
    run_id = (data.get("data") or {}).get("id", "")
    if started["http"] not in (200, 201) or not run_id:
        return BackendResult("apify", "FAIL", latency_ms=started.get("ms", 0),
                             note="run start http %s" % started["http"])
    dataset = (data.get("data") or {}).get("defaultDatasetId", "")
    if not dataset:
        return BackendResult("apify", "FAIL", note="no dataset id")
    items_url = "https://api.apify.com/v2/datasets/%s/items?token=%s&limit=20" % (dataset, key)
    # ponytail: single immediate fetch, no polling loop; SUCCEEDED-or-empty is reported, long runs surface as empty + note
    got = http.call(items_url, timeout=30)
    items = http.json_body(got) or []
    return BackendResult("apify", "OK" if got["http"] == 200 else "FAIL",
                         items=items if isinstance(items, list) else [],
                         latency_ms=started.get("ms", 0) + got.get("ms", 0),
                         note="actor %s, dataset items fetched once" % actor)


def jina_fetch(url: str) -> BackendResult:
    """Page text via Jina Reader. Robots gate is unconditional — no bypass parameter exists."""
    ok, reason = robots.allowed(url)
    if not ok:
        return BackendResult("jina", "FAIL", note="skipped: " + reason)
    res = http.call("https://r.jina.ai/" + url)
    if res["http"] != 200:
        return BackendResult("jina", "FAIL", latency_ms=res.get("ms", 0),
                             note="reader http %s" % res["http"])
    text = res["body"].decode("utf-8", "replace")
    return BackendResult("jina", "OK", items=[{"url": url, "text": text[:4000]}],
                         latency_ms=res.get("ms", 0),
                         note="truncated=%s" % res.get("truncated", False))


def osm_search(query: str, n: int = 5) -> BackendResult:
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": query, "format": "jsonv2", "limit": min(n, 10)})
    res = http.call(url, headers={"Accept": "application/json"})
    data = http.json_body(res) or []
    rows = [{"title": r.get("display_name", ""), "url": "",
             "snippet": "%s/%s" % (r.get("type", ""), r.get("class", ""))} for r in data]
    return _snippets("osm", res, rows, "http %s" % res["http"])


def youtube_search(query: str, n: int = 5) -> BackendResult:
    exe = shutil.which("yt-dlp")
    if exe is None:
        return BackendResult("youtube", "UNAVAILABLE", note="yt-dlp not installed")
    try:
        proc = subprocess.run([exe, "--skip-download", "--print", "%(title)s | %(id)s",
                               "ytsearch%d:%s" % (min(n, 5), query)],
                              capture_output=True, text=True, timeout=60)
    except (subprocess.SubprocessError, OSError) as exc:
        return BackendResult("youtube", "FAIL", note=type(exc).__name__)
    rows = [{"title": line.rsplit(" | ", 1)[0], "url": "https://www.youtube.com/watch?v=" + line.rsplit(" | ", 1)[-1],
             "snippet": ""} for line in proc.stdout.splitlines() if " | " in line]
    return BackendResult("youtube", "OK" if proc.returncode == 0 else "FAIL",
                         items=rows, note="yt-dlp exit %d" % proc.returncode)
