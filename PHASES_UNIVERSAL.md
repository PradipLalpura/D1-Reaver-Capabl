# REAVER — Universal Phase Ideation (U1–U5)

> Sequel to `PHASES.md` (P0/P1 + A–D done). Goal: REAVER connects from **every
> legitimate AI surface** — Claude, ChatGPT, Kimi, MiniMax, CLI agents, desktop
> GUIs — with zero-terminal onboarding, and stays more advanced than Agent-Reach.
> No code from this file alone — each phase is built, run, and accepted before the next.

**Conventions:** `UMUST` = blocks universal claim. `UGOOD` = strengthens it.
Every phase ends with acceptance checks. `ponytail:` marks deliberate shortcuts.

---

## Diagnosis driving this plan (verified 2026-09-20)

**"Playground not working today" root cause: brains, not infrastructure.**
Railway + domain proxy serve correctly (pages 200, `/api/health` 12 sources,
sessions issue). But **all three free LLM tiers are simultaneously dead**
(groq unparseable, gemini 404, openrouter 429) — so every run fails honestly at
compile. The engine refuses to fabricate; the Playground correctly reports failure.
Infrastructure: innocent. Quota: guilty. This plan makes the system survive that.

**Agent-Reach gap analysis (why we stay ahead):** Agent-Reach is CLI-stdout +
desktop-login-sessions with no evidence model, no compliance gate, no cache/TTL,
no qualification. Our leads: typed contracts, per-backend routing, robots gate,
SQLite cache, code-graded verdicts, RAG citations. U-phases extend the lead to
**onboarding** (they need terminal + cookies; we need clicks) and **host reach**
(they serve CLI agents; we serve everything).

---

## Phase U1 — Universal provider/host matrix [UMUST]

Goal: Kimi, MiniMax, and any OpenAI-compatible endpoint work as first-class BYOK;
every CLI and GUI connects with copy-paste configs or one command.

Verified 2026-09-20 (docs, not yet wired) — all compatible with our transports:
- **Kimi Code CLI** (`kimi`/MoonshotAI/kimi-cli): full MCP client — stdio, HTTP, SSE;
  `kimi mcp add [--transport]`, `mcp.json` user+project levels, TUI `/mcp-config`.
  Our stdio + HTTP both fit. Commands: `kimi mcp add --transport stdio reaver -- python -m reaver_mcp.server --transport stdio`.
- **MiniMax Agent/Code** (`mcode`): MCP client — stdio, http, streamable-http, sse;
  GUI form + JSON modes, `~/.minimax/mcp.json`, `mcode mcp list/tools/auth` checks.
  Our stdio + HTTP both fit.
- **Cursor / Windsurf / Cline / Codex**: standard JSON/TOML MCP configs (same shape
  family as our desktop/opencode writers) — no protocol risk, only new writers.
- **Moonshot API as BYOK**: OpenAI-compatible (`api.moonshot.ai/v1`); Kimi models also
  reachable free via OpenRouter (`moonshotai/kimi-k2:free`, confirmed listed).
- **MiniMax API as BYOK**: OpenAI-compatible endpoint claimed — VERIFY LIVE with one
  JSON call before merge; cut or keep on result.

Already complete (no work): `custom` provider accepts ANY OpenAI-compatible base URL,
so BYOK-universal is technically covered today; 3-deep failover chain
(groq→gemini→openrouter) + JSON salvage already shift quota exhaustion to fallbacks.
Named moonshot/minimax entries are convenience + verified defaults, not new capability.

Work:
- `provider/llm.py`: add `moonshot`, `minimax` flat entries — each merged ONLY after
  one live JSON call; dead ones cut, never stubbed.
- `/api/health` + `doctor`: report provider reachability (key presence only, quota-safe).
- `scripts/setup_mcp.py`: `--install` gains `kimi`, `mcode`, `cursor`, `windsurf`,
  `cline`, `codex` (command-runners where CLIs exist, config-writers with backups
  otherwise — same pattern as existing six).
- `/mcp-docs`: host-matrix section (host × transport × exact command/config × difficulty);
  Kimi/MiniMax appear TWICE with labels kept distinct: MCP *clients* (their CLIs run
  our tools) vs BYOK *models* (their APIs reason behind our tools).
Out of scope: OAuth issuance (U2), session adapters (backlog).
Accept: one live JSON call per new provider; setup script installs 6 new hosts;
`setup_mcp.py --check` still green; matrix claims trace to verified docs above.
`# ponytail: provider table stays flat dicts; setup writers share one merge helper; no plugin framework.`

## Phase U2 — `/connect`: zero-terminal onboarding [UMUST]

Goal: a non-technical user goes from landing to connected host with clicks only.

Work:
- New `static/connect.html` (same forged system + theme toggle): host picker cards
  (ChatGPT / Claude Desktop / Claude Code / OpenCode / Cursor / Kimi / MiniMax-as-model),
  per-host GUI-only steps, token issuance widget, downloadable configs
  (`claude_desktop_config.json`, `opencode.json` snippet) generated client-side.
- Token service: `tokens` SQLite table (hash, label, cap, created, revoked);
  `POST /api/token/request` (label → token shown once, per-IP rate-limited);
  middleware checks table (401 unknown/revoked, 429 over cap, defaults 3 prospect runs/day);
  admin `usage` + `revoke` CLI commands. Operator token becomes row one.
- Server route `/connect` (+ vercel rewrite `/connect` → static).
- Playground BYOK checklist gains moonshot/minimax/custom rows automatically from provider table.
Out of scope: OAuth logins, user accounts, email verification (label + IP limit + caps only).
Accept: request token → use in ChatGPT connector → exhaust cap → 429 → revoke → 401;
config download imports into Claude Desktop shape (schema-validated offline);
zero key bytes in issuance responses (extend key-leak scan).
`# ponytail: issuance is one endpoint + table; approval queues and dashboards wait for abuse data.`

## Phase U3 — MCP docs as a site [UGOOD]

Goal: `/mcp-docs` becomes the docs subsite the landing's arsenal section promises.

Work:
- Restructure `static/mcp.html`: overview → host matrix (links per host to tab) →
  setup tabs (existing 6 + cursor/windsurf/cline) → tool reference (existing 10) →
  transports/auth → troubleshooting (append quota-drought + Vercel-proxy notes) →
  `/connect` CTA band.
- `static/mcp.js`: deep-linkable tabs (`#host=chatgpt`), active-section highlight on scroll.
- README deploy section points at `/mcp-docs` as canonical user docs.
Out of scope: versioned docs, search index, video embeds.
Accept: every anchor resolves; tabs deep-link; pages served 200 locally + via Vercel proxy.

## Phase U4 — Animated GitHub README [UGOOD]

Goal: the repo page sells in 30 seconds (judges land here from the hackathon booklet).

Work:
- `README.md` rewrite: hero banner (logo), animated SVG pipeline diagram (CSS-only,
  no external media), host-matrix table, 30-second quickstart (3 commands),
  screenshots section (captured from localhost, committed under `docs/img/`),
  badges (checks status as text, license, D1 track), architecture + security summary,
  deploy + connect links.
- Screenshots captured with Playwright MCP/CLI against localhost (replaces byte-count
  verification for UI claims where it matters).
Out of scope: video file, GIF recording pipeline (single stills first).
Accept: README renders complete offline (no hotlinked assets); every claim traces to
a green check or a linked eval.

## Phase U5 — Quota-survival reliability [UMUST]

Goal: the next all-provider drought degrades gracefully instead of failing every run.

Work:
- Provider `/models` refresh in `doctor` (live IDs replace rotted defaults automatically;
  the twice-rotted groq/gemini defaults are the evidence this is load-bearing).
- Compile fallback: 2 attempts → cached-spec retry → honest "brains unavailable, retry in X"
  message carrying the per-provider failure list (already surfaced in LLMError; plumb it).
- Playground run button states: quota-dead error renders as a distinct banner
  (not a generic failure), with retry action.
- Eval gate: quota-dependent cases skip with reason (pattern exists; extend to new paths).
Out of scope: paid fallback keys, request queueing across hours.
Accept: simulated all-dead providers → distinct banner + skip-evals green;
models refresh flips a rotted default without code change.
`# ponytail: refresh is a cached list, not a model registry service.`

---

## Backlog (explicitly not in U1–U5)

- Phase 8 login-session adapters (LinkedIn/X/Reddit) — only if a demo target proves unreachable.
- Full-20 live proof rerun — executes automatically when quota returns (script exists: `run_pb.py`).
- Video phase — separate track per brief.
- Paid-tier fallbacks, CRM sync, outreach — permanent non-goals.

---

## Build order

U1 (reach) → U2 (onboarding) → U5 (survival) → U3 (docs site) → U4 (README).
U5 can swap before U2 if the drought persists — say so and the order flips.

## Changelog

| Date (UTC) | Change |
|---|---|
| 2026-09-20 | `PHASES_UNIVERSAL.md` created: playground-outage diagnosis (quota, not infra), Agent-Reach gap analysis, U1–U5 + backlog + order. |
| 2026-09-20 | U1 scope verified before build: Kimi CLI + MiniMax `mcode` confirmed MCP clients (stdio/HTTP/SSE) via official docs; Cursor/Windsurf/Cline/Codex standard configs; Moonshot OpenAI-compat confirmed, MiniMax endpoint verify-pending. Setup covers 6 hosts today, +6 planned. `custom` already makes BYOK universal; failover chain already shifts quota. |
| 2026-09-20 | U1 built: setup script covers 12 hosts (kimi/mcode/cursor/windsurf/cline/codex added, installs verified into sandbox configs); `/api/health` reports provider key presence; mcp-docs gains Kimi/MiniMax/Cursor tabs. Named moonshot/minimax provider entries DEFERRED — no direct keys supplied, and the file's own verify-or-cut rule forbids stubs (`custom` covers both URLs today). Selfcheck 65/65, evals 11/11. |
| 2026-09-20 | U2 built: `engine/tokens.py` (hash-stored per-user tokens, daily caps, revoke, usage), middleware table-check + operator fallback, `POST /api/token/request` (5/day/IP), `scripts/tokens.py` admin, `/connect` page (host cards, GUI guides, token widget, config downloads). Proven live: issue→use→counted→revoke→401, unknown→401. Selfcheck 72/72, evals 11/11. |
| 2026-09-20 | U3 built: mcp-docs overview strip, host-matrix cards (deep-linked to tabs), 2 new troubleshooting cards (quota drought, proxy streams), /connect CTA band, README canonical-docs pointers. Scrollspy dropped — no anchor nav exists to highlight; deep links cover navigation. Selfcheck 72/72, evals 11/11. |
| 2026-09-20 | U4 built: README rewrite (hero shot, SMIL-animated pipeline SVG, host matrix, 30s quickstart, 4 Playwright-captured localhost screenshots, trust/deploy/docs sections). Screenshots visually reviewed: forged UI renders correctly. Selfcheck 72/72, evals 11/11. |
| 2026-09-21 | README v2 (stunning pass): hero banner, 6-stage animated SVG, problem→solution narrative, pipeline diagram, 12-host table, 4 screenshots, claim⇄proof table, deploy + docs links. Video package `video/` (verbatim SCRIPT + timed captions.srt + Flow/Veo scene prompts + shot list + edit rules). No credentials ever requested or accepted. Selfcheck 75/75, evals 11/11. |
| 2026-09-21 | README v3 (animation-max): PIL-rendered typing-terminal GIF + animated counters GIF, SMIL packet dot on pipeline, verdict-state cycler SVG. Images cut to 3 (terminal, stats, playground). Selfcheck 75/75, evals 11/11. |
| 2026-09-21 | U5 built: provider `/models` refresh + stale-default auto-override (cached 7d, env always wins), compile failures carry per-provider causes, Playground "brains unavailable" banner. Live 20-run on quota return: all 4 search backends + all enrichers fired, 11 delivered / 8 uncertain capped / 16 rejected with reasons. Caught live: Hunter unmetered (22 calls ≈ monthly free quota) → budget-gated at 10/run. Selfcheck 75/75, evals 11/11. |
