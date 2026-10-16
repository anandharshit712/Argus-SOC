import logging

import httpx
import pytest
from tests.ingestor.conftest import talos_reports

from argus_soc import graph
from argus_soc.ingestor import talos_client
from argus_soc.ingestor.ingest_loop import poll_once
from argus_soc.ingestor.talos_client import TalosClient, TalosError
from argus_soc.ingestor.tenant_resolver import load_inventories


def _talos(reports: list[dict]) -> TalosClient:
    """A TalosClient whose `GET /reports` answers with these reports."""
    return TalosClient(
        "http://talos:8000",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=reports)),
    )


async def test_new_reports_are_stored_in_their_tenants_graph():
    s1, s4 = talos_reports("s1"), talos_reports("s4")
    talos = _talos(s1 + talos_reports("s3") + s4)
    inventories, skipped = load_inventories(), set()

    assert await poll_once(talos, None, inventories, skipped) == 8
    acme = {a["incident_id"]: a for a in await graph.list_new_alerts("acme", limit=100)}
    assert {r["incident_id"] for r in s1} <= set(acme)
    assert acme[s1[0]["incident_id"]]["iocs"] == ["203.0.113.7"]
    globex = [a["incident_id"] for a in await graph.list_new_alerts("globex", limit=100)]
    assert s4[0]["incident_id"] in globex
    assert s1[0]["incident_id"] not in globex  # tenants never mix

    assert await poll_once(talos, None, inventories, skipped) == 0  # the graph is the record


async def test_report_with_unknown_host_is_dropped_and_logged_once(caplog):
    report = talos_reports("s1")[0] | {"incident_id": "inc-x"}
    report["aggregate_scope"] = report["aggregate_scope"] | {"affected_hosts": ["nowhere-01"]}
    talos, inventories, skipped = _talos([report]), load_inventories(), set()
    with caplog.at_level(logging.WARNING):
        assert await poll_once(talos, None, inventories, skipped) == 0
        assert await poll_once(talos, None, inventories, skipped) == 0
    assert sum("dropped report inc-x" in m for m in caplog.messages) == 1


async def test_bad_report_does_not_block_the_others():
    good, bad = talos_reports("s3")[0], talos_reports("s1")[0]
    del bad["domain"]
    assert await poll_once(_talos([bad, good]), None, load_inventories(), set()) == 1


async def test_per_tenant_talos_skips_host_lookup():
    report = talos_reports("s4")[0]  # vpn-gw is Globex's, but this Talos is Acme's
    assert await poll_once(_talos([report]), "acme", load_inventories(), set()) == 1
    assert report["incident_id"] in {a["incident_id"] for a in await graph.list_new_alerts("acme")}


async def test_client_retries_5xx_then_fails_fast_on_4xx(monkeypatch):
    async def no_sleep(_):
        pass

    monkeypatch.setattr(talos_client.asyncio, "sleep", no_sleep)
    answers = iter([httpx.Response(503), httpx.Response(200, json=[])])
    client = TalosClient("http://t", transport=httpx.MockTransport(lambda r: next(answers)))
    assert await client.list_reports(5) == []

    client = TalosClient("http://t", transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    with pytest.raises(TalosError, match="404"):
        await client.list_reports(5)

    client = TalosClient("http://t", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(TalosError, match="after 5 tries"):
        await client.list_reports(5)
