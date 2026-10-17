import pytest
from tests.ingestor.conftest import talos_reports

from argus_soc.ingestor.report_mapper import extract_source_ips, map_report

ATTACKER_IPS = {"s1": "203.0.113.7", "s2": "10.0.5.20", "s3": "198.51.100.23", "s4": "203.0.113.7"}


def test_ssh_brute_force_maps_to_alert():
    first, landed = talos_reports("s1")[:2]
    alert = map_report(first)
    assert alert.incident_id == first["incident_id"]
    assert (alert.category, alert.severity, alert.succeeded) == (
        "network_brute_force",
        "medium",
        False,
    )
    assert alert.hosts == ("bastion-01",)
    assert alert.users == ("svc_deploy",)
    assert alert.source_ips == ("203.0.113.7",)
    assert [t.mitre_id for t in alert.techniques] == ["T1110"]
    assert alert.talos_created_at == first["created_at"]
    assert map_report(landed).succeeded is True


@pytest.mark.parametrize("scenario", sorted(ATTACKER_IPS))
def test_every_saved_report_yields_its_attacker_ip(scenario):
    for report in talos_reports(scenario):
        assert map_report(report).source_ips == (ATTACKER_IPS[scenario],)


def test_busy_hour_reports_each_have_one_source_ip():
    assert all(len(map_report(r).source_ips) == 1 for r in talos_reports("s5"))


def test_sqli_keeps_endpoint_and_waf_line_as_data():
    alert = map_report(talos_reports("s3")[0])
    assert alert.endpoints == ("/api/search",)
    assert any('"status": 403' in line for line in alert.evidence)


def test_evidence_is_trimmed_to_contract_limits():
    report = talos_reports("s1")[0]
    report["verdicts"][0]["evidence"] = [{"detail": "x" * 600}] * 25
    alert = map_report(report)
    assert len(alert.evidence) == 20
    assert {len(line) for line in alert.evidence} == {500}


def test_extract_source_ips():
    texts = [
        "Failed password from 203.0.113.7 port 22",
        "again 203.0.113.7:4444 and 2001:db8::7 then 10.0.1.10",
        "at 10:02:11, version 1.2.3.4.5, bad 999.1.1.1",
    ]
    assert extract_source_ips(texts, own_ips=frozenset({"10.0.1.10"})) == [
        "203.0.113.7",
        "2001:db8::7",
    ]
