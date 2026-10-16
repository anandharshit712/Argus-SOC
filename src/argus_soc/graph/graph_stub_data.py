"""Sample data for the stub graph library (graph_stubs.py).

Values follow the walkthrough (docs/design/Argus SOC with Talos.html): the incident ids,
categories, hosts and IPs are the ones Talos produces for the four demo scenarios.
"""

from typing import Any

from argus_soc.graph.graph_schema import (
    AlertStatus,
    CaseStatus,
    DecisionOutcome,
    IocVerdict,
    PlaybookAction,
    Priority,
)

ATTACKER_IP = "203.0.113.7"
SQLI_IP = "198.51.100.23"
SCANNER_IP = "10.0.5.20"
SCANNER_PLAYBOOK = "auto-close internal scanner"

# Environment the stubs pretend was seeded (subset of data/inventory/).
CRITICALITY = {"bastion-01": 3, "app-02": 4, "db-prod-01": 5, "web-01": 2, "vpn-gw": 3}
LOGS_INTO = {"svc_deploy": ["app-02", "bastion-01"]}
PATHS = {"bastion-01": ["bastion-01", "app-02", "db-prod-01"], "app-02": ["app-02", "db-prod-01"]}
RANK = {"bastion-01": 0.81, "app-02": 0.64}


def empty_state() -> dict[str, Any]:
    return {
        "alerts": {},
        "cases": {},
        "decisions": {},
        "feedback": {},
        "playbooks": [],
        "runs": [],
        "hosts": {},
        "users": {},
        "iocs": {},
    }


def _alert(
    iid: str,
    domain: str,
    category: str,
    severity: str,
    confidence: float,
    succeeded: bool,
    summary: str,
    at: str,
    *,
    hosts=(),
    users=(),
    endpoints=(),
    iocs=(),
    techniques=(),
    status=AlertStatus.CASED,
    actions=(),
) -> dict[str, Any]:
    return {
        "incident_id": iid,
        "domain": domain,
        "category": category,
        "severity": severity,
        "confidence": confidence,
        "succeeded": succeeded,
        "summary": summary,
        "evidence": [],
        "recommended_actions": list(actions),
        "talos_created_at": at,
        "ingested_at": at,
        "status": str(status),
        "hosts": list(hosts),
        "users": list(users),
        "endpoints": list(endpoints),
        "iocs": list(iocs),
        "techniques": [{"mitre_id": t, "name": None, "tactic": None} for t in techniques],
    }


def make_case(
    cid: int,
    status: str,
    priority: str,
    category: str,
    alert_ids: list[str],
    opened: str,
    **extra: Any,
) -> dict[str, Any]:
    case = {
        "id": cid,
        "status": status,
        "priority": priority,
        "category": category,
        "alert_ids": alert_ids,
        "opened_at": opened,
        "updated_at": opened,
        "closed_at": None,
        "claimed_by": None,
        "claimed_at": None,
        "findings": {},
        "verdict": None,
        "closed_reason": None,
        "decision_id": None,
        "feedback_ids": [],
        "applied_playbook": None,
    }
    case.update(extra)
    return case


def _acme() -> dict[str, Any]:
    s = empty_state()
    for a in (
        _alert(
            "inc-9b10",
            "web",
            "auth_failure",
            "medium",
            0.72,
            False,
            "credential_stuffing on /login over 16 accounts -- did not succeed",
            "2026-10-15T09:10:00+00:00",
            hosts=["web-01"],
            endpoints=["/login"],
            iocs=[SCANNER_IP],
            techniques=["T1110.004"],
        ),
        _alert(
            "inc-7f3a",
            "network",
            "network_brute_force",
            "high",
            0.90,
            True,
            "brute_force on bastion-01 against svc_deploy over 12 attempts -- succeeded",
            "2026-10-16T10:02:00+00:00",
            hosts=["bastion-01"],
            users=["svc_deploy"],
            iocs=[ATTACKER_IP],
            techniques=["T1110"],
            actions=[f"block source IP {ATTACKER_IP} at the perimeter"],
        ),
        _alert(
            "inc-81c2",
            "web",
            "auth_failure",
            "medium",
            0.76,
            False,
            "credential_stuffing on /login over 18 accounts -- did not succeed",
            "2026-10-16T10:04:00+00:00",
            hosts=["app-02"],
            endpoints=["/login"],
            iocs=[ATTACKER_IP],
            techniques=["T1110.004", "T1110"],
        ),
        _alert(
            "inc-a412",
            "web",
            "auth_failure",
            "medium",
            0.70,
            False,
            "credential_stuffing on /login over 15 accounts -- did not succeed",
            "2026-10-16T11:00:00+00:00",
            hosts=["web-01"],
            endpoints=["/login"],
            iocs=[SCANNER_IP],
            techniques=["T1110.004"],
            status=AlertStatus.NEW,
        ),
        _alert(
            "inc-c5e0",
            "web",
            "injection",
            "high",
            0.88,
            False,
            "sqli on /api/search -- did not succeed",
            "2026-10-16T11:05:00+00:00",
            hosts=["web-01"],
            endpoints=["/api/search"],
            iocs=[SQLI_IP],
            techniques=["T1190"],
            status=AlertStatus.NEW,
            actions=[f"block source IP {SQLI_IP}"],
        ),
    ):
        s["alerts"][a["incident_id"]] = a

    s["cases"][32] = make_case(
        32,
        CaseStatus.CLOSED,
        Priority.MEDIUM,
        "auth_failure",
        ["inc-9b10"],
        "2026-10-15T09:11:00+00:00",
        closed_at="2026-10-15T09:40:00+00:00",
        verdict="benign",
        closed_reason="analyst: benign",
        feedback_ids=["fb-32"],
    )
    s["cases"][31] = make_case(
        31,
        CaseStatus.AWAITING_APPROVAL,
        Priority.HIGH,
        "network_brute_force",
        ["inc-7f3a", "inc-81c2"],
        "2026-10-16T10:03:00+00:00",
        decision_id="dec-31",
        findings={
            "succeeded": True,
            "path_to_crown_jewel": True,
            "shortest_path": PATHS["bastion-01"],
            "blast_radius": [
                {
                    "host": "bastion-01",
                    "criticality": 3,
                    "accounts": ["svc_deploy"],
                    "reached_hosts": ["app-02", "bastion-01"],
                    "alerts": 1,
                }
            ],
        },
    )
    s["decisions"]["dec-31"] = {
        "id": "dec-31",
        "case_id": 31,
        "rule_id": "R1",
        "actions": ["isolate_top_host", "disable_accounts", "block_ips"],
        "target_hosts": ["bastion-01"],
        "target_users": ["svc_deploy"],
        "target_iocs": [ATTACKER_IP],
        "needs_approval": True,
        "reason": "Attack succeeded and bastion-01 reaches crown jewel db-prod-01.",
        "explanation": "svc_deploy logged in on bastion-01 after 12 failures; bastion-01 -> "
        "app-02 -> db-prod-01. bastion-01 ranks highest.",
        "evidence": {"ranking": [["bastion-01", 0.81], ["app-02", 0.64]]},
        "outcome": DecisionOutcome.PENDING,
        "playbook": None,
        "agent": "responder",
        "created_at": "2026-10-16T10:05:30+00:00",
    }
    s["feedback"]["fb-32"] = {
        "id": "fb-32",
        "case_id": 32,
        "verdict": "benign",
        "note": "internal pentest scanner",
        "analyst": "analyst1",
        "created_at": "2026-10-15T09:40:00+00:00",
    }
    s["playbooks"].append(
        {
            "name": SCANNER_PLAYBOOK,
            "version": 1,
            "active": True,
            "condition": {"category": "auth_failure", "ioc_in": [SCANNER_IP]},
            "action": PlaybookAction.AUTO_CLOSE,
            "source_case": 32,
            "learned_from": "fb-32",
            "created_at": "2026-10-15T09:41:00+00:00",
        }
    )
    for i, (agent, handed) in enumerate(
        (("triage", "investigator"), ("investigator", "responder"), ("responder", None))
    ):
        s["runs"].append(
            {
                "id": f"run-31-{i}",
                "at": f"2026-10-16T10:0{3 + i}:30+00:00",
                "agent": agent,
                "worker": "agents-1",
                "case_id": 31,
                "summary": f"{agent} finished case 31",
                "handed_to": handed,
                "tool_calls": None,
            }
        )
    seen = "2026-10-16T10:04:10+00:00"
    s["hosts"]["bastion-01"] = {"targeted_case_ids": [31], "last_targeted_at": seen}
    s["users"]["svc_deploy"] = {
        "suspected_compromised": True,
        "suspected_at": seen,
        "suspect_case_id": 31,
    }
    s["iocs"][ATTACKER_IP] = {"verdict": IocVerdict.UNKNOWN, "owner": None, "seen_case_ids": [31]}
    s["iocs"][SCANNER_IP] = {
        "verdict": IocVerdict.BENIGN,
        "owner": "internal pentest scanner",
        "seen_case_ids": [32],
    }
    return s


def _globex() -> dict[str, Any]:
    s = empty_state()
    a = _alert(
        "inc-d901",
        "network",
        "network_brute_force",
        "medium",
        0.72,
        False,
        "brute_force on vpn-gw against admin over 9 attempts -- did not succeed",
        "2026-10-16T11:10:00+00:00",
        hosts=["vpn-gw"],
        users=["admin"],
        iocs=[ATTACKER_IP],
        techniques=["T1110"],
        status=AlertStatus.NEW,
    )
    s["alerts"][a["incident_id"]] = a
    return s


def sample_state() -> dict[str, dict[str, Any]]:
    """Fresh copy of every tenant's starting state."""
    return {"acme": _acme(), "globex": _globex()}
