# Argus SOC — live demo harness

A small, deliberately attackable environment that feeds Talos continuously, so a case moves
through Argus (Triage → Investigator → Responder → analyst) live, without anyone running
`talos replay`. Replay stays the backup for the video. Design and rationale:
[docs/DEMO_DESIGN.md](docs/DEMO_DESIGN.md).

> **It only ever targets the bundled demo containers on the internal network.** It is a
> self-contained test harness, not a general attack tool. All source addresses are RFC 5737
> documentation ranges; all data is synthetic.

## Services

| Service | What it is | Exposed |
|---|---|---|
| `web_shop` | tiny FastAPI shop (`/login`, `/api/search`, `/api/orders/{id}`); writes nginx-JSON access logs | 127.0.0.1:8080 |
| `ssh_target` | throwaway sshd, one dummy account, host name `bastion-01` | internal only |
| `shipper` | tails the logs, parses with **Talos's own** parsers, POSTs to Talos `/events` | internal only |
| `attack_bot` | randomized campaigns + self-check scoreboard | 127.0.0.1:8090 |

No change to Talos. The shipper runs inside the pinned Talos image and uses its `WebLogParser` /
`NetworkLogParser` — the same path `talos replay` uses.

## Run

```bash
# 1. core stack (FalkorDB, Talos, ingestor, agents, API, UI)
docker compose --profile app up -d

# 2. demo harness
docker compose -f docker-compose.yml -f demo/docker-compose.demo.yml --profile demo up -d
```

On Windows, build first then start without `--build` (see root CLAUDE.md "Windows note").

## Drive it

```bash
# fire one campaign on demand (demo mode)
curl -X POST "http://127.0.0.1:8090/launch?attack=sqli"
#   attacks: web_brute | cred_stuffing | sqli | xss | ssh_brute

# the self-check scoreboard: what Talos caught, and how fast
curl http://127.0.0.1:8090/selfcheck

# always-running chaos loop instead of on-demand
DEMO_SOAK=1 docker compose -f docker-compose.yml -f demo/docker-compose.demo.yml --profile demo up -d attack_bot
```

## Campaigns and what Talos raises

| Campaign | Talos detector | Threshold | Expected incident |
|---|---|---|---|
| `web_brute` | web brute force | ≥10 fails / account / 120 s | auth_failure / medium |
| `cred_stuffing` | credential stuffing | ≥15 accounts / 300 s, ≤3 each | auth_failure / medium |
| `sqli` | SQL injection | one actionable payload (WAF 403) | injection / high |
| `xss` | XSS | one actionable payload | injection / high |
| `ssh_brute` | SSH brute force | ≥8 fails / host+account / 120 s | network_brute_force / medium |

Each run rotates the component that is actually in Talos's 1 h repeat-suppression signature, so
the next run of the same campaign is a new signature rather than a suppressed duplicate:

- `web_brute`, `ssh_brute` — a fresh **account** (brute-force signature is host + account).
- `cred_stuffing` — a fresh **set of accounts**.
- `sqli`, `xss` — a fresh **endpoint** (`/api/search` → `/api/products` → `/api/items` →
  `/api/catalog` → `/api/reviews` → `/api/deals`). Rotating
  the source IP would not help: the signature is (category, techniques, accounts, hosts,
  endpoints) and does **not** include source IP, and these payloads carry no account. `sqli` and
  `xss` never collide with each other (different technique). With six endpoints you get six
  sqli + six xss runs per hour before any repeat is suppressed.

## Known limits

- **SSH source IP** is the bot's internal container IP (no `X-Forwarded-For` for SSH) — web
  campaigns carry documentation-range IPs, SSH does not. See DEMO_DESIGN §6.
- **IDOR / broken access control** needs a 50-observation baseline per account before it fires, so
  it is not a one-shot demo campaign; `/api/orders/{id}` exists for a soak-mode warm-up only.
- **RDP** stays on replay (needs synthesized Windows Security events).
- **A second break-in on the same account within 1 h is not reported.** Talos reports a repeat
  signature again only when the attack succeeds or the attempts double; a success after an
  earlier *successful* report on that account is neither, so no incident and no case (live test
  Oct 17: 192.0.2.51 logged in after case 6, nothing raised). Talos is not changed in this
  project: use a different account for each hand-run break-in in a demo.
- **Self-check latency** is campaign start → Talos's `created_at` for the incident, so it
  includes the time the campaign takes to reach the detector's threshold.
