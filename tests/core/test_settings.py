import pytest
from pydantic import ValidationError

from argus_soc.core.settings import Settings, get_settings


def test_defaults_match_lld():
    s = get_settings()
    assert (s.falkordb_host, s.falkordb_port) == ("falkordb", 6379)
    assert s.tenant_ids == ["acme", "globex"]
    assert s.argus_graph_backend == "falkordb"
    assert s.talos_url == "http://talos:8000"
    assert s.agent_claim_ttl_seconds == 120
    assert s.max_path_hops == 6
    assert s.llm_enabled is False
    assert s.deep_dive_active is False  # deep dive needs the LLM too
    assert s.api_port == 8080
    assert s.log_level == "INFO"
    assert s.agent_worker_id  # host name by default


def test_environment_overrides_defaults(monkeypatch):
    monkeypatch.setenv("FALKORDB_HOST", "localhost")
    monkeypatch.setenv("ARGUS_TENANTS", " acme , globex , test ")
    monkeypatch.setenv("ARGUS_GRAPH_BACKEND", "stub")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    s = Settings()
    assert s.falkordb_host == "localhost"
    assert s.tenant_ids == ["acme", "globex", "test"]
    assert s.argus_graph_backend == "stub"
    assert s.log_level == "DEBUG"


def test_dotenv_file_is_read(tmp_path):
    (tmp_path / ".env").write_text("FALKORDB_PORT=6380\nLLM_ENABLED=true\n")
    s = Settings()
    assert s.falkordb_port == 6380
    assert s.llm_enabled is True
    assert s.deep_dive_active is True


def test_get_settings_is_cached():
    assert get_settings() is get_settings()


@pytest.mark.parametrize(
    "name,value",
    [
        ("FALKORDB_PORT", "not-a-port"),
        ("FALKORDB_PORT", "70000"),
        ("ARGUS_GRAPH_BACKEND", "redis"),
        ("ARGUS_TENANTS", ""),
        ("ARGUS_TENANTS", "acme,Acme-Corp"),
        ("ARGUS_TENANTS", "acme,acme"),
        ("AGENT_CLAIM_TTL_SECONDS", "0"),
        ("LOG_LEVEL", "LOUD"),
    ],
)
def test_bad_values_fail_at_startup(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings()


def test_api_key_is_not_printed(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-very-secret")
    s = Settings()
    assert "sk-very-secret" not in repr(s)
    assert s.llm_api_key.get_secret_value() == "sk-very-secret"


def test_talos_url_per_tenant(monkeypatch):
    monkeypatch.setenv("TALOS_URL_GLOBEX", "http://talos-globex:8000")
    s = Settings()
    assert s.talos_url_for("globex") == "http://talos-globex:8000"
    assert s.talos_url_for("acme") == "http://talos:8000"
