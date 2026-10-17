"""The Responder's decision table (docs/LLD.md §6.4). Deterministic code, never the LLM (rule 8).

Rules are data, read top to bottom; the first whose `when` matches the findings wins. The
deep dive's results are evidence only and are never read here.
"""

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class Rule:
    id: str
    when: dict[str, bool]  # finding -> required value
    actions: tuple[str, ...]
    needs_approval: bool
    priority: str | None  # "lower_one" or None (keep)
    reason: str


RULES = (
    Rule(
        "R1",
        {"succeeded": True, "path": True},
        ("isolate_top_host", "disable_accounts", "block_ips"),
        needs_approval=True,
        priority=None,
        reason="the attack succeeded and a path reaches a crown jewel",
    ),
    Rule(
        "R2",
        {"succeeded": True, "path": False},
        ("disable_accounts", "block_ips", "open_hunt_ticket"),
        needs_approval=True,
        priority=None,
        reason="the attack succeeded but no path reaches a crown jewel",
    ),
    Rule(
        "R3",
        {"succeeded": False, "path": True},
        ("block_ips", "watch_path_hosts"),
        needs_approval=False,
        priority=None,
        reason="the attack did not succeed but a path reaches a crown jewel",
    ),
    Rule(
        "R4",
        {"succeeded": False, "path": False},
        ("block_or_rate_limit_ips", "open_ticket"),
        needs_approval=False,
        priority="lower_one",
        reason="the attack did not succeed and no path reaches a crown jewel",
    ),
)


def decide(findings: dict[str, Any]) -> Rule:
    """First matching rule. A missing finding counts as False (nothing proven). R3 needs
    approval when Triage found a known-malicious IOC (`known_malicious_iocs`)."""
    facts = {
        "succeeded": bool(findings.get("succeeded")),
        "path": bool(findings.get("path_to_crown_jewel")),
    }
    rule = next(r for r in RULES if all(facts[k] == v for k, v in r.when.items()))
    if rule.id == "R3" and findings.get("known_malicious_iocs"):
        # An attacker already marked malicious (an approved decision) on a crown-jewel path
        # goes to the analyst instead of closing on its own (live test Oct 17, case 20).
        return replace(
            rule,
            needs_approval=True,
            reason=f"{rule.reason}, and the attacker is already known malicious",
        )
    return rule
