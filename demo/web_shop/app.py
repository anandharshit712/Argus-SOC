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

Home page (demo/README.md, "Attack buttons on the shop"): a banner, one-click campaign buttons
that call `/demo/launch` (a whitelisted, rate-limited proxy to the attack-bot's own `/launch`),
and a list of the attack-prone endpoints for anyone who wants to try their own payloads by hand
or via /docs. Every live attack lands in tenant Globex (this shop logs as gx-web-01).
"""

from __future__ import annotations

import json
import os
import re
import socket
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

HOST_NAME = os.environ.get("DEMO_WEB_HOST", "gx-web-01")  # a Globex host (data/inventory)
ACCESS_LOG = Path(os.environ.get("DEMO_ACCESS_LOG", "/var/log/web_shop/access.jsonl"))
# Attack-bot container name or IP; X-Forwarded-For is honoured only from it. A name is resolved
# via Docker DNS so the compose file needs no hard-coded container IP.
TRUSTED_PROXY = os.environ.get("DEMO_TRUSTED_PROXY", "")

# A password nobody guesses: every demo login fails (401) unless it is the one valid demo account.
VALID_ACCOUNT = os.environ.get("DEMO_VALID_ACCOUNT", "demo@shop.example")
VALID_PASSWORD = os.environ.get("DEMO_VALID_PASSWORD", "correct-horse-battery-staple")

# Pool accounts the attack-bot uses for a "pass" run: pool####@shop.example all share one password.
# A fresh pool account per pass keeps each success a new Talos signature (ATTACK_BOT_PASS_FAIL §6).
# Empty password -> no pool login works, so a pass cannot happen; the bot handles that fallback.
POOL_PASSWORD = os.environ.get("DEMO_POOL_PASSWORD", "")
_POOL_ACCOUNT = re.compile(r"^pool\d{4}@shop\.example$")

# ponytail: a stand-in WAF, not a real one. Obvious injection shapes -> 403 blocked, logged as
# WAF JSON. Deliberately stricter than "any apostrophe" so benign searches (o'brien jacket,
# order by price) are NOT blocked -- only payloads Talos would call actionable.
_SQLI = re.compile(
    r"('|%27)\s*(or|and|union|;|--)|\bunion\b.{0,20}\bselect\b|--\s*$|\bor\b\s+'?\d+'?\s*=\s*'?\d+",
    re.I,
)
_XSS = re.compile(r"<\s*script|on\w+\s*=|javascript:|<\s*svg|<\s*img[^>]*\bon\w+", re.I)

# --- demo launch panel (demo/README.md) -------------------------------------------------------
# The attack-bot is never reached from the browser directly, only through this proxy, and only
# these five fixed campaign names are forwarded to it: no pass-through, no soak control here.
ATTACK_BOT_URL = os.environ.get("DEMO_ATTACK_BOT_URL", "http://attack_bot:8000").rstrip("/")
# Where a resulting case shows up in the Argus UI (for the "view the case" link). Optional: the
# panel still works without it, it just has nothing to link to.
ARGUS_UI_URL = os.environ.get("DEMO_ARGUS_UI_URL", "")
ATTACKS: dict[str, str] = {
    "web_brute": "Web login brute force",
    "cred_stuffing": "Credential stuffing",
    "sqli": "SQL injection probe",
    "xss": "XSS probe",
    "ssh_brute": "SSH brute force",
}
OUTCOMES = ("fail", "pass")
# Global, not per visitor: behind the public nginx every visitor has the same address anyway.
LAUNCH_INTERVAL_SECONDS = 20.0
# The bot answers only after the campaign and its Talos poll (up to 40 s for a pass), and it may
# first wait for its lock while a soak campaign runs. Past this, the attack still runs in the
# background; the page then says so instead of reporting a failure.
LAUNCH_TIMEOUT_SECONDS = 120.0

_launch_lock = threading.Lock()
_launch_state = {"running": False, "last_start": float("-inf")}

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


def _is_trusted_peer(request: Request) -> bool:
    """True when the request's direct peer is the attack-bot container (the only source we trust
    for X-Forwarded-For and the X-Demo-Outcome bypass). The public internet never is."""
    peer = request.client.host if request.client else None
    return peer is not None and peer == _trusted_proxy_ip()


def _client_ip(request: Request) -> str:
    """Real source IP: trust X-Forwarded-For only from the attack-bot container."""
    peer = request.client.host if request.client else "unknown"
    if _is_trusted_peer(request):
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


def _waf_block(request: Request, source_ip: str) -> Response:
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


def _attack_buttons_html() -> str:
    buttons = []
    for name, label in ATTACKS.items():
        buttons.append(
            f"""
        <div class="attack-row">
          <span class="attack-label">{label}</span>
          <select id="outcome-{name}">
            <option value="fail">fail</option>
            <option value="pass">pass</option>
          </select>
          <button onclick="launch('{name}')" id="btn-{name}">Launch</button>
          <span class="attack-result" id="result-{name}"></span>
        </div>"""
        )
    return "".join(buttons)


_ARGUS_WHERE = (
    f'<a href="{ARGUS_UI_URL}" target="_blank" rel="noopener">Argus</a>'
    if ARGUS_UI_URL
    else "the Argus UI (ask your host for its address)"
)
_ARGUS_LINK_HTML = (
    f"<p>Every attack on this shop lands in tenant <strong>Globex</strong>. See the resulting "
    f"case in {_ARGUS_WHERE}, signed in as a Globex user; the incident id shown after each "
    "launch is how to find it.</p>"
)

_HOME_PAGE = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Argus Demo Shop</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 820px; margin: 2rem auto; padding: 0 1rem;
         background: #0b120f; color: #d8e8df; }}
  h1, h2 {{ color: #7be3a0; }}
  .banner {{ border: 1px solid #c77; background: #2a1414; color: #f3c4c4; padding: 0.75rem 1rem;
             border-radius: 6px; margin-bottom: 1.5rem; }}
  .attack-row {{ display: flex; align-items: center; gap: 0.75rem; padding: 0.4rem 0; }}
  .attack-label {{ flex: 1 0 220px; }}
  button {{ background: #1d5c38; color: #eafff0; border: 0; border-radius: 4px;
            padding: 0.4rem 0.9rem; cursor: pointer; }}
  button:disabled {{ opacity: 0.5; cursor: default; }}
  .attack-result {{ font-family: ui-monospace, monospace; font-size: 0.85rem; color: #9fc; }}
  .attack-result.err {{ color: #f88; }}
  code {{ background: #182420; padding: 0.1rem 0.35rem; border-radius: 3px; }}
  ul {{ line-height: 1.7; }}
  a {{ color: #7be3a0; }}
</style>
</head>
<body>
<h1>Argus Demo Shop</h1>
<div class="banner">
  Deliberately vulnerable synthetic target built for the Argus SOC demo. Nothing here is a real
  store, a real account or real infrastructure &mdash; every button below only talks to this
  sandbox's own containers.
</div>
{_ARGUS_LINK_HTML}

<h2>One-click attacks</h2>
<p>Pick an outcome and launch a campaign against this shop. <code>fail</code> is a realistic
attempt that does not get in; <code>pass</code> lets one attempt through so you can see a
succeeded, higher-severity case that waits for an analyst's approval.</p>
<p>One launch at a time, shared by everyone using this page, at least 20 s apart. A run takes
10 s to about a minute; if the attack harness is busy with its own background campaign, yours
waits for it first.</p>
{_attack_buttons_html()}

<h2>Attack-prone endpoints</h2>
<p>Prefer to try your own payloads? These are the endpoints Talos watches. Full interactive docs
(including "try it out") are at <a href="/docs">/docs</a>.</p>
<ul>
  <li><code>GET /api/search?q=...</code> (and <code>/api/products</code>, <code>/api/items</code>,
      <code>/api/catalog</code>, <code>/api/reviews</code>, <code>/api/deals</code>) &mdash; an
      injection point behind a small inline WAF.</li>
  <li><code>POST /login</code> (form fields <code>username</code>, <code>password</code>) &mdash;
      watched for brute force and credential stuffing.</li>
  <li><code>GET /api/orders/&#123;id&#125;</code> &mdash; an object-reference endpoint.</li>
</ul>
<p>One note: free-form traffic from this page or from <code>/docs</code> all shares one visible
source IP (this host's own), since only the attack-bot's traffic carries synthetic source IPs.</p>

<script>
async function launch(name) {{
  const btn = document.getElementById('btn-' + name);
  const out = document.getElementById('result-' + name);
  const outcome = document.getElementById('outcome-' + name).value;
  btn.disabled = true;
  out.className = 'attack-result';
  out.textContent = 'running…';
  try {{
    const res = await fetch('/demo/launch?attack=' + encodeURIComponent(name) +
                             '&outcome=' + encodeURIComponent(outcome), {{ method: 'POST' }});
    const body = await res.json();
    if (res.status === 504) {{
      out.textContent = body.error;  // still running in the background: not a failure
    }} else if (!res.ok) {{
      out.className = 'attack-result err';
      out.textContent = body.error || ('HTTP ' + res.status);
    }} else if (body.detected) {{
      out.textContent = 'detected: ' + body.incident_id + ' (' + body.latency_s + ' s)' +
                        (body.warning ? ' (' + body.warning + ')' : '');
    }} else {{
      out.textContent = 'not detected within the wait window';
      out.className = 'attack-result err';
    }}
  }} catch (err) {{
    out.className = 'attack-result err';
    out.textContent = 'could not reach the demo harness';
  }} finally {{
    btn.disabled = false;
  }}
}}
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    _log(request, _client_ip(request), 200, len(_HOME_PAGE), None)
    return HTMLResponse(_HOME_PAGE)


def _claim_launch_slot() -> str | None:
    """Take the single launch slot, or say why not (one launch in flight, 20 s apart)."""
    now = time.monotonic()
    with _launch_lock:
        if _launch_state["running"]:
            return "another launch is still running; try again when it finishes"
        wait = LAUNCH_INTERVAL_SECONDS - (now - _launch_state["last_start"])
        if wait > 0:
            gap = f"{LAUNCH_INTERVAL_SECONDS:.0f} s"
            return f"launches are at least {gap} apart; try again in {wait:.0f} s"
        _launch_state.update(running=True, last_start=now)
        return None


@app.post("/demo/launch")
async def demo_launch(attack: str, outcome: str = "fail") -> Response:
    """Whitelisted, rate-limited proxy to the attack-bot's own `/launch` (demo/README.md).

    Only the five fixed campaign names are forwarded: no arbitrary pass-through to the bot, and
    the bot's soak controls are never reachable from here.
    """
    if attack not in ATTACKS:
        return JSONResponse({"error": f"attack must be one of {sorted(ATTACKS)}"}, status_code=400)
    if outcome not in OUTCOMES:
        return JSONResponse({"error": "outcome must be fail or pass"}, status_code=400)
    busy = _claim_launch_slot()
    if busy:
        return JSONResponse({"error": busy}, status_code=429)

    try:
        async with httpx.AsyncClient(timeout=LAUNCH_TIMEOUT_SECONDS) as client:
            upstream = await client.post(
                f"{ATTACK_BOT_URL}/launch", params={"attack": attack, "outcome": outcome}
            )
    except httpx.TimeoutException:
        # The bot keeps going after we stop waiting; the case still shows up.
        return JSONResponse(
            {"error": "still running in the background; check Argus in a minute"},
            status_code=504,
        )
    except httpx.HTTPError:
        return JSONResponse({"error": "could not reach the attack harness"}, status_code=502)
    finally:
        with _launch_lock:
            _launch_state["running"] = False

    try:
        body = upstream.json()
    except ValueError:
        return JSONResponse(
            {"error": f"the attack harness answered {upstream.status_code} without JSON"},
            status_code=502,
        )
    return JSONResponse(body, status_code=upstream.status_code)


# Several search-like endpoints behind ONE handler. The attack-bot rotates among them per
# injection run: Talos's repeat-suppression signature includes affected_endpoints (but not source
# IP), so a fresh endpoint is what makes the next sqli/xss run a new signature instead of a
# suppressed duplicate. All of them must exist and be logged, or a 404 would never reach Talos.
@app.get("/api/search")
@app.get("/api/products")
@app.get("/api/items")
@app.get("/api/catalog")
@app.get("/api/reviews")
@app.get("/api/deals")
async def search(request: Request, q: str = "") -> Response:
    source_ip = _client_ip(request)
    if _SQLI.search(q) or _XSS.search(q):
        # Bypass the WAF only for a request the trusted bot marks as a "pass" (ATTACK_BOT_PASS_FAIL
        # §7). From anyone else -- including the public internet -- the header is ignored and the
        # payload still gets a 403. No real data is returned either way; results stay empty.
        if request.headers.get("x-demo-outcome") == "pass" and _is_trusted_peer(request):
            _log(request, source_ip, 200, 1024, None)
            return JSONResponse({"query": q, "results": []})
        return _waf_block(request, source_ip)
    _log(request, source_ip, 200, 1024, None)
    return JSONResponse({"query": q, "results": []})


@app.post("/login")
async def login(request: Request) -> Response:
    source_ip = _client_ip(request)
    form = await request.form()
    username = str(form.get("username", ""))
    password = str(form.get("password", ""))
    ok = (username == VALID_ACCOUNT and password == VALID_PASSWORD) or (
        bool(POOL_PASSWORD) and bool(_POOL_ACCOUNT.match(username)) and password == POOL_PASSWORD
    )
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
