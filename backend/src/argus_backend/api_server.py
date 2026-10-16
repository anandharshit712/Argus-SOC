"""The backend API app: routers, CORS, error mapping, and `main()` for `argus-backend`.

    argus-backend                          # uvicorn on API_PORT (default 8080)
    uvicorn argus_backend.api_server:create_app --factory --reload   # local development

Errors (docs/LLD.md §7): unknown tenant or case -> 404, verdict not allowed -> 409,
validation -> 422, FalkorDB unreachable -> 503. The UI shows a banner on 503 and keeps polling.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from argus_backend import (
    activity_routes,
    auth_routes,
    case_routes,
    dashboard_routes,
    health_routes,
    playbook_routes,
)
from argus_backend.api_settings import get_api_settings
from argus_soc.core.logging_setup import get_logger, setup_logging
from argus_soc.core.settings import get_settings
from argus_soc.core.tenant_registry import UnknownTenant
from argus_soc.graph import falkor_client

SERVICE = "api"
log = get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    get_api_settings()  # a bad ARGUS_DEMO_USERS / ARGUS_SESSION_SECRET stops startup here
    log.info("api started, graph backend %s", get_settings().argus_graph_backend)
    yield
    await falkor_client.close()


async def _unknown_tenant(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": "Unknown tenant"})


async def _graph_down(request: Request, exc: Exception) -> JSONResponse:
    log.warning("graph database unreachable: %s", type(exc).__name__)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "The graph database is unreachable; try again shortly"},
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title="Argus SOC API",
        version="0.1.0",
        lifespan=_lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.add_exception_handler(UnknownTenant, _unknown_tenant)
    for exc in (RedisConnectionError, RedisTimeoutError):
        app.add_exception_handler(exc, _graph_down)
    for module in (
        health_routes,
        auth_routes,
        case_routes,
        playbook_routes,
        activity_routes,
        dashboard_routes,
    ):
        app.include_router(module.router)
    return app


def main() -> None:
    setup_logging(SERVICE)
    uvicorn.run(create_app(), host="0.0.0.0", port=get_settings().api_port, log_config=None)


if __name__ == "__main__":
    main()
