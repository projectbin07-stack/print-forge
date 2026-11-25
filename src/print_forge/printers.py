"""Build volumes of the supported printers (mm).

The figures come from ``print_registry.json``, the printer and material registry shared with
gcode-insight, printfarm-planner and stl-doctor. Each printer there carries the manufacturer pages
its published build volume was taken from.
"""

from __future__ import annotations

from dataclasses import dataclass

from .registry import load_registry


@dataclass(frozen=True)
class Printer:
    key: str
    name: str
    x: float
    y: float
    z: float

    def label(self) -> str:
        return f"{self.name} ({self.x:g} x {self.y:g} x {self.z:g} mm)"


PRINTERS: dict[str, Printer] = {
    p.key: Printer(p.key, p.full_name, *p.build_volume_mm) for p in load_registry().printers
}
DEFAULT_PRINTER = "p1s"


def printer_key(name: str) -> str:
    """Registry key for a key, model name or alias (``X1C`` -> ``x1c``); unknown names unchanged."""
    spec = load_registry().printer(name)
    return spec.key if spec is not None else name


def get_printer(key: str) -> Printer:
    try:
        return PRINTERS[printer_key(key)]
    except KeyError:
        raise ValueError(f"unknown printer {key!r}; choose one of {', '.join(PRINTERS)}") from None
