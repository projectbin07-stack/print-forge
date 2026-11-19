"""Miniature vases: a smooth profile through a few control points, a circular, polygonal or wavy
cross-section, optional twist, and either a real wall (hollow vessel with a floor) or a solid body
meant for the slicer's spiral vase mode.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from .. import build, curves, poly2d
from ..mesh import Mesh
from ..validate import (
    ERROR,
    NOTE,
    WARNING,
    Issue,
    PrintSettings,
    overhang_issues,
    wall_issue,
)
from ..vec import Vec2, Vec3
from .base import Family, ParamError, param


@dataclass
class VaseParams:
    height: float = param(60.0, "overall height", "mm", 10, 250)
    profile: str = param(
        "0:18,0.4:24,0.8:14,1:17",
        "control points 'z:r,...' with z as a fraction of the height (0 to 1, increasing) "
        "and r the outer radius in mm",
    )
    curve: str = param(
        "catmull-rom", "curve through the control points", choices=("catmull-rom", "bezier")
    )
    section: str = param("circle", "cross-section shape", choices=("circle", "polygon", "wavy"))
    sides: int = param(6, "polygon sides or number of waves", "", 3, 24)
    wave_depth: float = param(0.08, "wave amplitude as a fraction of the radius", "", 0, 0.3)
    twist: float = param(0.0, "rotation of the top section relative to the base", "deg", -720, 720)
    vase_mode: bool = param(
        False, "solid body for slicer spiral vase mode instead of a modelled wall"
    )
    wall: float = param(1.6, "wall thickness (ignored in vase mode)", "mm", 0.2, 10)
    floor: float = param(1.6, "floor thickness (ignored in vase mode)", "mm", 0.4, 10)
    segments: int = param(96, "vertices around each section", "", 24, 360)
    rings: int = param(72, "sections along the height", "", 8, 400)


PRESETS: dict[str, dict[str, object]] = {
    "tulip": {"profile": "0:16,0.45:24,0.85:17,1:20", "height": 60},
    "hex-twist": {
        "profile": "0:20,0.5:23,1:18",
        "section": "polygon",
        "sides": 6,
        "twist": 60,
        "height": 70,
    },
    "wavy-bud": {
        "profile": "0:16,0.35:22,0.8:12,1:14",
        "section": "wavy",
        "sides": 9,
        "wave_depth": 0.1,
        "height": 55,
    },
    "spiral-vase-mode": {
        "profile": "0:22,0.5:30,1:24",
        "section": "polygon",
        "sides": 8,
        "twist": 90,
        "vase_mode": True,
        "height": 90,
    },
    "bezier-bottle": {
        "profile": "0:18,0.3:26,0.6:6,0.85:10,1:9",
        "curve": "bezier",
        "height": 80,
    },
}


def parse_profile(text: str) -> list[tuple[float, float]]:
    pts = []
    for chunk in text.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            z_txt, r_txt = chunk.split(":")
            pts.append((float(z_txt), float(r_txt)))
        except ValueError:
            raise ParamError(f"profile point {chunk!r} is not 'z:r'") from None
    if len(pts) < 2:
        raise ParamError("profile needs at least two control points")
    zs = [z for z, _ in pts]
    if zs[0] != 0 or zs[-1] != 1:
        raise ParamError("profile must start at z=0 and end at z=1")
    if any(b <= a for a, b in itertools.pairwise(zs)):
        raise ParamError("profile z values must increase")
    if any(r <= 0 for _, r in pts):
        raise ParamError("profile radii must be positive")
    return pts


def radii(p: VaseParams, zs: list[float]) -> list[float]:
    """Outer (circumscribed) radius at each height in ``zs`` (mm)."""
    ctrl: list[Vec2] = [(r, z * p.height) for z, r in parse_profile(p.profile)]
    curve = curves.bezier(ctrl, 256) if p.curve == "bezier" else curves.catmull_rom(ctrl, 48)
    try:
        return curves.resample_by_y(curve, zs)
    except ValueError as exc:
        raise ParamError(f"profile: {exc}") from None


def _shape(p: VaseParams, theta: float) -> float:
    if p.section == "polygon":
        step = 2 * math.pi / p.sides
        local = (theta % step) - step / 2
        return math.cos(step / 2) / math.cos(local)
    if p.section == "wavy":
        return 1.0 + p.wave_depth * math.cos(p.sides * theta)
    return 1.0


def _segments(p: VaseParams) -> int:
    if p.section == "polygon":
        return max(p.sides, round(p.segments / p.sides) * p.sides)
    return p.segments


def section(p: VaseParams, z: float, radius: float) -> list[Vec2]:
    n = _segments(p)
    tw = math.radians(p.twist) * z / p.height
    pts = []
    for j in range(n):
        th = 2 * math.pi * j / n
        r = radius * _shape(p, th)
        pts.append((r * math.cos(th + tw), r * math.sin(th + tw)))
    return pts


def _slope_factor(rs: list[float], zs: list[float], k: int) -> float:
    """1 / cos(wall slope): horizontal offset needed for a given normal wall thickness."""
    a, b = max(0, k - 1), min(len(rs) - 1, k + 1)
    dr = (rs[b] - rs[a]) / max(zs[b] - zs[a], 1e-9)
    return math.sqrt(1.0 + dr * dr)


def rings(p: VaseParams) -> tuple[list[list[Vec2]], list[float], list[list[Vec2]], list[float]]:
    """Outer sections and heights, and (unless vase mode) inner sections and heights."""
    zs = [p.height * k / p.rings for k in range(p.rings + 1)]
    rs = radii(p, zs)
    outer = [section(p, z, r) for z, r in zip(zs, rs, strict=True)]
    if p.vase_mode:
        return outer, zs, [], []
    zi = [p.floor + (p.height - p.floor) * k / p.rings for k in range(p.rings + 1)]
    ri = radii(p, zi)
    inner = []
    for k, (z, r) in enumerate(zip(zi, ri, strict=True)):
        sec = section(p, z, r)
        inner.append(poly2d.offset_ring(sec, p.wall * _slope_factor(ri, zi, k)))
    return outer, zs, inner, zi


def build_vase(p: VaseParams) -> Mesh:
    outer, zs, inner, zi = rings(p)
    o3: list[list[Vec3]] = [[(x, y, z) for x, y in ring] for ring, z in zip(outer, zs, strict=True)]
    if p.vase_mode:
        return build.loft(o3, name="vase")
    i3: list[list[Vec3]] = [[(x, y, z) for x, y in ring] for ring, z in zip(inner, zi, strict=True)]
    return build.vessel(o3, i3, name="vase")


def check_vase(p: VaseParams, s: PrintSettings, mesh: Mesh) -> list[Issue]:
    issues: list[Issue] = []
    outer, _zs, inner, _ = rings(p)
    min_r = min(min(math.hypot(x, y) for x, y in ring) for ring in outer)
    if not p.vase_mode:
        issues += wall_issue("wall", p.wall, s, "wall")
        if p.floor < 3 * s.layer_height:
            issues.append(Issue(WARNING, "floor", f"floor {p.floor:g} mm is under three layers"))
        for k, ring in enumerate(inner):
            if poly2d.signed_area(ring) <= 0 or not poly2d.is_simple(ring):
                issues.append(
                    Issue(
                        ERROR,
                        "wall",
                        f"the {p.wall:g} mm wall does not fit inside the section at "
                        f"z = {p.floor + (p.height - p.floor) * k / p.rings:.1f} mm "
                        "(too narrow or too sharp a corner)",
                    )
                )
                break
        top_opening = min(math.hypot(x, y) for x, y in inner[-1]) if inner else 0.0
        if inner and top_opening < 2.0:
            issues.append(
                Issue(WARNING, "opening", f"top opening is only {2 * top_opening:.1f} mm wide")
            )
    else:
        if min_r < 4 * s.nozzle:
            issues.append(
                Issue(ERROR, "neck", f"narrowest radius {min_r:.1f} mm is too small for vase mode")
            )
    base_r = min(math.hypot(x, y) for x, y in outer[0])
    if p.height > 4 * 2 * base_r:
        issues.append(
            Issue(
                WARNING,
                "stability",
                f"height {p.height:g} mm is over four times the base width "
                f"({2 * base_r:.1f} mm): it may wobble while printing",
            )
        )
    issues += overhang_issues(mesh, s, bridges_ok=False)
    if not issues or all(i.severity == NOTE for i in issues):
        issues.append(Issue(NOTE, "supportless", "prints without support in this orientation"))
    return issues


def vase_notes(p: VaseParams) -> list[str]:
    if p.vase_mode:
        return [
            "Solid body for spiral vase mode: enable the slicer's spiral vase option (Bambu "
            "Studio: Others > Spiral vase). The slicer prints the bottom layers solid, then one "
            "continuous outer wall, and leaves the top open; the modelled top face is not "
            "printed.",
            "Wall strength in vase mode comes from the line width: a wider line (for example "
            "0.6-0.8 mm with a 0.4 mm nozzle, if your profile allows it) gives a stiffer wall.",
        ]
    return [f"Hollow vessel with a {p.wall:g} mm wall and a {p.floor:g} mm floor; print normally."]


def vase_label(p: VaseParams) -> str:
    kind = "vasemode" if p.vase_mode else "vase"
    return f"{kind}-{p.section}-{p.height:g}mm"


FAMILY: Family[VaseParams] = Family(
    name="vase",
    summary="a miniature vase from a profile curve, with twist and polygonal or wavy sections",
    params_type=VaseParams,
    presets=PRESETS,
    default_preset="tulip",
    build_fn=build_vase,
    check_fn=check_vase,
    notes_fn=vase_notes,
    label_fn=vase_label,
)
