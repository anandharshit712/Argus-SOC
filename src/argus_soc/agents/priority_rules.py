"""Case priority steps (docs/LLD.md §6.2, §6.5). Order: info < low < medium < high < critical."""

from typing import Any

from argus_soc.graph.graph_schema import PRIORITY_ORDER, Priority


def raise_one(priority: str) -> Priority:
    """One step up, capped at critical."""
    i = PRIORITY_ORDER.index(Priority(priority))
    return PRIORITY_ORDER[min(i + 1, len(PRIORITY_ORDER) - 1)]


def lower_one(priority: str) -> Priority:
    """One step down, floored at info."""
    i = PRIORITY_ORDER.index(Priority(priority))
    return PRIORITY_ORDER[max(i - 1, 0)]


def highest(priorities: list[str]) -> Priority:
    """The highest of these; values that are not priorities are ignored (info if none)."""
    known = [Priority(p) for p in priorities if p in Priority._value2member_map_]
    return max(known, key=PRIORITY_ORDER.index, default=Priority.INFO)


def case_priority(case: dict[str, Any]) -> Priority:
    """The case's priority, raised to its most severe alert. An alert that joins a case after
    it was triaged (e.g. the successful login after the brute force) still counts."""
    return highest([case["priority"], *(a["severity"] for a in case["alerts"])])
