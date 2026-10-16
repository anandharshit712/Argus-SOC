"""The demo, in order (design doc demo script). Each test builds on the graph the previous one
left, as the live demo does, so the module runs top to bottom from one reset."""

import os

import pytest
from tests.e2e.conftest import case_with, cases, give_feedback, replay, settle

from argus_soc import graph
from argus_soc.graph.graph_schema import CaseStatus, Priority

ATTACKER = "203.0.113.7"
SCANNER = "10.0.5.20"
SQLI = "198.51.100.23"
RETURNING = "198.51.100.77"

# Acme alerts after each step, in demo order (Talos incidents per scenario: 6, 1, 2, 2, 1).
ACME_AFTER = {"1": 6, "3": 7, "2a": 9, "2b": 11, "6": 12}


@pytest.fixture(scope="module", autouse=True)
def fresh_stack():
    if os.environ.get("ARGUS_E2E") == "1":
        replay("--reset")


async def test_01_brute_force_that_lands():
    replay("1")
    await settle({"acme": ACME_AFTER["1"]})
    case = await case_with("acme", lambda c: ATTACKER in c["iocs"])
    assert len(case["alerts"]) == 6  # SSH + credential stuffing, joined through the IP
    assert case["status"] == CaseStatus.AWAITING_APPROVAL
    assert case["priority"] == Priority.HIGH
    assert case["findings"]["shortest_path"] == ["bastion-01", "app-02", "db-prod-01"]
    d = case["decision"]
    assert (d["rule_id"], d["target_hosts"], d["target_users"], d["target_iocs"]) == (
        "R1",
        ["bastion-01"],
        ["svc_deploy"],
        [ATTACKER],
    )
    assert [r["agent"] for r in case["agent_runs"]][:3] == ["triage", "investigator", "responder"]

    await give_feedback("acme", case["id"], "approve", "confirmed intrusion")
    assert (await graph.get_case("acme", case["id"]))["decision"]["outcome"] == "approved"


async def test_02_blocked_injection_is_closed_and_lowered():
    replay("3")
    await settle({"acme": ACME_AFTER["3"]})
    case = await case_with("acme", lambda c: SQLI in c["iocs"])
    assert (case["status"], case["decision"]["rule_id"]) == (CaseStatus.CLOSED, "R4")
    assert case["priority"] == Priority.MEDIUM  # Talos said high; no way in, one step lower
    assert case["decision"]["previous_priority"] == Priority.HIGH  # GAP-5: shown as high -> medium
    assert case["decision"]["target_hosts"] == []


async def test_03_scanner_marked_benign_teaches_a_playbook():
    replay("2a")
    await settle({"acme": ACME_AFTER["2a"]})
    case = await case_with("acme", lambda c: SCANNER in c["iocs"])
    assert (case["status"], case["decision"]["rule_id"]) == (CaseStatus.CLOSED, "R4")

    learned = await give_feedback("acme", case["id"], "benign", "internal pentest scanner")
    assert learned is not None and learned.endswith("v1")


async def test_04_scanner_again_is_auto_closed_by_the_playbook():
    replay("2b")
    await settle({"acme": ACME_AFTER["2b"]})
    auto = [c for c in await cases("acme") if c["status"] == CaseStatus.AUTO_CLOSED]
    assert sum(len(c["alerts"]) for c in auto) == 2  # both incidents of the second run
    assert all("learned from Case" in c["closed_reason"] for c in auto)


async def test_05_second_tenant_has_no_memory_of_the_first():
    replay("4")
    await settle({"globex": 1})
    case = await case_with("globex", lambda c: ATTACKER in c["iocs"])
    assert case["findings"]["recall"] == []
    assert case["findings"]["memory_reasons"] == []  # Acme's verdict on the IP never leaks
    assert case["priority"] == Priority.MEDIUM


async def test_06_returning_attack_on_a_suspected_account_is_raised():
    replay("6")
    await settle({"acme": ACME_AFTER["6"]})
    case = await case_with("acme", lambda c: RETURNING in c["iocs"])
    reasons = case["findings"]["memory_reasons"]
    assert any(r.startswith("user svc_deploy is suspected compromised") for r in reasons)
    assert case["priority"] == Priority.HIGH  # Talos said medium; memory raised it one step
