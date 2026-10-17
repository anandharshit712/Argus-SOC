"""Live feed of agent steps, handoffs and workers (docs/LLD.md §7, GAP-2/3).

    GET /api/{tenant}/activity?since=<ISO timestamp> -> list[ActivityItem], oldest first

The UI polls with `since` = the newest `at` it has, so each call returns only what is new.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query

from argus_backend import case_mapper
from argus_backend.access_guard import tenant_access
from argus_backend.api_models import ActivityItem
from argus_soc import graph

router = APIRouter(prefix="/api/{tenant}")

MAX_ITEMS = 500


def graph_timestamp(moment: datetime) -> str:
    """The graph stores times as UTC ISO strings and compares them as text, so `since` must be
    written the same way (a "Z" suffix or another time zone would compare wrongly)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


@router.get("/activity", response_model=list[ActivityItem])
async def list_activity(
    tenant: str = Depends(tenant_access),
    since: datetime | None = Query(default=None),
) -> list[ActivityItem]:
    runs = await graph.list_activity(tenant, graph_timestamp(since) if since else None)
    return [case_mapper.to_activity(r) for r in runs[-MAX_ITEMS:]]
