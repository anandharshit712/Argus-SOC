"""Dashboard summary for one tenant (UI_PAGES dashboard page). Never a combined view across
tenants (rule 2, G7).

    GET /api/{tenant}/dashboard?window=30m|1h|24h|all -> DashboardOut (default 1h)
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query

from argus_backend import dashboard_service
from argus_backend.access_guard import tenant_access
from argus_backend.activity_routes import graph_timestamp
from argus_backend.api_models import DashboardOut, Window
from argus_soc import graph

router = APIRouter(prefix="/api/{tenant}")

ALL_CASES = 10_000


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(
    tenant: str = Depends(tenant_access),
    window: Window = Query(default="1h"),
) -> DashboardOut:
    now = datetime.now(UTC)
    span = dashboard_service.WINDOW_SPAN[window]
    # Activity for this window and the one before it, for the deltas.
    since = graph_timestamp(now - 2 * span) if span is not None else None
    cases = await graph.list_cases(tenant, None, ALL_CASES)
    playbooks = await graph.list_playbooks(tenant)
    runs = await graph.list_activity(tenant, since)
    return dashboard_service.build_dashboard(tenant, window, cases, playbooks, runs, now)
