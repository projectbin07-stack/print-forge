"""Letter tiles and keychains: raised Hershey-font text on a rounded base plate.

The text outline (see :mod:`print_forge.text`) and the base are joined with
:func:`~print_forge.build.extrude_stepped`, so the letters and the plate are one closed solid.
The ``keychain`` style adds a tab with a keyring hole on the left.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .. import build, poly2d
from ..mesh import Mesh
from ..text import SUPPORTED, Outline, TextError, text_outline, unsupported
from ..validate import ERROR, NOTE, WARNING, Issue, PrintSettings, overhang_issues, wall_issue
from ..vec import Vec2
from .base import Family, ParamError, param


@dataclass
class LetterParams:
    text: str = param("A", "text to emboss (printable ASCII)")
    style: str = param("keychain", "base style", choices=("tile", "keychain"))
    cap_height: float = param(12.0, "height of capital letters", "mm", 3, 150)
    stroke: float = param(1.6, "stroke width of the letters", "mm", 0.3, 10)
    tracking: float = param(1.0, "extra space between letters", "mm", -5, 20)
    base_thickness: float = param(2.4, "base plate thickness", "mm", 0.6, 20)
    relief: float = param(1.2, "letter height above the base", "mm", 0.2, 20)
    padding: float = param(3.0, "base margin around the text", "mm", 0.5, 30)
    corner_radius: float = param(3.0, "base corner radius", "mm", 0, 30)
    hole: float = param(5.0, "keyring hole diameter (keychain)", "mm", 1, 20)
    ring_wall: float = param(2.5, "material around the keyring hole (keychain)", "mm", 0.4, 20)
    min_size: float = param(0.0, "make the base at least this wide and deep (tiles)", "mm", 0, 250)


PRESETS: dict[str, dict[str, object]] = {
    "keychain": {"text": "NAV", "style": "keychain"},
    "tile-a": {"text": "A", "style": "tile", "cap_height": 14, "min_size": 22},
    "tile-7": {"text": "7", "style": "tile", "cap_height": 14, "min_size": 22},
    "name-tag": {"text": "PLA 2026", "style": "keychain", "cap_height": 9, "stroke": 1.4},
}


@dataclass
class LetterLayout:
    outline: Outline
    base: list[Vec2]
    hole: list[Vec2] | None
    hole_centre: Vec2 | None


def letter_layout(p: LetterParams) -> LetterLayout:
    if not p.text or not p.text.strip():
        raise ParamError("text must not be empty")
    bad = unsupported(p.text)
    if bad:
        raise ParamError(
            f"unsupported character(s) {' '.join(repr(c) for c in bad)}; supported: {SUPPORTED!r}"
        )
    try:
        outline = text_outline(p.text, p.cap_height, p.stroke, p.tracking).centred()
    except TextError as exc:
        raise ParamError(str(exc)) from None
    w = outline.width + 2 * p.padding
    d = outline.height + 2 * p.padding
    w = max(w, p.min_size)
    d = max(d, p.min_size)
    if p.style == "tile":
        base = poly2d.rounded_rect(w, d, p.corner_radius, 8)
        return LetterLayout(outline, base, None, None)
    tab = p.hole + 2 * p.ring_wall
    d = max(d, tab)
    total = w + tab
    base = poly2d.translate2d(poly2d.rounded_rect(total, d, p.corner_radius, 8), -tab / 2, 0)
    hx = -w / 2 - tab / 2
    hole = poly2d.translate2d(poly2d.hole_circle(p.hole / 2, 48), hx, 0)
    return LetterLayout(outline, base, hole, (hx, 0.0))


def build_letter(p: LetterParams) -> Mesh:
    lay = letter_layout(p)
    base = [lay.base] + ([lay.hole] if lay.hole else [])
    z1 = p.base_thickness
    mesh = build.extrude_stepped(base, lay.outline.contours, 0.0, z1, z1 + p.relief, name="letter")
    return mesh


def check_letter(p: LetterParams, s: PrintSettings, mesh: Mesh) -> list[Issue]:
    issues: list[Issue] = []
    lay = letter_layout(p)
    issues += wall_issue("stroke width", p.stroke, s, "stroke")
    if p.base_thickness < 3 * s.layer_height:
        issues.append(Issue(WARNING, "base", f"base {p.base_thickness:g} mm is under three layers"))
    if p.relief < 2 * s.layer_height:
        issues.append(Issue(WARNING, "relief", f"relief {p.relief:g} mm is under two layers"))
    cs = lay.outline.contours
    # narrowest gap between separate outlines (inside counters, between letters)
    gap = math.inf
    for i in range(len(cs)):
        for j in range(i + 1, len(cs)):
            gap = min(gap, poly2d.ring_distance(cs[i], cs[j]))
    if gap < s.nozzle:
        issues.append(
            Issue(
                WARNING,
                "gap",
                f"narrowest gap in the text is {gap:.2f} mm, under the {s.nozzle:g} mm nozzle: "
                "it will fill in; increase tracking or cap height, or reduce stroke",
            )
        )
    margin = min(min(poly2d.min_edge_distance(pt, lay.base) for pt in c) for c in cs)
    if margin < s.nozzle:
        issues.append(Issue(ERROR, "margin", f"text is {margin:.2f} mm from the base edge"))
    if lay.hole is not None:
        issues += wall_issue("material around the keyring hole", p.ring_wall, s, "ring_wall")
        to_text = min(min(poly2d.min_edge_distance(pt, lay.hole) for pt in c) for c in cs)
        if to_text < s.nozzle:
            issues.append(Issue(ERROR, "hole", "keyring hole touches the text"))
    issues += overhang_issues(mesh, s, bridges_ok=False)
    if not any(i.severity in (ERROR, WARNING) for i in issues):
        issues.append(Issue(NOTE, "supportless", "flat base, vertical walls: no support needed"))
    return issues


def letter_notes(p: LetterParams) -> list[str]:
    return [
        "Raised letters are part of the same solid as the base. For two colours, add a filament "
        f"change (colour swap) at z = {p.base_thickness:g} mm in the slicer.",
        "Font: Hershey Roman Simplex (data and its distribution terms in font_data.py), "
        f"strokes thickened to {p.stroke:g} mm by print-forge.",
    ]


def letter_label(p: LetterParams) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in p.text) or "text"
    return f"{p.style}-{safe}"


FAMILY: Family[LetterParams] = Family(
    name="letter",
    summary="a letter tile or keychain with raised single-stroke text",
    params_type=LetterParams,
    presets=PRESETS,
    default_preset="keychain",
    build_fn=build_letter,
    check_fn=check_letter,
    notes_fn=letter_notes,
    label_fn=letter_label,
)
