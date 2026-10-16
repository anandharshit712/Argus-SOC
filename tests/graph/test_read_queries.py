"""Real FalkorDB Q4-Q6, playbooks and the activity feed (step 8).

Feedback and playbooks are written here with plain Cypher in the shape LLD §4.1 gives;
step 9 adds the real record_feedback / create_playbook_version and checks the same reads.
"""

from pathlib import Path

import pytest

from argus_soc.graph import read_queries as rq
from argus_soc.graph import write_queries as wq
from argus_soc.graph.falkor_client import run
from argus_soc.graph.graph_schema import CLOSED, AlertInput, DecisionInput, Label, PlaybookRef, Rel
from argus_soc.graph.inventory_seed import inventory_path, load_inventory, seed_tenant
from argus_soc.graph.property_codec import to_json

pytestmark = pytest.mark.falkordb
INVENTORY = Path(__file__).resolve().parents[2] / "data" / "inventory"
SCANNER = "10.0.5.20"
CONDITION = {"category": "auth_failure", "ioc_in": [SCANNER]}
SCAN = AlertInput(
    incident_id="inc-9b10", domain="web", category="auth_failure", severity="medium",
    confidence=0.72, succeeded=False, talos_created_at="2026-10-15T09:10:00+00:00",
    hosts=("web-01",), endpoints=("/login",), source_ips=(SCANNER,),
)  # fmt: skip


async def _close(tenant: str, case_id: int, closed_at: str, verdict: str | None) -> None:
    await wq.set_case_status(tenant, case_id, CLOSED)
    await run(tenant, f"MATCH (c:{Label.CASE} {{id: $id}}) SET c.closed_at = $at, c.verdict = $v",
              {"id": case_id, "at": closed_at, "v": verdict})  # fmt: skip


async def _feedback(tenant: str, case_id: int, fid: str, note: str, at: str) -> None:
    await run(
        tenant,
        f"MATCH (c:{Label.CASE} {{id: $case}}) CREATE (:{Label.FEEDBACK} {{id: $id, "
        "verdict: 'benign', note: $note, analyst: 'acme.analyst', created_at: $at})"
        f"-[:{Rel.ON}]->(c)",
        {"case": case_id, "id": fid, "note": note, "at": at},
    )


async def _playbook(tenant: str, version: int, active: bool, fid: str) -> None:
    await run(
        tenant,
        f"MATCH (f:{Label.FEEDBACK} {{id: $fid}}) CREATE (:{Label.PLAYBOOK} {{name: 'scanner', "
        "version: $v, active: $active, condition: $cond, action: 'auto_close', "
        f"created_at: '2026-10-15T09:41:00+00:00'}})-[:{Rel.LEARNED_FROM}]->(f)",
        {"fid": fid, "v": version, "active": active, "cond": to_json(CONDITION)},
    )


@pytest.fixture
async def world(live_db, s1):
    """Acme with a closed benign scanner case (playbook v1 old, v2 active) and an open
    scenario 1 case with decision R1."""
    t = "test"
    await seed_tenant(t, load_inventory(inventory_path(INVENTORY, "acme")))
    for alert in (SCAN, s1.brute_force, s1.stuffing):
        await wq.upsert_alert_from_report(t, alert)
    scan_case = await wq.open_or_join_case(t, ["inc-9b10"], "medium")
    await _close(t, scan_case, "2026-10-15T09:40:00+00:00", "benign")
    await _feedback(t, scan_case, "fb-1", "first look", "2026-10-15T09:30:00+00:00")
    await _feedback(t, scan_case, "fb-2", "internal pentest scanner", "2026-10-15T09:40:00+00:00")
    await _playbook(t, 1, False, "fb-1")
    await _playbook(t, 2, True, "fb-2")
    attack_case = await wq.open_or_join_case(t, ["inc-7f3a", "inc-81c2"], "high")
    path = ["bastion-01", "app-02", "db-prod-01"]
    await wq.record_findings(t, attack_case, {"shortest_path": path})
    decision = await wq.record_decision(t, attack_case, s1.r1)
    return {"t": t, "scan": scan_case, "attack": attack_case, "decision": decision, "path": path}


# --- Q4 recall ----------------------------------------------------------------------


async def test_recall_by_ioc_host_or_user(world):
    t, scan = world["t"], world["scan"]
    expected = [{"case_id": scan, "verdict": "benign", "closed_at": "2026-10-15T09:40:00+00:00",
                 "note": "internal pentest scanner"}]  # latest note  # fmt: skip
    assert await rq.recall(t, ioc=SCANNER) == expected
    assert await rq.recall(t, host=["web-01"]) == expected
    assert await rq.recall(t, ioc=[SCANNER], host="web-01") == expected  # no duplicates


async def test_recall_ignores_open_cases(world, s1):
    t = world["t"]
    assert await rq.recall(t, ioc=s1.attacker, user="svc_deploy") == []
    await _close(t, world["attack"], "2026-10-16T12:00:00+00:00", None)
    hits = await rq.recall(t, ioc=s1.attacker, host="web-01")
    assert [h["case_id"] for h in hits] == [world["attack"], world["scan"]]  # newest first
    assert hits[0]["note"] is None


async def test_recall_needs_something_to_look_for(world):
    assert await rq.recall(world["t"]) == []


async def test_recall_is_per_tenant(world):
    assert await rq.recall("test_b", ioc=SCANNER) == []


# --- Q5 linked alerts --------------------------------------------------------------


async def test_linked_alerts(world):
    t = world["t"]
    assert await rq.linked_alerts(t, "inc-7f3a") == ["inc-81c2"]  # same attacker IP
    assert await rq.linked_alerts(t, "inc-81c2") == ["inc-7f3a"]
    assert await rq.linked_alerts(t, "inc-7f3a", window_hours=0) == []  # 2 minutes apart
    assert await rq.linked_alerts(t, "inc-9b10") == []  # web-01 + scanner: nothing shared
    assert await rq.linked_alerts(t, "inc-nope") == []


# --- Playbooks -----------------------------------------------------------------------


async def test_list_playbooks(world):
    books = await rq.list_playbooks(world["t"])
    assert [(p["version"], p["active"], p["learned_from"]) for p in books] == [
        (1, False, "fb-1"), (2, True, "fb-2"),
    ]  # fmt: skip
    assert books[1]["condition"] == CONDITION and books[1]["source_case"] == world["scan"]


async def test_matching_playbook(world, s1):
    t = world["t"]
    pb = await rq.matching_playbook(t, {"category": "auth_failure", "iocs": [SCANNER]})
    assert (pb["name"], pb["version"], pb["source_case"]) == ("scanner", 2, world["scan"])
    assert (
        await rq.matching_playbook(t, {"category": "auth_failure", "iocs": [s1.attacker]}) is None
    )
    assert await rq.matching_playbook(t, {"category": "injection", "iocs": [SCANNER]}) is None


async def test_no_active_playbook_no_match(world):
    t = world["t"]
    await run(t, f"MATCH (p:{Label.PLAYBOOK}) SET p.active = false")
    assert await rq.matching_playbook(t, {"category": "auth_failure", "iocs": [SCANNER]}) is None


# --- Q6 explain decision -------------------------------------------------------------


async def test_explain_decision(world, s1):
    t = world["t"]
    out = await rq.explain_decision(t, world["decision"])
    assert out["case_id"] == world["attack"] and out["alerts"] == ["inc-7f3a", "inc-81c2"]
    assert out["path"] == world["path"]
    assert out["acted_on"] == {"hosts": ["bastion-01"], "users": ["svc_deploy"],
                               "iocs": [s1.attacker]}  # fmt: skip
    assert out["decision"]["rule_id"] == "R1"
    assert out["playbook"] is None and out["source_case"] is None
    assert await rq.explain_decision(t, "no-such-decision") is None


async def test_explain_decision_cites_the_playbook(world):
    t = world["t"]
    cid = await wq.open_or_join_case(t, ["inc-9b10"], "low")  # scan case is closed: new case
    ref = PlaybookRef(name="scanner", version=2)
    cited = DecisionInput(
        rule_id="PB", actions=("auto_close",), needs_approval=False, reason="playbook", playbook=ref
    )
    did = await wq.record_decision(t, cid, cited)
    out = await rq.explain_decision(t, did)
    assert (out["playbook"]["version"], out["source_case"]) == (2, world["scan"])


# --- Activity feed and typed feedback -------------------------------------------------


async def test_list_activity_since_with_workers_and_tool_calls(world):
    t, cid = world["t"], world["attack"]
    calls = [{"tool": "recall", "args": {"ioc": SCANNER}, "result": "[]", "why": "check"}]
    await wq.record_agent_run(t, "triage", cid, "opened", handed_to="investigator", worker="w1")
    await wq.record_agent_run(t, "investigator", cid, "done", worker="w2", tool_calls=calls)
    feed = await rq.list_activity(t)
    assert [(r["agent"], r["worker"]) for r in feed] == [("triage", "w1"), ("investigator", "w2")]
    assert feed[1]["tool_calls"] == calls and feed[0]["case_id"] == cid
    assert await rq.list_activity(t, since="2999-01-01T00:00:00+00:00") == []
    assert len(await rq.list_activity(t, since="2000-01-01T00:00:00+00:00")) == 2


async def test_get_case_feedback_is_typed(world):
    case = await rq.get_case(world["t"], world["scan"])
    assert [f["id"] for f in case["feedback"]] == ["fb-1", "fb-2"]
    assert set(case["feedback"][0]) == {"id", "verdict", "note", "analyst", "created_at"}
    assert case["verdict"] == "benign" and case["status"] == "closed"
