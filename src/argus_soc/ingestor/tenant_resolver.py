"""Which tenant a Talos report belongs to (docs/LLD.md §5.4).

One shared Talos (the default): a report goes to the tenant whose inventory lists one of its
`affected_hosts`. No match, or hosts from two tenants, means the report is dropped and logged,
never guessed. Host names are therefore unique across tenants.

One Talos per tenant (`TALOS_URL_<TENANT>` set): everything from that Talos is that tenant's.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from argus_soc.core.settings import get_settings
from argus_soc.graph.inventory_seed import expand, inventory_path, load_inventory


@dataclass(frozen=True)
class TenantInventory:
    hostnames: frozenset[str]
    # The tenant's own host IPs, dropped from source IPs. Inventory IOCs (such as the internal
    # scanner) stay, since they are real sources the analyst has seen before.
    own_ips: frozenset[str]


def load_inventories() -> dict[str, TenantInventory]:
    """Every tenant's hosts and own IPs, read once at start-up from the inventory files."""
    settings = get_settings()
    out = {}
    for tenant in settings.tenant_ids:
        inv = expand(load_inventory(inventory_path(Path(settings.argus_inventory_dir), tenant)))
        iocs = {i.value for i in inv.iocs}
        out[tenant] = TenantInventory(
            hostnames=frozenset(h.hostname for h in inv.hosts),
            own_ips=frozenset(str(h.ip) for h in inv.hosts) - iocs,
        )
    return out


def sources() -> list[tuple[str, str | None]]:
    """(Talos URL, tenant it belongs to); tenant None means "resolve each report by host"."""
    settings = get_settings()
    own = {t: settings.talos_url_for(t) for t in settings.tenant_ids}
    out: list[tuple[str, str | None]] = [
        (url, t) for t, url in own.items() if url != settings.talos_url
    ]
    if len(out) < len(own):  # some tenants still use the shared Talos
        out.append((settings.talos_url, None))
    return out


def resolve(report: dict[str, Any], inventories: dict[str, TenantInventory]) -> str | None:
    """The one tenant owning the report's hosts, or None (no match, or more than one)."""
    hosts = set((report.get("aggregate_scope") or {}).get("affected_hosts", []))
    owners = [t for t, inv in inventories.items() if hosts & inv.hostnames]
    return owners[0] if len(owners) == 1 else None
