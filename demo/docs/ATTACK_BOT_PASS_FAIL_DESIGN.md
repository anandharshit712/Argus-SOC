# Attack bot v2: random pass/fail campaigns, run until stopped

Status: **built and tested e2e** (Oct 17, 2026; branch `a/attack-bot-v2`). Phase 1 only — §10 (SSH
multi-IP) deferred. Extends [DEMO_DESIGN.md](DEMO_DESIGN.md) §5. Owner: Workstream A (demo harness).
No change to Talos or Argus.

**E2E result (Oct 17, local full stack):** every campaign's pass produces the Talos report with
`succeeded: true` and the §5 severity (web/cred High, SSH High, sqli/xss Critical); the sqli pass
reaches Argus as an Awaiting-approval R2 case. The WAF bypass is refused from any untrusted peer,
pool logins work, soak start/stop/no-op and the FalkorDB backlog count all behave as specified.
Observed gap (Argus decisioning, not the bot): the web_brute / ssh_brute passes decide on the
not-succeeded **threshold** report and close R4/R3 even though the succeeded escalation alert is
linked into the case — the "re-decide on late success" area tracked on `a/fix-live-e2e-bugs`.

**Decisions (Oct 17):**

- **Ratio:** exact per 10 runs: 3 passes in every 10, in random order.
- **Weights:** rebalanced (§5).
- **Multiple SSH source IPs (§10):** later, not part of this build.
- **Backlog pause:** soak pauses all attacks while more than 20 cases are Awaiting approval (§9a).

## 1. Goal

Today every attack-bot campaign fails on purpose: wrong passwords, made-up accounts, and a WAF that
answers `403` to every injection. Successful attacks only come from the hand-run helper
`local_tools/land.sh` on the VM.

v2 makes every campaign able to **fail or pass**:

- **Ratio:** fail 70 %, pass 30 %, exact over every 10 runs (so also over every 100).
- **Order:** random. Nobody can predict which run passes.
- **Lifetime:** in soak mode the bot runs until someone stops it.

A pass is a real success as Talos sees it (`aggregate_scope.succeeded = true`), so it reaches Argus
as R1 or R2 and waits for an analyst, exactly like a `land.sh` break-in.

## 2. What exists today (for reference)

| Piece | Today |
| --- | --- |
| `demo/attack_bot/bot.py` | `/launch?attack=<name>` (one campaign, blocks until scored), `/selfcheck` (last 100 runs), `/health`. Soak loop only when `DEMO_SOAK=1` at start; weights web_brute 3, ssh_brute 3, cred_stuffing 2, sqli 2, xss 2; 45 to 180 s between runs; benign shop searches always running |
| `demo/attack_bot/campaigns.py` | Web campaigns. Source IP random from 100 documentation IPs (`203.0.113.10–59`, `198.51.100.10–59`) via `X-Forwarded-For`; fresh account or endpoint each run to beat Talos's 1 h suppression |
| `demo/attack_bot/ssh_campaign.py` | 10 wrong passwords for a made-up account (`deploy7`, …) on `ssh_target` (`bastion-01`) |
| `demo/web_shop/app.py` | One valid account (`DEMO_VALID_ACCOUNT`). WAF regex returns `403` on SQLi/XSS shapes. Trusts `X-Forwarded-For` only from `attack_bot` |
| `demo/ssh_target/Dockerfile` | One account, `svc_deploy`, password from `SSH_TARGET_PASSWORD` |

## 3. Talos rules that shape the design

Taken from `testing/TALOS_TEST_SCENARIOS_SPEC.md` §4 and the Oct 16/17 live tests:

1. **Succeeded:**
   - Rate detectors (web brute force, credential stuffing, SSH brute force): `succeeded` is true
     when the detector's window key also holds a successful login at or after the first counted
     failure.
   - Injection: `succeeded` comes from the HTTP status. `200/201/202` → true; `403` → false.
2. **Severity:**
   - Starts at the category floor: injection High, auth_failure Medium, network_brute_force Medium.
   - **+1 if succeeded:** a passed injection is Critical, a passed login is High.
3. **Window keys:**

   | Detector | Key | Window | Threshold |
   | --- | --- | --- | --- |
   | web brute force | account | 120 s | 10 failures |
   | credential stuffing | source IP | 300 s | 15 failures, 15 accounts, max 3 failures each |
   | SSH brute force | host + account | 120 s | 8 failures |

4. **Repeat suppression (1 h):**
   - Talos records a report only if its signature is new, or it has escalated: newly succeeded, or
     attempts doubled.
   - The signature is (domain, category, techniques, accounts, hosts, endpoints). Source IP is
     **not** in it.
   - Consequence: a second success on the same account within 1 h is never reported. Every pass
     must use an account (or, for injections, an endpoint) not used in the last hour.
5. **One success after the threshold gives two incidents:** the "not succeeded" report at the
   threshold, then the escalation when the success arrives. Argus links them (same IP and account),
   so both land in one case.

## 4. Outcome draw: exactly 3 in every 10

A **shuffled bag**, not a coin flip. A 30 % coin flip gives anywhere from about 21 to 39 passes in
100 runs; the bag gives exactly 3 in every 10, in random order (and so exactly 30 in every 100).

- The bag holds `DEMO_BAG_SIZE` tokens (default **10**). `round(size × DEMO_PASS_RATIO)` of them
  are `pass` (default ratio 0.3), the rest `fail`. It is shuffled with `random.SystemRandom()`.
- Which runs pass is random, within the bag's limits:
  - at most 6 passes in a row: the last 3 of one bag, then the first 3 of the next;
  - at most 14 fails in a row: a bag whose 3 passes came first, then a bag whose 3 passes come
    last.
- Each soak run takes the next token. An empty bag is refilled and reshuffled.
- The outcome is drawn **independently of the campaign** (the campaign is still picked by
  `WEIGHTS`). Over 100 runs each campaign therefore passes about 30 % of the time, but not exactly.
- Manual runs choose their own outcome and do not consume a token:
  `/launch?attack=<name>&outcome=pass|fail|random`. `random` draws from the bag; the default is
  `fail`, which keeps today's behaviour.
- The bag lives in memory. A bot restart starts a fresh bag (the ratio is exact per bag, not across
  restarts).
- `DEMO_BAG_SIZE=100` gives exactly 30 in every 100 with longer possible streaks, if that is ever
  wanted.

## 5. Campaign changes

All campaigns keep their current shape. `outcome` only changes what happens after the threshold.

**New soak weights** (were web_brute 3, ssh_brute 3, cred_stuffing 2, sqli 2, xss 2):

| Campaign | Weight | Why |
| --- | --- | --- |
| `web_brute` | 3 | The clearest story: one IP, one account, a clean R2 pass |
| `sqli` | 2 | Unchanged; passes show Critical |
| `xss` | 2 | Unchanged |
| `ssh_brute` | 2 | Down from 3. Until §10 is built, all SSH shares one source IP, so SSH passes pile into one open case. Fewer SSH runs keep that pile small |
| `cred_stuffing` | 1 | Down from 2. Each run already makes 4–5 alerts |

| Campaign | Fail (today, unchanged) | Pass (new) | Talos incidents on a pass | Argus on a pass |
| --- | --- | --- | --- | --- |
| `web_brute` | 12 wrong logins on a made-up `victimN@mail.example` | 10–14 wrong logins on a **pool account**, then its right password | auth_failure Medium (not succeeded), then auth_failure High (succeeded) | R2 (web-01 has no crown-jewel path), Awaiting approval, High or Critical |
| `cred_stuffing` | 18 made-up accounts, 1 wrong login each | 17 made-up accounts with 1 wrong login each, plus 1 **pool account** that is first tried wrong once and then logs in with its right password, all from the same IP | 4 auth_failure Medium reports, then 1 escalation, succeeded, High | R2, Awaiting approval |
| `ssh_brute` | 10 wrong passwords on a made-up account | 8–11 wrong passwords on an **SSH pool account**, then its right password | network_brute_force Medium, then High succeeded | R1 (bastion-01 → app-02 → db-prod-01), Awaiting approval, High or Critical |
| `sqli` | 5 probes, all `403` | first 4 probes `403`, last probe let through: `200` | injection High (not succeeded), then injection Critical (succeeded) | R2, Awaiting approval, Critical |
| `xss` | 3 probes, all `403` | first 2 probes `403`, last probe `200` | injection High, then injection Critical | R2, Awaiting approval, Critical |

Notes:

- **Random failure counts:** the number of failures before a pass varies, so passes don't look
  scripted. It always stays at or above the threshold, so the "not succeeded" report always fires
  first.
- **Credential stuffing:**
  - The pool account's first failure counts toward the 15-account threshold (it is one of the 18).
  - It has 1 failure, under the 3-per-account limit, so the detector still fires.
  - The success, from the same source IP inside 300 s, marks the stuffing verdict succeeded.
- **Injections:** reaching the shop with a `200` is what Talos calls "succeeded". No real data
  is returned; the shop still answers `{"query": …, "results": []}`.

## 6. Account pools (so passes are never suppressed)

**Web shop pool:**

- Accounts `pool0001@shop.example` … `pool0500@shop.example`, all with the password
  `DEMO_POOL_PASSWORD`.
- `DEMO_VALID_ACCOUNT` keeps working for `land.sh` and hand demos.

**SSH pool:**

- Accounts `ops001` … `ops300` on `ssh_target`, created at image build with the password
  `DEMO_SSH_POOL_PASSWORD`.
- `svc_deploy` stays as it is for `land.sh`.

**Rotation:**

- The bot hands out pool accounts in a cycle, starting at a random index so two bot restarts don't
  replay the same names.
- At about 30 runs/hour and a 30 % pass rate, the bot needs about 9 pool accounts an hour. With 500
  web and 300 SSH accounts, no account repeats within the 1 h suppression window.

**Passwords:** both pool passwords come from `.env`. They are never logged; the shop already masks
passwords as `********`.

## 7. Letting an injection through

The WAF stays. It is bypassed only for one request the bot marks:

- **The marker:** the bot sends `X-Demo-Outcome: pass` on the last probe of a pass run.
- **Trust check:** `web_shop` honours the header only when the request comes from the trusted bot
  address. That is the same check that already guards `X-Forwarded-For` (`_trusted_proxy_ip()`).
- **From anyone else:** the header is ignored and the request still gets a `403`. The public shop
  behind nginx can never be told to let a payload through.
- **What happens:** when honoured, the shop skips the WAF for that request, logs a normal access
  line with status `200` and the real query, and returns the empty search result.

## 8. Running until stopped

Soak mode becomes something you switch on and off without restarting the container.

| Endpoint | Does |
| --- | --- |
| `POST /soak/start` | Starts the loop if it is not running. Optional `?interval_min=45&interval_max=180&ratio=0.3` |
| `POST /soak/stop` | Stops after the current campaign finishes (never mid-campaign) |
| `GET /soak/status` | `running`, runs so far, passes/fails so far, tokens left in the bag, the current campaign, and when the next run starts |
| `GET /health` | Also reports `mode: soak` or `demo` |

- **On start-up:** `DEMO_SOAK=1` in `.env` still starts the loop when the container boots, so it
  survives a VM reboot. `DEMO_SOAK=0` boots idle, waiting for `/soak/start`.
- **One loop:** a single `threading.Event` controls it. A second `/soak/start` is a no-op, so two
  loops can never run at once.
- **Failure handling:** if one campaign raises an error, the loop logs it and carries on, as today.
- **`/launch` while soak runs:** it waits for the shared campaign lock, so the story stays one
  attack at a time.

Commands on the VM:

```bash
curl -s -X POST localhost:8090/soak/start
curl -s localhost:8090/soak/status | python3 -m json.tool
curl -s -X POST localhost:8090/soak/stop
curl -s -X POST "localhost:8090/launch?attack=sqli&outcome=pass"
```

## 9. Self-check scoreboard

Each result row gains:

- `outcome`: `pass` or `fail`.
- `expected_severity`: from §5.
- `expected_succeeded`.

The poll changes for passes:

- **Fail run:** as today, the first new report of the category.
- **Pass run:** waits for the new report of that category with `aggregate_scope.succeeded = true`.
  The threshold report alone does not count as detected.
- **Timeout:** pass runs take longer (failures plus the success), so the self-check timeout rises
  from 20 s to 40 s for them.

`/selfcheck` adds totals, so the ratio and the detection rate can be checked at a glance:

- passes and fails run so far
- passes detected and fails detected
- the observed pass ratio

## 9a. Backlog pause: more than 20 cases awaiting approval

An unattended soak with 30 % passes can make 6–9 cases an hour that wait for an analyst. To stop
the queue from growing without limit, the soak loop pauses itself.

**Rule:**

- **Check:** before every soak run, the bot counts the cases in `awaiting_approval` for the demo
  tenant.
- **Pause:** if the count is **more than 20** (`DEMO_MAX_PENDING=20`), the loop pauses. No new
  campaign starts, pass or fail.
- **Resume:** it re-checks every 30 s. It resumes on its own when the count is 20 or less, so as
  soon as an analyst works one case off.
- **What keeps running:** benign shop traffic, because it never makes a case.
- **What is not paused:** manual `/launch`. Someone at the keyboard decides for themselves. Its
  answer carries a `warning` when the backlog is over the limit.
- **Turning it off:** `DEMO_MAX_PENDING=0`.

**How the bot counts (yes, this is possible):**

- The bot already sits on `soc-net` next to FalkorDB, which needs no login inside the network. It
  runs one read-only query on the tenant's graph:
  `MATCH (c:Case {status: 'awaiting_approval'}) RETURN count(c)`.
  - Graph: `tenant_<DEMO_TENANT>`, default `tenant_acme`.
  - Client: the `falkordb` Python package (same client Argus uses), added to the bot image.
- **Why not the Argus API:** it needs a signed-in session, so the bot would need an analyst login.
  A read-only graph count needs no credentials and does not touch Argus code.
- **If FalkorDB can't be reached:** the bot keeps running and logs a warning once per minute. A
  broken count must never stop the demo silently.

**Visibility:**

- `GET /soak/status` shows `paused: true`, `pending: 23`, `limit: 20` and since when.
- The bot logs one line when it pauses and one when it resumes.
- The self-check scoreboard is unaffected (no run, no row).

## 10. SSH from more than one source IP (phase 2, deferred)

**Decision (Oct 17):** later, not part of this build. Until then SSH passes behave as described in
§13.

**The problem:**

- Every SSH attempt comes from the bot container's one IP (`172.18.0.x`).
- In Argus all SSH alerts share that IOC, so:
  - while one SSH case is Awaiting approval, every later SSH run joins it instead of opening a new
    case;
  - one Mark benign verdict on any SSH case teaches a playbook that auto-closes every later SSH
    attack, passes included.
- With 30 % passes this becomes very visible: SSH passes would pile into a single case.

**Proposal:**

- **Reserve a slice of `soc-net`:** give `soc-net` an explicit subnet with an IPAM `ip_range`, so
  Docker allocates container IPs from the lower half only, and reserve 32 addresses from the upper
  half for the bot.
- **Add those addresses to the bot:** give the bot container `cap_add: [NET_ADMIN]`. At start it
  adds the reserved addresses to its `eth0` (`ip addr add …/32`).
- **Pick one per run:** each SSH run picks one at random and binds the paramiko socket to it as the
  source address. `sshd` then logs `from <that IP>`, and Talos and Argus see a different attacker
  per run.
- **Fallback:** if the addresses can't be added (no `NET_ADMIN`), log a warning and fall back to
  today's single IP.

**Cost:**

- It changes `soc-net`, so the whole stack restarts once.
- The addresses are private `172.x`, not documentation range. Argus keeps them as source IPs
  because they are not inventory hosts.

**Alternative:** accept the single IP and document it. Phase 1 works without this.

## 11. Configuration

| Variable (`.env`) | Default | Used by |
| --- | --- | --- |
| `DEMO_SOAK` | `0` | bot: start the loop at boot |
| `DEMO_PASS_RATIO` | `0.3` | bot |
| `DEMO_BAG_SIZE` | `10` | bot |
| `DEMO_MAX_PENDING` | `20` (`0` = off) | bot: backlog pause (§9a) |
| `DEMO_TENANT` | `acme` | bot: which graph the backlog count reads |
| `DEMO_SOAK_INTERVAL_MIN` / `_MAX` | `45` / `180` s | bot |
| `DEMO_POOL_PASSWORD` | none, required | bot, web_shop |
| `DEMO_WEB_POOL_SIZE` | `500` | bot, web_shop |
| `DEMO_SSH_POOL_PASSWORD` | none, required | bot, ssh_target (build arg) |
| `DEMO_SSH_POOL_SIZE` | `300` | bot, ssh_target (build arg) |
| `DEMO_SSH_SOURCE_IPS` | empty (phase 2) | bot |

If a required password is missing, the bot logs one error and runs fail-only: passes are skipped
with a reason in the scoreboard, never silently.

## 12. Files to change

| File | Change |
| --- | --- |
| `demo/attack_bot/bot.py` | Outcome bag, soak start/stop/status endpoints, `outcome` on `/launch`, scoreboard fields and totals, pass-aware poll, backlog pause (§9a), new weights |
| `demo/attack_bot/Dockerfile` | Add the `falkordb` client package |
| `demo/attack_bot/campaigns.py` | `outcome` parameter on each web campaign, web pool rotation, the pass sequences from §5, `X-Demo-Outcome` header |
| `demo/attack_bot/ssh_campaign.py` | `outcome` parameter, SSH pool rotation, pass sequence; phase 2: source-address binding |
| `demo/web_shop/app.py` | Pool accounts on `/login`, trusted `X-Demo-Outcome: pass` bypass on the search endpoints |
| `demo/ssh_target/Dockerfile` | Create the SSH pool accounts at build (build args for size and password) |
| `demo/docker-compose.demo.yml` | New env vars and build args; phase 2: `soc-net` IPAM range, `cap_add` |
| `.env.example` | The new variables, with a note that the passwords must be set |
| `demo/README.md`, `demo/docs/DEMO_DESIGN.md` | Campaign table with pass columns, soak endpoints, known limits updated |
| `demo/web_shop/test_waf.py` (+ new bot tests) | Bypass honoured only from the bot; pool login; bag gives exactly 30/100; stop never interrupts a campaign |

## 13. What Argus will show (expected, no Argus change)

At the default pacing (about 20–30 runs/hour) with 30 % passes:

- **Volume:** about 6–9 cases per hour wait for an analyst. The rest close themselves (R3/R4) or are
  auto-closed by a playbook.
- **Pass cases:**
  - they hold two alerts (the threshold report and the success), Critical or High;
  - web passes are R2 and SSH passes are R1, so the Path to Crown Jewel panel lights up.
- **Memory grows:**
  - pool accounts that passed become "suspected compromised";
  - approved IPs become malicious, so later attacks from the same random IP get +1 priority;
  - a known IP failing over SSH becomes R3 + Awaiting approval.
- **Credential stuffing passes:** Argus targets every account in the succeeded alert, so approval
  would "disable" all 18 stuffed accounts, not only the one that logged in. That is current Argus
  behaviour (it disables the users of succeeded alerts), and it is noted here so testers expect it.
- **Without phase 2:** SSH passes join one open SSH case while it awaits approval (see §10).

## 14. Acceptance checks

1. **Exact ratio:** every block of 10 soak runs from a fresh bag has exactly 3 `outcome: pass`
   (unit test with the interval at 0, plus a live soak of 20 runs).
2. **No pattern:** two soak sessions give a different pass order.
3. **Every pass is detected:** each pass run has a Talos report with `succeeded: true` and the
   severity from §5. Each fail run has its usual report.
4. **Argus decisions:** every detected pass becomes a case Awaiting approval (R1 or R2). Every fail
   behaves as in the manual test guide.
5. **Stop is clean:** `/soak/stop` during a campaign lets it finish and score, then no new run
   starts. `/soak/start` resumes. A second start does not create a second loop.
6. **Bypass is safe:** the public shop with `X-Demo-Outcome: pass` and a SQLi payload still gets
   `403`.
7. **No suppressed passes:** no pass is lost to suppression in a 2 h soak (needs pool rotation
   working).
8. **Backlog pause:**
   - With 21 cases Awaiting approval, soak starts no campaign and `/soak/status` shows `paused`.
   - Working one case off (down to 20) resumes it within about 30 s.
   - Manual `/launch` still runs, with a warning.
9. **Phase 2 (when built):** five SSH runs give five different source IPs in Argus.

## 15. Decisions (were open questions)

| Question | Decision (Oct 17) |
| --- | --- |
| Exact ratio per 100 or per 10? | Per 10 (`DEMO_BAG_SIZE=10`) |
| Change the campaign weights? | Yes: web_brute 3, sqli 2, xss 2, ssh_brute 2, cred_stuffing 1 (§5) |
| Build phase 2 (SSH source IPs) now? | Later |
| Pause on an approval backlog? | Yes: pause all soak attacks while more than 20 cases are Awaiting approval (§9a) |
