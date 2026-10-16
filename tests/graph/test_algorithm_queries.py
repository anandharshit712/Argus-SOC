"""Real FalkorDB Q1-Q3 on the seeded Acme graph (step 7)."""

from pathlib import Path

import pytest

from argus_soc.graph import algorithm_queries as aq
from argus_soc.graph import read_queries as rq
from argus_soc.graph import write_queries as wq
from argus_soc.graph.inventory_seed import inventory_path, load_inventory, seed_tenant

pytestmark = pytest.mark.falkordb
INVENTORY = Path(__file__).resolve().parents[2] / "data" / "inventory"


@pytest.fixture
async def acme(live_db, s1):
    await seed_tenant("test", load_inventory(inventory_path(INVENTORY, "acme")))
    for alert in (s1.brute_force, s1.stuffing):
        await wq.upsert_alert_from_report("test", alert)
    return "test"


async def test_q1_blast_radius(acme, s1):
    rows = await rq.blast_radius(acme, s1.attacker)
    assert [r["host"] for r in rows] == ["app-02", "bastion-01"]  # most critical first
    app, bastion = rows
    assert (app["criticality"], app["accounts"], app["alerts"]) == (4, [], 1)
    assert bastion["accounts"] == ["svc_deploy"]
    assert bastion["reached_hosts"] == ["app-02", "bastion-01"]  # where svc_deploy logs in
    assert await rq.blast_radius(acme, "192.0.2.1") == []


async def test_q2_path_from_bastion(acme):
    paths = await aq.paths_to_crown_jewels(acme, "bastion-01")
    assert paths[0] == ["bastion-01", "app-02", "db-prod-01"]  # shortest first
    assert ["bastion-01", "svc_deploy", "app-02", "db-prod-01"] in paths  # via the account
    assert all(len(p) <= 7 for p in paths) and len(paths) <= 3


async def test_q2_respects_max_hops(acme):
    assert await aq.paths_to_crown_jewels(acme, "bastion-01", max_hops=1) == []
    assert await aq.paths_to_crown_jewels(acme, "bastion-01", max_hops=2) == [
        ["bastion-01", "app-02", "db-prod-01"]
    ]
    with pytest.raises(ValueError):
        await aq.paths_to_crown_jewels(acme, "bastion-01", max_hops=0)


async def test_q2_web01_has_no_path(acme):
    assert await aq.paths_to_crown_jewels(acme, "web-01") == []
    assert await aq.paths_to_crown_jewels(acme, "no-such-host") == []


async def test_q2_crown_jewel_itself(acme):
    assert await aq.paths_to_crown_jewels(acme, "db-prod-01") == []


async def test_q3_bastion_ranks_first(acme):
    cid = await wq.open_or_join_case(acme, ["inc-7f3a", "inc-81c2"], "high")
    ranking = await aq.rank_hosts(acme, cid)
    assert [h for h, _ in ranking] == ["bastion-01", "app-02"]
    assert ranking[0][1] == 1.0 and 0 < ranking[1][1] < 1.0
    assert await aq.rank_hosts(acme, 999) == []


async def test_q3_single_host_case(acme, s1):
    cid = await wq.open_or_join_case(acme, ["inc-81c2"], "medium")
    assert await aq.rank_hosts(acme, cid) == [("app-02", 1.0)]


async def test_case_reads_on_the_real_graph(acme):
    cid = await wq.open_or_join_case(acme, ["inc-7f3a", "inc-81c2"], "high")
    case = await rq.get_case(acme, cid)
    assert case["hosts"] == ["app-02", "bastion-01"] and case["users"] == ["svc_deploy"]
    assert [a["incident_id"] for a in case["alerts"]] == ["inc-7f3a", "inc-81c2"]
    assert case["decision"] is None and case["feedback"] == [] and case["agent_runs"] == []
    assert await rq.get_case(acme, 999) is None
    assert [c["id"] for c in await rq.list_cases(acme)] == [cid]
    assert await rq.list_cases(acme, status="closed") == []
