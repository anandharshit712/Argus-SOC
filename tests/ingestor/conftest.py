import json
from pathlib import Path

import pytest

from argus_soc.core.settings import Settings, get_settings
from argus_soc.graph import graph_stubs

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"


def talos_reports(scenario: str) -> list[dict]:
    """Reports saved from the Oct 16 Talos runs (`GET /reports`), e.g. scenario "s1"."""
    return json.loads((FIXTURES / f"talos_reports_{scenario}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def ingestor_settings(monkeypatch, tmp_path):
    """LLD defaults, the stub graph and the real inventories in data/inventory/."""
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    for tenant in ("ACME", "GLOBEX"):
        monkeypatch.delenv(f"TALOS_URL_{tenant}", raising=False)
    monkeypatch.chdir(tmp_path)  # never read a developer's real .env
    monkeypatch.setenv("ARGUS_GRAPH_BACKEND", "stub")
    monkeypatch.setenv("ARGUS_INVENTORY_DIR", str(REPO / "data" / "inventory"))
    get_settings.cache_clear()
    graph_stubs.reset_stubs()
    yield
    graph_stubs.reset_stubs()
    get_settings.cache_clear()
