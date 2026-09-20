"""Phase 1 acceptance, runnable: python -m engine.selfcheck. One assert per load-bearing behavior."""
from datetime import datetime, timedelta, timezone
from urllib import robotparser

from pydantic import ValidationError

from compliance import robots
from data import cache
from mesh import router

from .deterministic import (
    canonical_url,
    ensure_http_url,
    merge_leads,
    normalize_domain,
    normalize_name,
    summarize_attribute,
    to_csv,
)
from .models import Evidence, LeadRecord, LeadState, TargetSpec

_passed = 0


def check(name: str, condition: bool) -> None:
    global _passed
    assert condition, "FAIL: " + name
    _passed += 1
    print("pass: " + name)


def ev(attribute: str, value: str, days_old: int = 1) -> Evidence:
    return Evidence(attribute=attribute, value=value, source="https://example.com",
                    tier=1, observed_at=datetime.now(timezone.utc) - timedelta(days=days_old),
                    confidence=0.9)


def main() -> None:
    check("domain variants collapse", normalize_domain("HTTPS://WWW.Acme.com/pricing?x=1") == "acme.com")
    check("name suffix stripped", normalize_name("Acme Pvt. Ltd.") == "acme")
    check("canonical url", canonical_url("acme.com/") == "https://acme.com")
    try:
        ensure_http_url("ftp://acme.com")
        check("non-http rejected", False)
    except ValueError:
        check("non-http rejected", True)

    check("empty evidence unsupported",
          summarize_attribute("size", []).get("supported") is False)
    conflict = summarize_attribute("size", [ev("size", "120"), ev("size", "400")])
    check("conflict detected, no fake certainty",
          conflict["conflict"] is True and conflict["supported"] is False)
    check("near-identical numbers agree",
          summarize_attribute("size", [ev("size", "120"), ev("size", "125")])["supported"] is True)
    stale = summarize_attribute("hiring", [ev("hiring", "active", days_old=400)], ttl_days=90)
    check("stale marked stale", stale["stale"] is True and stale["supported"] is False)

    dupes = merge_leads([LeadRecord(name="Acme", domain="acme.com", sources=["a"]),
                         LeadRecord(name="Acme Inc", domain="https://www.acme.com/", sources=["b"])])
    check("duplicates merge, evidence unions",
          len(dupes) == 1 and sorted(dupes[0].sources) == ["a", "b"])
    disagree = merge_leads([LeadRecord(name="Acme", domain="acme.com", state=LeadState.QUALIFIED),
                            LeadRecord(name="Acme", domain="acme.com", state=LeadState.DISQUALIFIED)])
    check("verdict disagreement -> UNCERTAIN", disagree[0].state == LeadState.UNCERTAIN)

    csv_text = to_csv([LeadRecord(name="Acme", domain="acme.com")])
    check("csv header hubspot-compatible", csv_text.splitlines()[0].startswith("company,domain,website"))
    check("default state UNCERTAIN", LeadRecord(name="X").state == LeadState.UNCERTAIN)
    check("default format csv", TargetSpec(request="find 5 bakeries").output_format.value == "csv")
    try:
        TargetSpec(request="find 5 bakeries", desired_count=999)
        check("count cap enforced", False)
    except ValidationError:
        check("count cap enforced", True)

    cache.put("selfcheck:probe", {"a": 1}, 60)
    check("cache roundtrip", cache.get("selfcheck:probe") == {"a": 1})
    cache.put("selfcheck:dead", {"a": 1}, -1)
    check("expired cache misses", cache.get("selfcheck:dead") is None)

    parser = robotparser.RobotFileParser()
    parser.parse(["User-agent: *", "Disallow: /private"])
    check("robots logic blocks", not parser.can_fetch("*", "https://x.example/private/y"))
    check("robots logic allows", parser.can_fetch("*", "https://x.example/public"))
    check("robots blocks non-public hosts", robots.allowed("http://127.0.0.1/")[0] is False)

    router._spent["apollo"] = router.METERED_BUDGET["apollo"]
    capped = router.route("firmographic", "selfcheck victim should never hit network", n=1)
    router._spent["apollo"] = 0
    check("spend cap stops metered calls",
          capped["ok"] is False and "budget exhausted" in capped["fallbacks"][0]["note"])
    check("router covers all wired facts",
          set(router.ROUTES) >= {"web_search", "entity", "tech", "firmographic", "email",
                                 "structured", "page", "local", "video"})

    from connectors import backends as _backends
    from connectors.keys import BackendResult
    real_hunter, real_jina = _backends.hunter_domain, _backends.jina_fetch
    _backends.hunter_domain = lambda domain, n=3: BackendResult("hunter", "OK", items=[{"email": "a@b.c"}])
    _backends.jina_fetch = lambda url: BackendResult("jina", "OK", items=[{"url": url, "text": "t"}])
    try:
        check("kwargs backends dispatch",
              router.route("email", "x.example", n=1, domain="x.example", cache_ttl=0)["ok"] is True
              and router.route("page", "https://x.example", cache_ttl=0)["ok"] is True)
    finally:
        _backends.hunter_domain, _backends.jina_fetch = real_hunter, real_jina

    print("SELFCHECK PASS %d/%d" % (_passed, _passed))


if __name__ == "__main__":
    main()
