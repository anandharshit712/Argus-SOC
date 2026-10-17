# Argus SOC — Low-Level Design (LLD)

Module by module: configuration, schema, every function, every algorithm, the API and the UI.
This is the document to code from. Where something here differs from the code, fix one of them in
the same pull request.

## 0. Who works on what in this document

| Section | Owner | Notes |
|---|---|---|
| 1. Package layout | Everyone | Matches `FOLDER_STRUCTURE.md` |
| 2. Configuration | **B** owns `.env.example`; each owner adds their own variables | |
| 3. Shared core | **B** writes it; changes need all three | `settings`, `tenant_registry`, `logging_setup` |
| 4. Graph layer | **B — Database and graph** | Schema, indexes, every query function, stubs |
| 5. Ingestor | **A — Harshit** | Talos client, mapping, IP extraction, polling loop |
| 6. Agents and learning | **A — Harshit** | Runner, claiming, three agents, decision table, LLM, learning |
| 7. Backend API | **C — UI, API and submission** | Endpoints, models, errors |
| 8. UI | **C — UI, API and submission** | Pages, components, refresh |
| 9. Errors and retries | A (ingestor, agents), B (graph), C (API) | One table for everyone |
| 10. Logging | Everyone | One format |
| 11. Testing | Each owner for their layer; A for end-to-end | |
| 12. Deployment detail | **B**; A provides the Talos Dockerfile | |

Owners: **A** = Agents + Talos integration (Harshit) · **B** = Database and graph (Md Adnan Afzal) ·
**C** = UI, API and submission (Satya).

---

## 1. Package layout

```
src/argus_soc/
  core/      settings.py · tenant_registry.py · logging_setup.py
  graph/     falkor_client.py · graph_schema.py · index_setup.py · read_queries.py
             algorithm_queries.py · write_queries.py · graph_stubs.py · mcp_server.py
  ingestor/  talos_client.py · report_mapper.py · tenant_resolver.py · ingest_loop.py
  agents/    agent_runner.py · triage_agent.py · investigator_agent.py · responder_agent.py
             decision_table.py · handoff_service.py · learning_service.py · llm_client.py
             graph_tool_client.py · prompts/
  api/       api_server.py · case_routes.py · playbook_routes.py · activity_routes.py
             api_models.py · mock_data.py
```

Entry points (console scripts in `pyproject.toml`): `argus-ingest` → `ingest_loop.main`,
`argus-agents` → `agent_runner.main`, `argus-api` → `api_server.main`.

## 2. Configuration (`.env` → `core/settings.py`)

| Variable | Default | Used by | Owner |
|---|---|---|---|
| `FALKORDB_HOST` | `falkordb` | graph | B |
| `FALKORDB_PORT` | `6379` | graph | B |
| `ARGUS_TENANTS` | `acme,globex` | core | B |
| `TALOS_URL` | `http://talos:8000` | ingestor | A |
| `TALOS_URL_<TENANT>` | unset | ingestor, if one Talos per tenant | A |
| `INGEST_POLL_SECONDS` | `3` | ingestor | A |
| `INGEST_PAGE_LIMIT` | `50` | ingestor | A |
| `ARGUS_INVENTORY_DIR` | `data/inventory` | ingestor (routes reports to tenants by host) | A |
| `AGENT_POLL_SECONDS` | `2` | agents | A |
| `AGENT_CLAIM_TTL_SECONDS` | `120` | agents | A |
| `CORRELATION_WINDOW_HOURS` | `24` | triage | A |
| `MAX_PATH_HOPS` | `6` | investigator | A |
| `REPEAT_TARGET_THRESHOLD` | `2` | triage | A |
| `DEEP_DIVE_ENABLED` | `true` (runs only when `LLM_ENABLED` is also true) | investigator | A |
| `DEEP_DIVE_MAX_CALLS` | `4` | investigator | A |
| `MCP_SERVER_COMMAND` | `python -m argus_soc.graph.mcp_server` | investigator | B |
| `AGENT_WORKER_ID` | host name of the container | agents | A |
| `PLAYBOOK_MIN_FEEDBACK` | `1` (demo) | learning | A |
| `LLM_ENABLED` | `false` | agents | A |
| `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY` | unset (provider read from the key; model required for OpenAI, §6.8) | agents | A |
| `LLM_TIMEOUT_SECONDS` | `20` | agents | A |
| `API_PORT` | `8080` | api | C |
| `API_CORS_ORIGINS` | `http://localhost:5173` | api | C |
| `ARGUS_DEMO_USERS` | required; JSON `[{"username","display_name","password","tenants":[...]}]` | api (login) | C (field in shared `settings.py`) — **GAP-1, proposed** |
| `ARGUS_SESSION_SECRET` | required, ≥ 32 chars | api (login) | C — **GAP-1, proposed** |
| `ARGUS_SESSION_HOURS` | `12` | api (login) | C — **GAP-1, proposed** |
| `LOG_LEVEL` | `INFO` | all | everyone |

`settings.py` uses `pydantic-settings`; a bad value raises at startup (rule C9).

## 3. Shared core

- **`settings.py`** — `Settings` model with the variables above; `get_settings()` cached.
- **`tenant_registry.py`** — `TENANTS: dict[str, str]` mapping tenant id → graph name
  (`"acme" → "tenant_acme"`). `graph_name(tenant)` raises `UnknownTenant` for anything else, so
  a typo can never create a new graph.
- **`logging_setup.py`** — JSON lines to stdout with fields `ts`, `level`, `service`, `tenant`,
  `case_id`, `agent`, `msg`.

---

## 4. Graph layer — Workstream B

### 4.1 Schema (`graph_schema.py`)

Labels, relationship types and status values live here as constants. Nobody types a label as a
string anywhere else.

| Label | Key | Properties |
|---|---|---|
| `Host` | `hostname` | `ip`, `os`, `zone` (`dmz`/`app`/`data`/`corp`), `criticality` (1–5), `isolated` (bool, simulated); semantic facts: `targeted_case_ids` (list), `last_targeted_at` |
| `User` | `username` | `role`, `department`, `privileged` (bool), `disabled` (bool, simulated); semantic facts: `suspected_compromised` (bool), `suspected_at`, `suspect_case_id` |
| `Service` | `name` | `port`, `exposed` (bool) |
| `Endpoint` | `path` + `app` | `method` |
| `AssetTag` | `name` | — (`crown-jewel`, `pci`, …) |
| `Alert` | `incident_id` | `category`, `domain`, `severity`, `confidence`, `succeeded`, `summary`, `evidence` (JSON string), `recommended_actions` (list), `talos_created_at`, `ingested_at`, `status` (`new`/`cased`) |
| `IOC` | `type` + `value` | `first_seen`, `last_seen`, `verdict` (`unknown`/`malicious`/`benign`), `owner` (semantic fact), `seen_case_ids` (list, semantic fact) |
| `Technique` | `mitre_id` | `name`, `tactic` |
| `Case` | `id` (int) | `status`, `priority`, `opened_at`, `updated_at`, `claimed_by`, `claimed_at`, `findings` (JSON string), `verdict`, `closed_reason` |
| `Decision` | `id` (uuid) | `actions` (list), `needs_approval`, `rule_id`, `reason`, `explanation`, `evidence` (JSON: query names + results), `outcome` (`pending`/`approved`/`rejected`/`auto`), `created_at`; `previous_priority` (case priority before this decision — **GAP-5, proposed**) |
| `Feedback` | `id` (uuid) | `verdict` (`approve`/`reject`/`benign`), `note`, `analyst`, `created_at` |
| `Playbook` | `name` + `version` | `condition` (JSON), `action` (`auto_close`), `active` (bool), `created_at` |
| `AgentRun` | `id` (uuid) | `agent`, `worker`, `case_id`, `started_at`, `finished_at`, `outcome`, `summary`, `tool_calls` (JSON: deep-dive calls, Investigator only) |

Relationships: as in `ARCHITECTURE.md` §4. `LOGGED_INTO` carries `last_seen`; `CONNECTS_TO`
carries `port`. `graph_schema.py` also defines `(Case)-[:APPLIED]->(Playbook)` and
`(Decision)-[:APPLIED]->(Playbook)` to cite the playbook used (GAP-7, docs to catch up).

No label holds UI analyst accounts. For the hackathon, analysts are hard-coded demo users in
`.env` (HLD D13); the graph's `User` label is the simulated company's accounts. The only analyst
trace in the graph is `Feedback.analyst`.

Case status constants: `NEW`, `TRIAGED`, `INVESTIGATED`, `AWAITING_APPROVAL`, `CLOSED`,
`AUTO_CLOSED`.

### 4.2 Connection (`falkor_client.py`)

```python
def graph_for(tenant: str) -> AsyncGraph      # db.select_graph(tenant_registry.graph_name(tenant))
async def run(tenant: str, query: str, params: dict) -> list[dict]   # always parameterised
```

One client per process; queries always pass parameters, never string-built values (security).

### 4.3 Indexes (`index_setup.py`)

Run once per tenant at seed time:

```cypher
CREATE INDEX FOR (n:Alert)    ON (n.incident_id)
CREATE INDEX FOR (n:Host)     ON (n.hostname)
CREATE INDEX FOR (n:User)     ON (n.username)
CREATE INDEX FOR (n:IOC)      ON (n.value)
CREATE INDEX FOR (n:Case)     ON (n.id)
CREATE INDEX FOR (n:Case)     ON (n.status)
CREATE INDEX FOR (n:Playbook) ON (n.active)
```

### 4.4 Read functions (`read_queries.py`, `algorithm_queries.py`)

Every function is `async`, takes `tenant` first, returns plain Python types.

| Function | Query | Returns |
|---|---|---|
| `blast_radius(tenant, ioc)` | Q1: hosts and accounts linked to alerts involving the IOC, plus hosts those accounts log into | `[{host, criticality, accounts, reached_hosts, alerts}]` |
| `paths_to_crown_jewels(tenant, host, max_hops=6)` | Q2: shortest path over `CONNECTS_TO`/`LOGGED_INTO` to hosts tagged `crown-jewel` | `[[node names...]]`, shortest first, max 3 |
| `rank_hosts(tenant, case_id)` | Q3: centrality on the case's host subgraph × `criticality` | `[(hostname, score)]`, highest first |
| `recall(tenant, ioc=None, host=None, user=None)` | Q4: closed cases containing alerts with that IOC/host/user, with verdict and feedback | `[{case_id, verdict, closed_at, note}]` |
| `linked_alerts(tenant, incident_id, window_hours)` | Q5: alerts sharing an IOC or a user within the window (a shared host alone does not link; alerts in closed cases are skipped); connected components when more than one hop | `[incident_id]` |
| `explain_decision(tenant, decision_id)` | Q6: decision, case, alerts, acted-on nodes, playbook and source case | `dict` |
| `entity_facts(tenant, hosts, users, iocs)` | Semantic facts on those nodes (§4.4.1) | `{hosts: {name: facts}, users: {...}, iocs: {...}}` |
| `matching_playbook(tenant, alert)` | Active playbooks whose `condition` matches the alert's category and IOC | `dict | None` |
| `list_new_alerts(tenant, limit)` | Alerts with `status = 'new'`, oldest first | `[alert dict]` |
| `known_incident_ids(tenant, ids)` | Which of these incident ids already exist | `set[str]` |
| `list_cases(tenant, status=None, limit=100)` | Cases newest first | `[case summary]` |
| `get_case(tenant, case_id)` | Case with alerts, findings, decisions, feedback, agent runs | `dict`; feedback items as `{id, verdict, note, analyst, created_at}` (GAP-4) and agent runs with `worker`, `tool_calls` (GAP-2/3) — **proposed** |
| `list_playbooks(tenant)` | Playbooks with version and source case | `[dict]` |
| `list_activity(tenant, since)` | AgentRun entries after a timestamp | `[dict]` incl. `worker` and parsed `tool_calls` (GAP-2/3, **proposed**) |

#### 4.4.1 Semantic facts

Facts are written by agents (`record_semantic_facts`) and by analyst feedback (`set_ioc_fact`), and
read back with `entity_facts`. Counts are stored as lists of case ids, never as counters, so
writing the same case twice changes nothing (rule A3): times targeted = `size(targeted_case_ids)`.

Q2 draft (verify `shortestPath` placement against FalkorDB docs on day 1):

```cypher
MATCH (src:Host {hostname: $host}), (dst:Host)-[:TAGGED]->(:AssetTag {name: 'crown-jewel'})
WITH src, dst
MATCH p = shortestPath((src)-[:CONNECTS_TO|LOGGED_INTO*1..6]-(dst))
RETURN [n IN nodes(p) | coalesce(n.hostname, n.username)] AS path, length(p) AS hops
ORDER BY hops LIMIT 3
```

Q3 approach: collect the case's hosts plus their one-hop `CONNECTS_TO` neighbours, run the
FalkorDB PageRank or betweenness procedure on that subgraph (check the exact procedure name in
docs.falkordb.com/algorithms), multiply by `criticality`. Fallback if the procedure doesn't fit:
degree within the subgraph × criticality, computed in Cypher.

### 4.5 Write functions (`write_queries.py`)

All single `MERGE`-based queries (rule A3).

| Function | Effect |
|---|---|
| `upsert_alert_from_report(tenant, alert: AlertInput)` | MERGE Alert by `incident_id`; MERGE Host, User, Endpoint, IOC, Technique; MERGE relationships. Sets `status='new'` only on create |
| `open_or_join_case(tenant, incident_ids, priority)` | If any alert is in an open case, add the rest to it; else create Case with next id (`MAX(id)+1` in the same query). Sets alerts `status='cased'` |
| `close_case_auto(tenant, incident_ids, playbook_ref, reason)` | Create case directly as `auto_closed` with the playbook cited |
| `claim_case(tenant, status, agent, ttl_seconds)` | Atomically claim the oldest case in `status` whose claim is empty or expired; returns `case_id` or `None` (§6.1) |
| `set_case_status(tenant, case_id, status, priority=None)` | Move status, clear the claim |
| `record_findings(tenant, case_id, findings: dict)` | Store findings JSON on the case |
| `record_decision(tenant, case_id, decision: DecisionInput)` | CREATE Decision, link HAS_DECISION, MERGE ACTED_ON to targets, set simulated flags (`isolated`, `disabled`); stores `decision.previous_priority` (GAP-5, **proposed**) |
| `record_feedback(tenant, case_id, verdict, note, analyst)` | CREATE Feedback ON Case; set Decision outcome; set IOC `verdict` |
| `create_playbook_version(tenant, feedback_id, condition, action)` | Deactivate older versions with the same name; CREATE new version; LEARNED_FROM feedback |
| `set_ioc_fact(tenant, ioc, key, value)` | Semantic fact on an IOC (e.g. `owner`) |
| `record_semantic_facts(tenant, case_id, facts: SemanticFactsInput)` | One query: add `case_id` to `targeted_case_ids` of each host and `seen_case_ids` of each IOC (only if absent), set `last_targeted_at`; for `facts.suspected_users` set `suspected_compromised`, `suspected_at`, `suspect_case_id` |
| `record_agent_run(tenant, agent, case_id, summary, handed_to=None, worker=None, tool_calls=None)` | CREATE AgentRun; WROTE case; HANDED_OFF_TO previous run when `handed_to` is set; `worker` and `tool_calls` stored as given |

FalkorDB runs write queries on a graph one at a time, so each single-query write (including
`claim_case`) is atomic.

### 4.6 Stubs (`graph_stubs.py`)

Same signatures, fixed return values taken from scenario 1. Selected with
`ARGUS_GRAPH_BACKEND=stub`. Shipped on Oct 15 so A and C never wait.

### 4.7 MCP server (`mcp_server.py`)

Exposes the **read** functions as MCP tools for the Investigator's deep dive (§6.9):
`blast_radius`, `paths_to_crown_jewels`, `rank_hosts`, `recall`, `linked_alerts`, `entity_facts`.
Built with the official `mcp` Python SDK over stdio: the agents process starts it as a subprocess
with `MCP_SERVER_COMMAND`, so there is no extra service or port.

- Every tool takes `tenant` as its first argument and passes it through unchanged.
- Each tool has a one-line description and typed arguments; that is what the LLM chooses from.
- No write function is ever exposed.
- Returns are the same plain types as the Python functions, cut to 4 000 characters.

### 4.8 Seeding (`scripts/seed_tenants.py`, `data/inventory/*.yaml`)

```yaml
tenant: acme
hosts:
  - {hostname: bastion-01, ip: 10.0.1.10, zone: dmz,  criticality: 3}
  - {hostname: app-02,     ip: 10.0.2.20, zone: app,  criticality: 4}
  - {hostname: db-prod-01, ip: 10.0.3.30, zone: data, criticality: 5, tags: [crown-jewel]}
  - {hostname: web-01,     ip: 10.0.1.40, zone: dmz,  criticality: 2}
users:
  - {username: svc_deploy, role: service, privileged: true, logs_into: [bastion-01, app-02]}
links:
  - {from: bastion-01, to: app-02, port: 22}
  - {from: app-02, to: db-prod-01, port: 5432}
iocs:
  - {type: ip, value: 10.0.5.20, owner: null}
```

Plus generated filler hosts and users (seeded random, fixed seed) to reach 50–200 hosts.
Required demo facts: the bastion-01 → app-02 → db-prod-01 path exists; web-01 has no path to a
crown jewel.

---

## 5. Ingestor — Workstream A

### 5.1 `talos_client.py`

```python
class TalosClient:
    async def list_reports(self, limit: int) -> list[dict]      # GET /reports, newest first
```

`httpx.AsyncClient`, 10 s timeout, retries 1, 2, 4, 8 s on connection errors and 5xx, then
raises `TalosError` (the loop logs it and polls again); a 4xx fails at once. As built:
`GET /reports` already returns full IncidentReports (every verdict and its evidence), so
`GET /reports/{incident_id}` is not needed. The Compose healthcheck covers `/healthz`.

### 5.2 `report_mapper.py`

`map_report(report: dict) -> AlertInput` (a Pydantic model defined in `graph_schema.py`):

| AlertInput field | From the Talos IncidentReport |
|---|---|
| `incident_id`, `domain`, `category`, `severity`, `confidence`, `summary` | same-named fields |
| `talos_created_at` | `created_at` |
| `succeeded` | `aggregate_scope.succeeded` |
| `hosts` | `aggregate_scope.affected_hosts` |
| `users` | `aggregate_scope.affected_accounts` |
| `endpoints` | `aggregate_scope.affected_endpoints` |
| `techniques` | `mitre_techniques[]` → `{mitre_id, name, tactic}` |
| `evidence` | `verdicts[].evidence[]`, trimmed to 20 items and 500 characters each |
| `recommended_actions` | `recommended_actions` |
| `source_ips` | extracted, see 5.3 |

### 5.3 Source IP extraction

Talos's report counts source addresses but has no structured field naming them (they appear in
evidence lines and in action text). So:

1. Collect strings from `verdicts[].evidence[].detail` and `recommended_actions`.
2. Find IPv4/IPv6 candidates with a regex; keep those that `ipaddress.ip_address()` accepts.
3. Drop addresses that belong to the tenant's own hosts (from the inventory), except known
   internal sources such as the scanner.
4. Order by number of occurrences; keep at most 5.

This is a day-1 check: run scenario 1 through Talos and confirm the attacker IP is recovered.

### 5.4 `tenant_resolver.py`

**Decided (Oct 16): one shared Talos, routed by host (Option B).** Option A still works with
no code change: set `TALOS_URL_<TENANT>` and that Talos's reports all go to that tenant.

- **Option A — one Talos per tenant:** the tenant is the one whose `TALOS_URL_<TENANT>` was polled.
- **Option B — one Talos:** a report goes to the tenant whose inventory
  (`ARGUS_INVENTORY_DIR`, expanded with its filler hosts) contains any of its `hosts`; no
  match, or hosts of two tenants → logged once and dropped (never guessed). Host names must
  be unique across tenants (filler hosts are prefixed `acme-…`, `globex-…`).

### 5.5 `ingest_loop.py`

```
for ever:
    for talos_url, fixed_tenant in sources():        # fixed_tenant None = route by host
        reports = talos.list_reports(limit=INGEST_PAGE_LIMIT)
        group reports by (fixed_tenant or tenant_resolver.resolve(report)); drop None, log once
        for tenant, group:
            new = group - graph.known_incident_ids(tenant, ids)
            for report in new (oldest first):
                try: graph.upsert_alert_from_report(tenant, report_mapper.map_report(report))
                except error: log, continue          # retried next poll
    sleep(INGEST_POLL_SECONDS)
```

No in-memory "seen" set: the graph is the record, so a restarted ingestor never duplicates or
misses a report still in Talos's recent list.

---

## 6. Agents and learning — Workstream A

### 6.1 `agent_runner.py` and case claiming

One process runs a worker loop per agent role and tenant:

```
for ever, for each tenant:
    triage.step(tenant)                      # works on alerts, not cases
    if case_id := graph.claim_case(tenant, TRIAGED, "investigator", ttl): investigator.run(tenant, case_id)
    if case_id := graph.claim_case(tenant, INVESTIGATED, "responder", ttl): responder.run(tenant, case_id)
    sleep(AGENT_POLL_SECONDS) if nothing was done
```

`claim_case` (B) in one query:

```cypher
MATCH (c:Case {status: $status})
WHERE c.claimed_by IS NULL OR c.claimed_at < $expired_before
WITH c ORDER BY c.updated_at ASC LIMIT 1
SET c.claimed_by = $agent, c.claimed_at = $now
RETURN c.id
```

A crashed worker's claim expires after `AGENT_CLAIM_TTL_SECONDS`; another worker picks the case
up and redoes the step. Every write in a step is a MERGE, so redoing it is safe. Several runner
containers can run at once (`docker compose up --scale agents=2`). Each worker passes
`<role>@<AGENT_WORKER_ID>` as `agent` to `claim_case` and `worker=AGENT_WORKER_ID` to
`record_agent_run`, so the activity feed shows which worker did each step (needed for the
concurrency proof, §11).

### 6.2 `triage_agent.py`

As built (Oct 16): two phases, so two workers never triage one case twice (the double-decision
fix from the Oct 16 review; proven by `tests/e2e/test_concurrency_burst.py`).

```
step(tenant):
    # 1. Route: one atomic write per alert.
    for alert in graph.list_new_alerts(tenant, limit=20):
        if pb := graph.matching_playbook(tenant, alert):
            case = graph.close_case_auto(tenant, [alert.id], pb, reason=f"Playbook {pb.name} v{pb.version}, learned from Case {pb.source_case}")
            graph.record_agent_run(tenant, "triage", case, summary="auto-closed by playbook")
            continue
        linked = graph.linked_alerts(tenant, alert.id, CORRELATION_WINDOW_HOURS)   # shared IOC or user
        case = graph.open_or_join_case(tenant, [alert.id] + linked, alert.severity)
        if case is past triage: record_agent_run("joined case; not re-triaged")   # never moved back
    # 2. Triage each new case this worker can claim (like the other agents).
    while case_id := graph.claim_case(tenant, NEW, "triage@<worker>", AGENT_CLAIM_TTL_SECONDS):
        case = graph.get_case(tenant, case_id)                    # all its hosts, users, IOCs
        history = graph.recall(tenant, ioc=case.iocs, host=case.hosts, user=case.users)
        facts   = graph.entity_facts(tenant, case.hosts, case.users, case.iocs)
        reasons = memory_reasons(history, facts)   # malicious past case or IOC, suspected user,
                                                   # host targeted >= REPEAT_TARGET_THRESHOLD times
        severity = highest(alert.severity for alert in case.alerts)
        priority = raise_one(severity) if reasons else severity   # at most one step
        graph.record_findings(tenant, case_id, {"recall": history, "facts": facts,
            "linked": other alert ids, "severity": severity, "memory_reasons": reasons,
            "known_malicious_iocs": IOCs whose fact verdict is malicious})   # read by §6.4
        handoff: set_case_status(TRIAGED, priority) + record_agent_run(handed_to="investigator")
```

Priority order: `info < low < medium < high < critical`. The IOC-verdict check is an addition:
nothing writes `Case.verdict = malicious`, but an approved decision marks the IOC malicious.
The Investigator and Responder also raise a case to its most severe alert, so a late success
alert that joins an investigated case still counts.

### 6.3 `investigator_agent.py`

```
run(tenant, case_id):
    case = graph.get_case(tenant, case_id)
    radius = [graph.blast_radius(tenant, ioc) for ioc in case.iocs]
    start_hosts = case.hosts ∪ reached hosts from radius
    paths = {h: graph.paths_to_crown_jewels(tenant, h, MAX_PATH_HOPS) for h in start_hosts}
    findings = {
        "succeeded": any(alert.succeeded),
        "path_to_crown_jewel": any(paths.values()),
        "shortest_path": min(paths, key=len) or None,
        "blast_radius": radius,
        "investigated_alerts": sorted alert ids of the case,   # read by §6.5
    }
    deep = deep_dive(tenant, case, findings) if DEEP_DIVE_ENABLED and LLM_ENABLED else []   # §6.9
    findings["deep_dive"] = deep                     # evidence only; decide() never reads it
    graph.record_findings(tenant, case_id, findings)
    graph.record_semantic_facts(tenant, case_id, SemanticFactsInput(
        hosts=case.hosts, iocs=case.iocs,
        suspected_users=case.users if findings["succeeded"] else []))
    graph.set_case_status(tenant, case_id, INVESTIGATED)
    graph.record_agent_run(tenant, "investigator", case_id, summary=..., handed_to="responder",
                           worker=AGENT_WORKER_ID, tool_calls=deep)
```

The fixed Q1 + Q2 run always comes first, so the decision never depends on the deep dive. As
built: paths are taken from the case's own hosts first and from hosts reached through its
accounts only when those have none (keeps `bastion-01 → app-02 → db-prod-01` as the story);
only the accounts **in alerts that succeeded** are marked suspected compromised (scenario 1:
`svc_deploy`, not the 18 customer e-mails the credential stuffing tried).

### 6.4 `decision_table.py`

Rules are data, evaluated top to bottom; first match wins.

```python
RULES = [
  Rule(id="R1", when={"succeeded": True,  "path": True},
       actions=["isolate_top_host", "disable_accounts", "block_ips"], needs_approval=True,  priority=None),
  Rule(id="R2", when={"succeeded": True,  "path": False},
       actions=["disable_accounts", "block_ips", "open_hunt_ticket"], needs_approval=True,  priority=None),
  Rule(id="R3", when={"succeeded": False, "path": True},
       actions=["block_ips", "watch_path_hosts"],                    needs_approval=False, priority=None),
  Rule(id="R4", when={"succeeded": False, "path": False},
       actions=["block_or_rate_limit_ips", "open_ticket"],           needs_approval=False, priority="lower_one"),
]
def decide(findings: dict) -> Rule
```

R3 needs approval when `findings.known_malicious_iocs` is not empty: an attacker already marked
malicious by an approved decision, on a crown-jewel path, goes to the analyst instead of closing
on its own (live test Oct 17, case 20). The rule id stays R3; the reason says why.

### 6.5 `responder_agent.py`

```
run(tenant, case_id):
    case = graph.get_case(tenant, case_id)
    if case.alert ids != case.findings.investigated_alerts: send back (below); return
    rule = decision_table.decide(case.findings)
    ranking = graph.rank_hosts(tenant, case_id)
    targets = resolve(rule.actions, ranking, case)     # e.g. isolate_top_host → ranking[0]
    explanation = llm.explain(case, rule, ranking) if LLM_ENABLED else template(case, rule, ranking)
    if graph.get_case(tenant, case_id) alert ids changed: send back; return   # the LLM takes seconds
    graph.record_decision(tenant, case_id, DecisionInput(rule_id=rule.id, actions=targets,
        needs_approval=rule.needs_approval, reason=..., explanation=explanation,
        previous_priority=case.priority,          # GAP-5 (done): lets the UI show high → medium
        evidence={"findings": case.findings, "ranking": ranking}))
    new_priority = lower_one(case.priority) if rule.priority == "lower_one" else None
    graph.set_case_status(tenant, case_id, AWAITING_APPROVAL if rule.needs_approval else CLOSED, new_priority)
    graph.record_agent_run(tenant, "responder", case_id, summary=...)
```

Talos's `recommended_actions` are shown next to ours in the UI but never decide.

**Send back (live test Oct 17, case 8).** Talos can report "8 attempts, not succeeded" and,
seconds later, "9 attempts, succeeded" for the same attack. When an alert joined the case after
the Investigator ran, the findings are stale, so the Responder hands the case back to the
Investigator (`set_case_status(TRIAGED)` + agent run handed to `investigator`) instead of
deciding; the next pass decides from all alerts (R1, not R3). A case already decided keeps its
one decision (`record_decision` is one per case); an alert joining in the milliseconds between
the Responder's last read and its write is still missed.

Targets (as built): `isolate_top_host` → the first host of the ranking; `disable_accounts` → the
accounts in alerts that succeeded; `block_ips` / `block_or_rate_limit_ips` → the case's IOCs;
`watch_path_hosts` → named in the explanation only, never a target (`record_decision` isolates
every target host once applied). `previous_priority` (GAP-5, done) is the case's priority going
into the decision; the priority set after it is that, or one step lower for R4.

### 6.6 `handoff_service.py`

Wraps `set_case_status` + `record_agent_run(handed_to=...)` so every handoff is recorded the same
way and the UI activity feed has one source.

### 6.7 `learning_service.py`

```python
async def on_feedback(tenant: str, case_id: int, feedback_id: str) -> str | None
```

- Only `benign` verdicts create playbooks.
- Pattern = (alert `category`, IOC values of the case). Count benign feedback with that pattern;
  if `>= PLAYBOOK_MIN_FEEDBACK`, create the next playbook version with
  `condition = {"category": ..., "ioc_in": [...]}` and `action = "auto_close"`, and set the IOC's
  `owner`/`verdict` facts from the note.
- `approve`/`reject` only update the Decision outcome and IOC verdict (malicious on approve).
- Called by the API right after `record_feedback`. The call is part of the contracts.

### 6.8 `llm_client.py` and prompts

```python
async def complete(prompt_name: str, variables: dict, schema: type[BaseModel]) -> BaseModel | None
```

- **Providers (as built): Anthropic or OpenAI**, one adapter function each. `LLM_PROVIDER` if
  set, else from `LLM_API_KEY` (`sk-ant-…` = Anthropic, other keys = OpenAI). `LLM_MODEL`:
  default `claude-opus-5-5` on Anthropic (low effort, server-side refusal fallback on), required
  on OpenAI (e.g. `gpt-5.4-mini`).
- Returns `None` when off or misconfigured, on timeout, API error, refusal or JSON that does not
  validate against `schema`; callers then use the template.
- Prompts live in `agents/prompts/<agent>_<purpose>_v<N>.md`: `responder_explain_v1.md`,
  `investigator_deepdive_v1.md`; filled with `string.Template`, so a `$` in data is inert.
- Untrusted content (evidence, log lines, summaries, user and host names) goes inside an
  `<untrusted_data>` block, each item cut to 500 characters, with a system instruction that it is
  data only.
- The LLM never chooses actions, Cypher, or targets. It writes explanations and short summaries,
  and in the deep dive (§6.9) it picks which read-only graph tool to call next.

### 6.9 `graph_tool_client.py`: the deep dive (MCP tool selection)

The Investigator's optional second step, where the LLM chooses which graph tools to call. This is
the Track 01 "MCP tool selection" proof.

```
deep_dive(tenant, case, findings):
    tools = mcp.list_tools()                               # names, descriptions, argument schemas
    calls = []
    for i in range(DEEP_DIVE_MAX_CALLS):
        choice = llm.complete("investigator_deepdive_v1",
                              {tools (tenant hidden), case summary, findings,
                               calls so far as UNTRUSTED DATA}, schema=ToolChoice)
        if choice is None or choice.done: break
        if choice.tool not in tools: break                 # unknown tool → stop, never guess
        result = mcp.call_tool(choice.tool, {**choice.args, "tenant": tenant})
        calls.append({"tool": choice.tool, "args": choice.args,
                      "result": truncate(result), "why": choice.reason})
    return calls
```

- **Tenant is set by code.** `tenant` is removed from the tool schemas shown to the LLM and added
  back by the client; a `tenant` key in `choice.args` is overwritten.
- **Read-only.** The MCP server exposes only read functions (§4.7).
- **Bounded.** At most `DEEP_DIVE_MAX_CALLS` calls; arguments validated against the tool schema;
  any error ends the dive and keeps what was collected.
- **Evidence, not decision.** Calls and results are stored in `findings.deep_dive` and on the
  AgentRun (`tool_calls`). The UI shows them and the Responder's explanation may cite them;
  `decision_table.decide` never reads them (rule A8).
- `ToolChoice` = `{done: bool, tool: str | None, args: dict, reason: str}`.
- LLM off, MCP failure or bad choice → the step returns what it has (possibly `[]`) and the case
  moves on unchanged.

---

## 7. Backend API — Workstream C

FastAPI app in `api_server.py`, routers per file, all under `/api/{tenant}`. Unknown tenant →
404. Responses are the Pydantic models in `api_models.py` (the UI contract).

| Method + path | Request | Response model |
|---|---|---|
| `GET /api/health` | — | `{status, falkordb: bool}` |
| `GET /api/tenants` | — | `list[str]` |
| `GET /api/{tenant}/cases?status=&limit=` | query params | `list[CaseSummary]` |
| `GET /api/{tenant}/cases/{case_id}` | — | `CaseDetail` |
| `POST /api/{tenant}/cases/{case_id}/feedback` | `FeedbackIn` | `FeedbackOut` |
| `GET /api/{tenant}/playbooks` | — | `list[PlaybookOut]` |
| `GET /api/{tenant}/activity?since=` | ISO timestamp | `list[ActivityItem]` |

```python
class CaseSummary(BaseModel):
    id: int; status: str; priority: str; category: str
    alert_count: int; opened_at: datetime; updated_at: datetime
    needs_approval: bool; auto_closed_by: str | None

class PathNode(BaseModel):  name: str; label: str            # e.g. "bastion-01", "Host"
class AlertOut(BaseModel):
    incident_id: str; category: str; severity: str; confidence: float
    succeeded: bool | None; summary: str; evidence: list[str]; talos_actions: list[str]
class DecisionOut(BaseModel):
    id: str; rule_id: str; actions: list[str]; needs_approval: bool
    reason: str; explanation: str; outcome: str; path: list[PathNode]; ranking: list[tuple[str, float]]
class CaseDetail(CaseSummary):
    alerts: list[AlertOut]; findings: dict; decision: DecisionOut | None
    feedback: list[dict]; agent_runs: list["ActivityItem"]
class FeedbackIn(BaseModel):
    verdict: Literal["approve", "reject", "benign"]; note: str = Field(max_length=500); analyst: str
class FeedbackOut(BaseModel):  feedback_id: str; playbook_created: str | None
class PlaybookOut(BaseModel):
    name: str; version: int; active: bool; condition: dict; source_case: int | None; created_at: datetime
class ActivityItem(BaseModel):
    at: datetime; agent: str; case_id: int | None; summary: str; handed_to: str | None
```

Feedback endpoint flow: validate → `record_feedback` → `set_case_status(CLOSED)` if awaiting
approval → `learning_service.on_feedback` → return.

Errors: 404 unknown tenant or case; 409 feedback on a case not awaiting approval (except
`benign`, allowed on any closed case); 422 validation; 503 FalkorDB unreachable.

`mock_data.py` returns these same models with scenario-1 values when `ARGUS_API_MOCK=true`.

### 7.1 Login for the hackathon (GAP-1, proposed — see `docs/CONTRACT_GAPS.md`)

Hard-coded demo users from `ARGUS_DEMO_USERS` (`acme.analyst` → acme, `globex.analyst` → globex,
`demo.admin` → both). No user table; real login is post-hackathon (HLD D13).

| Method + path | Request | Response | Errors |
|---|---|---|---|
| `POST /api/auth/login` | `LoginIn {username, password}` | `SessionOut {token, username, display_name, tenants, expires_at}` | 401 (same message for unknown user and wrong password) |
| `GET /api/auth/me` | bearer token | `MeOut {username, display_name, tenants}` | 401 |
| `POST /api/auth/logout` | bearer token | 204 | — |

- Token = `base64(payload).hmac_sha256(payload, ARGUS_SESSION_SECRET)`, payload `{username, exp}`;
  checked with `hmac.compare_digest`. Files: `api/auth_routes.py`, `api/session_tokens.py`.
- Guard dependency on every `/api/{tenant}/…` route: 401 without a valid token, 403 if the tenant
  isn't the user's. `/api/health` and `/api/auth/login` stay open. `GET /api/tenants` returns
  only the caller's tenants.
- Feedback: `analyst` comes from the token; the browser's value is ignored.

### 7.2 Proposed model additions (GAP-2…6, not in the contract until acked)

```python
class ToolCallOut(BaseModel):     tool: str; args: dict; result: str; why: str
class ActivityItem(BaseModel):    # + worker: str | None = None; tool_calls: list[ToolCallOut] | None = None
class FeedbackItemOut(BaseModel): id: str; verdict: Literal["approve","reject","benign"]; note: str; analyst: str; created_at: datetime
class DecisionOut(BaseModel):     # + previous_priority: str | None = None
class FindingsOut(BaseModel, extra="allow"):   # every key optional
    recall: list[dict] | None; facts: dict | None; linked: list[str] | None
    succeeded: bool | None; path_to_crown_jewel: bool | None; shortest_path: list[str] | None
    blast_radius: list[dict] | None; deep_dive: list[ToolCallOut] | None
# CaseDetail: findings: FindingsOut; feedback: list[FeedbackItemOut]
```

## 8. UI — Workstream C

| Page | Shows | Data |
|---|---|---|
| Case queue | Cases per tenant with priority, status, category, "needs approval" badge, auto-closed marker | `GET /cases`, refresh every 3 s |
| Case detail | Alerts with Talos evidence; findings; decision with rule and explanation; **path view** (nodes and arrows from `DecisionOut.path`); ranking; approve / reject / benign form | `GET /cases/{id}`, `POST /feedback` |
| Playbooks | Versions, active flag, condition, link to source case | `GET /playbooks` |
| Activity | Live feed of agent steps and handoffs | `GET /activity?since=`, every 2 s |
| Tenant switcher | Acme / Globex in the header | `GET /tenants` |

Notes: path view can be plain SVG or a small graph library; Talos's own recommended actions are
shown, labelled "Talos suggested", next to the agent's decision.

**Full page-by-page spec: `docs/UI_PAGES.md`** (5 pages: Sign in, Case queue, Case detail,
Playbooks, Agent activity; plus the app shell and a not-found page). The Sign in page and the
token handling depend on GAP-1; the worker, tool-call and "high → medium" displays depend on
GAP-2, GAP-3 and GAP-5 and stay hidden until those fields exist.

---

## 9. Errors and retries

| Where | Failure | Behaviour | Owner |
|---|---|---|---|
| Startup, any service | Bad config, unknown tenant | Exit with a clear message | everyone |
| Ingestor | Talos unreachable / 5xx | Backoff 1→30 s, keep looping | A |
| Ingestor | One report fails to map or write | Log with incident id, skip, continue | A |
| Agent step | Graph call fails | Leave the claim; it expires and the step is retried | A |
| Agent step | LLM fails or times out | Use the template explanation, continue | A |
| Deep dive | MCP server won't start, tool error, bad tool choice | End the dive, keep calls so far, continue | A |
| Graph | Query error | Raise `GraphError` with query name and tenant; never swallow | B |
| API | FalkorDB down | 503 with message; UI shows a banner and keeps polling | C |

## 10. Logging

JSON lines: `ts`, `level`, `service` (`ingestor`/`agents`/`api`), `tenant`, `case_id`,
`agent`, `incident_id`, `msg`. No log line contains API keys or full raw payloads (truncate to
200 characters).

## 11. Testing

| Layer | Tests | Runs against | Owner |
|---|---|---|---|
| Graph | One test per read and write function; idempotency (write twice, count once); tenant isolation | FalkorDB test container seeded with a small inventory | B |
| Ingestor | Mapping from real Talos report JSON fixtures; IP extraction; skip on bad report | Fixtures, stub graph | A |
| Agents | Triage paths (playbook / join / new / memory-hit raise), decision table rows R1–R4, claim expiry | `graph_stubs` | A |
| Deep dive | Stops at `DEEP_DIVE_MAX_CALLS`; unknown tool stops; `tenant` from the LLM is ignored; LLM off → `[]` | Fake LLM + stub MCP tools | A |
| MCP server | Lists only read tools; each tool returns the same as the Python function | FalkorDB test container | B |
| Learning | Benign → playbook version; approve → IOC malicious | `graph_stubs` | A |
| API | Each endpoint, status codes, mock mode | FastAPI test client + stub graph | C |
| End to end | Scenarios 1–4 produce the expected case statuses and decisions | Full Compose stack | A (with B and C) |
| Concurrency (`tests/e2e/test_concurrency_burst.py`) | Burst of ~30 alerts over both tenants with `--scale agents=2`: each case has exactly one Decision, no alert in two cases, AgentRuns from both workers, no node shared across tenants | Full Compose stack + `scripts/replay_scenario.py --burst` | A |

## 12. Deployment detail

| Service | Command | Env | Volumes | Healthcheck |
|---|---|---|---|---|
| `falkordb` | image default | — | `falkordb-data:/data` | `redis-cli ping` |
| `talos-postgres` | image default | `POSTGRES_*` | `talos-pg-data:/var/lib/postgresql/data` | `pg_isready` |
| `talos` | apply Talos migrations, then `talos serve --host 0.0.0.0 --port 8000` | `TALOS_DB_DSN` | — | `GET /healthz` |
| `ingestor` | `argus-ingest` | `TALOS_URL`, `FALKORDB_*` | — | process alive |
| `agents` | `argus-agents` | `FALKORDB_*`, `LLM_*` | — | process alive |
| `api` | `argus-api` | `FALKORDB_*`, `API_*` | — | `GET /api/health` |
| `ui` | static server | — | — | `GET /` |
| `nginx` | nginx | — | certs | `GET /` |

`talos serve` binds to 0.0.0.0 inside the container so the ingestor can reach it; the port is not
published outside the Compose network. The Talos Dockerfile (A) clones the public repo at a pinned
commit and runs `pip install .`, so Talos's `scripts/apply_migrations.py` is available to the
start command. No Talos file is edited.
