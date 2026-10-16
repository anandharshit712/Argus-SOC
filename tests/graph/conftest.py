import os
from types import SimpleNamespace

import pytest

from argus_soc.core.settings import Settings, get_settings
from argus_soc.graph import falkor_client
from argus_soc.graph.graph_schema import AlertInput, DecisionInput, TechniqueInput

# Where the developer's FalkorDB is: `docker compose up -d falkordb` publishes it on
# 127.0.0.1:6379. Read once, before the per-test clean-up below removes the variables.
# 127.0.0.1, not "localhost": on Windows "localhost" tries IPv6 (::1) first, and the
# port is only published on IPv4, so every new connection waits about 2 s.
DB_HOST = os.environ.get("FALKORDB_HOST", "127.0.0.1")
DB_PORT = os.environ.get("FALKORDB_PORT", "6379")

# Tests only ever write to these throwaway graphs, never to tenant_acme or tenant_globex.
TEST_TENANTS = ("test", "test_b")


@pytest.fixture(autouse=True)
async def clean_settings(monkeypatch, tmp_path):
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    monkeypatch.chdir(tmp_path)  # never read a developer's real .env
    monkeypatch.setenv("FALKORDB_HOST", DB_HOST)
    monkeypatch.setenv("FALKORDB_PORT", DB_PORT)
    monkeypatch.setenv("ARGUS_TENANTS", ",".join(("acme", "globex", *TEST_TENANTS)))
    get_settings.cache_clear()
    yield
    await falkor_client.close()
    get_settings.cache_clear()


@pytest.fixture
async def live_db():
    """A reachable FalkorDB with empty test graphs; skips the test if none is running."""
    if not await falkor_client.ping():
        pytest.skip(
            f"FalkorDB not reachable on {DB_HOST}:{DB_PORT} (docker compose up -d falkordb)"
        )
    await _drop_test_graphs()
    yield
    await _drop_test_graphs()


async def _drop_test_graphs() -> None:
    db = falkor_client._db()
    existing = set(await db.list_graphs())
    for tenant in TEST_TENANTS:
        name = f"tenant_{tenant}"
        if name in existing:
            await db.select_graph(name).delete()


# --- Scenario 1 as the ingestor and agents will send it (real-database tests) ---
ATTACKER = "203.0.113.7"

BRUTE_FORCE = AlertInput(
    incident_id="inc-7f3a", domain="network", category="network_brute_force",
    severity="high", confidence=0.9, succeeded=True,
    summary="brute_force on bastion-01 against svc_deploy over 12 attempts -- succeeded",
    talos_created_at="2026-10-16T10:02:00+00:00", hosts=("bastion-01",),
    users=("svc_deploy",), source_ips=(ATTACKER,),
    techniques=(TechniqueInput(mitre_id="T1110", name="Brute Force", tactic="credential-access"),),
    evidence=("12 failed SSH logins, then success as svc_deploy",),
    recommended_actions=(f"block source IP {ATTACKER} at the perimeter",),
)  # fmt: skip

STUFFING = AlertInput(
    incident_id="inc-81c2", domain="web", category="auth_failure", severity="medium",
    confidence=0.76, succeeded=False,
    summary="credential_stuffing on /login over 18 accounts -- did not succeed",
    talos_created_at="2026-10-16T10:04:00+00:00", hosts=("app-02",), endpoints=("/login",),
    source_ips=(ATTACKER,), techniques=(TechniqueInput(mitre_id="T1110.004"),),
)  # fmt: skip

R1 = DecisionInput(
    rule_id="R1", actions=("isolate_top_host", "disable_accounts", "block_ips"),
    needs_approval=True, reason="succeeded + path to crown jewel",
    target_hosts=("bastion-01",), target_users=("svc_deploy",), target_iocs=(ATTACKER,),
    evidence={"ranking": [("bastion-01", 1.0)]},
)  # fmt: skip


@pytest.fixture
def s1() -> SimpleNamespace:
    """Scenario 1 inputs: the two Talos alerts and decision R1."""
    return SimpleNamespace(brute_force=BRUTE_FORCE, stuffing=STUFFING, attacker=ATTACKER, r1=R1)
