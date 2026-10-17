# Argus SOC — Architecture

Diagrams of the whole system: context, deployment, components, graph schema, runtime sequences
and the case lifecycle. Diagrams are Mermaid and render on GitHub. Detail behind each one is in
`HLD.md`, `LLD.md` and `DFD.md`.

## 0. Who works on what in this document

| Section | Owner | What to take from it |
|---|---|---|
| 1. System context | Everyone | The big picture; read first |
| 2. Deployment view | **B — Database and graph** | Services, ports, network and volumes for `docker-compose.yml` and the GCP VM |
| 3. Component view: `ingestor/`, `agents/`, `deploy/talos/` | **A — Harshit** | Modules you build and what they call |
| 3. Component view: `graph/`, `core/` | **B — Database and graph** | Modules you build and who calls them |
| 3. Component view: `api/`, `ui/` | **C — UI, API and submission** | Modules you build and what they call |
| 4. Graph schema | **B** owns; **A** and **C** read | Labels and relationships every query uses |
| 5. Scenario 1 sequence | **A** owns the flow; **B** and **C** check their calls | The end-to-end run due by end of Oct 16 |
| 6. Case lifecycle | **A** owns; **C** displays it | Status values and who moves a case between them |
| 7. Learning loop sequence | **A** (learning logic), **C** (feedback UI) | Scenario 2 |
| 8. Trust boundaries | Everyone | What is untrusted and what stays private |

Owners: **A** = Agents + Talos integration (Harshit) · **B** = Database and graph (Md Adnan Afzal) ·
**C** = UI, API and submission (Satya).

---

## 1. System context

Talos detects. Argus SOC connects, remembers and decides. The analyst approves.

```mermaid
flowchart LR
    LOGS["Scenario logs<br/>web access + sshd/RDP<br/>(synthetic)"]
    INV["Asset inventories<br/>tenant_acme, tenant_globex<br/>(synthetic YAML)"]
    TALOS["Talos<br/>detection engine<br/>(Apache-2.0, unchanged)"]
    ARGUS["Argus SOC<br/>ingestor + 3 agents<br/>+ FalkorDB"]
    ANALYST(["Analyst<br/>(browser)"])
    JUDGE(["Judges<br/>(live URL, video)"])

    LOGS -- "talos replay" --> TALOS
    TALOS -- "IncidentReport JSON<br/>GET /reports" --> ARGUS
    INV -- "seed script" --> ARGUS
    ARGUS -- "cases, decisions, paths" --> ANALYST
    ANALYST -- "approve / reject / benign" --> ARGUS
    ARGUS --> JUDGE
```

---

## 2. Deployment view (Docker Compose on the GCP VM)

One Compose project. Only nginx is reachable from the internet. Talos, its PostgreSQL and
FalkorDB stay on the internal network.

Since Oct 17, 2026 it runs on one GCP Compute Engine VM (`argus-soc`, e2-standard-4, asia-south1,
static IP 34.93.139.203) instead of OCI (HLD D14). nginx serves the UI and API at `ARGUS_DOMAIN` and
the demo web shop at `SHOP_DOMAIN` (free sslip.io names); the rest of the live demo harness
(attack-bot, SSH target, log shipper) stays on `soc-net`. Steps: `deploy/gcp_runbook.md`.

```mermaid
flowchart TB
    subgraph INTERNET["Internet"]
        BROWSER(["Analyst / judge browser"])
    end

    subgraph VM["GCP VM argus-soc — docker compose project argus-soc"]
        NGINX["nginx<br/>:443 HTTPS<br/>/ → ui, /api → api<br/>SHOP_DOMAIN → web_shop"]

        subgraph NET["internal network: soc-net"]
            UI["ui<br/>static build<br/>:80"]
            API["api<br/>FastAPI :8080<br/>(Workstream C)"]
            AGENTS["agents<br/>agent_runner<br/>(Workstream A)"]
            ING["ingestor<br/>ingest_loop<br/>(Workstream A)"]
            FDB[("falkordb<br/>:6379<br/>graph per tenant")]
            TALOS["talos<br/>talos serve :8000<br/>(pinned commit)"]
            TPG[("talos-postgres<br/>:5432<br/>Talos audit log")]
            SHOP["web_shop<br/>demo target :8000<br/>(live demo harness)"]
        end

        VOLF[["volume: falkordb-data"]]
        VOLT[["volume: talos-pg-data"]]
    end

    BROWSER -- HTTPS --> NGINX
    NGINX --> UI
    NGINX --> API
    NGINX --> SHOP
    API -- "graph tools library" --> FDB
    AGENTS -- "graph tools library" --> FDB
    ING -- "graph tools library" --> FDB
    ING -- "HTTP GET /reports" --> TALOS
    TALOS --> TPG
    FDB --- VOLF
    TPG --- VOLT
    AGENTS -. "LLM API (OpenAI gpt-5.5 in the live demo)<br/>optional" .-> EXT(["LLM provider"])
```

| Service | Built from | Port (internal) | Exposed | Depends on | Owner |
|---|---|---|---|---|---|
| `nginx` | `deploy/nginx/` | 443 | **yes** | ui, api | B |
| `ui` | `deploy/ui.Dockerfile` | 80 | via nginx | — | C |
| `api` | `deploy/api.Dockerfile` | 8080 | via nginx `/api` | falkordb | C |
| `agents` | `deploy/agents.Dockerfile` (`agent_runner`) | — | no | falkordb | A |
| `ingestor` | `deploy/agents.Dockerfile` (`ingest_loop`) | — | no | falkordb, talos | A |
| `falkordb` | `falkordb/falkordb` image | 6379 | no | — | B |
| `talos` | `deploy/talos/Dockerfile` | 8000 | no | talos-postgres | A |
| `talos-postgres` | `postgres:16` image | 5432 | no | — | B |
| `web_shop` (+ `ssh_target`, `shipper`, `attack_bot`) | `demo/` (`demo/docker-compose.demo.yml`) | 8000 | shop only, via nginx `SHOP_DOMAIN` | talos | A |

---

## 3. Component view (inside the repo)

Arrows mean "calls". Nothing outside `graph/` talks to FalkorDB directly (rule A1).

```mermaid
flowchart LR
    subgraph A_ING["ingestor/ — A"]
        TC["talos_client"]
        RM["report_mapper"]
        TR["tenant_resolver"]
        IL["ingest_loop"]
    end

    subgraph A_AG["agents/ — A"]
        AR["agent_runner"]
        TRI["triage_agent"]
        INVE["investigator_agent"]
        RESP["responder_agent"]
        DT["decision_table"]
        HS["handoff_service"]
        LS["learning_service"]
        LLM["llm_client"]
        GTC["graph_tool_client<br/>(MCP client, deep dive)"]
        PR[["prompts/*.md"]]
    end

    subgraph B_GR["graph/ — B"]
        FC["falkor_client"]
        GS["graph_schema"]
        RQ["read_queries"]
        AQ["algorithm_queries"]
        WQ["write_queries"]
        STUB["graph_stubs"]
        MCP["mcp_server<br/>(read tools over stdio)"]
    end

    subgraph C_API["api/ — C"]
        SRV["api_server"]
        CR["case_routes"]
        PBR["playbook_routes"]
        ACR["activity_routes"]
        AM["api_models"]
    end

    subgraph CORE["core/ — shared"]
        SET["settings"]
        TEN["tenant_registry"]
        LOG["logging_setup"]
    end

    UIAPP["ui/ — C<br/>pages + components"]

    IL --> TC
    IL --> TR
    IL --> RM
    RM --> WQ
    TR --> TEN

    AR --> TRI & INVE & RESP
    TRI --> RQ & WQ & HS & LLM
    INVE --> RQ & AQ & WQ & HS & LLM & GTC
    GTC -- "MCP stdio" --> MCP
    GTC --> LLM
    RESP --> AQ & RQ & WQ & DT & HS & LLM
    LS --> WQ & RQ
    LLM --> PR
    HS --> WQ

    UIAPP -- "HTTP /api" --> SRV
    SRV --> CR & PBR & ACR
    CR --> RQ & WQ & AM
    CR --> LS
    PBR --> RQ
    ACR --> RQ

    RQ & AQ & WQ --> FC
    RQ & AQ & WQ --> GS
    FC --> SET
    MCP --> RQ & AQ
```

Note: the feedback route calls `learning_service` so that a benign verdict turns into a playbook
straight away. That one call crosses from C into A, so its signature is part of the contracts.

---

## 4. Graph schema (one graph per tenant)

```mermaid
flowchart LR
    subgraph ENV["Environment — seeded by B"]
        User((User))
        Host((Host))
        Service((Service))
        Endpoint((Endpoint))
        AssetTag((AssetTag))
    end
    subgraph ACT["Activity — written by ingestor (A)"]
        Alert((Alert))
        IOC((IOC))
        Technique((Technique))
    end
    subgraph MEM["Memory — written by agents (A) and API (C)"]
        Case((Case))
        Decision((Decision))
        Feedback((Feedback))
        Playbook((Playbook))
        AgentRun((AgentRun))
    end

    User -- LOGGED_INTO --> Host
    Host -- CONNECTS_TO --> Host
    Host -- RUNS --> Service
    Endpoint -- SERVED_BY --> Host
    Host -- TAGGED --> AssetTag

    Alert -- ON_HOST --> Host
    Alert -- INVOLVES --> User
    Alert -- INVOLVES --> IOC
    Alert -- TARGETED --> Endpoint
    Alert -- MAPS_TO --> Technique

    Case -- CONTAINS --> Alert
    Case -- HAS_DECISION --> Decision
    Decision -- ACTED_ON --> Host
    Decision -- ACTED_ON --> User
    Decision -- ACTED_ON --> IOC
    Feedback -- ON --> Case
    Playbook -- LEARNED_FROM --> Feedback
    AgentRun -- WROTE --> Case
    AgentRun -- WROTE --> Decision
    AgentRun -- HANDED_OFF_TO --> AgentRun
```

Properties for every label are listed in `LLD.md` §4.1.

---

## 5. Runtime sequence — scenario 1 (brute force that lands)

```mermaid
sequenceDiagram
    autonumber
    participant R as replay_scenario (A)
    participant T as Talos
    participant I as Ingestor (A)
    participant G as Graph tools + FalkorDB (B)
    participant TRI as Triage (A)
    participant INV as Investigator (A)
    participant RSP as Responder (A)
    participant API as API (C)
    participant UI as Analyst UI (C)

    R->>T: replay sshd log (12 failures, then success)
    Note over T: parse → window → route → classify →<br/>SSH ∥ RDP detectors → aggregate → suppress
    T->>T: store IncidentReport (high, 0.90, succeeded)
    R->>T: replay web log (credential stuffing, same IP)
    T->>T: store IncidentReport (medium)

    loop every POLL_INTERVAL seconds
        I->>T: GET /reports
        T-->>I: newest incidents
        I->>G: known_incident_ids(tenant)
        I->>T: GET /reports/{id} (new ones only)
        I->>G: upsert_alert_from_report(tenant, report)
    end

    TRI->>G: list_new_alerts(tenant)
    TRI->>G: matching_playbook(...) → none
    TRI->>G: recall(ioc=203.0.113.7) → none
    TRI->>G: entity_facts(bastion-01, svc_deploy, 203.0.113.7) → none yet
    TRI->>G: linked_alerts(inc-7f3a) → [inc-81c2]
    TRI->>G: open_or_join_case → Case 31, set status triaged
    TRI->>G: record_agent_run(handed_to=investigator)

    INV->>G: claim_case(status=triaged) → 31
    INV->>G: blast_radius(ioc) / paths_to_crown_jewels(bastion-01)
    G-->>INV: bastion-01 → app-02 → db-prod-01
    opt deep dive (LLM on)
        INV->>G: MCP tool chosen by LLM, e.g. recall(user=svc_deploy)
        G-->>INV: result stored as evidence (max DEEP_DIVE_MAX_CALLS)
    end
    INV->>G: record findings + semantic facts (svc_deploy suspected, bastion-01 targeted)
    INV->>G: status investigated, handoff

    RSP->>G: claim_case(status=investigated) → 31
    RSP->>G: rank_hosts(31) → bastion-01 first
    Note over RSP: decision_table: succeeded + path → isolate,<br/>disable, block, needs approval
    RSP->>G: record_decision, status awaiting_approval

    UI->>API: GET /api/acme/cases (poll)
    API->>G: list_cases / get_case / explain_decision
    API-->>UI: case 31 with path and decision
    UI->>API: POST /cases/31/feedback {approve}
    API->>G: record_feedback, set status closed
```

---

## 6. Case lifecycle

```mermaid
stateDiagram-v2
    [*] --> new: Triage opens case
    new --> auto_closed: playbook matched (Triage)
    new --> triaged: correlated + prioritised (Triage)
    triaged --> investigated: findings written (Investigator)
    investigated --> awaiting_approval: high-impact decision (Responder)
    investigated --> closed: automatic low-impact decision (Responder)
    awaiting_approval --> closed: analyst approves or rejects (API)
    closed --> closed: analyst marks benign later (API, triggers learning)
    auto_closed --> [*]
    closed --> [*]
```

| Status | Set by | Next owner |
|---|---|---|
| `new` | Triage, when it opens the case | Triage (same step) |
| `triaged` | Triage | Investigator |
| `investigated` | Investigator | Responder |
| `awaiting_approval` | Responder | Analyst (UI) |
| `closed` | Responder (automatic actions) or API (analyst verdict) | — |
| `auto_closed` | Triage (playbook match) | — |

A case also stores `claimed_by` and `claimed_at`, so two workers never take the same case
(see `LLD.md` §6.1).

---

## 7. Learning loop — scenario 2

```mermaid
sequenceDiagram
    autonumber
    participant UI as Analyst UI (C)
    participant API as API (C)
    participant LS as learning_service (A)
    participant G as Graph tools + FalkorDB (B)
    participant TRI as Triage (A)

    Note over UI,G: Session 1
    UI->>API: POST /cases/32/feedback {benign, "internal pentest scanner"}
    API->>G: record_feedback(tenant, 32, benign, note)
    API->>LS: on_feedback(tenant, 32, feedback_id)
    LS->>G: feedback pattern = (category auth_failure, ioc 10.0.5.20)
    LS->>G: create_playbook_version(condition, action=auto_close)
    Note over G: Playbook v2 -[:LEARNED_FROM]-> Feedback

    Note over UI,TRI: docker compose restart agents — graph untouched

    Note over TRI,G: Session 2: same burst ingested as a new Alert
    TRI->>G: matching_playbook(alert) → v2 (from Case 32)
    TRI->>G: open case 33 as auto_closed, cite v2 and Case 32
```

---

## 8. Trust boundaries

```mermaid
flowchart LR
    subgraph UNTRUSTED["Untrusted"]
        LOGDATA["Log lines and payloads<br/>(attacker-controlled)"]
        BROWSERIN["Browser input<br/>(feedback notes)"]
    end
    subgraph SEMI["Trusted service, untrusted content"]
        TALOSOUT["Talos reports<br/>evidence quotes raw lines"]
    end
    subgraph TRUSTED["Trusted"]
        CODE["Argus SOC code<br/>decision_table, queries"]
        GRAPH[("FalkorDB")]
    end
    subgraph EXT["External"]
        LLMP(["LLM provider"])
    end

    LOGDATA --> TALOSOUT --> CODE
    BROWSERIN -- "validated by api_models" --> CODE
    CODE --> GRAPH
    CODE -- "delimited, truncated excerpts only" --> LLMP
```

- Anything quoted from logs is data. It never becomes an instruction, a Cypher fragment or a shell
  argument. Queries always use parameters.
- Only nginx is public. Talos has no authentication, so it stays internal.
- The API requires a signed session token on every `/api/{tenant}/…` call (GAP-1, proposed).
  Hackathon users are hard-coded in `.env` (HLD D13); no analyst account data is stored in
  FalkorDB. The feedback author comes from the token, not from browser input.
- The LLM receives short, delimited excerpts, never the whole graph or secrets.
