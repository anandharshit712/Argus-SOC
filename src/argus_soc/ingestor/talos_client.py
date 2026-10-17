"""Talos HTTP client (docs/LLD.md §5.1). Talos is reached only over its API (rule 7).

`GET /reports` already returns full IncidentReports (every verdict and its evidence), so the
ingestor never needs `GET /reports/{incident_id}`.
"""

import asyncio
from typing import Any

import httpx

from argus_soc.core.logging_setup import get_logger

TIMEOUT_SECONDS = 10
RETRY_DELAYS = (1, 2, 4, 8)  # seconds; then the error goes to the caller (LLD §5.1, §9)

log = get_logger(__name__)


class TalosError(Exception):
    """Talos could not be reached or answered with an error, after retries."""


class TalosClient:
    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url
        self._http = httpx.AsyncClient(
            base_url=base_url, timeout=TIMEOUT_SECONDS, transport=transport
        )

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET with retries on connection errors and 5xx; 4xx fails at once."""
        for attempt, delay in enumerate((*RETRY_DELAYS, None)):
            try:
                response = await self._http.get(path, params=params)
                if response.status_code < 500:
                    response.raise_for_status()
                    return response.json()
                error = f"HTTP {response.status_code}"
            except httpx.HTTPStatusError as exc:
                raise TalosError(f"{self.base_url}{path}: HTTP {exc.response.status_code}") from exc
            except httpx.TransportError as exc:
                error = repr(exc)
            if delay is None:
                raise TalosError(f"{self.base_url}{path}: {error} after {attempt + 1} tries")
            log.warning("talos %s%s failed (%s), retry in %ss", self.base_url, path, error, delay)
            await asyncio.sleep(delay)

    async def list_reports(self, limit: int) -> list[dict[str, Any]]:
        """`GET /reports`: the newest incidents first (Talos caps `limit` at 200)."""
        return await self._get("/reports", {"limit": limit})

    async def aclose(self) -> None:
        await self._http.aclose()
