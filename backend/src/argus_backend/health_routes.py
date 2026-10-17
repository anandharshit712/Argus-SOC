"""Health check, open to everyone (the Docker healthcheck and the UI banner use it).

    GET /api/health -> {status: ok | degraded | mock, falkordb: bool}

"mock" means ARGUS_GRAPH_BACKEND=stub: in-memory sample data, no database.
"""

from fastapi import APIRouter

from argus_backend.api_models import HealthOut
from argus_soc.core.settings import get_settings
from argus_soc.graph import falkor_client

router = APIRouter(prefix="/api")


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    if get_settings().argus_graph_backend == "stub":
        return HealthOut(status="mock", falkordb=False)
    up = await falkor_client.ping()
    return HealthOut(status="ok" if up else "degraded", falkordb=up)
