"""Clicker tops / keycap-style caps for MX-style switch stems.

The cap is one closed solid printed upright (open side down): a tapered outer shell with a flat,
cylindrical or spherical dish on top, a hollow cavity, and a round stem that runs from the bed up
to the cavity ceiling with a cross-shaped socket for the switch's stem. Optionally a raised legend
from the letter generator follows the dish.

Nominal stem numbers (mm), taken from the open-source KeyV2 OpenSCAD keycap library
(github.com/rsheldiii/KeyV2, ``src/functions.scad`` ``cherry_cross`` and ``src/settings.scad``),
not from a switch maker's datasheet:

* socket cross, horizontal slot 4.03 x 1.25, vertical slot 1.15 x 4.23
* KeyV2 adds a slop of 0.2 to the slot length and 0.2 / 3 to the slot widths by default
* round stem outside diameter 5.5, socket depth (``$stem_throw``) 4.0

Fit depends on the printer, filament, line width and slicer: print one cap and adjust the
clearances before printing a batch.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from .. import build, poly2d
from ..mesh import Mesh
from ..text import TextError, text_outline, unsupported
from ..validate import ERROR, NOTE, WARNING, Issue, PrintSettings, overhang_issues, wall_issue
from ..vec import Vec2
from .base import Family, ParamError, param

# KeyV2 nominal values, see module docstring
H_SLOT = (4.03, 1.25)
V_SLOT = (1.15, 4.23)


@dataclass
class CapParams:
    base_width: float = param(18.0, "outside width at the bottom", "mm", 8, 60)
    base_depth: float = param(18.0, "outside depth at the bottom", "mm", 8, 60)
    top_width: float = param(12.5, "outside width at the top", "mm", 5, 60)
    top_depth: float = param(14.0, "outside depth at the top", "mm", 5, 60)
    height: float = param(8.0, "height at the top edge", "mm", 5, 30)
    corner_radius: float = param(1.5, "corner radius at the bottom", "mm", 0.2, 10)
    top_corner_radius: float = param(2.5, "corner radius at the top", "mm", 0.2, 10)
    wall: float = param(1.2, "side wall thickness", "mm", 0.4, 5)
    top_thickness: float = param(1.6, "material under the deepest point of the dish", "mm", 0.6, 6)
    dish: str = param("spherical", "top surface", choices=("flat", "cylindrical", "spherical"))
    dish_depth: float = param(0.8, "depth of the dish at its centre", "mm", 0, 3)
    stem_diameter: float = param(5.5, "outside diameter of the round stem", "mm", 4, 8)
    socket_depth: float = param(4.0, "depth of the cross socket", "mm", 2, 8)
    length_clearance: float = param(0.2, "added to each slot length", "mm", -0.2, 0.6)
    width_clearance: float = param(0.07, "added to each slot width", "mm", -0.2, 0.4)
    legend: str = param("", "optional raised legend text")
    legend_height: float = param(5.0, "legend capital height", "mm", 2, 20)
    legend_stroke: float = param(0.9, "legend stroke width", "mm", 0.3, 3)
    legend_relief: float = param(0.6, "legend height above the dish", "mm", 0.2, 3)
    segments: int = param(48, "vertices around the stem", "", 16, 256)


PRESETS: dict[str, dict[str, object]] = {
    "spherical-1u": {"dish": "spherical", "height": 7.6, "top_width": 12.7, "top_depth": 12.7},
    "cylindrical-1u": {"dish": "cylindrical", "height": 8.5},
    "flat-clicker": {
        "dish": "flat",
        "dish_depth": 0,
        "top_width": 14,
        "top_depth": 14,
        "height": 7,
    },
    "legend-n": {"dish": "spherical", "legend": "N", "legend_height": 6},
}


def cross_slot(p: CapParams) -> list[Vec2]:
    """Counter-clockwise outline of the cross-shaped socket (with clearances)."""
    a = (H_SLOT[0] + p.length_clearance) / 2  # horizontal half-length
    b = (H_SLOT[1] + p.width_clearance) / 2  # horizontal half-width
    c = (V_SLOT[0] + p.width_clearance) / 2  # vertical half-width
    d = (V_SLOT[1] + p.length_clearance) / 2  # vertical half-length
    return [
        (a, -b), (a, b), (c, b), (c, d), (-c, d), (-c, b),
        (-a, b), (-a, -b), (-c, -b), (-c, -d), (c, -d), (c, -b),
    ]  # fmt: skip


def dish_fn(p: CapParams) -> Callable[[float, float], float]:
    hw, hd = p.top_width / 2, p.top_depth / 2
    depth = p.dish_depth if p.dish != "flat" else 0.0
    top = p.height

    def z(x: float, y: float) -> float:
        if p.dish == "cylindrical":
            return top - depth * max(0.0, 1.0 - (x / hw) ** 2)
        if p.dish == "spherical":
            return top - depth * max(0.0, 1.0 - (x / hw) ** 2 - (y / hd) ** 2)
        return top

    return z


def ceiling(p: CapParams) -> float:
    depth = p.dish_depth if p.dish != "flat" else 0.0
    return p.height - depth - p.top_thickness


def legend_contours(p: CapParams) -> list[list[Vec2]]:
    if not p.legend:
        return []
    bad = unsupported(p.legend)
    if bad:
        raise ParamError(f"legend has unsupported character(s): {' '.join(map(repr, bad))}")
    try:
        return text_outline(p.legend, p.legend_height, p.legend_stroke).centred().contours
    except TextError as exc:
        raise ParamError(str(exc)) from None


_CS, _ES = 6, 8  # corner and edge segments of every rounded rectangle (equal vertex counts)


def _rings(p: CapParams) -> tuple[list[Vec2], list[Vec2], int]:
    ob = poly2d.rounded_rect(p.base_width, p.base_depth, p.corner_radius, _CS, _ES)
    ot = poly2d.rounded_rect(p.top_width, p.top_depth, p.top_corner_radius, _CS, _ES)
    return ob, ot, len(ob)


def _inset(p: CapParams) -> float:
    """Horizontal inset that gives ``wall`` measured square to the sloped side."""
    slope = math.hypot((p.base_width - p.top_width) / 2, p.height) / p.height
    return p.wall * slope


def cavity_size(p: CapParams) -> tuple[float, float, float, float]:
    """Inner width and depth of the cavity at the bed and at the ceiling (mm)."""
    t = ceiling(p) / p.height
    inset = _inset(p)
    wc = p.base_width + (p.top_width - p.base_width) * t
    dc = p.base_depth + (p.top_depth - p.base_depth) * t
    return (
        p.base_width - 2 * inset,
        p.base_depth - 2 * inset,
        wc - 2 * inset,
        dc - 2 * inset,
    )


def cavity_rings(p: CapParams) -> tuple[list[Vec2], list[Vec2]]:
    wb, db, wc, dc = cavity_size(p)
    if min(wc, dc) <= p.stem_diameter + 0.4:
        raise ParamError("cavity is too small for the stem: thinner walls or a larger cap")
    t = ceiling(p) / p.height
    inset = _inset(p)
    rc = p.corner_radius + (p.top_corner_radius - p.corner_radius) * t
    ib = poly2d.rounded_rect(wb, db, max(p.corner_radius - inset, 0.2), _CS, _ES)
    ic = poly2d.rounded_rect(wc, dc, max(rc - inset, 0.2), _CS, _ES)
    return ib, ic


def build_cap(p: CapParams) -> Mesh:
    zf = dish_fn(p)
    zc = ceiling(p)
    if zc <= p.socket_depth:
        raise ParamError("cap is too low for the socket: raise height or reduce socket depth")
    ob, ot, _ = _rings(p)
    mesh = Mesh(name="cap")
    ob_i = mesh.add_vertices((x, y, 0.0) for x, y in ob)
    ot_i = mesh.add_vertices((x, y, zf(x, y)) for x, y in ot)
    build.wall(mesh, ob_i, ot_i)

    # inner cavity: rounded rectangles inset from the outer wall's sections at z = 0 and at the
    # ceiling (built directly rather than offset, so small corner radii cannot fold over)
    ib, ic = cavity_rings(p)
    ib_i = mesh.add_vertices((x, y, 0.0) for x, y in ib)
    ic_i = mesh.add_vertices((x, y, zc) for x, y in ic)
    build.wall(mesh, ic_i, ib_i)  # faces into the cavity
    n = len(ob_i)
    for j in range(n):  # rim on the bed
        k = (j + 1) % n
        mesh.add_quad(ob_i[k], ob_i[j], ib_i[j], ib_i[k])

    # stem with cross socket
    stem = poly2d.circle(p.stem_diameter / 2, p.segments)
    s_bot = mesh.add_vertices((x, y, 0.0) for x, y in stem)
    s_top = mesh.add_vertices((x, y, zc) for x, y in stem)
    build.wall(mesh, s_bot, s_top)
    cross = cross_slot(p)
    c_bot = mesh.add_vertices((x, y, 0.0) for x, y in cross)
    c_top = mesh.add_vertices((x, y, p.socket_depth) for x, y in cross)
    build.wall(mesh, c_top, c_bot)  # faces into the socket
    build.region_faces(mesh, [ic_i, s_top], up=False)  # cavity ceiling (bridged)
    build.region_faces(mesh, [s_bot, c_bot], up=False)  # stem end on the bed
    build.region_faces(mesh, [c_top], up=False)  # socket roof (bridged)

    # Top surface: concentric copies of the top outline, shrunk towards the centre and lifted
    # onto the dish, joined by quad strips (no slivers, follows the curvature). With a legend
    # the rings stop at the smallest copy that still clears the legend, and the region inside
    # is triangulated with the legend outlines as holes.
    legend = [
        poly2d.ccw(c) if d % 2 == 0 else poly2d.cw(c)
        for c, d in _with_depth([poly2d.densify(c, 1.0) for c in legend_contours(p)])
    ]
    s_min = _legend_scale(ot, legend, margin=0.8) if legend else 0.0
    step = 1.0 / max(p.top_width, p.top_depth) * 2  # about 1 mm between rings at the edge
    scales = []
    sc = 1.0 - step
    while sc > max(s_min, step * 0.5) + 1e-9:
        scales.append(sc)
        sc -= step
    if legend:
        scales.append(s_min)
    prev = ot_i
    for sc in scales:
        ring = mesh.add_vertices((x * sc, y * sc, zf(x * sc, y * sc)) for x, y in ot)
        for j in range(n):
            k = (j + 1) % n
            mesh.add_quad(prev[j], prev[k], ring[k], ring[j])
        prev = ring
    if legend:
        l_bot = [mesh.add_vertices((x, y, zf(x, y)) for x, y in c) for c in legend]
        l_top = [
            mesh.add_vertices((x, y, zf(x, y) + p.legend_relief) for x, y in c) for c in legend
        ]
        for lower, upper in zip(l_bot, l_top, strict=True):
            build.wall(mesh, lower, upper)
        build.region_faces(mesh, [prev, *l_bot], up=True)
        build.region_faces(mesh, l_top, up=True)
    else:
        apex = mesh.add_vertex((0.0, 0.0, zf(0.0, 0.0)))
        for j in range(n):
            mesh.add_face(prev[j], prev[(j + 1) % n], apex)
    return mesh


def _legend_scale(outline: list[Vec2], legend: list[list[Vec2]], margin: float) -> float:
    """Smallest scale of ``outline`` (about the origin) that contains the legend with margin."""
    pts = [pt for c in legend for pt in c]
    sc = 0.05
    while sc < 1.0:
        ring = [(x * sc, y * sc) for x, y in outline]
        if (
            all(poly2d.point_in_polygon(pt, ring) for pt in pts)
            and min(poly2d.min_edge_distance(pt, ring) for pt in pts) >= margin
        ):
            return sc
        sc += 0.02
    raise ParamError("legend does not fit on the top of the cap")


def _with_depth(contours: list[list[Vec2]]) -> list[tuple[list[Vec2], int]]:
    depth, _ = poly2d.nesting(contours)
    return list(zip(contours, depth, strict=True))


def stem_wall(p: CapParams) -> float:
    """Thinnest material between the socket's outer corners and the outside of the stem."""
    cross = cross_slot(p)
    return p.stem_diameter / 2 - max(math.hypot(x, y) for x, y in cross)


def check_cap(p: CapParams, s: PrintSettings, mesh: Mesh) -> list[Issue]:
    issues: list[Issue] = []
    issues += wall_issue("side wall", p.wall, s, "wall")
    issues += wall_issue("stem wall at the socket corners", stem_wall(p), s, "stem_wall")
    if p.top_thickness < 3 * s.layer_height:
        issues.append(Issue(WARNING, "top", f"top {p.top_thickness:g} mm is under three layers"))
    zc = ceiling(p)
    if zc - p.socket_depth < 3 * s.layer_height:
        issues.append(
            Issue(
                ERROR,
                "socket",
                f"only {zc - p.socket_depth:.2f} mm of stem above the socket",
            )
        )
    if p.top_width > p.base_width or p.top_depth > p.base_depth:
        issues.append(Issue(ERROR, "taper", "top is wider than the base: the sides overhang"))
    if p.legend:
        ot = poly2d.rounded_rect(p.top_width, p.top_depth, p.top_corner_radius, _CS, _ES)
        for c in legend_contours(p):
            if any(not poly2d.point_in_polygon(pt, ot) for pt in c):
                issues.append(Issue(ERROR, "legend", "legend is larger than the top"))
                break
            if min(poly2d.min_edge_distance(pt, ot) for pt in c) < s.nozzle:
                issues.append(Issue(WARNING, "legend", "legend almost touches the top edge"))
                break
    issues += overhang_issues(mesh, s, bridges_ok=True)
    issues.append(
        Issue(
            NOTE,
            "fit",
            "socket fit depends on printer and filament: test-print one cap on a switch first",
        )
    )
    return issues


def cap_notes(p: CapParams) -> list[str]:
    a = H_SLOT[0] + p.length_clearance
    return [
        "Print upright (open side on the bed). The cavity ceiling and the socket roof are "
        "bridges; the stem stands on the bed.",
        f"Socket: horizontal slot {a:.2f} x {H_SLOT[1] + p.width_clearance:.2f} mm, vertical "
        f"slot {V_SLOT[0] + p.width_clearance:.2f} x {V_SLOT[1] + p.length_clearance:.2f} mm, "
        f"{p.socket_depth:g} mm deep, in a {p.stem_diameter:g} mm stem (nominal values from "
        "the KeyV2 library plus the clearances). Fit must be test-printed.",
    ]


def cap_label(p: CapParams) -> str:
    leg = "-" + "".join(ch for ch in p.legend if ch.isalnum()) if p.legend else ""
    return f"cap-{p.dish}{leg}"


FAMILY: Family[CapParams] = Family(
    name="cap",
    summary="a clicker top / keycap-style cap for MX-style stems, optional legend",
    params_type=CapParams,
    presets=PRESETS,
    default_preset="spherical-1u",
    build_fn=build_cap,
    check_fn=check_cap,
    notes_fn=cap_notes,
    label_fn=cap_label,
)
