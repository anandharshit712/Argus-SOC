"""Ingestor: poll Talos, store each new report as an Alert in its tenant's graph (LLD §5.5).

No "seen" list of our own: the graph is the record. Each poll asks the graph which incident
ids it already has, so a restarted ingestor never duplicates or misses a report that is still
in Talos's recent list. Run with `argus-ingest`.
"""

import asyncio
import logging
from typing import Any

from argus_soc import graph
from argus_soc.core.logging_setup import get_logger, setup_logging
from argus_soc.core.settings import get_settings
from argus_soc.ingestor.report_mapper import map_report
from argus_soc.ingestor.talos_client import TalosClient
from argus_soc.ingestor.tenant_resolver import TenantInventory, load_inventories, resolve, sources

log = get_logger(__name__)


async def poll_once(
    talos: TalosClient,
    fixed_tenant: str | None,
    inventories: dict[str, TenantInventory],
    skipped: set[str],
) -> int:
    """One poll of one Talos; returns how many new alerts were stored.

    `skipped` holds reports that can never be stored (no tenant, bad shape), so each is
    logged once, not on every poll. ponytail: in memory, so a restart logs them once more.
    """
    by_tenant: dict[str, list[dict[str, Any]]] = {}
    for report in await talos.list_reports(get_settings().ingest_page_limit):
        iid = report.get("incident_id")
        if iid in skipped:
            continue
        tenant = fixed_tenant or resolve(report, inventories)
        if not iid or tenant is None:
            hosts = (report.get("aggregate_scope") or {}).get("affected_hosts")
            log.warning("dropped report %s: no single tenant owns hosts %s", iid, hosts)
            skipped.add(iid)
            continue
        by_tenant.setdefault(tenant, []).append(report)

    stored = 0
    for tenant, reports in by_tenant.items():
        known = await graph.known_incident_ids(tenant, [r["incident_id"] for r in reports])
        for report in sorted(reports, key=lambda r: r.get("created_at") or ""):  # oldest first
            iid = report["incident_id"]
            if iid in known:
                continue
            try:
                alert = map_report(report, inventories[tenant].own_ips)
            except (KeyError, TypeError, ValueError):  # pydantic's ValidationError is a ValueError
                log.exception("dropped report %s: not a valid IncidentReport", iid)
                skipped.add(iid)
                continue
            try:
                await graph.upsert_alert_from_report(tenant, alert)
            except Exception:  # not stored, so the next poll tries it again
                log.exception("could not store report %s", iid, extra={"tenant": tenant})
                continue
            stored += 1
            log.info("stored alert %s (%s)", iid, alert.category, extra={"tenant": tenant})
    return stored


async def run() -> None:
    settings = get_settings()
    inventories = load_inventories()
    talos = [(TalosClient(url), tenant) for url, tenant in sources()]
    skipped: set[str] = set()
    log.info("polling %s", [client.base_url for client, _ in talos])
    try:
        while True:
            for client, tenant in talos:
                try:
                    await poll_once(client, tenant, inventories, skipped)
                except Exception:  # Talos or graph down: log, try again next poll
                    log.exception("poll of %s failed", client.base_url)
            await asyncio.sleep(settings.ingest_poll_seconds)
    finally:
        for client, _ in talos:
            await client.aclose()


def main() -> None:
    setup_logging("ingestor")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per poll otherwise
    asyncio.run(run())


if __name__ == "__main__":
    main()
