"""Real FalkorDB write functions (step 7), scenario 1 from ingest to decision."""

from pathlib import Path

import pytest

from argus_soc.graph import read_queries as rq
from argus_soc.graph import write_queries as wq
from argus_soc.graph.falkor_client import run, run_read
from argus_soc.graph.graph_schema import (
    AWAITING_APPROVAL,
    CLOSED,
    INVESTIGATED,
    NEW,
    TRIAGED,
    Label,
    PlaybookRef,
)
from argus_soc.graph.inventory_seed import inventory_path, load_inventory, seed_tenant

pytestmark = pytest.mark.falkordb
INVENTORY = Path(__file__).resolve().parents[2] / "data" / "inventory"


@pytest.fixture
async def acme(live_db):
    await seed_tenant("test", load_inventory(inventory_path(INVENTORY, "acme")))
    return "test"


async def _count(tenant: str, pattern: str, params: dict | None = None) -> int:
    rows = await run_read(tenant, f"MATCH {pattern} RETURN count(*) AS n", params or {})
    return rows[0]["n"] if rows else 0


# --- Alerts ---------------------------------------------------------------------


async def test_upsert_alert_links_its_nodes(acme, s1):
    assert await wq.upsert_alert_from_report(acme, s1.brute_force) == "inc-7f3a"
    (alert,) = await rq.list_new_alerts(acme)
    assert alert["hosts"] == ["bastion-01"] and alert["users"] == ["svc_deploy"]
    assert alert["iocs"] == [s1.attacker] and alert["status"] == "new"
    assert alert["evidence"] == ["12 failed SSH logins, then success as svc_deploy"]
    assert alert["techniques"] == [
        {"mitre_id": "T1110", "name": "Brute Force", "tactic": "credential-access"}
    ]
    assert alert["succeeded"] is True and alert["confidence"] == 0.9


async def test_upsert_twice_is_one_alert(acme, s1):
    before = await _count(acme, "(n)"), await _count(acme, "()-[r]->()")
    await wq.upsert_alert_from_report(acme, s1.brute_force)
    once = await _count(acme, "(n)"), await _count(acme, "()-[r]->()")
    await wq.upsert_alert_from_report(acme, s1.brute_force)
    assert (await _count(acme, "(n)"), await _count(acme, "()-[r]->()")) == once
    assert once[0] == before[0] + 3  # the alert, the attacker IOC and the technique


async def test_upsert_keeps_status_and_creates_unknown_hosts(acme, s1):
    await wq.upsert_alert_from_report(acme, s1.brute_force)
    await wq.open_or_join_case(acme, ["inc-7f3a"], "high")
    await wq.upsert_alert_from_report(acme, s1.brute_force.model_copy(update={"summary": "again"}))
    assert await rq.list_new_alerts(acme) == []
    odd = s1.brute_force.model_copy(update={"incident_id": "inc-x", "hosts": ("not-in-inventory",)})
    await wq.upsert_alert_from_report(acme, odd)
    rows = await run_read(acme, f"MATCH (h:{Label.HOST} {{hostname: 'not-in-inventory'}}) "
                          "RETURN h.criticality AS c, h.isolated AS iso")  # fmt: skip
    assert rows == [{"c": 1, "iso": False}]


async def test_known_incident_ids(acme, s1):
    await wq.upsert_alert_from_report(acme, s1.brute_force)
    assert await rq.known_incident_ids(acme, ["inc-7f3a", "inc-zzzz"]) == {"inc-7f3a"}


# --- Cases ----------------------------------------------------------------------


async def test_open_join_and_new_case(acme, s1):
    await wq.upsert_alert_from_report(acme, s1.brute_force)
    await wq.upsert_alert_from_report(acme, s1.stuffing)
    first = await wq.open_or_join_case(acme, ["inc-7f3a"], "high")
    assert first == 1
    assert await wq.open_or_join_case(acme, ["inc-81c2", "inc-7f3a"], "medium") == first
    case = await rq.get_case(acme, first)
    assert case["alert_count"] == 2 and case["priority"] == "high"  # priority set on create
    assert case["category"] == "network_brute_force" and case["status"] == NEW
    await wq.set_case_status(acme, first, CLOSED)
    assert await wq.open_or_join_case(acme, ["inc-7f3a"], "high") == 2  # closed: new case


async def test_claim_is_exclusive_and_expires(acme, s1):
    await wq.upsert_alert_from_report(acme, s1.brute_force)
    cid = await wq.open_or_join_case(acme, ["inc-7f3a"], "high")
    await wq.set_case_status(acme, cid, TRIAGED)
    assert await wq.claim_case(acme, TRIAGED, "investigator@w1", 120) == cid
    assert await wq.claim_case(acme, TRIAGED, "investigator@w2", 120) is None
    await run(acme, f"MATCH (c:{Label.CASE} {{id: $id}}) SET c.claimed_at = '2000-01-01'",
              {"id": cid})  # fmt: skip
    assert await wq.claim_case(acme, TRIAGED, "investigator@w2", 120) == cid
    assert (await rq.get_case(acme, cid))["claimed_by"] == "investigator@w2"


async def test_set_status_clears_claim_and_stamps_close(acme, s1):
    await wq.upsert_alert_from_report(acme, s1.brute_force)
    cid = await wq.open_or_join_case(acme, ["inc-7f3a"], "high")
    await wq.claim_case(acme, NEW, "triage@w1", 120)
    await wq.set_case_status(acme, cid, CLOSED, "low")
    case = await rq.get_case(acme, cid)
    assert (case["status"], case["priority"], case["claimed_by"]) == ("closed", "low", None)
    assert case["closed_at"]
    with pytest.raises(KeyError):
        await wq.set_case_status(acme, 999, TRIAGED)
    with pytest.raises(ValueError):
        await wq.set_case_status(acme, cid, "awaiting-approval")


async def test_findings_merge(acme, s1):
    await wq.upsert_alert_from_report(acme, s1.brute_force)
    cid = await wq.open_or_join_case(acme, ["inc-7f3a"], "high")
    await wq.record_findings(acme, cid, {"recall": [], "linked": ["inc-81c2"]})
    await wq.record_findings(acme, cid, {"succeeded": True, "linked": []})
    findings = (await rq.get_case(acme, cid))["findings"]
    assert findings == {"recall": [], "linked": [], "succeeded": True}
    with pytest.raises(KeyError):
        await wq.record_findings(acme, 999, {})


# --- Decisions and agent runs ------------------------------------------------------


async def test_decision_waiting_for_approval_changes_nothing_yet(acme, s1):
    await wq.upsert_alert_from_report(acme, s1.brute_force)
    cid = await wq.open_or_join_case(acme, ["inc-7f3a"], "high")
    did = await wq.record_decision(acme, cid, s1.r1)
    assert await wq.record_decision(acme, cid, s1.r1) == did  # retried: same decision
    case = await rq.get_case(acme, cid)
    d = case["decision"]
    assert (d["id"], d["rule_id"], d["outcome"], d["needs_approval"]) == (
        did,
        "R1",
        "pending",
        True,
    )
    assert d["target_hosts"] == ["bastion-01"] and d["target_users"] == ["svc_deploy"]
    assert d["target_iocs"] == [s1.attacker]
    assert d["evidence"] == {"ranking": [["bastion-01", 1.0]]}
    await wq.set_case_status(acme, cid, AWAITING_APPROVAL)
    assert (await rq.list_cases(acme))[0]["needs_approval"] is True
    rows = await run_read(acme, f"MATCH (h:{Label.HOST} {{hostname: 'bastion-01'}}) "
                          "RETURN h.isolated AS iso")  # fmt: skip
    assert rows == [{"iso": False}]


async def test_automatic_decision_is_simulated_at_once(acme, s1):
    await wq.upsert_alert_from_report(acme, s1.brute_force)
    cid = await wq.open_or_join_case(acme, ["inc-7f3a"], "high")
    auto = s1.r1.model_copy(update={"rule_id": "R3", "needs_approval": False})
    await wq.record_decision(acme, cid, auto)
    rows = await run_read(
        acme,
        f"MATCH (h:{Label.HOST} {{hostname: 'bastion-01'}}), (u:{Label.USER} "
        "{username: 'svc_deploy'}) RETURN h.isolated AS iso, u.disabled AS dis",
    )
    assert rows == [{"iso": True, "dis": True}]
    assert (await rq.get_case(acme, cid))["decision"]["outcome"] == "auto"


async def test_decision_cites_a_playbook(acme, s1):
    await run(acme, f"CREATE (:{Label.PLAYBOOK} {{name: 'pb', version: 2, active: true}})")
    await wq.upsert_alert_from_report(acme, s1.brute_force)
    cid = await wq.open_or_join_case(acme, ["inc-7f3a"], "high")
    cited = s1.r1.model_copy(update={"playbook": PlaybookRef(name="pb", version=2)})
    await wq.record_decision(acme, cid, cited)
    assert (await rq.get_case(acme, cid))["decision"]["playbook"] == {"name": "pb", "version": 2}


async def test_decision_on_unknown_case(acme, s1):
    with pytest.raises(KeyError):
        await wq.record_decision(acme, 999, s1.r1)


async def test_agent_runs_chain_handoffs(acme, s1):
    await wq.upsert_alert_from_report(acme, s1.brute_force)
    cid = await wq.open_or_join_case(acme, ["inc-7f3a"], "high")
    await wq.record_agent_run(acme, "triage", cid, "opened", handed_to="investigator",
                              worker="w1")  # fmt: skip
    calls = [
        {"tool": "blast_radius", "args": {"ioc": s1.attacker}, "result": "2 hosts", "why": "x"}
    ]
    await wq.record_agent_run(acme, "investigator", cid, "paths found", handed_to="responder",
                              worker="w2", tool_calls=calls)  # fmt: skip
    await wq.record_agent_run(acme, "responder", cid, "R1", worker="w1")
    runs = (await rq.get_case(acme, cid))["agent_runs"]
    assert [(r["agent"], r["worker"], r["handed_to"]) for r in runs] == [
        ("triage", "w1", "investigator"), ("investigator", "w2", "responder"),
        ("responder", "w1", None),
    ]  # fmt: skip
    assert runs[1]["tool_calls"] == calls and runs[0]["tool_calls"] is None
    assert await _count(acme, f"(:{Label.AGENT_RUN})-[:HANDED_OFF_TO]->(:{Label.AGENT_RUN})") == 2


async def test_agent_run_without_case(acme, s1):
    await wq.record_agent_run(acme, "triage", None, "nothing to do")
    assert await _count(acme, f"(:{Label.AGENT_RUN})") == 1


async def test_scenario_1_end_to_end(acme, s1):
    """Ingest -> Triage -> Investigator -> Responder, the way the agents will call it."""
    for alert in (s1.brute_force, s1.stuffing):
        await wq.upsert_alert_from_report(acme, alert)
    ids = [a["incident_id"] for a in await rq.list_new_alerts(acme)]
    cid = await wq.open_or_join_case(acme, ids, "high")
    await wq.set_case_status(acme, cid, TRIAGED, "critical")
    assert await wq.claim_case(acme, TRIAGED, "investigator@w1", 120) == cid
    await wq.record_findings(acme, cid, {"succeeded": True, "path_to_crown_jewel": True})
    await wq.set_case_status(acme, cid, INVESTIGATED)
    assert await wq.claim_case(acme, INVESTIGATED, "responder@w1", 120) == cid
    await wq.record_decision(acme, cid, s1.r1)
    await wq.set_case_status(acme, cid, AWAITING_APPROVAL)
    (summary,) = await rq.list_cases(acme, status=AWAITING_APPROVAL)
    assert (summary["id"], summary["alert_count"], summary["priority"]) == (cid, 2, "critical")
    assert summary["needs_approval"] is True and summary["auto_closed_by"] is None
