# REAVER — universal MCP-first lead intelligence (Capabl AI Hackathon 2026, D1)

Describe any legitimate target in plain words. REAVER discovers, researches, verifies,
qualifies, deduplicates, and exports leads as **CSV (default) or JSON** — with cited evidence,
never invented facts.

## Quickstart

```bash
pip install -r requirements.txt
cp .env.example .env   # fill your keys; .env is gitignored and never committed
python -m engine.selfcheck   # 36 checks, offline
python evals/run.py           # 8 evals, one free fetch
python scripts/demo.py        # golden run: checks + evals + cached prospect + secret scan
```

## MCP server (Mode 1 — AI hosts)

```bash
python -m reaver_mcp.server --transport stdio          # Claude / OpenCode / local hosts
python -m reaver_mcp.server --transport http --port 8000
```

### Connect Claude Code / Claude Desktop (local, today)

```bash
claude mcp add reaver -- python -m reaver_mcp.server --transport stdio
```

Claude Desktop: same command + args in `Settings → Connectors → Add MCP server`.
Then ask: *"find 20 bakeries in Ahmedabad"* — Claude discovers `prospect` and calls it.

### Connect ChatGPT / Claude API (remote — needs public HTTPS)

Both verified paths (OpenAI Apps SDK plugin model; Anthropic `mcp_servers` URL
connector, beta `mcp-client-2025-11-20`) require the MCP on a public HTTPS URL —
localhost is rejected by both. Steps:

```bash
# 1. expose with a token (refuses non-loopback binds without one)
python -m reaver_mcp.server --transport http --host 0.0.0.0 --port 8000 --token $REAVER_MCP_TOKEN
# 2. terminate TLS in front (Caddy/nginx/Cloudflare Tunnel) → https://your-host/mcp/
```

- ChatGPT: developer mode → Connectors → add `https://your-host/mcp/` (Apps SDK plugin packaging for directory listing).
- Claude API: `"mcp_servers": [{"type": "url", "url": "https://your-host/mcp/",
  "name": "reaver", "authorization_token": "<same token>"}]` + `mcp_toolset`.
- Zero-deploy interim for your own testing: point a localhost tunnel (ngrok/cloudflared)
  at port 8000 and paste the tunnel URL instead. Same token, same auth.

Tools: `prospect` (end-to-end) + `discover_leads, research_target, enrich_lead,
qualify_lead, verify_evidence, deduplicate_leads, refresh_leads, export_leads` + `doctor`.
`output_format` is `csv` (default) or `json` — nothing else.

## Playground (Mode 2 — BYOK)

```bash
python -m playground.server --port 8080   # open http://127.0.0.1:8080
```

Landing at `/`, app at `/playground`. Bring primary + fallback provider/model/key
(groq, gemini, openrouter, openai, anthropic). Keys live in server memory for 30 minutes,
are never logged, never echoed, and are scrubbed from every response. Same engine as the MCP —
no duplicated agent logic.

## Architecture

```text
host model / playground BYOK keys
  -> MCP tools (reaver_mcp/server.py)
    -> LangGraph (agent/graph.py): compile > plan > discover > prefilter > research > verify > qualify > dedupe > export
      -> source mesh (connectors/ + mesh/router.py): tavily/serper/serpapi/exa/github/apollo/hunter/apify/jina/osm/yt-dlp
      -> compliance gate (compliance/robots.py) on every fetch, SQLite cache (data/cache.py)
```

LLM extracts and plans; code grades, merges, and exports. No evidence = UNKNOWN, conflict =
UNCERTAIN, robots-blocked = skipped with reason.

## HubSpot import (dry-tested shape)

`export_leads` CSV columns map 1:1 to HubSpot company/contact properties:

```text
company→Name, domain→Website Domain, website→Website URL, city→City,
country→Country, industry→Industry, employee_count→Employees,
contact_name→First/Last Name (split on import), contact_email→Email
```

Import path: Contacts/Companies → Import → CSV → map the columns above →
`lead_state`/`confidence`/`evidence_count` land in custom properties. No CRM sync in
MVP — the file is the handoff, and it imports without column edits.

## Docs

- Product/architecture brief: `D1_Universal_Lead_Intelligence_MCP_Ideation.md`
- Build plan + changelog: `PHASES.md`, universal sequel: `PHASES_UNIVERSAL.md`
- User docs (canonical): `/mcp-docs` — setup per host, tool reference, troubleshooting
- Zero-terminal onboarding: `/connect` — token issuance + GUI guides

## Deploy (single domain: Vercel static + Railway Python)

```text
reaver.antarik.co/            Vercel (static landing + UI assets, free CDN)
reaver.antarik.co/playground
reaver.antarik.co/api/*       Railway `playground` service (Python, same code)
reaver.antarik.co/mcp/        Railway `reaver-mcp` service (bearer-guarded)
```

Glue is `vercel.json` rewrites (same-origin throughout, so no CORS work).
Replace `REAVER_PLAYGROUND_HOST` / `REAVER_MCP_HOST` with the two Railway
hostnames when the services exist.

| Service | Start command | Env |
|---|---|---|
| `playground` | `python -m playground.server --host 0.0.0.0 --port $PORT` | all `.env` keys as secrets |
| `reaver-mcp` | `python -m reaver_mcp.server --transport http --host 0.0.0.0 --port $PORT` | same keys + `REAVER_MCP_TOKEN` (generate: `python -c "import secrets;print(secrets.token_hex(24))"`) |

Then: Cloudflare `reaver` CNAME → Vercel (`cname.vercel-dns.com`); Vercel project
from this repo. ChatGPT connectors / Claude `mcp_servers` → `https://reaver.antarik.co/mcp/`
with the token; judges use `https://reaver.antarik.co/playground` with their own BYOK keys.
Zero-deploy interim: `cloudflared tunnel --url http://127.0.0.1:8000` and paste the URL.
Stream fallback: if Vercel truncates multi-minute SSE/MCP streams, point
`app-`/`mcp-` subdomains straight at Railway (DNS-only, no code change).
