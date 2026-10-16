"""The one place that talks to FalkorDB (docs/LLD.md §4.2).

    rows = await run("acme", "MATCH (h:Host {hostname: $name}) RETURN h.zone AS zone",
                     {"name": "bastion-01"})
    # -> [{"zone": "dmz"}]

Rules this module enforces:
- The graph always comes from `tenant_registry.graph_name(tenant)`, so an unknown tenant
  fails before anything reaches the database (rule A2).
- Values travel only as query parameters; `params` must be a dict (security, rule 9).
- `run_read` uses GRAPH.RO_QUERY, so FalkorDB itself refuses a write sent through it.

One client per process (and per event loop, which matters only in tests).
"""

import asyncio
from typing import Any

from falkordb.asyncio import FalkorDB
from falkordb.asyncio.graph import AsyncGraph
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

from argus_soc.core.settings import get_settings
from argus_soc.core.tenant_registry import graph_name

_EMPTY_GRAPH_ERROR = "empty key"  # FalkorDB: "Invalid graph operation on empty key"

_client: FalkorDB | None = None
_client_loop: asyncio.AbstractEventLoop | None = None


def _db() -> FalkorDB:
    """The process-wide client, created on first use inside the running event loop."""
    global _client, _client_loop
    loop = asyncio.get_running_loop()
    if _client is None or _client_loop is not loop:
        settings = get_settings()
        _client = FalkorDB(host=settings.falkordb_host, port=settings.falkordb_port)
        _client_loop = loop
    return _client


def graph_for(tenant: str) -> AsyncGraph:
    """The graph that holds one tenant. Raises UnknownTenant for anything else."""
    name = graph_name(tenant)  # validate first: never touch the database for a bad tenant
    return _db().select_graph(name)


def _check_params(params: dict[str, Any] | None) -> dict[str, Any]:
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise TypeError("params must be a dict of query parameters")
    return params


def _as_dicts(result: Any) -> list[dict[str, Any]]:
    """Rows as dicts keyed by the RETURN aliases, e.g. [{"zone": "dmz"}]."""
    columns = [name for _type, name in result.header]
    return [dict(zip(columns, row, strict=True)) for row in result.result_set]


async def run(tenant: str, query: str, params: dict[str, Any] | None = None) -> list[dict]:
    """Run a query that may write. Returns the rows (empty for writes without RETURN)."""
    params = _check_params(params)  # before anything reaches the database
    result = await graph_for(tenant).query(query, params)
    return _as_dicts(result)


async def run_read(tenant: str, query: str, params: dict[str, Any] | None = None) -> list[dict]:
    """Run a read-only query. FalkorDB rejects it if it tries to write."""
    params = _check_params(params)  # before anything reaches the database
    try:
        result = await graph_for(tenant).ro_query(query, params)
    except ResponseError as exc:
        # A tenant graph that was never written to does not exist yet; FalkorDB then
        # refuses read-only queries. Nothing stored means nothing to return.
        if _EMPTY_GRAPH_ERROR in str(exc):
            return []
        raise
    return _as_dicts(result)


async def ping() -> bool:
    """True when the database answers (used by health checks and tests)."""
    try:
        return bool(await _db().connection.ping())
    except (RedisConnectionError, RedisTimeoutError, OSError):
        return False


async def graph_exists(tenant: str) -> bool:
    """True when the tenant's graph has been created (seeded or indexed)."""
    return graph_name(tenant) in await _db().list_graphs()


async def delete_graph(tenant: str) -> bool:
    """Delete the tenant's whole graph. True if there was one. Used by reset_demo only."""
    if not await graph_exists(tenant):
        return False
    await graph_for(tenant).delete()
    return True


async def close() -> None:
    """Close the connection pool (service shutdown, end of tests)."""
    global _client, _client_loop
    if _client is not None:
        await _client.aclose()
    _client, _client_loop = None, None
