"""Tiny deliberately-attackable demo shop for the live Argus harness.

Writes one nginx-JSON access line per request to the access log the shipper tails, in the exact
shape Talos's WebLogParser reads (`time_iso8601`, `remote_addr`, `host`, `request_method`,
`request_uri`, `status`, `body_bytes_sent`, `http_user_agent`, `http_referer`, `request_body`).

The real client address is taken from `X-Forwarded-For`, trusted ONLY from the attack-bot's
container IP (DEMO_TRUSTED_PROXY) so a live attack carries documentation-range source IPs instead
of the Docker gateway. Everything here targets the bundled demo containers only.

ponytail: the app writes its own access log in nginx-JSON format instead of running a real nginx
in front of it -- one fewer container and no nginx config to own (that is Workstream B's folder).
A crude inline WAF 403s obvious SQLi/XSS so the injection story shows "did not succeed / high"
rather than "succeeded / critical" (DEMO_DESIGN §2, scenario 3).
"""

from __future__ import annotations

import json
import os
import re
import socket
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

HOST_NAME = os.environ.get("DEMO_WEB_HOST", "web-01")
ACCESS_LOG = Path(os.environ.get("DEMO_ACCESS_LOG", "/var/log/web_shop/access.jsonl"))
# Attack-bot container name or IP; X-Forwarded-For is honoured only from it. A name is resolved
# via Docker DNS so the compose file needs no hard-coded container IP.
TRUSTED_PROXY = os.environ.get("DEMO_TRUSTED_PROXY", "")

# A password nobody guesses: every demo login fails (401) unless it is the one valid demo account.
VALID_ACCOUNT = os.environ.get("DEMO_VALID_ACCOUNT", "demo@shop.example")
VALID_PASSWORD = os.environ.get("DEMO_VALID_PASSWORD", "correct-horse-battery-staple")

# ponytail: a stand-in WAF, not a real one. Obvious injection shapes -> 403 blocked, logged as
# WAF JSON. Deliberately stricter than "any apostrophe" so benign searches (o'brien jacket,
# order by price) are NOT blocked -- only payloads Talos would call actionable.
_SQLI = re.compile(
    r"('|%27)\s*(or|and|union|;|--)|\bunion\b.{0,20}\bselect\b|--\s*$|\bor\b\s+'?\d+'?\s*=\s*'?\d+",
    re.I,
)
_XSS = re.compile(r"<\s*script|on\w+\s*=|javascript:|<\s*svg|<\s*img[^>]*\bon\w+", re.I)

app = FastAPI(title="Argus demo shop")
ACCESS_LOG.parent.mkdir(parents=True, exist_ok=True)


def _trusted_proxy_ip() -> str | None:
    """Resolve DEMO_TRUSTED_PROXY (name or IP) to an IP, or None if unset/unresolvable."""
    if not TRUSTED_PROXY:
        return None
    try:
        return socket.gethostbyname(TRUSTED_PROXY)
    except OSError:
        return None


def _client_ip(request: Request) -> str:
    """Real source IP: trust X-Forwarded-For only from the attack-bot container."""
    peer = request.client.host if request.client else "unknown"
    if peer == _trusted_proxy_ip():
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return peer


def _uri(request: Request) -> str:
    return request.url.path + (f"?{request.url.query}" if request.url.query else "")


def _log(request: Request, source_ip: str, status: int, size: int, body: str | None) -> None:
    line = {
        "time_iso8601": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S%z"),
        "remote_addr": source_ip,
        "host": HOST_NAME,
        "request_method": request.method,
        "request_uri": _uri(request),
        "status": status,
        "body_bytes_sent": size,
        "http_user_agent": request.headers.get("user-agent", "-"),
        "http_referer": request.headers.get("referer", "-"),
    }
    if body is not None:
        line["request_body"] = body
    with ACCESS_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line) + "\n")


def _waf_block(request: Request, source_ip: str, payload: str) -> Response:
    """Log a WAF-JSON block line and return 403, like the WAF in front of the real shop."""
    line = {
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S%z"),
        "client_ip": source_ip,
        "host": HOST_NAME,
        "method": request.method,
        "uri": _uri(request),
        "status": 403,
        "action": "blocked",
        "rule_id": "942100",  # CRS SQLi/XSS rule family
        "anomaly_score": 15,
        "user_agent": request.headers.get("user-agent", "-"),
    }
    with ACCESS_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line) + "\n")
    return JSONResponse({"error": "request blocked"}, status_code=403)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    _log(request, _client_ip(request), 200, 512, None)
    return HTMLResponse("<h1>Argus Demo Shop</h1><p>Synthetic target for the live demo.</p>")


@app.get("/api/search")
async def search(request: Request, q: str = "") -> Response:
    source_ip = _client_ip(request)
    if _SQLI.search(q) or _XSS.search(q):
        return _waf_block(request, source_ip, q)
    _log(request, source_ip, 200, 1024, None)
    return JSONResponse({"query": q, "results": []})


@app.post("/login")
async def login(request: Request) -> Response:
    source_ip = _client_ip(request)
    form = await request.form()
    username = str(form.get("username", ""))
    password = str(form.get("password", ""))
    ok = username == VALID_ACCOUNT and password == VALID_PASSWORD
    status = 302 if ok else 401
    # Never log the real password (rule 9 / spec §3.3).
    _log(request, source_ip, status, 180, f"username={username}&password=********")
    return Response(status_code=status)


@app.get("/api/orders/{order_id}")
async def order(request: Request, order_id: int) -> Response:
    """Object endpoint for the IDOR story (soak mode only; needs a warmed baseline)."""
    _log(request, _client_ip(request), 200, 256, None)
    return JSONResponse({"order_id": order_id, "item": "demo"})


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
