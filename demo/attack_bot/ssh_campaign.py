"""SSH brute-force campaign against the internal demo target (needs paramiko).

Rotates the guessed account each run (fresh host+account signature, beating Talos's 1 h
suppression). Known limitation: inside Docker the source IP is the bot's own container IP, so the
SSH attacker address is not a documentation-range IP the way web campaigns are (DEMO_DESIGN §6).
"""

from __future__ import annotations

import itertools
import os
import random
import time

import paramiko
from campaigns import Expect

SSH_HOST = os.environ.get("DEMO_SSH_HOST", "ssh_target")
SSH_PORT = int(os.environ.get("DEMO_SSH_PORT", "22"))
_ACCT = itertools.count(1)


def ssh_brute_force(_client: object, _base: str) -> Expect:
    """>=8 failed SSH logins against one host+account within 120 s -> network_brute_force.

    A unique account each run (host+account is the Talos signature), so two runs within the 1 h
    suppression window never collide.
    """
    account = f"{random.choice(['deploy', 'admin', 'root', 'ubuntu', 'git'])}{next(_ACCT)}"
    for _ in range(10):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(
                SSH_HOST,
                port=SSH_PORT,
                username=account,
                password="wrong-password",
                allow_agent=False,
                look_for_keys=False,
                timeout=5,
            )
        except paramiko.AuthenticationException:
            pass  # expected: every guess fails
        except Exception:  # noqa: BLE001 -- network hiccup, keep guessing
            pass
        finally:
            ssh.close()
        time.sleep(random.uniform(1.0, 2.5))
    return Expect("network_brute_force", "medium")
