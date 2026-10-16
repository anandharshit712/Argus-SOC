"""Sign in with a hard-coded demo user (HLD D13, CONTRACT_GAPS GAP-1).

POST /api/auth/login   {username, password} -> SessionOut
GET  /api/auth/me      bearer token         -> MeOut
POST /api/auth/logout  bearer token         -> 204 (tokens are stateless)
GET  /api/tenants                           -> the caller's tenants only
"""

import hmac

from fastapi import APIRouter, Depends, HTTPException, Response, status

from argus_backend.access_guard import allowed_tenants, current_user
from argus_backend.api_models import LoginIn, MeOut, SessionOut
from argus_backend.api_settings import DemoUser, get_api_settings
from argus_backend.session_tokens import create_token
from argus_soc.core.logging_setup import get_logger

router = APIRouter(prefix="/api")
log = get_logger(__name__)

# Compared against when the username is unknown, so both failures take the same path.
_NO_USER_PASSWORD = "\x00" * 32


def _me(user: DemoUser) -> MeOut:
    return MeOut(
        username=user.username, display_name=user.display_name, tenants=allowed_tenants(user)
    )


@router.post("/auth/login", response_model=SessionOut)
async def login(body: LoginIn) -> SessionOut:
    settings = get_api_settings()
    user = settings.find_user(body.username)
    expected = user.password.get_secret_value() if user else _NO_USER_PASSWORD
    password_ok = hmac.compare_digest(body.password.encode(), expected.encode())
    if user is None or not password_ok:
        log.info("failed sign in")  # never the username typed, the password or the token
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong username or password"
        )
    token, expires_at = create_token(
        user.username, settings.session_secret, settings.argus_session_hours
    )
    log.info("signed in: %s", user.username)
    return SessionOut(**_me(user).model_dump(), token=token, expires_at=expires_at)


@router.get("/auth/me", response_model=MeOut)
async def me(user: DemoUser = Depends(current_user)) -> MeOut:
    return _me(user)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(_: DemoUser = Depends(current_user)) -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/tenants", response_model=list[str])
async def list_tenants(user: DemoUser = Depends(current_user)) -> list[str]:
    return allowed_tenants(user)
