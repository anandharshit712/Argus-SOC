"""The randomized attack simulator + self-check scoreboard (DEMO_DESIGN §5).

Two modes, one service:
  * demo   -- POST/GET /launch?attack=<name> fires one clean campaign on demand.
  * soak   -- a background weighted-random loop (DEMO_SOAK=1), one campaign at a time, benign
              traffic trickling underneath.

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
from ssh_campaign import ssh_brute_force

logging.basicConfig(level=logging.INFO, format="%(asctime)s attack-bot %(levelname)s %(message)s")
log = logging.getLogger("attack-bot")

SHOP_URL = os.environ.get("DEMO_SHOP_URL", "http://web_shop:8000").rstrip("/")
TALOS_URL = os.environ.get("TALOS_URL", "http://talos:8000").rstrip("/")
SOAK = os.environ.get("DEMO_SOAK", "0") == "1"
SELFCHECK_TIMEOUT = float(os.environ.get("DEMO_SELFCHECK_TIMEOUT", "20"))

CAMPAIGNS = {**WEB_CAMPAIGNS, "ssh_brute": ssh_brute_force}
_scoreboard: deque[dict] = deque(maxlen=100)
_lock = threading.Lock()  # one campaign at a time, so the demo story stays legible


@asynccontextmanager
async def lifespan(_app: FastAPI):
    threading.Thread(target=_benign_traffic, daemon=True).start()
    if SOAK:
        threading.Thread(target=_soak_loop, daemon=True).start()
        log.info("soak mode on")
    yield


app = FastAPI(title="Argus attack-bot", lifespan=lifespan)


def _known_incident_ids(client: httpx.Client) -> set[str]:
    try:
        reports = client.get(f"{TALOS_URL}/reports", params={"limit": 200}).json()
        return {r["incident_id"] for r in reports}
    except (httpx.HTTPError, ValueError, KeyError):
        return set()


def _poll_for_incident(client: httpx.Client, before: set[str], category: str) -> dict | None:
    """Wait for a NEW incident of the expected category to show up in Talos."""
    deadline = time.monotonic() + SELFCHECK_TIMEOUT
    while time.monotonic() < deadline:
        try:
            reports = client.get(f"{TALOS_URL}/reports", params={"limit": 200}).json()
        except (httpx.HTTPError, ValueError):
            reports = []
        for r in reports:
            if r["incident_id"] not in before and r.get("category") == category:
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


def run_campaign(name: str) -> dict:
    """Fire one campaign and score it against Talos. Serialized by _lock."""
    if name not in CAMPAIGNS:
        return {"error": f"unknown campaign {name}", "known": sorted(CAMPAIGNS)}
    with _lock, httpx.Client(timeout=10.0) as client:
        before = _known_incident_ids(client)
        log.info("launching %s", name)
        started = datetime.now(UTC)
        expect = CAMPAIGNS[name](client, SHOP_URL)
        hit = _poll_for_incident(client, before, expect.category)
        result = {
            "time": datetime.now(UTC).isoformat(timespec="seconds"),
            "campaign": name,
            "expected": f"{expect.category}/{expect.severity}",
            "detected": bool(hit),
            "incident_id": hit.get("incident_id") if hit else None,
            "latency_s": _latency(hit, started) if hit else None,
        }
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


def _soak_loop() -> None:
    names = list(WEIGHTS)
    weights = [WEIGHTS[n] for n in names]
    while True:
        name = random.choices(names, weights=weights, k=1)[0]
        try:
            run_campaign(name)
        except Exception:  # noqa: BLE001 -- soak must survive one bad run
            log.exception("soak campaign %s failed", name)
        time.sleep(random.uniform(45, 180))


@app.get("/health")
@app.get("/healthz")
async def health() -> dict[str, str]:
    return {"status": "ok", "mode": "soak" if SOAK else "demo"}


# Sync def on purpose: FastAPI runs it in a threadpool, so a campaign's blocking sleeps do not
# freeze the event loop (and /selfcheck stays responsive while an attack runs).
@app.get("/launch")
@app.post("/launch")
def launch(attack: str) -> dict:
    return run_campaign(attack)


@app.get("/selfcheck")
async def selfcheck() -> dict:
    board = list(_scoreboard)
    hits = sum(1 for r in board if r["detected"])
    return {"runs": len(board), "detected": hits, "results": board}
