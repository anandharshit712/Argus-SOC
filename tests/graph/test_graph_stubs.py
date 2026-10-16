"""Behaviour of the stub graph library, used through `argus_soc.graph` as A and C will."""

import pytest
from pydantic import ValidationError

from argus_soc import graph
from argus_soc.core.settings import get_settings
from argus_soc.core.tenant_registry import UnknownTenant
from argus_soc.graph import graph_stubs
from argus_soc.graph.graph_schema import (
    AUTO_CLOSED,
    CLOSED,
    INVESTIGATED,
    TRIAGED,
    AlertInput,
    DecisionInput,
    PlaybookRef,
    SemanticFactsInput,
)
from argus_soc.graph.graph_stubs import ATTACKER_IP, SCANNER_IP, SCANNER_PLAYBOOK


@pytest.fixture(autouse=True)
def stub_backend(monkeypatch):
    monkeypatch.setenv("ARGUS_GRAPH_BACKEND", "stub")
    get_settings.cache_clear()
    graph_stubs.reset_stubs()
    yield
    graph_stubs.reset_stubs()


def _alert(iid: str, **kw) -> AlertInput:
    base = dict(incident_id=iid, domain="web", category="injection", severity="high",
                confidence=0.9, talos_created_at="2026-10-16T12:00:00+00:00",
                hosts=("web-01",), source_ips=("198.51.100.99",))  # fmt: skip
    return AlertInput(**{**base, **kw})


# --- Sample data --------------------------------------------------------------


async def test_unknown_tenant_is_rejected():
    with pytest.raises(UnknownTenant):
        await graph.list_cases("initech")


async def test_sample_cases():
    cases = await graph.list_cases("acme")
    assert [c["id"] for c in cases] == [31, 32]  # newest first
    assert cases[0]["needs_approval"] is True and cases[0]["status"] == "awaiting_approval"
    assert await graph.list_cases("acme", status="closed") == [cases[1]]
    assert await graph.list_cases("globex") == []


async def test_new_alerts_and_known_ids():
    new = await graph.list_new_alerts("acme")
    assert [a["incident_id"] for a in new] == ["inc-a412", "inc-c5e0"]  # oldest first
    known = await graph.known_incident_ids("acme", ["inc-7f3a", "inc-zzzz"])
    assert known == {"inc-7f3a"}


async def test_case_31_detail():
    case = await graph.get_case("acme", 31)
    assert [a["incident_id"] for a in case["alerts"]] == ["inc-7f3a", "inc-81c2"]
    assert case["iocs"] == [ATTACKER_IP] and case["users"] == ["svc_deploy"]
    assert case["decision"]["rule_id"] == "R1"
    assert [r["agent"] for r in case["agent_runs"]] == ["triage", "investigator", "responder"]
    assert await graph.get_case("acme", 999) is None


async def test_reads_return_copies():
    case = await graph.get_case("acme", 31)
    case["alerts"].clear()
    assert len((await graph.get_case("acme", 31))["alerts"]) == 2


# --- Q1-Q6 ---------------------------------------------------------------------


async def test_q1_blast_radius():
    rows = await graph.blast_radius("acme", ATTACKER_IP)
    assert [r["host"] for r in rows] == ["app-02", "bastion-01"]  # most critical first
    bastion = rows[1]
    assert bastion["accounts"] == ["svc_deploy"]
    assert bastion["reached_hosts"] == ["app-02", "bastion-01"]


async def test_q2_paths():
    assert await graph.paths_to_crown_jewels("acme", "bastion-01") == [
        ["bastion-01", "app-02", "db-prod-01"]
    ]
    assert await graph.paths_to_crown_jewels("acme", "bastion-01", max_hops=1) == []
    assert await graph.paths_to_crown_jewels("acme", "web-01") == []


async def test_q3_rank_hosts():
    ranking = await graph.rank_hosts("acme", 31)
    assert ranking[0][0] == "bastion-01"
    assert [h for h, _ in ranking] == ["bastion-01", "app-02"]


async def test_q4_recall_and_tenant_isolation():
    hits = await graph.recall("acme", ioc=[SCANNER_IP])
    assert hits == [{"case_id": 32, "verdict": "benign", "closed_at": "2026-10-15T09:40:00+00:00",
                     "note": "internal pentest scanner"}]  # fmt: skip
    assert await graph.recall("acme", ioc=ATTACKER_IP) == []  # case 31 is still open
    assert await graph.recall("globex", ioc=SCANNER_IP) == []  # Globex never saw Acme's cases


async def test_q5_linked_alerts():
    assert await graph.linked_alerts("acme", "inc-7f3a") == ["inc-81c2"]
    assert await graph.linked_alerts("acme", "inc-7f3a", window_hours=0) == []
    assert await graph.linked_alerts("acme", "inc-nope") == []


async def test_q6_explain_decision():
    out = await graph.explain_decision("acme", "dec-31")
    assert out["path"] == ["bastion-01", "app-02", "db-prod-01"]
    assert out["acted_on"] == {"hosts": ["bastion-01"], "users": ["svc_deploy"],
                               "iocs": [ATTACKER_IP]}  # fmt: skip
    assert await graph.explain_decision("acme", "dec-nope") is None


async def test_entity_facts():
    facts = await graph.entity_facts("acme", ["bastion-01", "web-01"], ["svc_deploy"],
                                     [SCANNER_IP])  # fmt: skip
    assert facts["hosts"]["bastion-01"]["targeted_case_ids"] == [31]
    assert facts["hosts"]["web-01"]["targeted_case_ids"] == []
    assert facts["users"]["svc_deploy"]["suspected_compromised"] is True
    assert facts["iocs"][SCANNER_IP]["verdict"] == "benign"


# --- Scenario 2: learning loop ----------------------------------------------------


async def test_playbook_auto_closes_the_scanner():
    (alert, _sqli) = await graph.list_new_alerts("acme")
    pb = await graph.matching_playbook("acme", alert)
    assert (pb["name"], pb["version"], pb["source_case"]) == (SCANNER_PLAYBOOK, 1, 32)
    ref = PlaybookRef(name=pb["name"], version=pb["version"])
    case_id = await graph.close_case_auto("acme", [alert["incident_id"]], ref, "playbook v1")
    case = await graph.get_case("acme", case_id)
    assert case["status"] == AUTO_CLOSED
    assert case["auto_closed_by"] == f"{SCANNER_PLAYBOOK} v1"
    assert [a["incident_id"] for a in await graph.list_new_alerts("acme")] == ["inc-c5e0"]


async def test_benign_feedback_makes_a_new_playbook_version():
    fb = await graph.record_feedback("acme", 32, "benign", "still the scanner", "analyst1")
    condition = {"category": "auth_failure", "ioc_in": [SCANNER_IP]}
    assert await graph.create_playbook_version("acme", fb, condition, "auto_close") == {
        "name": SCANNER_PLAYBOOK,
        "version": 2,
    }
    books = await graph.list_playbooks("acme")
    assert [(p["version"], p["active"]) for p in books] == [(1, False), (2, True)]
    pb = await graph.matching_playbook("acme", {"category": "auth_failure", "iocs": [SCANNER_IP]})
    assert pb["version"] == 2


async def test_approve_applies_the_decision():
    await graph.record_feedback("acme", 31, "approve", "go", "analyst1")
    case = await graph.get_case("acme", 31)
    assert case["decision"]["outcome"] == "approved"
    state = graph_stubs._STATE["acme"]
    assert state["hosts"]["bastion-01"]["isolated"] is True  # simulated only
    assert state["users"]["svc_deploy"]["disabled"] is True
    assert state["iocs"][ATTACKER_IP]["verdict"] == "malicious"


async def test_reject_applies_nothing():
    await graph.record_feedback("acme", 31, "reject", "false alarm", "analyst1")
    assert (await graph.get_case("acme", 31))["decision"]["outcome"] == "rejected"
    assert "isolated" not in graph_stubs._STATE["acme"]["hosts"]["bastion-01"]


# --- Scenario 3: a new alert through all three agents ------------------------------


async def test_full_pipeline_for_a_new_alert():
    t = "acme"
    case_id = await graph.open_or_join_case(t, ["inc-c5e0"], "high")
    assert await graph.open_or_join_case(t, ["inc-c5e0"], "high") == case_id  # joins, not new
    await graph.set_case_status(t, case_id, TRIAGED, "high")
    await graph.record_agent_run(t, "triage", case_id, "new case", handed_to="investigator")

    assert await graph.claim_case(t, TRIAGED, "investigator@w1", 120) == case_id
    assert await graph.claim_case(t, TRIAGED, "investigator@w2", 120) is None  # taken
    await graph.record_findings(t, case_id, {"succeeded": False, "path_to_crown_jewel": False})
    facts = SemanticFactsInput(hosts=("web-01",), iocs=("198.51.100.23",))
    await graph.record_semantic_facts(t, case_id, facts)
    await graph.record_semantic_facts(t, case_id, facts)  # twice: no duplicate
    await graph.set_case_status(t, case_id, INVESTIGATED)

    assert await graph.claim_case(t, INVESTIGATED, "responder@w1", 120) == case_id
    decision = DecisionInput(rule_id="R4", actions=("block_or_rate_limit_ips", "open_ticket"),
                             needs_approval=False, reason="no success, no path",
                             target_iocs=("198.51.100.23",))  # fmt: skip
    await graph.record_decision(t, case_id, decision)
    await graph.set_case_status(t, case_id, CLOSED, "medium")

    case = await graph.get_case(t, case_id)
    assert (case["status"], case["priority"], case["claimed_by"]) == ("closed", "medium", None)
    assert case["closed_at"] and case["decision"]["outcome"] == "auto"
    facts_now = await graph.entity_facts(t, ["web-01"], [], ["198.51.100.23"])
    assert facts_now["hosts"]["web-01"]["targeted_case_ids"] == [case_id]
    assert facts_now["iocs"]["198.51.100.23"]["seen_case_ids"] == [case_id]


async def test_expired_claim_can_be_taken_again():
    await graph.set_case_status("acme", 31, TRIAGED)
    assert await graph.claim_case("acme", TRIAGED, "investigator@w1", 120) == 31
    graph_stubs._STATE["acme"]["cases"][31]["claimed_at"] = "2000-01-01T00:00:00+00:00"
    assert await graph.claim_case("acme", TRIAGED, "investigator@w2", 120) == 31


async def test_activity_since():
    runs = await graph.list_activity("acme")
    assert [r["agent"] for r in runs] == ["triage", "investigator", "responder"]
    later = await graph.list_activity("acme", since=runs[-1]["at"])
    assert later == []


# --- Ingestion and validation --------------------------------------------------------


async def test_upsert_is_idempotent_and_keeps_status():
    await graph.upsert_alert_from_report("acme", _alert("inc-new1"))
    await graph.upsert_alert_from_report("acme", _alert("inc-new1"))
    new = [a["incident_id"] for a in await graph.list_new_alerts("acme")]
    assert new.count("inc-new1") == 1
    await graph.open_or_join_case("acme", ["inc-new1"], "high")
    await graph.upsert_alert_from_report("acme", _alert("inc-new1"))  # seen again later
    assert "inc-new1" not in [a["incident_id"] for a in await graph.list_new_alerts("acme")]


def test_alert_input_limits_attacker_text():
    with pytest.raises(ValidationError):
        _alert("inc-x", evidence=("x" * 501,))
    with pytest.raises(ValidationError):
        _alert("inc-x", evidence=tuple("e" for _ in range(21)))
    with pytest.raises(ValidationError):
        _alert("inc-x", confidence=1.5)


@pytest.mark.parametrize(
    "call",
    [
        lambda: graph.set_case_status("acme", 31, "awaiting-approval"),
        lambda: graph.set_case_status("acme", 31, TRIAGED, "urgent"),
        lambda: graph.record_feedback("acme", 31, "maybe", "", "a"),
        lambda: graph.set_ioc_fact("acme", SCANNER_IP, "colour", "red"),
        lambda: graph.set_ioc_fact("acme", SCANNER_IP, "verdict", "spooky"),
        lambda: graph.claim_case("acme", "pending", "x", 10),
    ],
    ids=["status", "priority", "verdict", "fact-key", "fact-verdict", "claim-status"],
)
async def test_bad_values_are_rejected(call):
    with pytest.raises(ValueError):
        await call()


async def test_missing_case_is_a_key_error():
    with pytest.raises(KeyError):
        await graph.set_case_status("acme", 999, TRIAGED)


# --- Linking rules and the closed-case safety net (Harshit's report, Oct 16) -----------


async def test_auto_closed_alert_is_not_pulled_into_a_new_case():
    """inc-a412 (scanner) is auto-closed; inc-c5e0 (SQLi) on the same host must not grab it."""
    ref = PlaybookRef(name=SCANNER_PLAYBOOK, version=1)
    auto = await graph.close_case_auto("acme", ["inc-a412"], ref, "playbook v1")
    assert await graph.linked_alerts("acme", "inc-c5e0") == []
    sqli_case = await graph.open_or_join_case("acme", ["inc-c5e0", "inc-a412"], "high")
    assert [a["incident_id"] for a in (await graph.get_case("acme", sqli_case))["alerts"]] == [
        "inc-c5e0"
    ]
    assert [a["incident_id"] for a in (await graph.get_case("acme", auto))["alerts"]] == [
        "inc-a412"
    ]


async def test_a_shared_host_alone_does_not_link():
    # Both new, both on web-01, different source IPs and no users in common.
    assert await graph.linked_alerts("acme", "inc-a412") == []
    assert await graph.linked_alerts("acme", "inc-c5e0") == []


async def test_closed_case_alerts_are_never_linked():
    await graph.upsert_alert_from_report(
        "acme", _alert("inc-again", source_ips=(SCANNER_IP,), hosts=("web-02",))
    )
    # inc-9b10 (case 32, closed) and inc-a412 (new) share the scanner IP; only the new one links.
    assert await graph.linked_alerts("acme", "inc-again") == ["inc-a412"]


async def test_cases_refuse_alerts_that_are_all_closed():
    ref = PlaybookRef(name=SCANNER_PLAYBOOK, version=1)
    with pytest.raises(ValueError):
        await graph.open_or_join_case("acme", ["inc-9b10"], "low")  # case 32 is closed
    with pytest.raises(ValueError):
        await graph.close_case_auto("acme", ["inc-9b10"], ref, "again")


# --- GAP-5: the priority before the decision -------------------------------------------


async def test_sample_decision_has_previous_priority():
    assert (await graph.get_case("acme", 31))["decision"]["previous_priority"] == "high"


async def test_previous_priority_round_trip():
    case_id = await graph.open_or_join_case("acme", ["inc-c5e0"], "high")
    r4 = DecisionInput(rule_id="R4", actions=("open_ticket",), needs_approval=False,
                       reason="no success, no path", previous_priority="high")  # fmt: skip
    await graph.record_decision("acme", case_id, r4)
    await graph.set_case_status("acme", case_id, "closed", "medium")
    case = await graph.get_case("acme", case_id)
    assert (case["decision"]["previous_priority"], case["priority"]) == ("high", "medium")
    explained = await graph.explain_decision("acme", case["decision"]["id"])
    assert explained["decision"]["previous_priority"] == "high"


def test_previous_priority_is_optional_and_checked():
    assert (
        DecisionInput(rule_id="R1", actions=(), needs_approval=True, reason="x").previous_priority
        is None
    )
    with pytest.raises(ValidationError):
        DecisionInput(rule_id="R1", actions=(), needs_approval=True, reason="x",
                      previous_priority="urgent")  # fmt: skip
