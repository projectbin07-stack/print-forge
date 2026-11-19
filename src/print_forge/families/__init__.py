"""Product families. ``FAMILIES`` maps the CLI name to the family object."""

from __future__ import annotations

from typing import Any

from . import bead, cap, letter, vase
from .base import Family, ParamError, Part

FAMILIES: dict[str, Family[Any]] = {
    "vase": vase.FAMILY,
    "bead": bead.FAMILY,
    "letter": letter.FAMILY,
    "cap": cap.FAMILY,
}

__all__ = ["FAMILIES", "Family", "ParamError", "Part"]
