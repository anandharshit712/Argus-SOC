"""Who is calling, and may they see this tenant? (CONTRACT_GAPS GAP-1)

Every `/api/{tenant}/...` route depends on `tenant_access`:
- 401 without a valid, unexpired bearer token;
- 404 for a tenant that is not in ARGUS_TENANTS;
- 403 for a tenant the signed-in user is not allowed to see.
`/api/health` and `/api/auth/login` stay open.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from argus_backend.api_settings import DemoUser, get_api_settings
from argus_backend.session_tokens import InvalidToken, verify_token
from argus_soc.core import tenant_registry

_bearer = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not signed in or the session has expired",
    headers={"WWW-Authenticate": "Bearer"},
)


async def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> DemoUser:
    """The signed-in demo user. A token for a user who was since removed is rejected too."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _UNAUTHORIZED
    settings = get_api_settings()
    try:
        username = verify_token(credentials.credentials, settings.session_secret)
    except InvalidToken:
        raise _UNAUTHORIZED from None
    user = settings.find_user(username)
    if user is None:
        raise _UNAUTHORIZED
    return user


def allowed_tenants(user: DemoUser) -> list[str]:
    """The user's tenants that exist, in ARGUS_TENANTS order."""
    return [t for t in tenant_registry.tenants() if t in user.tenants]


async def tenant_access(tenant: str, user: DemoUser = Depends(current_user)) -> str:
    """The path's tenant, once it is known to exist and the user may see it."""
    if tenant not in tenant_registry.tenants():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown tenant")
    if tenant not in user.tenants:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No access to this tenant"
        )
    return tenant
