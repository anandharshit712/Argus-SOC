"""Attack campaigns: just enough synthetic traffic to trip one Talos detector each.

Every campaign targets ONLY the bundled demo containers on the internal network. Volumes and
timings come from TALOS_TEST_SCENARIOS_SPEC.md §4 (the thresholds), sent live. Each campaign
returns the category/severity/succeeded Talos should raise, so the self-check (bot.py) can score it.

Each campaign can **fail** (today's behaviour: wrong creds / WAF 403, never succeeds) or **pass**
(a real success as Talos sees it: a right login after the brute force, or an injection let through).
A pass reaches Argus as an Awaiting-approval case (ATTACK_BOT_PASS_FAIL_DESIGN.md §5).

Target rotation: each run pulls a fresh account/source IP so the Talos signature is new and the
1 h repeat suppression does not swallow the second run. Passes draw from the account pools (§6) so a
success is never suppressed as a repeat of an earlier success on the same account.
"""

from __future__ import annotations

import itertools
import os
import random
import time
from dataclasses import dataclass

import httpx

# Documentation-range source IPs (RFC 5737), spoofed via X-Forwarded-For (trusted only from this
# container). Never real addresses.
SOURCE_IPS = [f"203.0.113.{n}" for n in range(10, 60)] + [f"198.51.100.{n}" for n in range(10, 60)]
_ACCT = itertools.count(1)
SCRIPTED_UA = "argus-demo-bot/1.0"

# Pool accounts that really log in on a pass (web_shop honours DEMO_POOL_PASSWORD for pool####@...).
# A fresh pool account per pass keeps every success a new Talos signature (§6). An empty password
# means passes fall back to fail, with a reason in the scoreboard (§11).
POOL_PASSWORD = os.environ.get("DEMO_POOL_PASSWORD", "")
WEB_POOL_SIZE = int(os.environ.get("DEMO_WEB_POOL_SIZE", "500"))
WEB_POOL_READY = bool(POOL_PASSWORD)


def pool_cycle(size: int, fmt: str) -> itertools.cycle:
    """Pool account names, cycled, starting at a random index so two bot restarts do not replay
    the same names (§6). `fmt` is a format string taking the 1-based index, e.g. 'pool{:04d}@x'."""
    names = [fmt.format(i) for i in range(1, size + 1)]
    start = random.SystemRandom().randrange(size)
    return itertools.cycle(names[start:] + names[:start])


_WEB_POOL = pool_cycle(WEB_POOL_SIZE, "pool{:04d}@shop.example")

# Injection campaigns rotate the endpoint, not the source IP: Talos's suppression signature
# includes affected_endpoints but NOT the source IP, so for an account-less injection a fresh
# endpoint is the only way the next run is a new signature instead of a suppressed duplicate.
# These must all be served and logged by the shop (web_shop/app.py). One cycle per technique:
# a shared cycle let xss land on the endpoint its own previous run used (xss, sqli, sqli, xss),
# which Talos suppressed as a duplicate.
# Six endpoints = six runs of each per hour (live test Oct 17: three ran out in a long soak).
_ENDPOINTS = [
    "/api/search",
    "/api/products",
    "/api/items",
    "/api/catalog",
    "/api/reviews",
    "/api/deals",
]
SQLI_ENDPOINTS = itertools.cycle(_ENDPOINTS)
XSS_ENDPOINTS = itertools.cycle(_ENDPOINTS)

SQLI_PROBES = [
    "1'",
    "1' AND '1'='1",
    "1' AND '1'='2",
    "1' UNION SELECT NULL,NULL--",
    "1' UNION SELECT username,password FROM users--",
]
XSS_PROBES = [
    "<script>alert(1)</script>",
    '"><svg onload=alert(1)>',
    "<img src=x onerror=alert(1)>",
]


@dataclass
class Expect:
    category: str
    severity: str
    succeeded: bool = False
    note: str | None = None  # why a pass became a fail (missing pool password), for the scoreboard


def _ip() -> str:
    return random.choice(SOURCE_IPS)


def _hdrs(ip: str, outcome_pass: bool = False) -> dict[str, str]:
    h = {"X-Forwarded-For": ip, "User-Agent": SCRIPTED_UA}
    if outcome_pass:
        # web_shop honours this only from the trusted bot IP: skip the WAF for this one request
        # (§7). From anyone else it is ignored and the request still gets a 403.
        h["X-Demo-Outcome"] = "pass"
    return h


def _pool_fallback_note() -> str:
    return "pass skipped: DEMO_POOL_PASSWORD unset"


def web_brute_force(client: httpx.Client, base: str, outcome: str = "fail") -> Expect:
    """>=10 failed logins against one account within 120 s -> auth_failure / medium.

    Pass: 10-14 failures on a pool account, then its right password -> auth_failure / high,
    succeeded (§5). Fail: 12 failures on a made-up victim account."""
    ip = _ip()
    if outcome == "pass" and not WEB_POOL_READY:
        outcome, note = "fail", _pool_fallback_note()
    else:
        note = None

    if outcome == "pass":
        account = next(_WEB_POOL)
        fails = random.randint(10, 14)
    else:
        account = f"victim{next(_ACCT)}@mail.example"
        fails = 12

    for _ in range(fails):
        client.post(
            f"{base}/login", data={"username": account, "password": "wrong"}, headers=_hdrs(ip)
        )
        time.sleep(random.uniform(0.3, 0.8))

    if outcome == "pass":
        client.post(
            f"{base}/login",
            data={"username": account, "password": POOL_PASSWORD},
            headers=_hdrs(ip),
        )
        return Expect("auth_failure", "high", succeeded=True)
    return Expect("auth_failure", "medium", note=note)


def credential_stuffing(client: httpx.Client, base: str, outcome: str = "fail") -> Expect:
    """>=15 distinct accounts, <=3 each, from one source within 300 s -> auth_failure.

    Pass: 17 made-up accounts (1 wrong login each) plus 1 pool account tried wrong once then logged
    in with its right password, all from the same IP -> auth_failure / high, succeeded (§5).
    Fail: 18 made-up accounts, 1 wrong login each."""
    ip = _ip()
    if outcome == "pass" and not WEB_POOL_READY:
        outcome, note = "fail", _pool_fallback_note()
    else:
        note = None

    made_up = 17 if outcome == "pass" else 18
    for _ in range(made_up):
        account = f"cust{next(_ACCT)}@mail.example"
        client.post(
            f"{base}/login", data={"username": account, "password": "wrong"}, headers=_hdrs(ip)
        )
        time.sleep(random.uniform(0.2, 0.6))

    if outcome == "pass":
        pool_account = next(_WEB_POOL)  # 1 failure (under the 3-per-account limit), then success
        client.post(
            f"{base}/login",
            data={"username": pool_account, "password": "wrong"},
            headers=_hdrs(ip),
        )
        time.sleep(random.uniform(0.2, 0.6))
        client.post(
            f"{base}/login",
            data={"username": pool_account, "password": POOL_PASSWORD},
            headers=_hdrs(ip),
        )
        return Expect("auth_failure", "high", succeeded=True)
    return Expect("auth_failure", "medium", note=note)


def sqli_probe(client: httpx.Client, base: str, outcome: str = "fail") -> Expect:
    """An actionable SQLi payload -> injection / high (WAF 403, did not succeed).

    Pass: the first probes 403, the last let through (200) via the X-Demo-Outcome header ->
    injection / critical, succeeded (§5). Rotates the endpoint each run (see module docstring)."""
    ip = _ip()
    endpoint = next(SQLI_ENDPOINTS)
    last = len(SQLI_PROBES) - 1
    for i, q in enumerate(SQLI_PROBES):
        passing_probe = outcome == "pass" and i == last
        client.get(f"{base}{endpoint}", params={"q": q}, headers=_hdrs(ip, passing_probe))
        time.sleep(random.uniform(0.4, 1.0))
    if outcome == "pass":
        return Expect("injection", "critical", succeeded=True)
    return Expect("injection", "high")


def xss_probe(client: httpx.Client, base: str, outcome: str = "fail") -> Expect:
    """An actionable XSS payload -> injection / high. Pass lets the last probe through (200) ->
    injection / critical, succeeded. Rotates the endpoint (see sqli_probe)."""
    ip = _ip()
    endpoint = next(XSS_ENDPOINTS)
    last = len(XSS_PROBES) - 1
    for i, q in enumerate(XSS_PROBES):
        passing_probe = outcome == "pass" and i == last
        client.get(f"{base}{endpoint}", params={"q": q}, headers=_hdrs(ip, passing_probe))
        time.sleep(random.uniform(0.4, 1.0))
    if outcome == "pass":
        return Expect("injection", "critical", succeeded=True)
    return Expect("injection", "high")


# Registry used by bot.py. SSH lives in ssh_campaign.py (needs paramiko) and is added at runtime.
WEB_CAMPAIGNS = {
    "web_brute": web_brute_force,
    "cred_stuffing": credential_stuffing,
    "sqli": sqli_probe,
    "xss": xss_probe,
}

# Soak weights (ATTACK_BOT_PASS_FAIL_DESIGN.md §5). Down from web_brute 3 / cred_stuffing 2 /
# sqli 2 / xss 2 / ssh_brute 3: ssh_brute 2 (all SSH shares one source IP until phase 2, so passes
# pile into one case), cred_stuffing 1 (each run already makes 4-5 alerts).
WEIGHTS = {"web_brute": 3, "cred_stuffing": 1, "sqli": 2, "xss": 2, "ssh_brute": 2}
