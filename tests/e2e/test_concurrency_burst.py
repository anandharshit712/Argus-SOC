"""Concurrency proof (G11, LLD §11): scenario 5's 24 bursts over both tenants at once, with
two agent workers (`--scale agents=2`). Every case gets exactly one decision, no alert lands in
two cases, both workers do work, and nothing crosses tenants."""

import os
from collections import Counter

import pytest
from tests.e2e.conftest import cases, replay, settle

from argus_soc import graph

# Talos incidents from scenario 5 per tenant (31 in all, verified Oct 16).
BURST = {"acme": 16, "globex": 15}
HOST_PREFIX = {"acme": ("acme-",), "globex": ("globex-", "gx-")}


@pytest.fixture(scope="module", autouse=True)
def fresh_stack():
    if os.environ.get("ARGUS_E2E") == "1":
        replay("--reset")


async def test_burst_over_two_workers():
    replay("5", "--burst")
    await settle(BURST, seconds=240)

    alerts: Counter[str] = Counter()
    for tenant, expected in BURST.items():
        found = await cases(tenant)
        alerts.update(a["incident_id"] for c in found for a in c["alerts"])
        assert sum(len(c["alerts"]) for c in found) == expected
        assert all(c["decision"] is not None for c in found), "a case was never decided"
        hosts = {h for c in found for h in c["hosts"]}
        assert all(h.startswith(HOST_PREFIX[tenant]) for h in hosts), f"foreign host in {tenant}"
    assert max(alerts.values()) == 1, "an alert is in two cases"

    runs = [(t, r) for t in BURST for r in await graph.list_activity(t)]
    # Case ids are numbered per tenant, so count (tenant, case id).
    decided = Counter((t, r["case_id"]) for t, r in runs if r["agent"] == "responder")
    assert set(decided.values()) == {1}, "a case was decided twice"
    workers = {r["worker"] for _, r in runs}
    assert len(workers) >= 2, f"only {workers} did work; start the stack with --scale agents=2"
