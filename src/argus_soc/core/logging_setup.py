"""JSON-lines logging to stdout for every service (docs/LLD.md §3, §10).

Each line has: ts, level, service, tenant, case_id, agent, msg (plus `exc` on errors).

    setup_logging("agents")
    log = get_logger(__name__, tenant="acme", agent="triage")
    log.info("case opened", extra={"case_id": 33})

Messages are JSON-encoded, so newlines or quotes inside attacker-controlled text
(log lines, Talos evidence) cannot fake a second log entry.
"""

import json
import logging
import sys
from collections.abc import MutableMapping
from datetime import UTC, datetime
from typing import Any

from argus_soc.core.settings import get_settings

CONTEXT_FIELDS = ("tenant", "case_id", "agent")


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": self.service,
        }
        for field in CONTEXT_FIELDS:
            entry[field] = getattr(record, field, None)
        entry["msg"] = record.getMessage()
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str, ensure_ascii=False)


class ContextLogger(logging.LoggerAdapter):
    """Adds fixed context (tenant, case_id, agent) to every line; per-call `extra` wins."""

    def process(
        self, msg: Any, kwargs: MutableMapping[str, Any]
    ) -> tuple[Any, MutableMapping[str, Any]]:
        kwargs["extra"] = {**(self.extra or {}), **kwargs.get("extra", {})}
        return msg, kwargs


def setup_logging(service: str, level: str | None = None) -> None:
    """Send all logging to stdout as JSON lines. Safe to call more than once."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level or get_settings().log_level)


def get_logger(name: str, **context: Any) -> ContextLogger:
    """Logger that stamps `context` (e.g. tenant="acme", agent="triage") on every line."""
    unknown = set(context) - set(CONTEXT_FIELDS)
    if unknown:
        raise ValueError(f"unknown log context {sorted(unknown)}; use {CONTEXT_FIELDS}")
    return ContextLogger(logging.getLogger(name), dict(context))
