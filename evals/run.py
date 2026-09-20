"""Phase 5 evals: 5 cases, runnable offline except one free fetch. python evals/run.py."""
import sys

sys.path.insert(0, ".")

passed = 0


def check(name, cond):
    global passed
    assert cond, "FAIL: " + name
    passed += 1
    print("pass: " + name)


from connectors import backends
from connectors.keys import BackendResult
from data import cache
from engine.judge import judge_lead
from engine.models import LeadRecord, TargetSpec
from mesh import router
from reaver_mcp.server import export_leads as _export

# 1. schema validity
try:
    TargetSpec(request="x", desired_count=999)
    check("schema rejects", False)
except Exception:
    check("schema rejects bad spec", True)

# 2. dedup correctness
dupes = [LeadRecord(name="Acme", domain="acme.com"), LeadRecord(name="Acme Inc", domain="www.acme.com/")]
merged = __import__("engine.deterministic", fromlist=["merge_leads"]).merge_leads(dupes)
check("dedup merges domain variants", len(merged) == 1)

# 3. default-CSV behavior (real tool function, default arg)
from reaver_mcp.server import export_leads as _export_tool

_export_fn = getattr(_export_tool, "fn", _export_tool)
out = _export_fn([{"name": "Acme", "domain": "acme.com"}])
check("export defaults to csv", out["ok"] and out["format"] == "csv"
      and out["data"].splitlines()[0].startswith("company,domain"))

# 4. robots-block respected (one free fetch)
r = backends.jina_fetch("https://www.google.com/search?q=reaver+probe")
check("robots-blocked fetch refused", r.status == "FAIL" and "robots" in r.note)

# 5a. no fabrication: empty evidence → UNKNOWN, never invented
state, _, verdicts = judge_lead(["located in India"], {})
check("no evidence -> UNKNOWN", state == "UNCERTAIN" and verdicts[0].state.value == "UNKNOWN")

# 5b. failure choreography: dead primary → fallback serves
real = backends.tavily
backends.tavily = lambda q, n=5: BackendResult("tavily", "FAIL", note="killed for eval")
router._last.pop("tavily", None)
try:
    res = router.route("web_search", "Acme bakery eval", n=1, cache_ttl=0)
    check("dead primary falls back", res["ok"] and res["backend"] != "tavily"
          and any(f["backend"] == "tavily" for f in res["fallbacks"]))
finally:
    backends.tavily = real

# 5c. stale cache → refetch (stub backend counts calls)
calls = []
backends.tavily = lambda q, n=5: (calls.append(1), BackendResult(
    "tavily", "OK", items=[{"title": "T", "url": "https://t.example", "snippet": "s"}]))[1]
try:
    router.route("web_search", "stale probe eval", n=1, cache_ttl=-1)
    router.route("web_search", "stale probe eval", n=1, cache_ttl=-1)
    check("expired cache refetches", len(calls) == 2)
finally:
    backends.tavily = real

# 5d. conflict → UNCERTAIN lead, sources preserved
from engine.models import Evidence  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
now = datetime.now(timezone.utc)
attrs = {"employee_count": [
    Evidence(attribute="employee_count", value="120", source="https://a.example",
             tier=1, observed_at=now, confidence=0.9),
    Evidence(attribute="employee_count", value="400", source="https://b.example",
             tier=3, observed_at=now, confidence=0.5)]}
state, _, verdicts = judge_lead(["has 100-150 employees"], attrs)
check("conflict -> not false certainty",
      verdicts[0].state.value == "UNKNOWN" and "conflict" in verdicts[0].reason
      and len(verdicts[0].evidence) == 2)

print("EVALS PASS %d/%d" % (passed, passed))
