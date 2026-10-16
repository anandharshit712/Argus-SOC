from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from argus_backend.dashboard_service import build_dashboard

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def _ago(minutes: float) -> str:
    return (NOW - timedelta(minutes=minutes)).isoformat()


def _case(cid: int, status: str, priority: str, opened_min_ago: float, **extra: object) -> dict:
    return {
        "id": cid,
        "status": status,
        "priority": priority,
        "category": "auth_failure",
        "alert_count": 1,
        "opened_at": _ago(opened_min_ago),
        "updated_at": _ago(opened_min_ago),
        "needs_approval": status == "awaiting_approval",
        "auto_closed_by": None,
        **extra,
    }


def test_build_dashboard_numbers() -> None:
    cases = [
        _case(1, "awaiting_approval", "high", 10),
        _case(2, "auto_closed", "low", 20, auto_closed_by="benign-scanner v2"),
        _case(3, "closed", "medium", 40),
        _case(4, "new", "critical", 5),
        _case(5, "closed", "medium", 90),  # previous 1 h window
        _case(6, "auto_closed", "low", 100),  # previous 1 h window
    ]
    playbooks = [
        {
            "name": "benign-scanner",
            "version": 2,
            "active": True,
            "source_case": 3,
            "created_at": _ago(30),
        },
        {
            "name": "benign-scanner",
            "version": 1,
            "active": False,
            "source_case": 5,
            "created_at": _ago(80),
        },
    ]
    runs = [
        {"id": "r1", "at": _ago(9), "agent": "responder", "worker": "w1", "case_id": 1},
        {"id": "r2", "at": _ago(38), "agent": "responder", "worker": "w2", "case_id": 3},
        {"id": "r3", "at": _ago(19), "agent": "triage", "worker": "w1", "case_id": 2},
        {"id": "r4", "at": _ago(89), "agent": "responder", "worker": "w1", "case_id": 5},
    ]

    d = build_dashboard("acme", "1h", cases, playbooks, runs, NOW)

    assert d.kpis.open_cases.value == 2
    assert d.kpis.open_cases.previous is None
    assert d.kpis.awaiting_approval.value == 1
    assert d.kpis.critical_high_open.value == 2
    assert d.kpis.auto_closed.value == 1 and d.kpis.auto_closed.previous == 1
    assert d.kpis.auto_closed_pct.value == 50.0  # 1 of 2 closed in the window
    assert d.kpis.median_decision_seconds.value == 90.0  # 60 s and 120 s
    assert d.kpis.median_decision_seconds.previous == 60.0
    assert d.kpis.active_playbooks.value == 1
    assert d.pipeline["awaiting_approval"] == 1 and d.pipeline["auto_closed"] == 1
    assert sum(b.human + b.auto for b in d.buckets) == 4
    assert [m.playbook for m in d.playbook_markers] == ["benign-scanner v2"]
    assert [c.id for c in d.needs_you] == [1]
    assert d.by_priority == {"critical": 1, "high": 1, "medium": 1, "low": 1}
    assert {(a.agent, a.worker): a.steps for a in d.agents} == {
        ("responder", "w1"): 1,
        ("responder", "w2"): 1,
        ("triage", "w1"): 1,
    }
    assert [r.id for r in d.recent_activity] == ["r1", "r3", "r2", "r4"]


def test_all_window_has_no_previous() -> None:
    d = build_dashboard("acme", "all", [_case(1, "closed", "low", 600)], [], [], NOW)
    assert d.kpis.auto_closed.previous is None
    assert len(d.buckets) == 12


async def test_dashboard_route_on_stub_data(client: AsyncClient, acme: dict[str, str]) -> None:
    response = await client.get("/api/acme/dashboard?window=all", headers=acme)
    assert response.status_code == 200
    body = response.json()
    assert body["tenant"] == "acme"
    assert body["kpis"]["open_cases"]["value"] == 1
    assert body["kpis"]["awaiting_approval"]["value"] == 1
    assert body["kpis"]["active_playbooks"]["value"] == 1
    # Case 31 opened 10:03:00, the Responder's step on it ran at 10:05:30.
    assert body["kpis"]["median_decision_seconds"]["value"] == 150.0
    assert [c["id"] for c in body["needs_you"]] == [31]


async def test_dashboard_window_is_validated(client: AsyncClient, acme: dict[str, str]) -> None:
    assert (await client.get("/api/acme/dashboard?window=7d", headers=acme)).status_code == 422
    assert (await client.get("/api/acme/dashboard", headers=acme)).status_code == 200
