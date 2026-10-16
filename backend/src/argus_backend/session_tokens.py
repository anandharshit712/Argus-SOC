"""Stateless session tokens: `base64url(payload).base64url(hmac_sha256(payload))`.

`payload` is `{"u": username, "exp": unix seconds}`. Nothing is stored server side, so logout
only means the browser drops the token, and changing ARGUS_SESSION_SECRET signs everyone out.
No JWT library: the format is small enough to check by eye (CONTRACT_GAPS GAP-1).
"""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta


class InvalidToken(Exception):
    """Malformed, tampered with or expired. The message is never shown to the caller."""


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: str, secret: bytes) -> str:
    return _b64encode(hmac.new(secret, payload.encode(), hashlib.sha256).digest())


def create_token(
    username: str, secret: bytes, hours: int, now: datetime | None = None
) -> tuple[str, datetime]:
    """A signed token for `username` and the moment it expires."""
    expires_at = (now or datetime.now(UTC)) + timedelta(hours=hours)
    body = json.dumps({"u": username, "exp": int(expires_at.timestamp())}, separators=(",", ":"))
    payload = _b64encode(body.encode())
    return f"{payload}.{_sign(payload, secret)}", expires_at.replace(microsecond=0)


def verify_token(token: str, secret: bytes, now: datetime | None = None) -> str:
    """The username in a valid token. Raises InvalidToken otherwise."""
    payload, sep, signature = token.partition(".")
    if not sep or not payload or not signature:
        raise InvalidToken("not a token")
    if not hmac.compare_digest(signature, _sign(payload, secret)):
        raise InvalidToken("bad signature")
    try:
        body = json.loads(_b64decode(payload))
        username, expires = body["u"], int(body["exp"])
    except (ValueError, KeyError, TypeError) as exc:
        raise InvalidToken("bad payload") from exc
    if not isinstance(username, str) or not username:
        raise InvalidToken("bad payload")
    if (now or datetime.now(UTC)).timestamp() >= expires:
        raise InvalidToken("expired")
    return username
