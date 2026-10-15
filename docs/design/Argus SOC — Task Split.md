# Argus SOC — Task Split

Oct 15, 2026 · @Harshit Anand

## Ownership

Three workstreams, one owner each. The streams meet only at three agreed interfaces (see Interface contracts), so each person can build and test alone with stubs until the Oct 16 integration checkpoint.

| Workstream | Owner | Delivers |
| --- | --- | --- |
| A. Agents + Talos integration | @Harshit Anand | Talos running, ingestor, scenario logs, Triage / Investigator / Responder agents, learning logic |
| B. Database and graph | To be chosen by the team | FalkorDB, schema, asset inventory, graph tools library (Q1–Q6 + writes), Docker Compose and OCI deployment |
| C. UI, API and submission | To be chosen by the team | Backend API for the UI, analyst UI, live demo view, README, demo video |

The two open owners pick B or C between themselves today, then put their name in this table.

Reference: the design doc, "Argus SOC — FalkorDB Hackathon Design", for the full data model, queries and demo scenarios.

## Workstream A — Agents + Talos integration

Owner: @Harshit Anand. Turns Talos incidents into graph alerts and runs the three agents that make every decision. This is the critical path: the demo cannot run without it.

**Talos service**

- [ ] Write a Dockerfile for Talos in our repo, pinned to a commit of the public Talos repo. Talos itself is not changed.
- [ ] Run `talos serve` with its own PostgreSQL; confirm `GET /healthz` responds.
- [ ] Run Talos with no LLM keys first (`used_llm=false`) so detection never depends on a model.

**Scenario logs**

- [ ] Write the four scenario logs in Talos's web and sshd formats, starting from `data/samples/demo_web_chain.log` and `demo_network_chain.log`.
- [ ] Check each one with `talos replay` and confirm the expected detector fires (SSH brute force that succeeds, credential stuffing, SQLi).
- [ ] Share the host names, accounts and IPs with Workstream B so the asset inventory matches.

**Ingestor**

- [ ] Poll `GET /reports` every few seconds; fetch each unseen `incident_id` with `GET /reports/{incident_id}`.
- [ ] Map each report to the graph using B's write functions (never raw Cypher): Alert, Host, User, Endpoint, IOC, Technique.
- [ ] Decide tenancy on day 1: one Talos per tenant, or map by host name.

**Agents (Python)**

- [ ] Pick the agent framework and LLM provider.
- [ ] Triage: playbook check → recall (Q4) → correlate (Q5) → open or join a case → hand off.
- [ ] Investigator: blast radius (Q1) and paths to crown jewels (Q2) → findings on the case → hand off.
- [ ] Responder: rank (Q3), apply the decision table, write Decision + explanation (Q6), mark whether approval is needed.
- [ ] Handoffs: record `HANDED_OFF_TO` and case status; an agent that restarts reads the case from the graph and carries on.
- [ ] Several cases in flight at once without clashes.

**Learning**

- [ ] Benign Feedback → new Playbook version linked with `LEARNED_FROM`; Triage checks playbooks first next session.

**How:** code against stub versions of B's graph functions from hour one, so agent logic doesn't wait for the database. Keep every decision traceable to a query result: that's what judges will check.

## Workstream B — Database and graph

Owner: to be chosen. Owns everything inside FalkorDB and the way the rest of the system reaches it. This is the core of both tracks: the rules say the product must stop working without the graph.

**FalkorDB setup**

- [ ] Run `falkordb/falkordb` in Docker with data on a mounted volume, so memory survives restarts.
- [ ] One named graph per tenant: `tenant_acme`, `tenant_globex`.
- [ ] Indexes on the lookup keys: `Alert.incident_id`, `Host.hostname`, `User.username`, `IOC.value`, `Case.id`.

**Schema**

- [ ] Freeze node labels, relationships and properties today (Interface contracts → schema), from the design doc's data model.
- [ ] Write the schema into the README: it is a required submission item.

**Asset inventory**

- [ ] A seed script that generates each tenant's environment: hosts, users, services, endpoints, `CONNECTS_TO`, `LOGGED_INTO`, crown-jewel tags.
- [ ] Use the names from A's scenario logs (bastion-01, app-02, db-prod-01, web-01, vpn-gw, svc\_deploy, 10.0.5.20).
- [ ] Make sure the demo paths exist: bastion-01 → app-02 → db-prod-01 for Acme; no path from web-01 to a crown jewel.

**Graph tools library (Python)**

- [ ] Read functions Q1–Q6 (blast radius, paths to crown jewels, centrality ranking, recall, connected components, explain decision).
- [ ] Write functions: alert from a Talos report, case, decision, feedback, playbook, agent run, handoff. All with `MERGE`, one short query each.
- [ ] Check FalkorDB's algorithm procedure names (shortest path, PageRank or betweenness, WCC) against docs.falkordb.com on day 1.
- [ ] Unit tests for each function against the seeded graph.
- [ ] Optional: expose the read functions over MCP, which Track 01 names explicitly.

**Deployment**

- [ ] Docker Compose: talos, talos-postgres, falkordb, ingestor, agents, api, ui.
- [ ] OCI instance: check RAM, set up the reverse proxy with HTTPS, keep FalkorDB, Talos and Postgres ports private.
- [ ] A reset command that wipes and reseeds both tenants for judges.

**How:** ship stub versions of every function signature on Oct 15, returning fixed sample data, so A and C can code against them immediately. Replace stubs with real queries one by one.

## Workstream C — UI, API and submission

Owner: to be chosen. Owns everything a judge sees: the analyst screen, the live view of the agents, and the submission package.

**Backend API for the UI (Python, FastAPI)**

- [ ] Endpoints from the Interface contracts: case list, case detail, approve / reject / benign, tenant switch, live activity.
- [ ] Reads and writes go through B's graph tools library, never raw Cypher in the API.
- [ ] Serve mock JSON from hour one so the UI never waits on the graph.

**Analyst UI**

- [ ] Case queue per tenant: priority, status, Talos category, auto-closed or waiting for approval.
- [ ] Case detail: alerts, Talos evidence, the agent's decision and the graph path behind it (bastion-01 → app-02 → db-prod-01) drawn as a small graph.
- [ ] Approve / reject / mark benign with a reason; the result shows up as Feedback.
- [ ] Playbook list with versions and the case each was learned from.
- [ ] Tenant switcher (Acme / Globex) to show isolation.

**Live demo view**

- [ ] A feed of agent activity (Triage picked up case, handed to Investigator, …) from AgentRun nodes, so the video shows the agents working.

**Submission package**

- [ ] README: setup steps, graph data model (from B), Cypher queries Q1–Q6, architecture diagram, AI-assistant disclosure, credit to Talos (Apache licence) and what was built Oct 15–18.
- [ ] Demo video following the design doc's demo script, plus a recorded backup in case the live demo fails.
- [ ] Submission form: both tracks named, live URL, repo link, every teammate on the WeMakeDevs panel.
- [ ] Optional: blog post for the AirPods side prize.

**How:** start with the case detail screen; it carries the demo. Build against mock data that matches the agreed JSON shapes, then switch to the real API on Oct 16.

## Interface contracts

These three contracts are what keep the streams independent. Agree them in today's call; after that, change them only with a message to all three.

**1. Graph schema (owner B, used by everyone)**

| Layer | Nodes | Key relationships |
| --- | --- | --- |
| Environment | Host, User, Service, Endpoint, AssetTag | `LOGGED_INTO`, `CONNECTS_TO`, `RUNS`, `SERVED_BY`, `TAGGED` |
| Activity | Alert, IOC, Technique | `ON_HOST`, `INVOLVES`, `TARGETED`, `MAPS_TO` |
| Memory | Case, Decision, Feedback, Playbook, AgentRun | `CONTAINS`, `HAS_DECISION`, `ACTED_ON`, `ON`, `LEARNED_FROM`, `WROTE`, `HANDED_OFF_TO` |

Case status values: `new`, `triaged`, `investigated`, `awaiting_approval`, `closed`, `auto_closed`. Every function takes `tenant` first.

**2. Graph tools library (owner B, called by A and C)**

```python
# reads
blast_radius(tenant, ioc) -> list[dict]                 # Q1
paths_to_crown_jewels(tenant, host, max_hops=6) -> list[list[str]]  # Q2
rank_hosts(tenant, case_id) -> list[tuple[str, float]]  # Q3
recall(tenant, ioc=None, host=None, user=None) -> list[dict]  # Q4
linked_alerts(tenant, incident_id) -> list[str]         # Q5
explain_decision(tenant, decision_id) -> dict           # Q6
matching_playbook(tenant, alert) -> dict | None
list_cases(tenant, status=None) -> list[dict]
get_case(tenant, case_id) -> dict

# writes (all MERGE)
upsert_alert_from_report(tenant, report: dict) -> str   # returns incident_id
open_or_join_case(tenant, incident_ids) -> int
set_case_status(tenant, case_id, status, priority=None)
record_decision(tenant, case_id, decision: dict) -> str
record_feedback(tenant, case_id, verdict, note, analyst) -> str
create_playbook_version(tenant, feedback_id, condition, action) -> str
record_agent_run(tenant, agent, case_id, handed_to=None) -> str
```

**3. UI API (owner C, reads the graph through B's library)**

| Method + path | Returns or does |
| --- | --- |
| `GET /api/{tenant}/cases?status=` | Case list: id, priority, status, category, created\_at |
| `GET /api/{tenant}/cases/{id}` | Case detail: alerts with Talos evidence, findings, decision, explanation path, feedback |
| `POST /api/{tenant}/cases/{id}/feedback` | Body \`{verdict: approve |
| `GET /api/{tenant}/playbooks` | Playbooks with version and source case |
| `GET /api/{tenant}/activity?since=` | Recent AgentRun entries for the live feed |

The exact JSON shapes for case detail are written by C and agreed with A, since A's agents write the fields it shows.

## Dependencies and checkpoints

The only hard checkpoint is the end of Oct 16: scenario 1 runs end to end, Talos → ingestor → graph → three agents → UI, however rough. Everything after that is the other scenarios and polish.

**Who waits on whom**

- A needs B's write functions for the ingestor and B's read functions for the agents. Covered by B's stubs on Oct 15.
- B needs A's host names, accounts and IPs for the asset inventory. A sends them on Oct 15.
- C needs B's read functions for the API and A's decision fields for case detail. Covered by mock JSON until Oct 16.
- Everyone needs B's Docker Compose for the integrated run on Oct 16.

**Day by day (IST)**

| Day | A — Agents + Talos | B — Database and graph | C — UI, API and submission |
| --- | --- | --- | --- |
| Oct 15 | Contracts call; Talos in Docker; scenario 1 log fires in Talos; ingestor against stubs | Contracts call; schema frozen; stubs for every function; FalkorDB up; Acme seed | Contracts call; API with mock JSON; case list + case detail screens |
| Oct 16 | Triage, Investigator, Responder for scenario 1; handoffs | Real Q1, Q2, Q4, Q5 + all writes; Compose with all services | Switch to the real API; approve / reject flow; activity feed. **End of day: scenario 1 end to end** |
| Oct 17 | Scenarios 2–4; learning loop; parallel cases | Q3, Q6; Globex seed; deploy on OCI with HTTPS; reset command | Playbook view; tenant switch; README draft; first full demo run |
| Oct 18 | Bug fixes only | Bug fixes only; final deploy | Record video; finish README; **submit by 8 PM** (4-hour buffer before 11:59 PM) |

## Working rules

One public repo, one folder per workstream, and a short daily sync keep three people from colliding.

- **Repo layout:** `agents/` and `ingestor/` (A), `graph/` and `deploy/` (B), `api/` and `ui/` (C). Shared code goes only in `graph/`.
- **Branches:** each person works on their own branch and merges to `main` through a pull request. `main` must always start with `docker compose up`.
- **Never in the repo:** `.env` files and API keys. Commit `.env.example` instead.
- **Talos:** used as a pinned dependency, never copied or changed during the event.
- **FalkorDB is the only state store** for Argus SOC. No Redis, vector store or framework checkpoints holding cases or memory.
- **Contract changes:** message all three before changing a function signature, schema name or API shape.
- **Daily sync:** 15 minutes each morning and evening (IST): done, next, blocked.
- **AI coding assistants:** allowed, but each person must be able to explain their own code, queries and design choices to judges. Disclose the use in the README.

**Done means:** the feature works inside `docker compose up` on `main`, has at least one test or a scripted check, and is ticked in this doc.
