"""The randomized attack simulator + self-check scoreboard (DEMO_DESIGN §5, pass/fail v2).

Two modes, one service:
  * demo   -- POST/GET /launch?attack=<name>&outcome=pass|fail|random fires one campaign on demand.
  * soak   -- a background weighted-random loop, toggled at runtime with /soak/start and /soak/stop
              (or DEMO_SOAK=1 at boot), one campaign at a time, benign traffic trickling underneath.

Every campaign can fail (wrong creds / WAF 403) or pass (a real success Talos marks `succeeded`,
which reaches Argus as an Awaiting-approval case). In soak mode the outcome is drawn from a shuffled
bag so exactly 3 in every 10 runs pass (ATTACK_BOT_PASS_FAIL_DESIGN.md §4).

After each campaign the self-check polls Talos /reports and records whether the expected incident
appeared and how fast -- a live scoreboard of what Talos caught, which doubles as the harness test.
Everything targets the bundled demo containers only.
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
from campaigns import WEB_CAMPAIGNS, WEIGHTS
from fastapi import FastAPI
from outcome_bag import OutcomeBag
from ssh_campaign import ssh_brute_force

try:  # the backlog pause needs the FalkorDB client; the bot still runs without it (count disabled)
    from falkordb import FalkorDB
except ImportError:  # pragma: no cover
    FalkorDB = None  # type: ignore[assignment,misc]

logging.basicConfig(level=logging.INFO, format="%(asctime)s attack-bot %(levelname)s %(message)s")
log = logging.getLogger("attack-bot")

SHOP_URL = os.environ.get("DEMO_SHOP_URL", "http://web_shop:8000").rstrip("/")
TALOS_URL = os.environ.get("TALOS_URL", "http://talos:8000").rstrip("/")
SOAK_AT_BOOT = os.environ.get("DEMO_SOAK", "0") == "1"
SELFCHECK_TIMEOUT = float(os.environ.get("DEMO_SELFCHECK_TIMEOUT", "20"))
# Pass runs take longer (failures plus the success), so they get a longer detection window (§9).
SELFCHECK_TIMEOUT_PASS = float(os.environ.get("DEMO_SELFCHECK_TIMEOUT_PASS", "40"))

PASS_RATIO = float(os.environ.get("DEMO_PASS_RATIO", "0.3"))
BAG_SIZE = int(os.environ.get("DEMO_BAG_SIZE", "10"))
INTERVAL_MIN = float(os.environ.get("DEMO_SOAK_INTERVAL_MIN", "45"))
INTERVAL_MAX = float(os.environ.get("DEMO_SOAK_INTERVAL_MAX", "180"))

# Backlog pause (§9a): count Cases Awaiting approval on the tenant graph; pause soak over the limit.
MAX_PENDING = int(os.environ.get("DEMO_MAX_PENDING", "20"))  # 0 = off
DEMO_TENANT = os.environ.get("DEMO_TENANT", "globex")  # every live attack lands in Globex
FALKOR_HOST = os.environ.get("FALKORDB_HOST", "falkordb")
FALKOR_PORT = int(os.environ.get("FALKORDB_PORT", "6379"))
PENDING_RECHECK_SECONDS = 30.0

CAMPAIGNS = {**WEB_CAMPAIGNS, "ssh_brute": ssh_brute_force}
_scoreboard: deque[dict] = deque(maxlen=100)
_lock = threading.Lock()  # one campaign at a time, so the demo story stays legible

# Soak control: a single loop, guarded so a second /soak/start is a no-op (§8).
_soak_ctl_lock = threading.Lock()
_soak_thread: threading.Thread | None = None
_soak_stop = threading.Event()
_soak_state_lock = threading.Lock()
_soak_state: dict = {
    "running": False,
    "paused": False,
    "paused_since": None,
    "pending": 0,
    "limit": MAX_PENDING,
    "current": None,
    "next_run_at": None,
    "passes": 0,
    "fails": 0,
    "tokens_left": 0,
}


def _set_state(**kw) -> None:
    with _soak_state_lock:
        _soak_state.update(kw)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    threading.Thread(target=_benign_traffic, daemon=True).start()
    if SOAK_AT_BOOT:
        _start_soak(INTERVAL_MIN, INTERVAL_MAX, PASS_RATIO)
        log.info("soak mode on at boot")
    yield


app = FastAPI(title="Argus attack-bot", lifespan=lifespan)


def _known_incident_ids(client: httpx.Client) -> set[str]:
    try:
        reports = client.get(f"{TALOS_URL}/reports", params={"limit": 200}).json()
        return {r["incident_id"] for r in reports}
    except (httpx.HTTPError, ValueError, KeyError):
        return set()


def _succeeded(report: dict) -> bool:
    scope = report.get("aggregate_scope") or {}
    return bool(scope.get("succeeded"))


def _poll_for_incident(
    client: httpx.Client, before: set[str], category: str, require_succeeded: bool, timeout: float
) -> dict | None:
    """Wait for a NEW incident of the expected category. A pass run waits specifically for the
    report with aggregate_scope.succeeded = true; the threshold report alone is not it (§9)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            reports = client.get(f"{TALOS_URL}/reports", params={"limit": 200}).json()
        except (httpx.HTTPError, ValueError):
            reports = []
        for r in reports:
            if r["incident_id"] in before or r.get("category") != category:
                continue
            if require_succeeded and not _succeeded(r):
                continue
            return r
        time.sleep(1.0)
    return None


def _latency(report: dict, started: datetime) -> float | None:
    """Campaign start -> Talos stored the incident (its `created_at`). Timing the poll instead
    read 0.0 s every run: Talos detects mid-campaign (e.g. at the 8th failure), so the incident
    is already there when the campaign's traffic ends and the poll starts."""
    try:
        created = datetime.fromisoformat(report["created_at"])
    except (KeyError, TypeError, ValueError):
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return round((created - started).total_seconds(), 1)


def run_campaign(name: str, outcome: str = "fail") -> dict:
    """Fire one campaign (pass or fail) and score it against Talos. Serialized by _lock."""
    if name not in CAMPAIGNS:
        return {"error": f"unknown campaign {name}", "known": sorted(CAMPAIGNS)}
    with _lock, httpx.Client(timeout=10.0) as client:
        before = _known_incident_ids(client)
        log.info("launching %s (outcome=%s)", name, outcome)
        started = datetime.now(UTC)
        expect = CAMPAIGNS[name](client, SHOP_URL, outcome)
        timeout = SELFCHECK_TIMEOUT_PASS if expect.succeeded else SELFCHECK_TIMEOUT
        hit = _poll_for_incident(client, before, expect.category, expect.succeeded, timeout)
        result = {
            "time": datetime.now(UTC).isoformat(timespec="seconds"),
            "campaign": name,
            "outcome": outcome,
            "expected": f"{expect.category}/{expect.severity}",
            "expected_severity": expect.severity,
            "expected_succeeded": expect.succeeded,
            "detected": bool(hit),
            "incident_id": hit.get("incident_id") if hit else None,
            "latency_s": _latency(hit, started) if hit else None,
        }
        if expect.note:  # a pass that became a fail (missing pool password) -- never silent (§11)
            result["note"] = expect.note
    _scoreboard.appendleft(result)
    log.info("%s -> %s", name, f"DETECTED {result['incident_id']}" if hit else "MISSED")
    return result


def _benign_traffic() -> None:
    """Trickle normal requests so attacks sit in noise. Never trips a detector."""
    phrases = ["shoes", "european union flags", "o'brien jacket", "gift card", "blue dress"]
    with httpx.Client(timeout=5.0) as client:
        while True:
            try:
                client.get(f"{SHOP_URL}/api/search", params={"q": random.choice(phrases)})
                client.get(f"{SHOP_URL}/")
            except httpx.HTTPError:
                pass
            time.sleep(random.uniform(3, 8))


# --- Backlog pause (§9a) -----------------------------------------------------------------------
_last_pending_warn = 0.0


def _pending_count() -> int | None:
    """Cases Awaiting approval for the demo tenant, read directly off FalkorDB (no Argus login
    needed; the bot sits on soc-net). None if the count cannot be read -- never stop silently."""
    global _last_pending_warn
    if FalkorDB is None:
        return None
    try:
        db = FalkorDB(host=FALKOR_HOST, port=FALKOR_PORT)
        graph = db.select_graph(f"tenant_{DEMO_TENANT}")
        res = graph.ro_query("MATCH (c:Case {status: 'awaiting_approval'}) RETURN count(c)")
        return int(res.result_set[0][0])
    except Exception as exc:  # noqa: BLE001 -- a broken count must never stop the demo
        if "empty key" in str(exc).lower():
            return 0  # tenant graph not created yet: no cases
        now = time.monotonic()
        if now - _last_pending_warn > 60:  # one warning a minute, not one a check
            log.warning("backlog count failed, soak keeps running: %s", exc)
            _last_pending_warn = now
        return None


def _backlog_over_limit() -> tuple[bool, int]:
    if MAX_PENDING <= 0:
        return False, 0
    n = _pending_count()
    if n is None:
        return False, 0  # cannot read -> do not pause
    return n > MAX_PENDING, n


# --- Soak loop (§8) ----------------------------------------------------------------------------
def _soak_loop(interval_min: float, interval_max: float, ratio: float) -> None:
    names = list(WEIGHTS)
    weights = [WEIGHTS[n] for n in names]
    bag = OutcomeBag(BAG_SIZE, ratio)
    _set_state(running=True, passes=0, fails=0, tokens_left=bag.remaining())
    log.info("soak loop started (ratio=%.2f, bag=%d, max_pending=%d)", ratio, BAG_SIZE, MAX_PENDING)
    try:
        while not _soak_stop.is_set():
            over, pending = _backlog_over_limit()
            while over and not _soak_stop.is_set():
                if not _soak_state["paused"]:
                    log.warning("backlog %d > %d: soak paused", pending, MAX_PENDING)
                    _set_state(
                        paused=True, paused_since=datetime.now(UTC).isoformat(), pending=pending
                    )
                _soak_stop.wait(PENDING_RECHECK_SECONDS)
                over, pending = _backlog_over_limit()
            if _soak_stop.is_set():
                break
            if _soak_state["paused"]:
                log.info("backlog %d <= %d: soak resumed", pending, MAX_PENDING)
                _set_state(paused=False, paused_since=None, pending=pending)

            name = random.choices(names, weights=weights, k=1)[0]
            outcome = bag.draw()
            _set_state(current=name, tokens_left=bag.remaining(), pending=pending)
            try:
                run_campaign(name, outcome)
                with _soak_state_lock:
                    key = "passes" if outcome == "pass" else "fails"
                    _soak_state[key] += 1
            except Exception:  # noqa: BLE001 -- soak must survive one bad run
                log.exception("soak campaign %s failed", name)

            delay = random.uniform(interval_min, interval_max)
            _set_state(next_run_at=datetime.fromtimestamp(time.time() + delay, UTC).isoformat())
            _soak_stop.wait(delay)  # stop interrupts the sleep, never a running campaign
    finally:
        _set_state(running=False, paused=False, current=None, next_run_at=None)
        log.info("soak loop stopped")


def _start_soak(interval_min: float, interval_max: float, ratio: float) -> bool:
    """Start the loop if not already running. True if started, False if one was already running."""
    global _soak_thread
    with _soak_ctl_lock:
        if _soak_thread is not None and _soak_thread.is_alive():
            return False
        _soak_stop.clear()
        _soak_thread = threading.Thread(
            target=_soak_loop, args=(interval_min, interval_max, ratio), daemon=True
        )
        _soak_thread.start()
        return True


@app.get("/health")
@app.get("/healthz")
async def health() -> dict[str, str]:
    return {"status": "ok", "mode": "soak" if _soak_state["running"] else "demo"}


# Sync def on purpose: FastAPI runs it in a threadpool, so a campaign's blocking sleeps do not
# freeze the event loop (and /selfcheck stays responsive while an attack runs).
@app.get("/launch")
@app.post("/launch")
def launch(attack: str, outcome: str = "fail") -> dict:
    """Fire one campaign. outcome: fail (default) | pass | random (draws the bag).
    A manual run does not consume a soak token (§4)."""
    if outcome == "random":
        outcome = OutcomeBag(BAG_SIZE, PASS_RATIO).draw()
    elif outcome not in ("pass", "fail"):
        return {"error": f"outcome must be pass|fail|random, got {outcome!r}"}
    result = run_campaign(attack, outcome)
    if MAX_PENDING > 0:  # manual runs are never paused, but warn if the backlog is over the limit
        n = _pending_count()
        if n is not None and n > MAX_PENDING:
            result["warning"] = (
                f"backlog {n} > {MAX_PENDING}: soak is paused, this manual run ran anyway"
            )
    return result


@app.post("/soak/start")
def soak_start(
    interval_min: float | None = None, interval_max: float | None = None, ratio: float | None = None
) -> dict:
    started = _start_soak(
        interval_min if interval_min is not None else INTERVAL_MIN,
        interval_max if interval_max is not None else INTERVAL_MAX,
        ratio if ratio is not None else PASS_RATIO,
    )
    return {"status": "started" if started else "already running", "running": True}


@app.post("/soak/stop")
def soak_stop() -> dict:
    """Stop after the current campaign finishes (never mid-campaign)."""
    _soak_stop.set()
    return {"status": "stopping", "note": "the current campaign finishes first"}


@app.get("/soak/status")
async def soak_status() -> dict:
    with _soak_state_lock:
        return dict(_soak_state)


@app.get("/selfcheck")
async def selfcheck() -> dict:
    board = list(_scoreboard)
    hits = sum(1 for r in board if r["detected"])
    passes = [r for r in board if r.get("outcome") == "pass"]
    fails = [r for r in board if r.get("outcome") == "fail"]
    passes_detected = sum(1 for r in passes if r["detected"])
    fails_detected = sum(1 for r in fails if r["detected"])
    observed_ratio = round(len(passes) / len(board), 3) if board else 0.0
    return {
        "runs": len(board),
        "detected": hits,
        "passes": len(passes),
        "fails": len(fails),
        "passes_detected": passes_detected,
        "fails_detected": fails_detected,
        "observed_pass_ratio": observed_ratio,
        "results": board,
    }
