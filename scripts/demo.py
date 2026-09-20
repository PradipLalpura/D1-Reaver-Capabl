"""REAVER golden run: selfcheck + evals + cached live prospect + secret scan. python scripts/demo.py."""
import subprocess
import sys

ROOT = "."
failures = []


def step(name, *cmd):
    print("== " + name)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    print(proc.stdout[-1500:])
    if proc.returncode != 0:
        print(proc.stderr[-1000:])
        failures.append(name)


step("selfcheck", sys.executable, "-m", "engine.selfcheck")
step("evals", sys.executable, "evals/run.py")

print("== secret scan (tracked files must hold zero key material)")
import subprocess as _sp
tracked = _sp.run(["git", "ls-files"], capture_output=True, text=True).stdout.split()
patterns = ("tvly-", "gsk_", "sk-or-v1", "ghp_", "apify_api_", "AIza", "xox", "AKIA")
hits = [f for f in tracked for p in patterns
        if p in open(f, encoding="utf-8", errors="ignore").read() and ".env" not in f]
if hits:
    print("LEAKED:", hits)
    failures.append("secret scan")
else:
    print("pass: no key material in %d tracked files" % len(tracked))

print("== cached live prospect (warm caches: cheap by design)")
step("prospect", sys.executable, "-c",
     "import sys; sys.path.insert(0, '.');"
     " from agent.graph import run_prospect;"
     " out = run_prospect('Find 6 bakeries in Ahmedabad, India, in the food/bakery business.', 6, 'csv');"
     " print('leads:', out.get('count'), '| steps:', ' > '.join(out.get('steps', [])));"
     " assert out.get('ok') and out.get('count', 0) >= 1, out.get('error')")

if failures:
    print("DEMO FAIL:", failures)
    sys.exit(1)
print("DEMO GREEN")
