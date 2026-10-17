from argus_backend import case_mapper


def test_evidence_is_plain_truncated_text() -> None:
    alert = {
        "incident_id": "inc-1",
        "evidence": ["a" * 600, {"line": "<script>"}],
        "recommended_actions": None,
    }
    out = case_mapper.to_alert(alert)
    assert len(out.evidence[0]) == case_mapper.EVIDENCE_MAX_CHARS + 1
    assert out.evidence[1] == '{"line": "<script>"}'
    assert out.talos_actions == []


def test_tool_calls_never_carry_the_tenant() -> None:
    run = {
        "id": "r",
        "tool_calls": [{"tool": "recall", "args": {"tenant": "acme", "ioc": "x"}, "result": [1]}],
    }
    calls = case_mapper.to_activity(run).tool_calls
    assert calls is not None and calls[0].args == {"ioc": "x"} and calls[0].result == "[1]"


def test_auto_closed_case_names_its_source_case() -> None:
    sources = case_mapper.source_cases(
        [{"name": "benign-scanner", "version": 2, "source_case": 32}]
    )
    case = {
        "id": 40,
        "status": "auto_closed",
        "priority": "low",
        "auto_closed_by": "benign-scanner v2",
    }
    assert case_mapper.to_summary(case, sources).auto_closed_source_case == 32


def test_bad_findings_key_is_dropped_not_fatal() -> None:
    case = {
        "id": 1,
        "status": "triaged",
        "priority": "low",
        "users": ["svc_deploy"],
        "findings": {"succeeded": "not-a-bool", "severity": "high", "custom": 1},
        "decision": {"id": "d", "evidence": {"ranking": [["h", "0.5"], ["bad"]]}},
    }
    detail = case_mapper.to_detail(case, {})
    assert detail.findings.succeeded is None
    assert detail.findings.severity == "high"
    assert detail.findings.model_extra == {"custom": 1}
    assert detail.decision is not None and detail.decision.ranking == [("h", 0.5)]


def test_path_labels_users_from_the_case() -> None:
    decision = case_mapper.to_decision(
        {"id": "d"}, {"shortest_path": ["bastion-01", "svc_deploy", "db-prod-01"]}, {"svc_deploy"}
    )
    assert [(n.name, n.label) for n in decision.path] == [
        ("bastion-01", "Host"),
        ("svc_deploy", "User"),
        ("db-prod-01", "Host"),
    ]
