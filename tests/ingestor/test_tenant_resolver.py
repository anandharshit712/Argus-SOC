from tests.ingestor.conftest import talos_reports

from argus_soc.core.settings import get_settings
from argus_soc.ingestor.tenant_resolver import load_inventories, resolve, sources


def _report(*hosts: str) -> dict:
    return {"aggregate_scope": {"affected_hosts": list(hosts)}}


def test_reports_go_to_the_tenant_owning_their_host():
    inventories = load_inventories()
    assert {resolve(r, inventories) for r in talos_reports("s1")} == {"acme"}
    assert resolve(talos_reports("s4")[0], inventories) == "globex"


def test_unknown_or_ambiguous_hosts_are_never_guessed():
    inventories = load_inventories()
    assert resolve(_report("no-such-host"), inventories) is None
    assert resolve(_report(), inventories) is None
    assert resolve(_report("bastion-01", "vpn-gw"), inventories) is None


def test_own_ips_exclude_inventory_iocs():
    acme = load_inventories()["acme"]
    assert "10.0.1.10" in acme.own_ips  # bastion-01
    assert "10.0.5.20" not in acme.own_ips  # the internal scanner, an inventory IOC


def test_sources_shared_talos_by_default():
    assert sources() == [("http://talos:8000", None)]


def test_sources_with_one_talos_per_tenant(monkeypatch):
    monkeypatch.setenv("TALOS_URL_ACME", "http://talos-acme:8000")
    get_settings.cache_clear()
    assert sources() == [("http://talos-acme:8000", "acme"), ("http://talos:8000", None)]
    monkeypatch.setenv("TALOS_URL_GLOBEX", "http://talos-globex:8000")
    assert sources() == [
        ("http://talos-acme:8000", "acme"),
        ("http://talos-globex:8000", "globex"),
    ]
