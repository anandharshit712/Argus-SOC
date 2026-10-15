from argus_soc.graph import graph_schema as s
from argus_soc.graph.graph_schema import EDGES, NODE_KEYS, CaseStatus, Label, Rel


def test_labels_match_lld():
    assert {label.value for label in Label} == {
        "Host", "User", "Service", "Endpoint", "AssetTag",
        "Alert", "IOC", "Technique",
        "Case", "Decision", "Feedback", "Playbook", "AgentRun",
    }  # fmt: skip


def test_every_label_has_a_key():
    assert set(NODE_KEYS) == set(Label)
    assert NODE_KEYS[Label.ENDPOINT] == ("path", "app")
    assert NODE_KEYS[Label.IOC] == ("type", "value")
    assert NODE_KEYS[Label.PLAYBOOK] == ("name", "version")


def test_relationships_match_architecture():
    architecture = {
        "LOGGED_INTO", "CONNECTS_TO", "RUNS", "SERVED_BY", "TAGGED",
        "ON_HOST", "INVOLVES", "TARGETED", "MAPS_TO",
        "CONTAINS", "HAS_DECISION", "ACTED_ON", "ON", "LEARNED_FROM", "WROTE", "HANDED_OFF_TO",
    }  # fmt: skip
    assert {rel.value for rel in Rel} == architecture | {"APPLIED"}


def test_every_relationship_is_used_by_an_edge():
    assert {rel for _src, rel, _dst in EDGES} == set(Rel)
    assert (Label.USER, Rel.LOGGED_INTO, Label.HOST) in EDGES
    assert (Label.DECISION, Rel.ACTED_ON, Label.IOC) in EDGES


def test_case_statuses():
    assert [st.value for st in CaseStatus] == [
        "new", "triaged", "investigated", "awaiting_approval", "closed", "auto_closed",
    ]  # fmt: skip
    assert s.TRIAGED is CaseStatus.TRIAGED
    assert CaseStatus.CLOSED not in s.OPEN_CASE_STATUSES
    assert CaseStatus.AUTO_CLOSED not in s.OPEN_CASE_STATUSES
    assert CaseStatus.AWAITING_APPROVAL in s.OPEN_CASE_STATUSES


def test_priority_order():
    assert [p.value for p in s.PRIORITY_ORDER] == ["info", "low", "medium", "high", "critical"]


def test_allowed_values():
    assert {z.value for z in s.Zone} == {"dmz", "app", "data", "corp"}
    assert {v.value for v in s.IocVerdict} == {"unknown", "malicious", "benign"}
    assert {v.value for v in s.FeedbackVerdict} == {"approve", "reject", "benign"}
    assert {o.value for o in s.DecisionOutcome} == {"pending", "approved", "rejected", "auto"}
    assert {a.value for a in s.AlertStatus} == {"new", "cased"}
    assert (s.CRITICALITY_MIN, s.CRITICALITY_MAX) == (1, 5)
    assert s.CROWN_JEWEL_TAG == "crown-jewel"


def test_values_are_plain_strings():
    # Enums go straight into Cypher text (labels) and parameters (statuses).
    assert f"(:{Label.HOST})" == "(:Host)"
    assert CaseStatus.NEW == "new"
