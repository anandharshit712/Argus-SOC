"""Wipe the tenant graphs and seed them again, for a clean demo (Workstream B).

    python scripts/reset_demo.py --yes           # every tenant in ARGUS_TENANTS
    python scripts/reset_demo.py --yes acme      # just one

This deletes everything in those graphs: alerts, cases, decisions, feedback, playbooks and
agent memory, not just the inventory. It refuses to run without --yes.
"""

import argparse
import asyncio
import sys

from seed_tenants import parse_tenants, seed

from argus_soc.core.logging_setup import get_logger, setup_logging
from argus_soc.graph.falkor_client import close
from argus_soc.graph.inventory_seed import wipe_tenant

log = get_logger("reset_demo")


async def reset(tenants: list[str]) -> None:
    try:
        for tenant in tenants:
            existed = await wipe_tenant(tenant)
            log.info("graph %s", "deleted" if existed else "was empty", extra={"tenant": tenant})
    finally:
        await close()
    await seed(tenants)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--yes", action="store_true", help="really delete the tenant graphs")
    tenants = parse_tenants(parser, argv)
    if not parser.parse_args(argv).yes:
        parser.error("this deletes all data in the tenant graphs; add --yes to confirm")
    setup_logging("reset_demo")
    asyncio.run(reset(tenants))


if __name__ == "__main__":
    sys.exit(main())
