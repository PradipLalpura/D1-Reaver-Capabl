# REAVER — Build Phases (P0 / P1 / P2)

> Source of truth for build order. Ideation brief = product spec (`D1_Universal_Lead_Intelligence_MCP_Ideation.md`).
> This file = execution plan. Phase 0 analysis is done; implementation starts at Phase 1.
> Stack lock (ponytail default, change only with reason): **Python + FastMCP + LangGraph + SQLite + single web UI**.
> No code from this file alone — each phase is built, run, and accepted before the next starts.

**Conventions:** `P0` = demo dies without it. `P1` = highly valuable, demo-safe to defer. `P2` = only if P0+P1 green.
Every phase ends with acceptance checks. `ponytail:` marks a deliberate shortcut + its upgrade path.

---

## Answers to your 3 questions (locked)

### Q1 — Keys (RECEIVED — present in `.env`, values never committed, never logged)

| # | Provider | Unique role (no overlaps) | Quota note |
|---|----------|---------------------------|------------|
| 1 | **Tavily** (primary + fallback) | PRIMARY discovery + research content. LLM-shaped returns, best RAG input. | 1,000 credits/mo free |
| 2 | **Serper.dev** (primary + fallback) | Bulk discovery bursts (candidate-pool volume). | 2,500 trial queries — spend carefully |
| 3 | **SerpApi** (primary + fallback) | Recurring fallback discovery (always-on, shape-tested). | 250/mo recurring free |
| 4 | **Exa** (primary + fallback) | Entity search + independent cross-check (people/company match). | Trial credits — verify at build |
| 5 | **GitHub** (token) | Tech/activity signals (code, product, hiring-adjacent evidence). | Confirmed working by user |
| 6 | **Apollo** | Firmographic + contact enrichment (size/industry + people). Metered use only. | Keyed — verify quota at build |
| 7 | **Hunter** | Email verification first, discovery second (deliverability signal, not a contact list). | Keyed — verification endpoint first |
| 8 | **Apify** (primary + 2 fallbacks) | Universal structured actors (maps/local, company pages, profiles) — server-side, replaces desktop-login hacks. Allowlisted actors + per-run spend cap. | Credit-metered — cap enforced in code |
| — | Jina Reader (`https://r.jina.ai/`) | Page-text extraction fallback. | Free, no key |
| — | OSM Nominatim + Overpass | Local/maps entities, zero-cost path. | Free, rate-limited, no key |

Dropped: YouTube Data API key (declined — zero-key `yt-dlp` path only in P0). Skipped: Google CSE (closed, sunset Jan 2027),
Brave (terms unstable 2025–26), DataForSEO ($1 deposit).
**Non-duplication rule:** the four search backends look overlapping but hold distinct jobs (content / volume / recurring / entity).
At Phase 2 build, `doctor` measures unique contribution per backend; any backend with zero unique hits gets cut. No two connectors keep the same job.
**Status: full P0 mesh unlocked. No further keys required before P0.**

### Q2 — BYOK providers (locked list)

Abstraction = **OpenAI-compatible Chat Completions** as the primary interface. Covers: OpenAI, Groq, Cerebras,
Gemini (via its OpenAI-compat endpoint), Mistral, OpenRouter, SambaNova, NVIDIA NIM, GitHub Models.
**Anthropic Claude** = one native adapter (Messages API differs) behind the same `ProviderAdapter` interface.
Playground checklist ships with: `OpenAI · Anthropic · Gemini · Groq · Cerebras · Mistral · OpenRouter (+ custom base-URL)`.
Primary + fallback each = (provider, model id, key). Any pair works; failure of primary → fallback per policy.
Free-tier notes for your testing keys: Gemini AI Studio (no card, biggest free context), Groq (30 RPM, no card),
Cerebras (~1M tok/day), Mistral experiment tier, OpenRouter `:free` models, GitHub Models (any GitHub user).

### Q3 — HubSpot (locked)

Strict outputs stay **CSV / JSON, default CSV**. Additionally the CSV column set is **HubSpot-import-compatible**
(`company, domain, website, city, country, industry, employee_count, contact_* …`) so D1's "HubSpot-style format"
is satisfied without adding a third output mode. No CRM sync, no API push in MVP.

---

## Architecture at a glance (LangGraph inside the engine)

```text
Host model / Playground BYOK loop
  → MCP tools (FastMCP: stdio + HTTP)
    → LangGraph orchestrator (inside engine, NOT in UI):
       compile → plan → discover → prefilter → research → verify → qualify → dedupe → export
         ↑________fallback / retry edges________|
    → deterministic nodes are code; LLM nodes are compile/plan/extract ONLY
    → state: TargetSpec + candidates + evidence[] + qualify verdicts (SQLite persisted)
```

Why LangGraph (justified, not fashion): the pipeline needs conditional edges (stale→refresh, fail→fallback,
conflict→uncertain), retries with backoff, and visible step state for the Playground stream. A linear script
re-implements all three badly. LangGraph is the already-installed dependency that solves exactly this —
per the ladder, use it instead of hand-rolling an orchestrator.
`# ponytail: single LangGraph StateGraph, in-process, SQLite checkpointer; no separate worker queue — add one only if a demo run exceeds host timeouts.`

---

## P0 — Must ship for a live demo (phases 1–5)

### Phase 1 — MCP skeleton + contracts + deterministic core

Goal: the MCP exists, tools are callable, schemas are strict, fake data is impossible by construction.
Work:
- `reaver_mcp/` FastMCP server (`python -m reaver_mcp.server --transport stdio|http`), dual transport (stdio for local hosts, HTTP for Playground server).
- All 9 tools stubbed with real pydantic I/O schemas: `prospect, discover_leads, research_target, enrich_lead, qualify_lead, verify_evidence, deduplicate_leads, refresh_leads, export_leads`. `output_format: csv|json = csv`.
- `engine/models.py`: `TargetSpec, Candidate, Evidence {value, source, tier, observed_at, freshness, confidence}, CriterionVerdict {PASS|FAIL|UNKNOWN}, LeadVerdict {QUALIFIED|DISQUALIFIED|UNCERTAIN}`.
- Deterministic utils with zero LLM: normalizers (domain/name/URL), CSV/JSON exporter (stdlib `csv`/`json`), HubSpot-compatible header map, tier ranking, freshness math, contradiction detector (pure function).
- `doctor` endpoint (source health list) — static list first, wired in Phase 2.
- 1 runnable self-check: `python -m engine.selfcheck` (assert-based, no framework) proving normalize→contradict→export round-trips.
Out of scope: real search, LLM calls, UI, RAG, DB (in-memory only).
Accept: `prospect` callable from an MCP inspector; invalid inputs rejected by schema; exporter byte-checks pass; UNKNOWN returned when evidence absent (never invented).
Security (MCP): schema validation on every tool arg (count caps: `max_leads ≤ 200`, URL allow-list scheme http/https); error strings contain no paths/keys.

### Phase 2 — Source mesh v1 + robots gate + cache

Goal: real evidence flows; every fetch is compliant, cached, and attributed.
Work:
- `connectors/`: `tavily.py` (primary content), `serper.py` (bulk), `exaid.py` (entity), `serp.py` (recurring fallback), `github.py` (tech signals), `reader.py` (Jina fallback), `local.py` (Nominatim/Overpass), `yt.py` (zero-key `yt-dlp` captions/search — no API key), `apollo.py` (firmographic + people enrich, metered), `hunter.py` (email verify first, discovery second), `apify.py` (generic actor-runner: allowlisted actor IDs only, per-run spend cap, dataset → Evidence mapping; maps/local + company-page actors). Each returns `(results[], status, latency)`; missing key → `status=UNAVAILABLE`, never exception-as-data.
- Enrichment chain (fixed order, no overlap): discovery (search mesh) → firmographics (Apollo) → email verification (Hunter) → structured gaps only (Apify actors) → page text (Jina). A later stage never re-fetches what an earlier stage already proved fresh.
- `mesh/router.py`: ordered-backend routing per fact type (Agent-Reach pattern) + `doctor` real probes, incl. unique-contribution stats for the non-duplication cut.
- `compliance/robots.py`: robots.txt fetch-parse-cache gate on every URL; `disallowed → skip + reason` stored in evidence metadata. `# ponytail: stdlib + urllib.robotparser, cached in SQLite; no per-domain crawler — single-fetch only.`
- `data/cache.py`: SQLite tables `requests, sources, evidence, leads` with TTLs (hiring short, firmographic long). Rerun = reuse fresh / refresh stale.
- Backoff + fallback: 429/5xx → backoff → next backend → recorded `fallback_attempted`. Apify + Apollo metered calls additionally gated by per-run budget counters.
Out of scope: LLM extraction (raw snippets stored), RAG embeddings, UI, login-session adapters (P2 only).
Accept: `discover_leads("…")` returns real candidates w/ URLs; `enrich_lead` returns Apollo firmographics + Hunter verification state; an Apify maps actor returns structured local entities mapped to Evidence; robots-blocked URL proves skip+reason; second identical run hits cache (no new HTTP); spend caps provably stop metered calls; keyless/unknown actor reports UNAVAILABLE cleanly.
Security (MCP): keys read from server env only, never tool args; SSRF guard (no localhost/metadata-IP fetches, redirect cap, size cap 2 MB, timeout 15 s); per-tool rate limits.

### Phase 3 — LangGraph orchestrator + qualify + dedup + export

Goal: `prospect` runs end-to-end: NL → leads → CSV/JSON.
Work:
- `agent/graph.py`: StateGraph `compile → plan → discover → prefilter → research → verify → qualify → dedupe → export`, conditional edges for refresh/fallback/uncertain. Checkpointer = SQLite (rerunnable).
- LLM nodes (via provider abstraction, server-side test key): target compiler (NL→TargetSpec JSON, schema-validated, asks only material gaps), search-plan writer, snippet→attribute extractor (values always paired w/ source+observed_at or dropped).
- Code nodes: prefilter (cheap rules), verifier (tier weight + freshness + contradiction), qualifier (per-criterion PASS/FAIL/UNKNOWN → lead verdict; score = summary), deduper (normalized domain→URL→name+geo merge, evidence union), exporter (CSV default / JSON + HubSpot-compatible columns).
- Cap guards: discovery ≤ N queries, research only top-K post-filter (staged retrieval), research depth/timeout budgets.
Out of scope: Playground UI, vector RAG (keyword evidence filtering only here), refresh UI.
Accept: 1 live run on a fixed demo target yields CSV with ≥10 real leads, ≥1 UNCERTAIN (conflict or stale) proving honesty, dedup removes an injected duplicate; run is resumable from checkpoint.
Security (MCP): long-run guard (step events + heartbeat so hosts don't time out silently); max-leads/timeout caps enforced in code, not prompt.

### Phase 4 — Playground + BYOK + streaming (same MCP, no second agent)

Goal: website = landing + playground; playground is a thin client over the Phase-3 MCP.
Work:
- `playground/server`: session API — creates `session_id`, holds `{primary(provider,model,key), fallback(...)}` in **server memory only, TTL 30 min**, runs model→MCP loop against the MCP over HTTP, SSE step stream (`understanding ✓ → plan ✓ → health ✓ → discovering ✓ → … → CSV/JSON ✓`).
- `playground/ui`: landing + playground pages; model checklists (primary/fallback), NL input, CSV/JSON radio (default CSV), live steps, lead cards (verdict, confidence, freshness, evidence count, "why qualified?" expander, source links), download button (short-lived signed URL).
- Server-side MCP client only; zero discovery/qualify logic duplicated in UI (CI lint: UI bundle must not import `engine/`).
Out of scope: auth accounts, persistence of keys, extra pages.
Accept: with user-supplied Groq + Gemini keys, full run streams to CSV download; keys absent from all client traffic (verify via network log); killing session wipes keys; no project key exists anywhere in repo/config.
Security (Playground) — full list in §Security; headline: keys never leave server, never logged, redacted from errors/SSE; per-IP+session rate limits; input caps; CSP; signed expiring downloads.

### Phase 5 — E2E demo hardening + repo hygiene

Goal: the demo cannot embarrass us.
Work:
- Fixed demo target + golden-run script (`scripts/demo.sh`) with recorded step transcript.
- Failure choreography: forced kill of primary search backend → fallback path shown; forced stale evidence → refresh shown; forced conflict → UNCERTAIN card shown.
- `evals/`: 5-case mini-suite (schema validity, dedup correctness, default-CSV behavior, robots-block respected, no-fabrication probe with a nonsense company → must return empty/UNCERTAIN, never invented data).
- README (setup, MCP host configs for Claude/OpenCode/ChatGPT-Apps, playground BYOK steps), `.env.example` (key names only, no values), LICENSE, `.gitignore` (secrets, db, caches).
Accept: cold-clone → env keys → `demo.sh` green; all 5 evals pass; network log shows zero key leakage.

---

## P1 — Highly valuable, demo-safe to defer (phases 6–7)

### Phase 6 — Real evidence RAG (wired into qualify, not a checkbox)

Work: `evidence/rag.py` — fetched docs → clean → chunk (source-aware) → embed (provider-agnostic embedding call, Cohere free trial or local hash-embed fallback `# ponytail: start keyword+embedding hybrid via SQLite; dedicated vector service only if retrieval precision measurably fails`) → retrieve per-criterion → cite passage IDs in verdicts + playground "why qualified?" expander.
Accept: every PASS cites ≥1 retrieved passage; removing the passage store flips verdicts to UNKNOWN (proves RAG is load-bearing).

### Phase 7 — Refresh + health UX + contradiction surfacing

Work: `refresh_leads` full path (stale→refetch, dead→fallback, gone→mark + explain); `doctor` live in playground (per-source dot + latency); contradiction cards show all conflicting values side-by-side; HubSpot CSV dry-import test documented.
Accept: rerun within TTL = zero new search calls; expired TTL = targeted refresh only; all source outages render as honest UNAVAILABLE states.

---

## P2 — Only if P0+P1 green (phase 8)

### Phase 8 — Extra connectors, eval depth, polish

Work: login-session adapters ONLY if a demo target proves unreachable without them (LinkedIn/X/Reddit via user-supplied throwaway sessions, ban-risk disclosed, run-scoped); 20-case eval set; landing polish; run history (local SQLite, no cloud); multi-target queue.
Explicit non-goals (do not build): outreach/email/LinkedIn messaging, campaigns, nurturing, forecasting, call analysis, CRM suite/sync, model training, scraping bypass, CLI product, Excel/XML/markdown export, extra website modules, any new connector duplicating an existing job.

---

## Security (normative — enforced from Phase 1, audited in Phase 5)

### Playground security
1. Keys in server memory only (dict keyed by `session_id`, TTL 30 min, explicit "Clear keys" destroys). Never localStorage / URL / cookie / DB / log.
2. TLS everywhere; `Secure, HttpOnly, SameSite=Lax` session cookie holds only opaque session id.
3. Redaction: central `redact()` over all logs, errors, SSE payloads (keys, bearer tokens, Set-Cookie never emitted).
4. Rate limits: per-IP (e.g. 10 runs/hr) + per-session concurrency 1; input caps (prompt ≤ 4k chars, max_leads ≤ 200).
5. SSRF/download guards on server fetch paths (Phase-2 guards apply); signed download URLs, 5-min expiry, single session.
6. CSP + no secrets in client bundle (build-time assertion: `grep -r` for key patterns fails build if found); dependency audit before demo.
7. No analytics on prompt/key material; error reports contain verdict IDs only.

### MCP security
1. HTTP transport requires bearer token when exposed beyond localhost (playground server holds it; stdio local = trusted loopback only).
2. Every tool arg schema-validated (pydantic), counts/URLs/timeouts capped; rejects over-budget calls before any spend.
3. Secrets never cross tool boundary: connectors read env/server config; tool args carry no keys.
4. Robots/auth/access-control gate is server-side and unconditional — a hostile host prompt cannot bypass it (no `ignore_robots` param exists by design).
5. Audit log per run: tool, args-hash, backend, status, latency — no content beyond IDs; retained locally for demo traceability.
6. Graceful failure: rate-limit/auth/outage → structured UNAVAILABLE + fallback, never stack traces or key hints to the host.

---

## What I require from you (blocking order)

1. **Keys: DONE.** Tavily/Serper/Serp/Exa/GitHub/Apollo/Hunter/Apify present in local `.env` (never committed — `.gitignore` covers it). YouTube key declined (zero-key path). No further keys needed before P0.
2. **BYOK test keys (Phase 4):** one primary (e.g. Groq, no card) + one fallback from a different provider (e.g. Gemini). Confirms primary→fallback switch live.
3. **Decisions (one line each):** confirm Python stack lock; confirm hosting target for demo (local laptop vs deploy URL); pick the fixed demo target entity-type (company / local business / professional — one only).
4. **Access:** push rights confirmed on `PradipLalpura/D1-Reaver-Capabl` (repo is currently empty — I will init + push Phase scaffolding on your go-ahead); tell me whether to push `PHASES.md` + scaffolding now or keep local until Phase 1 code lands.
5. **Nothing else yet:** no new connectors until Phase 8, and only if a demo target proves unreachable; no video work until P0 green.

---

## Changelog

| Date (UTC) | Change |
|---|---|
| 2026-09-20 | Phase 0 analysis complete (UNDERSTANDING REPORT delivered in chat). Repo verified: only ideation file; remote `D1-Reaver-Capabl` verified empty. |
| 2026-09-20 | `PHASES.md` v1 created: P0 split into Phases 1–5, P1 into 6–7, P2 into 8. LangGraph adopted as orchestrator (justified). Q1/Q2/Q3 locked (Tavily-first free-tier keyset; OpenAI-compat + Claude-native BYOK; HubSpot-compatible CSV within strict CSV/JSON). Playground + MCP security sections added (normative). |
| 2026-09-20 | `PHASES.md` v2: Q1 rewritten — Apollo (firmographic+people), Hunter (verify-first), Apify (allowlisted actor-runner + spend cap) promoted into Phase 2; enrichment chain + non-duplication rule added; YouTube key declined (zero-key yt-dlp); GitHub confirmed; Phase 8 rescoped to session-adapters-if-proven-needed; requirements updated (keys DONE, BYOK + 3 decisions remain). |
| 2026-09-20 | Phase 1 landed: `engine/` contracts + deterministic core, `reaver_mcp/server.py` (10 tools: 4 wired, 6 honest stubs), `mesh/doctor.py` static registry. `engine.selfcheck` 14/14, stdio smoke 7/7. Package named `reaver_mcp` (SDK collision); entry is `python -m reaver_mcp.server`. |
| 2026-09-20 | Phase 2 landed: `connectors/` (11 backends, stdlib urllib, SSRF guard), `mesh/router.py` (ordered routing, budgets, cache), `compliance/robots.py` (unconditional gate), `data/cache.py` (sqlite TTL). `discover/research/enrich/doctor` wired live. Selfcheck 22/22, live 14/14, MCP smoke 10/10. Apollo fixed to free-plan `/v1/organizations/search`; router KeyError on kwargs-backends fixed + regression-guarded. yt-dlp absent → youtube honestly UNAVAILABLE. |
| 2026-09-20 | Phase 3 landed: `agent/graph.py` (LangGraph compile→plan→discover→prefilter→research→verify→qualify→dedupe→export, SQLite checkpoint), `provider/llm.py` (OpenAI-compat primary→fallback, stdlib), `engine/judge.py` (code-graded PASS/FAIL/UNKNOWN). `prospect` + `qualify_lead` wired. Live bakery run: 10 leads (6 QUALIFIED / 4 UNCERTAIN), rerun 21s via checkpoint+cache. Selfcheck 29/29, MCP smoke 11/11. Model IDs refreshed from live listings (groq gpt-oss-20b, gemini-2.5-flash). |
| 2026-09-20 | Phase 4 landed: `playground/server.py` (stdlib HTTP: landing + BYOK playground, SSE over real graph-stream events, signed expiring downloads) + static UI (model checklists, CSV/JSON default CSV, lead cards + why-qualified). Session keys memory-only 30-min TTL; per-IP rate limit; key scrub on all responses; CSP. `provider` gains per-run chains + Anthropic adapter; `KEY_NAMES` centralized in `connectors/keys.py`. Live HTTP: 9-lead SSE run, full CSV download, 0 key bytes in 15 scanned bodies, session wipe verified. Selfcheck 36/36. |
| 2026-09-20 | Phase 5 landed: `evals/run.py` (8 checks: schema, dedup, default-CSV, robots-block, no-fabrication, dead-primary fallback, stale refetch, conflict-honesty), `scripts/demo.py` (golden run + tracked-file secret scan), README + .env.example + LICENSE. Eval caught a real hole: judge ignored in-attribute conflict (e.g. 120 vs 400 employees could PASS) — now UNKNOWN at every criterion kind. DEMO GREEN. P0 complete. |
| 2026-09-20 | Phase 6 landed: `evidence/rag.py` (sentence chunking, cached+budgeted Gemini embeds, hybrid cosine/overlap retrieval over SQLite passage table) + `judge.attach_citations` (PASS without a cited passage downgrades to UNKNOWN). Citations flow into verdicts + playground why-expander. Live coffee-roaster run: 8 leads, all 8 PASS verdicts cited; offline ablation proves no-passages flips PASS to UNKNOWN. Selfcheck 42/42, evals 8/8. |
| 2026-09-20 | Phase 7 landed: real `refresh_leads` (forced refetch, change detection, re-judge; REFRESHED/FRESH/STALE/GONE), conflict values in verify summaries surfaced as `conflicts` in results + Playground cards, last-known latency in `/api/health` + UI dots, HubSpot import docs + column eval. Live refresh proven on motibakery.com. Two live-caught fixes: judge pooled city+country into false conflicts (now per-attribute); selfcheck import shadowing. Selfcheck 44/44, evals 11/11. P1 complete. |
| 2026-09-20 | Phase A landed: optional `business_context` (name/sells/ideal-buyer/dealbreakers) threads MCP `prospect` + Playground into compile; buyer-fit + dealbreaker criteria graded like any other (keyword-kind, evidence-bound). Live proof: 9-lead run carries "serves retail bakeries" verdicts. Selfcheck 48/48, evals 11/11, MCP smoke green. |
| 2026-09-20 | Phase B landed: wave top-up loop (pool 2.5x asked, 3 waves, entity-deduped prefilter, multi-backend pool expansion via router `skip`), delivery split (qualified + uncertain capped 40%, rejected WITH reasons), quota reporting, empty-dedupe guard. Provider chain now 3-deep + JSON salvage parsing. Proven: waves fire, split holds, shortfall honest (12/20 run). Full-20 live proof PENDING free-tier LLM quota (groq/openrouter 429, gemini 404, github-models brownout — verified, not code). Selfcheck 53/53, evals 10/10 + 1 honest skip. |
| 2026-09-20 | Phase C landed: `verdict_summary` on every delivered lead (pass ratio + top failing notes, CSV column after HubSpot set), `rejected` with reasons + `shortfall` + `quota` in MCP/SSE results, Playground rejected section + shortfall banner + quota line + per-card summaries. Eval refresh-gate hardened for mid-run quota death (skip on empty extract). Selfcheck 56/56, evals 10/10. Live 20-proof still PENDING same quota drought. |
| 2026-09-20 | Phase D landed: remote-ready MCP (`--host/--port/--token`, fail-safe refusal of untokened public binds, bearer middleware, uvicorn) + README connection guide (Claude Code/Desktop stdio one-liner; ChatGPT Apps SDK + Claude URL-connector via public HTTPS). Verified: 401 unauthenticated, full 10-tool session authenticated over HTTP. Selfcheck 58/58, evals 11/11. |
| 2026-09-20 | Deploy split landed: Vercel (`vercel.json` rewrites) serves `/` + `/static/*`; Railway runs playground + MCP behind `/playground`, `/api/*`, `/mcp/*`. Static assets moved to top-level `static/` (single source); playground gains `--host`. Railway placeholders filled at deploy; DNS-only subdomain fallback kept warm for long streams. |
| 2026-09-20 | Brand UI landed: navy/gold/red system from `logos/`, loader with favicon build animation, hero with assembling mark, scroll reveals, hover-only motion, branded 404 (HTML for browsers, JSON for APIs), favicon on every page. BYOK is now generic: 6 providers + custom https endpoint. Selfcheck 61/61, evals 11/11, all routes served live. |
| 2026-09-20 | Bright UI landed (Targo-system reference): Quantico, paper #F2F1F0, accent #15BCDF, staircase hero + about, chamfered glowing CTAs, cyan-tinted panel, hover-only motion, reduced-motion respected. No external media (inline SVG motif, own logos). Selfcheck 61/61, evals 11/11, pages verified live. |
| 2026-09-20 | FORGED UI landed (weapon concept): kinetic rise-in hero, forge-sequence loader, spark canvas fleeing the pointer, magnetic CTAs, marquee, animated battle stats, hover-tilt strike cards, "Trophies/Fallen/Armory" playground, "Miss" 404. Vanilla only. Selfcheck 61/61, evals 11/11, routes verified live. |
| 2026-09-20 | UI round 2: dark/bright transitional theme (persisted toggle on all pages), MCP arsenal section (what it is + local/remote/Playground wiring), "works everywhere" host marquee. |
| 2026-09-20 | MCP docs page (`/mcp-docs`): 6 host setup tabs with copy buttons, 10-tool reference from real signatures, transports/auth, troubleshooting from real incidents, live status widget. vercel.json serves it statically. Selfcheck 61/61, evals 11/11. |
| 2026-09-20 | Sources diversified: discover rotates lead backend per query (tavily→serper→serpapi→exa proven live), router cache keyed by skip-set, pool target raised. Images fixed: brand PNGs committed under `static/`, all refs root-relative (Vercel-safe). UI v3 (FORGED II): bento hero with live terminal, strike rail, verdict tabs, stepper progress, sticky blurred nav. Selfcheck 61/61, evals 10/10. |
| 2026-09-20 | Every-source enrich: new `enrich_node` (Apollo firmographics + Hunter contacts + OSM location + GitHub tech fill page gaps only, capped, skips non-entities), directory/article pages disqualified-as-non-entity (mined for entities instead). Proven: all 5 enrichers fired live. Full SaaS proof PENDING same LLM drought (mining/extraction calls 429). Selfcheck 63/63, evals 10/10. |
| 2026-09-20 | Completion round: `scripts/setup_mcp.py` one-command installer (list/print/install/check across 6 hosts); Apify actor path proven live (compass/crawler-google-places, real results) + bounded polling + last-resort maps wiring; PNG allowlist fix (real PNG bytes verified); 3D buttons + beamed cards. Selfcheck 63/63, evals 11/11. SaaS verdict proof still PENDING quota drought. |
