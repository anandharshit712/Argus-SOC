"""Which tenants exist and the FalkorDB graph that holds each one (docs/LLD.md §3).

Every graph name comes from `graph_name()`, so a typo in a tenant id raises
`UnknownTenant` instead of silently creating a new, empty graph (rule A2).
"""

from argus_soc.core.settings import get_settings

GRAPH_PREFIX = "tenant_"


class UnknownTenant(ValueError):
    """Raised for a tenant id that is not in ARGUS_TENANTS."""


def tenants() -> dict[str, str]:
    """Tenant id -> graph name, e.g. {"acme": "tenant_acme", "globex": "tenant_globex"}."""
    return {tenant: f"{GRAPH_PREFIX}{tenant}" for tenant in get_settings().tenant_ids}


def graph_name(tenant: str) -> str:
    """Graph name for a known tenant. Raises UnknownTenant for anything else."""
    known = tenants()
    if not isinstance(tenant, str) or tenant not in known:
        raise UnknownTenant(f"unknown tenant {tenant!r}; known: {sorted(known)}")
    return known[tenant]


def __getattr__(name: str) -> dict[str, str]:
    # `TENANTS` (the name used in the LLD) is computed on access, so it always
    # matches the current settings.
    if name == "TENANTS":
        return tenants()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
