"""Investigator agent (docs/LLD.md §6.3): how far could this attack go?

1. Blast radius (Q1) of every IOC in the case: hosts hit, accounts used, hosts those accounts
   log into.
2. Paths to crown jewels (Q2): from the case's own hosts first; only if none has a path, from
   the hosts its accounts reach.
3. Store the findings and the semantic facts (hosts targeted, IOCs seen, users suspected
   compromised), then hand the case to the Responder.

The decision later reads only `succeeded` and `path_to_crown_jewel`, both from fixed queries,
so it never depends on the optional LLM deep dive (§6.9).
"""

from typing import Any

from argus_soc import graph
from argus_soc.agents.graph_tool_client import deep_dive
from argus_soc.agents.handoff_service import hand_off
from argus_soc.agents.priority_rules import case_priority
from argus_soc.core.logging_setup import get_logger
from argus_soc.core.settings import get_settings
from argus_soc.graph.graph_schema import AgentName, CaseStatus, SemanticFactsInput

AGENT = AgentName.INVESTIGATOR


async def _paths(tenant: str, hosts: list[str]) -> list[list[str]]:
    """Every path from these hosts to a crown jewel, shortest first."""
    hops = get_settings().max_path_hops
    paths = [p for h in hosts for p in await graph.paths_to_crown_jewels(tenant, h, hops)]
    return sorted(paths, key=lambda p: (len(p), p))


async def investigate(tenant: str, case: dict[str, Any]) -> dict[str, Any]:
    """The findings for one case (LLD §6.3, key names fixed by CONTRACT_GAPS GAP-6)."""
    radius = [row for ioc in case["iocs"] for row in await graph.blast_radius(tenant, ioc)]
    reached = sorted({h for row in radius for h in row["reached_hosts"]} - set(case["hosts"]))
    # The case's own hosts tell the clearest story (bastion-01 -> app-02 -> db-prod-01);
    # hosts reached through a compromised account only count when those have no path.
    paths = await _paths(tenant, case["hosts"]) or await _paths(tenant, reached)
    return {
        "succeeded": any(a["succeeded"] for a in case["alerts"]),
        "path_to_crown_jewel": bool(paths),
        "shortest_path": paths[0] if paths else None,
        "blast_radius": radius,
    }


async def run(tenant: str, case_id: int) -> None:
    log = get_logger(__name__, tenant=tenant, agent=AGENT, case_id=case_id)
    case = await graph.get_case(tenant, case_id)
    if case is None:
        log.warning("claimed case %s does not exist", case_id)
        return
    findings = await investigate(tenant, case)
    # The fixed queries above always run first; the LLM's lookups are extra evidence only.
    findings["deep_dive"] = await deep_dive(tenant, case, findings)
    await graph.record_findings(tenant, case_id, findings)
    # Only accounts in alerts that succeeded are suspected: in scenario 1 that is svc_deploy,
    # not the customer e-mails the credential stuffing tried.
    suspected = sorted({u for a in case["alerts"] if a["succeeded"] for u in a["users"]})
    await graph.record_semantic_facts(
        tenant,
        case_id,
        SemanticFactsInput(
            hosts=tuple(case["hosts"]), iocs=tuple(case["iocs"]), suspected_users=tuple(suspected)
        ),
    )
    path = " -> ".join(findings["shortest_path"] or []) or "none"
    await hand_off(
        tenant,
        case_id,
        agent=AGENT,
        status=CaseStatus.INVESTIGATED,
        priority=case_priority(case),
        handed_to=AgentName.RESPONDER,
        summary=(
            f"case {case_id}: succeeded={findings['succeeded']}, path to crown jewel: {path}, "
            f"{len(findings['blast_radius'])} hosts in blast radius"
            + (f", suspected compromised: {', '.join(suspected)}" if suspected else "")
        ),
        tool_calls=findings["deep_dive"],
    )
    log.info("investigated: path %s", path)
