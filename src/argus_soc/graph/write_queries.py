"""Write functions of the graph tools library, real FalkorDB versions (docs/LLD.md §4.5).

Each write is one Cypher query (FalkorDB runs a graph's writes one at a time, so each is
atomic), with every value passed as a parameter. MERGE makes them safe to retry, except
`record_agent_run`, which appends to the activity log by design.
"""

import uuid
from typing import Any

from argus_soc.graph.falkor_client import run, run_read
from argus_soc.graph.graph_schema import (
    OPEN_CASE_STATUSES,
    AlertInput,
    AlertStatus,
    CaseStatus,
    DecisionInput,
    DecisionOutcome,
    FeedbackVerdict,
    IocType,
    IocVerdict,
    Label,
    PlaybookAction,
    PlaybookRef,
    Priority,
    Rel,
    SemanticFactsInput,
)
from argus_soc.graph.property_codec import (
    canonical_condition,
    from_json,
    to_json,
    utc_ago,
    utc_now,
)

ALERT, HOST, USER, IOC = Label.ALERT, Label.HOST, Label.USER, Label.IOC
ENDPOINT, TECHNIQUE = Label.ENDPOINT, Label.TECHNIQUE
CASE, DECISION, RUN, PLAYBOOK = Label.CASE, Label.DECISION, Label.AGENT_RUN, Label.PLAYBOOK
FEEDBACK = Label.FEEDBACK

# Properties a node gets the first time an alert mentions it (agent memory starts empty).
_NEW_HOST = "n.isolated = false, n.targeted_case_ids = [], n.criticality = 1"
_NEW_USER = "n.disabled = false, n.suspected_compromised = false"
_NEW_IOC = f"n.verdict = '{IocVerdict.UNKNOWN}', n.seen_case_ids = [], n.first_seen = $now"

_CLOSED = [str(CaseStatus.CLOSED), str(CaseStatus.AUTO_CLOSED)]


def _when(condition: str) -> str:
    """Cypher idiom: FOREACH (_ IN <this> | ...) runs its body only when `condition` holds."""
    return f"CASE WHEN {condition} THEN [1] ELSE [] END"


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

_UPSERT_ALERT = f"""
MERGE (a:{ALERT} {{incident_id: $incident_id}})
ON CREATE SET a.status = '{AlertStatus.NEW}', a.ingested_at = $now
SET a.domain = $domain, a.category = $category, a.severity = $severity,
    a.confidence = $confidence, a.succeeded = $succeeded, a.summary = $summary,
    a.evidence = $evidence, a.recommended_actions = $recommended_actions,
    a.talos_created_at = $talos_created_at
WITH a
FOREACH (h IN $hosts |
    MERGE (n:{HOST} {{hostname: h}}) ON CREATE SET {_NEW_HOST}
    MERGE (a)-[:{Rel.ON_HOST}]->(n))
FOREACH (u IN $users |
    MERGE (n:{USER} {{username: u}}) ON CREATE SET {_NEW_USER}
    MERGE (a)-[:{Rel.INVOLVES}]->(n))
FOREACH (ip IN $source_ips |
    MERGE (n:{IOC} {{type: '{IocType.IP}', value: ip}}) ON CREATE SET {_NEW_IOC}
    SET n.last_seen = $now
    MERGE (a)-[:{Rel.INVOLVES}]->(n))
FOREACH (p IN $endpoints |
    MERGE (n:{ENDPOINT} {{path: p, app: $app}})
    MERGE (a)-[:{Rel.TARGETED}]->(n))
FOREACH (t IN $techniques |
    MERGE (n:{TECHNIQUE} {{mitre_id: t.mitre_id}})
    SET n.name = coalesce(t.name, n.name), n.tactic = coalesce(t.tactic, n.tactic)
    MERGE (a)-[:{Rel.MAPS_TO}]->(n))
RETURN a.incident_id AS incident_id
"""


async def upsert_alert_from_report(tenant: str, alert: AlertInput) -> str:
    """Store one Talos report as an Alert with its hosts, users, IOCs, endpoints, techniques.

    The same incident_id twice is one alert: properties are refreshed, the status
    ('new' until Triage puts it in a case) is kept.
    """
    data = alert.model_dump(mode="json")
    params = {
        **data,
        "evidence": to_json(data["evidence"]),
        "app": alert.hosts[0] if alert.hosts else "",
        "now": utc_now(),
    }
    rows = await run(tenant, _UPSERT_ALERT, params)
    return rows[0]["incident_id"]


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

# Safety net shared by both case-opening writes: an alert that is already in a closed or
# auto-closed case is never put into another case. If that leaves none, the query returns
# no row and the caller raises ValueError.
_ELIGIBLE_ALERTS = f"""
MATCH (a:{ALERT}) WHERE a.incident_id IN $ids
OPTIONAL MATCH (a)<-[:{Rel.CONTAINS}]-(done:{CASE}) WHERE done.status IN $closed
WITH a, count(done) AS closed_cases
WHERE closed_cases = 0
WITH collect(a) AS alerts, collect(a.incident_id) AS eligible
WHERE size(alerts) > 0
"""

_OPEN_OR_JOIN = (
    _ELIGIBLE_ALERTS
    + f"""
OPTIONAL MATCH (open:{CASE})-[:{Rel.CONTAINS}]->(x:{ALERT})
WHERE x.incident_id IN eligible AND open.status IN $open_statuses
WITH alerts, open ORDER BY open.id LIMIT 1
OPTIONAL MATCH (any:{CASE})
WITH alerts, open, coalesce(max(any.id), 0) + 1 AS next_id
MERGE (c:{CASE} {{id: coalesce(open.id, next_id)}})
ON CREATE SET c.status = '{CaseStatus.NEW}', c.priority = $priority, c.opened_at = $now,
              c.findings = '{{}}'
SET c.updated_at = $now
WITH c, alerts
UNWIND alerts AS a
MERGE (c)-[:{Rel.CONTAINS}]->(a)
SET a.status = '{AlertStatus.CASED}', c.category = coalesce(c.category, a.category)
RETURN DISTINCT c.id AS id
"""
)


async def open_or_join_case(tenant: str, incident_ids: list[str], priority: str) -> int:
    """Add the alerts to the open case that already holds one of them, or open a new case
    with the next id. Either way the alerts become 'cased'.

    Alerts already in a closed or auto-closed case are left out (they were dealt with);
    ValueError if that leaves no alert at all.
    """
    rows = await run(
        tenant,
        _OPEN_OR_JOIN,
        {
            "ids": list(incident_ids),
            "priority": str(Priority(priority)),
            "open_statuses": [str(s) for s in OPEN_CASE_STATUSES],
            "closed": _CLOSED,
            "now": utc_now(),
        },
    )
    if not rows:
        raise ValueError(f"no alert of {list(incident_ids)} can go in a case: unknown or closed")
    return rows[0]["id"]


_CLOSE_AUTO = (
    _ELIGIBLE_ALERTS
    + f"""
OPTIONAL MATCH (any:{CASE})
WITH alerts, coalesce(max(any.id), 0) + 1 AS next_id
CREATE (c:{CASE} {{id: next_id, status: '{CaseStatus.AUTO_CLOSED}', priority: $priority,
                   opened_at: $now, updated_at: $now, closed_at: $now,
                   closed_reason: $reason, verdict: 'benign', findings: '{{}}'}})
WITH c, alerts
OPTIONAL MATCH (p:{PLAYBOOK} {{name: $playbook_name, version: $playbook_version}})
FOREACH (_ IN {_when("p IS NOT NULL")} | MERGE (c)-[:{Rel.APPLIED}]->(p))
WITH c, alerts
UNWIND alerts AS a
MERGE (c)-[:{Rel.CONTAINS}]->(a)
SET a.status = '{AlertStatus.CASED}', c.category = coalesce(c.category, a.category)
RETURN DISTINCT c.id AS id
"""
)


async def close_case_auto(
    tenant: str, incident_ids: list[str], playbook_ref: PlaybookRef, reason: str
) -> int:
    """Open a case directly as auto_closed (benign, priority info) that cites the playbook
    which closed it with an APPLIED edge. Same safety net as open_or_join_case."""
    rows = await run(
        tenant,
        _CLOSE_AUTO,
        {
            "ids": list(incident_ids),
            "closed": _CLOSED,
            "priority": str(Priority.INFO),
            "reason": reason,
            "playbook_name": playbook_ref.name,
            "playbook_version": playbook_ref.version,
            "now": utc_now(),
        },
    )
    if not rows:
        raise ValueError(f"no alert of {list(incident_ids)} can go in a case: unknown or closed")
    return rows[0]["id"]


_CLAIM = f"""
MATCH (c:{CASE} {{status: $status}})
WHERE c.claimed_by IS NULL OR c.claimed_at < $expired_before
WITH c ORDER BY c.updated_at ASC, c.id ASC LIMIT 1
SET c.claimed_by = $agent, c.claimed_at = $now
RETURN c.id AS id
"""


async def claim_case(tenant: str, status: str, agent: str, ttl_seconds: int) -> int | None:
    """Atomically claim the oldest case in `status` whose claim is empty or expired (LLD §6.1).
    Returns its id, or None when there is nothing to do."""
    rows = await run(
        tenant,
        _CLAIM,
        {"status": str(CaseStatus(status)), "agent": agent, "now": utc_now(),
         "expired_before": utc_ago(ttl_seconds)},
    )  # fmt: skip
    return rows[0]["id"] if rows else None


_SET_STATUS = f"""
MATCH (c:{CASE} {{id: $case_id}})
SET c.status = $status,
    c.priority = coalesce($priority, c.priority),
    c.claimed_by = null, c.claimed_at = null, c.updated_at = $now,
    c.closed_at = CASE WHEN $status IN $closed AND c.closed_at IS NULL
                       THEN $now ELSE c.closed_at END
RETURN c.id AS id
"""


async def set_case_status(
    tenant: str, case_id: int, status: str, priority: str | None = None
) -> None:
    """Move the case on and release its claim. Raises KeyError for an unknown case."""
    rows = await run(
        tenant,
        _SET_STATUS,
        {"case_id": case_id, "status": str(CaseStatus(status)),
         "priority": str(Priority(priority)) if priority is not None else None,
         "closed": _CLOSED, "now": utc_now()},
    )  # fmt: skip
    if not rows:
        raise KeyError(f"no case {case_id}")


_READ_FINDINGS = f"MATCH (c:{CASE} {{id: $case_id}}) RETURN c.findings AS findings"
_WRITE_FINDINGS = f"""
MATCH (c:{CASE} {{id: $case_id}})
SET c.findings = $findings, c.updated_at = $now
RETURN c.id AS id
"""


async def record_findings(tenant: str, case_id: int, findings: dict[str, Any]) -> None:
    """Store findings on the case. Top-level keys are added or replaced, the rest kept, so
    the Investigator does not wipe what Triage wrote. Raises KeyError for an unknown case.

    Read then write: only the agent holding the case's claim calls this.
    """
    rows = await run_read(tenant, _READ_FINDINGS, {"case_id": case_id})
    if not rows:
        raise KeyError(f"no case {case_id}")
    merged = {**from_json(rows[0]["findings"], {}), **findings}
    await run(
        tenant, _WRITE_FINDINGS, {"case_id": case_id, "findings": to_json(merged), "now": utc_now()}
    )


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

_RECORD_DECISION = f"""
MATCH (c:{CASE} {{id: $case_id}})
MERGE (c)-[:{Rel.HAS_DECISION}]->(d:{DECISION})
ON CREATE SET d.id = $id, d.rule_id = $rule_id, d.actions = $actions,
              d.needs_approval = $needs_approval, d.reason = $reason,
              d.explanation = $explanation, d.evidence = $evidence, d.outcome = $outcome,
              d.agent = $agent, d.previous_priority = $previous_priority,
              d.created_at = $now
WITH c, d, d.id = $id AS created
FOREACH (h IN CASE WHEN created THEN $hosts ELSE [] END |
    MERGE (n:{HOST} {{hostname: h}}) ON CREATE SET {_NEW_HOST}
    MERGE (d)-[:{Rel.ACTED_ON}]->(n)
    FOREACH (_ IN {_when("NOT $needs_approval")} | SET n.isolated = true))
FOREACH (u IN CASE WHEN created THEN $users ELSE [] END |
    MERGE (n:{USER} {{username: u}}) ON CREATE SET {_NEW_USER}
    MERGE (d)-[:{Rel.ACTED_ON}]->(n)
    FOREACH (_ IN {_when("NOT $needs_approval")} | SET n.disabled = true))
FOREACH (ip IN CASE WHEN created THEN $iocs ELSE [] END |
    MERGE (n:{IOC} {{type: '{IocType.IP}', value: ip}}) ON CREATE SET {_NEW_IOC}
    MERGE (d)-[:{Rel.ACTED_ON}]->(n))
WITH c, d, created
OPTIONAL MATCH (p:{PLAYBOOK} {{name: $playbook_name, version: $playbook_version}})
FOREACH (_ IN {_when("created AND p IS NOT NULL")} | MERGE (d)-[:{Rel.APPLIED}]->(p))
SET c.updated_at = $now
RETURN d.id AS id
"""


async def record_decision(tenant: str, case_id: int, decision: DecisionInput) -> str:
    """Store the Responder's decision with ACTED_ON edges to its targets.

    One decision per case: calling again (a retried step) returns the existing one.
    Actions that need approval are simulated only after approval (record_feedback);
    the others are simulated now (hosts isolated, users disabled; rule 10).
    Raises KeyError for an unknown case.
    """
    outcome = DecisionOutcome.PENDING if decision.needs_approval else DecisionOutcome.AUTO
    rows = await run(
        tenant,
        _RECORD_DECISION,
        {
            "case_id": case_id,
            "id": str(uuid.uuid4()),
            "rule_id": decision.rule_id,
            "actions": list(decision.actions),
            "needs_approval": decision.needs_approval,
            "reason": decision.reason,
            "explanation": decision.explanation,
            "evidence": to_json(decision.evidence),
            "outcome": str(outcome),
            "agent": str(decision.agent),
            "previous_priority": (
                str(decision.previous_priority) if decision.previous_priority else None
            ),
            "hosts": list(decision.target_hosts),
            "users": list(decision.target_users),
            "iocs": list(decision.target_iocs),
            "playbook_name": decision.playbook.name if decision.playbook else None,
            "playbook_version": decision.playbook.version if decision.playbook else None,
            "now": utc_now(),
        },
    )
    if not rows:
        raise KeyError(f"no case {case_id}")
    return rows[0]["id"]


# ---------------------------------------------------------------------------
# Agent runs (the activity log)
# ---------------------------------------------------------------------------

_RECORD_RUN = f"""
OPTIONAL MATCH (c:{CASE} {{id: $case_id}})
OPTIONAL MATCH (prev:{RUN} {{case_id: $case_id, handed_to: $agent}})
WHERE NOT (prev)-[:{Rel.HANDED_OFF_TO}]->()
WITH c, prev ORDER BY prev.at DESC LIMIT 1
CREATE (r:{RUN} {{id: $id, agent: $agent, worker: $worker, case_id: $case_id, at: $now,
                summary: $summary, handed_to: $handed_to, tool_calls: $tool_calls}})
FOREACH (_ IN {_when("c IS NOT NULL")} | MERGE (r)-[:{Rel.WROTE}]->(c))
FOREACH (_ IN {_when("prev IS NOT NULL")} | MERGE (prev)-[:{Rel.HANDED_OFF_TO}]->(r))
RETURN r.id AS id
"""


async def record_agent_run(
    tenant: str,
    agent: str,
    case_id: int | None,
    summary: str,
    handed_to: str | None = None,
    worker: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> str:
    """Append one agent step to the activity log. If the previous step on this case handed
    the case to `agent`, the two runs are linked with HANDED_OFF_TO."""
    rows = await run(
        tenant,
        _RECORD_RUN,
        {"id": str(uuid.uuid4()), "agent": agent, "worker": worker, "case_id": case_id,
         "summary": summary, "handed_to": handed_to, "now": utc_now(),
         "tool_calls": to_json(tool_calls) if tool_calls is not None else None},
    )  # fmt: skip
    return rows[0]["id"]


# ---------------------------------------------------------------------------
# Learning: analyst feedback, playbooks, IOC facts (docs/LLD.md §4.5, §6.7)
# ---------------------------------------------------------------------------

_RECORD_FEEDBACK = f"""
MATCH (c:{CASE} {{id: $case_id}})
CREATE (f:{FEEDBACK} {{id: $id, verdict: $verdict, note: $note, analyst: $analyst,
                       created_at: $now}})-[:{Rel.ON}]->(c)
SET c.updated_at = $now,
    c.verdict = CASE WHEN $verdict = '{FeedbackVerdict.BENIGN}' THEN 'benign' ELSE c.verdict END
WITH c, f
OPTIONAL MATCH (c)-[:{Rel.HAS_DECISION}]->(d:{DECISION} {{outcome: '{DecisionOutcome.PENDING}'}})
FOREACH (_ IN {_when("d IS NOT NULL")} | SET d.outcome = $outcome)
WITH c, f, d
OPTIONAL MATCH (d)-[:{Rel.ACTED_ON}]->(h:{HOST})
FOREACH (_ IN {_when("h IS NOT NULL AND $approve")} | SET h.isolated = true)
WITH DISTINCT c, f, d
OPTIONAL MATCH (d)-[:{Rel.ACTED_ON}]->(u:{USER})
FOREACH (_ IN {_when("u IS NOT NULL AND $approve")} | SET u.disabled = true)
WITH DISTINCT c, f
OPTIONAL MATCH (c)-[:{Rel.CONTAINS}]->(:{ALERT})-[:{Rel.INVOLVES}]->(i:{IOC})
FOREACH (_ IN {_when("i IS NOT NULL AND $ioc_verdict IS NOT NULL")} |
    SET i.verdict = $ioc_verdict)
RETURN DISTINCT f.id AS id
"""


async def record_feedback(tenant: str, case_id: int, verdict: str, note: str, analyst: str) -> str:
    """The analyst's verdict on a case, in one query:

    - a Feedback node ON the case;
    - a pending decision becomes approved (approve) or rejected (reject, benign); on approve
      its simulated actions run now (ACTED_ON hosts isolated, users disabled; rule 10);
    - the case's IOCs become malicious (approve) or benign (benign); reject leaves them;
    - benign marks the case verdict benign, which recall shows next time.

    Raises KeyError for an unknown case, ValueError for an unknown verdict.
    """
    v = FeedbackVerdict(verdict)
    ioc_verdict = {
        FeedbackVerdict.APPROVE: IocVerdict.MALICIOUS,
        FeedbackVerdict.BENIGN: IocVerdict.BENIGN,
    }.get(v)
    outcome = DecisionOutcome.APPROVED if v == FeedbackVerdict.APPROVE else DecisionOutcome.REJECTED
    rows = await run(
        tenant,
        _RECORD_FEEDBACK,
        {
            "case_id": case_id,
            "id": str(uuid.uuid4()),
            "verdict": str(v),
            "note": note,
            "analyst": analyst,
            "outcome": str(outcome),
            "approve": v == FeedbackVerdict.APPROVE,
            "ioc_verdict": str(ioc_verdict) if ioc_verdict else None,
            "now": utc_now(),
        },
    )
    if not rows:
        raise KeyError(f"no case {case_id}")
    return rows[0]["id"]


_PLAYBOOK_FROM_FEEDBACK = f"""
MATCH (f:{FEEDBACK} {{id: $feedback_id}})-[:{Rel.ON}]->(c:{CASE})
OPTIONAL MATCH (done:{PLAYBOOK})-[:{Rel.LEARNED_FROM}]->(f)
RETURN c.id AS case_id, done.name AS name, done.version AS version
"""

_CREATE_PLAYBOOK = f"""
MATCH (f:{FEEDBACK} {{id: $feedback_id}})
OPTIONAL MATCH (old:{PLAYBOOK} {{condition: $condition}})
WITH f, collect(old) AS olds, max(old.version) AS top
WITH f, olds, coalesce(top, 0) + 1 AS version,
     CASE WHEN size(olds) > 0 THEN olds[0].name ELSE $default_name END AS name
FOREACH (o IN olds | SET o.active = false)
CREATE (p:{PLAYBOOK} {{name: name, version: version, condition: $condition,
                       action: $action, active: true, created_at: $now}})
       -[:{Rel.LEARNED_FROM}]->(f)
RETURN p.name AS name, p.version AS version
"""


async def create_playbook_version(
    tenant: str, feedback_id: str, condition: dict[str, Any], action: str
) -> dict[str, Any]:
    """Learn a playbook from analyst feedback (procedural memory).

    The same condition (category + IOCs) always belongs to the same playbook name: a new
    version is created and the older versions are deactivated, so only the newest one
    auto-closes. Asking again for the same feedback returns the version it already made.
    Raises KeyError for unknown feedback.
    """
    action = str(PlaybookAction(action))
    rows = await run_read(tenant, _PLAYBOOK_FROM_FEEDBACK, {"feedback_id": feedback_id})
    if not rows:
        raise KeyError(f"no feedback {feedback_id}")
    if rows[0]["name"] is not None:
        return {"name": rows[0]["name"], "version": rows[0]["version"]}
    condition = canonical_condition(condition)
    default_name = f"auto-close {condition.get('category')} learned from case {rows[0]['case_id']}"
    created = await run(
        tenant,
        _CREATE_PLAYBOOK,
        {"feedback_id": feedback_id, "condition": to_json(condition), "action": action,
         "default_name": default_name, "now": utc_now()},
    )  # fmt: skip
    return {"name": created[0]["name"], "version": created[0]["version"]}


_IOC_FACT = {
    "owner": f"""
MERGE (n:{IOC} {{type: '{IocType.IP}', value: $ioc}}) ON CREATE SET {_NEW_IOC}
SET n.owner = $value
""",
    "verdict": f"""
MERGE (n:{IOC} {{type: '{IocType.IP}', value: $ioc}}) ON CREATE SET {_NEW_IOC}
SET n.verdict = $value
""",
}


async def set_ioc_fact(tenant: str, ioc: str, key: str, value: Any) -> None:
    """Semantic fact on an IOC from analyst feedback: `owner` (free text, e.g. "internal
    pentest scanner") or `verdict` (unknown / malicious / benign)."""
    if key not in _IOC_FACT:
        raise ValueError(f"unknown IOC fact {key!r}; use one of {sorted(_IOC_FACT)}")
    if key == "verdict":
        value = str(IocVerdict(value))
    await run(tenant, _IOC_FACT[key], {"ioc": ioc, "value": value, "now": utc_now()})


# ---------------------------------------------------------------------------
# Semantic facts written by the Investigator (LLD §4.4.1)
# ---------------------------------------------------------------------------

_SEMANTIC_FACTS = f"""
MATCH (c:{CASE} {{id: $case_id}})
FOREACH (name IN $hosts |
    MERGE (n:{HOST} {{hostname: name}}) ON CREATE SET {_NEW_HOST}
    FOREACH (_ IN {_when("NOT $case_id IN coalesce(n.targeted_case_ids, [])")} |
        SET n.targeted_case_ids = coalesce(n.targeted_case_ids, []) + $case_id,
            n.last_targeted_at = $now))
FOREACH (value IN $iocs |
    MERGE (n:{IOC} {{type: '{IocType.IP}', value: value}}) ON CREATE SET {_NEW_IOC}
    FOREACH (_ IN {_when("NOT $case_id IN coalesce(n.seen_case_ids, [])")} |
        SET n.seen_case_ids = coalesce(n.seen_case_ids, []) + $case_id))
FOREACH (name IN $users |
    MERGE (n:{USER} {{username: name}}) ON CREATE SET {_NEW_USER}
    FOREACH (_ IN {_when("coalesce(n.suspect_case_id, -1) <> $case_id")} |
        SET n.suspected_compromised = true, n.suspected_at = $now,
            n.suspect_case_id = $case_id))
RETURN c.id AS id
"""


async def record_semantic_facts(tenant: str, case_id: int, facts: SemanticFactsInput) -> None:
    """Remember what this case taught about its hosts, IOCs and users, in one query.

    Counts are kept as lists of case ids, never counters, so writing the same case twice
    changes nothing (times targeted = len(targeted_case_ids)). Raises KeyError for an
    unknown case.
    """
    rows = await run(
        tenant,
        _SEMANTIC_FACTS,
        {"case_id": case_id, "hosts": list(facts.hosts), "iocs": list(facts.iocs),
         "users": list(facts.suspected_users), "now": utc_now()},
    )  # fmt: skip
    if not rows:
        raise KeyError(f"no case {case_id}")
