"""Triage agent (docs/LLD.md §6.2): turns new alerts into cases.

For each new alert, oldest first:
1. A learned playbook matches → open the case already auto-closed, citing the playbook.
2. Otherwise read memory (closed cases, semantic facts) and correlated alerts, raise the
   priority one step if memory says this is a known bad actor or target, open or join a
   case, store what was read as findings and hand the case to the Investigator.

Deterministic: no LLM. Stateless: everything it needs is read from the graph each step.
"""

from typing import Any

from argus_soc import graph
from argus_soc.agents.handoff_service import hand_off
from argus_soc.core.logging_setup import get_logger
from argus_soc.core.settings import get_settings
from argus_soc.graph.graph_schema import (
    PRIORITY_ORDER,
    AgentName,
    CaseStatus,
    IocVerdict,
    PlaybookRef,
    Priority,
)

AGENT = AgentName.TRIAGE
ALERTS_PER_STEP = 20


def raise_one(priority: str) -> Priority:
    """One step up the priority order, capped at critical."""
    i = PRIORITY_ORDER.index(Priority(priority))
    return PRIORITY_ORDER[min(i + 1, len(PRIORITY_ORDER) - 1)]


def memory_reasons(history: list[dict[str, Any]], facts: dict[str, dict]) -> list[str]:
    """Why memory says this alert matters more than its severity. Empty list: no hit."""
    threshold = get_settings().repeat_target_threshold
    reasons = [
        f"case {h['case_id']} with these entities was closed as malicious"
        for h in history
        if h.get("verdict") == IocVerdict.MALICIOUS
    ]
    # Not in the LLD pseudocode: nothing writes Case.verdict = malicious yet (chat log turn
    # 19), but an approved decision marks the IOC malicious, so read that fact too.
    reasons += [
        f"IOC {ioc} is known malicious"
        for ioc, f in facts["iocs"].items()
        if f.get("verdict") == IocVerdict.MALICIOUS
    ]
    reasons += [
        f"user {user} is suspected compromised (case {f.get('suspect_case_id')})"
        for user, f in facts["users"].items()
        if f.get("suspected_compromised")
    ]
    reasons += [
        f"host {host} was targeted in {len(f['targeted_case_ids'])} cases"
        for host, f in facts["hosts"].items()
        if len(f.get("targeted_case_ids") or []) >= threshold
    ]
    return reasons


async def _auto_close(tenant: str, alert: dict[str, Any], playbook: dict[str, Any]) -> int:
    ref = PlaybookRef(name=playbook["name"], version=playbook["version"])
    reason = f"Playbook {ref.name} v{ref.version}, learned from Case {playbook.get('source_case')}"
    case_id = await graph.close_case_auto(tenant, [alert["incident_id"]], ref, reason)
    await graph.record_agent_run(
        tenant,
        AGENT,
        case_id,
        f"auto-closed {alert['incident_id']} by playbook {ref.name} v{ref.version}",
        worker=get_settings().agent_worker_id,
    )
    return case_id


async def triage_alert(tenant: str, alert: dict[str, Any]) -> int:
    """Triage one alert; returns the id of the case it ended up in."""
    playbook = await graph.matching_playbook(tenant, alert)
    if playbook:
        return await _auto_close(tenant, alert, playbook)

    iid = alert["incident_id"]
    hosts, users, iocs = alert["hosts"], alert["users"], alert["iocs"]
    history = await graph.recall(tenant, ioc=iocs, host=hosts, user=users)
    facts = await graph.entity_facts(tenant, hosts, users, iocs)
    linked = await graph.linked_alerts(tenant, iid, get_settings().correlation_window_hours)

    severity = Priority(alert["severity"])
    reasons = memory_reasons(history, facts)
    priority = raise_one(severity) if reasons else severity  # at most one step

    case_id = await graph.open_or_join_case(tenant, [iid, *linked], priority)
    case = await graph.get_case(tenant, case_id)
    if case["status"] != CaseStatus.NEW:
        # Joined a case another agent already moved on. Moving it back to triaged could give
        # it a second decision (chat log turn 19), so the alert just joins it.
        await graph.record_agent_run(
            tenant,
            AGENT,
            case_id,
            f"{iid} joined case {case_id} ({case['status']}); not re-triaged",
            worker=get_settings().agent_worker_id,
        )
        return case_id

    await graph.record_findings(
        tenant,
        case_id,
        {
            "recall": history,
            "facts": facts,
            "linked": linked,
            "severity": str(severity),
            "memory_reasons": reasons,
        },
    )
    raised = f", raised from {severity}: {'; '.join(reasons)}" if reasons else ""
    await hand_off(
        tenant,
        case_id,
        agent=AGENT,
        status=CaseStatus.TRIAGED,
        priority=priority,
        handed_to=AgentName.INVESTIGATOR,
        summary=(
            f"{iid} triaged into case {case_id} with {len(linked)} linked alerts, "
            f"{len(history)} past cases; priority {priority}{raised}"
        ),
    )
    return case_id


async def step(tenant: str) -> int:
    """Triage the tenant's new alerts; returns how many were handled."""
    log = get_logger(__name__, tenant=tenant, agent=AGENT)
    cased: set[str] = set()  # this step only: alerts already pulled into a case as linked
    done = 0
    for alert in await graph.list_new_alerts(tenant, limit=ALERTS_PER_STEP):
        iid = alert["incident_id"]
        if iid in cased:
            continue
        try:
            case_id = await triage_alert(tenant, alert)
        except Exception:
            # The alert stays 'new' and is retried next step; the others still get triaged.
            log.exception("triage failed for %s", iid)
            continue
        done += 1
        case = await graph.get_case(tenant, case_id)
        cased.update(a["incident_id"] for a in case["alerts"])
        log.info("%s -> case %s", iid, case_id, extra={"case_id": case_id})
    return done
