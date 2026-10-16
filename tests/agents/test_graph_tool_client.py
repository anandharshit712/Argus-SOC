"""The deep dive against Adnan's real MCP server (a stdio subprocess on the stub graph), with
a scripted fake LLM, plus the Responder's LLM explanation."""

from argus_soc import graph
from argus_soc.agents import agent_runner, graph_tool_client, llm_client, responder_agent
from argus_soc.agents.graph_tool_client import ToolChoice, deep_dive
from argus_soc.core.settings import get_settings
from argus_soc.graph.graph_stubs import ATTACKER_IP


def _llm_on(monkeypatch, max_calls: int = 4) -> None:
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "fake")
    monkeypatch.setenv("DEEP_DIVE_MAX_CALLS", str(max_calls))
    get_settings.cache_clear()


def _scripted(monkeypatch, choices: list[ToolChoice | None], seen: list[dict]) -> None:
    replies = iter(choices)

    async def complete(prompt_name, variables, schema):
        seen.append(variables)
        return next(replies, None)

    monkeypatch.setattr(llm_client, "complete", complete)


async def test_llm_picks_tools_and_code_sets_the_tenant(monkeypatch):
    _llm_on(monkeypatch)
    seen: list[dict] = []
    _scripted(
        monkeypatch,
        [
            # The LLM tries another tenant: code puts the case's tenant back.
            ToolChoice(
                done=False,
                tool="blast_radius",
                args={"ioc": ATTACKER_IP, "tenant": "globex"},
                reason="reach",
            ),  # noqa: E501
            ToolChoice(done=False, tool="drop_database", args={}, reason="unknown tool"),
        ],
        seen,
    )
    case = await graph.get_case("acme", 31)
    calls = await deep_dive("acme", case, case["findings"])

    assert [c["tool"] for c in calls] == ["blast_radius"]  # the unknown tool ended the dive
    assert calls[0]["args"] == {"ioc": ATTACKER_IP}
    assert "bastion-01" in calls[0]["result"]  # Acme's data, not Globex's
    tools = {t["name"]: t for t in seen[0]["tools"]}
    assert set(tools) == {
        "blast_radius", "paths_to_crown_jewels", "rank_hosts", "recall", "linked_alerts",
        "entity_facts",
    }  # fmt: skip
    assert "tenant" not in tools["blast_radius"]["arguments"]["properties"]


async def test_dive_stops_at_the_call_limit(monkeypatch):
    _llm_on(monkeypatch, max_calls=2)
    same = ToolChoice(done=False, tool="entity_facts", args={"hosts": [], "users": [], "iocs": []})
    _scripted(monkeypatch, [same] * 5, [])
    case = await graph.get_case("acme", 31)
    assert len(await deep_dive("acme", case, case["findings"])) == 2


async def test_dive_is_skipped_when_the_llm_is_off(monkeypatch):
    _scripted(monkeypatch, [], seen := [])
    case = await graph.get_case("acme", 31)
    assert await deep_dive("acme", case, case["findings"]) == []
    assert seen == []


async def test_bad_server_command_ends_the_dive_quietly(monkeypatch):
    _llm_on(monkeypatch)
    monkeypatch.setenv("MCP_SERVER_COMMAND", "no-such-command-argus")
    get_settings.cache_clear()
    _scripted(monkeypatch, [], [])
    case = await graph.get_case("acme", 31)
    assert await graph_tool_client.deep_dive("acme", case, case["findings"]) == []


async def test_responder_uses_the_llm_explanation_or_the_template(monkeypatch):
    async def explains(prompt_name, variables, schema):
        if prompt_name == "responder_explain_v1":
            assert "untrusted_data" in variables["evidence"]
            return schema(text="Blocked the SQLi source; no path to a crown jewel.")
        return None

    monkeypatch.setattr(llm_client, "complete", explains)
    while await agent_runner.run_once("acme"):
        pass
    explained = [c for c in await _cases("acme") if c["decision"] and c["id"] != 31]
    assert explained
    assert all(c["decision"]["explanation"].startswith("Blocked the SQLi") for c in explained)

    async def fails(*args):
        return None

    monkeypatch.setattr(llm_client, "complete", fails)
    case = explained[0]
    text = await responder_agent.explanation(
        responder_agent.decision_table.decide(case["findings"]), case, [], {
            "target_hosts": (), "target_users": (), "target_iocs": ()
        }, "medium"
    )  # fmt: skip
    assert text.startswith("Rule R")  # the template


async def _cases(tenant: str) -> list[dict]:
    return [await graph.get_case(tenant, r["id"]) for r in await graph.list_cases(tenant)]
