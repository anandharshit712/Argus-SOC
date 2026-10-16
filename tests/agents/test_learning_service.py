from argus_soc import graph
from argus_soc.agents import agent_runner, learning_service
from argus_soc.graph.graph_schema import AlertInput, CaseStatus

SCANNER = "10.0.5.99"  # a new internal scanner, unknown to the stub sample data


async def _closed_scanner_case() -> int:
    await graph.upsert_alert_from_report(
        "acme",
        AlertInput(
            incident_id="inc-scan",
            domain="web",
            category="auth_failure",
            severity="medium",
            confidence=0.7,
            talos_created_at="2026-10-16T12:00:00+00:00",
            hosts=("acme-edge-001",),
            source_ips=(SCANNER,),
        ),
    )
    while await agent_runner.run_once("acme"):
        pass
    for row in await graph.list_cases("acme"):
        case = await graph.get_case("acme", row["id"])
        if "inc-scan" in [a["incident_id"] for a in case["alerts"]]:
            assert case["status"] == CaseStatus.CLOSED  # R4, no approval needed
            return case["id"]
    raise AssertionError("scanner case not found")


async def test_benign_feedback_learns_a_playbook_and_the_next_alert_auto_closes():
    case_id = await _closed_scanner_case()
    fid = await graph.record_feedback("acme", case_id, "benign", "internal scanner", "acme.analyst")

    learned = await learning_service.on_feedback("acme", case_id, fid)
    assert learned is not None and learned.endswith("v1")
    facts = await graph.entity_facts("acme", [], [], [SCANNER])
    assert facts["iocs"][SCANNER]["owner"] == "internal scanner"

    alert = {"category": "auth_failure", "iocs": [SCANNER]}
    assert await graph.matching_playbook("acme", alert) is not None


async def test_approve_learns_no_playbook():
    case_id = await _closed_scanner_case()
    fid = await graph.record_feedback("acme", case_id, "approve", "", "acme.analyst")
    assert await learning_service.on_feedback("acme", case_id, fid) is None
