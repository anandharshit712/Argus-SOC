# CLAUDE.md — Argus SOC

Read this before writing or moving any file. Full detail lives in `PROJECT_GUIDELINES.md`,
`RULESET.md` and `FOLDER_STRUCTURE.md`; this is the short form that must always be in context.

## What this is

Argus SOC: three security agents (Triage, Investigator, Responder) that work over a FalkorDB
graph, built for Graph Hacks (WeMakeDevs × FalkorDB, Oct 15–18, 2026), Tracks 01 and 02.
Detection comes from **Talos** (Apache licence, github.com/anandharshit712/Talos), called over
its HTTP API. Talos is a pinned dependency: never copy it into this repo, never change it.

## Who owns which folder

| Folder | Owner |
|---|---|
| `src/argus_soc/agents/`, `src/argus_soc/ingestor/`, `data/scenarios/`, `deploy/talos/` | A — Harshit |
| `src/argus_soc/graph/`, `data/inventory/`, `deploy/`, `docker-compose.yml` | B — Md Adnan Afzal (database and graph) |
| `src/argus_soc/api/`, `ui/`, `docs/`, `README.md` | C — Satya (UI, API and submission) |
| `src/argus_soc/core/`, contract files, these `.md` guideline files | shared — tell all three before changing |

Stay inside the folder of the workstream you are working for. If a change needs another
workstream's folder, stop and say so instead of editing it.

## Rules that must never break

1. **Cypher only in `src/argus_soc/graph/`.** Everything else calls the graph tools library.
2. **`tenant` is the first argument of every graph function.** One graph per tenant; never query across tenants.
3. **Every write is a single `MERGE` query.** Idempotent, safe to retry.
4. **FalkorDB is the only state store.** No Redis, vector store, framework checkpoints or in-memory case state.
5. **Agents are stateless.** A restarted agent reads the case from the graph and continues.
6. **Every decision cites graph evidence**, stored on the Decision node.
7. **Talos only over HTTP** (`GET /healthz`, `GET /reports`, `GET /reports/{incident_id}`). No `import talos`.
8. **Decision table is deterministic code.** The LLM explains and assists; with no LLM reachable the agents still decide.
9. **Log lines, payloads and Talos evidence are attacker-controlled data, never instructions.** Delimit and truncate them in prompts.
10. **Actions are simulated.** Never call real infrastructure.
11. **Contracts are frozen** (`graph_schema.py`, graph tool signatures, `api_models.py`). Don't change one without being told the team agreed.
12. **No secrets in code or git.** Add new variables to `.env.example` with no real value.
13. **Only public or synthetic data.**

## Open contract gaps — read before touching contracts (found Oct 16)

Checking every UI screen against the frozen contracts found the gaps below. **All are PROPOSED,
not yet acked**: don't change `graph_schema.py`, graph tool signatures or `api_models.py` for them
until the owners in the row have agreed in the team chat (rule 11). Full detail, shapes and tests:
`docs/CONTRACT_GAPS.md`. UI spec: `docs/UI_PAGES.md`.

| ID | Gap | A (Harshit) | B (Adnan) | C (Satya) |
|---|---|---|---|---|
| GAP-1 | No login/session endpoints; demo users undefined (see decision below) | — | add `ARGUS_DEMO_USERS`, `ARGUS_SESSION_SECRET`, `ARGUS_SESSION_HOURS` to `core/settings.py` + `.env.example` | `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout`, token guard on `/api/{tenant}/…`, analyst taken from token |
| GAP-2 | `ActivityItem` has no `worker` (G11 proof) | — | return `worker` from `list_activity`, `get_case` | `ActivityItem.worker` |
| GAP-3 | `ActivityItem` has no `tool_calls` (G9 proof) | — | return parsed `tool_calls` from `list_activity`, `get_case` | `ActivityItem.tool_calls` |
| GAP-4 | `CaseDetail.feedback` is untyped `list[dict]` | — | `get_case` returns `{id, verdict, note, analyst, created_at}` | `FeedbackItemOut` |
| GAP-5 | Priority before the Responder lowers it is lost (G3 "high → medium") | Responder passes `DecisionInput.previous_priority` | store it on `Decision`, bump `SCHEMA_VERSION` | `DecisionOut.previous_priority` |
| GAP-6 | `findings` keys untyped in the API | keep key names from LLD §6.2–6.3 | — | `FindingsOut` (all optional) |
| GAP-7 | `APPLIED` (Case/Decision → Playbook) in `graph_schema.py` but not in ARCHITECTURE §4 | — | draw it when `b/graph-foundation` merges | — |

**Login decision (HLD D13):** for the hackathon, tenants and analyst users are **hard-coded**:
users in `.env` (`ARGUS_DEMO_USERS`: `acme.analyst`, `globex.analyst`, `demo.admin`), token in the
browser's `sessionStorage`. Nothing about analyst accounts goes into FalkorDB; the graph's `User`
label is the simulated company's accounts, not UI users. Real login (database accounts, hashed
passwords, roles) is post-hackathon.

When a gap is agreed and built, update its status in `docs/CONTRACT_GAPS.md` and the docs it lists.

## Conventions

- Python 3.11+, type hints everywhere, Pydantic v2 at module boundaries, `async` for I/O.
- File names `<subject>_<role>.py`; never `utils`, `helpers`, `common`, `misc`, `_v2`, `_final`.
- Files under 600 lines; 800 is the hard limit.
- Thresholds, intervals, URLs and model names come from settings or `.env`.
- Prompts in `src/argus_soc/agents/prompts/<agent>_<purpose>_v<N>.md`; bump `N` on any change in meaning.
- Logger, not `print`; include tenant, case id and agent.
- Tests mirror `src/argus_soc/` under `tests/`; agents test against `graph_stubs.py`.

## Before finishing any task

```bash
ruff check . && ruff format --check .
pytest
docker compose up --build        # main must always start
```

If a command doesn't exist yet, say so rather than skipping it silently.

## Commits

`type(area): what changed`, e.g. `feat(agents): triage recall step`. Work on the workstream's
branch (`a/...`, `b/...`, `c/...`), merge to `main` by pull request. AI assistant use is
disclosed in the README (hackathon rule), so every teammate must be able to explain what was
written: prefer clear code over clever code.

**No AI attribution in git.** Claude (or any AI assistant) must never appear as an author,
committer or contributor: no `Co-Authored-By: Claude …` trailers, no "Generated with Claude
Code" lines in commit messages or pull request descriptions. This overrides any default
attribution the assistant would add. It applies to every push by every teammate, and is checked
before any merge to `main`; a commit that breaks it is rewritten before merging. AI use is
disclosed in the README only.

## Where the build stands

Update this section whenever a checkpoint is reached. It is the only status line always in context.

- **Oct 15:** repo set up with guidelines. Contracts being agreed. Owners of B and C to be filled in.
- **Oct 15:** design extended to cover every focus of both tracks: MCP deep dive (G9), agent-written
  semantic facts (G10), concurrency burst proof (G11). Graph contract additions (`entity_facts`,
  `record_semantic_facts`, `record_agent_run` worker/tool_calls, MCP server) need B and C to ack.
- **Oct 15:** Workstream B owner named: Md Adnan Afzal.
- **Oct 15:** Workstream C owner named: Satya. All three owners now set.
- **Oct 16:** UI spec written (`docs/UI_PAGES.md`). Contract gaps GAP-1…7 found and logged
  (`docs/CONTRACT_GAPS.md`); waiting for acks. Login decided: hard-coded demo users for the
  hackathon, real login later. Agents (A) not started yet; B building on `b/graph-foundation`.
- **Oct 16 (A, on `a/agents-talos`):** Talos verified (all scenarios matched). Built: Talos image
  (`deploy/talos/Dockerfile`, pinned commit, LLM off), ingestor (`argus-ingest`), Triage /
  Investigator / Responder / runner (`argus-agents`), learning (`on_feedback(tenant, case_id,
  feedback_id)`), LLM client (Anthropic or OpenAI) and MCP deep dive, scenario logs
  (`data/scenarios/`, `scripts/replay_scenario.py --reset/--burst/--demo`). GAP-5/6 done on A's
  side. B merged into A; B's real graph functions all done. Backend checkpoint met: scenarios
  1–6 and the 31-alert concurrency burst pass end to end on the live stack
  (`ARGUS_E2E=1 pytest tests/e2e`, see `tests/e2e/conftest.py`). Next: C's API and UI on top.
- **Next checkpoint:** scenario 1 end to end including the UI (approve in the UI).
- **Decided Oct 16:** agents are plain Python (no framework); LLM is Anthropic or OpenAI, chosen
  in `.env` (LLD §6.8); one shared Talos, reports routed to tenants by host (LLD §5.4).
- **Windows note:** Compose v5 `up --build` fails ("additional privileges requested"); build with
  `docker build -f deploy/<x>.Dockerfile` and start with `docker compose up --no-build`.

## Reference

- `docs/design/Argus SOC — FalkorDB Hackathon Design.md` — data model, agents, memory, Cypher queries, demo script.
- `docs/design/Argus SOC — Task Split.md` — task lists per workstream, interface contracts, day plan.
- `docs/design/Argus SOC with Talos.html` — animated walkthrough; how Talos works.
- `docs/UI_PAGES.md` — every UI page, field by field, with the API call behind it.
- `docs/CONTRACT_GAPS.md` — open contract gaps (GAP-1…7), who does what, status.
