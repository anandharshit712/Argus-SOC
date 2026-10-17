"""Attack campaigns: just enough synthetic traffic to trip one Talos detector each.

Every campaign targets ONLY the bundled demo containers on the internal network. Volumes and
timings come from TALOS_TEST_SCENARIOS_SPEC.md §4 (the thresholds), sent live. Each campaign
returns the category/severity Talos should raise, so the self-check (bot.py) can score it.

Target rotation: each run pulls a fresh account/source IP so the Talos signature is new and the
1 h repeat suppression does not swallow the second run (DEMO_DESIGN §5).
"""

from __future__ import annotations

import itertools
import random
import time
from dataclasses import dataclass

import httpx

# Documentation-range source IPs (RFC 5737), spoofed via X-Forwarded-For (trusted only from this
# container). Never real addresses.
SOURCE_IPS = [f"203.0.113.{n}" for n in range(10, 60)] + [f"198.51.100.{n}" for n in range(10, 60)]
_ACCT = itertools.count(1)
SCRIPTED_UA = "argus-demo-bot/1.0"

# Injection campaigns rotate the endpoint, not the source IP: Talos's suppression signature
# includes affected_endpoints but NOT the source IP, so for an account-less injection a fresh
# endpoint is the only way the next run is a new signature instead of a suppressed duplicate.
# These must all be served and logged by the shop (web_shop/app.py).
INJECTION_ENDPOINTS = itertools.cycle(["/api/search", "/api/products", "/api/items"])

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


def _ip() -> str:
    return random.choice(SOURCE_IPS)


def _hdrs(ip: str) -> dict[str, str]:
    return {"X-Forwarded-For": ip, "User-Agent": SCRIPTED_UA}


def web_brute_force(client: httpx.Client, base: str) -> Expect:
    """>=10 failed logins against one account within 120 s -> auth_failure / medium."""
    ip = _ip()
    account = f"victim{next(_ACCT)}@mail.example"
    for _ in range(12):
        client.post(
            f"{base}/login",
            data={"username": account, "password": "wrong"},
            headers=_hdrs(ip),
        )
        time.sleep(random.uniform(0.3, 0.8))
    return Expect("auth_failure", "medium")


def credential_stuffing(client: httpx.Client, base: str) -> Expect:
    """>=15 distinct accounts, <=3 each, from one source within 300 s -> auth_failure."""
    ip = _ip()
    for _ in range(18):
        account = f"cust{next(_ACCT)}@mail.example"
        client.post(
            f"{base}/login",
            data={"username": account, "password": "wrong"},
            headers=_hdrs(ip),
        )
        time.sleep(random.uniform(0.2, 0.6))
    return Expect("auth_failure", "medium")


def sqli_probe(client: httpx.Client, base: str) -> Expect:
    """An actionable SQLi payload -> injection / high (WAF 403, did not succeed).

    Rotates the endpoint each run so a second sqli run within Talos's 1 h window is a new
    signature, not a suppressed duplicate.
    """
    ip = _ip()
    endpoint = next(INJECTION_ENDPOINTS)
    for q in SQLI_PROBES:
        client.get(f"{base}{endpoint}", params={"q": q}, headers=_hdrs(ip))
        time.sleep(random.uniform(0.4, 1.0))
    return Expect("injection", "high")


def xss_probe(client: httpx.Client, base: str) -> Expect:
    """An actionable XSS payload -> injection / high. Rotates the endpoint (see sqli_probe)."""
    ip = _ip()
    endpoint = next(INJECTION_ENDPOINTS)
    for q in XSS_PROBES:
        client.get(f"{base}{endpoint}", params={"q": q}, headers=_hdrs(ip))
        time.sleep(random.uniform(0.4, 1.0))
    return Expect("injection", "high")


# Registry used by bot.py. SSH lives in ssh_campaign.py (needs paramiko) and is added at runtime.
WEB_CAMPAIGNS = {
    "web_brute": web_brute_force,
    "cred_stuffing": credential_stuffing,
    "sqli": sqli_probe,
    "xss": xss_probe,
}

# Weights for soak/chaos mode -- one campaign at a time, weighted so the story stays legible.
WEIGHTS = {"web_brute": 3, "cred_stuffing": 2, "sqli": 2, "xss": 2, "ssh_brute": 3}
