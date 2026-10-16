"""Stub graph tools library: same names, signatures and return shapes as the real one,
no database (docs/LLD.md §4.6). Select it with ARGUS_GRAPH_BACKEND=stub.

State lives in memory and starts from the walkthrough's sample data:
- Acme, scenario 1: inc-7f3a (SSH brute force on bastion-01 that succeeded as svc_deploy,
  from 203.0.113.7) and inc-81c2 (credential stuffing from the same IP) are Case 31,
  awaiting approval of decision R1.
- Acme, scenario 2: inc-9b10 (the internal scanner 10.0.5.20) is Case 32, closed as benign;
  playbook "auto-close internal scanner" v1 was learned from it. inc-a412 (the scanner again)
  and inc-c5e0 (SQL injection from 198.51.100.23) are new alerts waiting for Triage.
- Globex: one new alert, inc-d901, from the same attacker IP, and no memory of Acme.

Writes change that state, so later reads see them. `reset_stubs()` restores the start.
Every function returns plain Python types (dicts, lists, ints, strings): copies, never
the stored objects. Unknown tenants raise UnknownTenant, like the real library.
"""

import copy
import itertools
from datetime import UTC, datetime, timedelta
from typing import Any

from argus_soc.core.tenant_registry import graph_name
from argus_soc.graph.graph_schema import (
    OPEN_CASE_STATUSES,
    AlertInput,
    AlertStatus,
    CaseStatus,
    DecisionInput,
    DecisionOutcome,
    FeedbackVerdict,
    IocVerdict,
    PlaybookAction,
    PlaybookRef,
    Priority,
    SemanticFactsInput,
)
from argus_soc.graph.graph_stub_data import (
    ATTACKER_IP,
    CRITICALITY,
    LOGS_INTO,
    PATHS,
    RANK,
    SCANNER_IP,
    SCANNER_PLAYBOOK,
    SQLI_IP,
    empty_state,
    make_case,
    sample_state,
)

# Re-exported so tests and teammates can use the sample values.
__all__ = ["ATTACKER_IP", "SCANNER_IP", "SCANNER_PLAYBOOK", "SQLI_IP", "reset_stubs"]

_ids = itertools.count(1000)
_STATE: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{next(_ids)}"


def _t(tenant: str) -> dict[str, Any]:
    graph_name(tenant)  # UnknownTenant for anything not in ARGUS_TENANTS
    return _STATE.setdefault(tenant, empty_state())


def reset_stubs() -> None:
    """Back to the sample data (tests call this between cases)."""
    _STATE.clear()
    _STATE.update(sample_state())


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def _as_list(value: str | list[str] | tuple[str, ...] | None) -> set[str]:
    if value is None:
        return set()
    return {value} if isinstance(value, str) else set(value)


def _case_alerts(s: dict[str, Any], case: dict[str, Any]) -> list[dict[str, Any]]:
    return [s["alerts"][i] for i in case["alert_ids"] if i in s["alerts"]]


def _case_entities(s: dict[str, Any], case: dict[str, Any], key: str) -> list[str]:
    return sorted({v for a in _case_alerts(s, case) for v in a[key]})


async def blast_radius(tenant: str, ioc: str) -> list[dict[str, Any]]:
    """Q1: hosts and accounts linked to alerts involving the IOC, most critical first."""
    s = _t(tenant)
    rows: dict[str, dict[str, Any]] = {}
    for a in s["alerts"].values():
        if ioc not in a["iocs"]:
            continue
        for host in a["hosts"]:
            row = rows.setdefault(
                host,
                {
                    "host": host,
                    "criticality": CRITICALITY.get(host, 1),
                    "accounts": set(),
                    "reached_hosts": set(),
                    "alerts": 0,
                },
            )
            row["alerts"] += 1
            for user in a["users"]:
                row["accounts"].add(user)
                row["reached_hosts"].update(LOGS_INTO.get(user, []))
    out = [
        {**r, "accounts": sorted(r["accounts"]), "reached_hosts": sorted(r["reached_hosts"])}
        for r in rows.values()
    ]
    return sorted(out, key=lambda r: (-r["criticality"], r["host"]))


async def paths_to_crown_jewels(tenant: str, host: str, max_hops: int = 6) -> list[list[str]]:
    """Q2: shortest paths from the host to crown-jewel hosts, as node names, max 3."""
    _t(tenant)
    path = PATHS.get(host) if tenant == "acme" else None
    return [list(path)] if path and len(path) - 1 <= max_hops else []


async def rank_hosts(tenant: str, case_id: int) -> list[tuple[str, float]]:
    """Q3: (hostname, score), best host to act on first."""
    s = _t(tenant)
    case = s["cases"].get(case_id)
    if case is None:
        return []
    hosts = _case_entities(s, case, "hosts")
    ranked = [(h, RANK.get(h, round(CRITICALITY.get(h, 1) / 10, 2))) for h in hosts]
    return sorted(ranked, key=lambda r: (-r[1], r[0]))


async def recall(
    tenant: str,
    ioc: str | list[str] | None = None,
    host: str | list[str] | None = None,
    user: str | list[str] | None = None,
) -> list[dict[str, Any]]:
    """Q4: closed cases with alerts involving any of these, newest first, max 5."""
    s = _t(tenant)
    iocs, hosts, users = _as_list(ioc), _as_list(host), _as_list(user)
    out = []
    for case in s["cases"].values():
        if case["status"] not in (CaseStatus.CLOSED, CaseStatus.AUTO_CLOSED):
            continue
        if any(
            iocs & set(a["iocs"]) or hosts & set(a["hosts"]) or users & set(a["users"])
            for a in _case_alerts(s, case)
        ):
            notes = [s["feedback"][f]["note"] for f in case["feedback_ids"]]
            out.append(
                {
                    "case_id": case["id"],
                    "verdict": case["verdict"],
                    "closed_at": case["closed_at"],
                    "note": notes[-1] if notes else None,
                }
            )
    return sorted(out, key=lambda r: r["closed_at"] or "", reverse=True)[:5]


async def linked_alerts(tenant: str, incident_id: str, window_hours: int = 24) -> list[str]:
    """Q5: other live alerts that share an IOC or a user with this one, within the window.

    A shared host alone does not link (two attackers can hit the same web server), and
    alerts already in a closed or auto-closed case are never returned.
    """
    s = _t(tenant)
    alert = s["alerts"].get(incident_id)
    if alert is None:
        return []
    keys = set(alert["users"]) | set(alert["iocs"])
    at = datetime.fromisoformat(alert["talos_created_at"])
    window = timedelta(hours=window_hours)
    return sorted(
        other["incident_id"]
        for other in s["alerts"].values()
        if other["incident_id"] != incident_id
        and keys & (set(other["users"]) | set(other["iocs"]))
        and abs(datetime.fromisoformat(other["talos_created_at"]) - at) <= window
        and not _in_closed_case(s, other["incident_id"])
    )


async def explain_decision(tenant: str, decision_id: str) -> dict[str, Any] | None:
    """Q6: the decision with its case, alerts, acted-on nodes, path, playbook and source case."""
    s = _t(tenant)
    d = s["decisions"].get(decision_id)
    if d is None:
        return None
    case = s["cases"][d["case_id"]]
    pb = d["playbook"] or case["applied_playbook"]
    playbook = next(
        (
            p
            for p in s["playbooks"]
            if pb and (p["name"], p["version"]) == (pb["name"], pb["version"])
        ),
        None,
    )
    return copy.deepcopy(
        {
            "decision": d,
            "case_id": case["id"],
            "alerts": case["alert_ids"],
            "acted_on": {
                "hosts": d["target_hosts"],
                "users": d["target_users"],
                "iocs": d["target_iocs"],
            },
            "path": case["findings"].get("shortest_path") or [],
            "playbook": playbook,
            "source_case": playbook["source_case"] if playbook else None,
        }
    )


async def entity_facts(
    tenant: str, hosts: list[str], users: list[str], iocs: list[str]
) -> dict[str, dict[str, dict[str, Any]]]:
    """Semantic facts on these nodes (LLD §4.4.1); unknown names get empty facts."""
    s = _t(tenant)
    blank = {
        "hosts": {"targeted_case_ids": [], "last_targeted_at": None},
        "users": {"suspected_compromised": False, "suspected_at": None, "suspect_case_id": None},
        "iocs": {"verdict": IocVerdict.UNKNOWN, "owner": None, "seen_case_ids": []},
    }
    asked = {"hosts": hosts, "users": users, "iocs": iocs}
    return copy.deepcopy(
        {
            kind: {name: {**blank[kind], **s[kind].get(name, {})} for name in names}
            for kind, names in asked.items()
        }
    )


async def matching_playbook(tenant: str, alert: dict[str, Any]) -> dict[str, Any] | None:
    """Newest active playbook whose category matches and whose ioc_in shares an IOC."""
    s = _t(tenant)
    for pb in sorted(s["playbooks"], key=lambda p: -p["version"]):
        cond = pb["condition"]
        if (
            pb["active"]
            and alert.get("category") == cond.get("category")
            and set(alert.get("iocs", [])) & set(cond.get("ioc_in", []))
        ):
            return copy.deepcopy(pb)
    return None


async def list_new_alerts(tenant: str, limit: int = 20) -> list[dict[str, Any]]:
    """Alerts not yet in a case, oldest first."""
    s = _t(tenant)
    new = [a for a in s["alerts"].values() if a["status"] == AlertStatus.NEW]
    return copy.deepcopy(sorted(new, key=lambda a: a["talos_created_at"])[:limit])


async def known_incident_ids(tenant: str, ids: list[str]) -> set[str]:
    return set(ids) & set(_t(tenant)["alerts"])


def _summary(s: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    decision = s["decisions"].get(c["decision_id"]) if c["decision_id"] else None
    pb = c["applied_playbook"]
    return {
        "id": c["id"],
        "status": str(c["status"]),
        "priority": str(c["priority"]),
        "category": c["category"],
        "alert_count": len(c["alert_ids"]),
        "opened_at": c["opened_at"],
        "updated_at": c["updated_at"],
        "needs_approval": bool(
            decision and decision["needs_approval"] and c["status"] == CaseStatus.AWAITING_APPROVAL
        ),
        "auto_closed_by": f"{pb['name']} v{pb['version']}" if pb else None,
    }


async def list_cases(tenant: str, status: str | None = None, limit: int = 100) -> list[dict]:
    """Case summaries for the UI queue, newest first."""
    s = _t(tenant)
    rows = [_summary(s, c) for c in s["cases"].values() if status in (None, c["status"])]
    return sorted(rows, key=lambda r: r["opened_at"], reverse=True)[:limit]


def _feedback_item(f: dict[str, Any]) -> dict[str, Any]:
    """Feedback as get_case returns it (CONTRACT_GAPS GAP-4)."""
    return {k: f[k] for k in ("id", "verdict", "note", "analyst", "created_at")}


async def get_case(tenant: str, case_id: int) -> dict[str, Any] | None:
    """Everything about one case, or None if there is no such case."""
    s = _t(tenant)
    c = s["cases"].get(case_id)
    if c is None:
        return None
    return copy.deepcopy(
        {
            **_summary(s, c),
            "closed_at": c["closed_at"],
            "verdict": c["verdict"],
            "closed_reason": c["closed_reason"],
            "claimed_by": c["claimed_by"],
            "alerts": _case_alerts(s, c),
            "hosts": _case_entities(s, c, "hosts"),
            "users": _case_entities(s, c, "users"),
            "iocs": _case_entities(s, c, "iocs"),
            "findings": c["findings"],
            "decision": s["decisions"].get(c["decision_id"]) if c["decision_id"] else None,
            "feedback": [_feedback_item(s["feedback"][f]) for f in c["feedback_ids"]],
            "agent_runs": [r for r in s["runs"] if r["case_id"] == c["id"]],
        }
    )


async def list_playbooks(tenant: str) -> list[dict[str, Any]]:
    return copy.deepcopy(sorted(_t(tenant)["playbooks"], key=lambda p: (p["name"], p["version"])))


async def list_activity(tenant: str, since: str | None = None) -> list[dict[str, Any]]:
    """AgentRun entries after `since` (ISO timestamp), oldest first."""
    runs = [r for r in _t(tenant)["runs"] if since is None or r["at"] > since]
    return copy.deepcopy(sorted(runs, key=lambda r: r["at"]))


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def _get_case(s: dict[str, Any], case_id: int) -> dict[str, Any]:
    if case_id not in s["cases"]:
        raise KeyError(f"no case {case_id}")
    return s["cases"][case_id]


async def upsert_alert_from_report(tenant: str, alert: AlertInput) -> str:
    """Store one Talos report as an Alert. The same incident_id twice is one alert."""
    s = _t(tenant)
    old = s["alerts"].get(alert.incident_id)
    s["alerts"][alert.incident_id] = {
        **alert.model_dump(mode="json", exclude={"source_ips"}),
        "iocs": list(alert.source_ips),
        "ingested_at": old["ingested_at"] if old else _now(),
        "status": old["status"] if old else str(AlertStatus.NEW),
    }
    return alert.incident_id


def _in_closed_case(s: dict[str, Any], incident_id: str) -> bool:
    return any(
        incident_id in c["alert_ids"] and c["status"] in (CaseStatus.CLOSED, CaseStatus.AUTO_CLOSED)
        for c in s["cases"].values()
    )


def _eligible(s: dict[str, Any], incident_ids: list[str]) -> list[str]:
    """Safety net: an alert already in a closed case never goes into another case."""
    ids = [i for i in dict.fromkeys(incident_ids) if not _in_closed_case(s, i)]
    if not ids:
        raise ValueError(f"all of {list(incident_ids)} are already in closed cases")
    return ids


def _open_case(s: dict[str, Any], ids: list[str], status: str, priority: str, **extra: Any) -> int:
    case_id = max(s["cases"], default=0) + 1
    first = s["alerts"].get(ids[0], {}) if ids else {}
    s["cases"][case_id] = make_case(
        case_id, status, priority, first.get("category"), list(ids), _now(), **extra
    )
    for i in ids:
        if i in s["alerts"]:
            s["alerts"][i]["status"] = str(AlertStatus.CASED)
    return case_id


async def open_or_join_case(tenant: str, incident_ids: list[str], priority: str) -> int:
    """Add the alerts to the open case that holds one of them, or open a new case.
    Alerts already in a closed case are left out; ValueError if that leaves none."""
    s = _t(tenant)
    Priority(priority)
    ids = _eligible(s, incident_ids)
    for case in s["cases"].values():
        if case["status"] in OPEN_CASE_STATUSES and set(ids) & set(case["alert_ids"]):
            case["alert_ids"] += [i for i in ids if i not in case["alert_ids"]]
            for i in ids:
                if i in s["alerts"]:
                    s["alerts"][i]["status"] = str(AlertStatus.CASED)
            case["updated_at"] = _now()
            return case["id"]
    return _open_case(s, ids, CaseStatus.NEW, priority)


async def close_case_auto(
    tenant: str, incident_ids: list[str], playbook_ref: PlaybookRef, reason: str
) -> int:
    """Open a case directly as auto_closed, citing the playbook that closed it.
    Alerts already in a closed case are left out; ValueError if that leaves none."""
    s = _t(tenant)
    now = _now()
    return _open_case(
        s,
        _eligible(s, incident_ids),
        CaseStatus.AUTO_CLOSED,
        Priority.INFO,
        closed_at=now,
        closed_reason=reason,
        verdict="benign",
        applied_playbook=playbook_ref.model_dump(),
    )


async def claim_case(tenant: str, status: str, agent: str, ttl_seconds: int) -> int | None:
    """Claim the oldest case in `status` with no claim or an expired one."""
    s = _t(tenant)
    CaseStatus(status)
    now = datetime.now(UTC)
    expired_before = (now - timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds")
    free = [
        c
        for c in s["cases"].values()
        if c["status"] == status and (c["claimed_by"] is None or c["claimed_at"] < expired_before)
    ]
    if not free:
        return None
    case = min(free, key=lambda c: c["updated_at"])
    case["claimed_by"], case["claimed_at"] = agent, now.isoformat(timespec="seconds")
    return case["id"]


async def set_case_status(
    tenant: str, case_id: int, status: str, priority: str | None = None
) -> None:
    """Move the case on and release its claim."""
    s = _t(tenant)
    case = _get_case(s, case_id)
    case["status"] = CaseStatus(status)
    if priority is not None:
        case["priority"] = Priority(priority)
    case["claimed_by"] = case["claimed_at"] = None
    case["updated_at"] = _now()
    if case["status"] in (CaseStatus.CLOSED, CaseStatus.AUTO_CLOSED) and not case["closed_at"]:
        case["closed_at"] = case["updated_at"]


async def record_findings(tenant: str, case_id: int, findings: dict[str, Any]) -> None:
    """Store findings on the case. Top-level keys are added or replaced, others kept."""
    case = _get_case(_t(tenant), case_id)
    case["findings"].update(copy.deepcopy(findings))
    case["updated_at"] = _now()


def _apply_actions(s: dict[str, Any], d: dict[str, Any]) -> None:
    """Simulated response: flags only, never real infrastructure (rule 10)."""
    for host in d["target_hosts"]:
        s["hosts"].setdefault(host, {})["isolated"] = True
    for user in d["target_users"]:
        s["users"].setdefault(user, {})["disabled"] = True


async def record_decision(tenant: str, case_id: int, decision: DecisionInput) -> str:
    """Store the decision. Actions that need approval are applied only once approved.
    One decision per case: calling again returns the existing one."""
    s = _t(tenant)
    case = _get_case(s, case_id)
    if case["decision_id"]:  # one decision per case; a retried step gets the same one
        return case["decision_id"]
    did = _new_id("dec")
    d = {
        **decision.model_dump(mode="json"),
        "id": did,
        "case_id": case_id,
        "outcome": DecisionOutcome.PENDING if decision.needs_approval else DecisionOutcome.AUTO,
        "created_at": _now(),
    }
    s["decisions"][did] = d
    case["decision_id"] = did
    if not decision.needs_approval:
        _apply_actions(s, d)
    return did


async def record_feedback(tenant: str, case_id: int, verdict: str, note: str, analyst: str) -> str:
    """Analyst verdict on a case: sets the decision outcome and the IOC verdicts."""
    s = _t(tenant)
    case = _get_case(s, case_id)
    v = FeedbackVerdict(verdict)
    fid = _new_id("fb")
    s["feedback"][fid] = {
        "id": fid,
        "case_id": case_id,
        "verdict": str(v),
        "note": note,
        "analyst": analyst,
        "created_at": _now(),
    }
    case["feedback_ids"].append(fid)
    decision = s["decisions"].get(case["decision_id"]) if case["decision_id"] else None
    if decision and decision["outcome"] == DecisionOutcome.PENDING:
        decision["outcome"] = {FeedbackVerdict.APPROVE: DecisionOutcome.APPROVED}.get(
            v, DecisionOutcome.REJECTED
        )
        if v == FeedbackVerdict.APPROVE:
            _apply_actions(s, decision)
    ioc_verdict = {
        FeedbackVerdict.APPROVE: IocVerdict.MALICIOUS,
        FeedbackVerdict.BENIGN: IocVerdict.BENIGN,
    }.get(v)
    if ioc_verdict:
        for ioc in _case_entities(s, case, "iocs"):
            s["iocs"].setdefault(ioc, {})["verdict"] = ioc_verdict
    if v == FeedbackVerdict.BENIGN:
        case["verdict"] = "benign"
    return fid


async def create_playbook_version(
    tenant: str, feedback_id: str, condition: dict[str, Any], action: str
) -> dict[str, Any]:
    """Next version of the playbook with this condition; older versions are deactivated."""
    s = _t(tenant)
    fb = s["feedback"][feedback_id]
    PlaybookAction(action)
    same = [p for p in s["playbooks"] if p["condition"] == condition]
    category = condition.get("category")
    name = same[0]["name"] if same else f"auto-close {category} learned from case {fb['case_id']}"
    for p in same:
        p["active"] = False
    version = max((p["version"] for p in same), default=0) + 1
    s["playbooks"].append(
        {
            "name": name,
            "version": version,
            "active": True,
            "condition": copy.deepcopy(condition),
            "action": action,
            "source_case": fb["case_id"],
            "learned_from": feedback_id,
            "created_at": _now(),
        }
    )
    return {"name": name, "version": version}


async def set_ioc_fact(tenant: str, ioc: str, key: str, value: Any) -> None:
    """Semantic fact on an IOC: `owner` (free text) or `verdict`."""
    if key not in ("owner", "verdict"):
        raise ValueError(f"unknown IOC fact {key!r}")
    s = _t(tenant)
    s["iocs"].setdefault(ioc, {})[key] = IocVerdict(value) if key == "verdict" else value


async def record_semantic_facts(tenant: str, case_id: int, facts: SemanticFactsInput) -> None:
    """Remember that these hosts and IOCs were in this case. Writing it twice changes nothing."""
    s = _t(tenant)
    _get_case(s, case_id)
    now = _now()
    for host in facts.hosts:
        h = s["hosts"].setdefault(host, {"targeted_case_ids": []})
        h.setdefault("targeted_case_ids", [])
        if case_id not in h["targeted_case_ids"]:
            h["targeted_case_ids"].append(case_id)
        h["last_targeted_at"] = now
    for ioc in facts.iocs:
        i = s["iocs"].setdefault(ioc, {})
        i.setdefault("seen_case_ids", [])
        if case_id not in i["seen_case_ids"]:
            i["seen_case_ids"].append(case_id)
    for user in facts.suspected_users:
        s["users"].setdefault(user, {}).update(
            suspected_compromised=True, suspected_at=now, suspect_case_id=case_id
        )


async def record_agent_run(
    tenant: str,
    agent: str,
    case_id: int | None,
    summary: str,
    handed_to: str | None = None,
    worker: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> str:
    """One agent step, for the activity feed. `handed_to` records a handoff."""
    s = _t(tenant)
    rid = _new_id("run")
    s["runs"].append(
        {
            "id": rid,
            "at": _now(),
            "agent": agent,
            "worker": worker,
            "case_id": case_id,
            "summary": summary,
            "handed_to": handed_to,
            "tool_calls": copy.deepcopy(tool_calls),
        }
    )
    return rid


reset_stubs()
