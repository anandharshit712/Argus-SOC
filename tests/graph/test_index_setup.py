import asyncio

import pytest

from argus_soc.graph import index_setup
from argus_soc.graph.falkor_client import _db, graph_for, run, run_read
from argus_soc.graph.graph_schema import Label
from argus_soc.graph.index_setup import INDEXES, ensure_indexes, existing_indexes, setup_tenants

LLD_INDEXES = {
    ("Alert", "incident_id"),
    ("Host", "hostname"),
    ("User", "username"),
    ("IOC", "value"),
    ("Case", "id"),
    ("Case", "status"),
    ("Playbook", "active"),
}


def test_index_list_matches_lld():
    assert {(label.value, prop) for label, prop in INDEXES} == LLD_INDEXES


def test_cli_rejects_unknown_tenant(capsys):
    with pytest.raises(SystemExit):
        index_setup.main(["initech"])
    assert "unknown tenant" in capsys.readouterr().err


@pytest.mark.falkordb
async def test_creates_every_index_then_nothing(live_db):
    first = await setup_tenants(["test"])
    assert set(first["test"]) == LLD_INDEXES
    second = await setup_tenants(["test"])
    assert second["test"] == []
    have = await existing_indexes("test")
    assert {k for k, status in have.items() if status == "OPERATIONAL"} >= LLD_INDEXES


@pytest.mark.falkordb
async def test_creates_the_tenant_graph(live_db):
    await setup_tenants(["test"])
    assert "tenant_test" in await _db().list_graphs()
    # The graph exists now, so read-only aggregates return a row again.
    assert await run_read("test", "MATCH (n) RETURN count(n) AS nodes") == [{"nodes": 0}]


@pytest.mark.falkordb
async def test_two_processes_at_once_do_not_fail(live_db):
    created = await asyncio.gather(ensure_indexes("test"), ensure_indexes("test"))
    assert set(created[0]) | set(created[1]) == LLD_INDEXES


@pytest.mark.falkordb
async def test_only_the_named_tenant_gets_indexes(live_db):
    await setup_tenants(["test"])
    assert await existing_indexes("test_b") == {}


@pytest.mark.falkordb
@pytest.mark.parametrize("label,prop", INDEXES, ids=[f"{lb}.{p}" for lb, p in INDEXES])
async def test_lookups_use_the_index(live_db, label, prop):
    await setup_tenants(["test"])
    await run("test", f"CREATE (:{label} {{{prop}: 'x'}})")
    plan = await graph_for("test").explain(f"MATCH (n:{label} {{{prop}: $v}}) RETURN n", {"v": "x"})
    assert "Node By Index Scan" in str(plan)


@pytest.mark.falkordb
async def test_unindexed_lookup_scans_the_label(live_db):
    # Sanity check that the plan text tells the two apart.
    await setup_tenants(["test"])
    plan = await graph_for("test").explain(
        f"MATCH (h:{Label.HOST} {{zone: $z}}) RETURN h", {"z": "dmz"}
    )
    assert "Node By Index Scan" not in str(plan)
