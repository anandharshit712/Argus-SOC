"""Handoffs between agents (docs/LLD.md §6.6).

Every handoff is the same two writes: move the case to its next status (which releases the
claim), then record the AgentRun that names the next agent. One function, so the activity
feed always has one shape.
"""

from typing import Any

from argus_soc import graph
from argus_soc.core.settings import get_settings


async def hand_off(
    tenant: str,
    case_id: int,
    *,
    agent: str,
    status: str,
    summary: str,
    handed_to: str | None,
    priority: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> str:
    """Move the case on and record the step; returns the AgentRun id."""
    await graph.set_case_status(tenant, case_id, status, priority)
    return await graph.record_agent_run(
        tenant,
        agent,
        case_id,
        summary,
        handed_to=handed_to,
        worker=get_settings().agent_worker_id,
        tool_calls=tool_calls,
    )
