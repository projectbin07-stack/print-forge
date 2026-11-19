from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from print_forge.tomlread import TomlError, loads, loads_subset

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "parts.toml"

DOC = """
# comment
title = "batch # not a comment"
count = 1_000
ratio = 0.15
neg = -2
exp = 1e3
on = true
off = false
list = [1, 2.5, "three", 'four']
nested = { a = 1, b = { c = "x" }, d = [] }
empty = {}
quote = "say \\"hi\\"\\n\\u00e9"
dotted.key = 3

[plate]
printer = 'a1-mini'  # trailing comment

[[part]]
family = "bead"
[part.params]
cord = 1.5

[[part]]
family = "vase"
params = { height = 50 }
"""


def test_subset_matches_tomllib() -> None:
    lib = importlib.import_module("tomllib") if _has_tomllib() else None
    sub = loads_subset(DOC)
    assert sub["title"] == "batch # not a comment"
    assert sub["count"] == 1000
    assert sub["quote"] == 'say "hi"\né'
    assert sub["part"][0]["params"] == {"cord": 1.5}
    assert sub["dotted"] == {"key": 3}
    assert sub["nested"] == {"a": 1, "b": {"c": "x"}, "d": []}
    if lib is not None:
        assert sub == lib.loads(DOC)
        text = EXAMPLE.read_text(encoding="utf-8")
        assert loads_subset(text) == lib.loads(text)
    assert loads(DOC) == sub


def _has_tomllib() -> bool:
    try:
        importlib.import_module("tomllib")
    except ModuleNotFoundError:  # pragma: no cover - Python 3.10
        return False
    return True


@pytest.mark.parametrize(
    "bad",
    [
        "a = ",
        "a = 1\na = 2",
        "[x\n",
        "[[x]\n",
        "a = [1 2]",
        "a = {b = 1 c = 2}",
        "a = 'open",
        'a = "open',
        "a = nope",
        "just text",
        "a = 1 2",
        "bad key! = 1",
        'a = "\\q"',
        "[a]\nb = 1\n[a.b]\n",
        "a = {b 1}",
        "x = []\n[x.y]\n",
        "[[t]]\n[t.u]\nv=1\n[[t.u]]\n",
    ],
)
def test_subset_errors(bad: str) -> None:
    with pytest.raises(TomlError):
        loads_subset(bad)


def test_loads_wraps_tomllib_errors() -> None:
    with pytest.raises(TomlError):
        loads("a = ")
