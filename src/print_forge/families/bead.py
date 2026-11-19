"""Beads with a vertical through-hole sized for a cord: sphere, faceted, torus, barrel, twist.

The hole is modelled as a polygon whose *inscribed* circle has diameter ``cord + 2 *
clearance``, so the cord fits between the flats. With ``supportless`` on, the part of a rounded
shape that would overhang more than ``support_angle`` is replaced by a straight chamfer down to a
flat foot (the same idea as a teardrop hole), so the bead prints upright without support.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .. import build
from ..mesh import Mesh
from ..validate import ERROR, NOTE, WARNING, Issue, PrintSettings, overhang_issues, wall_issue
from ..vec import Vec2, Vec3
from .base import Family, ParamError, param


@dataclass
class BeadParams:
    shape: str = param(
        "sphere", "bead shape", choices=("sphere", "faceted", "torus", "barrel", "twist")
    )
    diameter: float = param(10.0, "outer diameter", "mm", 3, 60)
    height: float = param(10.0, "length along the hole (barrel and twist only)", "mm", 2, 60)
    cord: float = param(1.0, "cord or wire diameter", "mm", 0.2, 10)
    clearance: float = param(0.2, "gap between cord and hole on each side", "mm", 0, 2)
    tube: float = param(4.0, "torus tube diameter", "mm", 1, 30)
    end_ratio: float = param(0.7, "barrel end diameter / middle diameter", "", 0.3, 1)
    facets: int = param(8, "facets around (faceted and twist)", "", 3, 24)
    twist: float = param(90.0, "twist from bottom to top (twist shape)", "deg", -360, 360)
    wobble: float = param(0.0, "helix radius the twist section orbits on", "mm", 0, 5)
    supportless: bool = param(True, "chamfer the underside so it prints without support")
    support_angle: float = param(
        45.0, "chamfer angle from vertical when supportless", "deg", 20, 60
    )
    segments: int = param(48, "vertices around (smooth shapes)", "", 12, 256)


PRESETS: dict[str, dict[str, object]] = {
    "round-10": {"shape": "sphere", "diameter": 10},
    "round-10-cord-2": {"shape": "sphere", "diameter": 10, "cord": 2.0},
    "gem-12": {"shape": "faceted", "diameter": 12, "facets": 8},
    "donut-14": {"shape": "torus", "diameter": 14, "tube": 5, "cord": 2},
    "barrel-8x12": {"shape": "barrel", "diameter": 8, "height": 12},
    "twist-hex": {"shape": "twist", "diameter": 10, "height": 10, "facets": 6, "twist": 60},
}


def hole_radius(p: BeadParams) -> float:
    """Inscribed radius of the hole polygon (mm)."""
    return p.cord / 2 + p.clearance


def _n_around(p: BeadParams) -> int:
    return p.facets if p.shape == "faceted" else p.segments


def _vertex_radius(p: BeadParams) -> float:
    """Radius of the hole polygon's vertices for the inscribed radius above."""
    return hole_radius(p) / math.cos(math.pi / _n_around(p))


def foot_ratio(angle_deg: float) -> float:
    """Foot radius / circle radius after the supportless chamfer: (1 - sin a) / cos a."""
    a = math.radians(angle_deg)
    return (1 - math.sin(a)) / math.cos(a)


def _arc(rc: float, zc: float, rad: float, a0: float, a1: float, steps: int) -> list[Vec2]:
    return [
        (
            rc + rad * math.cos(a0 + (a1 - a0) * i / steps),
            zc + rad * math.sin(a0 + (a1 - a0) * i / steps),
        )
        for i in range(steps + 1)
    ]


def sphere_profile(p: BeadParams) -> list[Vec2]:
    big_r = p.diameter / 2
    rv = _vertex_radius(p)
    rows = max(2, p.facets // 2) if p.shape == "faceted" else max(8, p.segments // 2)
    a_top = math.acos(min(1.0, rv / big_r))
    zc = big_r
    if p.supportless:
        lim = math.radians(p.support_angle)
        foot = big_r * foot_ratio(p.support_angle)
        z_bot = 0.0
        if foot <= rv:
            raise ParamError(
                "bead too small for its hole with a supportless foot: make it larger, use a "
                "thinner cord or turn supportless off"
            )
        span = a_top + lim
        steps = max(2, round(rows * span / math.pi))
        arc = _arc(0.0, zc, big_r, -lim, a_top, steps)
        return [(rv, z_bot), (foot, z_bot), *arc[:-1], (rv, arc[-1][1])]
    a_bot = -a_top
    steps = max(2, rows)
    arc = _arc(0.0, zc, big_r, a_bot, a_top, steps)
    return [(rv, arc[0][1]), *arc[1:-1], (rv, arc[-1][1])]


def torus_profile(p: BeadParams) -> list[Vec2]:
    rt = p.tube / 2
    rc = p.diameter / 2 - rt
    zc = rt
    steps = max(12, p.segments // 2)
    if p.supportless:
        lim = math.radians(p.support_angle)
        half = rt * foot_ratio(p.support_angle)
        arc = _arc(rc, zc, rt, -lim, math.pi + lim, steps)
        return [(rc - half, 0.0), (rc + half, 0.0), *arc]
    return _arc(rc, zc, rt, -math.pi / 2, 1.5 * math.pi, steps)[:-1]


def barrel_profile(p: BeadParams) -> list[Vec2]:
    rm = p.diameter / 2
    re = rm * p.end_ratio
    h = p.height
    rv = _vertex_radius(p)
    steps = 16
    pts: list[Vec2] = [(rv, 0.0)]
    for i in range(steps + 1):
        z = h * i / steps
        u = (2 * z / h) - 1
        pts.append((re + (rm - re) * (1 - u * u), z))
    pts.append((rv, h))
    return pts


def twist_rings(p: BeadParams) -> tuple[list[list[Vec3]], list[list[Vec3]]]:
    """Outer rings (regular polygon section swept along a helix with a horizontal frame) and the
    matching hole rings, turned with the same twist so the end annuli stay untangled."""
    n_side = max(1, p.segments // p.facets)
    n = n_side * p.facets
    big_r = p.diameter / 2
    corners = [
        (big_r * math.cos(2 * math.pi * k / p.facets), big_r * math.sin(2 * math.pi * k / p.facets))
        for k in range(p.facets)
    ]
    sec: list[Vec2] = []
    for k in range(p.facets):
        a, b = corners[k], corners[(k + 1) % p.facets]
        for s in range(n_side):
            t = s / n_side
            sec.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    rings_n = max(8, round(abs(p.twist) / 5))
    if p.twist == 0:
        outer = [[(x, y, p.height * k / rings_n) for x, y in sec] for k in range(rings_n + 1)]
    else:
        turns = p.twist / 360
        # The section's centre follows a helix of radius `wobble` (0 = pure twist).
        outer = build.helix_rings(
            sec,
            p.wobble,
            p.height / turns,
            turns,
            max(1, round(rings_n / abs(turns))),
            "horizontal",
        )
    rv = hole_radius(p) / math.cos(math.pi / n)
    inner = []
    for ring in outer:
        z = ring[0][2]
        tw = math.radians(p.twist) * z / p.height
        inner.append(
            [
                (
                    rv * math.cos(2 * math.pi * j / n + tw),
                    rv * math.sin(2 * math.pi * j / n + tw),
                    z,
                )
                for j in range(n)
            ]
        )
    return outer, inner


def build_bead(p: BeadParams) -> Mesh:
    if p.shape in ("sphere", "faceted"):
        return build.revolve(sphere_profile(p), _n_around(p), name="bead")
    if p.shape == "torus":
        return build.revolve(torus_profile(p), p.segments, name="bead")
    if p.shape == "barrel":
        return build.revolve(barrel_profile(p), p.segments, name="bead")
    outer, inner = twist_rings(p)
    return build.tube(outer, inner, name="bead")


def min_wall(p: BeadParams) -> float:
    """Thinnest material between the hole and the outside (mm)."""
    rh = hole_radius(p)
    if p.shape in ("sphere", "faceted"):
        outer = p.diameter / 2 * (math.cos(math.pi / p.facets) if p.shape == "faceted" else 1.0)
        if p.supportless:
            outer = min(outer, p.diameter / 2 * foot_ratio(p.support_angle))
        return outer - rh
    if p.shape == "torus":
        return p.tube  # the cord passes through the open centre, not through material
    if p.shape == "barrel":
        return p.diameter / 2 * p.end_ratio - rh
    apothem = p.diameter / 2 * math.cos(math.pi / p.facets)
    return apothem - p.wobble - rh


def check_bead(p: BeadParams, s: PrintSettings, mesh: Mesh) -> list[Issue]:
    issues: list[Issue] = []
    rh = hole_radius(p)
    if p.shape == "torus":
        inner = p.diameter / 2 - p.tube
        if inner < rh:
            issues.append(
                Issue(
                    ERROR,
                    "hole",
                    f"torus opening {2 * inner:.2f} mm is smaller than the hole "
                    f"{2 * rh:.2f} mm (cord + clearance)",
                )
            )
        issues += wall_issue("tube", p.tube, s, "wall")
    else:
        issues += wall_issue("wall around the hole", min_wall(p), s, "wall")
    if 2 * rh < 2 * s.nozzle:
        issues.append(
            Issue(
                WARNING,
                "hole",
                f"hole diameter {2 * rh:.2f} mm is under two nozzle widths; small holes "
                "often close up, test-print one",
            )
        )
    if p.supportless and p.shape in ("sphere", "faceted", "torus"):
        foot_r = (p.diameter / 2 if p.shape != "torus" else p.tube / 2) * foot_ratio(
            p.support_angle
        )
        width = foot_r - rh if p.shape != "torus" else 2 * foot_r
        if width < 2 * s.nozzle:
            issues.append(
                Issue(WARNING, "foot", f"flat foot is only {width:.2f} mm wide: poor bed grip")
            )
        if p.support_angle > s.overhang_limit:
            issues.append(
                Issue(
                    WARNING,
                    "chamfer",
                    f"support_angle {p.support_angle:g} deg is steeper than the printer "
                    f"limit {s.overhang_limit:g} deg",
                )
            )
    issues += overhang_issues(mesh, s, bridges_ok=False)
    if not any(i.severity in (ERROR, WARNING) for i in issues):
        issues.append(Issue(NOTE, "supportless", "prints upright without support"))
    return issues


def bead_notes(p: BeadParams) -> list[str]:
    rh = hole_radius(p)
    notes = [
        f"Hole: {2 * rh:.2f} mm across the flats for a {p.cord:g} mm cord "
        f"({p.clearance:g} mm clearance per side). Holes in FDM prints usually come out a "
        "little small; test-print one bead and adjust the clearance."
    ]
    if p.supportless and p.shape in ("sphere", "faceted", "torus"):
        notes.append(
            f"Underside chamfered at {p.support_angle:g} deg to a flat foot so it prints "
            "without support."
        )
    return notes


def bead_label(p: BeadParams) -> str:
    return f"bead-{p.shape}-{p.diameter:g}mm"


FAMILY: Family[BeadParams] = Family(
    name="bead",
    summary="a bead with a cord hole: sphere, faceted, torus, barrel or twist",
    params_type=BeadParams,
    presets=PRESETS,
    default_preset="round-10",
    build_fn=build_bead,
    check_fn=check_bead,
    notes_fn=bead_notes,
    label_fn=bead_label,
)
