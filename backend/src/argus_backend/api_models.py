"""Response and request shapes of the backend API: the UI contract (docs/LLD.md §7).

LLD §7 plus the fields from docs/CONTRACT_GAPS.md:
- GAP-1 login: LoginIn, SessionOut, MeOut; FeedbackIn.analyst is ignored (the token decides).
- GAP-2/3 ActivityItem.worker, ActivityItem.tool_calls.
- GAP-4 typed feedback rows (FeedbackItemOut).
- GAP-5 DecisionOut.previous_priority.
- GAP-6 typed findings (FindingsOut, unknown keys kept).
Dashboard models are new (UI_PAGES dashboard page).

Every field the agents fill in step by step is optional, so a case half way through the
pipeline still validates.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Verdict = Literal["approve", "reject", "benign"]
Window = Literal["30m", "1h", "24h", "all"]

# --- health, tenants, auth -------------------------------------------------------


class HealthOut(BaseModel):
    status: Literal["ok", "degraded", "mock"]
    falkordb: bool


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class MeOut(BaseModel):
    username: str
    display_name: str
    tenants: list[str]


class SessionOut(MeOut):
    token: str
    expires_at: datetime


# --- cases -----------------------------------------------------------------------


class CaseSummary(BaseModel):
    id: int
    status: str
    priority: str
    category: str | None = None
    alert_count: int = 0
    opened_at: datetime | None = None
    updated_at: datetime | None = None
    needs_approval: bool = False
    auto_closed_by: str | None = None  # "<playbook name> v<version>"
    auto_closed_source_case: int | None = None  # the case that playbook was learned from


class PathNode(BaseModel):
    name: str
    label: str  # "Host" or "User"


class AlertOut(BaseModel):
    incident_id: str
    category: str | None = None
    severity: str | None = None
    confidence: float | None = None
    succeeded: bool | None = None
    summary: str | None = None
    # Talos evidence is attacker-controlled: plain, truncated strings, shown as text only.
    evidence: list[str] = []
    talos_actions: list[str] = []  # Talos's own recommended actions ("Talos suggested")


class ToolCallOut(BaseModel):
    """One MCP tool call of the Investigator's deep dive. Never carries the tenant."""

    model_config = ConfigDict(extra="ignore")

    tool: str
    args: dict[str, Any] = {}
    result: str | None = None
    why: str | None = None


class DecisionOut(BaseModel):
    id: str
    rule_id: str | None = None
    actions: list[str] = []
    needs_approval: bool = False
    reason: str | None = None
    explanation: str | None = None
    outcome: str | None = None  # pending / approved / rejected / auto
    path: list[PathNode] = []
    ranking: list[tuple[str, float]] = []
    previous_priority: str | None = None
    target_hosts: list[str] = []
    target_users: list[str] = []
    target_iocs: list[str] = []
    playbook: str | None = None  # "<name> v<version>" when a playbook decided
    agent: str | None = None
    created_at: datetime | None = None


class FindingsOut(BaseModel):
    """The keys Triage and the Investigator write (GAP-6). Unknown keys are kept."""

    model_config = ConfigDict(extra="allow")

    recall: list[dict[str, Any]] | None = None
    facts: dict[str, Any] | None = None
    linked: list[str] | None = None
    severity: str | None = None
    memory_reasons: list[str] | None = None
    succeeded: bool | None = None
    path_to_crown_jewel: bool | None = None
    shortest_path: list[str] | None = None
    blast_radius: list[dict[str, Any]] | None = None
    deep_dive: list[ToolCallOut] | None = None


class FeedbackItemOut(BaseModel):
    id: str
    verdict: Verdict
    note: str = ""
    analyst: str
    created_at: datetime | None = None


class ActivityItem(BaseModel):
    id: str | None = None
    at: datetime | None = None
    agent: str | None = None
    worker: str | None = None
    case_id: int | None = None
    summary: str | None = None
    handed_to: str | None = None
    tool_calls: list[ToolCallOut] | None = None


class CaseDetail(CaseSummary):
    closed_at: datetime | None = None
    verdict: str | None = None
    closed_reason: str | None = None
    alerts: list[AlertOut] = []
    findings: FindingsOut = FindingsOut()
    decision: DecisionOut | None = None
    feedback: list[FeedbackItemOut] = []
    agent_runs: list[ActivityItem] = []


class FeedbackIn(BaseModel):
    verdict: Verdict
    note: str = Field(default="", max_length=500)
    analyst: str | None = None  # ignored: the analyst is the signed-in user (GAP-1)


class FeedbackOut(BaseModel):
    feedback_id: str
    playbook_created: str | None = None


class PlaybookOut(BaseModel):
    name: str
    version: int
    active: bool
    condition: dict[str, Any] = {}
    action: str | None = None
    source_case: int | None = None
    created_at: datetime | None = None


# --- dashboard -------------------------------------------------------------------


class Kpi(BaseModel):
    # int for counts, float for % and seconds (int first, so a count stays 3, not 3.0)
    value: int | float | None
    previous: int | float | None = None  # same number for the window before; None if none


class DashboardKpis(BaseModel):
    open_cases: Kpi
    awaiting_approval: Kpi
    critical_high_open: Kpi
    auto_closed: Kpi
    auto_closed_pct: Kpi
    median_decision_seconds: Kpi
    active_playbooks: Kpi


class TimeBucket(BaseModel):
    start: datetime
    human: int  # cases that needed (or still need) an analyst
    auto: int  # auto-closed by a playbook


class PlaybookMarker(BaseModel):
    at: datetime
    playbook: str  # "<name> v<version>"


class AgentStats(BaseModel):
    agent: str
    worker: str | None
    steps: int
    last_seen: datetime | None


class DashboardOut(BaseModel):
    tenant: str
    window: Window
    generated_at: datetime
    kpis: DashboardKpis
    pipeline: dict[str, int]  # case count per status
    buckets: list[TimeBucket]
    playbook_markers: list[PlaybookMarker]
    needs_you: list[CaseSummary]
    by_priority: dict[str, int]
    by_category: dict[str, int]
    agents: list[AgentStats]
    recent_activity: list[ActivityItem]
