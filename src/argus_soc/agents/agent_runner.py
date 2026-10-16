"""Agents process (docs/LLD.md §6.1): `argus-agents`.

For each tenant: Triage works on new alerts; the Investigator and the Responder each claim
one case in their status and work on it. A claim is a single graph write that expires after
AGENT_CLAIM_TTL_SECONDS, so a crashed worker's case is picked up again, and several runner
containers can share the work (`docker compose up --scale agents=2`). Nothing is kept in
memory between steps: a restarted runner carries on from the graph.
"""

import asyncio

from argus_soc import graph
from argus_soc.agents import investigator_agent, responder_agent, triage_agent
from argus_soc.core.logging_setup import get_logger, setup_logging
from argus_soc.core.settings import get_settings
from argus_soc.graph.graph_schema import AgentName, CaseStatus

log = get_logger(__name__)

# Which status each agent claims cases in, and the agent that works on them.
CLAIMS = (
    (CaseStatus.TRIAGED, AgentName.INVESTIGATOR, investigator_agent.run),
    (CaseStatus.INVESTIGATED, AgentName.RESPONDER, responder_agent.run),
)


async def run_once(tenant: str) -> bool:
    """One pass over one tenant; True if any agent did something."""
    settings = get_settings()
    did = await triage_agent.step(tenant) > 0
    for status, agent, work in CLAIMS:
        claimer = f"{agent}@{settings.agent_worker_id}"
        case_id = await graph.claim_case(tenant, status, claimer, settings.agent_claim_ttl_seconds)
        if case_id is not None:
            await work(tenant, case_id)
            did = True
    return did


async def run() -> None:
    settings = get_settings()
    log.info("worker %s on tenants %s", settings.agent_worker_id, settings.tenant_ids)
    while True:
        did = False
        for tenant in settings.tenant_ids:
            try:
                did = await run_once(tenant) or did
            except Exception:  # the claim is left to expire, so the step is retried (LLD §9)
                log.exception("agent step failed", extra={"tenant": tenant})
        if not did:
            await asyncio.sleep(settings.agent_poll_seconds)


def main() -> None:
    setup_logging("agents")
    asyncio.run(run())


if __name__ == "__main__":
    main()
