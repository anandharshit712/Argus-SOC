"""The graph tools contract: names, parameters and defaults (docs/LLD.md §4.4, §4.5).

Step 7 adds the same check for the real FalkorDB functions.
"""

import inspect

import pytest

from argus_soc import graph
from argus_soc.core.settings import get_settings
from argus_soc.graph import graph_stubs

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
    try:
        fn = graph.implementation("rank_hosts")
    except NotImplementedError:
        fn = None  # no FalkorDB version yet (step 7)
    assert fn is not graph_stubs.rank_hosts


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
