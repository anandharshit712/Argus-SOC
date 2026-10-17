"""Responder agent (docs/LLD.md §6.5): decide, explain, act (simulated, rule 10).

The decision table picks the rule from the findings; Q3 ranks the hosts; the targets come
from the graph, never from the LLM or from Talos's recommended actions. Every decision
stores the findings and ranking it was made from (rule 6).
"""

import json
from typing import Any

from pydantic import BaseModel, Field

from argus_soc import graph
from argus_soc.agents import decision_table, llm_client
from argus_soc.agents.decision_table import Rule
from argus_soc.agents.handoff_service import hand_off
from argus_soc.agents.priority_rules import case_priority, lower_one
from argus_soc.core.logging_setup import get_logger
from argus_soc.graph.graph_schema import AgentName, CaseStatus, DecisionInput

AGENT = AgentName.RESPONDER


def targets(
    rule: Rule, case: dict[str, Any], ranking: list[tuple[str, float]]
) -> dict[str, tuple[str, ...]]:
    """What each action acts on. record_decision isolates every target host and disables
    every target user (once approved, or at once when no approval is needed), so only
    `isolate_top_host` and `disable_accounts` may name them. `watch_path_hosts` stays in the
    explanation: watching a host must not isolate it."""
    hosts: tuple[str, ...] = ()
    users: tuple[str, ...] = ()
    iocs: tuple[str, ...] = ()
    if "isolate_top_host" in rule.actions and ranking:
        hosts = (ranking[0][0],)
    if "disable_accounts" in rule.actions:
        # Accounts that were actually broken into, not every account the attacker tried.
        users = tuple(sorted({u for a in case["alerts"] if a["succeeded"] for u in a["users"]}))
    if {"block_ips", "block_or_rate_limit_ips"} & set(rule.actions):
        iocs = tuple(case["iocs"])
    return {"target_hosts": hosts, "target_users": users, "target_iocs": iocs}


class Explanation(BaseModel):
    text: str = Field(min_length=1, max_length=1200)


# Findings the LLM sees, one untrusted item each (they hold attacker-chosen names).
EXPLAINED_FINDINGS = (
    "succeeded",
    "path_to_crown_jewel",
    "shortest_path",
    "blast_radius",
    "memory_reasons",
    "deep_dive",
)


async def explanation(
    rule: Rule,
    case: dict[str, Any],
    ranking: list[tuple[str, float]],
    chosen: dict[str, tuple],
    priority: str,
) -> str:
    """The LLM's explanation of the decision, or the template when the LLM is off or fails.
    Either way the decision itself is already made."""
    findings = case["findings"]
    answer = await llm_client.complete(
        "responder_explain_v1",
        {
            "rule_id": rule.id,
            "rule_reason": rule.reason,
            "actions": ", ".join(rule.actions),
            "targets": llm_client.untrusted(
                [
                    f"{k.removeprefix('target_')}: {', '.join(v) or 'none'}"
                    for k, v in chosen.items()
                ]
            ),
            "needs_approval": "yes" if rule.needs_approval else "no",
            "priority": priority,
            "findings": llm_client.untrusted(
                [f"{k}: {json.dumps(findings.get(k), default=str)}" for k in EXPLAINED_FINDINGS]
            ),
            "ranking": ranking[:5],
            "evidence": llm_client.untrusted(
                [a["summary"] for a in case["alerts"]]
                + [line for a in case["alerts"] for line in a["evidence"][:3]]
            ),
        },
        Explanation,
    )
    return answer.text if answer else explain(rule, case, ranking, chosen)


def explain(
    rule: Rule, case: dict[str, Any], ranking: list[tuple[str, float]], chosen: dict[str, tuple]
) -> str:
    """The template explanation (used whenever the LLM is off or fails, LLD §6.8)."""
    findings = case["findings"]
    parts = [f"Rule {rule.id}: {rule.reason}."]
    if findings.get("shortest_path"):
        parts.append(f"Path: {' -> '.join(findings['shortest_path'])}.")
    if ranking:
        top = ", ".join(f"{h} ({s})" for h, s in ranking[:3])
        parts.append(f"Host ranking (centrality x criticality): {top}.")
    for key, label in (
        ("target_hosts", "Isolate"),
        ("target_users", "Disable"),
        ("target_iocs", "Block"),
    ):
        if chosen[key]:
            parts.append(f"{label}: {', '.join(chosen[key])}.")
    if "watch_path_hosts" in rule.actions and findings.get("shortest_path"):
        parts.append(f"Watch: {', '.join(findings['shortest_path'])}.")
    parts.append("Needs analyst approval." if rule.needs_approval else "Applied automatically.")
    return " ".join(parts)


async def _sent_back(tenant: str, case_id: int, case: dict[str, Any]) -> bool:
    """Send the case back to the Investigator if alerts joined after it was investigated
    (live test Oct 17, case 8: the "succeeded" alert came 9 s after the brute force, and the
    case closed as R3 instead of R1). True when sent back."""
    seen = case["findings"].get("investigated_alerts")
    now = sorted(a["incident_id"] for a in case["alerts"])
    if seen is None or seen == now:  # None: investigated before this check existed
        return False
    await hand_off(
        tenant,
        case_id,
        agent=AGENT,
        status=CaseStatus.TRIAGED,
        handed_to=AgentName.INVESTIGATOR,
        summary=f"case {case_id}: {len(now) - len(seen)} alerts joined since the investigation; "
        "sent back to the Investigator",
    )
    return True


async def run(tenant: str, case_id: int) -> None:
    log = get_logger(__name__, tenant=tenant, agent=AGENT, case_id=case_id)
    case = await graph.get_case(tenant, case_id)
    if case is None:
        log.warning("claimed case %s does not exist", case_id)
        return
    if await _sent_back(tenant, case_id, case):
        return
    rule = decision_table.decide(case["findings"])
    ranking = [tuple(r) for r in await graph.rank_hosts(tenant, case_id)]
    chosen = targets(rule, case, ranking)
    priority = case_priority(case)
    new_priority = lower_one(priority) if rule.priority == "lower_one" else priority
    text = await explanation(rule, case, ranking, chosen, new_priority)
    # The LLM can take seconds: check again just before the decision is written.
    # ponytail: an alert joining in the milliseconds between this read and record_decision is
    # still missed; closing that needs the check inside the graph write (Workstream B).
    if await _sent_back(tenant, case_id, await graph.get_case(tenant, case_id) or case):
        return
    await graph.record_decision(
        tenant,
        case_id,
        DecisionInput(
            rule_id=rule.id,
            actions=rule.actions,
            needs_approval=rule.needs_approval,
            reason=rule.reason,
            explanation=text,
            evidence={"findings": case["findings"], "ranking": ranking},
            previous_priority=priority,  # GAP-5: lets the UI show "high -> medium"
            **chosen,
        ),
    )
    status = CaseStatus.AWAITING_APPROVAL if rule.needs_approval else CaseStatus.CLOSED
    lowered = f", priority {priority} -> {new_priority}" if new_priority != priority else ""
    await hand_off(
        tenant,
        case_id,
        agent=AGENT,
        status=status,
        priority=new_priority,
        handed_to=None,
        summary=f"case {case_id}: rule {rule.id}, {', '.join(rule.actions)}; {status}{lowered}",
    )
    log.info("decided %s -> %s", rule.id, status)
