"""SSH brute-force campaign against the internal demo target (needs paramiko).

Rotates the guessed account each run (fresh host+account signature, beating Talos's 1 h
suppression). Known limitation: inside Docker the source IP is the bot's own container IP, so the
SSH attacker address is not a documentation-range IP the way web campaigns are (DEMO_DESIGN §6);
all SSH passes therefore pile into one open case until phase 2 (ATTACK_BOT_PASS_FAIL_DESIGN.md §10).
"""

from __future__ import annotations

import itertools
import os
import random
import time

import paramiko
from campaigns import Expect, pool_cycle

SSH_HOST = os.environ.get("DEMO_SSH_HOST", "ssh_target")
SSH_PORT = int(os.environ.get("DEMO_SSH_PORT", "22"))
_ACCT = itertools.count(1)

# Pool accounts that really log in on a pass (ssh_target makes ops001.. with the pool password).
SSH_POOL_PASSWORD = os.environ.get("DEMO_SSH_POOL_PASSWORD", "")
SSH_POOL_SIZE = int(os.environ.get("DEMO_SSH_POOL_SIZE", "300"))
SSH_POOL_READY = bool(SSH_POOL_PASSWORD)
_SSH_POOL = pool_cycle(SSH_POOL_SIZE, "ops{:03d}")


def _attempt(account: str, password: str) -> bool:
    """One SSH login attempt. True if it authenticated, False otherwise."""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(
            SSH_HOST,
            port=SSH_PORT,
            username=account,
            password=password,
            allow_agent=False,
            look_for_keys=False,
            timeout=5,
        )
        return True
    except paramiko.AuthenticationException:
        return False
    except Exception:  # noqa: BLE001 -- network hiccup, treat as a failed attempt
        return False
    finally:
        ssh.close()


def ssh_brute_force(_client: object, _base: str, outcome: str = "fail") -> Expect:
    """>=8 failed SSH logins against one host+account within 120 s -> network_brute_force / medium.

    Pass: 8-11 failures on a pool account, then its right password -> network_brute_force / high,
    succeeded (§5). Fail: 10 failures on a made-up account. A unique account each run (host+account
    is the Talos signature), so two runs within the 1 h suppression window never collide."""
    if outcome == "pass" and not SSH_POOL_READY:
        outcome, note = "fail", "pass skipped: DEMO_SSH_POOL_PASSWORD unset"
    else:
        note = None

    if outcome == "pass":
        account = next(_SSH_POOL)
        fails = random.randint(8, 11)
    else:
        account = f"{random.choice(['deploy', 'admin', 'root', 'ubuntu', 'git'])}{next(_ACCT)}"
        fails = 10

    for _ in range(fails):
        _attempt(account, "wrong-password")
        time.sleep(random.uniform(1.0, 2.5))

    if outcome == "pass":
        _attempt(account, SSH_POOL_PASSWORD)  # the real login that marks the brute force succeeded
        return Expect("network_brute_force", "high", succeeded=True)
    return Expect("network_brute_force", "medium", note=note)
