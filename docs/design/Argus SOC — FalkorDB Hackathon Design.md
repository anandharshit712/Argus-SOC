# Argus SOC — FalkorDB Hackathon Design

Oct 11, 2026 · @Harshit Anand

## Overview

Argus SOC is a team of security agents that triage alerts, investigate them by walking a FalkorDB graph, and recommend or take a response, while remembering every past case and analyst verdict. One project, entered in Track 01 (Agents That Act on Connected Data) and Track 02 (Agent Memory and Coordination).

**Built on Talos.** Detection comes from [Talos](https://github.com/anandharshit712/Talos), our open-source attack-detection engine under the Apache licence, which Argus SOC calls over its API. Talos is used unchanged. Argus SOC adds what Talos lacks: linking incidents together, memory, and response. Everything outside Talos is new work built Oct 15–18.

**Problem.** A security operations centre (SOC) analyst sees one alert at a time. The real questions are about connections: which other hosts touched this indicator, how could an attacker reach the database server from here, and have we seen this before and closed it as benign?

**What judges must see in the demo:**

| Track | Proof point | Where it shows |
| --- | --- | --- |
| 01 | A multi-hop query decides the action (blast radius, attack path) | Investigator explains its path through the graph |
| 01 | Graph algorithms used as agent tools (shortest path, PageRank, connected components) | Responder ranks which host to isolate first |
| 01 | The agent acts, not just answers | Isolate host, disable user, open a ticket |
| 02 | Memory that lasts across sessions | Day-2 alert recalls incident #12 from day 1 |
| 02 | Memory that updates over time | Analyst marks a case benign; next alert is auto-closed |
| 02 | Shared state and agent handoffs | Triage writes a case; Investigator and Responder pick it up |
| 02 | Separate memory per tenant | Two client companies, two isolated graphs |

**The rule to keep passing:** remove FalkorDB and the product must stop working. Every decision goes through a Cypher query or graph algorithm.

## Graph data model

The model has three layers in one graph per tenant: the environment (what exists), activity (what happened), and memory (what the agents learned). A draft to sketch on paper before Oct 15.

**Environment layer**

| Node label | Key properties | Example |
| --- | --- | --- |
| Host | hostname, ip, os, criticality (1–5), zone | db-prod-01, criticality 5 |
| User | username, role, department, privileged | svc\_backup, privileged |
| Service | name, port, exposed | postgres:5432 |
| AssetTag | name (e.g. crown-jewel, PCI) | crown-jewel |

**Activity layer**

| Node label | Key properties | Example |
| --- | --- | --- |
| Alert | incident\_id, category, severity, confidence, succeeded, ts, status | Talos: SSH brute force, succeeded |
| Endpoint | path, method, app | /api/login |
| IOC | type (ip, domain, hash), value, first\_seen | 185.x.x.x |
| Technique | mitre\_id, name, tactic | T1110 Brute Force |

**Memory layer**

| Node label | Key properties | Example |
| --- | --- | --- |
| Case | id, status, opened\_by, verdict, summary, ts | Case #12, benign |
| Decision | action, reason, agent, ts, outcome | isolate host, approved |
| Feedback | analyst, verdict, note, ts | false positive: backup job |
| Playbook | name, version, steps, conditions | PowerShell from svc account |
| AgentRun | agent, session\_id, ts | Investigator, session 7 |

**Main relationships**

- `(User)-[:LOGGED_INTO {ts}]->(Host)`, `(Host)-[:CONNECTS_TO {port, ts}]->(Host)`, `(Host)-[:RUNS]->(Service)`, (Host)-\[:TAGGED\]->(AssetTag)
- `(Alert)-[:ON_HOST]->(Host)`, `(Alert)-[:INVOLVES]->(User|IOC)`, `(Alert)-[:MAPS_TO]->(Technique)`
- `(Alert)-[:TARGETED]->(Endpoint)`, `(Endpoint)-[:SERVED_BY]->(Host)`
- `(Case)-[:CONTAINS]->(Alert)`, `(Case)-[:HAS_DECISION]->(Decision)`, `(Decision)-[:ACTED_ON]->(Host|User)`
- `(Feedback)-[:ON]->(Case)`, `(Playbook)-[:LEARNED_FROM]->(Feedback)`, `(Case)-[:SIMILAR_TO {score}]->(Case)`
- `(AgentRun)-[:WROTE]->(Case|Decision)`, `(AgentRun)-[:HANDED_OFF_TO]->(AgentRun)`

**Tenancy.** Each client company gets its own named graph (e.g. `tenant_acme`, `tenant_globex`), so one company's memory can never leak into another's. FalkorDB says one instance can hold thousands of separate graphs.

## Agent architecture

Three agents work in a pipeline over one shared Case. Each reads and writes the tenant's graph only through a small set of tested graph tools.

&#91;embedded content: Argus SOC architecture · 3 agents, 1 tool layer, 1 graph per tenant\]

Alerts flow left to right through the agents; every arrow into the graph is a Cypher query, and the analyst's verdicts flow back in as memory.

| Agent | Job | Graph tools it uses | Writes |
| --- | --- | --- | --- |
| Triage | Groups alerts into cases, checks memory for known patterns, auto-closes matches | Q4 recall, Q5 connected components, Playbook match | Case, AgentRun |
| Investigator | Finds blast radius and attack paths to crown-jewel hosts | Q1 blast radius, Q2 shortest path | Findings on the Case, semantic facts |
| Responder | Picks and explains the action; waits for approval on high-impact actions | Q3 centrality ranking, Q6 explain | Decision, ACTED\_ON edges |

**Handoffs.** Each agent finishes by recording a `HANDED_OFF_TO` edge and setting the Case status. The next agent polls for cases in its status, so any agent can crash and resume.

## Talos integration

Talos handles detection; Argus SOC handles everything after it. Talos runs as its own service, and Argus SOC talks to it only over HTTP.

**How data flows**

1. Scenario logs, written in Talos's web and SSH/RDP log formats, are replayed into Talos with `talos replay`.
2. Talos runs its detectors and records an IncidentReport for each incident.
3. The Argus SOC ingestor polls `GET /reports`, then fetches each new incident with `GET /reports/{incident_id}`.
4. The ingestor writes each report into the tenant's graph using `MERGE` on `incident_id`, so reading a report twice never duplicates it.
5. Triage picks up the new Alert from the graph.

Talos endpoints we use: `GET /healthz`, `GET /reports` and `GET /reports/{incident_id}`. `POST /events` is also available for sending a single event directly.

**How a Talos report maps into the graph**

| IncidentReport field | Graph |
| --- | --- |
| The incident (`incident_id`, `category`, `severity`, `confidence`, `summary`) | `Alert` node |
| `aggregate_scope.affected_hosts` | `(Alert)-[:ON_HOST]->(Host)` |
| `aggregate_scope.affected_accounts` | `(Alert)-[:INVOLVES]->(User)` |
| `aggregate_scope.affected_endpoints` | `(Alert)-[:TARGETED]->(Endpoint)` |
| Source IP from the verdicts' events | `(Alert)-[:INVOLVES]->(IOC {type: 'ip'})` |
| `aggregate_scope.succeeded` | `succeeded` property on the Alert (a successful login raises the priority) |
| `mitre_techniques` | `(Alert)-[:MAPS_TO]->(Technique)` |
| `verdicts[].evidence`, `reasoning` | Alert properties, shown in explanations |
| `recommended_actions` | Input for the Responder, which makes the final decision |

Check the field names against Talos's `report_schema.py` and `verdict_schema.py` on day 1.

**Comes from Talos:** six detectors (SQLi, XSS, web brute force, SSH/RDP brute force, credential stuffing, IDOR), MITRE mapping, confidence and evidence, the log parsers, demo attack chains, and the evaluation corpus.

**Built during the event:** the ingestor, the FalkorDB schema, the three agents, Cypher queries Q1–Q6, memory and feedback, tenant isolation, the asset inventory generator, the UI, and the Docker deployment, including a Dockerfile for Talos kept in our repo.

**Boundaries for the hackathon**

- Talos is a dependency pinned to a commit of the public repo. It is never copied into our repo and is not changed during the event.
- Talos keeps its own PostgreSQL audit store internally. All Argus SOC state lives in FalkorDB.
- Argus SOC does not push anything back into Talos.
- The README credits Talos and lists exactly what was built Oct 15–18.

**Tenancy.** Talos has no concept of a tenant. Option A: run one Talos service per tenant (two in the demo). Option B: one Talos service, with the ingestor assigning the tenant from the host name, since each tenant's hosts are unique. Decide on day 1.

**Future feature (after the hackathon):** the feedback loop pushes what it learns back into Talos, for example suppressing a detector for a source known to be benign.

## Memory design

All memory lives in the tenant's graph, so every agent reads and writes the same state, and it survives restarts. The three memory types the Track 02 brief names map directly to the memory layer.

| Memory type | What it stores | Written by | Read by | Example recall |
| --- | --- | --- | --- | --- |
| Episodic | Cases, decisions, agent runs, timestamps | All agents | Triage, Investigator | "IOC 185.x was in Case #12 three weeks ago" |
| Semantic | Facts about hosts, users, IOCs (criticality, normal behaviour, reputation) | Investigator, analyst feedback | All agents | "10.0.5.20 is the internal pentest scanner; benign" |
| Procedural | Playbooks with conditions and versions | Feedback loop | Triage, Responder | "Playbook v2: auto-close this pattern" |

**Feedback loop (the Track 02 "updates over time" proof)**

1. Responder proposes an action and records a Decision node.
2. An analyst approves or rejects it, or marks the case benign; this becomes a Feedback node.
3. When the same pattern gets enough consistent feedback, a new Playbook version is created with a `LEARNED_FROM` edge to that feedback, so the change is traceable.
4. Next session, Triage matches the new alert against Playbook conditions and cites the case that taught it.

**Shared state and handoffs.** A Case node is the shared work item. Each agent claims it, writes its findings and Decision nodes, then records a `HANDED_OFF_TO` edge between AgentRun nodes. Any agent restarted mid-case can rebuild its context with one query.

**Concurrency.** Several alerts arrive at once in the demo, and the agents work on different cases in parallel. Use `MERGE` for idempotent writes and keep each write to one short query, so parallel agents don't clash on the same nodes.

**Forgetting.** Old low-value episodes can be summarised into a single node and pruned. This is optional; skip it if time is short.

## Core Cypher queries and graph algorithms

These six queries are the agents' tools and go in the README, which the rules require. They are drafts: check syntax and algorithm procedure names against the [FalkorDB Cypher docs](https://docs.falkordb.com/cypher) and [algorithms docs](https://docs.falkordb.com/algorithms) on day 1.

**Q1. Blast radius: what else touched this indicator (Investigator)**

```cypher
MATCH (i:IOC {value: $ioc})<-[:INVOLVES]-(a:Alert)-[:ON_HOST]->(h:Host)
OPTIONAL MATCH (a)-[:INVOLVES]->(u:User)-[:LOGGED_INTO]->(h2:Host)
RETURN h.hostname, h.criticality,
       collect(DISTINCT u.username) AS accounts,
       collect(DISTINCT h2.hostname) AS reached_hosts,
       count(DISTINCT a) AS alerts
ORDER BY h.criticality DESC
```

**Q2. Attack path to crown jewels (Investigator, algorithm as a tool)**

```cypher
MATCH (src:Host {hostname: $host}), (dst:Host)-[:TAGGED]->(:AssetTag {name: 'crown-jewel'})
WITH src, dst
MATCH p = shortestPath((src)-[:CONNECTS_TO|LOGGED_INTO*1..6]-(dst))
RETURN [n IN nodes(p) | coalesce(n.hostname, n.username)] AS path, length(p) AS hops
ORDER BY hops LIMIT 3
```

**Q3. Which host to isolate first (Responder)** — run PageRank or betweenness centrality on the `CONNECTS_TO` subgraph of affected hosts, then rank by centrality × criticality.

**Q4. Have we seen this before? (Triage, episodic recall)**

```cypher
MATCH (c:Case)-[:CONTAINS]->(:Alert)-[:INVOLVES]->(i:IOC {value: $ioc})
OPTIONAL MATCH (f:Feedback)-[:ON]->(c)
RETURN c.id, c.verdict, c.ts, f.note ORDER BY c.ts DESC LIMIT 5
```

**Q5. Group related alerts into one incident (Triage)** — connected components (WCC) over alerts linked by a shared host, user or IOC, so ten noisy alerts become one case.

**Q6. Explain a decision (all agents)**

```cypher
MATCH (d:Decision {id: $id})<-[:HAS_DECISION]-(c:Case)-[:CONTAINS]->(a:Alert)
OPTIONAL MATCH (d)-[:ACTED_ON]->(t)
OPTIONAL MATCH (pb:Playbook)-[:LEARNED_FROM]->(:Feedback)-[:ON]->(prev:Case)
RETURN d, c, collect(a) AS evidence, t, pb, prev
```

The path Q6 returns is shown in the UI as the "why" behind every action.

## Data plan

We use only public and synthetic data, as the rules require. Talos turns scenario logs into incidents. A generated asset inventory supplies the environment that Talos knows nothing about: hosts, users and how they connect. MITRE ATT&CK supplies the technique catalogue.

| Source | Use | Notes |
| --- | --- | --- |
| Scenario logs (our own) in Talos's web and SSH/RDP formats | Replayed into Talos to produce incidents | Start from Talos's `data/samples/demo_web_chain.log` and `demo_network_chain.log`; fixed content so the demo runs the same every time |
| Asset inventory generator (our own script) | Hosts, users, services, endpoints, `CONNECTS_TO` and `LOGGED_INTO` links, crown-jewel tags for 2 tenants | 50–200 hosts per tenant; host names and IPs must match the scenario logs |
| Talos's MITRE mapping | Technique nodes | Load only the techniques Talos emits (e.g. T1110 brute force, T1190 exploit public-facing app) |
| [MITRE ATT&CK (mitre/cti)](https://github.com/mitre/cti) (optional) | Tactic names and descriptions for the UI | Public STIX JSON |

**Three demo scenarios**

1. **Brute force to crown jewel (Acme):** Talos flags SSH brute force on `bastion-01` that succeeds as `svc_deploy`, then credential stuffing on the web app from the same IP. Triage merges both into one case through the shared IP. The Investigator finds the path `svc_deploy` → `app-02` → `db-prod-01`. The Responder isolates `bastion-01` and disables `svc_deploy`.
2. **Benign look-alike (Acme):** a credential-stuffing burst from the internal pentest scanner `10.0.5.20`. In session 1 the analyst marks it benign. After a restart, session 2 auto-closes the same pattern and cites the earlier case.
3. **Injection with no follow-on (Acme):** Talos flags SQLi on `/api/search` with no successful login nearby. The Investigator finds no path to a crown jewel, so the Responder opens a ticket instead of isolating anything. This shows the graph lowering severity as well as raising it.
4. **Cross-tenant check (Globex):** the attacker IP from scenario 1 appears in Globex, which has no memory of it, so it's treated as new. This proves the tenants are isolated.

Writing the scenario logs and the generator counts as building, so it starts on Oct 15. Before then, write the scenario stories, choose host and account names, and check which log lines trigger each Talos detector.

## Stack decision and deployment

Decided: everything is Python, to match Talos, and Talos is called over its API. Deployment is Docker Compose on the OCI instance. Still open: the agent framework, decided by the team, and the LLM provider, chosen during the build from whatever is at hand.

**Stack options to discuss**

| Option | Strength | Weakness | Fit for 4 days |
| --- | --- | --- | --- |
| Python + LLM API tool use (no framework) | Least to learn; full control over the prompts and tools; async like Talos | Handoffs and retries are written by hand | Good if the team already knows the API |
| Python + LangGraph | Built-in multi-agent graphs, handoffs and checkpoints | More to learn; its own state store can make FalkorDB look optional | Good, but keep FalkorDB as the only memory |
| Python + FalkorDB MCP server | Agents choose graph tools over MCP, which Track 01 names explicitly | Less control over query shape; check what the server exposes | Use alongside either option above |

Whatever the choice, avoid using LangGraph checkpoints, Redis or a vector store as the main memory. Judges will ask whether the product still works without FalkorDB.

**Deployment on the OCI instance**

- Docker Compose with six services: `talos` (built from the public Talos repo pinned to a commit, using a Dockerfile kept in our repo), `talos-postgres` (Talos's own audit store), `falkordb` (image `falkordb/falkordb`), `ingestor`, `agents` (API plus workers) and `ui`.
- FalkorDB data on a mounted volume, so memory survives restarts. Restarting live is a good demo moment.
- Keep the FalkorDB, Talos and Postgres ports private. Expose only the UI and the Argus SOC API, through a reverse proxy with HTTPS.
- Put LLM API keys in an env file kept out of the repo, and add a `.env.example` file for the README.
- A seed command loads both tenants' asset inventories and replays the scenario logs into Talos, so judges can reset the demo.
- Check that the OCI instance has enough RAM for all six services. FalkorDB and Postgres are the heaviest.

## Team split and build plan

The work splits into four streams. With a team of 3, combine Data and Deploy & demo; with 2, one person takes Graph + Data and the other Agents + UI.

| Stream | Owns |
| --- | --- |
| A. Graph + data | Schema, Talos ingestor, asset generator, scenario logs for Talos, Cypher queries Q1–Q6 |
| B. Agents | Triage, Investigator and Responder agents, tool wiring, handoffs |
| C. Memory | Case, Decision, Feedback and Playbook writes; recall; per-tenant graphs |
| D. UI + deploy + demo | Case view, graph path view, approve or reject buttons, OCI deploy, README, video |

**Day by day (all times IST)**

| Day | A. Graph + data | B. Agents | C. Memory | D. UI + deploy + demo |
| --- | --- | --- | --- | --- |
| Before Oct 15 (planning only) | Schema on paper, scenario stories, ATT&CK IDs | Prompts and tool list on paper | Memory rules on paper | UI wireframe, OCI Docker ready, decide stack |
| Oct 15 | Talos running + ingestor; generator + seed for tenant A; Q1, Q4 | Triage agent end to end on 1 alert | Case and Decision writes | Talos Dockerfile, Compose stack up on OCI, repo skeleton |
| Oct 16 | Scenarios 1–2; Q2, Q3, Q5 | Investigator + Responder; handoffs | Feedback → Playbook loop | Case view + path view |
| Oct 17 | Tenant B; Q6; query tuning | Parallel alerts; error handling | Cross-session recall test; tenant isolation test | Approve/reject flow; first full demo run |
| Oct 18 | Freeze data | Bug fixes only | Bug fixes only | README, record video, submit by 8 PM (4-hour buffer before 11:59 PM) |

**Rule:** by the end of Oct 16, scenario 1 must run end to end, even if it looks rough. Everything after that is polish.

## Demo script and submission checklist

The video should prove all seven points from the Overview in about 3–4 minutes; the rules don't set a length, so keep it short.

**Demo script**

1. **Problem (20 s):** one alert alone tells you nothing; the connections do.
2. **Lateral movement (60 s):** Talos flags SSH brute force on bastion-01, then credential stuffing from the same IP, and Triage merges them into one case, the Investigator shows the path to `db-prod-01`, and the Responder isolates the most central host and explains why.
3. **Session 1, benign case (30 s):** a credential-stuffing burst from the internal pentest scanner; the analyst marks it benign.
4. **Restart (15 s):** restart the agents container live, to show memory isn't held in process.
5. **Session 2 (30 s):** the same pattern auto-closes, citing Case #12 and the Playbook version it learned.
6. **Tenant B (20 s):** the same IOC is treated as new, showing the tenants are isolated.
7. **Under the hood (30 s):** a Talos IncidentReport becoming graph nodes, then FalkorDB Browser showing the graph and one Cypher query.

**Submission checklist (from the rules page)**

- [ ] Public GitHub repo
- [ ] README: setup steps, graph data model, architecture diagram
- [ ] README credits Talos (Apache licence, pinned commit) and lists what was built Oct 15–18
- [ ] Cypher queries and algorithms listed in the README (Q1–Q6)
- [ ] Demo video
- [ ] Live deployment URL on OCI, plus local setup steps as a fallback
- [ ] Tracks named: Agents That Act on Connected Data + Agent Memory and Coordination
- [ ] AI coding assistant use disclosed in the README
- [ ] Every teammate added on the WeMakeDevs panel
- [ ] Every teammate can explain the graph model, the queries and the Talos boundary
- [ ] Optional: blog post for the AirPods side prize

## Risks and open questions

| Risk | Fallback |
| --- | --- |
| Scope too big for 4 days | Cut Playbook versioning and forgetting first; keep the recall and handoff proofs |
| Judges see Talos as the bulk of the project | README and video show the clear boundary: Talos only detects, and every graph, agent and memory feature is new |
| Scenario logs don't trigger Talos detectors | Start from Talos's own demo chains and check each scenario with `talos replay` on day 1 |
| Talos needs an LLM endpoint | Talos's statistical path works without a model (`used_llm=false`), so the demo doesn't depend on Talos reaching an LLM |
| Talos has no Docker setup | Write its Dockerfile in our repo on day 1; fallback is running Talos natively on the OCI host |
| LLM writes bad Cypher | Agents call the fixed, tested Q1–Q6 tools; free-form Cypher only as a read-only extra |
| Algorithm procedure names differ from the drafts | Check the docs on day 1; fall back to plain Cypher path queries |
| Graph looks like decoration | Every agent decision must cite a query result; no other store for Argus SOC state |
| Demo breaks live | Seed script plus a recorded backup video |
| Rule breach on early work | No code before Oct 15, 12:01 AM IST; don't change Talos during the event |

**Open questions**

- [ ] Agent framework (see the Stack options table)
- [ ] Who owns which stream (team of 3; splitting work on Oct 13)
- [ ] LLM provider, chosen during the build
- [ ] Tenancy with Talos: one Talos per tenant, or one Talos with mapping by host (decide on day 1)
- [ ] OCI instance RAM and CPU; domain and HTTPS for the live demo
- [ ] Judging criteria and results date: ask in the FalkorDB Discord
- [ ] Final project name
