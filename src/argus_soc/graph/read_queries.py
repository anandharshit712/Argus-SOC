"""Read functions of the graph tools library, real FalkorDB versions (docs/LLD.md §4.4).

All read-only queries (GRAPH.RO_QUERY), every value passed as a parameter, results
returned as plain Python types in the same shapes as graph_stubs.
"""

from datetime import datetime, timedelta
from typing import Any

from argus_soc.graph.falkor_client import run_read
from argus_soc.graph.graph_schema import AlertStatus, CaseStatus, Label, Rel
from argus_soc.graph.property_codec import from_json

ALERT, HOST, USER, IOC = Label.ALERT, Label.HOST, Label.USER, Label.IOC
ENDPOINT, TECHNIQUE = Label.ENDPOINT, Label.TECHNIQUE
CASE, DECISION, RUN, PLAYBOOK = Label.CASE, Label.DECISION, Label.AGENT_RUN, Label.PLAYBOOK
FEEDBACK = Label.FEEDBACK

# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

# Appended after a query that binds `a` (one Alert per row): gathers its linked nodes.
_ALERT_DETAIL = f"""
OPTIONAL MATCH (a)-[:{Rel.ON_HOST}]->(h:{HOST})
WITH a, collect(DISTINCT h.hostname) AS hosts
OPTIONAL MATCH (a)-[:{Rel.INVOLVES}]->(u:{USER})
WITH a, hosts, collect(DISTINCT u.username) AS users
OPTIONAL MATCH (a)-[:{Rel.INVOLVES}]->(i:{IOC})
WITH a, hosts, users, collect(DISTINCT i.value) AS iocs
OPTIONAL MATCH (a)-[:{Rel.TARGETED}]->(e:{ENDPOINT})
WITH a, hosts, users, iocs, collect(DISTINCT e.path) AS endpoints
OPTIONAL MATCH (a)-[:{Rel.MAPS_TO}]->(t:{TECHNIQUE})
WITH a, hosts, users, iocs, endpoints,
     collect(DISTINCT {{mitre_id: t.mitre_id, name: t.name, tactic: t.tactic}}) AS techniques
RETURN properties(a) AS alert, hosts, users, iocs, endpoints, techniques
"""

_ALERT_KEYS = (
    "incident_id", "domain", "category", "severity", "confidence", "succeeded", "summary",
    "recommended_actions", "talos_created_at", "ingested_at", "status",
)  # fmt: skip


def _alert_row(row: dict[str, Any]) -> dict[str, Any]:
    props = dict(row["alert"])
    alert = {key: props.get(key) for key in _ALERT_KEYS}
    alert["recommended_actions"] = list(alert["recommended_actions"] or [])
    alert["evidence"] = from_json(props.get("evidence"), [])
    for key in ("hosts", "users", "iocs", "endpoints"):
        alert[key] = sorted(row[key])
    alert["techniques"] = sorted(
        (dict(t) for t in row["techniques"] if t["mitre_id"] is not None),
        key=lambda t: t["mitre_id"],
    )
    return alert


async def list_new_alerts(tenant: str, limit: int = 20) -> list[dict[str, Any]]:
    """Alerts not yet in a case, oldest first (Triage's work queue)."""
    rows = await run_read(
        tenant,
        f"MATCH (a:{ALERT} {{status: $status}}) "
        "WITH a ORDER BY a.talos_created_at ASC LIMIT $limit" + _ALERT_DETAIL,
        {"status": str(AlertStatus.NEW), "limit": limit},
    )
    return sorted((_alert_row(r) for r in rows), key=lambda a: a["talos_created_at"] or "")


async def known_incident_ids(tenant: str, ids: list[str]) -> set[str]:
    """Which of these Talos incident ids are already stored as alerts."""
    rows = await run_read(
        tenant,
        f"MATCH (a:{ALERT}) WHERE a.incident_id IN $ids RETURN a.incident_id AS id",
        {"ids": list(ids)},
    )
    return {r["id"] for r in rows}


# ---------------------------------------------------------------------------
# Q1 blast radius
# ---------------------------------------------------------------------------

_BLAST_RADIUS = f"""
MATCH (:{IOC} {{value: $ioc}})<-[:{Rel.INVOLVES}]-(a:{ALERT})-[:{Rel.ON_HOST}]->(h:{HOST})
OPTIONAL MATCH (a)-[:{Rel.INVOLVES}]->(u:{USER})
OPTIONAL MATCH (u)-[:{Rel.LOGGED_INTO}]->(r:{HOST})
WITH h, collect(DISTINCT a.incident_id) AS alerts, collect(DISTINCT u.username) AS accounts,
     collect(DISTINCT r.hostname) AS reached
RETURN h.hostname AS host, coalesce(h.criticality, 1) AS criticality, accounts,
       reached AS reached_hosts, size(alerts) AS alerts
"""


async def blast_radius(tenant: str, ioc: str) -> list[dict[str, Any]]:
    """Q1: hosts hit by alerts involving the IOC, the accounts in those alerts and the hosts
    those accounts log into. Most critical host first."""
    rows = await run_read(tenant, _BLAST_RADIUS, {"ioc": ioc})
    out = [
        {**r, "accounts": sorted(r["accounts"]), "reached_hosts": sorted(r["reached_hosts"])}
        for r in rows
    ]
    return sorted(out, key=lambda r: (-r["criticality"], r["host"]))


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

_CASE_SUMMARY = f"""
OPTIONAL MATCH (c)-[:{Rel.CONTAINS}]->(a:{ALERT})
WITH c, count(DISTINCT a) AS alert_count
OPTIONAL MATCH (c)-[:{Rel.HAS_DECISION}]->(d:{DECISION})
OPTIONAL MATCH (c)-[:{Rel.APPLIED}]->(p:{PLAYBOOK})
RETURN c.id AS id, c.status AS status, c.priority AS priority, c.category AS category,
       alert_count, c.opened_at AS opened_at, c.updated_at AS updated_at,
       coalesce(d.needs_approval, false) AND c.status = '{CaseStatus.AWAITING_APPROVAL}'
           AS needs_approval,
       p.name AS playbook_name, p.version AS playbook_version
"""


def _summary(row: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in row.items() if not k.startswith("playbook_")}
    name, version = row["playbook_name"], row["playbook_version"]
    out["auto_closed_by"] = f"{name} v{version}" if name is not None else None
    return out


async def list_cases(tenant: str, status: str | None = None, limit: int = 100) -> list[dict]:
    """Case summaries for the UI queue, newest first."""
    rows = await run_read(
        tenant,
        f"MATCH (c:{CASE}) WHERE $status IS NULL OR c.status = $status" + _CASE_SUMMARY,
        {"status": status},
    )
    cases = sorted((_summary(r) for r in rows), key=lambda c: c["opened_at"], reverse=True)
    return cases[:limit]


_CASE_ALERTS = f"MATCH (:{CASE} {{id: $case_id}})-[:{Rel.CONTAINS}]->(a:{ALERT})" + _ALERT_DETAIL

_CASE_DECISION = f"""
MATCH (:{CASE} {{id: $case_id}})-[:{Rel.HAS_DECISION}]->(d:{DECISION})
OPTIONAL MATCH (d)-[:{Rel.ACTED_ON}]->(h:{HOST})
WITH d, collect(DISTINCT h.hostname) AS hosts
OPTIONAL MATCH (d)-[:{Rel.ACTED_ON}]->(u:{USER})
WITH d, hosts, collect(DISTINCT u.username) AS users
OPTIONAL MATCH (d)-[:{Rel.ACTED_ON}]->(i:{IOC})
WITH d, hosts, users, collect(DISTINCT i.value) AS iocs
OPTIONAL MATCH (d)-[:{Rel.APPLIED}]->(p:{PLAYBOOK})
RETURN properties(d) AS d, hosts, users, iocs, p.name AS pb_name, p.version AS pb_version
"""

_CASE_FEEDBACK = f"""
MATCH (f:{FEEDBACK})-[:{Rel.ON}]->(:{CASE} {{id: $case_id}})
RETURN f.id AS id, f.verdict AS verdict, f.note AS note, f.analyst AS analyst,
       f.created_at AS created_at
"""

_CASE_RUNS = f"""
MATCH (r:{RUN})-[:{Rel.WROTE}]->(:{CASE} {{id: $case_id}})
RETURN properties(r) AS r
"""


def _decision(row: dict[str, Any], case_id: int) -> dict[str, Any]:
    d = dict(row["d"])
    playbook = None
    if row["pb_name"] is not None:
        playbook = {"name": row["pb_name"], "version": row["pb_version"]}
    return {
        "id": d["id"], "case_id": case_id, "rule_id": d.get("rule_id"),
        "actions": list(d.get("actions") or []), "target_hosts": sorted(row["hosts"]),
        "target_users": sorted(row["users"]), "target_iocs": sorted(row["iocs"]),
        "needs_approval": d.get("needs_approval"), "reason": d.get("reason"),
        "explanation": d.get("explanation"), "evidence": from_json(d.get("evidence"), {}),
        "outcome": d.get("outcome"), "playbook": playbook, "agent": d.get("agent"),
        "previous_priority": d.get("previous_priority"),
        "created_at": d.get("created_at"),
    }  # fmt: skip


def activity_item(props: dict[str, Any]) -> dict[str, Any]:
    """One AgentRun as the activity feed shows it (also used by list_activity)."""
    p = dict(props)
    return {
        "id": p["id"], "at": p.get("at"), "agent": p.get("agent"), "worker": p.get("worker"),
        "case_id": p.get("case_id"), "summary": p.get("summary"),
        "handed_to": p.get("handed_to"), "tool_calls": from_json(p.get("tool_calls"), None),
    }  # fmt: skip


async def get_case(tenant: str, case_id: int) -> dict[str, Any] | None:
    """Everything about one case, or None if there is no such case."""
    params = {"case_id": case_id}
    head = await run_read(
        tenant,
        f"MATCH (c:{CASE} {{id: $case_id}}) WITH c" + _CASE_SUMMARY
        + ", c.closed_at AS closed_at, c.verdict AS verdict, c.closed_reason AS closed_reason,"
        " c.claimed_by AS claimed_by, c.findings AS findings",
        params,
    )  # fmt: skip
    if not head:
        return None
    case = _summary(head[0])
    findings = from_json(case.pop("findings"), {})
    alerts = sorted(
        (_alert_row(r) for r in await run_read(tenant, _CASE_ALERTS, params)),
        key=lambda a: a["talos_created_at"] or "",
    )
    decision_rows = await run_read(tenant, _CASE_DECISION, params)
    feedback = await run_read(tenant, _CASE_FEEDBACK, params)
    runs = [activity_item(r["r"]) for r in await run_read(tenant, _CASE_RUNS, params)]
    return {
        **case,
        "alerts": alerts,
        "hosts": sorted({h for a in alerts for h in a["hosts"]}),
        "users": sorted({u for a in alerts for u in a["users"]}),
        "iocs": sorted({i for a in alerts for i in a["iocs"]}),
        "findings": findings,
        "decision": _decision(decision_rows[0], case_id) if decision_rows else None,
        "feedback": sorted(feedback, key=lambda f: f["created_at"] or ""),
        "agent_runs": sorted(runs, key=lambda r: r["at"] or ""),
    }


# ---------------------------------------------------------------------------
# Q4 recall, Q5 linked alerts
# ---------------------------------------------------------------------------

_CLOSED = [str(CaseStatus.CLOSED), str(CaseStatus.AUTO_CLOSED)]

# One branch per kind of entity; UNION drops the duplicates.
_RECALL = f"""
MATCH (c:{CASE})-[:{Rel.CONTAINS}]->(:{ALERT})-[:{Rel.INVOLVES}]->(i:{IOC})
WHERE c.status IN $closed AND i.value IN $iocs
RETURN c.id AS case_id, c.verdict AS verdict, c.closed_at AS closed_at
UNION
MATCH (c:{CASE})-[:{Rel.CONTAINS}]->(:{ALERT})-[:{Rel.ON_HOST}]->(h:{HOST})
WHERE c.status IN $closed AND h.hostname IN $hosts
RETURN c.id AS case_id, c.verdict AS verdict, c.closed_at AS closed_at
UNION
MATCH (c:{CASE})-[:{Rel.CONTAINS}]->(:{ALERT})-[:{Rel.INVOLVES}]->(u:{USER})
WHERE c.status IN $closed AND u.username IN $users
RETURN c.id AS case_id, c.verdict AS verdict, c.closed_at AS closed_at
"""

_LATEST_NOTES = f"""
MATCH (f:{FEEDBACK})-[:{Rel.ON}]->(c:{CASE}) WHERE c.id IN $ids
RETURN c.id AS case_id, f.note AS note, f.created_at AS created_at
"""

RECALL_LIMIT = 5


def _names(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


async def recall(
    tenant: str,
    ioc: str | list[str] | None = None,
    host: str | list[str] | None = None,
    user: str | list[str] | None = None,
) -> list[dict[str, Any]]:
    """Q4: closed cases whose alerts involved any of these IOCs, hosts or users, with the
    verdict and the latest analyst note. Newest first, at most 5. This is episodic memory:
    it works the same after a restart because it is all in the graph."""
    params = {"closed": _CLOSED, "iocs": _names(ioc), "hosts": _names(host), "users": _names(user)}
    if not (params["iocs"] or params["hosts"] or params["users"]):
        return []
    cases = await run_read(tenant, _RECALL, params)
    cases = sorted(cases, key=lambda c: c["closed_at"] or "", reverse=True)[:RECALL_LIMIT]
    if not cases:
        return []
    notes = await run_read(tenant, _LATEST_NOTES, {"ids": [c["case_id"] for c in cases]})
    latest: dict[int, tuple[str, str]] = {}
    for n in notes:
        if n["case_id"] not in latest or (n["created_at"] or "") > latest[n["case_id"]][0]:
            latest[n["case_id"]] = (n["created_at"] or "", n["note"])
    return [{**c, "note": latest.get(c["case_id"], ("", None))[1]} for c in cases]


# Linked through a shared IOC or user (both are INVOLVES edges). A shared host alone does
# not link: two different attackers can hit the same web server.
_LINKED = f"""
MATCH (a:{ALERT} {{incident_id: $id}})-[:{Rel.INVOLVES}]->(shared)
      <-[:{Rel.INVOLVES}]-(b:{ALERT})
WHERE b <> a
OPTIONAL MATCH (b)<-[:{Rel.CONTAINS}]-(done:{CASE}) WHERE done.status IN $closed
WITH a, b, count(done) AS closed_cases
WHERE closed_cases = 0
RETURN DISTINCT b.incident_id AS id, b.talos_created_at AS at, a.talos_created_at AS origin
"""


async def linked_alerts(tenant: str, incident_id: str, window_hours: int = 24) -> list[str]:
    """Q5: other live alerts that share an IOC or a user with this one and were raised
    within `window_hours` of it (either side). Alerts in a closed or auto-closed case are
    never returned, so Triage cannot pull a finished alert into a new case. Sorted by id."""
    rows = await run_read(tenant, _LINKED, {"id": incident_id, "closed": _CLOSED})
    window = timedelta(hours=window_hours)
    linked = set()
    for r in rows:
        if r["at"] and r["origin"]:
            gap = abs(datetime.fromisoformat(r["at"]) - datetime.fromisoformat(r["origin"]))
            if gap <= window:
                linked.add(r["id"])
    return sorted(linked)


# ---------------------------------------------------------------------------
# Playbooks (procedural memory)
# ---------------------------------------------------------------------------

_PLAYBOOKS = f"""
MATCH (p:{PLAYBOOK}) WHERE $only_active = false OR p.active = true
OPTIONAL MATCH (p)-[:{Rel.LEARNED_FROM}]->(f:{FEEDBACK})-[:{Rel.ON}]->(c:{CASE})
RETURN properties(p) AS p, f.id AS learned_from, c.id AS source_case
"""


def _playbook(row: dict[str, Any]) -> dict[str, Any]:
    p = dict(row["p"])
    return {
        "name": p["name"], "version": p["version"], "active": bool(p.get("active")),
        "condition": from_json(p.get("condition"), {}), "action": p.get("action"),
        "source_case": row["source_case"], "learned_from": row["learned_from"],
        "created_at": p.get("created_at"),
    }  # fmt: skip


async def list_playbooks(tenant: str) -> list[dict[str, Any]]:
    """Every playbook version with the case it was learned from, by name then version."""
    rows = await run_read(tenant, _PLAYBOOKS, {"only_active": False})
    return sorted((_playbook(r) for r in rows), key=lambda p: (p["name"], p["version"]))


def playbook_matches(playbook: dict[str, Any], alert: dict[str, Any]) -> bool:
    """Same category, and the alert shares at least one IOC with the condition's ioc_in."""
    cond = playbook["condition"]
    return (
        playbook["active"]
        and alert.get("category") == cond.get("category")
        and bool(set(alert.get("iocs") or []) & set(cond.get("ioc_in") or []))
    )


async def matching_playbook(tenant: str, alert: dict[str, Any]) -> dict[str, Any] | None:
    """The newest active playbook that matches the alert (category + IOC), or None.
    Triage asks this first: a match closes the alert without the other agents."""
    rows = await run_read(tenant, _PLAYBOOKS, {"only_active": True})
    candidates = sorted((_playbook(r) for r in rows), key=lambda p: -p["version"])
    return next((p for p in candidates if playbook_matches(p, alert)), None)


# ---------------------------------------------------------------------------
# Q6 explain decision, activity feed
# ---------------------------------------------------------------------------

_DECISION_CASE = f"""
MATCH (c:{CASE})-[:{Rel.HAS_DECISION}]->(:{DECISION} {{id: $id}})
OPTIONAL MATCH (c)-[:{Rel.APPLIED}]->(p:{PLAYBOOK})
RETURN c.id AS case_id, c.findings AS findings, p.name AS case_pb_name,
       p.version AS case_pb_version
"""


async def explain_decision(tenant: str, decision_id: str) -> dict[str, Any] | None:
    """Q6: the decision with its case, alerts, acted-on nodes, attack path, the playbook it
    applied and the case that playbook was learned from. None if there is no such decision."""
    rows = await run_read(tenant, _DECISION_CASE, {"id": decision_id})
    if not rows:
        return None
    head = rows[0]
    case_id = head["case_id"]
    decision_rows = await run_read(tenant, _CASE_DECISION, {"case_id": case_id})
    decision = _decision(decision_rows[0], case_id)
    alerts = await run_read(
        tenant,
        f"MATCH (:{CASE} {{id: $case_id}})-[:{Rel.CONTAINS}]->(a:{ALERT}) "
        "RETURN a.incident_id AS id",
        {"case_id": case_id},
    )
    ref = decision["playbook"]
    if ref is None and head["case_pb_name"] is not None:
        ref = {"name": head["case_pb_name"], "version": head["case_pb_version"]}
    playbook = None
    if ref is not None:
        playbook = next(
            (p for p in await list_playbooks(tenant)
             if (p["name"], p["version"]) == (ref["name"], ref["version"])),
            None,
        )  # fmt: skip
    findings = from_json(head["findings"], {})
    return {
        "decision": decision,
        "case_id": case_id,
        "alerts": sorted(a["id"] for a in alerts),
        "acted_on": {
            "hosts": decision["target_hosts"],
            "users": decision["target_users"],
            "iocs": decision["target_iocs"],
        },
        "path": findings.get("shortest_path") or [],
        "playbook": playbook,
        "source_case": playbook["source_case"] if playbook else None,
    }


_ACTIVITY = f"""
MATCH (r:{RUN}) WHERE $since IS NULL OR r.at > $since
RETURN properties(r) AS r
"""


async def list_activity(tenant: str, since: str | None = None) -> list[dict[str, Any]]:
    """Agent steps after `since` (ISO timestamp), oldest first, with the worker that ran
    each one and the Investigator's tool calls (the UI's live activity feed)."""
    rows = await run_read(tenant, _ACTIVITY, {"since": since})
    return sorted((activity_item(r["r"]) for r in rows), key=lambda r: (r["at"] or "", r["id"]))


# ---------------------------------------------------------------------------
# Semantic facts (LLD §4.4.1)
# ---------------------------------------------------------------------------

_HOST_FACTS = f"""
UNWIND $names AS name
OPTIONAL MATCH (n:{HOST} {{hostname: name}})
RETURN name, n.targeted_case_ids AS targeted_case_ids, n.last_targeted_at AS last_targeted_at
"""
_USER_FACTS = f"""
UNWIND $names AS name
OPTIONAL MATCH (n:{USER} {{username: name}})
RETURN name, coalesce(n.suspected_compromised, false) AS suspected_compromised,
       n.suspected_at AS suspected_at, n.suspect_case_id AS suspect_case_id
"""
_IOC_FACTS = f"""
UNWIND $names AS name
OPTIONAL MATCH (n:{IOC} {{value: name}})
RETURN name, coalesce(n.verdict, 'unknown') AS verdict, n.owner AS owner,
       n.seen_case_ids AS seen_case_ids
"""


async def entity_facts(
    tenant: str, hosts: list[str], users: list[str], iocs: list[str]
) -> dict[str, dict[str, dict[str, Any]]]:
    """What the graph remembers about these hosts, users and IOCs (semantic memory).
    Names the graph has never seen get empty facts, so callers can read keys directly."""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for kind, query, names in (
        ("hosts", _HOST_FACTS, hosts),
        ("users", _USER_FACTS, users),
        ("iocs", _IOC_FACTS, iocs),
    ):
        rows = await run_read(tenant, query, {"names": list(dict.fromkeys(names))}) if names else []
        facts = {}
        for row in rows:
            name = row.pop("name")
            for key in ("targeted_case_ids", "seen_case_ids"):
                if key in row:
                    row[key] = list(row[key] or [])
            facts[name] = row
        out[kind] = facts
    return out
