"""The dashboard summary for one tenant, computed from three existing graph reads
(`list_cases`, `list_playbooks`, `list_activity`), so there is no new Cypher (rule 1).

Two kinds of numbers:
- **now:** open cases, awaiting approval, critical/high open, active playbooks, "needs you".
  These describe the current state, so they have no "previous window" value.
- **in the window** (cases opened in the last 30 min / 1 h / 24 h / all): auto-closed and its
  share of closed cases (the learning proof, G5), median time to decision, the pipeline, the
  time buckets, the priority and category mix, the agents' steps. Each windowed KPI also gives
  the value for the window before it, so the UI can show a delta.

Median time to decision = the first Responder step on a case minus the case's `opened_at`.
"""

from collections import Counter
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any

from argus_backend import case_mapper
from argus_backend.api_models import (
    AgentStats,
    DashboardKpis,
    DashboardOut,
    Kpi,
    PlaybookMarker,
    TimeBucket,
    Window,
)
from argus_soc.graph.graph_schema import CaseStatus

WINDOW_SPAN: dict[str, timedelta | None] = {
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "all": None,
}
BUCKET_COUNT: dict[str, int] = {"30m": 6, "1h": 6, "24h": 12, "all": 12}
NEEDS_YOU_LIMIT = 5
RECENT_ACTIVITY_LIMIT = 8

OPEN = {
    CaseStatus.NEW,
    CaseStatus.TRIAGED,
    CaseStatus.INVESTIGATED,
    CaseStatus.AWAITING_APPROVAL,
}
PRIORITY_ORDER = ["critical", "high", "medium", "low", "info"]
RESPONDER = "responder"


def parse_time(value: Any) -> datetime | None:
    """A stored timestamp as an aware datetime (the graph writes UTC; a bare one is UTC)."""
    if isinstance(value, str) and value:
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def window_start(window: str, now: datetime, cases: list[dict[str, Any]]) -> datetime:
    """Start of the window. "all" starts at the oldest case (or an hour ago with no cases)."""
    span = WINDOW_SPAN[window]
    if span is not None:
        return now - span
    opened = [t for t in (parse_time(c.get("opened_at")) for c in cases) if t is not None]
    return min(opened) if opened else now - timedelta(hours=1)


def _opened_between(cases: list[dict[str, Any]], start: datetime, end: datetime) -> list[dict]:
    out = []
    for c in cases:
        opened = parse_time(c.get("opened_at"))
        if opened is not None and start <= opened <= end:
            out.append(c)
    return out


def _first_responder_step(runs: list[dict[str, Any]]) -> dict[int, datetime]:
    first: dict[int, datetime] = {}
    for r in runs:
        at = parse_time(r.get("at"))
        if r.get("agent") == RESPONDER and r.get("case_id") is not None and at is not None:
            if r["case_id"] not in first or at < first[r["case_id"]]:
                first[r["case_id"]] = at
    return first


def windowed_numbers(cases: list[dict[str, Any]], runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Auto-closed count, its % of closed cases, and median seconds to decision."""
    auto = sum(c["status"] == CaseStatus.AUTO_CLOSED for c in cases)
    closed = sum(c["status"] in (CaseStatus.CLOSED, CaseStatus.AUTO_CLOSED) for c in cases)
    decided = _first_responder_step(runs)
    seconds = []
    for c in cases:
        opened = parse_time(c.get("opened_at"))
        if c["id"] in decided and opened is not None:
            seconds.append(max(0.0, (decided[c["id"]] - opened).total_seconds()))
    return {
        "auto_closed": auto,
        "auto_closed_pct": round(100 * auto / closed, 1) if closed else None,
        "median_decision_seconds": round(median(seconds), 1) if seconds else None,
    }


def _priority_rank(priority: str) -> int:
    return PRIORITY_ORDER.index(priority) if priority in PRIORITY_ORDER else len(PRIORITY_ORDER)


def _buckets(
    cases: list[dict[str, Any]], start: datetime, now: datetime, count: int
) -> list[TimeBucket]:
    size = max((now - start) / count, timedelta(seconds=1))
    human, auto = [0] * count, [0] * count
    for c in cases:
        opened = parse_time(c.get("opened_at"))
        if opened is None:
            continue
        i = min(max(int((opened - start) / size), 0), count - 1)
        if c["status"] == CaseStatus.AUTO_CLOSED:
            auto[i] += 1
        else:
            human[i] += 1
    return [TimeBucket(start=start + size * i, human=human[i], auto=auto[i]) for i in range(count)]


def _agent_stats(runs: list[dict[str, Any]]) -> list[AgentStats]:
    steps: Counter[tuple[str, str | None]] = Counter()
    last: dict[tuple[str, str | None], datetime | None] = {}
    for r in runs:
        key = (r.get("agent") or "unknown", r.get("worker"))
        steps[key] += 1
        at = parse_time(r.get("at"))
        if at is not None and (last.get(key) is None or at > last[key]):
            last[key] = at
    return [
        AgentStats(
            agent=agent,
            worker=worker,
            steps=steps[(agent, worker)],
            last_seen=last.get((agent, worker)),
        )
        for agent, worker in sorted(steps, key=lambda k: (k[0], k[1] or ""))
    ]


def build_dashboard(
    tenant: str,
    window: Window,
    cases: list[dict[str, Any]],
    playbooks: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    now: datetime,
) -> DashboardOut:
    """`runs` must cover the window and the one before it (or everything for "all")."""
    start = window_start(window, now, cases)
    span = WINDOW_SPAN[window]
    in_window = _opened_between(cases, start, now)
    runs_in_window = [r for r in runs if (t := parse_time(r.get("at"))) is not None and t >= start]

    current = windowed_numbers(in_window, runs_in_window)
    previous: dict[str, Any] = {}
    if span is not None:
        previous = windowed_numbers(_opened_between(cases, start - span, start), runs)

    open_cases = [c for c in cases if c["status"] in OPEN]
    awaiting = [c for c in open_cases if c["status"] == CaseStatus.AWAITING_APPROVAL]
    sources = case_mapper.source_cases(playbooks)

    def windowed(key: str) -> Kpi:
        return Kpi(value=current[key], previous=previous.get(key))

    kpis = DashboardKpis(
        open_cases=Kpi(value=len(open_cases)),
        awaiting_approval=Kpi(value=len(awaiting)),
        critical_high_open=Kpi(
            value=sum(c["priority"] in ("critical", "high") for c in open_cases)
        ),
        auto_closed=windowed("auto_closed"),
        auto_closed_pct=windowed("auto_closed_pct"),
        median_decision_seconds=windowed("median_decision_seconds"),
        active_playbooks=Kpi(value=sum(bool(p.get("active")) for p in playbooks)),
    )

    markers = []
    for p in playbooks:
        created = parse_time(p.get("created_at"))
        if created is not None and start <= created <= now:
            markers.append(
                PlaybookMarker(
                    at=created, playbook=case_mapper.playbook_label(p["name"], p["version"])
                )
            )

    needs_you = sorted(
        awaiting, key=lambda c: (_priority_rank(c["priority"]), c.get("opened_at") or "")
    )[:NEEDS_YOU_LIMIT]
    recent = sorted(runs, key=lambda r: r.get("at") or "", reverse=True)[:RECENT_ACTIVITY_LIMIT]

    return DashboardOut(
        tenant=tenant,
        window=window,
        generated_at=now,
        kpis=kpis,
        pipeline={str(s): sum(c["status"] == s for c in in_window) for s in CaseStatus},
        buckets=_buckets(in_window, start, now, BUCKET_COUNT[window]),
        playbook_markers=sorted(markers, key=lambda m: m.at),
        needs_you=[case_mapper.to_summary(c, sources) for c in needs_you],
        by_priority={
            p: n for p in PRIORITY_ORDER if (n := sum(c["priority"] == p for c in in_window))
        },
        by_category=dict(Counter(c.get("category") or "unknown" for c in in_window).most_common()),
        agents=_agent_stats(runs_in_window),
        recent_activity=[case_mapper.to_activity(r) for r in recent],
    )
