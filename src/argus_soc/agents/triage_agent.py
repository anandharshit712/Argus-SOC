"""Triage agent (docs/LLD.md §6.2): turns new alerts into cases.

Two phases per step, each safe with several workers running at once:

1. **Route** each new alert, oldest first, with one atomic graph write: a learned playbook
   matches → a case opened already auto-closed, citing the playbook; otherwise the alert and
   the alerts correlated with it (shared IOC or user) go into a case, new or open.
2. **Triage** each new case this worker can claim (`claim_case`, like the other agents): read
   memory (closed cases, semantic facts) for every host, user and IOC in the case, take the
   priority of its most severe alert, raise it one step if memory says this is a known bad
   actor or target, store what was read as findings and hand the case to the Investigator.

The claim makes the triage of a case happen once, even when two workers routed its alerts
at the same moment. Deterministic, no LLM; nothing is kept between steps.
"""

from typing import Any

from argus_soc import graph
from argus_soc.agents.handoff_service import hand_off
from argus_soc.agents.priority_rules import highest, raise_one
from argus_soc.core.logging_setup import get_logger
from argus_soc.core.settings import get_settings
from argus_soc.graph.graph_schema import AgentName, CaseStatus, IocVerdict, PlaybookRef, Priority

AGENT = AgentName.TRIAGE
ALERTS_PER_STEP = 20


def memory_reasons(history: list[dict[str, Any]], facts: dict[str, dict]) -> list[str]:
    """Why memory says this case matters more than its severity. Empty list: no hit."""
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


async def route_alert(tenant: str, alert: dict[str, Any]) -> int:
    """Put one alert in a case (auto-closed if a playbook matches); returns the case id.
    Raises ValueError when another worker already put it in a closed case."""
    worker = get_settings().agent_worker_id
    iid = alert["incident_id"]
    playbook = await graph.matching_playbook(tenant, alert)
    if playbook:
        ref = PlaybookRef(name=playbook["name"], version=playbook["version"])
        reason = (
            f"Playbook {ref.name} v{ref.version}, learned from Case {playbook.get('source_case')}"
        )
        case_id = await graph.close_case_auto(tenant, [iid], ref, reason)
        summary = f"auto-closed {iid} by playbook {ref.name} v{ref.version}"
        await graph.record_agent_run(tenant, AGENT, case_id, summary, worker=worker)
        return case_id

    linked = await graph.linked_alerts(tenant, iid, get_settings().correlation_window_hours)
    case_id = await graph.open_or_join_case(tenant, [iid, *linked], Priority(alert["severity"]))
    status = (await graph.get_case(tenant, case_id))["status"]
    if status not in (CaseStatus.NEW, CaseStatus.TRIAGED):
        # A late alert (e.g. the successful login) joining a case already investigated is not
        # re-triaged. Before deciding, the Responder sends the case back to the Investigator
        # when its alerts changed; a case already decided keeps its one decision.
        summary = f"{iid} joined case {case_id} ({status}); not re-triaged"
        await graph.record_agent_run(tenant, AGENT, case_id, summary, worker=worker)
    return case_id


async def triage_case(tenant: str, case_id: int) -> None:
    """Memory, priority, findings and the handoff for one claimed new case."""
    case = await graph.get_case(tenant, case_id)
    if case is None:
        return
    hosts, users, iocs = case["hosts"], case["users"], case["iocs"]
    history = [
        h
        for h in await graph.recall(tenant, ioc=iocs, host=hosts, user=users)
        if h["case_id"] != case_id
    ]
    facts = await graph.entity_facts(tenant, hosts, users, iocs)
    reasons = memory_reasons(history, facts)
    # Read by the decision table: R3 needs approval when the attacker is already known bad.
    known_bad = sorted(
        i for i, f in facts["iocs"].items() if f.get("verdict") == IocVerdict.MALICIOUS
    )
    # The most severe alert in the case (a linked success counts), then memory: one step at most.
    severity = highest([a["severity"] for a in case["alerts"]])
    priority = raise_one(severity) if reasons else severity
    alert_ids = [a["incident_id"] for a in case["alerts"]]
    await graph.record_findings(
        tenant,
        case_id,
        {
            "recall": history,
            "facts": facts,
            "linked": alert_ids[1:],  # correlated with the first (oldest) alert
            "severity": str(severity),
            "memory_reasons": reasons,
            "known_malicious_iocs": known_bad,
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
            f"case {case_id} triaged: {len(alert_ids)} alerts, {len(history)} past cases; "
            f"priority {priority}{raised}"
        ),
    )


async def step(tenant: str) -> int:
    """Route the tenant's new alerts, then triage the new cases this worker can claim.
    Returns how many alerts and cases were handled."""
    log = get_logger(__name__, tenant=tenant, agent=AGENT)
    settings = get_settings()
    cased: set[str] = set()  # this step only: alerts already pulled into a case as linked
    done = 0
    for alert in await graph.list_new_alerts(tenant, limit=ALERTS_PER_STEP):
        iid = alert["incident_id"]
        if iid in cased:
            continue
        try:
            case_id = await route_alert(tenant, alert)
        except Exception:
            # The alert stays 'new' and is retried next step; the others still get routed.
            # (Also the case when another worker closed it a moment ago: then it is not new.)
            log.exception("routing failed for %s", iid)
            continue
        done += 1
        cased.update(a["incident_id"] for a in (await graph.get_case(tenant, case_id))["alerts"])
        log.info("%s -> case %s", iid, case_id, extra={"case_id": case_id})

    claimer = f"{AGENT}@{settings.agent_worker_id}"
    ttl = settings.agent_claim_ttl_seconds
    while (case_id := await graph.claim_case(tenant, CaseStatus.NEW, claimer, ttl)) is not None:
        await triage_case(tenant, case_id)
        done += 1
    return done
