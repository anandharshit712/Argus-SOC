import pytest

from argus_soc.core.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch, tmp_path):
    """Each test starts from the LLD defaults: no Argus env vars, no .env file."""
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    monkeypatch.chdir(tmp_path)  # so a developer's real .env is never read
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
