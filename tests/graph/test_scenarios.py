"""Demo scenarios 3 and 4 on the real graph (1 and 2 are in test_write_queries.py and
test_learning_queries.py). The agents' steps are written out the way LLD §6 describes."""

from pathlib import Path

import pytest

from argus_soc.graph import algorithm_queries as aq
from argus_soc.graph import read_queries as rq
from argus_soc.graph import write_queries as wq
from argus_soc.graph.falkor_client import run_read
from argus_soc.graph.graph_schema import (
    CLOSED,
    INVESTIGATED,
    TRIAGED,
    AlertInput,
    DecisionInput,
    Label,
    SemanticFactsInput,
)
from argus_soc.graph.inventory_seed import inventory_path, load_inventory, seed_tenant

pytestmark = pytest.mark.falkordb
INVENTORY = Path(__file__).resolve().parents[2] / "data" / "inventory"
SQLI_IP = "198.51.100.23"


async def _seed(tenant: str, inventory: str) -> None:
    await seed_tenant(tenant, load_inventory(inventory_path(INVENTORY, inventory)))


async def test_scenario_3_sqli_with_no_way_in(live_db):
    """SQLi on web-01 that did not succeed: web-01 has no path to a crown jewel, so the
    Responder takes the low-impact rule (R4) without approval and lowers the priority."""
    t = "test"
    await _seed(t, "acme")
    sqli = AlertInput(
        incident_id="inc-c5e0", domain="web", category="injection", severity="high",
        confidence=0.88, succeeded=False, talos_created_at="2026-10-16T11:05:00+00:00",
        hosts=("web-01",), endpoints=("/api/search",), source_ips=(SQLI_IP,),
        recommended_actions=(f"block source IP {SQLI_IP}",),
    )  # fmt: skip
    await wq.upsert_alert_from_report(t, sqli)

    # Triage: nothing remembered, nothing linked -> new case.
    assert await rq.recall(t, ioc=SQLI_IP, host="web-01") == []
    assert await rq.linked_alerts(t, "inc-c5e0") == []
    cid = await wq.open_or_join_case(t, ["inc-c5e0"], "high")
    await wq.set_case_status(t, cid, TRIAGED)

    # Investigator: blast radius and paths.
    assert await wq.claim_case(t, TRIAGED, "investigator@w1", 120) == cid
    radius = await rq.blast_radius(t, SQLI_IP)
    assert [r["host"] for r in radius] == ["web-01"] and radius[0]["accounts"] == []
    assert await aq.paths_to_crown_jewels(t, "web-01") == []
    findings = {"succeeded": False, "path_to_crown_jewel": False, "blast_radius": radius}
    await wq.record_findings(t, cid, findings)
    await wq.record_semantic_facts(t, cid, SemanticFactsInput(hosts=("web-01",), iocs=(SQLI_IP,)))
    await wq.set_case_status(t, cid, INVESTIGATED)

    # Responder: R4, automatic, priority one step lower.
    assert await wq.claim_case(t, INVESTIGATED, "responder@w1", 120) == cid
    assert await aq.rank_hosts(t, cid) == [("web-01", 1.0)]
    r4 = DecisionInput(rule_id="R4", actions=("block_or_rate_limit_ips", "open_ticket"),
                       needs_approval=False, reason="no success, no path",
                       target_iocs=(SQLI_IP,))  # fmt: skip
    await wq.record_decision(t, cid, r4)
    await wq.set_case_status(t, cid, CLOSED, "medium")

    case = await rq.get_case(t, cid)
    assert (case["status"], case["priority"], case["needs_approval"]) == ("closed", "medium", False)
    assert case["decision"]["outcome"] == "auto" and case["decision"]["target_hosts"] == []
    host = await run_read(
        t, f"MATCH (h:{Label.HOST} {{hostname: 'web-01'}}) RETURN h.isolated AS i"
    )
    assert host == [{"i": False}]  # nothing to isolate: no host was a target
    facts = await rq.entity_facts(t, ["web-01"], [], [SQLI_IP])
    assert facts["hosts"]["web-01"]["targeted_case_ids"] == [cid]  # remembered for next time


async def test_scenario_4_tenant_isolation(live_db, s1):
    """Acme already knows the attacker (case closed, IOC malicious). The same attacker then
    hits Globex's vpn-gw: Globex has no memory of it and none of Acme's hosts."""
    acme, globex = "test", "test_b"
    await _seed(acme, "acme")
    await _seed(globex, "globex")

    await wq.upsert_alert_from_report(acme, s1.brute_force)
    acme_case = await wq.open_or_join_case(acme, ["inc-7f3a"], "high")
    await wq.record_decision(acme, acme_case, s1.r1)
    await wq.record_feedback(acme, acme_case, "approve", "confirmed", "acme.analyst")
    await wq.set_case_status(acme, acme_case, CLOSED)
    assert (await rq.recall(acme, ioc=s1.attacker))[0]["case_id"] == acme_case

    hit = AlertInput(
        incident_id="inc-d901", domain="network", category="network_brute_force",
        severity="medium", confidence=0.72, succeeded=False,
        talos_created_at="2026-10-16T11:10:00+00:00", hosts=("vpn-gw",), users=("admin",),
        source_ips=(s1.attacker,),
    )  # fmt: skip
    await wq.upsert_alert_from_report(globex, hit)

    assert await rq.recall(globex, ioc=s1.attacker) == []  # no memory across tenants
    facts = await rq.entity_facts(globex, [], [], [s1.attacker])
    assert facts["iocs"][s1.attacker]["verdict"] == "unknown"
    acme_facts = await rq.entity_facts(acme, [], [], [s1.attacker])
    assert acme_facts["iocs"][s1.attacker]["verdict"] == "malicious"
    assert await rq.linked_alerts(globex, "inc-d901") == []  # inc-7f3a lives in Acme only
    assert [r["host"] for r in await rq.blast_radius(globex, s1.attacker)] == ["vpn-gw"]
    paths = await aq.paths_to_crown_jewels(globex, "vpn-gw")
    assert paths and paths[0][-1] == "gx-db-01"  # Globex's own crown jewel
    assert await aq.paths_to_crown_jewels(globex, "bastion-01") == []  # an Acme host
