"""The vendored registry loads, and print-forge's printers are exactly its build volumes."""

from __future__ import annotations

import pytest

from print_forge.cli import main
from print_forge.printers import PRINTERS, get_printer
from print_forge.registry import load_registry


def test_printers_come_from_the_registry() -> None:
    reg = load_registry()
    assert list(PRINTERS) == [p.key for p in reg.printers]
    for spec in reg.printers:
        printer = PRINTERS[spec.key]
        assert (printer.x, printer.y, printer.z) == spec.build_volume_mm
        assert printer.name == spec.full_name
        assert spec.sources


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("x1c", "x1c"),
        ("X1C", "x1c"),
        ("Bambu Lab X1 Carbon", "x1c"),
        ("P1P", "p1p"),
        ("A1 mini", "a1-mini"),
    ],
)
def test_get_printer_accepts_registry_names(name: str, key: str) -> None:
    assert get_printer(name).key == key


def test_unknown_printer() -> None:
    with pytest.raises(ValueError, match="unknown printer 'ender-3'"):
        get_printer("ender-3")


def test_cli_accepts_registry_aliases(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["bead", "--list-presets", "--printer", "X1C"]) == 0
    capsys.readouterr()
