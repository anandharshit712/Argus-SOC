import pytest

from argus_soc.core.settings import Settings, get_settings
from argus_soc.graph import graph_stubs


@pytest.fixture(autouse=True)
def stub_graph(monkeypatch, tmp_path):
    """Agents test against the stub graph library (CLAUDE.md), from the LLD defaults."""
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    monkeypatch.chdir(tmp_path)  # never read a developer's real .env
    monkeypatch.setenv("ARGUS_GRAPH_BACKEND", "stub")
    monkeypatch.setenv("AGENT_WORKER_ID", "worker-test")
    get_settings.cache_clear()
    graph_stubs.reset_stubs()
    yield
    graph_stubs.reset_stubs()
    get_settings.cache_clear()
