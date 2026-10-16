"""Backend API tests run on B's in-memory stub graph (ARGUS_GRAPH_BACKEND=stub), reset before
every test, so they need no database. Demo users and the session secret are test-only values."""

import json
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from argus_backend.api_server import create_app
from argus_backend.api_settings import get_api_settings
from argus_soc.core.settings import get_settings
from argus_soc.graph.graph_stubs import reset_stubs

SECRET = "test-only-session-secret-0123456789abcdef"
PASSWORDS = {
    "acme.analyst": "acme-pass",
    "globex.analyst": "globex-pass",
    "demo.admin": "admin-pass",
}
USERS = [
    {"username": "acme.analyst", "display_name": "Acme Analyst", "tenants": ["acme"]},
    {"username": "globex.analyst", "display_name": "Globex Analyst", "tenants": ["globex"]},
    {"username": "demo.admin", "display_name": "Demo Admin", "tenants": ["acme", "globex"]},
]


def _clear_caches() -> None:
    get_settings.cache_clear()
    get_api_settings.cache_clear()


@pytest.fixture(autouse=True)
def api_env(monkeypatch: pytest.MonkeyPatch) -> None:
    users = [{**u, "password": PASSWORDS[u["username"]]} for u in USERS]
    monkeypatch.setenv("ARGUS_GRAPH_BACKEND", "stub")
    monkeypatch.setenv("ARGUS_TENANTS", "acme,globex")
    monkeypatch.setenv("ARGUS_DEMO_USERS", json.dumps(users))
    monkeypatch.setenv("ARGUS_SESSION_SECRET", SECRET)
    monkeypatch.setenv("ARGUS_SESSION_HOURS", "12")
    monkeypatch.setenv("LLM_ENABLED", "false")
    _clear_caches()
    reset_stubs()
    yield
    _clear_caches()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as c:
        yield c


async def sign_in(client: AsyncClient, username: str) -> dict[str, str]:
    """Authorization header for a demo user."""
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": PASSWORDS[username]}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


@pytest.fixture
async def acme(client: AsyncClient) -> dict[str, str]:
    return await sign_in(client, "acme.analyst")


@pytest.fixture
async def admin(client: AsyncClient) -> dict[str, str]:
    return await sign_in(client, "demo.admin")
