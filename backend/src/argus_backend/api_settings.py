"""Settings only the backend needs: demo users and session tokens (CONTRACT_GAPS GAP-1).

Read from the environment and `.env`, like `argus_soc.core.settings` (which still supplies the
shared values: tenants, graph backend, API port, CORS origins). A bad value fails at startup
instead of on the first request (rule C9).

    ARGUS_DEMO_USERS='[{"username": "acme.analyst", "display_name": "Acme Analyst",
                        "password": "...", "tenants": ["acme"]}]'
    ARGUS_SESSION_SECRET=<at least 32 random characters>
    ARGUS_SESSION_HOURS=12

Login is hard-coded for the hackathon (HLD D13): no user table, nothing about analysts is
written to FalkorDB except the username on each Feedback.
"""

from functools import lru_cache

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from argus_soc.core.settings import get_settings

MIN_SECRET_LENGTH = 32


class DemoUser(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=100)
    password: SecretStr
    tenants: list[str] = Field(min_length=1)


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    argus_demo_users: list[DemoUser] = Field(default_factory=list)
    argus_session_secret: SecretStr | None = None
    argus_session_hours: int = Field(default=12, ge=1, le=168)

    @field_validator("argus_session_secret")
    @classmethod
    def _check_secret(cls, value: SecretStr | None) -> SecretStr:
        if value is None or len(value.get_secret_value()) < MIN_SECRET_LENGTH:
            raise ValueError(
                f"ARGUS_SESSION_SECRET must be set, at least {MIN_SECRET_LENGTH} chars"
            )
        return value

    @model_validator(mode="after")
    def _check_users(self) -> "ApiSettings":
        if not self.argus_demo_users:
            raise ValueError("ARGUS_DEMO_USERS must list at least one user")
        names = [u.username for u in self.argus_demo_users]
        if len(set(names)) != len(names):
            raise ValueError("ARGUS_DEMO_USERS lists a username twice")
        known = set(get_settings().tenant_ids)
        for user in self.argus_demo_users:
            unknown = sorted(set(user.tenants) - known)
            if unknown:
                raise ValueError(
                    f"user {user.username!r} has tenants not in ARGUS_TENANTS: {unknown}"
                )
        return self

    @property
    def session_secret(self) -> bytes:
        assert self.argus_session_secret is not None  # checked by the validator
        return self.argus_session_secret.get_secret_value().encode()

    def find_user(self, username: str) -> DemoUser | None:
        return next((u for u in self.argus_demo_users if u.username == username), None)


@lru_cache(maxsize=1)
def get_api_settings() -> ApiSettings:
    """Load once per process. Tests call `get_api_settings.cache_clear()`."""
    return ApiSettings()
