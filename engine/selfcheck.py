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

    from engine.judge import judge_criterion, judge_lead
    attrs = {"country": [ev("country", "India")], "industry": [ev("industry", "bakery")]}
    check("location pass", judge_criterion("located in India", attrs).state.value == "PASS")
    check("location fail", judge_criterion("located in France", attrs).state.value == "FAIL")
    check("industry pass", judge_criterion("operates in bakery", attrs).state.value == "PASS")
    check("absence is unknown",
          judge_criterion("has 50 employees", attrs).state.value == "UNKNOWN")
    check("no evidence is unknown",
          judge_criterion("located in India", {}).state.value == "UNKNOWN")
    state, _, _ = judge_lead(["located in India", "operates in bakery"], attrs)
    check("lead qualifies on evidence", state == "QUALIFIED")
    state, _, _ = judge_lead(["located in France", "operates in bakery"], attrs)
    check("hard mismatch disqualifies", state == "DISQUALIFIED")

    from playground.server import RUN_COUNT, SESSIONS, _preview, check_rate, new_sid, valid_slot
    check("bad slot rejected", valid_slot({"provider": "nope", "model": "m", "key": "k" * 8}) is None)
    check("short key rejected",
          valid_slot({"provider": "groq", "model": "m", "key": "short"}) is None)
    slot = valid_slot({"provider": "Groq", "model": "m", "key": "k" * 16})
    check("slot normalized", slot is not None and slot[0] == "groq")
    RUN_COUNT.pop("selfcheck-ip", None)
    for _ in range(10):
        check_rate("selfcheck-ip")
    check("rate limit trips", check_rate("selfcheck-ip") is False)
    RUN_COUNT.pop("selfcheck-ip", None)
    sid = new_sid()
    SESSIONS[sid] = {"created": 0.0, "primary": None, "fallback": None, "lock": None}
    from playground import server as _pg
    _pg.sweep()
    check("expired sessions purged", sid not in SESSIONS)
    check("short sids unique", new_sid() != new_sid())
    preview = _preview({"format": "csv",
                        "data": 'company,domain\n"Acme, Inc",acme.com\n'})
    check("preview parses quoted csv", preview and preview[0]["company"] == "Acme, Inc")

    from evidence import rag
    long_text = " ".join("Sentence %d about bakeries in Ahmedabad with fresh bread." % i for i in range(30))
    chunks = rag.chunk(long_text)
    check("chunker splits", len(chunks) >= 2 and all(len(c) <= 500 for c in chunks))
    check("cosine identity", abs(rag.cosine([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-9)
    pool = [{"id": "a#0", "text": "unrelated weather report", "vector": None},
            {"id": "a#1", "text": "bakery in Ahmedabad baking fresh bread", "vector": None}]
    hits = rag.retrieve("operates in bakery Ahmedabad", pool)
    check("retrieve ranks keyword passage", hits and hits[0]["id"] == "a#1")
    check("empty pool retrieves nothing", rag.retrieve("operates in bakery", []) == [])

    from engine.judge import attach_citations
    from engine.models import CriterionVerdict
    passing = [CriterionVerdict(criterion="operates in bakery", state="PASS",
                                reason="keyword evidenced", confidence=0.7, evidence=[])]
    stripped = attach_citations(passing, [])
    check("ablation: no passages flips PASS to UNKNOWN",
          stripped[0].state.value == "UNKNOWN" and not stripped[0].citations)
    kept = attach_citations([CriterionVerdict(criterion="operates in bakery", state="PASS",
                                              reason="keyword evidenced", confidence=0.7, evidence=[])], pool)
    check("ablation: cited PASS survives",
          kept[0].state.value == "PASS" and kept[0].citations == ["a#1"])

    summary = summarize_attribute("size", [ev("size", "120"), ev("size", "400")])
    check("summaries carry conflicting values", summary["values"] == ["120", "400"])
    check("router stats recorded", isinstance(router.last_stats(), dict))

    from agent.graph import _coerce_spec
    from engine.models import BusinessContext
    plain = _coerce_spec({"geography": "Ahmedabad, India", "industry": "bakery", "criteria": []})
    check("spec fills missing criteria",
          plain is not None and len(plain["criteria"]) == 2)
    boosted = _coerce_spec({"geography": "Ahmedabad, India", "industry": "bakery", "criteria": []},
                           {"ideal_buyer": "retail bakeries", "dealbreakers": ["chains"]})
    check("business context sharpens criteria",
          boosted is not None and any("serves retail bakeries" in c for c in boosted["criteria"])
          and any("must not be chains" in c for c in boosted["criteria"]))
    check("junk business dropped",
          _coerce_spec({"criteria": ["located in India"]}, {"ideal_buyer": 123}) is not None)
    try:
        BusinessContext(business_name="x" * 500)
        check("business model caps lengths", False)
    except ValidationError:
        check("business model caps lengths", True)

    print("SELFCHECK PASS %d/%d" % (_passed, _passed))


if __name__ == "__main__":
    main()
