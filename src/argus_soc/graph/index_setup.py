"""Create the lookup indexes on every tenant graph (docs/LLD.md §4.3).

    python -m argus_soc.graph.index_setup              # every tenant in ARGUS_TENANTS
    python -m argus_soc.graph.index_setup acme globex  # just these

Safe to run any number of times: indexes that already exist are skipped, and a
race with another process creating the same index is treated as success. Running
it also creates an empty graph for a tenant that has none yet, so read-only
queries work from the start (see falkor_client.run_read).
"""

import argparse
import asyncio
import time

from redis.exceptions import ResponseError

from argus_soc.core.logging_setup import get_logger, setup_logging
from argus_soc.core.settings import get_settings
from argus_soc.core.tenant_registry import UnknownTenant, graph_name
from argus_soc.graph.falkor_client import close, run, run_read
from argus_soc.graph.graph_schema import Label

# (label, property) pairs from LLD §4.3. Labels and properties come from these
# constants only, so building the CREATE INDEX text from them is safe.
INDEXES: tuple[tuple[Label, str], ...] = (
    (Label.ALERT, "incident_id"),
    (Label.HOST, "hostname"),
    (Label.USER, "username"),
    (Label.IOC, "value"),
    (Label.CASE, "id"),
    (Label.CASE, "status"),
    (Label.PLAYBOOK, "active"),
)

_ALREADY_INDEXED = "already indexed"  # FalkorDB: "Attribute 'x' is already indexed"
OPERATIONAL = "OPERATIONAL"

log = get_logger(__name__)


async def existing_indexes(tenant: str) -> dict[tuple[str, str], str]:
    """Range indexes on the tenant graph: (label, property) -> status."""
    rows = await run_read(
        tenant,
        "CALL db.indexes() YIELD label, properties, types, status "
        "RETURN label, properties, types, status",
    )
    found: dict[tuple[str, str], str] = {}
    for row in rows:
        for prop in row["properties"]:
            if "RANGE" in row["types"].get(prop, []):
                found[(row["label"], prop)] = row["status"]
    return found


async def ensure_indexes(tenant: str) -> list[tuple[str, str]]:
    """Create the missing indexes on one tenant graph. Returns the ones it created."""
    have = await existing_indexes(tenant)
    created: list[tuple[str, str]] = []
    for label, prop in INDEXES:
        if (label.value, prop) in have:
            continue
        try:
            await run(tenant, f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
        except ResponseError as exc:
            if _ALREADY_INDEXED not in str(exc):
                raise
            continue  # another process created it a moment ago
        created.append((label.value, prop))
    return created


async def wait_until_operational(tenant: str, timeout_seconds: float = 30.0) -> None:
    """FalkorDB builds indexes in the background; wait until all of ours are usable."""
    wanted = {(label.value, prop) for label, prop in INDEXES}
    deadline = time.monotonic() + timeout_seconds
    while True:
        have = await existing_indexes(tenant)
        pending = sorted(k for k in wanted if have.get(k) != OPERATIONAL)
        if not pending:
            return
        if time.monotonic() > deadline:
            raise TimeoutError(f"indexes on {tenant!r} not ready: {pending}")
        await asyncio.sleep(0.2)


async def setup_tenants(tenants: list[str]) -> dict[str, list[tuple[str, str]]]:
    """Ensure every index on each tenant graph and wait until they are operational."""
    result: dict[str, list[tuple[str, str]]] = {}
    for tenant in tenants:
        created = await ensure_indexes(tenant)
        await wait_until_operational(tenant)
        log.info(
            "indexes ready: %d created, %d already there",
            len(created),
            len(INDEXES) - len(created),
            extra={"tenant": tenant},
        )
        result[tenant] = created
    return result


async def _main(tenants: list[str]) -> None:
    try:
        await setup_tenants(tenants)
    finally:
        await close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Create the graph indexes for each tenant.")
    parser.add_argument("tenants", nargs="*", help="tenant ids (default: all in ARGUS_TENANTS)")
    args = parser.parse_args(argv)
    tenants = args.tenants or get_settings().tenant_ids
    for tenant in tenants:
        try:
            graph_name(tenant)
        except UnknownTenant as exc:
            parser.error(str(exc))
    setup_logging("index_setup")
    asyncio.run(_main(tenants))


if __name__ == "__main__":
    main()
