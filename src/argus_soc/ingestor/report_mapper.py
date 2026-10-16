"""Talos IncidentReport -> AlertInput (docs/LLD.md §5.2, §5.3).

Everything in a report's evidence comes from log lines an attacker can write, so it is only
trimmed and stored, never interpreted (rule 9). The one thing taken from it is the source IP:
Talos has no structured field for it, so addresses are pulled from evidence and action text
and kept only if `ipaddress` accepts them.
"""

import ipaddress
import re
from collections import Counter
from collections.abc import Iterable
from typing import Any

from argus_soc.graph.graph_schema import (
    EVIDENCE_MAX_CHARS,
    EVIDENCE_MAX_ITEMS,
    SOURCE_IPS_MAX,
    AlertInput,
    TechniqueInput,
)

# Candidates only; ipaddress decides. The lookarounds stop "10.0.0.1.5" or "1.2.3.4.5" matching
# in part. Timestamps such as "10:02:11" match the IPv6 pattern and are rejected by ipaddress.
_IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\.?\d)")
_IPV6 = re.compile(r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![0-9A-Fa-f:])")


def extract_source_ips(texts: Iterable[str], own_ips: frozenset[str] = frozenset()) -> list[str]:
    """Valid IPs in the texts, most mentioned first, at most SOURCE_IPS_MAX.
    `own_ips` (the tenant's own hosts) are dropped."""
    counts: Counter[str] = Counter()
    for text in texts:
        for candidate in (*_IPV4.findall(text), *_IPV6.findall(text)):
            try:
                ip = str(ipaddress.ip_address(candidate))
            except ValueError:
                continue
            if ip not in own_ips:
                counts[ip] += 1
    return [ip for ip, _ in counts.most_common(SOURCE_IPS_MAX)]


def map_report(report: dict[str, Any], own_ips: frozenset[str] = frozenset()) -> AlertInput:
    """One Talos report as the graph's AlertInput. Raises pydantic.ValidationError if the
    report is missing a required field."""
    scope = report.get("aggregate_scope") or {}
    details = [
        str(e.get("detail", "")) for v in report.get("verdicts", []) for e in v.get("evidence", [])
    ]
    actions = [str(a) for a in report.get("recommended_actions", [])]
    return AlertInput(
        incident_id=report["incident_id"],
        domain=report["domain"],
        category=report["category"],
        severity=report["severity"],
        confidence=report["confidence"],
        summary=report.get("summary") or "",
        talos_created_at=report["created_at"],  # storage time; attack time is in the scope
        succeeded=scope.get("succeeded"),
        hosts=tuple(scope.get("affected_hosts", [])),
        users=tuple(scope.get("affected_accounts", [])),
        endpoints=tuple(scope.get("affected_endpoints", [])),
        techniques=tuple(
            TechniqueInput(
                mitre_id=t["technique_id"], name=t.get("technique_name"), tactic=t.get("tactic")
            )
            for t in report.get("mitre_techniques", [])
        ),
        evidence=tuple(d[:EVIDENCE_MAX_CHARS] for d in details[:EVIDENCE_MAX_ITEMS]),
        recommended_actions=tuple(actions),
        source_ips=tuple(extract_source_ips([*details, *actions], own_ips)),
    )
