from ipaddress import IPv4Address
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from argus_soc.graph.falkor_client import graph_exists, run, run_read
from argus_soc.graph.graph_schema import CROWN_JEWEL_TAG, Label, Rel
from argus_soc.graph.inventory_seed import (
    Inventory,
    expand,
    inventory_path,
    load_inventory,
    seed_tenant,
    wipe_tenant,
)

INVENTORY_DIR = Path(__file__).resolve().parents[2] / "data" / "inventory"
DEMO_HOSTS = {"bastion-01", "app-02", "db-prod-01", "web-01"}
HOST, USER, IOC = Label.HOST, Label.USER, Label.IOC


@pytest.fixture(scope="module")
def acme() -> Inventory:
    return load_inventory(inventory_path(INVENTORY_DIR, "acme"))


@pytest.fixture(scope="module")
def globex() -> Inventory:
    return load_inventory(inventory_path(INVENTORY_DIR, "globex"))


# --- The inventory files -----------------------------------------------------


def test_files_name_their_own_tenant(acme, globex):
    assert (acme.tenant, globex.tenant) == ("acme", "globex")


def test_acme_demo_facts(acme):
    hosts = {h.hostname: h for h in acme.hosts}
    assert set(hosts) == DEMO_HOSTS
    assert hosts["db-prod-01"].tags == (CROWN_JEWEL_TAG,)
    assert (hosts["bastion-01"].zone, hosts["bastion-01"].criticality) == ("dmz", 3)
    assert hosts["app-02"].ip == IPv4Address("10.0.2.20")
    (svc,) = acme.users
    assert (svc.username, svc.logs_into, svc.privileged) == (
        "svc_deploy",
        ("bastion-01", "app-02"),
        True,
    )
    assert {(lk.src, lk.dst, lk.port) for lk in acme.links} == {
        ("bastion-01", "app-02", 22),
        ("app-02", "db-prod-01", 5432),
    }
    assert [(i.type, i.value) for i in acme.iocs] == [("ip", "10.0.5.20")]


def test_globex_has_vpn_gw(globex):
    assert "vpn-gw" in {h.hostname for h in globex.hosts}


@pytest.mark.parametrize("name", ["acme", "globex"])
def test_filler_is_the_same_every_time(name):
    inventory = load_inventory(inventory_path(INVENTORY_DIR, name))
    assert expand(inventory) == expand(inventory)


@pytest.mark.parametrize("name", ["acme", "globex"])
def test_size_is_in_the_lld_range(name):
    full = expand(load_inventory(inventory_path(INVENTORY_DIR, name)))
    assert 50 <= len(full.hosts) <= 200
    assert len({h.ip for h in full.hosts}) == len(full.hosts)


def test_filler_leaves_the_demo_paths_alone(acme):
    full = expand(acme)
    filler_links = full.links[len(acme.links) :]
    for link in filler_links:
        touched = {link.src, link.dst} & DEMO_HOSTS
        assert touched <= {"bastion-01"}, link  # only the gateway
        if touched:
            assert link.port == 22
    filler_hosts = full.hosts[len(acme.hosts) :]
    assert all(not h.tags for h in filler_hosts)  # no extra crown jewels
    assert all(h.hostname.startswith("acme-") for h in filler_hosts)
    for user in full.users[len(acme.users) :]:
        assert not set(user.logs_into) & DEMO_HOSTS


def test_tenants_share_nothing(acme, globex):
    a, g = expand(acme), expand(globex)
    assert not {h.hostname for h in a.hosts} & {h.hostname for h in g.hosts}
    assert not {u.username for u in a.users} & {u.username for u in g.users}
    assert not {h.ip for h in a.hosts} & {h.ip for h in g.hosts}


# --- Bad files are rejected -------------------------------------------------


def _base() -> dict:
    return {
        "tenant": "acme",
        "hosts": [
            {"hostname": "h1", "ip": "10.0.0.1", "zone": "dmz", "criticality": 3},
            {"hostname": "h2", "ip": "10.0.0.2", "zone": "app", "criticality": 4},
        ],
        "users": [{"username": "u1", "role": "admin", "logs_into": ["h1"]}],
        "links": [{"from": "h1", "to": "h2", "port": 22}],
    }


def test_base_is_valid():
    Inventory.model_validate(_base())


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["links"].append({"from": "h1", "to": "nowhere", "port": 22}),
        lambda d: d["links"].append({"from": "h1", "to": "h1", "port": 22}),
        lambda d: d["users"][0]["logs_into"].append("nowhere"),
        lambda d: d["hosts"].append(dict(d["hosts"][0])),
        lambda d: d["hosts"][0].update(zone="lobby"),
        lambda d: d["hosts"][0].update(criticality=7),
        lambda d: d["hosts"][0].update(ip="10.0.0.999"),
        lambda d: d["hosts"][1].update(ip="10.0.0.1"),
        lambda d: d["hosts"][0].update(hostname="bad name; DROP"),
        lambda d: d["hosts"][0].update(colour="red"),
        lambda d: d.update(
            filler={"seed": 1, "gateway": "nowhere", "subnets": {}, "hosts": {}, "users": 0}
        ),
    ],
    ids=[
        "link-to-unknown-host", "link-to-itself", "login-to-unknown-host", "duplicate-host",
        "bad-zone", "criticality-7", "bad-ip", "duplicate-ip", "bad-hostname", "unknown-field",
        "unknown-gateway",
    ],
)  # fmt: skip
def test_bad_inventory_is_rejected(change):
    data = _base()
    change(data)
    with pytest.raises(ValidationError):
        Inventory.model_validate(data)


def test_load_inventory_reads_yaml(tmp_path):
    path = tmp_path / "tenant_acme_inventory.yaml"
    path.write_text(yaml.safe_dump(_base()))
    assert load_inventory(path).hosts[1].hostname == "h2"


# --- Seeding a live graph ----------------------------------------------------


async def _count(tenant: str, pattern: str) -> int:
    rows = await run_read(tenant, f"MATCH {pattern} RETURN count(*) AS n")
    return rows[0]["n"] if rows else 0


async def _totals(tenant: str) -> tuple[int, int]:
    return (await _count(tenant, "(n)"), await _count(tenant, "()-[r]->()"))


@pytest.mark.falkordb
async def test_seed_writes_the_inventory(live_db, acme):
    full = expand(acme)
    await seed_tenant("test", acme)
    assert await _count("test", f"(:{Label.HOST})") == len(full.hosts)
    assert await _count("test", f"(:{Label.USER})") == len(full.users)
    assert await _count("test", f"()-[:{Rel.CONNECTS_TO}]->()") == len(full.links)
    assert await _count("test", f"(:{Label.IOC})") == 1
    rows = await run_read(
        "test",
        f"MATCH (h:{Label.HOST})-[:{Rel.TAGGED}]->(:{Label.ASSET_TAG} {{name: $tag}}) "
        "RETURN h.hostname AS h",
        {"tag": CROWN_JEWEL_TAG},
    )
    assert rows == [{"h": "db-prod-01"}]


@pytest.mark.falkordb
async def test_demo_path_exists(live_db, acme):
    await seed_tenant("test", acme)
    # FalkorDB's shortestPath must sit in WITH/RETURN and follow edge direction.
    rows = await run_read(
        "test",
        f"MATCH (a:{HOST} {{hostname: 'bastion-01'}}), (b:{HOST} {{hostname: 'db-prod-01'}}) "
        f"WITH shortestPath((a)-[:{Rel.CONNECTS_TO}*1..6]->(b)) AS p "
        "RETURN [n IN nodes(p) | n.hostname] AS path",
    )
    assert rows == [{"path": ["bastion-01", "app-02", "db-prod-01"]}]
    rows = await run_read(
        "test",
        f"MATCH (:{Label.USER} {{username: 'svc_deploy'}})-[:{Rel.LOGGED_INTO}]->(h) "
        "RETURN h.hostname AS h ORDER BY h",
    )
    assert rows == [{"h": "app-02"}, {"h": "bastion-01"}]


@pytest.mark.falkordb
async def test_web01_cannot_reach_a_crown_jewel(live_db, acme):
    await seed_tenant("test", acme)
    paths = await _count(
        "test",
        f"(:{Label.HOST} {{hostname: 'web-01'}})-[:{Rel.CONNECTS_TO}|{Rel.LOGGED_INTO}*1..6]-"
        f"(:{Label.HOST})-[:{Rel.TAGGED}]->(:{Label.ASSET_TAG} {{name: '{CROWN_JEWEL_TAG}'}})",
    )
    assert paths == 0


@pytest.mark.falkordb
async def test_seeding_twice_changes_nothing(live_db, acme):
    await seed_tenant("test", acme)
    before = await _totals("test")
    await seed_tenant("test", acme)
    assert await _totals("test") == before


@pytest.mark.falkordb
async def test_reseed_keeps_agent_memory(live_db, acme):
    await seed_tenant("test", acme)
    both = f"MATCH (h:{HOST} {{hostname: 'bastion-01'}}), (i:{IOC} {{value: '10.0.5.20'}}) "
    await run(
        "test",
        both + "SET h.isolated = true, h.targeted_case_ids = [7], "
        "i.verdict = 'benign', i.owner = 'pentest'",
    )
    await seed_tenant("test", acme)
    rows = await run_read(
        "test",
        both + "RETURN h.isolated AS iso, h.targeted_case_ids AS cases, "
        "i.verdict AS v, i.owner AS o",
    )
    assert rows == [{"iso": True, "cases": [7], "v": "benign", "o": "pentest"}]


@pytest.mark.falkordb
async def test_new_nodes_start_with_empty_memory(live_db, acme):
    await seed_tenant("test", acme)
    rows = await run_read(
        "test",
        f"MATCH (h:{HOST} {{hostname: 'app-02'}}), (u:{USER} {{username: 'svc_deploy'}}) "
        "RETURN h.isolated AS iso, h.targeted_case_ids AS cases, u.disabled AS dis, "
        "u.suspected_compromised AS sus",
    )
    assert rows == [{"iso": False, "cases": [], "dis": False, "sus": False}]


@pytest.mark.falkordb
async def test_seed_touches_only_its_tenant(live_db, acme):
    await seed_tenant("test", acme)
    assert not await graph_exists("test_b")


@pytest.mark.falkordb
async def test_wipe_deletes_the_graph(live_db, acme):
    await seed_tenant("test", acme)
    assert await wipe_tenant("test") is True
    assert not await graph_exists("test")
    assert await wipe_tenant("test") is False
