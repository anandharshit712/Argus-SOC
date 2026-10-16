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

Each run rotates its account / source IP so Talos's 1 h repeat suppression does not hide the next
run of the same campaign.

## Known limits

- **SSH source IP** is the bot's internal container IP (no `X-Forwarded-For` for SSH) — web
  campaigns carry documentation-range IPs, SSH does not. See DEMO_DESIGN §6.
- **IDOR / broken access control** needs a 50-observation baseline per account before it fires, so
  it is not a one-shot demo campaign; `/api/orders/{id}` exists for a soak-mode warm-up only.
- **RDP** stays on replay (needs synthesized Windows Security events).
