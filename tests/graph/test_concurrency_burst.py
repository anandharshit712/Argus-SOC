"""Graph-level concurrency proof (G11): many agent workers on a burst of alerts over two
tenants, all at once, against the real FalkorDB.

This is the graph half of tests/e2e/test_concurrency_burst.py (A): the agents here are
minimal stand-ins that call the graph tools library exactly the way LLD §6 describes, so the
test shows that the graph layer alone keeps the invariants.
"""

import asyncio
import itertools
from pathlib import Path

import pytest

from argus_soc.graph import read_queries as rq
from argus_soc.graph import write_queries as wq
from argus_soc.graph.falkor_client import run_read
from argus_soc.graph.graph_schema import (
    AWAITING_APPROVAL,
    CLOSED,
    INVESTIGATED,
    NEW,
    TRIAGED,
    AlertInput,
    DecisionInput,
    Label,
    Rel,
    SemanticFactsInput,
)
from argus_soc.graph.inventory_seed import inventory_path, load_inventory, seed_tenant

pytestmark = pytest.mark.falkordb
INVENTORY = Path(__file__).resolve().parents[2] / "data" / "inventory"
WORKERS = 4  # per role and tenant
TTL = 120

TENANTS = {
    "test": ("acme", ["bastion-01", "app-02", "web-01"]),
    "test_b": ("globex", ["vpn-gw", "gx-app-01"]),
}


def _burst(tenant: str, hosts: list[str]) -> list[AlertInput]:
    """15 alerts: 5 attackers x 3 alerts each (same IP, so each attacker is one case)."""
    alerts = []
    for attacker, n in itertools.product(range(5), range(3)):
        alerts.append(AlertInput(
            incident_id=f"{tenant}-a{attacker}-{n}", domain="network",
            category="network_brute_force", severity="high", confidence=0.8,
            succeeded=(n == 0 and attacker % 2 == 0),
            talos_created_at=f"2026-10-16T12:{attacker:02d}:{n:02d}+00:00",
            hosts=(hosts[(attacker + n) % len(hosts)],),
            source_ips=(f"203.0.113.{100 + attacker}",),
        ))  # fmt: skip
    return alerts


class Log:
    """What the stand-in workers did, to check afterwards."""

    def __init__(self) -> None:
        self.claims: list[tuple[str, int, str, str]] = []  # tenant, case, status, worker


async def triage(tenant: str, worker: str, log: Log) -> None:
    for alert in await rq.list_new_alerts(tenant, limit=50):
        linked = await rq.linked_alerts(tenant, alert["incident_id"])
        try:
            case_id = await wq.open_or_join_case(tenant, [alert["incident_id"], *linked], "high")
        except ValueError:
            continue  # another worker closed it meanwhile
        case = await rq.get_case(tenant, case_id)
        if case["status"] == NEW:  # never move a case back (LLD §6.2, Harshit's rule)
            await wq.set_case_status(tenant, case_id, TRIAGED)
        await wq.record_agent_run(tenant, "triage", case_id, "triaged", "investigator", worker)


async def investigator(tenant: str, worker: str, log: Log) -> bool:
    case_id = await wq.claim_case(tenant, TRIAGED, f"investigator@{worker}", TTL)
    if case_id is None:
        return False
    log.claims.append((tenant, case_id, TRIAGED, worker))
    case = await rq.get_case(tenant, case_id)
    succeeded = any(a["succeeded"] for a in case["alerts"])
    await wq.record_findings(tenant, case_id, {"succeeded": succeeded})
    await wq.record_semantic_facts(tenant, case_id, SemanticFactsInput(
        hosts=tuple(case["hosts"]), iocs=tuple(case["iocs"])))  # fmt: skip
    await wq.set_case_status(tenant, case_id, INVESTIGATED)
    await wq.record_agent_run(tenant, "investigator", case_id, "done", "responder", worker)
    return True


async def responder(tenant: str, worker: str, log: Log) -> bool:
    case_id = await wq.claim_case(tenant, INVESTIGATED, f"responder@{worker}", TTL)
    if case_id is None:
        return False
    log.claims.append((tenant, case_id, INVESTIGATED, worker))
    case = await rq.get_case(tenant, case_id)
    approve = bool(case["findings"].get("succeeded"))
    await wq.record_decision(tenant, case_id, DecisionInput(
        rule_id="R2" if approve else "R4", actions=("block_ips",), needs_approval=approve,
        reason="burst", target_iocs=tuple(case["iocs"])))  # fmt: skip
    await wq.set_case_status(tenant, case_id, AWAITING_APPROVAL if approve else CLOSED)
    await wq.record_agent_run(tenant, "responder", case_id, "decided", None, worker)
    return True


async def worker_loop(tenant: str, worker: str, log: Log) -> None:
    """One agents process: triage, then claim and work cases until nothing is left."""
    idle = 0
    while idle < 3:
        await triage(tenant, worker, log)
        did = await investigator(tenant, worker, log)
        did = await responder(tenant, worker, log) or did
        idle = 0 if did else idle + 1
        await asyncio.sleep(0)


@pytest.fixture
async def burst(live_db):
    alerts = {}
    for tenant, (inventory, hosts) in TENANTS.items():
        await seed_tenant(tenant, load_inventory(inventory_path(INVENTORY, inventory)))
        alerts[tenant] = _burst(tenant, hosts)
    # Talos reports arrive while the workers run: ingest everything concurrently too.
    await asyncio.gather(
        *(wq.upsert_alert_from_report(t, a) for t, al in alerts.items() for a in al)
    )
    log = Log()
    await asyncio.gather(*(
        worker_loop(tenant, f"w{n}", log) for tenant in TENANTS for n in range(WORKERS)
    ))  # fmt: skip
    return alerts, log


async def _rows(tenant: str, query: str) -> list[dict]:
    return await run_read(tenant, query)


ALERT_CASES = (
    f"MATCH (a:{Label.ALERT}) OPTIONAL MATCH (c:{Label.CASE})-[:{Rel.CONTAINS}]->(a) "
    "RETURN a.incident_id AS id, count(c) AS cases"
)
CASE_DECISIONS = (
    f"MATCH (c:{Label.CASE}) OPTIONAL MATCH (c)-[:{Rel.HAS_DECISION}]->(d) "
    "RETURN c.id AS id, count(d) AS n"
)
HOST_NAMES = f"MATCH (h:{Label.HOST}) RETURN h.hostname AS h"
ALERT_IDS = f"MATCH (a:{Label.ALERT}) RETURN a.incident_id AS id"


async def test_every_alert_is_in_exactly_one_case(burst):
    alerts, _ = burst
    for tenant, sent in alerts.items():
        rows = await _rows(tenant, ALERT_CASES)
        assert {r["id"] for r in rows} == {a.incident_id for a in sent}
        assert all(r["cases"] == 1 for r in rows), [r for r in rows if r["cases"] != 1]


async def test_one_case_per_attacker_and_all_finished(burst):
    for tenant in TENANTS:
        cases = await rq.list_cases(tenant)
        assert len(cases) == 5  # 5 attackers, 3 linked alerts each
        assert {c["alert_count"] for c in cases} == {3}
        assert {c["status"] for c in cases} <= {CLOSED, AWAITING_APPROVAL}


async def test_every_case_has_exactly_one_decision(burst):
    for tenant in TENANTS:
        rows = await _rows(tenant, CASE_DECISIONS)
        assert rows and all(r["n"] == 1 for r in rows), rows


async def test_no_case_was_claimed_twice_for_the_same_step(burst):
    _, log = burst
    steps = [(t, c, s) for t, c, s, _w in log.claims]
    assert len(steps) == len(set(steps)) == 2 * 5 * len(TENANTS)


async def test_work_was_shared_between_workers(burst):
    for tenant in TENANTS:
        workers = {r["worker"] for r in await rq.list_activity(tenant)}
        assert len(workers) > 1, f"{tenant}: only {workers} did any work"


async def test_tenants_share_nothing(burst):
    alerts, _ = burst
    for tenant, other in (("test", "test_b"), ("test_b", "test")):
        rows = await _rows(tenant, ALERT_IDS)
        assert not {r["id"] for r in rows} & {a.incident_id for a in alerts[other]}
        hosts = {
            r["h"] for r in await _rows(tenant, f"MATCH (h:{Label.HOST}) RETURN h.hostname AS h")
        }
        other_inventory = TENANTS[other][0]
        assert not any(h.startswith(f"{other_inventory}-") for h in hosts)
