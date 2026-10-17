import json
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from argus_backend.api_settings import ApiSettings
from argus_backend.session_tokens import InvalidToken, create_token, verify_token
from conftest import SECRET, sign_in


async def test_health_is_open_and_reports_mock(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "mock", "falkordb": False}


async def test_login_returns_session(client: AsyncClient) -> None:
    response = await client.post(
        "/api/auth/login", json={"username": "demo.admin", "password": "admin-pass"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "demo.admin"
    assert body["display_name"] == "Demo Admin"
    assert body["tenants"] == ["acme", "globex"]
    assert body["token"] and body["expires_at"]


@pytest.mark.parametrize("username,password", [("acme.analyst", "wrong"), ("nobody", "acme-pass")])
async def test_wrong_password_and_unknown_user_look_the_same(
    client: AsyncClient, username: str, password: str
) -> None:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Wrong username or password"}


async def test_me_and_logout(client: AsyncClient, acme: dict[str, str]) -> None:
    me = await client.get("/api/auth/me", headers=acme)
    assert me.json() == {
        "username": "acme.analyst",
        "display_name": "Acme Analyst",
        "tenants": ["acme"],
    }
    assert (await client.post("/api/auth/logout", headers=acme)).status_code == 204


async def test_tenants_lists_only_the_callers(client: AsyncClient, acme: dict[str, str]) -> None:
    assert (await client.get("/api/tenants", headers=acme)).json() == ["acme"]
    admin = await sign_in(client, "demo.admin")
    assert (await client.get("/api/tenants", headers=admin)).json() == ["acme", "globex"]


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer nonsense"}, {"Authorization": "Basic abc"}],
)
async def test_tenant_routes_need_a_valid_token(client: AsyncClient, headers: dict) -> None:
    response = await client.get("/api/acme/cases", headers=headers)
    assert response.status_code == 401


async def test_tampered_token_is_rejected(client: AsyncClient, acme: dict[str, str]) -> None:
    token = acme["Authorization"].removeprefix("Bearer ")
    payload, _, signature = token.partition(".")
    forged = {"Authorization": f"Bearer {payload}x.{signature}"}
    assert (await client.get("/api/acme/cases", headers=forged)).status_code == 401


async def test_expired_token_is_rejected(client: AsyncClient) -> None:
    token, _ = create_token(
        "acme.analyst", SECRET.encode(), 1, now=datetime.now(UTC) - timedelta(hours=2)
    )
    response = await client.get("/api/acme/cases", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_other_tenant_is_forbidden(client: AsyncClient, acme: dict[str, str]) -> None:
    assert (await client.get("/api/globex/cases", headers=acme)).status_code == 403


async def test_unknown_tenant_is_not_found(client: AsyncClient, admin: dict[str, str]) -> None:
    assert (await client.get("/api/initech/cases", headers=admin)).status_code == 404


def test_token_round_trip_and_expiry() -> None:
    now = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
    token, expires_at = create_token("demo.admin", b"k" * 32, 12, now=now)
    assert expires_at == now + timedelta(hours=12)
    assert verify_token(token, b"k" * 32, now=now) == "demo.admin"
    with pytest.raises(InvalidToken):
        verify_token(token, b"other-secret" * 3, now=now)
    with pytest.raises(InvalidToken):
        verify_token(token, b"k" * 32, now=expires_at)


UNKNOWN_TENANT_USER = json.dumps(
    [{"username": "x", "display_name": "X", "password": "p", "tenants": ["initech"]}]
)


@pytest.mark.parametrize(
    "env,message",
    [
        ({"ARGUS_SESSION_SECRET": "short"}, "ARGUS_SESSION_SECRET"),
        ({"ARGUS_DEMO_USERS": "[]"}, "at least one user"),
        ({"ARGUS_DEMO_USERS": UNKNOWN_TENANT_USER}, "not in ARGUS_TENANTS"),
    ],
)
def test_bad_settings_fail_at_startup(
    monkeypatch: pytest.MonkeyPatch, env: dict, message: str
) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match=message):
        ApiSettings()
