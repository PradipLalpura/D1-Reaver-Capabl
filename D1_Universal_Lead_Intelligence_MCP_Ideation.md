# D1 — REAVER
## Precise Product Ideation / Hackathon Build Specification

**Hackathon:** Capabl AI Hackathon 2026  
**Track:** D — Sales, Growth & Revenue Agents  
**Problem Statement:** D1 — Autonomous Lead Generation & Qualification Agent
**Product:** REAVER

### Core references

- Official hackathon: https://www.capabl.in/ai-hackathon-2026
- D1 problem statement: https://www.capabl.in/problem-statements/d1-autonomous-lead-generation-qualification-agent
- Agent-Reach (architectural reference): https://github.com/Panniantong/Agent-Reach
- Agent-Reach English docs: https://github.com/Panniantong/Agent-Reach/blob/main/docs/README_en.md
- Agent-Reach install/usage: https://github.com/Panniantong/Agent-Reach/blob/main/docs/install.md
- Model Context Protocol: https://modelcontextprotocol.io/
- OpenAI Apps SDK: https://developers.openai.com/apps-sdk/
- Anthropic MCP documentation: https://docs.anthropic.com/en/docs/agents-and-tools/mcp-connector
- OpenCode MCP documentation: https://opencode.ai/docs/mcp-servers/

---

# 1. LOCKED PRODUCT DIRECTION

We are **not building a traditional lead-generation SaaS** and we are **not building a CLI-first product**.

We are building **REAVER**, a universal, portable **MCP-first lead-intelligence agent**.

The MCP exposes lead-generation, research, enrichment, verification, qualification, deduplication, and export capabilities to AI hosts such as ChatGPT, Claude, Codex, OpenCode, and other MCP-capable agents.

The system is intentionally **universal**:

- usable by an individual or a business
- usable across every industry
- usable across every field/domain
- usable for any legitimate lead/target type that can be researched from available sources
- not hard-coded to SaaS, technology, agencies, sales agencies, or any single vertical
- not hard-coded to one geography
- not hard-coded to one ICP template

The user defines the target and the system adapts the discovery and qualification process to it.

### Core promise

> **One autonomous lead-intelligence agent that can discover, research, verify, qualify, deduplicate, and export leads for any legitimate use case — from the AI environment the user already works in.**

---

# 2. TWO EXECUTION MODES

There are exactly **two execution modes**.

## Mode 1 — AI Host / MCP Mode

The user connects the MCP to an AI environment such as:

- ChatGPT
- Claude
- Codex
- OpenCode
- another compatible MCP client

The host AI provides the reasoning/model.

REAVER's MCP supplies specialized lead-intelligence capabilities.

```text
User
  ↓
AI Host
  ↓
User's / Host's model
  ↓
Our MCP
  ↓
Lead Intelligence Engine
```

The user should not need to manage our model credentials in this mode.

## Mode 2 — BYOK Mode

The user uses the Playground and supplies their own provider credentials.

The Playground must provide:

```text
Primary API Key
Fallback API Key
```

It must also provide a **model-selection checklist** so the user chooses which supported provider/model configuration acts as the LLM for the Playground.

The Playground does **not** contain a separate lead-generation engine or a separate agent implementation. It directly uses **our MCP** and lets the selected BYOK LLM operate that MCP.

Execution:

```text
Selected primary model/provider + primary key
                    ↓
                  MCP
                    ↓
          Lead Intelligence Engine

if primary fails/unavailable
                    ↓
Selected fallback model/provider + fallback key
                    ↓
                  MCP
```

### Critical rule

**We will not provide hosted inference keys to users.**

There is no project-owned/free inference mode.

The Playground is **BYOK-only**.

All sensitive provider credentials remain server-side and must never be exposed to the browser/client.

---

# 3. MODEL OWNERSHIP PRINCIPLE

The LLM is **not the core product**.

REAVER's MCP is the capability layer.

The agentic system must separate:

```text
MODEL
= reasoning / interpretation / planning

MCP + ENGINE
= tools / retrieval / evidence / deterministic processing /
  source routing / qualification / validation / export
```

This allows the same lead-intelligence capability REAVER to operate across different AI hosts and different BYOK providers without rebuilding the core workflow for each model. The Playground is simply another interface for invoking the same MCP with the user's selected BYOK model/provider; it must not become a second implementation of the agent.

---

# 4. UNIVERSAL TARGET MODEL

The system must not assume that a "lead" means one particular kind of business prospect.

A lead can be represented according to the user's objective.

Examples of legitimate target dimensions:

```text
Organization
Person / decision maker
Business
Institution
Professional
Local entity
Vendor
Partner
Customer prospect
Hiring target
Research target
Other user-defined target
```

The user can define:

- industry
- geography
- organization/person type
- size
- niche
- required attributes
- exclusion rules
- signals
- recency requirements
- desired count
- qualification criteria
- evidence requirements

The system converts the natural-language request into a structured target specification.

---

# 5. WHAT D1 REQUIRES

The official D1 problem statement asks for:

- ICP definition
- company/contact discovery from public sources
- enrichment using firmographic, technology, funding and hiring signals
- qualification/scoring with clear reasoning
- deduplication
- CSV/JSON export
- rerunnable refresh with caching/rate-limit handling

The hackathon notes also emphasize:

- agentic multi-step reasoning
- tool use
- agent hand-offs
- mock/synthetic data where necessary
- explainability
- tight scope for a 4–5 person team
- robots.txt compliance as a compulsory add-on for D1

Therefore, the system should satisfy the D1 requirements while implementing a more general target/lead model instead of hard-coding one market or industry.

---

# 6. HIGH-LEVEL ARCHITECTURE

```text
                         USER
                           |
        +------------------+------------------+
        |                                     |
     AI HOST                                BYOK
(ChatGPT / Claude /                  Playground + user's
 Codex / OpenCode)                   primary/fallback keys
        |                                     |
        +------------------+------------------+
                           |
                      MCP SERVER
                           |
                +----------+-----------+
                |                      |
         HIGH-LEVEL TOOL         LOW-LEVEL TOOLS
          prospect()             discover_leads()
                                 research_target()
                                 enrich_lead()
                                 qualify_lead()
                                 verify_evidence()
                                 deduplicate_leads()
                                 refresh_leads()
                                 export_leads()
                |                      |
                +----------+-----------+
                           |
                  AGENT ORCHESTRATOR
                           |
        +------------------+------------------+
        |                  |                  |
     Discovery           Research          Verification
        |                  |                  |
        +------------------+------------------+
                           |
                     Qualification
                           |
                    Evidence Engine
                           |
                 Deduplication / Entity
                      Resolution
                           |
                   Structured Leads
                           |
                    Output Formatter
                           |
                   +-------+-------+
                   |               |
                  CSV             JSON
```

---

# 7. MCP TOOL SURFACE

## 7.1 Primary autonomous tool

### `prospect`

Purpose:

Run the complete D1 workflow from a natural-language target definition to verified, qualified leads.

Example conceptual input:

```json
{
  "request": "Find 50 businesses in my target market that match these requirements..."
}
```

The tool/workflow should:

1. interpret the request
2. compile the target criteria
3. generate a search strategy
4. discover candidates
5. normalize candidates
6. preliminary-filter candidates
7. research promising candidates
8. enrich required attributes
9. verify evidence
10. qualify candidates
11. deduplicate entities
12. produce structured lead output
13. optionally export

The model should not need to understand the internal sequence.

---

## 7.2 Low-level tools

### `discover_leads`
Find candidate targets from available sources.

### `research_target`
Perform deep research on one target entity.

### `enrich_lead`
Collect structured attributes and relevant signals.

### `qualify_lead`
Evaluate the target against the compiled criteria.

### `verify_evidence`
Check source quality, freshness, consistency, and contradictions.

### `deduplicate_leads`
Resolve duplicate entities.

### `refresh_leads`
Re-check previously stored leads whose evidence is stale or whose user requests a refresh.

### `export_leads`
Return the final qualified lead dataset in exactly one of two formats:
- CSV
- JSON

### Output format rule

The MCP must accept an optional `output_format` parameter:

```text
csv
json
```

If the user explicitly selects a format, use it.

If the user does not select one, **default to CSV**.

This rule applies to the end-to-end `prospect` workflow and to `export_leads`.

The names can be adjusted during implementation if better tool naming improves model tool selection, but the capability boundaries should remain clear.

---

# 8. SOURCE MESH

Do not hard-code the system around one vendor.

Build a **source mesh / capability router**.

Conceptually:

```text
                     SOURCE MESH
                         |
       +-----------------+-----------------+
       |                 |                 |
      WEB             SOCIAL          BUSINESS DATA
       |                 |                 |
  Search/Web          YouTube         Business DBs
  public pages        Reddit          Contact DBs
  target sites        GitHub          CRM-connected data
  public listings     public profiles Maps / local data
```

Potential source/connectivity classes may include:

- web search / SERP
- public websites
- public company pages
- authorized public social sources
- YouTube
- Reddit
- GitHub
- business directories
- maps/local listings
- Apollo or other authorized enrichment providers
- Hunter or other authorized enrichment providers
- HubSpot and other connected CRMs
- other lawful/authorized data sources

The exact connector list is implementation-dependent.

The system must support **available public/authorized sources**, not promise unrestricted access to private, blocked, paid-without-authorization, or protected data.

### Router responsibilities

For each requested fact, determine:

- which source(s) can answer it
- which source is currently available
- whether authentication is present
- whether the source is healthy
- whether the source is rate-limited
- expected freshness
- evidence quality
- whether another source should be used for cross-checking

The system should fall back to another source rather than fail the entire run when one connector is unavailable.

---

# 9. AGENT-REACH-INSPIRED DESIGN

Agent-Reach is an architectural reference, not something to copy.

Useful ideas to study:

- capability routing
- multiple upstream backends
- backend health checks
- fallback paths
- environment/config detection
- keeping the agent independent from fragile upstream providers
- using an agent-facing capability layer while calling upstream tools directly

Reference:

https://github.com/Panniantong/Agent-Reach

Our implementation applies the same philosophy to **universal lead intelligence**:

```text
Agent asks for evidence / lead capability
             |
       Capability Router
             |
      healthy source(s)
             |
     evidence collection
             |
      normalized result
```

But the output is not general internet access.

The output is:

> **qualified, evidence-backed leads for the user's own target definition.**

---

# 10. ICP / TARGET COMPILER

Do not force the user through a fixed 10-field form.

Allow natural-language target definitions.

Example:

> "Find organizations in India that match these characteristics, have recently expanded, and satisfy my specified size and activity requirements."

The compiler should extract structured criteria:

```text
Target type
Geography
Industry / field / domain
Size constraints
Required signals
Exclusion rules
Recency requirements
Qualification requirements
Desired count
```

The system should ask only for genuinely missing critical information.

For example:

> "How many leads should I return?"

The rest should be inferred from the request and confirmed only when ambiguity materially affects results.

---

# 11. DISCOVERY PIPELINE

Do not deeply research every discovered target.

Use staged retrieval.

```text
Natural-language target
        |
 Target compiler
        |
 Search-plan generation
        |
 Multi-source discovery
        |
 Candidate pool
        |
 Normalization
        |
 Cheap/fast preliminary filters
        |
 Promising candidate set
        |
 Deep research
```

Example:

```text
1,000 discovered candidates
        |
initial filtering
        |
250 candidates
        |
deep research
        |
90 candidates
        |
verification
        |
50 final leads
```

This minimizes unnecessary calls and reduces latency/cost.

The thresholds must remain configurable rather than hard-coded to one industry.

---

# 12. RESEARCH ENGINE

For each promising target, collect structured evidence relevant to the user's target definition.

Potential evidence classes include:

### Entity / firmographic
- name
- canonical domain
- country/location
- industry/field
- approximate size
- organization type
- business/activity status

### Technology / activity
- technology stack where relevant
- public technical activity
- product/activity signals
- engineering/technical signals where relevant

### Hiring
- active roles
- role categories
- hiring activity
- job recency

### Growth / business
- recent announcements
- expansion
- product launches
- funding announcements where applicable
- partnerships
- organizational changes
- other public activity

### Person/contact
Only collect information that is publicly available or obtained through authorized connected services.

The exact attributes should be driven by the user's target definition.

---

# 13. EVIDENCE-FIRST QUALIFICATION

The score must never be just:

```text
LLM says 92/100
```

Instead:

```text
Criterion
  -> evidence
  -> source
  -> timestamp
  -> freshness
  -> confidence
  -> consistency
```

Every important claim should be traceable.

Example:

```text
TARGET SIZE
Matches requested range

Evidence:
- primary/source record
- recent secondary confirmation

Status:
PASS

Confidence:
HIGH
```

If evidence conflicts:

```text
Target attribute:
Source A -> value 1
Source B -> value 2
Source C -> value 3

Status:
UNCERTAIN

Reason:
Conflicting public evidence
```

The system should **reduce confidence instead of inventing certainty**.

---

# 14. TEMPORAL TRUTH / FRESHNESS

A lead is not permanently true.

Store for important evidence:

```text
observed_at
source
source_type
freshness
confidence
```

Example:

```text
Hiring signal
ACTIVE
Observed: 2026-09-19

Business signal
OLD
Observed: 2026-02-04

Size estimate
CONFLICTING
```

The qualification engine should prefer recent primary evidence over stale secondary evidence.

Freshness requirements should be configurable by criterion.

---

# 15. CONTRADICTION ENGINE

Explicitly detect conflicts.

Example:

```text
Source A: value 120
Source B: value 450
Source C: value 300+
```

Do not average blindly.

Instead:

```text
Attribute = uncertain
Evidence conflict = detected
Confidence = reduced
```

This is a key anti-hallucination feature.

---

# 16. EVIDENCE RAG

RAG should be real and useful, not a checkbox.

Research artifacts:

```text
source
  |
clean content
  |
document representation
  |
chunking
  |
embeddings
  |
vector store
  |
retrieval
```

Use retrieval to answer:

> "Why did you qualify this lead?"

The result should provide the relevant evidence passages/records and their source.

Potential implementation:

- document loader/normalizer
- source-aware chunking
- embeddings
- vector store
- metadata filters
- semantic retrieval
- citation/evidence mapping

The exact storage technology can be chosen during implementation.

---

# 17. EVIDENCE HIERARCHY

Use an explicit source preference model.

Example:

```text
Tier 1 — Primary/direct evidence
Official entity website
Official documentation/careers/listings
Official announcements

Tier 2 — Direct platform evidence
Public GitHub
Public YouTube
Public social/profile evidence

Tier 3 — Structured/reputable secondary evidence
Business databases
Directories
Public registries where appropriate

Tier 4 — Search snippets / secondary mentions

Tier 5 — Model inference
```

Inference must never be represented as direct factual evidence.

---

# 18. QUALIFICATION MODEL

Qualification should evaluate each criterion independently.

Conceptually:

```text
Target Criterion
       |
Evidence retrieval
       |
Evidence validation
       |
Criterion result
       |
+------+------+ 
|             |
PASS      FAIL / UNKNOWN
```

The overall lead state can be:

```text
QUALIFIED
DISQUALIFIED
UNCERTAIN / NEEDS REVIEW
```

A numerical fit score may be used as an additional summary, but the explainable criterion-level evidence is the source of truth.

Scoring rules must adapt to the user's target instead of being tied to one industry.

---

# 19. DEDUPLICATION

Duplicates can exist because the same entity appears through different sources.

Need entity resolution based on combinations such as:

- normalized domain
- normalized name
- canonical URL
- location
- other stable public identifiers

The system should merge records and retain all evidence rather than simply deleting one record.

For person-level targets, use appropriate public/authorized identifiers and avoid guessing identity from weak signals.

---

# 20. REFRESH / CACHING / RATE LIMITS

D1 explicitly expects rerunnable refresh with caching/rate-limit handling.

Use:

```text
request cache
source cache
evidence cache
lead cache
timestamp/freshness policy
```

When rerunning:

```text
fresh evidence
    -> reuse

stale evidence
    -> refresh

broken source
    -> fallback

rate limit
    -> backoff / alternate source

unavailable source
    -> mark unavailable
```

Never fabricate a missing result just to complete a lead.

---

# 21. ROBOTS.TXT COMPLIANCE

This is a compulsory D1 add-on from the provided hackathon slide.

Every web-crawling/fetching pathway must have a compliance gate.

Conceptually:

```text
URL
 |
robots.txt check
 |
+----------+----------+
|                     |
allowed               disallowed
|                     |
fetch                 skip
                      |
              explain unavailable
```

The system must not bypass:

- robots.txt restrictions
- authentication barriers
- access controls
- platform protections

Use authorized APIs/connectors where required.

The compliance result should be retained as part of the execution/evidence metadata.

---

# 22. FAILURE BEHAVIOR

"Maximum capability" does not mean pretending every internet source is always available.

The system should maximize useful, compliant evidence while returning truthful states.

For every failed source, return:

```text
source
status
reason
fallback attempted
whether data is still sufficient
```

Example:

```text
Source
UNAVAILABLE
authentication required

Fallback:
public website + search + other available source

Result:
qualification continues with reduced confidence
```

This is better than hallucinating data.

---

# 23. MAXIMUM PRACTICAL SOURCE REACH

Goal:

> **Maximize practical, compliant, current evidence reach across relevant source types.**

Do not claim:

- unrestricted access to the internet
- unrestricted access to every platform
- guaranteed access to private data
- perfect accuracy
- zero failures

Measure the system by:

- number of usable source types
- fallback coverage
- successful retrieval rate
- freshness
- evidence agreement
- qualification accuracy
- graceful degradation

The system should dynamically use whatever compliant sources are actually available.

---

# 24. UNIVERSALITY REQUIREMENT

The product must work across:

```text
All legitimate industries
All legitimate business sectors
All legitimate professional domains
All geographies where usable sources exist
Individual and business users
Different target entity types
Different qualification criteria
Different source combinations
```

Do not create industry-specific hard-coded logic unless it is part of the user's requested criteria.

The engine should be **schema-driven and criterion-driven**.

A single generic pipeline should adapt to many domains:

```text
User target definition
        |
Generic target schema
        |
Dynamic discovery strategy
        |
Relevant source selection
        |
Evidence extraction
        |
Criterion-based qualification
```

---

# 25. CHATGPT / AI-HOST USER EXPERIENCE

The MCP must feel natural.

The MCP itself should not act like a chatbot.

### First interaction

User:

> Hi

Host AI:

> I can help you find, research, verify, and qualify leads. What are you looking for?

User:

> Find 50 organizations matching these requirements...

Host AI:

> Got it. I understand the target. Should I start discovery?

User:

> Yes.

Then:

```text
Target compiled
       |
search plan
       |
discovery
       |
research
       |
verification
       |
qualification
       |
results
```

### Direct interaction also works

User can immediately say:

> Find 50 targets matching this description.

No "start agent" command should be required.

The host model recognizes the intent and invokes `prospect`.

---

# 26. TOOL UX PRINCIPLE

The user should not need to understand:

- MCP internals
- tool names
- source routing
- retries
- evidence storage
- vector databases
- orchestration implementation

The AI host should translate user intent into tool execution.

Low-level tools exist for precise control and agent reasoning, while `prospect` provides the natural end-to-end path.

---

# 27. PLAYGROUND

The website consists only of:

1. **Landing page**
2. **Playground**

The Playground is **not a second agent implementation**.

It is a user-facing interface that connects to and executes **the same REAVER MCP we build for external AI hosts**.

Conceptually:

```text
             PLAYGROUND
                  |
          User selects BYOK model
                  |
          User provides keys
                  |
                MCP
                  |
       Lead Intelligence Engine
                  |
            final results
```

## Playground model selection

The Playground must contain a **model-selection checklist**.

The checklist lets the user choose the provider/model configuration that will act as the LLM for the Playground.

The precise provider/model list must be based on the providers actually supported by the implementation.

Conceptually:

```text
PRIMARY MODEL
[ ] Provider / Model A
[ ] Provider / Model B
[ ] Provider / Model C
...

FALLBACK MODEL
[ ] Provider / Model A
[ ] Provider / Model B
[ ] Provider / Model C
...
```

The selected primary model uses the **Primary API Key**.

The selected fallback model uses the **Fallback API Key**.

Only a configured primary + fallback pair should be used for an execution. The UI should clearly show which model is primary and which is fallback.

Do not expose secrets in the client.

## Playground input

Natural-language target/ICP:

```text
Find 50 targets matching these requirements:
[ user-defined request ]
```

The Playground sends the request to the **same REAVER MCP** used by external AI clients.

## Playground output selection

The Playground must explicitly provide:

```text
Output format:
( ) CSV
( ) JSON
```

Only these two formats exist.

If the user does not choose an option:

```text
default = CSV
```

The chosen format is passed through the MCP workflow.

## Live execution

Show visible steps:

```text
Understanding target       ✓
Generating search plan     ✓
Checking source health     ✓
Discovering candidates     ✓
Candidates found           ✓
Deduplicating              ✓
Researching candidates     ✓
Verifying evidence         ✓
Qualifying                 ✓
Preparing CSV/JSON         ✓
```

## Results

Show:

- target/entity
- canonical domain or identifying information
- relevant attributes
- key signals
- qualification state
- confidence
- evidence count
- evidence freshness
- "Why qualified?" expandable section
- source links
- selected output format
- export/download control

The Playground must use the MCP directly rather than duplicating its discovery/research/qualification logic.

# 28. BYOK PROVIDER ARCHITECTURE

The provider layer should be abstraction-based.

Conceptually:

```text
             PLAYGROUND / BYOK CLIENT
                        |
              +---------+---------+
              |                   |
           Primary            Fallback
        selected model       selected model
              |                   |
        Primary key          Fallback key
              |                   |
              +---------+---------+
                        |
                       MCP
                        |
                 Agent Runtime
```

Requirements:

- provider interface is abstracted
- primary model/provider is selectable
- fallback model/provider is selectable
- primary API key is configurable
- fallback API key is configurable
- provider failure is detected
- fallback is attempted according to policy
- credentials remain server-side
- no provider key is embedded in frontend code
- model identifiers are configurable
- exact supported provider APIs/models must be verified during implementation

REAVER's MCP itself should not assume one provider's request/response format everywhere.

The Playground is only an interface around the same REAVER MCP and BYOK model-selection layer; it is not a separate AI/agent backend.

# 29. WEBSITE SCOPE

Only:

```text
Landing Page
Playground
```

No additional website modules are required in the hackathon specification.

---

# 30. WHAT NOT TO BUILD

Strict non-goals for the hackathon:

- automated cold outreach
- email sending
- LinkedIn messaging
- campaign management
- lead nurturing
- revenue forecasting
- sales-call analysis
- giant CRM suite
- custom foundation model
- model training
- unrestricted scraping/bypass systems
- mandatory CLI product
- industry-specific product shells

Keep the D1 core on:

> **discover → research → enrich → verify → qualify → deduplicate → export**

---

# 31. DEMO STORY

The strongest demo is not a feature tour.

It is one universal target solved end-to-end.

Example:

```text
User describes target.
       |
Agent interprets target.
       |
Searches multiple relevant sources.
       |
Builds candidate pool.
       |
Removes duplicates/weak candidates.
       |
Deep researches promising targets.
       |
Cross-checks evidence.
       |
Rejects stale/contradictory candidates.
       |
Produces verified qualified leads.
       |
Explains every important decision.
       |
Exports them.
```

The target should be chosen for the actual live demo, but the engine itself must remain domain-agnostic.

---

# 32. TECHNICAL COMPONENTS

Suggested conceptual modules:

```text
mcp/
  server
  schemas
  tool definitions

agent/
  orchestrator
  target compiler
  planner
  qualifier
  evidence reasoner

discovery/
  source router
  candidate normalizer

research/
  target researcher
  signal extractor

evidence/
  collector
  verifier
  freshness engine
  contradiction detector
  citation mapper

data/
  cache
  vector store
  relational store
  entity resolver

connectors/
  web/search
  business sources
  authorized public sources
  contact/enrichment sources
  CRM/export sources

playground/
  API
  execution streaming
  UI

provider/
  primary BYOK adapter
  fallback BYOK adapter

compliance/
  robots.txt
  source policy
  rate limit
```

Exact language/framework/database choices are implementation decisions.

---

# 33. EVALUATION ALIGNMENT

The project should intentionally map to the supplied 500-mark rubric.

## Creativity — 100

### Visual/UX design — 40
Premium landing page + polished Playground + live execution visualization + evidence cards.

### Beyond-chat interaction — 30
Natural-language target input, live workflow status, lead/target cards, evidence panels, filters, exports.

### Polish & delight — 30
Loading, empty, error, retry, source unavailable, stale evidence, rate-limit states.

## Problem relevance — 100

### Problem-market fit — 40
Real-world autonomous prospect discovery and qualification.

### Originality — 30
Evidence-first, source-routed, model-agnostic, universal target model rather than a generic lead list generator.

### Practical usability — 30
Natural-language target definition, automatic planning, usable final dataset, traceable evidence.

## Technical — 100

### Core pipeline — 20
Document/source processing, embeddings/vector store/retriever where applicable, all integrated into the research/evidence pipeline.

### RAG quality — 20
Evidence retrieval with traceable source mapping.

### Tool design/calling — 25
Well-defined MCP tools with real deterministic logic and real source connectors.

### Agent reasoning/orchestration — 25
Target compiler → discovery → enrichment → verification → qualification → dedup → export.

### Live correctness — 10
End-to-end execution, fallbacks, retries, graceful failure.

## Video — 200

Video is a separate phase and should not distort the engineering scope right now.

---

# 34. DEFINITION OF DONE

The MVP is done only when all of the following work in a live run:

```text
[ ] Natural-language target/ICP input
[ ] Target extraction/confirmation
[ ] Multi-source discovery
[ ] Candidate normalization
[ ] Research
[ ] Enrichment
[ ] Evidence collection
[ ] Evidence retrieval / RAG
[ ] Qualification
[ ] Explainable qualification
[ ] Freshness awareness
[ ] Contradiction detection
[ ] Deduplication
[ ] robots.txt compliance
[ ] Caching
[ ] Rate-limit/failure handling
[ ] CSV/JSON export
[ ] MCP server
[ ] Playground using the same MCP
[ ] Primary BYOK key
[ ] Fallback BYOK key
[ ] Primary model-selection checklist
[ ] Fallback model-selection checklist
[ ] Secure server-side credential handling
[ ] Output selection: CSV or JSON only
[ ] Default output: CSV when no format is selected
[ ] MCP output selection: CSV or JSON only
[ ] MCP default output: CSV when no format is selected
[ ] Polished landing page
[ ] Live end-to-end demo
```

There is **no project-provided inference key requirement** for the user-facing Playground.

---

# 35. ENGINEERING PRINCIPLES

1. **No hallucinated evidence.**
2. **No fabricated contacts or entity facts.**
3. **Every important claim should have provenance.**
4. **Do not treat stale information as current.**
5. **Do not hide source failures.**
6. **Prefer primary evidence when available.**
7. **Use independent-source confirmation for high-value criteria.**
8. **Never bypass access controls or robots.txt.**
9. **Do not couple the agent to one LLM provider.**
10. **Do not couple discovery to one data vendor.**
11. **Use deterministic code for deterministic tasks.**
12. **Let the LLM reason where reasoning is useful, not where code is better.**
13. **Keep the D1 scope tight.**
14. **Make the agent trace visible enough for judges to understand what happened.**
15. **Keep target/qualification logic domain-agnostic.**
16. **Never force a conclusion when evidence is insufficient.**

---

# 36. IMPORTANT NOTE ON "MAXIMUM CAPABILITY"

Target:

> **Maximum practical, compliant, evidence-backed source reach across domains and industries.**

Do not use claims such as:

- "100% of the internet"
- "works with every platform"
- "never fails"
- "perfect lead accuracy"
- "the first system to ever do this"

unless independently verified.

A stronger technical statement is:

> "The system continuously chooses among available source backends, validates evidence, falls back when a source fails, respects source restrictions, and refuses to invent unavailable information."

That is the defensible engineering goal.

---

# 37. FINAL PRODUCT DEFINITION

## We are building:

**REAVER — a universal, MCP-first autonomous lead-intelligence system that lets an AI agent turn a natural-language target definition into a verified, evidence-backed, deduplicated set of qualified leads across industries, fields, domains, and user types.**

Its key architecture is:

```text
AI HOST
(ChatGPT / Claude / Codex / OpenCode / other MCP clients)
                    |
                  MCP
                    |
           Lead Intelligence Engine
                    |
       +------------+------------+
       |            |            |
   Discovery      Research    Verification
       |            |            |
       +------------+------------+
                    |
              Qualification
                    |
             Evidence / RAG
                    |
              Deduplication
                    |
                 Export
```

Two execution modes:

```text
1. AI Host / MCP
   -> host's model
   -> our MCP capabilities

2. BYOK Playground
   -> user's selected primary provider/model + primary key
   -> user's selected fallback provider/model + fallback key
   -> same MCP
```

The website scope is only:

```text
Landing Page
Playground
```

Outreach is out of scope.

The CLI is out of scope as a primary product interface.

The model provider is not owned by the core product.

Output formats are strictly limited to:

```text
CSV
JSON
```

If the user does not select a format in either the MCP workflow or Playground, the default is **CSV**.

The goal is not to make the largest feature list.

The goal is to make **one universal D1 workflow extremely reliable, explainable, agentic, portable, provider-agnostic, source-aware, and impressive in a live demo.**

---

# 38. HANDOFF TO OPENCODE

Use this file as the product/architecture brief.

Before implementing, Opencode should independently validate:

- current MCP protocol/API behavior
- current ChatGPT / Claude / Codex / OpenCode integration constraints
- every source connector's actual availability and terms
- current provider API interfaces
- package/library versions
- robots.txt behavior
- rate limits
- all credentials/environment variables
- testability of each connector
- model-selection and primary/fallback provider behavior
- MCP output selection behavior (CSV/JSON, default CSV)
- Playground's direct use of the MCP rather than a duplicated agent implementation

**Do not invent a connector simply because a source is named in this document.**

For every external integration, the implementation must verify that the connector actually works in the current environment and provide a truthful fallback when it does not.

The engineering objective is:

> **Build the most capable practical universal D1 lead-intelligence agent possible within the hackathon time, without sacrificing correctness for breadth.**
