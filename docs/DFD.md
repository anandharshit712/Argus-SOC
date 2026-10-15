# Argus SOC — Data Flow Diagrams (DFD)

Where data comes from, what transforms it, where it is stored and who reads it. Level 0 is the
whole system, Level 1 its main processes, Level 2 opens up the busiest ones. The data dictionary
at the end defines every flow.

Notation in the Mermaid diagrams: rectangles are **processes** (numbered), cylinders are **data
stores** (D-numbered), rounded boxes are **external entities**.

## 0. Who works on what in this document

| Section | Owner | What to check |
|---|---|---|
| 1. Level 0 context | Everyone | System boundary |
| 2. Level 1 | Everyone; each process names its owner | Which process you own and its inputs and outputs |
| 3. Level 2 — P1 Ingest incidents | **A — Harshit** | Talos → graph mapping |
| 4. Level 2 — Talos detection (external, for reference) | **A** | How the IncidentReport is produced |
| 5. Level 2 — P3–P5 Agents | **A** | What each agent reads and writes |
| 6. Level 2 — P6 Feedback and learning | **A** (learning), **C** (feedback capture) | The memory update loop |
| 7. Level 2 — P7 Serve the analyst | **C — UI, API and submission** | What the UI reads and writes |
| 8. Data stores | **B — Database and graph** | D1 layout, retention, who writes what |
| 9. Data dictionary | **B** keeps it current; A and C add their flows | Field-level definitions |
| 10. Trust and sensitivity | Everyone | Untrusted data and what must stay private |

Owners: **A** = Agents + Talos integration (Harshit) · **B** = Database and graph (Md Adnan Afzal) ·
**C** = UI, API and submission (Satya).

---

## 1. Level 0 — context

```mermaid
flowchart LR
    E1(["E1 Scenario runner<br/>(log files)"])
    E2(["E2 Talos<br/>(external system)"])
    E3(["E3 Asset inventory files"])
    E4(["E4 Analyst"])
    E5(["E5 LLM provider<br/>(optional)"])
    P0["0 Argus SOC"]

    E1 -- "F1 raw log lines" --> E2
    E2 -- "F2 IncidentReports" --> P0
    E3 -- "F3 environment records" --> P0
    P0 -- "F10 cases, decisions, paths, activity" --> E4
    E4 -- "F11 analyst verdicts" --> P0
    P0 -- "F8 explanation prompts (delimited excerpts)" --> E5
    E5 -- "F9 explanations" --> P0
```

Talos is drawn as external: we run it but do not change it.

---

## 2. Level 1 — main processes

```mermaid
flowchart TB
    E2(["E2 Talos"])
    E3(["E3 Inventory files"])
    E4(["E4 Analyst"])
    E5(["E5 LLM provider"])

    P1["P1 Ingest incidents<br/>(A)"]
    P2["P2 Seed environment<br/>(B)"]
    P3["P3 Triage<br/>(A)"]
    P4["P4 Investigate<br/>(A)"]
    P5["P5 Respond<br/>(A)"]
    P6["P6 Feedback and learning<br/>(A + C)"]
    P7["P7 Serve the analyst<br/>(C)"]

    D1[("D1 Tenant graph (FalkorDB)<br/>D1a Environment · D1b Activity · D1c Memory")]
    D2[("D2 Talos verdict log<br/>(PostgreSQL, inside Talos)")]

    E2 -- "F2 IncidentReports" --> P1
    E2 --- D2
    P1 -- "F4 alerts + entities" --> D1
    E3 -- "F3 environment records" --> P2
    P2 -- "F3 hosts, users, links, tags" --> D1

    D1 -- "F5 new alerts, playbooks, history, links" --> P3
    P3 -- "F6a cases, findings, agent runs" --> D1
    D1 -- "F5 case, blast radius, paths, MCP tool results" --> P4
    P4 -- "F6b findings, status · F6c semantic facts" --> D1
    P4 -- "F8 deep-dive prompt + tool list" --> E5
    E5 -- "F9 tool choice" --> P4
    D1 -- "F5 case, findings, ranking" --> P5
    P5 -- "F7 decisions, status" --> D1
    P5 -- "F8 prompt" --> E5
    E5 -- "F9 explanation" --> P5

    D1 -- "F10 cases, decisions, paths, playbooks, activity" --> P7
    P7 -- "F10 views" --> E4
    E4 -- "F11 verdicts" --> P7
    P7 -- "F11 verdict" --> P6
    P6 -- "F12 feedback, playbook versions, IOC facts" --> D1
    D1 -- "F13 active playbooks" --> P3
```

| Process | Owner | Input flows | Output flows | Runs |
|---|---|---|---|---|
| P1 Ingest incidents | A | F2 | F4 | Loop every 3 s |
| P2 Seed environment | B | F3 | F3 into D1a | Once, and on reset |
| P3 Triage | A | F5, F13 | F6a | Loop every 2 s, per tenant |
| P4 Investigate | A | F5, F9 | F6b, F6c, F8 | Per claimed case |
| P5 Respond | A | F5, F9 | F7, F8 | Per claimed case |
| P6 Feedback and learning | A (logic), C (capture) | F11 | F12 | On each verdict |
| P7 Serve the analyst | C | F10, F11 | F10, F11 | On request; UI polls every 2–3 s |

---

## 3. Level 2 — P1 Ingest incidents (A)

```mermaid
flowchart LR
    E2(["Talos API"])
    P11["1.1 List recent reports<br/>GET /reports"]
    P12["1.2 Filter new ids<br/>known_incident_ids"]
    P13["1.3 Fetch report<br/>GET /reports/{id}"]
    P14["1.4 Resolve tenant"]
    P15["1.5 Map report<br/>fields + IP extraction"]
    P16["1.6 Write alert<br/>upsert_alert_from_report"]
    D1b[("D1b Activity")]
    D1a[("D1a Environment")]

    E2 -- "report list" --> P11
    P11 -- "incident ids" --> P12
    D1b -- "existing ids" --> P12
    P12 -- "new ids" --> P13
    E2 -- "F2 IncidentReport" --> P13
    P13 --> P14
    D1a -- "tenant host names" --> P14
    P14 -- "report + tenant" --> P15
    P15 -- "F4 AlertInput" --> P16
    P16 -- "MERGE Alert, IOC, Technique, links" --> D1b
    P16 -- "MERGE links to Host, User, Endpoint" --> D1a
```

---

## 4. Level 2 — Talos detection (external, for reference)

How Talos turns F1 into F2. This runs inside Talos; we do not change it.

```mermaid
flowchart LR
    F1(["F1 raw log line"])
    T1["Parse<br/>→ NormalizedEvent"]
    T2[("Event window<br/>(recent events)")]
    T3["Route by domain"]
    T4["Classify attack type<br/>(static first, model if unsure)"]
    T5["Sub-agent:<br/>detectors in parallel"]
    T6["Aggregate verdicts<br/>severity, confidence, actions"]
    T7["Suppress repeats<br/>unless escalated"]
    D2[("D2 Talos verdict log")]
    OUT(["F2 IncidentReport<br/>GET /reports"])

    F1 --> T1 --> T2 --> T3 --> T4 --> T5
    T2 -. "windowed counts" .-> T5
    T5 -- "Verdicts" --> T6 --> T7 --> D2 --> OUT
```

---

## 5. Level 2 — P3 Triage, P4 Investigate, P5 Respond (A)

```mermaid
flowchart TB
    D1b[("D1b Activity")]
    D1a[("D1a Environment")]
    D1c[("D1c Memory")]
    E5(["LLM provider"])

    subgraph P3["P3 Triage"]
        P31["3.1 Take new alerts"]
        P32{"3.2 Playbook<br/>matches?"}
        P33["3.3 Recall history (Q4)"]
        P34["3.4 Link alerts (Q5)"]
        P35["3.5 Open or join case,<br/>set priority"]
        P36["3.6 Auto-close case"]
    end

    subgraph P4["P4 Investigate"]
        P41["4.1 Claim triaged case"]
        P42["4.2 Blast radius (Q1)"]
        P43["4.3 Paths to crown jewels (Q2)"]
        P45["4.5 Deep dive: LLM picks<br/>read tools over MCP (optional)"]
        P44["4.4 Write findings<br/>+ semantic facts"]
    end

    subgraph P5["P5 Respond"]
        P51["5.1 Claim investigated case"]
        P52["5.2 Rank hosts (Q3)"]
        P53["5.3 Apply decision table"]
        P54["5.4 Explain"]
        P55["5.5 Write decision"]
    end

    D1b -- "new alerts" --> P31 --> P32
    D1c -- "F13 active playbooks" --> P32
    P32 -- yes --> P36 -- "auto_closed case" --> D1c
    P32 -- no --> P33
    D1c -- "past cases, verdicts" --> P33 --> P34
    D1a -- "semantic facts (suspected, targeted)" --> P33
    D1b -- "alerts sharing host/user/IOC" --> P34 --> P35
    P35 -- "F6a case (triaged), agent run" --> D1c

    D1c -- "triaged case" --> P41 --> P42
    D1b -- "alerts by IOC" --> P42
    D1a -- "logins" --> P42
    P42 --> P43
    D1a -- "links, crown-jewel tags" --> P43
    P43 --> P45
    P45 -- "F8 delimited excerpt + tool list" --> E5
    E5 -- "F9 tool choice" --> P45
    D1a & D1b & D1c -- "F5 read-tool results (MCP)" --> P45
    P45 --> P44 -- "F6b findings (investigated), deep-dive calls" --> D1c
    P44 -- "F6c semantic facts" --> D1a & D1b

    D1c -- "investigated case + findings" --> P51 --> P52
    D1a -- "host subgraph, criticality" --> P52
    P52 --> P53 --> P54
    P54 -- "F8 delimited excerpt" --> E5
    E5 -- "F9 explanation" --> P54
    P54 --> P55 -- "F7 decision, status" --> D1c
    P55 -- "simulated flags (isolated, disabled)" --> D1a
```

---

## 6. Level 2 — P6 Feedback and learning (A logic, C capture)

```mermaid
flowchart LR
    E4(["Analyst"])
    P61["6.1 Validate verdict<br/>(API, C)"]
    P62["6.2 Record feedback<br/>(API, C)"]
    P63{"6.3 Verdict type?<br/>(learning, A)"}
    P64["6.4 Count benign verdicts<br/>for the pattern"]
    P65["6.5 Create playbook version"]
    P66["6.6 Update IOC facts"]
    D1c[("D1c Memory")]
    D1b[("D1b Activity")]

    E4 -- "F11 approve / reject / benign + note" --> P61 --> P62
    P62 -- "Feedback, decision outcome, case closed" --> D1c
    P62 --> P63
    P63 -- benign --> P64
    D1c -- "earlier feedback" --> P64
    P64 -- "threshold reached" --> P65 -- "F12 Playbook vN (LEARNED_FROM)" --> D1c
    P63 -- "any verdict" --> P66 -- "F12 IOC verdict / owner" --> D1b
```

---

## 7. Level 2 — P7 Serve the analyst (C)

```mermaid
flowchart LR
    E4(["Analyst browser"])
    P71["7.1 Case queue"]
    P72["7.2 Case detail + path"]
    P73["7.3 Playbooks"]
    P74["7.4 Activity feed"]
    P75["7.5 Feedback form"]
    D1c[("D1c Memory")]
    D1b[("D1b Activity")]
    D1a[("D1a Environment")]
    P6["P6 Feedback and learning"]

    D1c -- "cases" --> P71 --> E4
    D1c -- "case, decision, findings" --> P72
    D1b -- "alerts, evidence" --> P72
    D1a -- "path node names" --> P72
    P72 --> E4
    D1c -- "playbooks" --> P73 --> E4
    D1c -- "agent runs" --> P74 --> E4
    E4 -- "F11 verdict" --> P75 --> P6
```

---

## 8. Data stores

| Store | Technology | Contents | Written by | Read by | Kept |
|---|---|---|---|---|---|
| D1a Environment | FalkorDB, per-tenant graph | Host, User, Service, Endpoint, AssetTag and links | P2 (seed), P4 (semantic facts), P5 (simulated flags) | P1, P3, P4, P5, P7 | Until reset |
| D1b Activity | same graph | Alert, IOC, Technique and links | P1, P4 (IOC seen in cases), P6 (IOC facts) | P3, P4, P7 | Until reset |
| D1c Memory | same graph | Case, Decision, Feedback, Playbook, AgentRun | P3, P4, P5, P6 | P3–P7 | Until reset; survives restarts |
| D2 Talos verdict log | PostgreSQL inside Talos | Talos IncidentReports | Talos | Talos API only | Talos's own |

D1a–D1c are logical areas of one graph per tenant (`tenant_acme`, `tenant_globex`). Nothing flows
between tenant graphs.

---

## 9. Data dictionary

| Flow | Name | Fields | Producer → consumer |
|---|---|---|---|
| F1 | Raw log line | text line in nginx access or sshd/RDP format | Scenario runner → Talos |
| F2 | IncidentReport | `incident_id`, `created_at`, `domain`, `category`, `summary`, `severity`, `confidence`, `verdicts[]` (detector, technique, confidence, evidence[], scope, reasoning, model), `aggregate_scope` (affected_accounts, affected_endpoints, affected_objects, affected_hosts, attempt_count, source_diversity, succeeded, window_start, window_end), `mitre_techniques[]` (technique_id, technique_name, tactic), `recommended_actions[]` | Talos → P1 |
| F3 | Environment record | hosts (hostname, ip, zone, criticality, tags), users (username, role, privileged, logs_into), links (from, to, port), known IOCs | Inventory YAML → P2 → D1a |
| F4 | AlertInput | incident_id, domain, category, severity, confidence, succeeded, summary, talos_created_at, hosts[], users[], endpoints[], techniques[], source_ips[], evidence[], recommended_actions[] | P1 → D1b |
| F5 | Agent read set | per query: Q1 blast radius rows, Q2 paths, Q3 ranking, Q4 history, Q5 linked ids, case detail | D1 → P3/P4/P5 |
| F6a | Triage output | Case (id, status=triaged, priority), CONTAINS links, findings.recall, findings.linked, AgentRun | P3 → D1c |
| F6b | Investigation output | findings.succeeded, findings.path_to_crown_jewel, findings.shortest_path, findings.blast_radius, findings.deep_dive (tool, args, result, why), status=investigated, AgentRun (worker, tool_calls) | P4 → D1c |
| F6c | Semantic facts | Host targeted_case_ids, last_targeted_at; User suspected_compromised, suspected_at, suspect_case_id; IOC seen_case_ids | P4 → D1a, D1b; read by P3 |
| F7 | Decision | id, rule_id, actions[], targets, needs_approval, reason, explanation, evidence (query results), outcome, status | P5 → D1c |
| F8 | Explanation prompt | prompt name, case summary, rule, ranking, delimited evidence excerpts (≤ 500 chars each) | P5 → LLM |
| F9 | Explanation | text ≤ 1,000 chars, or none (template used) | LLM → P5 |
| F10 | Analyst view | CaseSummary, CaseDetail (alerts, findings, decision, path, ranking, feedback, agent runs), PlaybookOut, ActivityItem | D1 → P7 → Analyst |
| F11 | Analyst verdict | tenant, case_id, verdict (approve/reject/benign), note ≤ 500 chars, analyst | Analyst → P7 → P6 |
| F12 | Learning output | Feedback node, Decision outcome, Playbook (name, version, condition, action, active), IOC verdict/owner | P6 → D1 |
| F13 | Active playbooks | name, version, condition (category, ioc_in), source case | D1c → P3 |

---

## 10. Trust and sensitivity

| Data | Trust level | Handling |
|---|---|---|
| F1 log lines, evidence inside F2 | **Untrusted** (attacker-controlled) | Never executed or followed; parameterised queries only; delimited and truncated before any prompt; truncated in logs |
| F11 analyst notes | Untrusted input | Validated by `api_models` (length, type); stored as text only |
| F8 prompts | Leaves the system | Only short excerpts; no secrets, no whole graph |
| D2 Talos log | Internal | Talos port never published |
| D1 tenant graphs | Internal, isolated | One graph per tenant; FalkorDB port never published |
| Secrets (LLM key, DB passwords) | Secret | `.env` only, never in git or logs |

All scenario data is synthetic; external addresses use documentation IP ranges.
