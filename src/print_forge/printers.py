"""Build volumes of the supported printers (manufacturers' published sizes, mm)."""

from __future__ import annotations

from dataclasses import dataclass


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
    "p1s": Printer("p1s", "Bambu Lab P1S", 256, 256, 256),
    "a1": Printer("a1", "Bambu Lab A1", 256, 256, 256),
    "a1-mini": Printer("a1-mini", "Bambu Lab A1 mini", 180, 180, 180),
}
DEFAULT_PRINTER = "p1s"


def get_printer(key: str) -> Printer:
    try:
        return PRINTERS[key.lower()]
    except KeyError:
        raise ValueError(f"unknown printer {key!r}; choose one of {', '.join(PRINTERS)}") from None
