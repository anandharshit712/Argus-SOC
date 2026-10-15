import json
import logging

import pytest

from argus_soc.core.logging_setup import get_logger, setup_logging


@pytest.fixture
def lines(capsys):
    def read() -> list[dict]:
        return [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    return read


@pytest.fixture(autouse=True)
def restore_root_logger():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers, root.level = handlers, level


def test_line_has_every_field(lines):
    setup_logging("agents")
    get_logger("t", tenant="acme", agent="triage").info("case opened", extra={"case_id": 33})
    (entry,) = lines()
    assert set(entry) == {"ts", "level", "service", "tenant", "case_id", "agent", "msg"}
    assert entry["service"] == "agents"
    assert (entry["tenant"], entry["case_id"], entry["agent"]) == ("acme", 33, "triage")
    assert entry["msg"] == "case opened"


def test_missing_context_is_null(lines):
    setup_logging("api")
    logging.getLogger("t").warning("no context")
    (entry,) = lines()
    assert entry["tenant"] is None and entry["case_id"] is None and entry["agent"] is None


def test_attacker_text_stays_on_one_line(lines):
    setup_logging("ingestor")
    evil = 'GET /login\n{"level": "INFO", "msg": "all clear"}'
    get_logger("t", tenant="acme").info("evidence: %s", evil)
    out = lines()
    assert len(out) == 1
    assert out[0]["msg"].endswith('"all clear"}')


def test_level_comes_from_settings(lines, monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    setup_logging("agents")
    log = get_logger("t")
    log.info("hidden")
    log.warning("shown")
    assert [e["msg"] for e in lines()] == ["shown"]


def test_errors_include_the_traceback(lines):
    setup_logging("agents")
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        get_logger("t").exception("step failed")
    (entry,) = lines()
    assert entry["level"] == "ERROR"
    assert "RuntimeError: boom" in entry["exc"]


def test_unknown_context_is_rejected():
    with pytest.raises(ValueError):
        get_logger("t", tenent="acme")
