"""Real FalkorDB learning writes: feedback, playbooks, IOC facts, semantic facts.

The last test runs scenario 2 (the learning loop) end to end on the real graph.
"""

from pathlib import Path

import pytest

from argus_soc.graph import read_queries as rq
from argus_soc.graph import write_queries as wq
from argus_soc.graph.falkor_client import run_read
from argus_soc.graph.graph_schema import (
    AWAITING_APPROVAL,
    CLOSED,
    AlertInput,
    Label,
    PlaybookRef,
    SemanticFactsInput,
)
from argus_soc.graph.inventory_seed import inventory_path, load_inventory, seed_tenant

pytestmark = pytest.mark.falkordb
INVENTORY = Path(__file__).resolve().parents[2] / "data" / "inventory"
SCANNER = "10.0.5.20"


def _scan(iid: str, at: str) -> AlertInput:
    return AlertInput(
        incident_id=iid, domain="web", category="auth_failure", severity="medium",
        confidence=0.72, succeeded=False, talos_created_at=at, hosts=("web-01",),
        endpoints=("/login",), source_ips=(SCANNER,),
    )  # fmt: skip


@pytest.fixture
async def acme(live_db):
    await seed_tenant("test", load_inventory(inventory_path(INVENTORY, "acme")))
    return "test"


@pytest.fixture
async def attack(acme, s1):
    """Scenario 1 case with decision R1 waiting for approval."""
    for alert in (s1.brute_force, s1.stuffing):
        await wq.upsert_alert_from_report(acme, alert)
    cid = await wq.open_or_join_case(acme, ["inc-7f3a", "inc-81c2"], "high")
    await wq.record_decision(acme, cid, s1.r1)
    await wq.set_case_status(acme, cid, AWAITING_APPROVAL)
    return cid


async def _flags(tenant: str) -> dict:
    rows = await run_read(
        tenant,
        f"MATCH (h:{Label.HOST} {{hostname: 'bastion-01'}}), "
        f"(u:{Label.USER} {{username: 'svc_deploy'}}), (i:{Label.IOC} {{value: '203.0.113.7'}}) "
        "RETURN h.isolated AS isolated, u.disabled AS disabled, i.verdict AS verdict",
    )
    return rows[0]


# --- record_feedback --------------------------------------------------------------------


async def test_approve_runs_the_simulated_actions(acme, attack):
    assert await _flags(acme) == {"isolated": False, "disabled": False, "verdict": "unknown"}
    fid = await wq.record_feedback(acme, attack, "approve", "go ahead", "acme.analyst")
    case = await rq.get_case(acme, attack)
    assert case["decision"]["outcome"] == "approved"
    assert case["feedback"] == [{"id": fid, "verdict": "approve", "note": "go ahead",
                                 "analyst": "acme.analyst",
                                 "created_at": case["feedback"][0]["created_at"]}]  # fmt: skip
    assert await _flags(acme) == {"isolated": True, "disabled": True, "verdict": "malicious"}


async def test_reject_changes_no_target(acme, attack):
    await wq.record_feedback(acme, attack, "reject", "false alarm", "acme.analyst")
    assert (await rq.get_case(acme, attack))["decision"]["outcome"] == "rejected"
    assert await _flags(acme) == {"isolated": False, "disabled": False, "verdict": "unknown"}


async def test_a_decided_case_is_not_decided_twice(acme, attack):
    await wq.record_feedback(acme, attack, "reject", "no", "acme.analyst")
    await wq.record_feedback(acme, attack, "approve", "changed my mind", "acme.analyst")
    assert (await rq.get_case(acme, attack))["decision"]["outcome"] == "rejected"
    assert (await _flags(acme))["isolated"] is False  # the approve came too late
    assert len((await rq.get_case(acme, attack))["feedback"]) == 2  # both are recorded


async def test_feedback_errors(acme, attack):
    with pytest.raises(KeyError):
        await wq.record_feedback(acme, 999, "approve", "", "acme.analyst")
    with pytest.raises(ValueError):
        await wq.record_feedback(acme, attack, "maybe", "", "acme.analyst")


# --- create_playbook_version --------------------------------------------------------------


async def test_playbook_versions(acme):
    await wq.upsert_alert_from_report(acme, _scan("inc-9b10", "2026-10-15T09:10:00+00:00"))
    cid = await wq.open_or_join_case(acme, ["inc-9b10"], "medium")
    first = await wq.record_feedback(acme, cid, "benign", "scanner", "acme.analyst")
    second = await wq.record_feedback(acme, cid, "benign", "scanner again", "acme.analyst")
    condition = {"category": "auth_failure", "ioc_in": [SCANNER]}
    v1 = await wq.create_playbook_version(acme, first, condition, "auto_close")
    assert v1 == {"name": f"auto-close auth_failure learned from case {cid}", "version": 1}
    assert await wq.create_playbook_version(acme, first, {"category": "x"}, "auto_close") == v1
    # Same condition (list order does not matter) -> next version of the same playbook.
    reordered = {"ioc_in": [SCANNER], "category": "auth_failure"}
    v2 = await wq.create_playbook_version(acme, second, reordered, "auto_close")
    assert v2 == {"name": v1["name"], "version": 2}
    books = await rq.list_playbooks(acme)
    assert [(p["version"], p["active"], p["learned_from"]) for p in books] == [
        (1, False, first), (2, True, second),
    ]  # fmt: skip
    assert books[1]["source_case"] == cid and books[1]["condition"]["ioc_in"] == [SCANNER]
    with pytest.raises(KeyError):
        await wq.create_playbook_version(acme, "fb-nope", {}, "auto_close")
    with pytest.raises(ValueError):
        await wq.create_playbook_version(acme, first, {}, "delete_everything")


# --- set_ioc_fact, record_semantic_facts ---------------------------------------------------


async def test_set_ioc_fact(acme):
    await wq.set_ioc_fact(acme, SCANNER, "owner", "internal pentest scanner")
    await wq.set_ioc_fact(acme, SCANNER, "verdict", "benign")
    await wq.set_ioc_fact(acme, "192.0.2.50", "verdict", "malicious")  # new IOC is created
    facts = await rq.entity_facts(acme, [], [], [SCANNER, "192.0.2.50"])
    assert facts["iocs"][SCANNER] == {"verdict": "benign", "owner": "internal pentest scanner",
                                      "seen_case_ids": []}  # fmt: skip
    assert facts["iocs"]["192.0.2.50"]["verdict"] == "malicious"
    with pytest.raises(ValueError):
        await wq.set_ioc_fact(acme, SCANNER, "colour", "red")
    with pytest.raises(ValueError):
        await wq.set_ioc_fact(acme, SCANNER, "verdict", "spooky")


async def test_semantic_facts_are_idempotent(acme, attack, s1):
    facts = SemanticFactsInput(hosts=("bastion-01", "app-02"), iocs=(s1.attacker,),
                               suspected_users=("svc_deploy",))  # fmt: skip
    await wq.record_semantic_facts(acme, attack, facts)
    first = await rq.entity_facts(acme, ["bastion-01", "app-02"], ["svc_deploy"], [s1.attacker])
    await wq.record_semantic_facts(acme, attack, facts)  # a retried Investigator step
    assert await rq.entity_facts(acme, ["bastion-01", "app-02"], ["svc_deploy"],
                                 [s1.attacker]) == first  # fmt: skip
    assert first["hosts"]["bastion-01"]["targeted_case_ids"] == [attack]
    assert first["iocs"][s1.attacker]["seen_case_ids"] == [attack]
    user = first["users"]["svc_deploy"]
    assert (user["suspected_compromised"], user["suspect_case_id"]) == (True, attack)
    with pytest.raises(KeyError):
        await wq.record_semantic_facts(acme, 999, facts)


async def test_times_targeted_counts_cases(acme, s1):
    await wq.upsert_alert_from_report(acme, s1.brute_force)
    one = await wq.open_or_join_case(acme, ["inc-7f3a"], "high")
    await wq.set_case_status(acme, one, CLOSED)
    await wq.upsert_alert_from_report(acme, s1.stuffing)
    two = await wq.open_or_join_case(acme, ["inc-81c2"], "medium")
    for cid in (one, two):
        await wq.record_semantic_facts(acme, cid, SemanticFactsInput(hosts=("bastion-01",)))
    facts = await rq.entity_facts(acme, ["bastion-01"], [], [])
    assert facts["hosts"]["bastion-01"]["targeted_case_ids"] == [one, two]  # targeted twice


# --- Scenario 2: the learning loop, end to end ---------------------------------------------


async def test_scenario_2_learning_loop(acme):
    """Session 1: analyst marks the scanner benign -> playbook. Session 2: the same burst is
    auto-closed by that playbook, citing it, without the Investigator or Responder."""
    t = acme
    await wq.upsert_alert_from_report(t, _scan("inc-9b10", "2026-10-15T09:10:00+00:00"))
    (alert,) = await rq.list_new_alerts(t)
    assert await rq.matching_playbook(t, alert) is None  # nothing learned yet
    case_32 = await wq.open_or_join_case(t, ["inc-9b10"], "medium")
    fid = await wq.record_feedback(t, case_32, "benign", "internal pentest scanner", "acme.analyst")
    await wq.set_case_status(t, case_32, CLOSED)
    pb = await wq.create_playbook_version(
        t, fid, {"category": alert["category"], "ioc_in": alert["iocs"]}, "auto_close"
    )
    await wq.set_ioc_fact(t, SCANNER, "owner", "internal pentest scanner")

    # Session 2 (a restart changes nothing: everything above is in the graph).
    await wq.upsert_alert_from_report(t, _scan("inc-a412", "2026-10-16T11:00:00+00:00"))
    (again,) = await rq.list_new_alerts(t)
    match = await rq.matching_playbook(t, again)
    assert (match["name"], match["version"], match["source_case"]) == (pb["name"], 1, case_32)
    ref = PlaybookRef(name=match["name"], version=match["version"])
    case_33 = await wq.close_case_auto(t, [again["incident_id"]], ref,
                                       f"Playbook v1, learned from Case {case_32}")  # fmt: skip
    summary = (await rq.list_cases(t, status="auto_closed"))[0]
    assert (summary["id"], summary["auto_closed_by"]) == (case_33, f"{pb['name']} v1")
    memory = await rq.recall(t, ioc=SCANNER)
    assert [m["case_id"] for m in memory][-1] == case_32
    assert memory[-1]["note"] == "internal pentest scanner"
    facts = await rq.entity_facts(t, [], [], [SCANNER])
    assert facts["iocs"][SCANNER]["verdict"] == "benign"
    assert facts["iocs"][SCANNER]["owner"] == "internal pentest scanner"
