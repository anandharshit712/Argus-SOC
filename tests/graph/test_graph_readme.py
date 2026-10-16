"""src/argus_soc/graph/README.md must describe the code as it is (submission item)."""

import importlib
import re
from pathlib import Path

import pytest

from argus_soc.graph.graph_schema import Label, Rel
from argus_soc.graph.index_setup import INDEXES

README = Path(__file__).resolve().parents[2] / "src" / "argus_soc" / "graph" / "README.md"
TEXT = README.read_text(encoding="utf-8")
BLOCKS = re.findall(r"<!-- cypher: (\w+)\.(\w+) -->\n```cypher\n(.*?)\n```", TEXT, re.S)


def test_readme_shows_the_main_queries():
    shown = {name for _module, name, _cypher in BLOCKS}
    assert {"_BLAST_RADIUS", "_PATHS", "_BETWEENNESS", "_RECALL", "_LINKED", "_CLAIM"} <= shown


@pytest.mark.parametrize("module,name,cypher", BLOCKS, ids=[f"{m}.{n}" for m, n, _ in BLOCKS])
def test_cypher_in_readme_matches_the_code(module, name, cypher):
    code = getattr(importlib.import_module(f"argus_soc.graph.{module}"), name)
    assert cypher.strip() == code.strip(), f"README is out of date for {module}.{name}"


def test_every_label_relationship_and_index_is_documented():
    for label in Label:
        assert f"| `{label}` |" in TEXT, label
    for rel in Rel:
        assert f"-- {rel} -->" in TEXT, rel
    for label, prop in INDEXES:
        assert f"`{label}.{prop}`" in TEXT, (label, prop)
