"""How Python values are stored as FalkorDB properties and read back.

FalkorDB properties hold strings, numbers, booleans and lists of those. Nested data
(findings, decision evidence, Talos evidence, tool calls) is stored as a JSON string and
parsed on the way out. Timestamps are ISO 8601 strings in UTC with second precision, so
they compare correctly as strings (claim expiry, "since" filters).
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def utc_ago(seconds: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _plain(value: Any) -> Any:
    if isinstance(value, set | frozenset | tuple):
        return list(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def to_json(value: Any) -> str:
    """Nested Python data -> JSON text for one property. Tuples and sets become lists."""
    return json.dumps(value, default=_plain, ensure_ascii=False, sort_keys=True)


def from_json(text: str | None, default: Any) -> Any:
    """JSON property -> Python value; missing or empty gives `default`."""
    if not text:
        return default
    return json.loads(text)
