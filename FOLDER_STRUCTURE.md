# Argus SOC — Folder Structure

Every file has one owner, set by the folder it lives in. If you need a file somewhere that
isn't listed here, add it to this document in the same pull request.

Owners: **A** = Agents + Talos integration (Harshit) · **B** = Database and graph (Md Adnan Afzal) ·
**C** = UI, API and submission (Satya) · **shared** = change only after telling all three.

## Tree

```
Argus-SOC/                              repository root
├── CLAUDE.md                           shared   rules for AI coding sessions
├── README.md                           C        submission README (setup, schema, queries, credits)
├── PROJECT_GUIDELINES.md               shared   how we build
├── RULESET.md                          shared   the rules, numbered
├── FOLDER_STRUCTURE.md                 shared   this file
├── pyproject.toml                      B        Python package, dependencies, ruff/pytest config
├── docker-compose.yml                  B        every service, one command to run
├── docker-compose.oci.yml              B        OCI override: HTTPS on 80/443
├── .dockerignore                       B        keeps .env and caches out of images
├── .env.example                        B        every variable, no real values
├── .gitignore                          shared
│
├── src/argus_soc/                      Python package (import argus_soc....)
│   ├── __init__.py
│   ├── core/                           shared   small, rarely changes
│   │   ├── settings.py                 env and config loading (pydantic-settings)
│   │   ├── tenant_registry.py          tenant ids → FalkorDB graph names
│   │   └── logging_setup.py            structured logging
│   │
│   ├── graph/                          B        the ONLY place Cypher is written
│   │   ├── falkor_client.py            connection, select graph by tenant
│   │   ├── graph_schema.py             label, relationship, property and status constants
│   │   ├── index_setup.py              indexes on lookup keys
│   │   ├── read_queries.py             Q1, Q2, Q4, Q5, Q6, entity_facts, list_cases, get_case, matching_playbook
│   │   ├── algorithm_queries.py        Q3 ranking; shortest path, centrality, WCC wrappers
│   │   ├── write_queries.py            upsert_alert_from_report … record_agent_run (all MERGE)
│   │   ├── graph_stubs.py              same signatures, fixed sample data, for A and C
│   │   └── mcp_server.py               read functions exposed over MCP (stdio) for the deep dive
│   │
│   ├── ingestor/                       A        Talos → graph
│   │   ├── talos_client.py             GET /healthz, /reports, /reports/{incident_id}
│   │   ├── report_mapper.py            IncidentReport → write_queries calls
│   │   ├── tenant_resolver.py          which tenant an incident belongs to
│   │   └── ingest_loop.py              polling loop entry point
│   │
│   ├── agents/                         A        the three agents and learning
│   │   ├── triage_agent.py
│   │   ├── investigator_agent.py
│   │   ├── responder_agent.py
│   │   ├── decision_table.py           Responder rules as data, not prose
│   │   ├── handoff_service.py          case status + HANDED_OFF_TO
│   │   ├── learning_service.py         Feedback → Playbook version
│   │   ├── llm_client.py               provider wrapper (provider chosen during the build)
│   │   ├── graph_tool_client.py        MCP client: Investigator deep dive, tenant set by code
│   │   ├── agent_runner.py             worker loop entry point
│   │   └── prompts/                    <agent>_<purpose>_v<N>.md
│   │
│   └── api/                            C        backend for the UI
│       ├── api_server.py               FastAPI app
│       ├── case_routes.py              /api/{tenant}/cases, /cases/{id}, /cases/{id}/feedback
│       ├── playbook_routes.py          /api/{tenant}/playbooks
│       ├── activity_routes.py          /api/{tenant}/activity
│       ├── api_models.py               Pydantic response shapes (this IS the UI contract)
│       ├── auth_routes.py              /api/auth/login, /me, /logout (GAP-1, proposed)
│       ├── session_tokens.py           sign and check session tokens (GAP-1, proposed)
│       └── mock_data.py                mock responses until the real graph is ready
│
├── ui/                                 C        framework chosen by C (React + TypeScript + Vite suggested)
│   ├── package.json
│   └── src/
│       ├── pages/                      case queue, case detail, playbooks, activity feed
│       ├── components/                 path graph view, decision card, feedback form, tenant switcher
│       └── api/                        typed client for /api
│
├── data/
│   ├── scenarios/                      A        scenario logs in Talos formats
│   │                                            e.g. scenario_01_brute_force_sshd.log
│   └── inventory/                      B        tenant_acme_inventory.yaml, tenant_globex_inventory.yaml
│
├── deploy/                             B (talos/ by A)
│   ├── talos/Dockerfile                Talos pinned to a commit of the public repo
│   ├── agents.Dockerfile               runs ingestor, agents and the seed job
│   ├── api.Dockerfile
│   ├── ui.Dockerfile                   Vite build served by nginx
│   ├── oci_runbook.md                  OCI steps: ports, DNS, certificate, deploy, reset
│   └── nginx/                          proxy-common.conf, ui-static.conf,
│       ├── local/                      front proxy on http://127.0.0.1:8088
│       └── oci/                        front proxy with HTTPS for ARGUS_DOMAIN
│
├── scripts/
│   ├── seed_tenants.py                 B        load both inventories
│   ├── reset_demo.py                   B        wipe and reseed for judges
│   └── replay_scenario.py              A        replay a scenario log into Talos; --burst for the concurrency test
│
├── tests/                              mirrors src/argus_soc/
│   ├── graph/                          B
│   ├── ingestor/                       A
│   ├── agents/                         A
│   ├── api/                            C
│   └── e2e/                            A        test_scenario_01.py … one per demo scenario; test_concurrency_burst.py
│
└── docs/                               C (A and B contribute)
    ├── ARCHITECTURE.md                 diagrams: context, deployment, components, sequences
    ├── HLD.md                          high-level design
    ├── LLD.md                          low-level design
    ├── DFD.md                          data flow diagrams
    ├── graph_schema.md                 B
    ├── cypher_queries.md               B        Q1–Q6 with explanations (required for submission)
    ├── demo_script.md                  C
    ├── UI_PAGES.md                     C        every UI page, field by field
    ├── CONTRACT_GAPS.md                all      open contract gaps and who does what
    └── design/                         design doc, task split, HTML explainer
```

The three planning files (design doc, task split, HTML explainer) live in `docs/design/`.
`CHAT_LOG.md` stays in the root and is git-ignored. Empty folders hold a `.gitkeep` until real
files arrive.

## Naming

- **Python files:** `snake_case`, named `<subject>_<role>.py` so the name says what the file does.
  Roles: `agent`, `service`, `client`, `queries`, `routes`, `models`, `mapper`, `loop`,
  `runner`, `setup`, `schema`, `stubs`, `registry`, `server`, `table`.
- **Never:** `utils.py`, `helpers.py`, `common.py`, `misc.py`, `*_v2.py`, `*_final.py`, `*_new.py`.
- **Tests:** `tests/<same folder>/test_<module>.py`.
- **Prompts:** `<agent>_<purpose>_v<N>.md`; bump `N` on any change in meaning.
- **Scenario logs:** `scenario_<NN>_<attack>_<source>.log`.
- **UI files:** follow the UI framework's own convention, chosen by C.

## Size

- Aim for files under 400 lines.
- At 600 lines, split by responsibility.
- 800 lines is the hard limit.
