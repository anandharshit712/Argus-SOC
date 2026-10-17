import pytest

from argus_soc.core import tenant_registry
from argus_soc.core.settings import get_settings
from argus_soc.core.tenant_registry import UnknownTenant, graph_name


def test_known_tenants_map_to_their_graphs():
    assert tenant_registry.TENANTS == {"acme": "tenant_acme", "globex": "tenant_globex"}
    assert graph_name("acme") == "tenant_acme"
    assert graph_name("globex") == "tenant_globex"


@pytest.mark.parametrize("tenant", ["", "Acme", "acme ", "initech", "tenant_acme", None, 1])
def test_anything_else_is_rejected(tenant):
    with pytest.raises(UnknownTenant):
        graph_name(tenant)


def test_unknown_tenant_is_a_value_error():
    assert issubclass(UnknownTenant, ValueError)


def test_registry_follows_settings(monkeypatch):
    monkeypatch.setenv("ARGUS_TENANTS", "acme,globex,test")
    get_settings.cache_clear()
    assert graph_name("test") == "tenant_test"
