import pytest
from redis.exceptions import ResponseError

from argus_soc.core.tenant_registry import UnknownTenant
from argus_soc.graph.falkor_client import graph_for, ping, run, run_read
from argus_soc.graph.graph_schema import Label


@pytest.mark.parametrize("tenant", ["initech", "Acme", "tenant_acme", ""])
def test_unknown_tenant_fails_before_the_database(tenant):
    with pytest.raises(UnknownTenant):
        graph_for(tenant)


async def test_params_must_be_a_dict():
    with pytest.raises(TypeError):
        await run("test", "RETURN $x AS x", [("x", 1)])  # type: ignore[arg-type]


async def test_ping_is_false_when_nothing_listens(monkeypatch):
    from argus_soc.core.settings import get_settings
    from argus_soc.graph import falkor_client

    monkeypatch.setenv("FALKORDB_HOST", "127.0.0.1")
    monkeypatch.setenv("FALKORDB_PORT", "1")  # nothing listens on port 1
    get_settings.cache_clear()
    await falkor_client.close()
    assert await ping() is False


@pytest.mark.falkordb
async def test_write_then_read_returns_dicts(live_db):
    assert await run("test", f"MERGE (:{Label.HOST} {{hostname: $h, zone: $z}})",
                     {"h": "bastion-01", "z": "dmz"}) == []  # fmt: skip
    rows = await run_read(
        "test",
        f"MATCH (h:{Label.HOST} {{hostname: $h}}) RETURN h.hostname AS hostname, h.zone AS zone",
        {"h": "bastion-01"},
    )
    assert rows == [{"hostname": "bastion-01", "zone": "dmz"}]


@pytest.mark.falkordb
async def test_parameters_are_data_not_cypher(live_db):
    evil = "x'}) MATCH (n) DETACH DELETE n //"
    await run("test", f"CREATE (:{Label.HOST} {{hostname: 'keep-me'}})")
    await run("test", f"MERGE (:{Label.USER} {{username: $u}})", {"u": evil})
    rows = await run_read("test", "MATCH (n) RETURN count(n) AS nodes")
    assert rows == [{"nodes": 2}]
    rows = await run_read("test", f"MATCH (u:{Label.USER}) RETURN u.username AS u")
    assert rows == [{"u": evil}]


@pytest.mark.falkordb
async def test_run_read_refuses_writes(live_db):
    await run("test", f"CREATE (:{Label.HOST} {{hostname: 'exists'}})")  # graph must exist
    with pytest.raises(ResponseError):
        await run_read("test", f"CREATE (:{Label.HOST} {{hostname: 'nope'}})")


@pytest.mark.falkordb
async def test_tenants_never_see_each_other(live_db):
    await run("test", f"CREATE (:{Label.HOST} {{hostname: 'only-in-test'}})")
    await run("test_b", f"CREATE (:{Label.HOST} {{hostname: 'only-in-test-b'}})")
    query = f"MATCH (h:{Label.HOST}) RETURN h.hostname AS h"
    assert await run_read("test", query) == [{"h": "only-in-test"}]
    assert await run_read("test_b", query) == [{"h": "only-in-test-b"}]


@pytest.mark.falkordb
async def test_ping_when_running(live_db):
    assert await ping() is True


@pytest.mark.falkordb
async def test_reading_a_graph_never_written_returns_nothing(live_db):
    # FalkorDB refuses read-only queries on a graph that does not exist yet; run_read
    # returns no rows instead (even for count(), so seed every tenant before reading).
    assert await run_read("test_b", f"MATCH (h:{Label.HOST}) RETURN h.hostname AS h") == []
    assert await run_read("test_b", "MATCH (n) RETURN count(n) AS nodes") == []
