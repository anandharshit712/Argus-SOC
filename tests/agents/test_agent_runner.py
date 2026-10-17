"""The three agents end to end on the stub graph, driven by the runner as in production."""

from argus_soc import graph
from argus_soc.agents import agent_runner, investigator_agent, triage_agent
from argus_soc.graph.graph_schema import AlertInput, CaseStatus, Priority
from argus_soc.graph.graph_stubs import SQLI_IP

ATTACKER = "192.0.2.50"  # not in the stub sample data, so nothing links to case 31


async def _add(incident_id: str, **fields) -> None:
    base = {
        "domain": "network",
        "category": "network_brute_force",
        "severity": "medium",
        "confidence": 0.7,
        "talos_created_at": "2026-10-16T12:00:00+00:00",
        "source_ips": (ATTACKER,),
    }
    await graph.upsert_alert_from_report(
        "acme", AlertInput(incident_id=incident_id, **(base | fields))
    )


async def _run_until_idle(tenant: str = "acme") -> None:
    for _ in range(20):
        if not await agent_runner.run_once(tenant):
            return
    raise AssertionError("agents never went idle")


async def _case_with(incident_id: str) -> dict:
    for row in await graph.list_cases("acme"):
        case = await graph.get_case("acme", row["id"])
        if incident_id in [a["incident_id"] for a in case["alerts"]]:
            return case
    raise AssertionError(f"{incident_id} is in no case")


async def test_brute_force_that_lands_is_isolated_pending_approval():
    # Scenario 1 shape: brute force on bastion-01 that succeeds, plus credential stuffing on
    # web-01 from the same IP against customer accounts.
    await _add("inc-bf", hosts=("bastion-01",), users=("deploy2",))
    await _add("inc-ok", hosts=("bastion-01",), users=("deploy2",), severity="high", succeeded=True)
    await _add(
        "inc-cs",
        domain="web",
        category="auth_failure",
        hosts=("web-01",),
        users=("a@mail.example", "b@mail.example"),
    )
    await _run_until_idle()

    case = await _case_with("inc-bf")
    assert len(case["alerts"]) == 3  # one case through the shared IP
    assert case["status"] == CaseStatus.AWAITING_APPROVAL
    assert case["priority"] == Priority.HIGH  # the successful login, not the first alert
    assert case["decision"]["previous_priority"] == Priority.HIGH  # unchanged by R1
    assert case["findings"]["shortest_path"] == ["bastion-01", "app-02", "db-prod-01"]
    d = case["decision"]
    assert d["rule_id"] == "R1"
    assert (d["target_hosts"], d["target_users"], d["target_iocs"]) == (
        ["bastion-01"],
        ["deploy2"],  # broken into; the customer accounts it only tried are left alone
        [ATTACKER],
    )
    assert d["evidence"]["ranking"][0][0] == "bastion-01"
    assert [r["agent"] for r in case["agent_runs"]] == ["triage", "investigator", "responder"]
    facts = await graph.entity_facts("acme", ["bastion-01"], ["deploy2", "a@mail.example"], [])
    assert facts["users"]["deploy2"]["suspected_compromised"] is True
    assert facts["users"]["a@mail.example"]["suspected_compromised"] is False


async def test_blocked_injection_with_no_path_is_closed_and_lowered():
    # Scenario 3 shape (the stub's inc-c5e0): SQLi on web-01, blocked, no path to a crown jewel.
    await _run_until_idle()
    case = await _case_with("inc-c5e0")
    assert case["status"] == CaseStatus.CLOSED
    assert case["decision"]["rule_id"] == "R4"
    assert case["decision"]["target_iocs"] == [SQLI_IP]
    assert case["decision"]["target_hosts"] == []
    assert case["priority"] == Priority.MEDIUM  # high, lowered one step
    assert case["decision"]["previous_priority"] == Priority.HIGH  # GAP-5: "high -> medium"


async def test_rerun_after_done_changes_nothing():
    await _run_until_idle()
    before = await graph.list_cases("acme")
    assert await agent_runner.run_once("acme") is False
    assert await graph.list_cases("acme") == before


async def test_success_alert_joining_after_investigation_is_decided_r1():
    # Live test Oct 17, case 8: "not succeeded", then 9 s later "succeeded" for the same SSH
    # attack, after the Investigator ran. The case must not close as R3.
    await _add("inc-bf", hosts=("bastion-01",), users=("deploy2",))
    await triage_agent.step("acme")
    case_id = (await _case_with("inc-bf"))["id"]
    await investigator_agent.run("acme", case_id)

    await _add("inc-ok", hosts=("bastion-01",), users=("deploy2",), severity="high", succeeded=True)
    await _run_until_idle()

    case = await _case_with("inc-ok")
    assert case["id"] == case_id
    assert case["findings"]["succeeded"] is True
    assert case["decision"]["rule_id"] == "R1"
    assert case["status"] == CaseStatus.AWAITING_APPROVAL
    agents = [r["agent"] for r in case["agent_runs"]]
    assert agents[-4:] == ["triage", "responder", "investigator", "responder"]
