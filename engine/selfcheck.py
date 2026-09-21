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
    check("custom needs https base",
          valid_slot({"provider": "custom", "model": "m", "key": "k" * 16,
                      "base_url": "http://x.example"}) is None)
    check("custom https accepted",
          valid_slot({"provider": "custom", "model": "m", "key": "k" * 16,
                      "base_url": "https://x.example/v1"}) == ("custom", "m", "k" * 16, "https://x.example/v1"))
    from provider.llm import _chain
    chained = _chain([("custom", "m", "k" * 16, "https://x.example/v1"), ("nope", "m", "k" * 16)])
    check("chain keeps valid custom only", chained == [("custom", "m", "k" * 16, "https://x.example/v1")])
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

    from reaver_mcp.server import requires_token
    check("loopback needs no token", requires_token("127.0.0.1") is False)
    check("public bind demands token",
          requires_token("0.0.0.0") is True and requires_token("example.com") is True)

    from agent.graph import enrich_node, need_topup, split_delivery
    fake = lambda name, state: {"name": name, "domain": name + ".com", "state": state}
    why = {"a.com": [{"criterion": "located in India", "state": "FAIL",
                      "reason": "location mismatch"}]}
    delivered, rejected = split_delivery(
        [fake("q1", "QUALIFIED"), fake("q2", "QUALIFIED")] + [fake("u%d" % i, "UNCERTAIN") for i in range(10)]
        + [fake("d1", "DISQUALIFIED")], {**{"q1.com": [], "q2.com": []},
                                         **{"u%d.com" % i: [] for i in range(10)}, **why}, 20)
    check("uncertain capped at 40pct", len(delivered) == 10 and len(rejected) == 3)
    check("rejected carry reasons",
          any(r["name"] == "d1" for r in rejected))
    st = {"desired_count": 20, "wave": 0, "pool": [{}] * 40,
          "verdicts": [{"state": "QUALIFIED"}]}
    check("short pool tops up", need_topup(st) == "research")
    st["wave"] = 2
    check("waves capped", need_topup(st) == "dedupe")
    st2 = {"desired_count": 20, "wave": 0, "pool": [],
           "verdicts": [{"state": "QUALIFIED"}] * 12 + [{"state": "UNCERTAIN"}] * 20}
    check("enough delivered stops", need_topup(st2) == "dedupe")

    from mesh import router as _router
    real_route = _router.route
    _router.route = lambda fact, query, n=1, **kw: {
        "ok": True, "backend": "stub", "fallbacks": [], "cached": False,
        "items": [{"name": "Acme", "domain": "acme.com", "industry": "software",
                   "size": "50", "city": "Pune", "country": "India"}]
        if fact == "firmographic" else
        [{"email": "hi@acme.com", "confidence": 90, "type": "personal"}]
        if fact == "email" else
        [{"title": "Acme, Pune, India", "url": "", "snippet": ""}]
        if fact == "local" else []}
    try:
        st = {"spec": {"industry": "software", "geography": "India"},
              "researched": [{"name": "Acme", "domain": "acme.com",
                              "url": "https://acme.com", "attrs": {}}]}
        enrich_node(st)
        got = st["researched"][0]["attrs"]
        check("enrich fills every gap source",
              set(got) >= {"industry", "employee_count", "city", "country", "contact_email"})
        st2 = {"spec": {}, "researched": [{"name": "Acme", "domain": "acme.com",
                                           "url": "https://acme.com",
                                           "attrs": {"industry": [{"v": 1}]}}]}
        enrich_node(st2)
        after = st2["researched"][0]["attrs"]
        check("page evidence never overwritten", after["industry"] == [{"v": 1}])
    finally:
        _router.route = real_route

    from engine.judge import summarize_verdict
    summary = summarize_verdict([{"criterion": "located in India", "state": "PASS", "reason": "matched"},
                                 {"criterion": "has staff", "state": "UNKNOWN", "reason": "no evidence"}])
    check("verdict summary reads", summary == "1/2 criteria pass; has staff: no evidence")
    recs = [dict(LeadRecord(name="Acme", domain="acme.com").model_dump(), state="QUALIFIED")]
    delivered, _ = split_delivery(recs, {"acme.com": [{"criterion": "c", "state": "PASS", "reason": "r"}]}, 20)
    check("delivered carry summaries", delivered[0]["verdict_summary"] == "1/1 criteria pass")
    csv_text = to_csv([LeadRecord.model_validate(delivered[0])])
    check("csv carries verdict_summary", "verdict_summary" in csv_text.splitlines()[0])

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

    import scripts.setup_mcp as _setup
    check("12 hosts printable",
          len(_setup.HOSTS) == 12 and all(_setup._print(h).strip() for h in _setup.HOSTS))
    check("kimi uses stdio transport", "--transport stdio" in _setup._print("kimi"))

    import os as _os
    import tempfile as _tf
    _os.environ["REAVER_DB"] = _os.path.join(_tf.mkdtemp(), "t.db")
    from engine.tokens import check as _tcheck, issue as _tissue, revoke as _trevoke, usage as _tusage
    token = _tissue("selfcheck", cap=2)
    check("token issued once-shaped", token.startswith("rvr_") and len(token) > 20)
    check("token checks true", _tcheck(token)[0] is True)
    check("second use true", _tcheck(token)[0] is True)
    check("cap trips", _tcheck(token) == (False, "daily cap exhausted"))
    check("unknown rejected", _tcheck("rvr_nope") == (False, "unknown token"))
    check("revoke works", _trevoke("selfcheck") == 1 and _tcheck(token)[0] is False)
    check("usage lists", any(r["label"] == "selfcheck" for r in _tusage()))
    del _os.environ["REAVER_DB"]

    from data import cache as _cache
    from provider import llm as _llm
    real_list, real_get, real_put = _llm._list_models, _cache.get, _cache.put
    _cache.get = lambda k: None
    _cache.put = lambda k, v, ttl: None
    try:
        _llm._list_models = lambda p, k: ["openai/gpt-oss-20b", "whisper-large-v3"]
        check("live default kept", _llm.resolve_model("groq") == "openai/gpt-oss-20b")
        _llm._list_models = lambda p, k: ["some/new-chat-model", "whisper-large-v3"]
        check("rotted default overridden", _llm.resolve_model("groq") == "some/new-chat-model")
        _llm._list_models = lambda p, k: None
        check("list failure falls back", _llm.resolve_model("groq") == "openai/gpt-oss-20b")
    finally:
        _llm._list_models, _cache.get, _cache.put = real_list, real_get, real_put

    print("SELFCHECK PASS %d/%d" % (_passed, _passed))


if __name__ == "__main__":
    main()
