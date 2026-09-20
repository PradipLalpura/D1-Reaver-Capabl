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
- Build plan + changelog: `PHASES.md`
