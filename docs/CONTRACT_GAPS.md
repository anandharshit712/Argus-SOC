# Argus SOC — Contract gaps (found Oct 16)

While writing `docs/UI_PAGES.md` we checked every UI screen against the frozen contracts
(`graph_schema.py`, the graph tool signatures in `LLD.md` §4, and `api_models.py` in `LLD.md` §7).
Seven gaps came out of that check, plus one design decision (hard-coded login). This file is the
detailed version; `CLAUDE.md` carries the short list so every Claude Code session sees it.

**Status of every gap: PROPOSED — not yet acked by the team.** Contracts are frozen (rule A11),
so nobody changes `graph_schema.py`, `read_queries.py` / `write_queries.py` signatures or
`api_models.py` for these until the owners named in each row have agreed in the team chat.
When a gap is agreed, change its status here to **AGREED (date)**, make the code change in a
pull request that also updates the docs listed under "Docs to update", and mark it **DONE**.

How to read the owner columns: **A** = Harshit (agents + Talos), **B** = Md Adnan Afzal
(database and graph), **C** = Satya (UI, API and submission).

---

## Summary

| ID | Gap | Proof it blocks | A | B | C | Status |
|---|---|---|---|---|---|---|
| GAP-1 | No login / session endpoints; hard-coded demo users not defined | Sign in page; analyst name on feedback | — | settings fields (shared core) | endpoints, guard, models, UI | PROPOSED |
| GAP-2 | `ActivityItem` has no `worker` | G11 concurrency proof | — | return it from `list_activity`, `get_case` | add to model, show in UI | PROPOSED |
| GAP-3 | `ActivityItem` has no `tool_calls` | G9 MCP tool selection proof | — | return it from `list_activity`, `get_case` | add to model, show in UI | PROPOSED |
| GAP-4 | `CaseDetail.feedback` is an untyped `list[dict]` | Feedback history | — | return fixed fields from `get_case` | typed model | PROPOSED |
| GAP-5 | The priority before the Responder lowered it is not stored | G3 "high → medium" on screen | pass it in `DecisionInput` | property on `Decision`, `record_decision` | `DecisionOut.previous_priority` | AGREED (Oct 16) · A, B DONE · C to do |
| GAP-6 | `findings` keys are not typed in the API | Findings, Memory, Deep-dive panels | keep the key names from LLD §6.2–6.3 | — | typed optional model | AGREED (Oct 16) · A DONE · C to do |
| GAP-7 | `APPLIED` relationship (Case/Decision → Playbook) is in code but not in the docs | Q6 and auto-close citation | — | already in `graph_schema.py` on `b/graph-foundation` | — | DOCS ONLY |

Nothing here changes the agents' decision logic, the decision table or any Cypher query result
other than adding fields that are already stored.

---

## Decision: hard-coded login for the hackathon (HLD D13)

- Tenants and their analyst users are **hard-coded** for the hackathon. No user table, no sign
  up, no password reset, no roles.
- **Real login is a post-hackathon feature** (accounts in a database, hashed passwords, roles,
  per-tenant permissions managed in the UI).
- Tenants stay where they are: `ARGUS_TENANTS` in `.env` → `core/tenant_registry.py`.
- Demo users live in `.env` only (`ARGUS_DEMO_USERS`, JSON). Passwords never go in code or git;
  `.env.example` has placeholders.

| Username | Display name | Tenants | Used for |
|---|---|---|---|
| `acme.analyst` | Acme Analyst | `acme` | Scenarios 1–3 |
| `globex.analyst` | Globex Analyst | `globex` | Scenario 4 |
| `demo.admin` | Demo Admin | `acme`, `globex` | Tenant switcher in the demo (G7) |

**Where login data is stored**

| Data | Where | Notes |
|---|---|---|
| Demo users and passwords | `.env` on the server (`ARGUS_DEMO_USERS`) | Read by `core/settings.py` at startup |
| Token signing secret | `.env` (`ARGUS_SESSION_SECRET`) | Changing it signs everyone out |
| Session token | Browser `sessionStorage` | Closing the tab signs out |
| Analyst identity in the graph | `Feedback.analyst` (username string) | The only trace; no `Analyst` node, nothing else in FalkorDB |

The graph's `User` label is **not** for people using the UI. It holds accounts inside the
simulated company (`svc_deploy`, …) that the agents reason about. Don't put analysts there.

---

## GAP-1 — Login and session endpoints

**Problem.** `LLD.md` §7 has no auth endpoints and the API trusts `FeedbackIn.analyst` from the
browser. The live demo URL is public over HTTPS and can approve or reject cases.

**Change**

*Shared core (`core/settings.py`, currently on `b/graph-foundation`; tell all three):*

| Variable | Type / default | Notes |
|---|---|---|
| `ARGUS_DEMO_USERS` | JSON list, required | `[{"username","display_name","password","tenants":[...]}]`; every tenant must exist in `ARGUS_TENANTS` or startup fails (rule C9) |
| `ARGUS_SESSION_SECRET` | `SecretStr`, required, ≥ 32 chars | HMAC key for tokens |
| `ARGUS_SESSION_HOURS` | `int`, default `12` | Token lifetime |

*API (C), new file `src/argus_soc/api/auth_routes.py` and `src/argus_soc/api/session_tokens.py`:*

| Method + path | Request | Response | Errors |
|---|---|---|---|
| `POST /api/auth/login` | `LoginIn {username, password}` | `SessionOut {token, username, display_name, tenants, expires_at}` | 401 same message for unknown user and wrong password |
| `GET /api/auth/me` | bearer token | `MeOut {username, display_name, tenants}` | 401 bad or expired token |
| `POST /api/auth/logout` | bearer token | 204 | — (tokens are stateless) |

- Token: `base64(payload).hmac_sha256(payload)` with `payload = {username, exp}`; compare with
  `hmac.compare_digest`. No JWT library needed.
- A FastAPI dependency guards every `/api/{tenant}/…` route: 401 without a valid token, 403 when
  `tenant` is not in the user's list. `/api/health` and `/api/auth/login` stay open.
- `GET /api/tenants` returns only the caller's tenants.
- Feedback route: `analyst` is set from the token; the value in `FeedbackIn` is ignored (keep the
  field so the model doesn't change shape, or make it optional — decide when agreeing).
- Password check uses `hmac.compare_digest`; never log the password or token (rule in LLD §10).
- Mock mode (`ARGUS_API_MOCK=true`) still requires login, using the same demo users.

**Tests (C):** login ok / wrong password / unknown user; 401 without token; 403 on other tenant;
expired token; feedback stores the session username.

**Docs to update when done:** LLD §2, §7, §8; HLD §1, D13; DFD §8–§10; ARCHITECTURE §8;
`.env.example`; `FOLDER_STRUCTURE.md`.

---

## GAP-2 — `worker` on activity items

**Problem.** G11 is shown by "AgentRuns from both workers" in the activity feed. `AgentRun.worker`
is stored (LLD §4.1, written by `record_agent_run`), but `ActivityItem` in `api_models.py` has no
`worker`, so the UI can't show it.

**Change**

- B: `list_activity` and the `agent_runs` part of `get_case` include `worker` (and `None` for runs
  written without it).
- C: `ActivityItem.worker: str | None = None`.
- UI: worker column and worker filter on the Activity page; worker on the case timeline.

---

## GAP-3 — `tool_calls` on activity items

**Problem.** G9 is shown by the Investigator's MCP calls. They are stored on the AgentRun
(`tool_calls`) and in `findings.deep_dive`, but `ActivityItem` has no field for them.

**Change**

- B: `list_activity` and `get_case.agent_runs` return `tool_calls` (parsed from its JSON string)
  for Investigator runs.
- C: `ActivityItem.tool_calls: list[ToolCallOut] | None = None` with
  `ToolCallOut {tool: str, args: dict, result: str, why: str}` (tenant never included).
- UI: "N MCP calls" chip on Investigator items, linking to the case's Deep-dive panel.

---

## GAP-4 — Typed feedback on the case

**Problem.** `CaseDetail.feedback: list[dict]` — the UI can't rely on field names.

**Change**

- B: `get_case` returns each Feedback as `{id, verdict, note, analyst, created_at}`.
- C: `FeedbackItemOut {id: str, verdict: Literal["approve","reject","benign"], note: str,
  analyst: str, created_at: datetime}`; `CaseDetail.feedback: list[FeedbackItemOut]`.

---

## GAP-5 — Priority before the Responder lowered it

**Problem.** G3 says the agent can lower urgency (rule R4: high → medium). The Responder calls
`set_case_status(..., new_priority)`, which overwrites `Case.priority`; the old value is lost, so
the UI can only show "medium".

**Change**

- A: `responder_agent.run` puts the case's current priority in
  `DecisionInput.previous_priority` (always, even when unchanged). A hasn't started the agents
  yet, so build it this way from the start.
- B: `DecisionInput.previous_priority: Priority | None`; `record_decision` stores it on the
  `Decision` node; add `previous_priority` to the Decision row in LLD §4.1 and to
  `graph_schema.py` docs. Bump `SCHEMA_VERSION`.
- C: `DecisionOut.previous_priority: str | None`; the UI shows "high → medium" when it differs
  from the case priority.

**Status: AGREED (Oct 16, Harshit). B part DONE** on `b/graph-foundation`:
`DecisionInput.previous_priority: Priority | None = None` (optional, invalid values rejected);
`record_decision` stores it on the `Decision` node; `get_case` and `explain_decision` return it
in the decision (stub and FalkorDB alike; the stub's sample case 31 has `"high"`);
`SCHEMA_VERSION` = 2; tests cover R4 high → medium on both backends.
**A part DONE** on `a/agents-talos`: the Responder sends `previous_priority` on every decision
(the case's priority going into it); checked live in scenario 3 (high → medium).
Still to do: C adds `DecisionOut.previous_priority`.

---

## GAP-6 — Typed `findings`

**Problem.** `CaseDetail.findings: dict`. The keys are fixed only by the agent pseudo-code in
LLD §6.2 and §6.3.

**Keys (A keeps exactly these names):**

| Key | Written by | Shape |
|---|---|---|
| `recall` | Triage | `[{case_id, verdict, closed_at, note}]` |
| `facts` | Triage | `{hosts: {name: facts}, users: {...}, iocs: {...}}` (from `entity_facts`) |
| `linked` | Triage | `[incident_id]`: the case's other alerts (correlated with its oldest by a shared IOC or user) |
| `severity` | Triage | the case's most severe alert severity, before any memory raise |
| `memory_reasons` | Triage | `[str]`, why memory raised the priority one step, e.g. `"user svc_deploy is suspected compromised (case 1)"`; `[]` when not raised |
| `succeeded` | Investigator | `bool` |
| `path_to_crown_jewel` | Investigator | `bool` |
| `shortest_path` | Investigator | `[node name]` or `null` |
| `blast_radius` | Investigator | `[{host, criticality, accounts, reached_hosts, alerts}]` per IOC |
| `deep_dive` | Investigator | `[{tool, args, result, why}]`; `[]` when the LLM is off |

**Change**

- A: DONE (Oct 16). Keys exactly as above; `severity` and `memory_reasons` added by Triage
  (show `memory_reasons` as "Priority raised one step because of: …", UI_PAGES §4.7).
- C: `FindingsOut` Pydantic model with every key optional (cases fill in step by step);
  `CaseDetail.findings: FindingsOut`. Unknown keys allowed (`extra="allow"`), so the UI can show
  them raw.

---

## GAP-7 — `APPLIED` relationship missing from the docs (docs only)

`graph_schema.py` on `b/graph-foundation` adds `(Case)-[:APPLIED]->(Playbook)` and
`(Decision)-[:APPLIED]->(Playbook)`, needed by `close_case_auto` and `explain_decision` (Q6) to
cite the playbook. `ARCHITECTURE.md` §4 doesn't draw it yet. B adds it to the diagram and to
LLD §4.1 "Relationships" when `b/graph-foundation` merges. No code change.

---

## What each person does next

| Person | Action |
|---|---|
| **Harshit (A)** | DONE (Oct 16): GAP-5 and GAP-6 acked and built on `a/agents-talos` (`previous_priority` on every decision; findings keys as in GAP-6). |
| **Adnan (B)** | Ack GAP-1 (settings), GAP-2, GAP-3, GAP-4, GAP-5. Add the auth settings to `core/settings.py` and `.env.example`; return `worker`, `tool_calls` and typed feedback from the read functions; add `previous_priority` to `Decision`; draw `APPLIED` (GAP-7). |
| **Satya (C)** | Ack all. Build GAP-1 endpoints and guard; extend `api_models.py` (GAP-2…6) once acked; build the UI from `docs/UI_PAGES.md`. Until then, ship with the new fields hidden. |
