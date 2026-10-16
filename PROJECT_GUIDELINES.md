# Argus SOC — Project Guidelines

How the three of us build Argus SOC during Graph Hacks (WeMakeDevs × FalkorDB, Oct 15–18, 2026).
The rules themselves are in `RULESET.md`; the file layout is in `FOLDER_STRUCTURE.md`.

## 1. What we're building

Argus SOC is a team of security agents that triage alerts, investigate them by walking a
FalkorDB graph, and recommend or take a response, while remembering every past case and analyst
verdict. Detection comes from **Talos**, our open-source detection engine (Apache licence),
which we call over its API and do not change.

We enter two tracks with one project:

- **Track 01 — Agents That Act on Connected Data:** multi-hop graph queries and graph algorithms
  drive every decision, and the agent acts.
- **Track 02 — Agent Memory and Coordination:** memory persists across sessions, updates from
  analyst feedback, is shared by every agent, and is isolated per tenant.

### What the demo must prove

| Track | Proof | Scenario |
|---|---|---|
| 01 | A multi-hop query decides the action (attack path to a crown jewel) | 1 |
| 01 | Graph algorithms used as agent tools (shortest path, centrality, connected components) | 1 |
| 01 | The agent acts, and can lower urgency as well as raise it | 1, 3 |
| 02 | Memory survives a restart | 2 |
| 02 | Memory updates from feedback (benign → playbook → auto-close) | 2 |
| 02 | Agents share state and hand off through the graph | 1 |
| 02 | Tenants are isolated | 4 |

## 2. How it fits together

```
Scenario logs ─► Talos (detect) ─► GET /reports ─► Ingestor ─► FalkorDB (one graph per tenant)
                                                                   ▲   │
                         Asset inventory (seeded) ─────────────────┘   │ graph tools (Q1–Q6)
                                                                       ▼
                                   Triage ─► Investigator ─► Responder ─► Analyst UI
                                      ▲                                      │
                                      └──────── Playbook ◄── Feedback ◄──────┘
```

The full walkthrough, with animation, is in `docs/design/Argus SOC with Talos.html`. The data model, queries
and demo scenarios are in the design doc.

## 3. Who owns what

| Workstream | Owner | Folders |
|---|---|---|
| A. Agents + Talos integration | Harshit | `src/argus_soc/agents/`, `src/argus_soc/ingestor/`, `data/scenarios/`, `deploy/talos/` |
| B. Database and graph | Md Adnan Afzal | `src/argus_soc/graph/`, `data/inventory/`, `deploy/`, `docker-compose.yml` |
| C. UI, API and submission | Satya | `src/argus_soc/api/`, `ui/`, `docs/`, `README.md` |

You own your folders: you decide how things work inside them. Anything shared (`core/`, the
contract files, these guideline files) changes only after telling the other two.

## 4. Tech stack

| Part | Choice |
|---|---|
| Language | Python 3.11+ everywhere except the UI |
| Graph database | FalkorDB (`falkordb/falkordb` Docker image, `falkordb` Python client) |
| Detection | Talos, pinned commit, run with `talos serve` and its own PostgreSQL |
| Backend API | FastAPI + Pydantic v2 |
| Agents | Python; framework and LLM provider chosen during the build |
| UI | Chosen by C (React + TypeScript + Vite suggested) |
| Quality | `ruff` (lint + format), `pytest` |
| Deployment | Docker Compose on the OCI instance, nginx reverse proxy with HTTPS |

## 5. The three contracts

These keep the workstreams independent. They are written out in full in the task split doc
("Interface contracts") and frozen once agreed (rule A11).

1. **Graph schema** — node labels, relationships, properties, case status values.
   Lives in `graph_schema.py`.
2. **Graph tools library** — function names, arguments and return shapes for reads (Q1–Q6,
   `list_cases`, `get_case`, `matching_playbook`) and writes (`upsert_alert_from_report` …
   `record_agent_run`). B ships stubs on day 1 in `graph_stubs.py`.
3. **UI API** — `/api/{tenant}/cases`, `/cases/{id}`, `/cases/{id}/feedback`, `/playbooks`,
   `/activity`. Shapes live in `api_models.py`; C serves mock data from hour one.

## 6. How the agents should behave

- **Graph first.** Every decision comes from a graph tool result, and the Decision node stores
  which results it used. That's what judges will check.
- **Deterministic core, LLM on top.** Triage rules and the Responder's decision table are plain
  code. The LLM writes explanations and helps with judgement calls, but the system still runs and
  decides with no LLM reachable (templated explanations).
- **Stateless workers.** All state is in the graph. Kill an agent mid-case, restart it, and it
  carries on from the case status.
- **Untrusted input.** Log lines and Talos evidence are attacker-controlled. Never put them in a
  prompt without delimiting and truncating them, and never treat them as instructions.
- **Simulated actions.** Isolate, disable and block are recorded and shown. Nothing touches real
  infrastructure.

## 7. Data

- **Scenario logs (A):** fixed files in Talos's web and sshd formats under `data/scenarios/`,
  one or more per demo scenario. Check each with `talos replay`.
- **Asset inventories (B):** fixed YAML per tenant under `data/inventory/`, using the same host
  names, accounts and IPs as the scenario logs.
- **Demo names:** Acme hosts `bastion-01`, `app-02`, `db-prod-01` (crown jewel), `web-01`;
  account `svc_deploy`; attacker `203.0.113.7`; injection source `198.51.100.23`; internal
  scanner `10.0.5.20`. Globex host `vpn-gw`.
- All of it is fictional. Use documentation IP ranges for external addresses.

## 8. Working rhythm

- **Syncs:** 15 minutes each morning and evening (IST): done, next, blocked.
- **Checkpoint — end of Oct 16:** scenario 1 runs end to end (Talos → ingestor → graph → three
  agents → UI), however rough.
- **Oct 17:** scenarios 2–4, OCI deployment with HTTPS, first full demo run.
- **Oct 18:** bug fixes only, video, README, **submit by 8 PM IST**.
- Track tasks in the task split doc; tick boxes as work lands on `main`.

## 9. Definition of done

A task is done when:

1. It works inside `docker compose up` on `main`.
2. It has a test or a scripted check (rule T1–T3).
3. `ruff` and `pytest` pass.
4. Any contract it touched is updated in the docs in the same pull request.
5. Its box is ticked in the task split doc.

## 10. Submission checklist

- [ ] Public GitHub repo
- [ ] README: setup steps, graph data model, architecture diagram, Cypher queries Q1–Q6
- [ ] README credits Talos (Apache licence, pinned commit) and lists what was built Oct 15–18
- [ ] README discloses AI coding assistant use
- [ ] Demo video, plus a backup recording
- [ ] Live URL on OCI, plus local setup steps
- [ ] Both tracks named on the submission form
- [ ] All three teammates on the WeMakeDevs panel
- [ ] Optional: blog post for the AirPods side prize

## 11. Reference

| File | Use it for |
|---|---|
| `docs/design/Argus SOC — FalkorDB Hackathon Design.md` | data model, agents, memory, queries, demo script, risks |
| `docs/design/Argus SOC — Task Split.md` | owners, task lists, interface contracts, day-by-day plan |
| `docs/design/Argus SOC with Talos.html` | animated walkthrough of every component and scenario; Talos explained |
| `RULESET.md` | the numbered rules |
| `FOLDER_STRUCTURE.md` | where every file goes |
| `CLAUDE.md` | short-form rules for AI coding sessions |
