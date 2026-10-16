"""Read functions of the graph tools library, real FalkorDB versions (docs/LLD.md §4.4).

All read-only queries (GRAPH.RO_QUERY), every value passed as a parameter, results
returned as plain Python types in the same shapes as graph_stubs.
"""

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
