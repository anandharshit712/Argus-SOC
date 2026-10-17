"""Settings for every Argus SOC service, read from the environment and `.env`.

The variables and defaults are the ones in docs/LLD.md §2. Field names match the
environment variable names (case does not matter): `falkordb_host` <- `FALKORDB_HOST`.
A bad value raises a validation error when the settings are first loaded, so a
service fails at startup instead of halfway through a case (rule C9).
"""

import os
import re
import socket
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_TENANT_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Graph (Workstream B) -------------------------------------------------
    falkordb_host: str = "falkordb"
    falkordb_port: int = Field(default=6379, ge=1, le=65535)
    argus_tenants: str = "acme,globex"  # comma-separated tenant ids
    argus_graph_backend: Literal["falkordb", "stub"] = "falkordb"
    mcp_server_command: str = "python -m argus_soc.graph.mcp_server"

    # --- Ingestor (Workstream A) ----------------------------------------------
    talos_url: str = "http://talos:8000"
    ingest_poll_seconds: float = Field(default=3, gt=0)
    ingest_page_limit: int = Field(default=50, ge=1)
    # Tenant inventories (data/inventory/): which hosts and IPs belong to which tenant.
    argus_inventory_dir: str = "data/inventory"

    # --- Agents and learning (Workstream A) -----------------------------------
    agent_poll_seconds: float = Field(default=2, gt=0)
    agent_claim_ttl_seconds: int = Field(default=120, ge=1)
    correlation_window_hours: int = Field(default=24, ge=1)
    max_path_hops: int = Field(default=6, ge=1, le=10)
    repeat_target_threshold: int = Field(default=2, ge=1)
    deep_dive_enabled: bool = True  # only runs when llm_enabled is also true
    deep_dive_max_calls: int = Field(default=4, ge=0)
    agent_worker_id: str = Field(default_factory=socket.gethostname)
    playbook_min_feedback: int = Field(default=1, ge=1)
    llm_enabled: bool = False
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: float = Field(default=20, gt=0)

    # --- Backend API (Workstream C) -------------------------------------------
    api_port: int = Field(default=8080, ge=1, le=65535)
    api_cors_origins: str = "http://localhost:5173"  # comma-separated

    # --- Everyone -------------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator("argus_tenants")
    @classmethod
    def _check_tenants(cls, value: str) -> str:
        ids = [part.strip() for part in value.split(",") if part.strip()]
        if not ids:
            raise ValueError("ARGUS_TENANTS must list at least one tenant")
        bad = [t for t in ids if not _TENANT_ID.match(t)]
        if bad:
            raise ValueError(f"invalid tenant ids {bad}: use lowercase letters, digits, _")
        if len(set(ids)) != len(ids):
            raise ValueError("ARGUS_TENANTS lists a tenant twice")
        return ",".join(ids)

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @property
    def tenant_ids(self) -> list[str]:
        return self.argus_tenants.split(",")

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    @property
    def deep_dive_active(self) -> bool:
        return self.deep_dive_enabled and self.llm_enabled

    def talos_url_for(self, tenant: str) -> str:
        """`TALOS_URL_<TENANT>` when one Talos runs per tenant, else `TALOS_URL`.

        Per-tenant URLs are read from the process environment (set them in Compose).
        """
        return os.environ.get(f"TALOS_URL_{tenant.upper()}") or self.talos_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load the settings once per process. Tests call `get_settings.cache_clear()`."""
    return Settings()
