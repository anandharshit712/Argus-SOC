"""Load a tenant's asset inventory into its graph (docs/LLD.md §4.8).

The inventory lives in `data/inventory/tenant_<tenant>_inventory.yaml`: the demo hosts,
users, links and IOCs written out by hand, plus a `filler` section that generates extra
hosts and users from a fixed seed (so the graph has 50-200 hosts and is the same every run).

Seeding is idempotent: every write is one `UNWIND ... MERGE` query, so running it again
changes nothing. Agent memory on the seeded nodes (isolated, disabled, targeted case ids,
IOC verdicts...) is only set when a node is first created, so re-seeding never erases it.
"""

import random
from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from argus_soc.core.tenant_registry import graph_name
from argus_soc.graph.falkor_client import delete_graph, run
from argus_soc.graph.graph_schema import (
    CRITICALITY_MAX,
    CRITICALITY_MIN,
    IocType,
    IocVerdict,
    Label,
    Rel,
    Zone,
)
from argus_soc.graph.index_setup import setup_tenants

Name = Annotated[str, StringConstraints(max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class HostIn(_Strict):
    hostname: Name
    ip: IPv4Address
    os: str | None = None
    zone: Zone
    criticality: int = Field(ge=CRITICALITY_MIN, le=CRITICALITY_MAX)
    tags: tuple[str, ...] = ()


class UserIn(_Strict):
    username: Name
    role: str
    department: str | None = None
    privileged: bool = False
    logs_into: tuple[str, ...] = ()


class LinkIn(_Strict):
    src: str = Field(alias="from")
    dst: str = Field(alias="to")
    port: int = Field(ge=1, le=65535)


class IocIn(_Strict):
    type: IocType
    value: str = Field(min_length=1)
    owner: str | None = None


class FillerIn(_Strict):
    seed: int
    gateway: str
    subnets: dict[Zone, IPv4Network]
    hosts: dict[Zone, int]
    users: int = Field(ge=0, le=500)

    @model_validator(mode="after")
    def _subnet_for_every_zone(self) -> "FillerIn":
        missing = sorted(z.value for z, n in self.hosts.items() if n > 0 and z not in self.subnets)
        if missing:
            raise ValueError(f"filler hosts in zones without a subnet: {missing}")
        return self


class Inventory(_Strict):
    tenant: str
    hosts: tuple[HostIn, ...]
    users: tuple[UserIn, ...] = ()
    links: tuple[LinkIn, ...] = ()
    iocs: tuple[IocIn, ...] = ()
    filler: FillerIn | None = None

    @model_validator(mode="after")
    def _check_references(self) -> "Inventory":
        names = [h.hostname for h in self.hosts]
        _no_duplicates("hostname", names)
        _no_duplicates("ip", [str(h.ip) for h in self.hosts])
        _no_duplicates("username", [u.username for u in self.users])
        known = set(names)
        for user in self.users:
            _all_known(f"user {user.username} logs_into", user.logs_into, known)
        for link in self.links:
            _all_known("link", (link.src, link.dst), known)
            if link.src == link.dst:
                raise ValueError(f"link from {link.src} to itself")
        if self.filler and self.filler.gateway not in known:
            raise ValueError(f"filler gateway {self.filler.gateway!r} is not a listed host")
        return self


def _no_duplicates(what: str, values: list[str]) -> None:
    dupes = sorted({v for v in values if values.count(v) > 1})
    if dupes:
        raise ValueError(f"duplicate {what}: {dupes}")


def _all_known(where: str, names: tuple[str, ...], known: set[str]) -> None:
    missing = sorted(set(names) - known)
    if missing:
        raise ValueError(f"{where} refers to unknown hosts {missing}")


def inventory_path(directory: Path, tenant: str) -> Path:
    return directory / f"tenant_{tenant}_inventory.yaml"


def load_inventory(path: Path) -> Inventory:
    """Read and validate one inventory file. Raises ValueError with the reason."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Inventory.model_validate(data)


# ---------------------------------------------------------------------------
# Filler: generated hosts and users around the demo hosts
# ---------------------------------------------------------------------------

_FILLER_ROLE = {Zone.DMZ: "edge", Zone.APP: "svc", Zone.DATA: "store", Zone.CORP: "ws"}
_FILLER_CRITICALITY = {Zone.DMZ: (2, 3), Zone.APP: (2, 4), Zone.DATA: (3, 4), Zone.CORP: (1, 2)}
_FILLER_OS = ("ubuntu-22.04", "debian-12", "rhel-9", "windows-server-2022")
_FILLER_USER_ROLES = ("engineer", "analyst", "support", "finance", "sales")


def expand(inventory: Inventory) -> Inventory:
    """The inventory plus its generated filler. Same input, same output, every time.

    Filler hosts only link to other filler hosts, except that some filler workstations
    SSH into the gateway. Filler hosts are never crown jewels and filler users never log
    into a listed host, so the hand-written demo paths are not changed.
    """
    filler = inventory.filler
    if filler is None:
        return inventory
    rnd = random.Random(filler.seed)
    used_ips = {h.ip for h in inventory.hosts}
    by_zone: dict[Zone, list[str]] = {zone: [] for zone in Zone}
    hosts: list[HostIn] = []

    for zone in Zone:  # fixed order keeps the output stable
        free = (ip for ip in filler.subnets[zone].hosts() if int(ip) % 256 >= 100)
        for n in range(1, filler.hosts.get(zone, 0) + 1):
            ip = next((ip for ip in free if ip not in used_ips), None)
            if ip is None:
                raise ValueError(f"filler subnet for zone {zone.value} has no free address")
            used_ips.add(ip)
            name = f"{inventory.tenant}-{_FILLER_ROLE[zone]}-{n:03d}"
            low, high = _FILLER_CRITICALITY[zone]
            hosts.append(
                HostIn(
                    hostname=name,
                    ip=ip,
                    os=rnd.choice(_FILLER_OS),
                    zone=zone,
                    criticality=rnd.randint(low, high),
                )
            )
            by_zone[zone].append(name)

    links: list[LinkIn] = []

    def link(src: str, dst: str, port: int) -> None:
        links.append(LinkIn.model_validate({"from": src, "to": dst, "port": port}))

    apps, stores = by_zone[Zone.APP], by_zone[Zone.DATA]
    for ws in by_zone[Zone.CORP]:
        if rnd.random() < 0.35:
            link(ws, filler.gateway, 22)
        if apps:
            link(ws, rnd.choice(apps), 443)
    for edge in by_zone[Zone.DMZ]:
        for app in rnd.sample(apps, k=min(len(apps), rnd.randint(1, 2))):
            link(edge, app, 8080)
    for app in apps:
        if stores and rnd.random() < 0.7:
            link(app, rnd.choice(stores), 5432)
        if rnd.random() < 0.3:
            other = rnd.choice(apps)
            if other != app:
                link(app, other, 8080)

    users: list[UserIn] = []
    workplaces = by_zone[Zone.CORP] + apps
    for n in range(1, filler.users + 1):
        users.append(
            UserIn(
                username=f"{inventory.tenant}_user{n:03d}",
                role=rnd.choice(_FILLER_USER_ROLES),
                department=None,
                privileged=rnd.random() < 0.1,
                logs_into=tuple(sorted(rnd.sample(workplaces, k=rnd.randint(1, 3)))),
            )
        )

    return Inventory(
        tenant=inventory.tenant,
        hosts=inventory.hosts + tuple(hosts),
        users=inventory.users + tuple(users),
        links=inventory.links + tuple(dict.fromkeys(links)),  # drop exact duplicates
        iocs=inventory.iocs,
        filler=None,
    )


# ---------------------------------------------------------------------------
# Writes: one UNWIND ... MERGE query per kind of thing
# ---------------------------------------------------------------------------

_HOSTS = f"""
UNWIND $rows AS r
MERGE (h:{Label.HOST} {{hostname: r.hostname}})
ON CREATE SET h.isolated = false, h.targeted_case_ids = [], h.last_targeted_at = null
SET h.ip = r.ip, h.os = r.os, h.zone = r.zone, h.criticality = r.criticality
"""

_TAGS = f"""
UNWIND $rows AS r
MATCH (h:{Label.HOST} {{hostname: r.hostname}})
MERGE (t:{Label.ASSET_TAG} {{name: r.tag}})
MERGE (h)-[:{Rel.TAGGED}]->(t)
"""

_USERS = f"""
UNWIND $rows AS r
MERGE (u:{Label.USER} {{username: r.username}})
ON CREATE SET u.disabled = false, u.suspected_compromised = false,
              u.suspected_at = null, u.suspect_case_id = null
SET u.role = r.role, u.department = r.department, u.privileged = r.privileged
"""

_LOGINS = f"""
UNWIND $rows AS r
MATCH (u:{Label.USER} {{username: r.username}}), (h:{Label.HOST} {{hostname: r.hostname}})
MERGE (u)-[l:{Rel.LOGGED_INTO}]->(h)
ON CREATE SET l.last_seen = $seeded_at
"""

_LINKS = f"""
UNWIND $rows AS r
MATCH (a:{Label.HOST} {{hostname: r.src}}), (b:{Label.HOST} {{hostname: r.dst}})
MERGE (a)-[:{Rel.CONNECTS_TO} {{port: r.port}}]->(b)
"""

_IOCS = f"""
UNWIND $rows AS r
MERGE (i:{Label.IOC} {{type: r.type, value: r.value}})
ON CREATE SET i.verdict = '{IocVerdict.UNKNOWN}', i.owner = r.owner, i.seen_case_ids = [],
              i.first_seen = $seeded_at, i.last_seen = $seeded_at
"""


def _rows(inventory: Inventory) -> dict[str, list[dict[str, Any]]]:
    return {
        "hosts": [
            {
                "hostname": h.hostname,
                "ip": str(h.ip),
                "os": h.os,
                "zone": h.zone.value,
                "criticality": h.criticality,
            }
            for h in inventory.hosts
        ],
        "tags": [{"hostname": h.hostname, "tag": t} for h in inventory.hosts for t in h.tags],
        "users": [
            {
                "username": u.username,
                "role": u.role,
                "department": u.department,
                "privileged": u.privileged,
            }
            for u in inventory.users
        ],
        "logins": [
            {"username": u.username, "hostname": h} for u in inventory.users for h in u.logs_into
        ],
        "links": [{"src": lk.src, "dst": lk.dst, "port": lk.port} for lk in inventory.links],
        "iocs": [
            {"type": i.type.value, "value": i.value, "owner": i.owner} for i in inventory.iocs
        ],
    }


async def seed_tenant(tenant: str, inventory: Inventory) -> dict[str, int]:
    """Create indexes, then MERGE the expanded inventory into the tenant's graph.

    `tenant` decides which graph is written; tests load Acme's file into a test graph.
    Returns how many rows of each kind were sent.
    """
    graph_name(tenant)  # unknown tenant -> UnknownTenant before anything is written
    await setup_tenants([tenant])
    rows = _rows(expand(inventory))
    seeded_at = datetime.now(UTC).isoformat(timespec="seconds")
    for kind, query in (
        ("hosts", _HOSTS),
        ("tags", _TAGS),
        ("users", _USERS),
        ("logins", _LOGINS),
        ("links", _LINKS),
        ("iocs", _IOCS),
    ):
        if rows[kind]:
            await run(tenant, query, {"rows": rows[kind], "seeded_at": seeded_at})
    return {kind: len(values) for kind, values in rows.items()}


async def wipe_tenant(tenant: str) -> bool:
    """Delete the tenant's whole graph (indexes included). True if there was one."""
    return await delete_graph(tenant)
