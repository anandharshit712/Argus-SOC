"""Graph tools library dicts -> API models (docs/LLD.md §7).

The graph functions return plain dicts in the same shape for the FalkorDB and stub backends;
this module is the one place that knows how those dicts become the UI contract.
"""

import json
from typing import Any

from pydantic import ValidationError

from argus_backend.api_models import (
    ActivityItem,
    AlertOut,
    CaseDetail,
    CaseSummary,
    DecisionOut,
    FeedbackItemOut,
    FindingsOut,
    PathNode,
    PlaybookOut,
    ToolCallOut,
)

# Talos evidence comes from attacker-controlled log lines (rule 9): sent as plain text, cut short.
EVIDENCE_MAX_ITEMS = 20
EVIDENCE_MAX_CHARS = 500


def playbook_label(name: str, version: int) -> str:
    """How the graph names a playbook version on a case: "<name> v<version>"."""
    return f"{name} v{version}"


def source_cases(playbooks: list[dict[str, Any]]) -> dict[str, int | None]:
    """ "<name> v<version>" -> the case the playbook was learned from."""
    return {playbook_label(p["name"], p["version"]): p.get("source_case") for p in playbooks}


def to_summary(case: dict[str, Any], sources: dict[str, int | None]) -> CaseSummary:
    auto = case.get("auto_closed_by")
    return CaseSummary(
        id=case["id"],
        status=case["status"],
        priority=case["priority"],
        category=case.get("category"),
        alert_count=case.get("alert_count") or 0,
        opened_at=case.get("opened_at"),
        updated_at=case.get("updated_at"),
        needs_approval=bool(case.get("needs_approval")),
        auto_closed_by=auto,
        auto_closed_source_case=sources.get(auto) if auto else None,
    )


def _evidence(raw: Any) -> list[str]:
    items = raw if isinstance(raw, list) else ([] if raw is None else [raw])
    out = []
    for item in items[:EVIDENCE_MAX_ITEMS]:
        text = item if isinstance(item, str) else json.dumps(item, default=str)
        out.append(text if len(text) <= EVIDENCE_MAX_CHARS else text[:EVIDENCE_MAX_CHARS] + "…")
    return out


def to_alert(alert: dict[str, Any]) -> AlertOut:
    return AlertOut(
        incident_id=alert["incident_id"],
        category=alert.get("category"),
        severity=alert.get("severity"),
        confidence=alert.get("confidence"),
        succeeded=alert.get("succeeded"),
        summary=alert.get("summary"),
        evidence=_evidence(alert.get("evidence")),
        talos_actions=[str(a) for a in alert.get("recommended_actions") or []],
    )


def _tool_calls(raw: Any) -> list[ToolCallOut] | None:
    if not isinstance(raw, list):
        return None
    calls = []
    for call in raw:
        if isinstance(call, dict) and call.get("tool"):
            result = call.get("result")
            calls.append(
                ToolCallOut(
                    tool=str(call["tool"]),
                    args={k: v for k, v in (call.get("args") or {}).items() if k != "tenant"},
                    result=result
                    if result is None or isinstance(result, str)
                    else json.dumps(result),
                    why=call.get("why"),
                )
            )
    return calls


def to_activity(run: dict[str, Any]) -> ActivityItem:
    return ActivityItem(
        id=run.get("id"),
        at=run.get("at"),
        agent=run.get("agent"),
        worker=run.get("worker"),
        case_id=run.get("case_id"),
        summary=run.get("summary"),
        handed_to=run.get("handed_to"),
        tool_calls=_tool_calls(run.get("tool_calls")),
    )


def _path(names: Any, users: set[str]) -> list[PathNode]:
    """The attack path from findings.shortest_path. It runs over host links and account logins
    (algo.SPpaths), so a node can be a user: those are labelled from the case's own users."""
    if not isinstance(names, list):
        return []
    return [PathNode(name=str(n), label="User" if n in users else "Host") for n in names]


def _ranking(evidence: Any) -> list[tuple[str, float]]:
    rows = evidence.get("ranking") if isinstance(evidence, dict) else None
    out = []
    for row in rows or []:
        if isinstance(row, list | tuple) and len(row) == 2:
            try:
                out.append((str(row[0]), float(row[1])))
            except (TypeError, ValueError):
                continue
    return out


def to_decision(decision: dict[str, Any], findings: dict[str, Any], users: set[str]) -> DecisionOut:
    playbook = decision.get("playbook")
    return DecisionOut(
        id=decision["id"],
        rule_id=decision.get("rule_id"),
        actions=list(decision.get("actions") or []),
        needs_approval=bool(decision.get("needs_approval")),
        reason=decision.get("reason"),
        explanation=decision.get("explanation"),
        outcome=decision.get("outcome"),
        path=_path(findings.get("shortest_path"), users),
        ranking=_ranking(decision.get("evidence")),
        previous_priority=decision.get("previous_priority"),
        target_hosts=list(decision.get("target_hosts") or []),
        target_users=list(decision.get("target_users") or []),
        target_iocs=list(decision.get("target_iocs") or []),
        playbook=playbook_label(playbook["name"], playbook["version"]) if playbook else None,
        agent=decision.get("agent"),
        created_at=decision.get("created_at"),
    )


def to_feedback(row: dict[str, Any]) -> FeedbackItemOut:
    return FeedbackItemOut(
        id=row["id"],
        verdict=row["verdict"],
        note=row.get("note") or "",
        analyst=row.get("analyst") or "",
        created_at=row.get("created_at"),
    )


def _findings(raw: dict[str, Any]) -> FindingsOut:
    """Typed findings. A key in an unexpected shape is dropped rather than failing the whole
    case detail (the main demo screen)."""
    data = dict(raw)
    if "deep_dive" in data:
        data["deep_dive"] = _tool_calls(data["deep_dive"])
    try:
        return FindingsOut.model_validate(data)
    except ValidationError as exc:
        bad = {err["loc"][0] for err in exc.errors() if err["loc"]}
        return FindingsOut.model_validate({k: v for k, v in data.items() if k not in bad})


def to_detail(case: dict[str, Any], sources: dict[str, int | None]) -> CaseDetail:
    findings = case.get("findings") if isinstance(case.get("findings"), dict) else {}
    users = set(case.get("users") or [])
    decision = case.get("decision")
    return CaseDetail(
        **to_summary(case, sources).model_dump(),
        closed_at=case.get("closed_at"),
        verdict=case.get("verdict"),
        closed_reason=case.get("closed_reason"),
        alerts=[to_alert(a) for a in case.get("alerts") or []],
        findings=_findings(findings),
        decision=to_decision(decision, findings, users) if decision else None,
        feedback=[to_feedback(f) for f in case.get("feedback") or []],
        agent_runs=[to_activity(r) for r in case.get("agent_runs") or []],
    )


def to_playbook(p: dict[str, Any]) -> PlaybookOut:
    return PlaybookOut(
        name=p["name"],
        version=p["version"],
        active=bool(p.get("active")),
        condition=p.get("condition") or {},
        action=None if p.get("action") is None else str(p["action"]),
        source_case=p.get("source_case"),
        created_at=p.get("created_at"),
    )
