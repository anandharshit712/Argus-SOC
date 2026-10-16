import pytest
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError

from argus_soc.graph import graph_stubs
from argus_soc.graph.graph_stub_data import ATTACKER_IP, PATHS


async def test_case_list(client: AsyncClient, acme: dict[str, str]) -> None:
    response = await client.get("/api/acme/cases", headers=acme)
    assert response.status_code == 200
    cases = {c["id"]: c for c in response.json()}
    assert set(cases) == {31, 32}
    assert cases[31]["status"] == "awaiting_approval"
    assert cases[31]["needs_approval"] is True
    assert cases[31]["alert_count"] == 2
    assert cases[32]["needs_approval"] is False


async def test_case_list_filters_by_status(client: AsyncClient, acme: dict[str, str]) -> None:
    response = await client.get("/api/acme/cases?status=awaiting_approval", headers=acme)
    assert [c["id"] for c in response.json()] == [31]
    assert (await client.get("/api/acme/cases?status=bogus", headers=acme)).status_code == 422


async def test_case_detail(client: AsyncClient, acme: dict[str, str]) -> None:
    response = await client.get("/api/acme/cases/31", headers=acme)
    assert response.status_code == 200
    case = response.json()

    decision = case["decision"]
    assert decision["rule_id"] == "R1"
    assert decision["needs_approval"] is True
    assert decision["previous_priority"] == "high"  # GAP-5
    assert decision["target_hosts"] == ["bastion-01"]
    assert decision["ranking"] == [["bastion-01", 0.81], ["app-02", 0.64]]
    assert [n["name"] for n in decision["path"]] == PATHS["bastion-01"]
    assert {n["label"] for n in decision["path"]} <= {"Host", "User"}

    alerts = {a["incident_id"]: a for a in case["alerts"]}
    assert alerts["inc-7f3a"]["talos_actions"] == [
        f"block source IP {ATTACKER_IP} at the perimeter"
    ]
    assert case["findings"]["path_to_crown_jewel"] is True
    assert [r["worker"] for r in case["agent_runs"]] == ["agents-1"] * 3  # GAP-2


async def test_case_detail_typed_feedback(client: AsyncClient, acme: dict[str, str]) -> None:
    case = (await client.get("/api/acme/cases/32", headers=acme)).json()
    assert case["decision"] is None
    assert case["feedback"] == [
        {
            "id": "fb-32",
            "verdict": "benign",
            "note": "internal pentest scanner",
            "analyst": "analyst1",
            "created_at": "2026-10-15T09:40:00Z",
        }
    ]


async def test_unknown_case_is_not_found(client: AsyncClient, acme: dict[str, str]) -> None:
    assert (await client.get("/api/acme/cases/999", headers=acme)).status_code == 404


async def test_tenants_are_isolated(client: AsyncClient, admin: dict[str, str]) -> None:
    assert (await client.get("/api/globex/cases", headers=admin)).json() == []
    assert (await client.get("/api/globex/cases/31", headers=admin)).status_code == 404


async def test_playbooks(client: AsyncClient, acme: dict[str, str]) -> None:
    playbooks = (await client.get("/api/acme/playbooks", headers=acme)).json()
    assert len(playbooks) == 1
    assert playbooks[0]["version"] == 1
    assert playbooks[0]["active"] is True
    assert playbooks[0]["source_case"] == 32


async def test_activity_feed_and_since(client: AsyncClient, acme: dict[str, str]) -> None:
    everything = (await client.get("/api/acme/activity", headers=acme)).json()
    assert [r["agent"] for r in everything] == ["triage", "investigator", "responder"]
    assert everything[0]["worker"] == "agents-1"
    # A "Z" timestamp must compare the same as the graph's "+00:00" ones.
    newer = await client.get(
        "/api/acme/activity", params={"since": "2026-10-16T10:04:00Z"}, headers=acme
    )
    assert [r["agent"] for r in newer.json()] == ["investigator", "responder"]
    assert (await client.get("/api/acme/activity?since=yesterday", headers=acme)).status_code == 422


async def test_graph_down_is_503(
    client: AsyncClient, acme: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down(*args: object, **kwargs: object) -> None:
        raise RedisConnectionError("connection refused")

    monkeypatch.setattr(graph_stubs, "list_cases", down)
    response = await client.get("/api/acme/cases", headers=acme)
    assert response.status_code == 503
