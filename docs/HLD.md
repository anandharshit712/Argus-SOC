# Argus SOC — High-Level Design (HLD)

What the system is, its parts, the decisions behind them and the qualities it must have.
Diagrams are in `ARCHITECTURE.md`; module-level detail is in `LLD.md`; data flows are in `DFD.md`.

## 0. Who works on what in this document

| Section | Owner | Why it matters to you |
|---|---|---|
| 1–3. Purpose, goals, overview | Everyone | Shared understanding of what we're proving |
| 4. Components: Talos service, ingestor, agents, learning | **A — Harshit** | Your components and their responsibilities |
| 4. Components: FalkorDB, graph tools, inventory, deployment | **B — Database and graph** | Your components and their responsibilities |
| 4. Components: API, UI, submission | **C — UI, API and submission** | Your components and their responsibilities |
| 5. Data model | **B** owns; **A** and **C** follow | The three layers every part reads and writes |
| 6. External interfaces | **A** (Talos API, MCP client), **C** (UI API), **B** (MCP server) | The boundaries you own |
| 7. Design decisions | Everyone | Why things are the way they are; don't reopen without the team |
| 8. Non-functional requirements | A: reliability of agents and ingestor · B: performance, isolation, persistence · C: usability, security at the edge | Targets you're measured against |
| 9. Deployment | **B** | How it runs on OCI |
| 10–11. Risks, open decisions | Everyone; owner named per row | What could go wrong, what's still undecided |

Owners: **A** = Agents + Talos integration (Harshit) · **B** = Database and graph (Md Adnan Afzal) ·
**C** = UI, API and submission (to be filled in).

---

## 1. Purpose and scope

**Purpose.** A security analyst sees alerts one at a time; the real questions are about
connections. Argus SOC loads detections into a FalkorDB graph alongside the environment (hosts,
users, network links, crown jewels) and past decisions, then runs three agents that correlate,
investigate, decide and learn, explaining every decision as a path through the graph.

**In scope (hackathon, Oct 15–18, 2026)**

- Detection by Talos (existing, unchanged) for web and network attacks.
- Ingestion of Talos incidents into a per-tenant FalkorDB graph.
- Three agents: Triage, Investigator, Responder.
- Memory: cases, decisions, analyst feedback, versioned playbooks; survives restarts.
- Two tenants (Acme, Globex) with isolated graphs.
- Analyst UI with approve / reject / benign, path view, playbooks, live agent activity.
- Deployment on one OCI instance with HTTPS.

**Out of scope**

- Changing Talos, or pushing learnings back into it (a post-hackathon feature).
- Real response actions against infrastructure (all actions are simulated).
- Real customer data, authentication and user management, multi-instance scaling.

## 2. Goals and success criteria

| # | Goal | Track | How we show it |
|---|---|---|---|
| G1 | A multi-hop query decides the action | 01 | Scenario 1: path bastion-01 → app-02 → db-prod-01 drives isolation |
| G2 | Graph algorithms are agent tools | 01 | Shortest path, centrality ranking, connected components in scenario 1 |
| G3 | The agent acts and can lower urgency | 01 | Scenario 1 isolates; scenario 3 drops a high to medium |
| G4 | Memory persists across sessions | 02 | Scenario 2 survives `docker compose restart agents` |
| G5 | Memory updates from feedback | 02 | Benign verdict → Playbook v2 → auto-close |
| G6 | Shared state and handoffs | 02 | Case handed Triage → Investigator → Responder through the graph |
| G7 | Tenant isolation | 02 | Scenario 4: same IP in Globex, no Acme memory |
| G8 | The graph is essential | Rules | Remove FalkorDB and no decision can be made |
| G9 | The agent selects graph tools over MCP | 01 | Investigator deep dive: the LLM picks read-only graph tools from the MCP server, up to `DEEP_DIVE_MAX_CALLS`; each call and result shown on the case |
| G10 | Agents write and use semantic memory | 02 | Scenario 1 marks `svc_deploy` suspected compromised and `bastion-01` targeted; a later alert on them is raised one priority step, citing the fact |
| G11 | Concurrent reads and writes without clashes | 02 | Burst of ~30 alerts over both tenants with two agent workers: every case processed once, one Decision each, both workers in the activity feed |

How each track's focus maps to these goals:

| Track | Focus named in the brief | Goals |
|---|---|---|
| 01 | Multi-hop reasoning | G1 |
| 01 | Graph queries and algorithms as tools | G1, G2 |
| 01 | MCP tool selection | G9 |
| 01 | Actions from graph results | G3 |
| 01 | Explainable results | G1, G3 (Decision evidence, Q6 path, deep-dive calls) |
| 02 | Episodic, semantic, procedural memory | G4 (episodic), G10 (semantic), G5 (procedural) |
| 02 | Persistent history | G4 |
| 02 | Shared state and handoffs | G6 |
| 02 | High-concurrency reads and writes | G11 |
| 02 | Per-tenant memory | G7 |

## 3. Architecture overview

Four layers, each with one job:

1. **Detection (Talos).** Turns raw logs into IncidentReports with evidence, scope, MITRE
   mapping, severity and confidence. Knows nothing about the environment or past decisions.
2. **Context (ingestor + FalkorDB).** Merges each incident into the tenant's graph next to
   the seeded environment and all earlier memory.
3. **Reasoning (three agents).** Read the graph through fixed queries, decide, and write
   cases, findings, semantic facts and decisions back. The Investigator can also let the LLM
   choose extra read-only graph tools over MCP; their results are evidence, never the decision.
4. **Human loop (API + UI).** Shows cases with their evidence paths, collects analyst verdicts,
   and turns them into memory.

See `ARCHITECTURE.md` §1–3 for the context, deployment and component diagrams.

## 4. Components

| Component | Responsibility | Technology | Owner |
|---|---|---|---|
| Talos service | Detect attacks in replayed logs; serve reports over HTTP | Talos (pinned), FastAPI, PostgreSQL | A |
| Scenario logs + replay | Fixed log files per scenario; replay into Talos | Talos log formats, `talos replay` | A |
| Ingestor | Poll Talos, map new reports into the right tenant graph | Python async, httpx | A |
| Triage agent | Playbook check, recall and semantic facts, correlation, case creation, priority | Python, graph tools, LLM (optional) | A |
| Investigator agent | Blast radius and paths to crown jewels; writes semantic facts; optional MCP deep dive | Python, graph tools, MCP client, LLM (optional) | A |
| Responder agent | Rank hosts, apply decision table, record explained decision | Python, graph tools, LLM (optional) | A |
| Learning service | Analyst feedback → versioned playbooks | Python, graph tools | A |
| FalkorDB | The only state store; one named graph per tenant | FalkorDB (Docker) | B |
| Graph tools library | All Cypher: reads Q1–Q6, algorithms, writes, stubs | Python, `falkordb` client | B |
| MCP server | Read-only graph tools exposed over MCP (stdio) for the deep dive | Python `mcp` SDK | B |
| Asset inventory + seed | Environment per tenant; reset command | YAML + Python script | B |
| Deployment | Compose, Dockerfiles, nginx, HTTPS, OCI | Docker Compose, nginx | B |
| Backend API | REST endpoints for the UI | FastAPI, Pydantic v2 | C |
| Analyst UI | Case queue, case detail with path, feedback, playbooks, activity | Framework chosen by C | C |
| Submission | README, demo video, docs | Markdown, screen recording | C |

## 5. Data model overview

One FalkorDB graph per tenant (`tenant_acme`, `tenant_globex`), in three layers:

| Layer | Nodes | Written by | Read by |
|---|---|---|---|
| Environment | Host, User, Service, Endpoint, AssetTag | Seed script (B) | Investigator, Responder, API |
| Activity | Alert, IOC, Technique | Ingestor (A) | All agents, API |
| Memory | Case, Decision, Feedback, Playbook, AgentRun | Agents (A), API (C) | All agents, API |

The memory types the Track 02 brief names map to it directly:

- **Episodic:** Case, Decision, AgentRun.
- **Semantic:** facts stored on Host, User and IOC, written by the Investigator (targeted,
  suspected compromised, seen in cases) and by analyst feedback (owner, verdict), read by Triage.
- **Procedural:** Playbook versions.

Full schema: `ARCHITECTURE.md` §4 and `LLD.md` §4.1.

## 6. External interfaces

| Interface | Direction | Protocol | Owner | Contract |
|---|---|---|---|---|
| Talos reports | Talos → ingestor | HTTP GET `/healthz`, `/reports`, `/reports/{incident_id}` | A | Talos `IncidentReport` schema (read-only for us) |
| UI API | browser → api | HTTPS REST under `/api/{tenant}/…` | C | `api_models.py` |
| Graph tools | agents, ingestor, api → graph | Python function calls | B | `read_queries.py`, `write_queries.py` signatures |
| LLM | agents → provider | HTTPS, provider TBD | A | `llm_client.complete(prompt, schema)` |
| MCP | Investigator → graph tools | MCP over stdio | B (server), A (client) | Read functions only; tenant set by code, never by the LLM |

## 7. Key design decisions

| # | Decision | Why | Alternative rejected |
|---|---|---|---|
| D1 | Talos is a separate service called over HTTP | Clean boundary judges can see; Talos stays unchanged and credited | Importing Talos as a library (blurs what was built during the event) |
| D2 | FalkorDB is the only Argus SOC state store | Hackathon rule: the product must not work without the graph | Framework checkpoints or Redis for agent state |
| D3 | One named graph per tenant | Isolation by construction; FalkorDB supports thousands of graphs | Tenant property on every node (one missed filter leaks data) |
| D4 | All Cypher in one library with fixed, tested queries | Agents can't write bad Cypher; one owner for query quality | Letting the LLM generate Cypher |
| D5 | Agents are stateless workers that claim cases by status | Crash-safe, restartable, parallel across cases | Long-running in-memory agent sessions |
| D6 | Deterministic decision table; LLM only explains | Repeatable demo; works with no LLM; decisions traceable | LLM decides the action |
| D7 | Writes use `MERGE`, one short query each | Idempotent retries; no clashes between parallel workers | Multi-statement transactions |
| D8 | Ingestor polls instead of Talos pushing | Talos must not change; polling is idempotent with MERGE | Webhook from Talos |
| D9 | Response actions are simulated | Safe demo; no real infrastructure | Real firewall or IAM calls |
| D10 | UI talks only to our API, never to FalkorDB | One place for validation; UI can use mocks from day one | UI querying the graph directly |
| D11 | MCP tool selection is a bounded, read-only deep dive after the fixed queries | Shows the agent choosing tools (Track 01) without letting the LLM decide, write or cross tenants | LLM drives the whole investigation through MCP |
| D12 | Semantic facts store case-id lists, not counters | Writing the same case twice changes nothing (D7) | Incrementing counters |

## 8. Non-functional requirements

Targets are for the demo on one OCI instance. All numbers are proposed and can be tuned.

| Quality | Requirement | Owner |
|---|---|---|
| Latency | New Talos incident visible in the graph within 10 s; a case moves from `new` to a decision within 30 s with the LLM on, 10 s with it off | A |
| Query speed | Each graph tool call under 200 ms on the demo graphs (≤ 200 hosts per tenant) | B |
| Persistence | Graph data survives container restarts (mounted volume) | B |
| Reliability | One bad report or failed LLM call never stops the ingestor or an agent; retry with backoff, log, continue | A |
| Idempotency | Re-ingesting a report or re-running a step never duplicates nodes | A, B |
| Isolation | No query reads or writes more than one tenant graph | B |
| Explainability | Every Decision stores the query results it used and an explanation path | A, B |
| Determinism | Same scenario files + same seed give the same cases and decisions | A, B |
| Security | Only nginx exposed; HTTPS; secrets only in `.env`; log content treated as untrusted; all queries parameterised | B, A, C |
| Usability | An analyst can see why a decision was made in one screen (case detail with path) | C |
| Observability | Every agent step logged with tenant, case id and agent; AgentRun nodes feed the UI activity view | A, C |

## 9. Deployment

- One Docker Compose project on the OCI instance: nginx, ui, api, agents, ingestor, falkordb,
  talos, talos-postgres (`ARCHITECTURE.md` §2).
- nginx terminates HTTPS and routes `/` to the UI and `/api` to the API. Nothing else is
  published.
- Volumes: `falkordb-data` and `talos-pg-data`.
- `scripts/seed_tenants.py` loads both inventories; `scripts/reset_demo.py` wipes and reseeds.
- Fallback if the instance can't run everything: local `docker compose up` with full README
  steps, plus the demo video.

## 10. Risks and mitigations

| Risk | Impact | Mitigation | Owner |
|---|---|---|---|
| Talos's IncidentReport has no structured source-IP field | IOC nodes missing; correlation by IP fails | Extract IPs from verdict evidence (raw log lines) and recommended-action text, validate with `ipaddress`; verify on day 1 against real Talos output | A |
| FalkorDB algorithm procedure names differ from drafts | Q2, Q3, Q5 fail | Check docs on day 1; fall back to plain Cypher variable-length paths | B |
| Scenario logs don't trigger the expected detectors | No incidents | Start from Talos's demo chains; test each with `talos replay` first | A |
| Instance runs out of RAM | Services crash | Check specs on day 1; trim Talos to one instance; reduce inventory size | B |
| LLM unavailable or slow | Agents stall | Templated explanations; decision table needs no LLM | A |
| Judges see Talos as most of the project | Lower score | README and video show the boundary clearly | C |
| Agent work runs late (critical path) | No end-to-end demo | Stubs from day 1; C can take over learning logic | A, C |
| Contract drift between streams | Integration breaks on Oct 16 | Contracts frozen; changes announced to all three | Everyone |
| LLM picks poor tools in the deep dive | Noisy or empty extra evidence | Call cap, schema validation, unknown tool ends the dive; decision never depends on it | A |
| MCP server or SDK doesn't fit in time | G9 missing | Fallback: code picks from a short tool menu, still called over MCP | A, B |

## 11. Open decisions

| Decision | Options | Decide by | Owner |
|---|---|---|---|
| Agent framework | Plain Python + `mcp` client (recommended; fits stateless workers and rule A4) · LangGraph | Oct 15 | A |
| LLM provider | Whatever is at hand during the build | Oct 16 | A |
| Tenancy with Talos | One Talos per tenant · one Talos + host-name mapping | Oct 15 | A, B |
| UI framework | React + TypeScript + Vite suggested | Oct 15 | C |
| Polling interval | 2–5 s | Oct 16 | A |
