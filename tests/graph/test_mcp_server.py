"""The read-only graph MCP server (step 11): what the LLM can see and call."""

import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from argus_soc import graph
from argus_soc.core.settings import get_settings
from argus_soc.graph import graph_stubs, mcp_server
from argus_soc.graph import read_queries as rq
from argus_soc.graph import write_queries as wq
from argus_soc.graph.inventory_seed import inventory_path, load_inventory, seed_tenant

ROOT = Path(__file__).resolve().parents[2]
ATTACKER = graph_stubs.ATTACKER_IP


@pytest.fixture
def stub(monkeypatch):
    monkeypatch.setenv("ARGUS_GRAPH_BACKEND", "stub")
    get_settings.cache_clear()
    graph_stubs.reset_stubs()


async def _call(name: str, args: dict):
    async with create_connected_server_and_client_session(mcp_server.server) as client:
        return await client.call_tool(name, args)


def _json(result) -> object:
    assert not result.isError, result.content[0].text
    return json.loads(result.content[0].text)


# --- What the LLM sees ------------------------------------------------------------------


async def test_only_the_six_read_tools_are_listed(stub):
    async with create_connected_server_and_client_session(mcp_server.server) as client:
        tools = (await client.list_tools()).tools
    assert sorted(t.name for t in tools) == sorted(mcp_server.READ_TOOLS)
    assert set(mcp_server.READ_TOOLS) <= set(graph.READ_FUNCTIONS)
    assert not {t.name for t in tools} & set(graph.WRITE_FUNCTIONS)  # nothing can write
    for tool in tools:
        assert tool.description and "\n" not in tool.description.strip()  # one line
        schema = tool.inputSchema
        assert next(iter(schema["properties"])) == "tenant", tool.name  # tenant first
        assert "tenant" in schema["required"]


async def test_argument_schemas_carry_the_limits(stub):
    async with create_connected_server_and_client_session(mcp_server.server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    hops = tools["paths_to_crown_jewels"].inputSchema["properties"]["max_hops"]
    assert (hops["minimum"], hops["maximum"], hops["default"]) == (1, 10, 6)


# --- Calls (stub backend) ------------------------------------------------------------------


async def test_calls_return_the_same_as_the_python_function(stub):
    assert _json(await _call("blast_radius", {"tenant": "acme", "ioc": ATTACKER})) == (
        await graph.blast_radius("acme", ATTACKER)
    )
    assert _json(await _call("rank_hosts", {"tenant": "acme", "case_id": 31})) == [
        ["bastion-01", 0.81],
        ["app-02", 0.64],
    ]
    paths = _json(await _call("paths_to_crown_jewels", {"tenant": "acme", "host": "bastion-01"}))
    assert paths == [["bastion-01", "app-02", "db-prod-01"]]
    hits = _json(await _call("recall", {"tenant": "acme", "ioc": [graph_stubs.SCANNER_IP]}))
    assert hits[0]["case_id"] == 32
    assert _json(await _call("linked_alerts", {"tenant": "acme", "incident_id": "inc-7f3a"})) == [
        "inc-81c2"
    ]
    facts = _json(await _call("entity_facts", {"tenant": "acme", "hosts": ["bastion-01"],
                                               "users": [], "iocs": []}))  # fmt: skip
    assert facts["hosts"]["bastion-01"]["targeted_case_ids"] == [31]


async def test_unknown_tenant_is_an_error(stub):
    result = await _call("blast_radius", {"tenant": "initech", "ioc": ATTACKER})
    assert result.isError and "unknown tenant" in result.content[0].text


async def test_bad_arguments_are_errors(stub):
    assert (
        await _call("paths_to_crown_jewels", {"tenant": "acme", "host": "x", "max_hops": 0})
    ).isError
    assert (await _call("rank_hosts", {"tenant": "acme"})).isError  # case_id missing
    assert (await _call("record_feedback", {"tenant": "acme"})).isError  # not a tool


def test_results_are_cut_to_4000_characters():
    text = mcp_server._result(["x" * 100] * 100)
    assert len(text) == mcp_server.RESULT_MAX_CHARS and text.endswith(mcp_server.TRUNCATED)
    assert mcp_server._result([1, 2]) == "[1, 2]"


# --- The way the agents start it: a subprocess over stdio -----------------------------------


async def test_runs_as_a_stdio_subprocess():
    env = {**os.environ, "ARGUS_GRAPH_BACKEND": "stub", "ARGUS_TENANTS": "acme,globex",
           "PYTHONPATH": str(ROOT / "src")}  # fmt: skip
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "argus_soc.graph.mcp_server"], env=env
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
        await client.initialize()
        assert len((await client.list_tools()).tools) == 6
        result = await client.call_tool("rank_hosts", {"tenant": "acme", "case_id": 31})
        assert json.loads(result.content[0].text)[0][0] == "bastion-01"


# --- Real FalkorDB behind the tools ----------------------------------------------------------


@pytest.mark.falkordb
async def test_tools_on_the_real_graph(live_db, s1):
    await seed_tenant("test", load_inventory(inventory_path(ROOT / "data" / "inventory", "acme")))
    for alert in (s1.brute_force, s1.stuffing):
        await wq.upsert_alert_from_report("test", alert)
    radius = _json(await _call("blast_radius", {"tenant": "test", "ioc": s1.attacker}))
    assert radius == await rq.blast_radius("test", s1.attacker)
    paths = _json(await _call("paths_to_crown_jewels", {"tenant": "test", "host": "bastion-01"}))
    assert paths[0] == ["bastion-01", "app-02", "db-prod-01"]
    # Other tenants stay invisible through MCP too.
    assert _json(await _call("blast_radius", {"tenant": "test_b", "ioc": s1.attacker})) == []
