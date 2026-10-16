"""Graph tools library: the only way the rest of Argus SOC reaches the graph (rule 1).

    from argus_soc import graph

    case = await graph.get_case("acme", 31)
    await graph.set_case_status("acme", 31, graph_schema.TRIAGED)

Which implementation answers depends on ARGUS_GRAPH_BACKEND, read at each lookup:
- "falkordb" (default): the real queries in read_queries / algorithm_queries / write_queries.
- "stub": graph_stubs, fixed sample data in memory, no database (for A and C to build on).

Both implementations have exactly the functions in CONTRACT, with the same signatures.
"""

from importlib import import_module
from typing import Any

from argus_soc.core.settings import get_settings

READ_FUNCTIONS = (
    "blast_radius",  # Q1
    "paths_to_crown_jewels",  # Q2
    "rank_hosts",  # Q3
    "recall",  # Q4
    "linked_alerts",  # Q5
    "explain_decision",  # Q6
    "entity_facts",
    "matching_playbook",
    "list_new_alerts",
    "known_incident_ids",
    "list_cases",
    "get_case",
    "list_playbooks",
    "list_activity",
)
WRITE_FUNCTIONS = (
    "upsert_alert_from_report",
    "open_or_join_case",
    "close_case_auto",
    "claim_case",
    "set_case_status",
    "record_findings",
    "record_decision",
    "record_feedback",
    "create_playbook_version",
    "set_ioc_fact",
    "record_semantic_facts",
    "record_agent_run",
)
CONTRACT = READ_FUNCTIONS + WRITE_FUNCTIONS

_STUB_MODULE = "argus_soc.graph.graph_stubs"
_REAL_MODULES = (
    "argus_soc.graph.read_queries",
    "argus_soc.graph.algorithm_queries",
    "argus_soc.graph.write_queries",
)


def implementation(name: str) -> Any:
    """The function `name` from the backend chosen by ARGUS_GRAPH_BACKEND."""
    if name not in CONTRACT:
        raise AttributeError(f"{name!r} is not a graph tools function")
    if get_settings().argus_graph_backend == "stub":
        return getattr(import_module(_STUB_MODULE), name)
    for module_name in _REAL_MODULES:
        try:
            module = import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name != module_name:
                raise  # a real import error inside the module, not a missing module
            continue
        if hasattr(module, name):
            return getattr(module, name)
    raise NotImplementedError(
        f"graph.{name} has no FalkorDB version yet; set ARGUS_GRAPH_BACKEND=stub to use the stub"
    )


def __getattr__(name: str) -> Any:
    if name in CONTRACT:
        return implementation(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
