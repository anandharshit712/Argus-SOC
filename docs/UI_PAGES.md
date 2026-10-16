# Argus SOC — UI Pages

Every screen of the analyst UI: what it shows, where each value comes from, how it refreshes and
how it behaves when something goes wrong. This is the document Workstream C builds the UI from.
API shapes are in `LLD.md` §7 (`api_models.py`); page summary in `LLD.md` §8.

Owner: **C — Satya**. Changes to anything marked **contract** need a message to all three (A11).

---

## 0. At a glance

**5 pages + 1 app shell + 1 fallback page.**

| # | Page | Route | Purpose | Main API calls | Refresh |
|---|---|---|---|---|---|
| 1 | Sign in | `/login` | Pick a hard-coded demo user, get a session | `POST /api/auth/login` | — |
| 2 | Case queue | `/t/:tenant/cases` | All cases for the tenant, newest first | `GET /api/{tenant}/cases` | 3 s |
| 3 | Case detail | `/t/:tenant/cases/:caseId` | Why the agents decided what they did; analyst verdict | `GET /api/{tenant}/cases/{id}`, `POST …/feedback` | 3 s while the case is still moving |
| 4 | Playbooks | `/t/:tenant/playbooks` | What the system has learned, version by version | `GET /api/{tenant}/playbooks` | 10 s |
| 5 | Agent activity | `/t/:tenant/activity` | Live feed of agent steps, handoffs and workers | `GET /api/{tenant}/activity?since=` | 2 s |
| — | App shell | wraps 2–5 | Header, tenant switcher, nav, user menu, health banner | `GET /api/health`, `GET /api/auth/me` | health 10 s |
| — | Not found | `*` | Unknown route, unknown tenant, unknown case | — | — |

Default route after sign in: `/t/<first allowed tenant>/cases`.

**Which page proves which goal** (so the demo video can be planned around the screens):

| Goal (HLD §2) | Shown on |
|---|---|
| G1 multi-hop query decides, G2 algorithms as tools | Case detail → Path view, Host ranking, Linked alerts |
| G3 acts and can lower urgency | Case detail → Decision panel (actions, priority change) |
| G4 memory survives restart, G5 memory from feedback | Case detail → Feedback form → Playbooks → auto-closed case in Case queue |
| G6 handoffs through the graph | Agent activity, Case detail → Agent timeline |
| G7 tenant isolation | Tenant switcher; same IOC in Globex shows no history |
| G9 MCP tool selection | Case detail → Deep-dive panel |
| G10 semantic memory | Case detail → Memory panel (facts that raised priority) |
| G11 concurrency | Agent activity → Worker column / filter |

---

## 1. Sign in and sessions (hackathon version)

**Decision:** for the hackathon the tenants and their analyst users are **hard-coded**. There is
no user table, no sign-up and no password reset. Real login (accounts stored in the database,
hashed passwords, roles) is a **post-hackathon feature**.

### 1.1 Demo users

| Username | Display name | Tenants allowed | Used in demo for |
|---|---|---|---|
| `acme.analyst` | Acme Analyst | `acme` | Scenarios 1–3 |
| `globex.analyst` | Globex Analyst | `globex` | Scenario 4 |
| `demo.admin` | Demo Admin | `acme`, `globex` | Showing the tenant switcher (G7) |

- The list lives in the API's config, read from `.env` (`ARGUS_DEMO_USERS`, see 1.4). Passwords
  are never in code or git; `.env.example` lists the variable with placeholder values.
- The tenant list itself stays in `core/tenant_registry.py` (`acme`, `globex`).

### 1.2 Page 1 — Sign in (`/login`)

**Layout:** centred card, product name "Argus SOC" and one-line tagline, the form, and a small
note "Demo environment — synthetic data only".

| Element | Type | Rules |
|---|---|---|
| Username | text input | required; trimmed |
| Password | password input | required |
| Sign in | primary button | disabled while the request is in flight; shows a spinner |
| Error line | text under the form | "Wrong username or password" on 401; "Can't reach the server" on network error / 5xx |

**Behaviour**

1. `POST /api/auth/login` with `{username, password}`.
2. On 200: store the session (1.3), go to `/t/<tenants[0]>/cases`, or to the page the user was
   sent away from (`?next=`).
3. Visiting `/login` with a valid session goes straight to the case queue.
4. Never log or display the password; clear the field after a failed attempt.

### 1.3 Session in the browser

- Response of `POST /api/auth/login` (**contract, new**):
  `{token: str, username: str, display_name: str, tenants: list[str], expires_at: datetime}`.
- Store it in `sessionStorage` (closing the tab signs out). Wrap reads/writes in try/catch; if
  storage is unavailable keep it in memory for the tab.
- Send `Authorization: Bearer <token>` on every `/api/...` call except `/api/health` and
  `/api/auth/login`.
- On any **401**: clear the session and go to `/login?next=<current path>`.
- On **403** for a tenant: show "You don't have access to this tenant" and switch to the user's
  first allowed tenant.
- On load, `GET /api/auth/me` confirms the stored token is still valid (the API may have restarted
  with a new secret).

### 1.4 What the API needs for this (for the LLD update)

| Item | Detail |
|---|---|
| `ARGUS_DEMO_USERS` | JSON in `.env`: `[{"username","display_name","password","tenants":[...]}]` |
| `ARGUS_SESSION_SECRET` | Random string in `.env`; signs the token (HMAC). Changing it signs everyone out |
| `ARGUS_SESSION_HOURS` | Default `12` |
| `POST /api/auth/login` | `{username, password}` → session above; 401 on mismatch (same message for unknown user and wrong password) |
| `GET /api/auth/me` | → `{username, display_name, tenants}`; 401 if the token is bad or expired |
| `POST /api/auth/logout` | 204; the UI drops the token (tokens are stateless, so nothing is stored server side) |
| Guard on `/api/{tenant}/…` | 401 without a valid token; 403 when `tenant` isn't in the user's list |
| Feedback author | The API sets `FeedbackIn.analyst` from the session username; whatever the browser sends is ignored |

**Where login data is stored:** only in `.env` on the server (users) and in the browser's
`sessionStorage` (token). Nothing about analyst accounts is written to FalkorDB. The graph's `User`
label is for accounts inside the simulated company (e.g. `svc_deploy`), not for people using the
UI. The only analyst trace in the graph is the `analyst` username on each `Feedback` node.

---

## 2. App shell (all signed-in pages)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ ◉ Argus SOC   [Acme ▾]   Cases (3)  Playbooks  Activity        ● Live  AA ▾ │
├──────────────────────────────────────────────────────────────────────────────┤
│ ⚠ Graph database unreachable — retrying…            (only when health fails) │
├──────────────────────────────────────────────────────────────────────────────┤
│                                 page content                                 │
└──────────────────────────────────────────────────────────────────────────────┘
```

| Element | Shows | Source | Behaviour |
|---|---|---|---|
| Product mark | "Argus SOC" | static | Links to the case queue |
| Tenant switcher | Current tenant name (Acme / Globex) | session `tenants` (intersected with `GET /api/tenants`) | Hidden when the user has one tenant. Switching keeps the same page type (`/t/globex/cases`) but never carries a case id across tenants |
| Tenant colour chip | A distinct accent per tenant | static map | Makes it obvious on video which tenant is on screen (G7) |
| Nav: Cases | Link + badge with count of `awaiting_approval` cases | from the queue poll | Badge hidden at 0 |
| Nav: Playbooks, Activity | Links | — | Active link underlined |
| Live indicator | "● Live" / "○ Paused" | polling state | Click to pause/resume all polling (useful when recording) |
| User menu | Initials → display name, username, "Sign out" | session | Sign out → `POST /api/auth/logout`, clear storage, go to `/login` |
| Health banner | Red bar under the header | `GET /api/health` every 10 s, and any 503 | Shown when `falkordb: false` or a call returns 503. Pages keep their last data, greyed, and keep polling |
| Toasts | Short confirmations and errors | — | Bottom-right, auto-hide after 5 s |

**Mock mode:** when the API runs with `ARGUS_API_MOCK=true`, `GET /api/health` returns
`{status: "mock", ...}`; show a small "MOCK DATA" tag next to the product mark.

---

## 3. Page 2 — Case queue (`/t/:tenant/cases`)

**Purpose:** see every case for the tenant at a glance; spot the ones waiting for a human.

**Data:** `GET /api/{tenant}/cases?status=&limit=100` → `list[CaseSummary]`, every 3 s.

### 3.1 Layout

```
Cases — Acme                                         [Search id/category]
[All] [Awaiting approval 2] [Open] [Closed] [Auto-closed]

 #   Priority   Status               Category            Alerts  Opened     Updated
 33  ▲ medium   ⟲ Auto-closed        auth_failure        1       10:42:05   10:42:06   by Playbook v2 (Case 32)
 31  ▲▲ high    ⏸ Awaiting approval  ssh_bruteforce      2       10:31:10   10:31:24   [Needs approval]
 30  ▼ low      ✓ Closed             sqli                1       10:20:01   10:20:15
```

### 3.2 Columns

| Column | Field | Display |
|---|---|---|
| # | `id` | Link to case detail |
| Priority | `priority` | Text + icon + colour (`critical`, `high`, `medium`, `low`, `info`); never colour alone |
| Status | `status` | Status pill (labels in §8.1) |
| Category | `category` | Talos category, monospace |
| Alerts | `alert_count` | Number |
| Opened | `opened_at` | Local time `HH:mm:ss`; full date in tooltip; "today"/date grouping not needed |
| Updated | `updated_at` | Relative ("12 s ago") with absolute time in tooltip |
| Flags | `needs_approval`, `auto_closed_by` | "Needs approval" amber badge; "by Playbook vN (Case M)" note when `auto_closed_by` is set |

### 3.3 Controls

| Control | Behaviour |
|---|---|
| Status tabs | All · Awaiting approval (`awaiting_approval`) · Open (`new`, `triaged`, `investigated`) · Closed (`closed`) · Auto-closed (`auto_closed`). Single-status tabs pass `status=` to the API; "Open" filters client side. Tab counts come from the "All" response |
| Search | Client-side filter on id and category |
| Sort | Default `updated_at` desc. Clicking Priority sorts by `critical > high > medium > low > info` |
| Row click | Opens case detail |

### 3.4 Live behaviour

- New cases slide in at the top with a 2 s highlight.
- A row whose status changed since the last poll flashes once.
- Keep scroll position and the selected tab across polls.

### 3.5 States

| State | What the user sees |
|---|---|
| Loading (first fetch) | 5 skeleton rows |
| Empty tenant | "No cases yet. Replay a scenario to see the agents work." |
| Empty filter | "No cases with this status." |
| 503 | Health banner; table keeps last data, greyed |

---

## 4. Page 3 — Case detail (`/t/:tenant/cases/:caseId`)

**Purpose:** the demo's main screen. One page answers "what happened, what did the agents find,
what did they decide, and why", then takes the analyst's verdict (HLD §8 Usability).

**Data:** `GET /api/{tenant}/cases/{case_id}` → `CaseDetail`. Poll every 3 s while `status` is
`new`, `triaged` or `investigated`; stop once it reaches `awaiting_approval`, `closed` or
`auto_closed` (resume after a feedback POST).

### 4.1 Layout (top to bottom; two columns on wide screens)

```
← Cases   Case #31   ▲▲ high   ⏸ Awaiting approval   ssh_bruteforce · 2 alerts · opened 10:31:10
[ Progress: Triage ✓ → Investigator ✓ → Responder ✓ → Analyst ● ]

┌─ Decision (R1) ─────────────────────────┐ ┌─ Path to crown jewel ───────────────┐
│ Isolate bastion-01 · Disable svc_deploy │ │ (bastion-01)──▶(app-02)──▶(db-prod-01★)│
│ · Block 203.0.113.7                     │ │  Host          Host        Host     │
│ Why: … explanation …                    │ └─────────────────────────────────────┘
│ Talos suggested: …                      │ ┌─ Host ranking ──────────────────────┐
│ [Approve] [Reject] [Mark benign]        │ │ bastion-01 ████████ 0.82 …           │
└─────────────────────────────────────────┘ └─────────────────────────────────────┘
Findings · Memory · Linked alerts · Deep dive · Alerts & evidence · Agent timeline · Feedback
```

### 4.2 Header

| Element | Field | Notes |
|---|---|---|
| Back link | — | Returns to the queue with its previous tab |
| Case number | `id` | |
| Priority, status | `priority`, `status` | Same pills as the queue. If the Responder lowered priority (R4), show "high → medium" using the Responder's agent run summary |
| Meta line | `category`, `alert_count`, `opened_at`, `updated_at` | |
| Auto-closed note | `auto_closed_by` | "Auto-closed by Playbook v2, learned from Case 32" with a link to the playbook and the source case |
| Progress strip | `status` + `agent_runs` | Four steps: Triage → Investigator → Responder → Analyst. Done = ✓, current = pulsing dot. Auto-closed cases show Triage → "Playbook" and stop |

### 4.3 Decision panel (`decision`, may be `null`)

| Element | Field | Display |
|---|---|---|
| Rule | `rule_id` | Chip "R1" with tooltip of the rule (`R1` succeeded + path, `R2` succeeded + no path, `R3` failed + path, `R4` failed + no path) |
| Actions | `actions` | One line per action with its target, e.g. "Isolate host bastion-01". All actions are simulated: add a small "simulated" tag (A10) |
| Approval | `needs_approval` | "Needs analyst approval" or "Applied automatically" |
| Reason | `reason` | One sentence |
| Explanation | `explanation` | Paragraph(s), plain text |
| Outcome | `outcome` | `pending` / `approved` / `rejected` / `auto` pill |
| Talos suggested | `alerts[].talos_actions` (deduplicated) | Separate grey box labelled **"Talos suggested"** — never mixed with the agent's actions |
| No decision yet | — | "The agents are still working on this case" with the progress strip |

### 4.4 Path view (`decision.path`, or `findings.shortest_path` before a decision)

- Draw nodes left → right with arrows; label each node with `name`, and its `label` (Host / User)
  underneath, with a different shape per label (Host = rounded box, User = circle).
- Mark the last node as the crown jewel (★) when the path ends on one.
- Highlight nodes that are targets of the decision (e.g. the isolated host).
- Plain SVG is enough; a small graph library is optional.
- Empty: "No path to a crown jewel within 6 hops" — this is a meaningful result (scenario 3), so
  show it plainly, not as an error.

### 4.5 Host ranking (`decision.ranking`)

- Horizontal bar per host, highest first, score to 2 decimals.
- The top host gets an "isolation target" tag when `isolate_top_host` is in the actions.
- Tooltip: "Centrality in the case subgraph × criticality".

### 4.6 Findings panel (`findings`)

| Key | Display |
|---|---|
| `succeeded` | "Attack succeeded: Yes / No" (bold, red when yes) |
| `path_to_crown_jewel` | "Path to crown jewel: Yes / No" |
| `shortest_path` | Same nodes as the path view, as text: `bastion-01 → app-02 → db-prod-01` |
| `blast_radius` | Table per IOC: host, criticality, accounts, reached hosts, alerts |
| `recall` | See Memory panel |
| `facts` | See Memory panel |
| `linked` | See Linked alerts |
| `deep_dive` | See Deep-dive panel |
| Any other key | Collapsible raw JSON (read-only) so nothing is hidden |

### 4.7 Memory panel (`findings.recall`, `findings.facts`) — G4, G10

- **Past cases** (`recall`): rows of `case_id` (link), `verdict`, `closed_at`, `note`.
  Empty: "No earlier cases with these hosts, users or IOCs" — in Globex this is the tenant
  isolation proof (G7), so keep the wording exact and visible.
- **Known facts** (`facts`): per entity, e.g. "svc_deploy — suspected compromised (Case 31)",
  "bastion-01 — targeted in 3 cases", "10.0.5.20 — owner: internal pentest scanner".
- If priority was raised by memory, show "Priority raised one step because of: …" naming the fact.

### 4.8 Linked alerts (`findings.linked`)

- List of incident ids joined into this case by a shared IOC or user within the correlation
  window; each expands to the matching alert in §4.10.

### 4.9 Deep-dive panel (`findings.deep_dive`) — G9

- Only shown when the list is non-empty; otherwise a single muted line "Deep dive off (LLM
  disabled)" or "No extra tool calls".
- One numbered card per call: **tool** name, **args** (tenant hidden), **why** (the LLM's reason),
  **result** (truncated, expandable).
- Label the panel "Evidence only — the decision table does not read this".

### 4.10 Alerts and evidence (`alerts[]`)

| Field | Display |
|---|---|
| `incident_id` | Monospace, copy button |
| `category`, `severity`, `confidence` | Chips; confidence as a percentage |
| `succeeded` | Yes / No / Unknown (`null`) |
| `summary` | One line |
| `evidence` | Monospace list, up to 20 lines, each ≤ 500 chars; "Show all" toggle |
| `talos_actions` | Feeds the "Talos suggested" box in §4.3 |

**Security:** evidence and summaries are attacker-controlled log text. Render them as plain text
only — no `dangerouslySetInnerHTML`, no Markdown, no auto-linking.

### 4.11 Agent timeline (`agent_runs`)

- Vertical timeline, oldest first: time, agent, worker (when available), summary, "→ handed to X".
- Same item component as the Activity page (§6).

### 4.12 Feedback history (`feedback`)

- Rows: verdict pill, note (plain text), analyst username, time. Newest first.

### 4.13 Feedback form — G5

| Element | Rules |
|---|---|
| Buttons | **Approve** and **Reject**: only when `status = awaiting_approval`. **Mark benign**: when `status` is `awaiting_approval` or `closed` (the API allows benign on closed cases; that is what starts learning) |
| Note | Textarea, required for **Reject** and **Mark benign**, optional for Approve; 500-char limit with live counter |
| Analyst | Not an input. Shown as "Submitting as acme.analyst" from the session; the API takes it from the token |
| Confirm | Approve on an R1/R2 case asks once: "Approve isolate/disable/block on N targets? (simulated)" — in-page dialog, not `window.confirm` |
| Submit | `POST /api/{tenant}/cases/{id}/feedback` with `{verdict, note, analyst}`; buttons disabled while sending |
| Success | Toast "Feedback recorded". If `playbook_created` is set: green callout "Learned: Playbook vN created" linking to the Playbooks page. Re-fetch the case immediately |
| 409 | "This case is no longer waiting for approval" and re-fetch |
| 422 | Show the field error under the note |
| Hidden | Whole form hidden for `auto_closed` cases and while `decision` is null |

### 4.14 States

| State | What the user sees |
|---|---|
| Loading | Skeleton panels |
| 404 | Not-found page: "Case 99 doesn't exist in Acme" with a link back |
| Case from another tenant in the URL | Same 404 (the API never reveals other tenants' cases) |
| 503 | Health banner; last data greyed; form disabled |

---

## 5. Page 4 — Playbooks (`/t/:tenant/playbooks`) — G5

**Data:** `GET /api/{tenant}/playbooks` → `list[PlaybookOut]`, every 10 s.

### 5.1 Layout

Grouped by `name`; inside a group, versions newest first. The active version is expanded.

| Column | Field | Display |
|---|---|---|
| Name | `name` | Group header |
| Version | `version` | "v2" |
| Status | `active` | "Active" green pill; older versions "Superseded" grey |
| Condition | `condition` | Human sentence: "Category is `auth_failure` and IOC is one of `10.0.5.20`"; raw JSON in a toggle |
| Action | — | "Auto-close" (the only action for now) |
| Learned from | `source_case` | Link "Case 32" (or "—" when `null`) |
| Created | `created_at` | Local time |

### 5.2 States

- Empty: "Nothing learned yet. Mark a case as benign to teach the agents."
- New version since last poll: highlight the group for 3 s.

---

## 6. Page 5 — Agent activity (`/t/:tenant/activity`) — G6, G11

**Data:** `GET /api/{tenant}/activity?since=<ISO>` → `list[ActivityItem]`, every 2 s. First load
uses `since` = 30 minutes ago; afterwards `since` = the newest `at` already shown. Append new
items; de-duplicate by (`at`, `agent`, `case_id`, `summary`).

### 6.1 Feed item

```
10:31:24  Responder   @agents-2   Case #31   Decided R1: isolate bastion-01 …        (end)
10:31:18  Investigator @agents-1  Case #31   Path to db-prod-01 found …   → Responder
10:31:11  Triage      @agents-1   Case #31   Joined 2 alerts, priority high → Investigator
```

| Element | Field | Display |
|---|---|---|
| Time | `at` | `HH:mm:ss` |
| Agent | `agent` | Icon + colour per agent (Triage, Investigator, Responder, Learning) |
| Worker | `worker` (**contract gap**, §9) | `@agents-1`; hidden when missing |
| Case | `case_id` | Link to case detail; "—" when null |
| Summary | `summary` | Plain text |
| Handoff | `handed_to` | "→ Investigator" arrow chip |
| Tool calls | `tool_calls` (**contract gap**, §9) | "3 MCP calls" chip on Investigator items; click opens the case's deep-dive panel |

### 6.2 Controls

| Control | Behaviour |
|---|---|
| Agent filter | All / Triage / Investigator / Responder |
| Worker filter | All / each worker seen so far (proves two workers in the burst demo) |
| Case filter | Text box for a case id |
| Pause | Same as the header Live toggle |
| Auto-scroll | On by default; turns off when the user scrolls down, with a "N new" pill to jump back |

### 6.3 Side counters (small, top right)

- Steps in the last minute; per-worker step counts. Enough to show G11 on video without charts.

### 6.4 States

- Empty: "No agent activity in the last 30 minutes."
- Keep at most 500 items in memory; drop the oldest.

---

## 7. Not-found page

- Shown for unknown routes, unknown tenants (API 404) and unknown case ids.
- Message plus "Back to cases" link to the user's current tenant.

---

## 8. Shared building blocks

### 8.1 Status labels

| Value | Label | Icon | Colour family |
|---|---|---|---|
| `new` | New | ○ | neutral |
| `triaged` | Triaged | ◔ | blue |
| `investigated` | Investigated | ◑ | blue |
| `awaiting_approval` | Awaiting approval | ⏸ | amber |
| `closed` | Closed | ✓ | green |
| `auto_closed` | Auto-closed | ⟲ | purple |

### 8.2 Priority labels

`critical` ▲▲▲ red · `high` ▲▲ orange · `medium` ▲ yellow · `low` ▼ grey · `info` · grey.

### 8.3 Components to build

| Component | Used on |
|---|---|
| `AppShell` (header, nav, tenant switcher, user menu, health banner, toasts) | all signed-in pages |
| `RequireSession` route guard | all signed-in pages |
| `StatusPill`, `PriorityPill`, `VerdictPill`, `RuleChip` | queue, detail, playbooks |
| `CaseTable` | queue |
| `ProgressStrip` | detail |
| `DecisionPanel` (with "Talos suggested" box) | detail |
| `PathView` (SVG) | detail |
| `HostRanking` | detail |
| `FindingsPanel`, `MemoryPanel`, `LinkedAlerts`, `DeepDivePanel` | detail |
| `AlertCard` (plain-text evidence) | detail |
| `ActivityItem` | detail timeline, activity page |
| `FeedbackForm`, `FeedbackHistory` | detail |
| `PlaybookGroup` | playbooks |
| `EmptyState`, `SkeletonRows`, `ErrorState` | everywhere |

### 8.4 API client (`ui/src/api/`)

- One typed client generated or hand-written from `api_models.py`; base URL `/api` (nginx routes
  it; in dev, Vite proxies to `http://localhost:8080`).
- Adds the bearer token; maps 401/403/404/409/422/503 to the behaviours above.
- One polling hook (`usePoll(fn, intervalMs, enabled)`) shared by every page; pauses when the tab
  is hidden and when the header Live toggle is off.
- Timestamps from the API are ISO UTC; show them in the browser's local time.

### 8.5 General UI rules

- Desktop first (demo is on a laptop at 1440 px); must not break at 1024 px. Mobile is not needed.
- Dark theme by default (SOC look); readable contrast; never use colour as the only signal.
- Keyboard: tab order through the feedback form; Enter submits sign in.
- No data from the API is rendered as HTML.
- No calls to FalkorDB, Talos or any external host from the browser — only `/api` (D10).

---

## 9. Contract gaps to agree with the team

Tracked as GAP-1…GAP-6 in `docs/CONTRACT_GAPS.md` (rows 1–6 below, same order), with owners and status. These are not in `api_models.py` today. The UI can ship without them (fields hidden), but the
G9/G11 proofs look much better with them. Agree before changing the contract (A11, G3).

| # | Gap | Proposed change | Needed for |
|---|---|---|---|
| 1 | Auth endpoints and session model | Add §1.4 endpoints and `LoginIn`, `SessionOut`, `MeOut` models | Sign in |
| 2 | `ActivityItem` has no worker | Add `worker: str \| None` (already stored on `AgentRun`) | G11 worker column and filter |
| 3 | `ActivityItem` has no tool calls | Add `tool_calls: list[dict] \| None` (already stored on `AgentRun`) | G9 chip in activity |
| 4 | `feedback: list[dict]` has no fixed shape | `FeedbackOutItem {id, verdict, note, analyst, created_at}` | Feedback history |
| 5 | Priority change isn't a field | Add `previous_priority: str \| None` on `DecisionOut` | "high → medium" (G3) |
| 6 | `findings` is a free `dict` | Document the keys (`succeeded`, `path_to_crown_jewel`, `shortest_path`, `blast_radius`, `recall`, `facts`, `linked`, `deep_dive`) in `api_models.py` as an optional typed model | Findings, memory, deep-dive panels |

---

## 10. Demo walkthrough by screen

| Demo step (design doc) | Screen and what to point at |
|---|---|
| 1. Problem | Case queue with several Acme cases |
| 2. Lateral movement | Activity feed as Triage → Investigator → Responder hand off; then Case #31: path view, ranking, decision R1, explanation, "Talos suggested" box; Approve |
| 3. Session 1 benign | Scanner case → Mark benign with note "internal pentest scanner" → "Learned: Playbook v2" callout → Playbooks page |
| 4. Restart | `docker compose restart agents` in a terminal; UI keeps polling, Live dot stays on |
| 5. Session 2 | New case appears in the queue as Auto-closed "by Playbook v2 (Case 32)" |
| 6. Tenant B | Switch to Globex (as `demo.admin`): same IOC, Memory panel shows "No earlier cases…" |
| 7. Under the hood | Deep-dive panel (G9), activity worker filter during the burst (G11) |
