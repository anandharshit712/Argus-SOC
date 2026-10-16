# Argus SOC — Live Demo Harness Design

Decided details for the **live** demo: a small, deliberately attackable environment that feeds
Talos continuously, so a case moves through Argus (Triage → Investigator → Responder → analyst)
without anyone pressing `talos replay`. Replay stays as the backup path for the video.

Status: **design agreed (Oct 17, 2026), not yet built.** Build only after scenario 1 runs end to
end, and time-box it (see §9).

Owner: **A — Harshit** (agents + Talos integration). The demo site may reuse C's UI styling, and
the demo hostnames must match B's inventory seed (§4).

---

## 1. Why a live harness, and how it differs from replay

Replay proves Talos works. A live harness proves the **whole system** works: a judge opens the
URL, real traffic hits a real page, logs stream into Talos as they are written, Talos raises an
incident when something crosses a threshold, and Argus picks it up and runs the case. It also
gives the learning scenario a natural home (the scheduled scanner runs on its own; mark one run
benign; the next run auto-closes while people watch) and supports an "always running" story.

| | Replay (existing) | Live harness (this doc) |
|---|---|---|
| Source of logs | static files, `talos replay` | real nginx/sshd logs, tailed live |
| Trigger | you run a command | traffic arrives on its own / on a button |
| What it shows | Talos detection | end-to-end Argus pipeline, live |
| Role | backup for the video | main demo |

---

## 2. What Talos can detect live (the attack menu)

Everything below is already in Talos today — **no new detectors.** The attack-bot (§5) exercises
all of them.

| Campaign | Talos detector | Trigger threshold | Live? |
|---|---|---|---|
| Web login brute force | `brute_force_detector` (web) | ≥10 failures / one account / 120 s | yes |
| Credential stuffing | `credential_stuffing_detector` | ≥15 failures, ≥15 accounts / 300 s, ≤3 each | yes |
| SQL injection probe | `sql_injection_detector` | one actionable payload | yes |
| XSS probe | `xss_detector` | one actionable payload | yes |
| Broken access control | `deviation_scorer` (IDOR) | one user reaching another's record | yes |
| SSH brute force | `ssh_brute_force_detector` | ≥8 failures / host+account / 120 s | yes (internal target) |
| RDP brute force | `rdp_brute_force_detector` | ≥8 failures / host+account / 120 s | **replay only** |

"Network attack" in Talos means SSH/RDP login guessing only — not port scans or floods, so the
demo does not show those. RDP needs Windows Security events; without synthesizing those, RDP stays
on replay.

---

## 3. Architecture — extra containers in the same Compose project

The harness is added to the existing `argus-soc` Docker Compose project on the OCI instance, on
the internal `soc-net` network. **Only the demo web shop is public.** The SSH target is internal
only — a real login service is never exposed to password guessing.

```
Internet ── nginx(:443) ──► web_shop        (login, /api/search, account page)
                               │  writes nginx/WAF JSON access log (host: web-01)
                               ▼
                           shipper ── tails the log, parses with Talos's own
                               │        web parser, POSTs each event ──► talos(:8000) /events
                               ▼
                           talos ──► stores IncidentReport ──► (existing) ingestor polls /reports
                               │                                           ▼
                               │                                     FalkorDB ──► agents ──► api ──► ui
attack_bot (internal) ──┬─► web_shop  (HTTP campaigns, X-Forwarded-For spoofed source)
                        └─► ssh_target (SSH brute force, internal only)
```

New services:

| Service | What it is | Exposed |
|---|---|---|
| `web_shop` | tiny vulnerable demo site: login, product search (`/api/search?q=`), account page | via nginx |
| `ssh_target` | throwaway SSH box, one dummy account, internal network only | no |
| `attack_bot` | the randomized attack simulator + self-check log (§5) | no |
| `shipper` | tails web_shop (and sshd) logs, runs Talos's parser, POSTs to Talos `/events` | no |

---

## 4. Changes required

### Talos — none

`talos serve` already accepts one event at a time on `POST /events`, and its parsers already read
lines one by one. The only new piece is the **shipper**, a ~40-line service that follows the log
files (like `tail -F`), runs each line through Talos's existing web/network parser, and POSTs the
event. That is a new service, not a change to Talos. No batching needed at demo volumes; send in
order so the windowed detectors stay correct.

### Argus — almost none

- Make sure the demo hostnames (`web-01`, `bastion-01`, etc.) are in **B's inventory seed**, so
  cases map to the right tenant.
- Make the **UI auto-refresh** (poll) so live cases appear without a manual reload.

The ingestor already polls `/reports`; nothing else changes.

---

## 5. The attack-bot (randomized simulator)

One container, one script (`httpx` + `paramiko`), driven by a menu of campaigns. Purpose is two
things at once: drive the live demo, and **exercise Talos's full detector set** as a running mini
eval.

**Campaign menu** — each function produces exactly enough traffic to trip one detector, then
returns: web login brute force, credential stuffing, SQLi probe, XSS probe, broken access control,
SSH brute force. (RDP excluded — replay only.)

**Weighted-random scheduler**, not pure random — one campaign at a time so the story stays legible:

```
while running:
    campaign = weighted_choice(MENU)       # tune frequencies
    campaign.run(target=rotate_target())   # fresh account/host/IP each run
    sleep(random.uniform(45, 180))         # jitter
```

Benign traffic runs continuously on a separate thread underneath, so attacks sit in normal noise.

**Target rotation is mandatory.** Talos suppresses a repeat of the same signature for 1 h unless
the attack escalates. Each campaign pulls a fresh account/host/IP from a pool so every run is a new
signature — otherwise the second run of a campaign produces no incident and the demo looks dead.

**Two modes, one script:**

- **Demo mode** — one clean attack on demand (a button / `/launch?attack=sqli`), spaced out, for
  the live walkthrough and the video.
- **Soak / chaos mode** — the weighted-random loop, for the always-running story and for hammering
  Talos.

**Self-check log (the "test Talos" part).** Each campaign knows the incident it should produce.
After launching, it polls Talos `/reports` (or Argus cases) for a few seconds and records hit/miss
+ latency:

```
14:32:07  launched: sqli         -> expected injection/high    -> DETECTED (inc-4f2a, 3.1s)
14:34:51  launched: login_brute  -> expected auth_failure/med  -> DETECTED (inc-91c7, 2.4s)
14:37:20  launched: xss          -> expected injection/high     -> MISSED
```

That turns the simulator into a live scoreboard of what Talos caught, how fast, and what it
missed — a genuine thing to show judges, and it doubles as the harness's test.

---

## 6. Source IP handling

- **Web:** inside Docker every request looks like it came from a `172.x` gateway address, which
  breaks the cross-signal link (the same `203.0.113.7` hitting both the web shop and `bastion-01`)
  that is the best graph moment. Fix: the bot sets `X-Forwarded-For` to the documentation-range
  IPs from the scenario spec; nginx trusts that header **only** from the attack_bot container's IP,
  never from the public internet. Label these as simulated sources in the README.
- **SSH:** no such header, so a live SSH brute force shows the bot's internal IP. Note this as a
  known demo limitation, or keep SSH on replay where the IPs are already correct.

---

## 7. Repo layout

The harness lives **inside the Argus-SOC repo**, not a separate repo — the deployment is one
Compose project, the bot needs the internal SSH target, and the shipper feeds the Talos container
already in that compose file. One `git clone`, one `docker compose up`.

```
Argus-SOC/
  ingestor/ agents/ graph/ api/ ui/ core/   # existing
  deploy/                                     # existing compose, nginx, dockerfiles
  demo/                                       # the live demo harness
    web_shop/      # vulnerable demo site
    ssh_target/    # throwaway SSH box, dummy account
    attack_bot/    # randomized simulator + self-check log
    shipper/       # tails logs, feeds Talos
    docs/          # this doc
    README.md      # how to run; states it only targets the bundled demo containers
```

The attack_bot and its payloads stay behind `demo/`, and the README states plainly that it only
targets the bundled demo containers on the internal network — so it reads as a self-contained test
harness, not a general tool. If wanted standalone later, `git subtree split` extracts `demo/` in
minutes.

---

## 8. Effort estimate

| Piece | Rough effort |
|---|---|
| Demo site (login, search, account) + nginx JSON access log | 2–3 hrs |
| SSH target container (dummy account, internal only) | 1–2 hrs |
| Shipper (tails logs → Talos `/events`) | ~2 hrs |
| attack_bot: campaigns + weighted scheduler + rotation + self-check log | 3–4 hrs |
| Compose wiring + end-to-end test | 2–3 hrs |

About **1–1.5 days** for one person with Claude Code; less if split across the team.

---

## 9. Open items, gotchas, guardrails

- **Build order / time-box.** Start only after the replay run of scenario 1 works end to end. Keep
  the harness to ~half a day of focus. **Keep replay as the backup for the video** — live demos
  fail at the worst moment.
- **Suppression.** Covered by target rotation (§5); also don't let a judge re-fire the same
  campaign within a minute (disable the button briefly, or vary the target).
- **Case pile-up during judging.** Rate-limit attacks; give the UI a filter or a reset.
- **Real internet bots** will hit the public page too — realistic noise, but uncontrolled.
- **RDP** stays on replay unless Windows events are synthesized.
- **Guardrail.** Everything the bot sends is the same traffic already specified in
  `testing/TALOS_TEST_SCENARIOS_SPEC.md`, now sent live against the bundled, disposable demo
  targets on the internal network. Nothing points outside the Compose project.

---

## 10. Next step

Hand a build spec + Claude Code prompt (the four `demo/` services, the compose wiring, and the
self-check log) to Claude Code, targeting the layout in §7. Not yet written.
