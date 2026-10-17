#!/usr/bin/env python3
"""Replay demo scenarios from data/scenarios/ into the Compose stack's Talos (Workstream A).

    python scripts/replay_scenario.py 1           # scenario 1 (2a / 2b: one run of scenario 2)
    python scripts/replay_scenario.py 5 --burst   # every file at once: the concurrency burst
    python scripts/replay_scenario.py --reset     # empty Talos and the tenant graphs first
    python scripts/replay_scenario.py --demo      # the whole demo, pausing for analyst steps

Needs the stack running (`docker compose --profile app up -d`). Talos's own `talos replay`
runs inside the talos container, so Argus never imports or bundles Talos (rule 7); the
ingestor and agents then pick the incidents up as in production. Standard library only.
Set COMPOSE_PROJECT_NAME to target a stack started under another project name.
"""

import argparse
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCENARIOS = Path(__file__).resolve().parents[1] / "data" / "scenarios"
TALOS_URL = "http://127.0.0.1:8000"  # inside the talos container
LOG_YEAR = "2026"  # syslog lines carry no year

# The demo, with what the presenter does after each step. Scenario 3 comes straight after 1:
# later, web-01 has been targeted in two cases, so memory raises the SQLi first and R4's
# one-step lowering no longer shows "high -> medium".
DEMO = (
    (
        "1",
        "Brute force lands on bastion-01, then credential stuffing from the same IP.",
        "One case, rule R1: isolate bastion-01, disable svc_deploy. Approve it in the UI.",
    ),
    (
        "3",
        "SQL injection probes on /api/search, all blocked by the WAF.",
        "No path to a crown jewel: closed by R4, priority lowered high -> medium.",
    ),
    (
        "2a",
        "The internal scanner checks weak passwords on web-01.",
        "Closed by R4. Mark it benign with a note: a playbook is learned.",
    ),
    (
        "2b",
        "The same scanner, a week later.",
        "Auto-closed by the learned playbook, citing the case it learned from.",
    ),
    (
        "4",
        "The scenario 1 attacker tries Globex's vpn-gw.",
        "Switch tenant: Globex has no memory of Acme's case.",
    ),
    (
        "6",
        "A week later, a new IP guesses svc_deploy's password on app-02.",
        "Priority raised one step: svc_deploy is suspected compromised since scenario 1.",
    ),
    (
        "5",
        "A busy hour: 24 attack bursts over both tenants at once.",
        "Activity feed: several workers, one decision per case.",
    ),
)


def compose(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "compose", *args], check=check, text=True,
                          capture_output=True)  # fmt: skip


def scenario_files(name: str) -> list[Path]:
    """Log files of scenario `name` ("1", "2", "2a", "2b", ...), in replay order."""
    number, run = name[0], name[1:]
    folders = sorted(SCENARIOS.glob(f"scenario_0{number}_*"))
    if len(name) > 2 or not folders:
        raise SystemExit(f"no scenario {name!r} in {SCENARIOS}")
    root = folders[0] / f"run_{run}" if run else folders[0]
    files = sorted(p for p in root.rglob("*") if p.is_file())
    if not files:
        raise SystemExit(f"no log files under {root}")
    return files


def domain(path: Path) -> str:
    """Talos parser domain: network for sshd and Windows logon logs, web for the rest."""
    return "network" if path.suffix == ".log" or "windows_security" in path.name else "web"


def replay_file(path: Path) -> str:
    target = f"/tmp/{path.parent.name}__{path.name}"
    compose("cp", str(path), f"talos:{target}")
    done = compose("exec", "-T", "talos", "talos", "replay", target, "--domain", domain(path),
                   "--year", LOG_YEAR, "--url", TALOS_URL)  # fmt: skip
    # `talos replay` prints each report on stdout and its "replayed ... N incident(s)" summary
    # on stderr; keep just the summary.
    lines = (done.stderr + done.stdout).splitlines()
    return next((ln for ln in lines if ln.startswith("replayed ")), f"replayed {path.name}")


def replay(name: str, burst: bool = False) -> None:
    files = scenario_files(name)
    if burst:
        with ThreadPoolExecutor(max_workers=len(files)) as pool:
            results = list(pool.map(replay_file, files))
    else:
        results = [replay_file(f) for f in files]
    for line in results:
        print(f"  {line}")


def reset() -> None:
    """Empty Talos (stored reports, learned baselines, in-memory repeat suppression) and wipe
    and re-seed the tenant graphs, so a rehearsal starts like the first run."""
    compose("exec", "-T", "talos-postgres", "psql", "-U", "talos", "-d", "talos", "-q", "-c",
            "TRUNCATE verdict_log, access_baseline;")  # fmt: skip
    compose("restart", "talos")
    compose("up", "-d", "--wait", "talos")
    compose("run", "--rm", "seed", "python", "scripts/reset_demo.py", "--yes")
    print("reset: Talos emptied and restarted, tenant graphs wiped and re-seeded")


def demo() -> None:
    reset()
    for step, (name, story, then) in enumerate(DEMO, 1):
        print(f"\n[{step}/{len(DEMO)}] scenario {name}: {story}")
        replay(name, burst=name == "5")
        print(f"  -> {then}")
        if step < len(DEMO):
            input("  press Enter for the next step ")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scenario", nargs="?", help="0-6, or 2a / 2b for one scenario 2 run")
    parser.add_argument("--burst", action="store_true", help="replay all files in parallel")
    parser.add_argument("--reset", action="store_true", help="empty Talos and the graphs first")
    parser.add_argument("--demo", action="store_true", help="run the whole demo, step by step")
    args = parser.parse_args(argv)
    if not (args.scenario or args.reset or args.demo):
        parser.error("give a scenario, --reset or --demo")
    try:
        if args.demo:
            demo()
            return
        if args.reset:
            reset()
        if args.scenario:
            print(f"scenario {args.scenario}:")
            replay(args.scenario, burst=args.burst)
    except subprocess.CalledProcessError as exc:
        sys.exit(f"{' '.join(exc.cmd)} failed:\n{exc.stderr or exc.stdout}")


if __name__ == "__main__":
    main()
