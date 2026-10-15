from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


@pytest.fixture
def scripts(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    import reset_demo
    import seed_tenants

    return seed_tenants, reset_demo


def test_seed_rejects_unknown_tenant(scripts, capsys):
    seed_tenants, _ = scripts
    with pytest.raises(SystemExit):
        seed_tenants.main(["initech"])
    assert "unknown tenant" in capsys.readouterr().err


def test_seed_needs_an_inventory_file(scripts, capsys):
    seed_tenants, _ = scripts
    with pytest.raises(SystemExit):
        seed_tenants.main(["test"])  # a known tenant with no inventory file
    assert "no inventory file" in capsys.readouterr().err


def test_reset_refuses_without_yes(scripts, capsys):
    _, reset_demo = scripts
    with pytest.raises(SystemExit):
        reset_demo.main(["acme"])
    assert "--yes" in capsys.readouterr().err


def test_every_configured_tenant_has_an_inventory(scripts):
    seed_tenants, _ = scripts
    for tenant in ("acme", "globex"):
        assert (seed_tenants.INVENTORY_DIR / f"tenant_{tenant}_inventory.yaml").is_file()
