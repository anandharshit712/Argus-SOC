"""Triage agent against the stub graph's sample data (see graph_stubs.py docstring)."""

import asyncio

from argus_soc import graph
from argus_soc.agents import triage_agent
from argus_soc.agents.priority_rules import highest, lower_one, raise_one
from argus_soc.graph.graph_schema import AlertInput, CaseStatus, Priority
from argus_soc.graph.graph_stubs import SCANNER_PLAYBOOK, SQLI_IP


async def _add_alert(tenant: str, incident_id: str, **fields) -> None:
    base = {
        "domain": "network",
        "category": "network_brute_force",
        "severity": "high",
        "confidence": 0.8,
        "talos_created_at": "2026-10-16T12:00:00+00:00",
    }
    await graph.upsert_alert_from_report(
        tenant, AlertInput(incident_id=incident_id, **(base | fields))
    )


async def _case_of(tenant: str, incident_id: str) -> dict:
    for summary in await graph.list_cases(tenant):
        case = await graph.get_case(tenant, summary["id"])
        if any(a["incident_id"] == incident_id for a in case["alerts"]):
            return case
    raise AssertionError(f"{incident_id} is in no case")


def test_priority_steps_are_capped():
    assert raise_one("high") == Priority.CRITICAL
    assert raise_one("critical") == Priority.CRITICAL
    assert lower_one("high") == Priority.MEDIUM
    assert lower_one("info") == Priority.INFO
    assert highest(["low", "high", "medium"]) == Priority.HIGH


async def test_playbook_match_auto_closes_and_cites_playbook():
    await triage_agent.step("acme")
    case = await _case_of("acme", "inc-a412")
    assert case["status"] == CaseStatus.AUTO_CLOSED
    assert case["closed_reason"] == f"Playbook {SCANNER_PLAYBOOK} v1, learned from Case 32"
    assert case["agent_runs"][-1]["worker"] == "worker-test"


async def test_new_alert_is_triaged_and_handed_to_investigator():
    assert (
        await triage_agent.step("acme") == 3
    )  # 2 alerts routed, 1 case triaged (the other is auto-closed)
    case = await _case_of("acme", "inc-c5e0")
    assert case["status"] == CaseStatus.TRIAGED
    assert case["priority"] == Priority.HIGH  # no memory hit: severity as is
    assert case["findings"]["memory_reasons"] == []
    run = case["agent_runs"][-1]
    assert (run["agent"], run["handed_to"], run["worker"]) == (
        "triage",
        "investigator",
        "worker-test",
    )
    assert await graph.list_new_alerts("acme") == []
    assert await triage_agent.step("acme") == 0  # nothing left: a rerun changes nothing


async def test_memory_hit_raises_priority_one_step():
    # An approved decision earlier marked this IP malicious; nothing else links the alert.
    await graph.set_ioc_fact("acme", "192.0.2.99", "verdict", "malicious")
    await _add_alert("acme", "inc-new1", hosts=("db-prod-01",), source_ips=("192.0.2.99",))
    await triage_agent.step("acme")
    case = await _case_of("acme", "inc-new1")
    assert case["priority"] == Priority.CRITICAL
    assert case["findings"]["memory_reasons"] == ["IOC 192.0.2.99 is known malicious"]
    assert case["findings"]["known_malicious_iocs"] == ["192.0.2.99"]  # read by R3


async def test_alert_correlated_with_open_case_joins_it():
    # svc_deploy is in inc-7f3a, part of case 31 (awaiting approval in the sample data).
    await _add_alert("acme", "inc-new3", hosts=("app-02",), users=("svc_deploy",))
    await triage_agent.step("acme")
    case = await graph.get_case("acme", 31)
    assert "inc-new3" in [a["incident_id"] for a in case["alerts"]]
    assert case["status"] == CaseStatus.AWAITING_APPROVAL


async def test_tenants_do_not_share_memory():
    # Globex sees the same attacker IP as Acme's case 31 but has no memory of it.
    await triage_agent.step("globex")
    case = await _case_of("globex", "inc-d901")
    assert case["priority"] == Priority.MEDIUM
    assert case["findings"]["recall"] == []


async def test_joining_a_case_past_triage_does_not_move_it_back():
    await triage_agent.step("acme")
    case = await _case_of("acme", "inc-c5e0")
    await graph.set_case_status("acme", case["id"], CaseStatus.AWAITING_APPROVAL)

    await _add_alert("acme", "inc-new2", category="injection", source_ips=(SQLI_IP,))
    await triage_agent.step("acme")

    joined = await graph.get_case("acme", case["id"])
    assert "inc-new2" in [a["incident_id"] for a in joined["alerts"]]
    assert joined["status"] == CaseStatus.AWAITING_APPROVAL
    assert joined["agent_runs"][-1]["handed_to"] is None


async def test_one_bad_alert_does_not_block_the_rest():
    await _add_alert("acme", "inc-bad", severity="not-a-severity", hosts=("db-prod-01",))
    assert await triage_agent.step("acme") == 3
    assert [a["incident_id"] for a in await graph.list_new_alerts("acme")] == ["inc-bad"]


async def test_two_workers_at_once_triage_each_case_once(monkeypatch):
    async def worker(name: str) -> int:
        monkeypatch.setenv("AGENT_WORKER_ID", name)
        return await triage_agent.step("acme")

    # Interleave two workers on the same new alerts, as two containers would.
    await asyncio.gather(worker("w1"), worker("w2"))
    case = await _case_of("acme", "inc-c5e0")
    triage_runs = [r for r in case["agent_runs"] if r["agent"] == "triage"]
    assert len(triage_runs) == 1
    assert case["status"] == CaseStatus.TRIAGED
