"""The graph tools contract: names, parameters and defaults (docs/LLD.md §4.4, §4.5),
checked for the stubs and for every real FalkorDB function written so far."""

import inspect

import pytest

from argus_soc import graph
from argus_soc.core.settings import get_settings
from argus_soc.graph import algorithm_queries, graph_stubs, read_queries, write_queries

# name -> parameters in order, with defaults where there is one
SIGNATURES: dict[str, list[tuple[str, object]]] = {
    "blast_radius": [("tenant", None), ("ioc", None)],
    "paths_to_crown_jewels": [("tenant", None), ("host", None), ("max_hops", 6)],
    "rank_hosts": [("tenant", None), ("case_id", None)],
    "recall": [("tenant", None), ("ioc", None), ("host", None), ("user", None)],
    "linked_alerts": [("tenant", None), ("incident_id", None), ("window_hours", 24)],
    "explain_decision": [("tenant", None), ("decision_id", None)],
    "entity_facts": [("tenant", None), ("hosts", None), ("users", None), ("iocs", None)],
    "matching_playbook": [("tenant", None), ("alert", None)],
    "list_new_alerts": [("tenant", None), ("limit", 20)],
    "known_incident_ids": [("tenant", None), ("ids", None)],
    "list_cases": [("tenant", None), ("status", None), ("limit", 100)],
    "get_case": [("tenant", None), ("case_id", None)],
    "list_playbooks": [("tenant", None)],
    "list_activity": [("tenant", None), ("since", None)],
    "upsert_alert_from_report": [("tenant", None), ("alert", None)],
    "open_or_join_case": [("tenant", None), ("incident_ids", None), ("priority", None)],
    "close_case_auto": [
        ("tenant", None), ("incident_ids", None), ("playbook_ref", None), ("reason", None),
    ],
    "claim_case": [("tenant", None), ("status", None), ("agent", None), ("ttl_seconds", None)],
    "set_case_status": [("tenant", None), ("case_id", None), ("status", None), ("priority", None)],
    "record_findings": [("tenant", None), ("case_id", None), ("findings", None)],
    "record_decision": [("tenant", None), ("case_id", None), ("decision", None)],
    "record_feedback": [
        ("tenant", None), ("case_id", None), ("verdict", None), ("note", None), ("analyst", None),
    ],
    "create_playbook_version": [
        ("tenant", None), ("feedback_id", None), ("condition", None), ("action", None),
    ],
    "set_ioc_fact": [("tenant", None), ("ioc", None), ("key", None), ("value", None)],
    "record_semantic_facts": [("tenant", None), ("case_id", None), ("facts", None)],
    "record_agent_run": [
        ("tenant", None), ("agent", None), ("case_id", None), ("summary", None),
        ("handed_to", None), ("worker", None), ("tool_calls", None),
    ],
}  # fmt: skip


def _params(fn) -> list[tuple[str, object]]:
    return [
        (p.name, None if p.default is inspect.Parameter.empty else p.default)
        for p in inspect.signature(fn).parameters.values()
    ]


def test_contract_lists_every_function_once():
    assert sorted(graph.CONTRACT) == sorted(SIGNATURES)
    assert len(set(graph.CONTRACT)) == len(graph.CONTRACT)


@pytest.mark.parametrize("name", sorted(SIGNATURES))
def test_stub_matches_contract(name):
    fn = getattr(graph_stubs, name)
    assert inspect.iscoroutinefunction(fn), f"{name} must be async"
    assert _params(fn) == SIGNATURES[name]


REAL_MODULES = (read_queries, algorithm_queries, write_queries)
REAL = {name: getattr(m, name) for m in REAL_MODULES for name in SIGNATURES if hasattr(m, name)}


@pytest.mark.parametrize("name", sorted(REAL))
def test_real_function_matches_contract(name):
    fn = REAL[name]
    assert inspect.iscoroutinefunction(fn), f"{name} must be async"
    assert _params(fn) == SIGNATURES[name]


def test_each_real_function_lives_in_one_module():
    names = [n for m in REAL_MODULES for n in SIGNATURES if hasattr(m, n)]
    assert len(names) == len(set(names))


def test_scenario_1_functions_are_real():
    step7 = {
        "upsert_alert_from_report", "list_new_alerts", "known_incident_ids",
        "open_or_join_case", "claim_case", "set_case_status", "record_findings",
        "record_decision", "record_agent_run", "blast_radius", "paths_to_crown_jewels",
        "rank_hosts", "get_case", "list_cases",
        # what Triage needs too (Harshit, Oct 16)
        "matching_playbook", "recall", "entity_facts", "linked_alerts", "close_case_auto",
    }  # fmt: skip
    assert step7 <= set(REAL)


@pytest.fixture
def backend(monkeypatch):
    def use(value: str) -> None:
        monkeypatch.setenv("ARGUS_GRAPH_BACKEND", value)
        get_settings.cache_clear()

    return use


def test_stub_backend_serves_the_stubs(backend):
    backend("stub")
    assert graph.get_case is graph_stubs.get_case
    assert graph.implementation("claim_case") is graph_stubs.claim_case


def test_backend_is_read_at_each_lookup(backend):
    backend("stub")
    assert graph.list_cases is graph_stubs.list_cases
    backend("falkordb")
    assert graph.rank_hosts is algorithm_queries.rank_hosts
    assert graph.get_case is read_queries.get_case
    assert graph.claim_case is write_queries.claim_case


def test_real_backend_says_what_is_missing(backend):
    backend("falkordb")
    missing = []
    for name in graph.CONTRACT:
        try:
            graph.implementation(name)
        except NotImplementedError as exc:
            assert "ARGUS_GRAPH_BACKEND=stub" in str(exc)
            missing.append(name)
    assert missing  # shrinks as step 7 lands the real functions


def test_unknown_names_are_attribute_errors():
    with pytest.raises(AttributeError):
        graph.drop_everything  # noqa: B018
    with pytest.raises(AttributeError):
        graph.implementation("drop_everything")
