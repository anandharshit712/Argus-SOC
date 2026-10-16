"""Load each tenant's asset inventory into its graph (Workstream B).

    python scripts/seed_tenants.py               # every tenant in ARGUS_TENANTS
    python scripts/seed_tenants.py acme          # just one

Reads data/inventory/tenant_<tenant>_inventory.yaml, creates the indexes, then MERGEs the
hosts, users, links and IOCs. Safe to run again: nothing is duplicated and agent memory
already in the graph is kept. To start from scratch, use scripts/reset_demo.py.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from argus_soc.core.logging_setup import get_logger, setup_logging
from argus_soc.core.settings import get_settings
from argus_soc.core.tenant_registry import UnknownTenant, graph_name
from argus_soc.graph.falkor_client import close
from argus_soc.graph.inventory_seed import inventory_path, load_inventory, seed_tenant

INVENTORY_DIR = Path(__file__).resolve().parents[1] / "data" / "inventory"

log = get_logger("seed_tenants")


def parse_tenants(parser: argparse.ArgumentParser, argv: list[str] | None) -> list[str]:
    parser.add_argument("tenants", nargs="*", help="tenant ids (default: all in ARGUS_TENANTS)")
    tenants = parser.parse_args(argv).tenants or get_settings().tenant_ids
    for tenant in tenants:
        try:
            graph_name(tenant)
        except UnknownTenant as exc:
            parser.error(str(exc))
        if not inventory_path(INVENTORY_DIR, tenant).is_file():
            parser.error(f"no inventory file {inventory_path(INVENTORY_DIR, tenant)}")
    return tenants


async def seed(tenants: list[str]) -> None:
    try:
        for tenant in tenants:
            inventory = load_inventory(inventory_path(INVENTORY_DIR, tenant))
            if inventory.tenant != tenant:
                raise ValueError(f"{tenant} inventory file says tenant {inventory.tenant!r}")
            counts = await seed_tenant(tenant, inventory)
            log.info("seeded %s", counts, extra={"tenant": tenant})
    finally:
        await close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    tenants = parse_tenants(parser, argv)
    setup_logging("seed_tenants")
    asyncio.run(seed(tenants))


if __name__ == "__main__":
    sys.exit(main())
