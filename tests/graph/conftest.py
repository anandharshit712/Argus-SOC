import os

import pytest

from argus_soc.core.settings import Settings, get_settings
from argus_soc.graph import falkor_client

# Where the developer's FalkorDB is: `docker compose up -d falkordb` publishes it on
# 127.0.0.1:6379. Read once, before the per-test clean-up below removes the variables.
# 127.0.0.1, not "localhost": on Windows "localhost" tries IPv6 (::1) first, and the
# port is only published on IPv4, so every new connection waits about 2 s.
DB_HOST = os.environ.get("FALKORDB_HOST", "127.0.0.1")
DB_PORT = os.environ.get("FALKORDB_PORT", "6379")

# Tests only ever write to these throwaway graphs, never to tenant_acme or tenant_globex.
TEST_TENANTS = ("test", "test_b")


@pytest.fixture(autouse=True)
async def clean_settings(monkeypatch, tmp_path):
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    monkeypatch.chdir(tmp_path)  # never read a developer's real .env
    monkeypatch.setenv("FALKORDB_HOST", DB_HOST)
    monkeypatch.setenv("FALKORDB_PORT", DB_PORT)
    monkeypatch.setenv("ARGUS_TENANTS", ",".join(("acme", "globex", *TEST_TENANTS)))
    get_settings.cache_clear()
    yield
    await falkor_client.close()
    get_settings.cache_clear()


@pytest.fixture
async def live_db():
    """A reachable FalkorDB with empty test graphs; skips the test if none is running."""
    if not await falkor_client.ping():
        pytest.skip(
            f"FalkorDB not reachable on {DB_HOST}:{DB_PORT} (docker compose up -d falkordb)"
        )
    await _drop_test_graphs()
    yield
    await _drop_test_graphs()


async def _drop_test_graphs() -> None:
    db = falkor_client._db()
    existing = set(await db.list_graphs())
    for tenant in TEST_TENANTS:
        name = f"tenant_{tenant}"
        if name in existing:
            await db.select_graph(name).delete()
