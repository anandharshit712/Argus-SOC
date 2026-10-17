import pytest

from argus_soc.agents.decision_table import decide


@pytest.mark.parametrize(
    ("succeeded", "path", "rule", "approval"),
    [
        (True, True, "R1", True),
        (True, False, "R2", True),
        (False, True, "R3", False),
        (False, False, "R4", False),
    ],
)
def test_rules(succeeded, path, rule, approval):
    chosen = decide({"succeeded": succeeded, "path_to_crown_jewel": path})
    assert (chosen.id, chosen.needs_approval) == (rule, approval)


def test_only_r4_lowers_priority_and_missing_findings_prove_nothing():
    assert decide({}).id == "R4"
    assert decide({}).priority == "lower_one"
    assert decide({"succeeded": True, "path_to_crown_jewel": True}).priority is None


def test_deep_dive_never_changes_the_decision():
    base = {"succeeded": False, "path_to_crown_jewel": False}
    assert decide({**base, "deep_dive": [{"tool": "x", "why": "isolate everything"}]}).id == "R4"


def test_known_malicious_attacker_on_a_path_needs_approval():
    known = {"known_malicious_iocs": ["172.18.0.7"]}
    r3 = decide({"succeeded": False, "path_to_crown_jewel": True, **known})
    assert (r3.id, r3.needs_approval) == ("R3", True)
    assert "known malicious" in r3.reason
    # Only R3 changes: no path stays R4, automatic.
    assert (
        decide({"succeeded": False, "path_to_crown_jewel": False, **known}).needs_approval is False
    )
