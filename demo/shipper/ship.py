"""Tail the demo targets' logs and feed Talos one event at a time.

Runs inside the pinned Talos image so it can use Talos's OWN parsers (WebLogParser,
NetworkLogParser) -- the same ones `talos replay` uses -- instead of re-implementing them and
drifting from the thing under test (DEMO_DESIGN §4; rule 7 covers Argus, and this is a Talos-side
feeder, not Argus: src/argus_soc/ never imports Talos).

Each watched file has a domain. Lines are parsed and POSTed to Talos `/events` in file order so
the windowed detectors stay correct. No batching -- demo volumes are tiny.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx
from talos.ingestion.parsers.network_log_parser import NetworkLogParser
from talos.ingestion.parsers.web_log_parser import WebLogParser

logging.basicConfig(level=logging.INFO, format="%(asctime)s shipper %(levelname)s %(message)s")
log = logging.getLogger("shipper")

TALOS_URL = os.environ.get("TALOS_URL", "http://talos:8000").rstrip("/")
POLL_SECONDS = float(os.environ.get("DEMO_SHIP_POLL", "1.0"))
WEB_LOG = os.environ.get("DEMO_WEB_LOG", "/var/log/web_shop/access.jsonl")
SSH_LOG = os.environ.get("DEMO_SSH_LOG", "/var/log/ssh_target/auth.log")


@dataclass
class Tailed:
    path: Path
    parser: object  # WebLogParser | NetworkLogParser
    offset: int = 0
    _buffer: str = field(default="", init=False)

    def read_new_lines(self) -> list[str]:
        if not self.path.is_file():
            return []
        size = self.path.stat().st_size
        if size < self.offset:  # rotated/truncated
            self.offset = 0
        with self.path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(self.offset)
            chunk = handle.read()
            self.offset = handle.tell()
        self._buffer += chunk
        *complete, self._buffer = self._buffer.split("\n")
        return complete


def ship(client: httpx.Client, tailed: Tailed) -> None:
    for raw in tailed.read_new_lines():
        if not raw.strip():
            continue
        event = tailed.parser.parse_line(raw)
        if event is None:
            continue
        resp = client.post(
            TALOS_URL + "/events",
            content=event.model_dump_json(),
            headers={"content-type": "application/json"},
        )
        if resp.status_code == 200:
            report = resp.json()
            log.info("incident %s: %s", report.get("incident_id"), report.get("summary"))
        elif resp.status_code != 204:
            log.warning("event rejected (%s)", resp.status_code)


def wait_for_talos(client: httpx.Client) -> None:
    for _ in range(60):
        try:
            if client.get(TALOS_URL + "/healthz").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    log.warning("Talos /healthz not ready; shipping anyway")


def main() -> None:
    year = datetime.now(UTC).year
    watched = [
        Tailed(Path(WEB_LOG), WebLogParser()),
        Tailed(Path(SSH_LOG), NetworkLogParser(default_year=year)),
    ]
    # Start at end of any existing content so a restart does not replay old lines.
    for t in watched:
        if t.path.is_file():
            t.offset = t.path.stat().st_size
    with httpx.Client(timeout=10.0) as client:
        wait_for_talos(client)
        log.info("shipping %s", ", ".join(str(t.path) for t in watched))
        while True:
            for t in watched:
                try:
                    ship(client, t)
                except Exception:  # noqa: BLE001 -- a demo feeder must not die on one bad line
                    log.exception("ship failed for %s", t.path)
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
