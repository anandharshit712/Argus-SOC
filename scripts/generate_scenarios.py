#!/usr/bin/env python3
"""Generate the synthetic demo scenario logs in data/scenarios/ (Workstream A).

    python scripts/generate_scenarios.py            # writes data/scenarios/scenario_NN_*/

Built on Oct 16 to verify Talos before any agent work (CHAT_LOG turns 23-26): every incident
Talos raised from scenarios 0-5 matched the expected output, locally and in Docker. Changes
since then, none of which alter what Talos detects:
  * scenario 5 targets hosts that exist in data/inventory/ (acme-svc-001 for app-03, ...), so
    reports route to their tenant; one-to-one renames, no random draw changed;
  * scenario 6 added after the others (G10, semantic memory), so scenarios 0-5 are unchanged;
  * folders renamed scenario_NN_<story>/ (FOLDER_STRUCTURE.md).

One script, standard library only, one fixed random seed (§1.1.7). Running it twice
produces byte-identical files. Each scenario writes to its own sub-folder and each log
source to its own file. § references are to TALOS_TEST_SCENARIOS_SPEC.md.

The data is written from each scenario's *story* (§1.1.1): who did what, when, how many
times, with what result. Nothing here is tuned to make Talos fire or not fire -- the
expected output in EXPECTED_OUTPUT.md is derived separately by tracing these lines through
the rules in §4.

Telemetry shapes were confirmed against Talos at commit 15e732b:
  * sshd syslog  -> src/talos/ingestion/parsers/network_log_parser.py
  * Windows RDP  -> same parser (_parse_rdp_event); only LogonType 10 is read as RDP
  * nginx / WAF  -> src/talos/ingestion/parsers/web_log_parser.py

Addresses, hosts, accounts and dates come only from spec §2 and §5. External addresses are
from the documentation ranges 192.0.2.0/24, 198.51.100.0/24 and 203.0.113.0/24; internal
from 10.0.0.0/8; domains end in .example.
"""

from __future__ import annotations

import argparse
import json
import os
import random
from datetime import UTC, datetime, timedelta

UTC = UTC

# A single fixed seed drives every random choice (jitter, ports, pids, UA pick, byte sizes,
# which background customers do what). The generation order is fixed, so the stream is stable
# and a second run is byte-identical.
SEED = 20261011

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


# --------------------------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------------------------


def syslog_stamp(ts: datetime) -> str:
    """`Mmm D HH:MM:SS`, day space-padded to width 2 (e.g. 'Sep 28', 'Oct  6')."""
    return f"{_MONTHS[ts.month - 1]} {ts.day:2d} {ts:%H:%M:%S}"


def iso_z(ts: datetime) -> str:
    """ISO-8601 with a trailing Z, whole seconds -- the shape an EVTX JSON exporter writes."""
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_off(ts: datetime) -> str:
    """ISO-8601 with a +00:00 offset -- nginx's time_iso8601 and a common WAF stamp."""
    return ts.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def pct(value: str) -> str:
    """Percent-encode a query value exactly once, as a browser or tool would send it (§3.3)."""
    out = []
    safe = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.~"
    for ch in value:
        if ch in safe:
            out.append(ch)
        else:
            out.append("".join(f"%{b:02X}" for b in ch.encode("utf-8")))
    return "".join(out)


# --------------------------------------------------------------------------------------------
# A log file under construction: entries carried with their event time so a collector file can
# be written in true time order (§5), with a stable insertion-order tiebreaker.
# --------------------------------------------------------------------------------------------


class LogFile:
    def __init__(self) -> None:
        self._entries: list[tuple[datetime, int, str]] = []
        self._seq = 0

    def line(self, ts: datetime, text: str) -> None:
        self._entries.append((ts, self._seq, text))
        self._seq += 1

    def render(self) -> str:
        ordered = sorted(self._entries, key=lambda item: (item[0], item[1]))
        return "".join(f"{text}\n" for _, _, text in ordered)


# --------------------------------------------------------------------------------------------
# Shared realistic detail
# --------------------------------------------------------------------------------------------

BROWSER_UAS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/18.1 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like "
    "Gecko) Version/18.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0",
)
STUFFING_UA = "python-requests/2.32.3"
SQLMAP_UA = "sqlmap/1.8.9#stable (https://sqlmap.org)"

SEARCH_PHRASES = (
    "running shoes",
    "blue jacket",
    "wireless headphones",
    "coffee maker",
    "yoga mat",
    "european union flags",
    "o'brien jacket",
    "order by price",
    "select a gift card",
    "desk lamp",
    "water bottle",
    "winter gloves",
    "laptop stand",
    "garden hose",
    "kids backpack",
    "phone case",
    "wall clock",
    "picnic blanket",
)
PRODUCT_PATHS = (
    "/",
    "/products",
    "/products/shoes",
    "/products/outdoor",
    "/cart",
    "/deals",
    "/account",
    "/products/electronics",
    "/support",
    "/products/home",
)


class Ports:
    """Rising ephemeral source ports and rising sshd pids -- each attempt a new connection."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self._port = rng.randint(49200, 50200)
        self._pid = rng.randint(2000, 9000)

    def port(self) -> int:
        self._port += self.rng.randint(1, 60)
        if self._port > 65400:
            self._port = self.rng.randint(49200, 50200)
        return self._port

    def pid(self) -> int:
        self._pid += self.rng.randint(1, 40)
        return self._pid


# --------------------------------------------------------------------------------------------
# sshd emitters
# --------------------------------------------------------------------------------------------


def ssh_fail_existing(f, ts, host, acct, ip, ports):
    """One failed password against an account that exists -> a single line (§3.1)."""
    f.line(
        ts,
        f"{syslog_stamp(ts)} {host} sshd[{ports.pid()}]: "
        f"Failed password for {acct} from {ip} port {ports.port()} ssh2",
    )


def ssh_fail_invalid(f, ts, host, acct, ip, ports):
    """One failed attempt against a non-existent account -> two lines, as real sshd writes
    (§1.1.4): the `Invalid user` notice and then the `Failed password for invalid user` line."""
    p = ports.pid()
    port = ports.port()
    f.line(ts, f"{syslog_stamp(ts)} {host} sshd[{p}]: Invalid user {acct} from {ip} port {port}")
    f.line(
        ts,
        f"{syslog_stamp(ts)} {host} sshd[{p}]: "
        f"Failed password for invalid user {acct} from {ip} port {port} ssh2",
    )


def ssh_accept(f, ts, host, acct, ip, ports, method="password"):
    """A successful login plus the session-opened line (a skipped housekeeping line)."""
    p = ports.pid()
    f.line(
        ts,
        f"{syslog_stamp(ts)} {host} sshd[{p}]: "
        f"Accepted {method} for {acct} from {ip} port {ports.port()} ssh2",
    )
    f.line(
        ts + timedelta(seconds=1),
        f"{syslog_stamp(ts + timedelta(seconds=1))} {host} sshd[{p}]: "
        f"pam_unix(sshd:session): session opened for user {acct} by (uid=0)",
    )


def ssh_housekeeping(f, ts, host, ip, ports, acct=None):
    """A line Talos skips: connection teardown / disconnect chatter (§3.1)."""
    p = ports.pid()
    port = ports.port()
    kind = ts.second % 3
    if kind == 0:
        f.line(
            ts,
            f"{syslog_stamp(ts)} {host} sshd[{p}]: Connection closed by {ip} port {port} [preauth]",
        )
    elif kind == 1 and acct:
        f.line(
            ts,
            f"{syslog_stamp(ts)} {host} sshd[{p}]: Disconnected from user {acct} {ip} port {port}",
        )
    else:
        f.line(
            ts,
            f"{syslog_stamp(ts)} {host} sshd[{p}]: "
            f"Received disconnect from {ip} port {port}:11: disconnected by user",
        )


# --------------------------------------------------------------------------------------------
# Windows RDP (Security event JSON) emitters
# --------------------------------------------------------------------------------------------


def rdp_record(
    ts,
    computer,
    acct,
    ip,
    event_id,
    logon_type,
    *,
    sub_status=None,
    wks="WKS-REMOTE",
    port=0,
    domain="GLOBEX",
):
    rec = {
        "EventID": event_id,
        "TimeCreated": iso_z(ts),
        "Computer": computer,
        "TargetUserName": acct,
        "TargetDomainName": domain,
        "IpAddress": ip,
        "IpPort": str(port),
        "LogonType": logon_type,
        "LogonProcessName": "NtLmSsp ",
        "AuthenticationPackageName": "NTLM",
        "WorkstationName": wks,
        "ProcessName": "C:\\Windows\\System32\\svchost.exe",
    }
    if sub_status is not None:
        rec["SubStatus"] = sub_status
    return json.dumps(rec)


def rdp_fail(f, ts, computer, acct, ip, wks="WKS-REMOTE", port=0):
    """4625, LogonType 10, SubStatus 0xC000006A (wrong password) -- a read RDP failure."""
    f.line(
        ts,
        rdp_record(ts, computer, acct, ip, 4625, 10, sub_status="0xC000006A", wks=wks, port=port),
    )


def rdp_success(f, ts, computer, acct, ip, wks="WKS-REMOTE", port=0):
    """4624, LogonType 10 -- a read RDP success."""
    f.line(ts, rdp_record(ts, computer, acct, ip, 4624, 10, wks=wks, port=port))


def rdp_skipped(f, ts, computer, acct, ip, kind):
    """A Windows Security event Talos skips: wrong event id, or a non-RDP logon type (§3.2)."""
    if kind == "network_success":  # 4624 LogonType 3 -- network logon, not RDP
        f.line(ts, rdp_record(ts, computer, acct, ip, 4624, 3, wks="-"))
    elif kind == "network_fail":  # 4625 LogonType 3 -- network logon failure
        f.line(ts, rdp_record(ts, computer, acct, ip, 4625, 3, sub_status="0xC000006A", wks="-"))
    elif kind == "logoff":  # 4634 -- an account was logged off
        f.line(
            ts,
            json.dumps(
                {
                    "EventID": 4634,
                    "TimeCreated": iso_z(ts),
                    "Computer": computer,
                    "TargetUserName": acct,
                    "TargetDomainName": "GLOBEX",
                    "LogonType": 10,
                }
            ),
        )
    else:  # 4672 -- special privileges assigned
        f.line(
            ts,
            json.dumps(
                {
                    "EventID": 4672,
                    "TimeCreated": iso_z(ts),
                    "Computer": computer,
                    "SubjectUserName": acct,
                    "SubjectDomainName": "GLOBEX",
                }
            ),
        )


# --------------------------------------------------------------------------------------------
# nginx / WAF (web JSON) emitters
# --------------------------------------------------------------------------------------------


def nginx(f, ts, ip, host, method, uri, status, ua, rng, referer="-", body=None):
    rec = {
        "time_iso8601": iso_off(ts),
        "remote_addr": ip,
        "host": host,
        "request_method": method,
        "request_uri": uri,
        "status": status,
        "body_bytes_sent": rng.randint(120, 8200),
        "http_user_agent": ua,
        "http_referer": referer,
    }
    if body is not None:
        rec["request_body"] = body
    f.line(ts, json.dumps(rec))


def waf(f, ts, ip, host, method, uri, status, ua, *, action, rule_id="-", score=0):
    rec = {
        "timestamp": iso_off(ts),
        "client_ip": ip,
        "host": host,
        "method": method,
        "uri": uri,
        "status": status,
        "action": action,
        "rule_id": rule_id,
        "anomaly_score": score,
        "user_agent": ua,
    }
    f.line(ts, json.dumps(rec))


def login_post(f, ts, ip, host, account, status, ua, rng):
    """A POST to /login. 302 is a shop's successful login; 401 a rejected one (§3.3)."""
    nginx(
        f,
        ts,
        ip,
        host,
        "POST",
        "/login",
        status,
        ua,
        rng,
        referer=f"https://{host}.acme.example/login",
        body=f"username={account}&password=********",
    )


# --------------------------------------------------------------------------------------------
# Background traffic (§1.1.5) -- benign activity, separate source addresses and accounts,
# never enough on its own to meet a §4 rule. Verified by the background check in self-review.
# --------------------------------------------------------------------------------------------


def bg_ssh_hour(
    f, host, rng, day, start_h, valid_accounts, admin_net, bot_accounts, n_staff=5, n_bots=4
):
    """Staff key logins, one typo-then-success, and a little internet bot noise on an sshd host."""
    ports = Ports(rng)
    base = datetime(2026, day.month, day.day, start_h, 0, 0, tzinfo=UTC)
    # Staff log in with keys from the admin workstation range, sessions open and close.
    for i in range(n_staff):
        acct = valid_accounts[i % len(valid_accounts)]
        ip = f"{admin_net}.{rng.randint(5, 60)}"
        ts = base + timedelta(seconds=rng.randint(30, 3400))
        ssh_accept(f, ts, host, acct, ip, ports, method="publickey")
        ssh_housekeeping(f, ts + timedelta(seconds=rng.randint(40, 300)), host, ip, ports, acct)
    # One staff member mistypes a password once, then succeeds.
    acct = valid_accounts[0]
    ip = f"{admin_net}.{rng.randint(5, 60)}"
    ts = base + timedelta(seconds=rng.randint(200, 3000))
    ssh_fail_existing(f, ts, host, acct, ip, ports)
    ssh_accept(f, ts + timedelta(seconds=rng.randint(4, 20)), host, acct, ip, ports)
    # Internet bots: 2-3 attempts each against distinct non-existent accounts, distinct IPs.
    for b in range(n_bots):
        acct = bot_accounts[b % len(bot_accounts)]
        ip = f"{rng.choice(('198.51.100', '203.0.113'))}.{rng.randint(120, 240)}"
        ts = base + timedelta(seconds=rng.randint(60, 3500))
        for _ in range(rng.randint(2, 3)):
            ssh_fail_invalid(f, ts, host, acct, ip, ports)
            ts += timedelta(seconds=rng.randint(3, 25))


def bg_web_hour(f, host, rng, day, start_h, n_requests, customers):
    """Customer browsing: page views, search, add-to-cart, successful logins, a few typos."""
    base = datetime(2026, day.month, day.day, start_h, 0, 0, tzinfo=UTC)
    span = 3500
    for _ in range(n_requests):
        ip = f"192.0.2.{rng.randint(2, 250)}"
        ua = rng.choice(BROWSER_UAS)
        ts = base + timedelta(seconds=rng.randint(0, span))
        roll = rng.random()
        if roll < 0.55:
            nginx(f, ts, ip, host, "GET", rng.choice(PRODUCT_PATHS), 200, ua, rng)
        elif roll < 0.78:
            q = pct(rng.choice(SEARCH_PHRASES))
            nginx(f, ts, ip, host, "GET", f"/api/search?q={q}", 200, ua, rng)
        elif roll < 0.88:
            nginx(
                f,
                ts,
                ip,
                host,
                "POST",
                "/cart",
                200,
                ua,
                rng,
                body="sku=SKU-" + str(rng.randint(1000, 9999)) + "&qty=1",
            )
        else:
            acct = rng.choice(customers)
            login_post(f, ts, ip, host, acct, 302, ua, rng)
    # A dozen clean logins (302), and two customers who mistype once or twice then succeed.
    for _ in range(12):
        acct = rng.choice(customers)
        ip = f"192.0.2.{rng.randint(2, 250)}"
        ua = rng.choice(BROWSER_UAS)
        ts = base + timedelta(seconds=rng.randint(0, span))
        login_post(f, ts, ip, host, acct, 302, ua, rng)
    for typos in (1, 2):
        acct = rng.choice(customers)
        ip = f"192.0.2.{rng.randint(2, 250)}"
        ua = rng.choice(BROWSER_UAS)
        ts = base + timedelta(seconds=rng.randint(0, span))
        for _ in range(typos):
            login_post(f, ts, ip, host, acct, 401, ua, rng)
            ts += timedelta(seconds=rng.randint(5, 30))
        login_post(f, ts, ip, host, acct, 302, ua, rng)


def bg_rdp_hour(f, rng, day, start_h, hosts, staff, admin_net):
    """Staff RDP logons (type 10), one failed-then-successful, plus type-3 and other event ids
    that Talos must skip (§5 scenario 0 file 3)."""
    base = datetime(2026, day.month, day.day, start_h, 0, 0, tzinfo=UTC)
    for i in range(6):
        host = rng.choice(hosts)
        acct = staff[i % len(staff)]
        ip = f"{admin_net}.{rng.randint(5, 60)}"
        ts = base + timedelta(seconds=rng.randint(30, 3400))
        rdp_success(
            f, ts, host, acct, ip, wks=f"WS-{rng.randint(10, 99)}", port=rng.randint(50000, 60000)
        )
        rdp_skipped(f, ts + timedelta(seconds=rng.randint(60, 600)), host, acct, ip, "logoff")
    # One staff member fails once then succeeds.
    host = rng.choice(hosts)
    acct = staff[0]
    ip = f"{admin_net}.{rng.randint(5, 60)}"
    ts = base + timedelta(seconds=rng.randint(200, 3000))
    rdp_fail(f, ts, host, acct, ip)
    rdp_success(f, ts + timedelta(seconds=rng.randint(5, 25)), host, acct, ip)
    # Noise Talos skips: network logons (type 3) and other event ids.
    for _ in range(5):
        host = rng.choice(hosts)
        acct = staff[rng.randint(0, len(staff) - 1)]
        ip = f"10.20.{rng.randint(2, 8)}.{rng.randint(10, 200)}"
        ts = base + timedelta(seconds=rng.randint(30, 3400))
        rdp_skipped(f, ts, host, acct, ip, rng.choice(("network_success", "network_fail", "priv")))


# --------------------------------------------------------------------------------------------
# Account pools (§2)
# --------------------------------------------------------------------------------------------

ACME_STAFF_SSH = ("ops_admin", "k.mehta", "r.oyelaran")
GLOBEX_STAFF_SSH = ("netops", "l.ferreira")
GLOBEX_RDP_STAFF = ("l.ferreira", "helpdesk", "jsmith")
GLOBEX_RDP_HOSTS = (
    "globex-ws-001",
    "globex-ws-002",
    "globex-ws-003",
    "globex-ws-004",
    "globex-ws-005",
    "globex-ws-006",
)
# Non-existent accounts internet bots probe. Deliberately DISJOINT from every attack account in
# §5 (no admin/oracle/test/ubuntu/root/deploy/git/... here), so background never shares a
# host+account window with an attack (§1.1.5).
BOT_ACCTS = (
    "nagios",
    "zabbix",
    "tomcat",
    "hadoop",
    "db2inst1",
    "sinusbot",
    "teamspeak3",
    "www-data",
    "minecraft",
    "ftp",
    "pi",
    "ubnt",
)
CUSTOMERS = tuple(
    f"{name}@{dom}"
    for name, dom in (
        ("alice.turner", "mail.example"),
        ("ben.carter", "inbox.example"),
        ("chen.wei", "webmail.example"),
        ("dara.okoro", "post.example"),
        ("evan.ross", "mail.example"),
        ("farah.khan", "inbox.example"),
        ("gina.lopez", "webmail.example"),
        ("hiro.tanaka", "post.example"),
        ("ivy.nguyen", "mail.example"),
        ("jack.obrien", "inbox.example"),
    )
)

# The 18 customer accounts the credential run in scenario 1 replays, and the 6 it retries.
STUFFING_ACCOUNTS = tuple(
    f"{name}@{dom}"
    for name, dom in (
        ("m.alvarez", "mail.example"),
        ("t.walsh", "inbox.example"),
        ("s.petrov", "webmail.example"),
        ("n.haddad", "post.example"),
        ("o.lindqvist", "mail.example"),
        ("p.ramirez", "inbox.example"),
        ("q.adeyemi", "webmail.example"),
        ("r.fischer", "post.example"),
        ("u.ivanova", "mail.example"),
        ("v.santos", "inbox.example"),
        ("w.kowalski", "webmail.example"),
        ("x.dubois", "post.example"),
        ("y.nakamura", "mail.example"),
        ("z.rossi", "inbox.example"),
        ("a.hassan", "webmail.example"),
        ("b.novak", "post.example"),
        ("c.mwangi", "mail.example"),
        ("d.schulz", "inbox.example"),
    )
)

# The 16 Acme staff accounts the scheduled scanner checks (§5 scenario 2).
SCANNER_ACCOUNTS = tuple(
    f"{n}@acme.example"
    for n in (
        "ops_admin",
        "k.mehta",
        "r.oyelaran",
        "a.bianchi",
        "s.delacroix",
        "m.okafor",
        "j.park",
        "l.romano",
        "t.ibrahim",
        "e.sorensen",
        "f.costa",
        "h.nakamura",
        "g.pavlou",
        "i.volkov",
        "n.abebe",
        "p.lindgren",
    )
)


# --------------------------------------------------------------------------------------------
# Scenario builders
# --------------------------------------------------------------------------------------------


def scenario_0(rng):
    """Quiet morning (control): a normal hour at both orgs, nothing malicious. 2026-09-28."""
    day = datetime(2026, 9, 28, tzinfo=UTC)
    files = {}

    f = LogFile()
    bg_ssh_hour(
        f, "bastion-01", rng, day, 9, ACME_STAFF_SSH, "10.0.9", BOT_ACCTS, n_staff=6, n_bots=5
    )
    files["scenario_00_quiet_morning/acme_bastion-01_auth.log"] = f

    f = LogFile()
    bg_ssh_hour(
        f, "vpn-gw", rng, day, 9, GLOBEX_STAFF_SSH, "10.20.9", BOT_ACCTS, n_staff=5, n_bots=4
    )
    files["scenario_00_quiet_morning/globex_vpn-gw_auth.log"] = f

    f = LogFile()
    bg_rdp_hour(f, rng, day, 9, GLOBEX_RDP_HOSTS, GLOBEX_RDP_STAFF, "10.20.9")
    files["scenario_00_quiet_morning/globex_windows_security.jsonl"] = f

    f = LogFile()
    bg_web_hour(f, "web-01", rng, day, 9, 300, CUSTOMERS)
    files["scenario_00_quiet_morning/acme_web-01_access.jsonl"] = f

    return files


def scenario_1(rng):
    """Brute force that lands on bastion-01, then a credential run on the web shop. 2026-09-29."""
    day = datetime(2026, 9, 29, tzinfo=UTC)
    files = {}
    attacker = "203.0.113.7"

    # --- bastion-01: 12 failed svc_deploy guesses, then the 13th (Accepted) lands -----------
    f = LogFile()
    ports = Ports(rng)
    t = datetime(2026, 9, 29, 10, 2, 11, tzinfo=UTC)
    fail_times = []
    for _ in range(12):
        ssh_fail_existing(f, t, "bastion-01", "svc_deploy", attacker, ports)
        fail_times.append(t)
        t = t + timedelta(seconds=rng.randint(5, 9))
    accept_t = datetime(2026, 9, 29, 10, 3, 40, tzinfo=UTC)
    ssh_accept(f, accept_t, "bastion-01", "svc_deploy", attacker, ports)
    bg_ssh_hour(
        f, "bastion-01", rng, day, 10, ACME_STAFF_SSH, "10.0.9", BOT_ACCTS, n_staff=4, n_bots=3
    )
    files["scenario_01_brute_force_lands/acme_bastion-01_auth.log"] = f

    # --- app-02: the stolen key logs in once from bastion-01 --------------------------------
    f = LogFile()
    ports = Ports(rng)
    app_t = datetime(2026, 9, 29, 10, 5, 2, tzinfo=UTC)
    ssh_accept(f, app_t, "app-02", "svc_deploy", "10.0.1.10", ports, method="publickey")
    bg_ssh_hour(f, "app-02", rng, day, 10, ACME_STAFF_SSH, "10.0.9", BOT_ACCTS, n_staff=4, n_bots=3)
    files["scenario_01_brute_force_lands/acme_app-02_auth.log"] = f

    # --- web-01: a leaked list replayed against the login, all rejected ---------------------
    f = LogFile()
    # 18 distinct accounts once, then the attacker retries 6 of them: 24 failed POST /login 401.
    sequence = list(STUFFING_ACCOUNTS) + list(STUFFING_ACCOUNTS[:6])
    t = datetime(2026, 9, 29, 10, 9, 0, tzinfo=UTC)
    for acct in sequence:
        login_post(f, t, attacker, "web-01", acct, 401, STUFFING_UA, rng)
        t = t + timedelta(seconds=rng.randint(8, 11))
    bg_web_hour(f, "web-01", rng, day, 10, 120, CUSTOMERS)
    files["scenario_01_brute_force_lands/acme_web-01_access.jsonl"] = f

    return files


def scenario_2(rng):
    """The scheduled scanner: one weak-password check, repeated a week later. 2026-09-29 / 10-06."""
    files = {}
    scanner_ip = "10.0.5.20"  # pentest-01

    def run(day, start):
        f = LogFile()
        t = start
        for acct in SCANNER_ACCOUNTS:
            login_post(f, t, scanner_ip, "web-01", acct, 401, "acme-pentest-scanner/3.2", rng)
            t = t + timedelta(seconds=rng.randint(6, 9))
        bg_web_hour(f, "web-01", rng, day, 14, 90, CUSTOMERS)
        return f

    files["scenario_02_scheduled_scanner/run_a/acme_web-01_access.jsonl"] = run(
        datetime(2026, 9, 29, tzinfo=UTC), datetime(2026, 9, 29, 14, 0, 0, tzinfo=UTC)
    )
    files["scenario_02_scheduled_scanner/run_b/acme_web-01_access.jsonl"] = run(
        datetime(2026, 10, 6, tzinfo=UTC), datetime(2026, 10, 6, 14, 0, 0, tzinfo=UTC)
    )
    return files


# The SQLi probe sequence from §5 scenario 3, in order.
SQLI_PROBES = (
    "1'",
    "1' AND '1'='1",
    "1' AND '1'='2",
    "1' ORDER BY 3--",
    "1' UNION SELECT NULL,NULL--",
    "1' UNION SELECT username,password FROM users--",
)


def scenario_3(rng):
    """SQL injection probing /api/search, every malicious request blocked 403. 2026-09-30."""
    files = {}
    attacker = "198.51.100.23"
    host = "web-01"

    waf_f = LogFile()
    access_f = LogFile()

    # Two ordinary fingerprinting requests first (both 200, allowed): seen by the WAF and nginx.
    t = datetime(2026, 9, 30, 11, 20, 4, tzinfo=UTC)
    waf(waf_f, t, attacker, host, "GET", "/", 200, SQLMAP_UA, action="allowed")
    nginx(access_f, t, attacker, host, "GET", "/", 200, SQLMAP_UA, rng)
    t = t + timedelta(seconds=rng.randint(6, 12))
    waf(waf_f, t, attacker, host, "GET", "/api/search?q=shoes", 200, SQLMAP_UA, action="allowed")
    nginx(access_f, t, attacker, host, "GET", "/api/search?q=shoes", 200, SQLMAP_UA, rng)

    # The six probes: each blocked with 403, a CRS-style rule id and an anomaly score. Blocked
    # requests never reach nginx, so they appear only in the WAF file.
    rule_ids = ("942100", "942110", "942120", "942130", "942190", "942200")
    for i, payload in enumerate(SQLI_PROBES):
        t = t + timedelta(seconds=rng.randint(6, 12))
        uri = f"/api/search?q={pct(payload)}"
        waf(
            waf_f,
            t,
            attacker,
            host,
            "GET",
            uri,
            403,
            SQLMAP_UA,
            action="blocked",
            rule_id=rule_ids[i],
            score=rng.randint(15, 45),
        )

    # Normal customer traffic around the same period, including everyday words that look SQL-ish.
    bg_web_hour(access_f, host, rng, datetime(2026, 9, 30, tzinfo=UTC), 11, 110, CUSTOMERS)

    files["scenario_03_sqli_blocked/acme_web-01_waf.jsonl"] = waf_f
    files["scenario_03_sqli_blocked/acme_web-01_access.jsonl"] = access_f
    return files


def scenario_4(rng):
    """The same attacker tries admin on Globex's vpn-gw: 9 failures, then gives up. 2026-09-29."""
    files = {}
    attacker = "203.0.113.7"
    f = LogFile()
    ports = Ports(rng)
    t = datetime(2026, 9, 29, 16, 30, 0, tzinfo=UTC)
    for _ in range(9):
        ssh_fail_existing(f, t, "vpn-gw", "admin", attacker, ports)
        t = t + timedelta(seconds=rng.randint(5, 8))
    # Normal Globex activity around 16:15-16:45.
    bg_ssh_hour(
        f,
        "vpn-gw",
        rng,
        datetime(2026, 9, 29, tzinfo=UTC),
        16,
        GLOBEX_STAFF_SSH,
        "10.20.9",
        BOT_ACCTS,
        n_staff=5,
        n_bots=4,
    )
    files["scenario_04_second_organization/globex_vpn-gw_auth.log"] = f
    return files


# Scenario 5 bursts (§5 table). (org, host, protocol, account, source, failures, success, start)
S5_BURSTS = (
    (1, "acme", "acme-svc-001", "ssh", "deploy", "198.51.100.41", 9, False, (13, 0, 5)),
    (2, "acme", "acme-svc-002", "ssh", "root", "198.51.100.42", 10, False, (13, 1, 30)),
    (3, "acme", "acme-svc-003", "ssh", "ubuntu", "198.51.100.43", 8, True, (13, 2, 10)),
    (4, "acme", "acme-svc-004", "ssh", "git", "198.51.100.44", 12, False, (13, 4, 45)),
    (5, "acme", "acme-svc-005", "ssh", "jenkins", "198.51.100.45", 9, True, (13, 5, 0)),
    (6, "acme", "acme-edge-001", "ssh", "postfix", "198.51.100.46", 8, False, (13, 8, 20)),
    (7, "acme", "acme-store-001", "ssh", "backup", "198.51.100.47", 11, False, (13, 10, 0)),
    (8, "acme", "acme-edge-002", "ssh", "admin", "198.51.100.48", 10, True, (13, 12, 40)),
    (9, "acme", "acme-svc-001", "ssh", "oracle", "203.0.113.51", 8, False, (13, 15, 0)),
    (10, "acme", "acme-svc-002", "ssh", "test", "203.0.113.52", 9, False, (13, 15, 30)),
    (11, "acme", "acme-svc-005", "ssh", "ci_runner", "203.0.113.53", 13, False, (13, 20, 0)),
    (12, "acme", "acme-store-001", "ssh", "svc_backup", "203.0.113.54", 8, True, (13, 22, 15)),
    (13, "globex", "globex-ws-001", "rdp", "administrator", "198.51.100.61", 9, False, (13, 3, 0)),
    (14, "globex", "globex-ws-002", "rdp", "administrator", "198.51.100.62", 10, True, (13, 6, 10)),
    (15, "globex", "globex-ws-003", "rdp", "helpdesk", "198.51.100.63", 8, False, (13, 9, 0)),
    (16, "globex", "globex-ws-004", "rdp", "scanner", "198.51.100.64", 12, False, (13, 14, 20)),
    (17, "globex", "globex-ws-005", "rdp", "jsmith", "203.0.113.65", 9, False, (13, 18, 0)),
    (18, "globex", "globex-ws-006", "rdp", "backup_svc", "203.0.113.66", 8, True, (13, 25, 30)),
    (19, "globex", "gx-app-01", "ssh", "root", "198.51.100.67", 10, False, (13, 2, 40)),
    (20, "globex", "globex-svc-001", "ssh", "deploy", "198.51.100.68", 9, False, (13, 11, 10)),
    (21, "globex", "globex-svc-002", "ssh", "ubuntu", "198.51.100.69", 8, True, (13, 16, 45)),
    (22, "globex", "gx-app-01", "ssh", "postgres", "203.0.113.70", 11, False, (13, 30, 0)),
    (23, "globex", "globex-svc-001", "ssh", "admin", "203.0.113.71", 9, False, (13, 33, 20)),
    (24, "globex", "globex-svc-002", "ssh", "git", "203.0.113.72", 8, False, (13, 40, 0)),
)


def scenario_5(rng):
    """A busy hour: 24 opportunistic bursts across both orgs, 2026-10-01 13:00-13:55."""
    files = {}
    acme_f = LogFile()
    globex_ssh_f = LogFile()
    globex_win_f = LogFile()
    ssh_ports = Ports(rng)

    for _num, org, host, proto, acct, src, fails, success, (hh, mm, ss) in S5_BURSTS:
        t = datetime(2026, 10, 1, hh, mm, ss, tzinfo=UTC)
        last = t
        for _ in range(fails):
            if proto == "ssh":
                ssh_fail_existing(
                    acme_f if org == "acme" else globex_ssh_f, t, host, acct, src, ssh_ports
                )
            else:
                rdp_fail(
                    globex_win_f,
                    t,
                    host,
                    acct,
                    src,
                    wks=f"RDP-{rng.randint(10, 99)}",
                    port=rng.randint(50000, 60000),
                )
            last = t
            t = t + timedelta(seconds=rng.randint(4, 10))
        if success:
            st = last + timedelta(seconds=rng.randint(3, 10))
            if proto == "ssh":
                ssh_accept(
                    acme_f if org == "acme" else globex_ssh_f, st, host, acct, src, ssh_ports
                )
            else:
                rdp_success(
                    globex_win_f,
                    st,
                    host,
                    acct,
                    src,
                    wks=f"RDP-{rng.randint(10, 99)}",
                    port=rng.randint(50000, 60000),
                )

    # Normal staff activity in each collector file.
    day = datetime(2026, 10, 1, tzinfo=UTC)
    bg_ssh_hour(
        acme_f,
        "acme-svc-001",
        rng,
        day,
        13,
        ACME_STAFF_SSH,
        "10.0.9",
        BOT_ACCTS,
        n_staff=4,
        n_bots=2,
    )
    bg_ssh_hour(
        globex_ssh_f,
        "gx-app-01",
        rng,
        day,
        13,
        GLOBEX_STAFF_SSH,
        "10.20.9",
        BOT_ACCTS,
        n_staff=4,
        n_bots=2,
    )
    bg_rdp_hour(globex_win_f, rng, day, 13, GLOBEX_RDP_HOSTS, GLOBEX_RDP_STAFF, "10.20.9")

    files["scenario_05_busy_hour/acme_linux_auth.log"] = acme_f
    files["scenario_05_busy_hour/globex_linux_auth.log"] = globex_ssh_f
    files["scenario_05_busy_hour/globex_windows_security.jsonl"] = globex_win_f
    return files


def scenario_6(rng):
    """The account comes back: a week after scenario 1, a new address guesses svc_deploy's
    password on app-02, 8 failures in about a minute, no success. 2026-10-06.

    Nothing in Talos's report links it to scenario 1 (new IP, no success). What makes it
    matter is Argus's memory: svc_deploy was marked suspected compromised in scenario 1, so
    Triage raises the priority one step and cites that fact (G10). Expected from Talos: one
    network_brute_force incident, medium, attempt_count 8, at the 8th failure."""
    files = {}
    attacker = "198.51.100.77"
    f = LogFile()
    ports = Ports(rng)
    t = datetime(2026, 10, 6, 9, 41, 3, tzinfo=UTC)
    for _ in range(8):
        ssh_fail_existing(f, t, "app-02", "svc_deploy", attacker, ports)
        t = t + timedelta(seconds=rng.randint(5, 9))
    bg_ssh_hour(
        f,
        "app-02",
        rng,
        datetime(2026, 10, 6, tzinfo=UTC),
        9,
        ACME_STAFF_SSH,
        "10.0.9",
        BOT_ACCTS,
        n_staff=4,
        n_bots=3,
    )
    files["scenario_06_account_returns/acme_app-02_auth.log"] = f
    return files


# --------------------------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------------------------

# scenario_6 last: it draws from the random stream after the others, so 0-5 stay byte-identical.
BUILDERS = (scenario_0, scenario_1, scenario_2, scenario_3, scenario_4, scenario_5, scenario_6)


def build_all():
    """Build every scenario with one freshly-seeded RNG, so the whole run is deterministic."""
    rng = random.Random(SEED)
    files = {}
    for builder in BUILDERS:
        files.update(builder(rng))
    return files


def main():
    parser = argparse.ArgumentParser(description="Generate the Talos evaluation datasets.")
    parser.add_argument(
        "--out",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "scenarios"),
        help="directory to write scenario folders into (default: data/scenarios)",
    )
    args = parser.parse_args()

    files = build_all()
    for rel_path, log in sorted(files.items()):
        dest = os.path.join(args.out, rel_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(log.render())
    print(f"wrote {len(files)} log file(s) under {args.out}")


if __name__ == "__main__":
    main()
