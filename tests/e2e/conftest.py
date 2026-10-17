"""End-to-end tests: the real stack (Talos, ingestor, agents, FalkorDB) running in Compose.

They wipe the tenant graphs and Talos's reports, so they only run when asked:

    docker compose --profile app up -d --scale agents=2 \
        falkordb seed talos-postgres talos ingestor agents
    ARGUS_E2E=1 pytest tests/e2e

Scenarios are replayed with scripts/replay_scenario.py; analyst feedback is given the way the
API does it (record_feedback, close if awaiting approval, on_feedback).
"""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from argus_soc import graph
from argus_soc.agents import learning_service
from argus_soc.core.settings import Settings, get_settings
from argus_soc.graph import falkor_client
from argus_soc.graph.graph_schema import CaseStatus

REPO = Path(__file__).resolve().parents[2]
BUSY = {CaseStatus.NEW, CaseStatus.TRIAGED, CaseStatus.INVESTIGATED}


@pytest.fixture(autouse=True)
async def e2e_stack(monkeypatch, tmp_path):
    if os.environ.get("ARGUS_E2E") != "1":
        pytest.skip("end-to-end: start the stack, then set ARGUS_E2E=1 (see tests/e2e/conftest.py)")
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    monkeypatch.chdir(tmp_path)  # never read a developer's real .env
    monkeypatch.setenv("FALKORDB_HOST", os.environ.get("FALKORDB_HOST", "127.0.0.1"))
    get_settings.cache_clear()
    yield
    await falkor_client.close()
    get_settings.cache_clear()


def replay(*args: str) -> None:
    subprocess.run([sys.executable, "scripts/replay_scenario.py", *args], cwd=REPO, check=True)


async def cases(tenant: str) -> list[dict]:
    return [await graph.get_case(tenant, row["id"]) for row in await graph.list_cases(tenant)]


async def settle(expected_alerts: dict[str, int], seconds: float = 120) -> None:
    """Wait until each tenant holds at least this many alerts, all in cases, and no case is
    still moving through the agents."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        ready = True
        for tenant, expected in expected_alerts.items():
            found = await cases(tenant)
            cased = sum(len(c["alerts"]) for c in found)
            waiting = await graph.list_new_alerts(tenant)
            if cased < expected or waiting or any(c["status"] in BUSY for c in found):
                ready = False
        if ready:
            return
        await asyncio.sleep(2)
    raise AssertionError(f"agents did not settle on {expected_alerts} within {seconds}s")


async def case_with(tenant: str, predicate) -> dict:
    found = [c for c in await cases(tenant) if predicate(c)]
    assert len(found) == 1, f"expected one matching case in {tenant}, found {len(found)}"
    return found[0]


async def give_feedback(tenant: str, case_id: int, verdict: str, note: str) -> str | None:
    """What POST /api/{tenant}/cases/{id}/feedback does (LLD §7)."""
    case = await graph.get_case(tenant, case_id)
    feedback_id = await graph.record_feedback(tenant, case_id, verdict, note, "e2e.analyst")
    if case["status"] == CaseStatus.AWAITING_APPROVAL:
        await graph.set_case_status(tenant, case_id, CaseStatus.CLOSED)
    return await learning_service.on_feedback(tenant, case_id, feedback_id)
