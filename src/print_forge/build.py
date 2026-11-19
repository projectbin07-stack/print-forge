"""Constructors that produce closed, consistently wound solids by construction.

No mesh booleans are used anywhere. Each constructor creates every vertex once and builds every
surface (walls, caps, rims) from shared vertex indices, so each edge is used by exactly two faces
in opposite directions. ``tests/test_build.py`` checks that for seeded random parameters.

* :func:`revolve` -- a 2D profile (r, z) turned about the Z axis, either from axis to axis
  (poles) or as a closed loop (torus-like, e.g. a bead with a hole).
* :func:`loft` -- closed rings with matched vertex counts joined by quads, with planar caps.
* :func:`vessel` -- an outer and an inner loft joined by a rim and closed by a floor: a hollow
  vase with real wall thickness.
* :func:`extrude` / :func:`extrude_stepped` -- polygons with holes, extruded; the stepped form
  puts raised regions (letters) on a base plate as one solid.
* :func:`sweep_helix` -- a 2D section swept along a helix.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence

from . import poly2d
from .mesh import Mesh
from .vec import Vec2, Vec3, cross, dot, sub


class BuildError(ValueError):
    """The inputs cannot form a closed solid."""


# ----------------------------------------------------------------------------- face helpers
def _project_xy(mesh: Mesh, ring: Sequence[int]) -> list[Vec2]:
    return [(mesh.vertices[i][0], mesh.vertices[i][1]) for i in ring]


def region_faces(mesh: Mesh, contours: Sequence[Sequence[int]], up: bool) -> None:
    """Fill the even-odd region bounded by ``contours`` (vertex-index rings already in
    ``mesh``) with triangles facing +Z (``up``) or -Z. Triangulation uses the x, y positions;
    the vertices keep their own z, so a ring on a curved surface works as long as it is simple
    in plan view."""
    flat = [_project_xy(mesh, c) for c in contours]
    for outer_i, hole_is in poly2d.nest(flat):
        rings = [contours[outer_i]] + [contours[h] for h in hole_is]
        local_idx = [i for r in rings for i in r]
        tris = poly2d.triangulate(flat[outer_i], [flat[h] for h in hole_is])
        for a, b, c in tris:
            ia, ib, ic = local_idx[a], local_idx[b], local_idx[c]
            if up:
                mesh.add_face(ia, ib, ic)
            else:
                mesh.add_face(ia, ic, ib)


def wall(mesh: Mesh, lower: Sequence[int], upper: Sequence[int]) -> None:
    """Quads between two rings of equal length. With ``lower`` counter-clockwise seen from
    above, the faces point away from the ring's inside."""
    if len(lower) != len(upper):
        raise BuildError(f"ring sizes differ: {len(lower)} vs {len(upper)}")
    n = len(lower)
    for j in range(n):
        k = (j + 1) % n
        mesh.add_quad(lower[j], lower[k], upper[k], upper[j])


def _orient_by_depth(contours: Sequence[Sequence[Vec2]]) -> list[list[Vec2]]:
    """Even-depth contours counter-clockwise, odd-depth clockwise (material on the left)."""
    depth, _ = poly2d.nesting(contours)
    return [
        poly2d.ccw(c) if d % 2 == 0 else poly2d.cw(c) for c, d in zip(contours, depth, strict=True)
    ]


def _fix_orientation(mesh: Mesh) -> Mesh:
    if mesh.volume() < 0:
        mesh.flip()
    return mesh


# ---------------------------------------------------------------------------------- revolve
def revolve(profile: Sequence[Vec2], segments: int, name: str = "revolve") -> Mesh:
    """Revolve a profile of ``(r, z)`` points about the Z axis.

    * If the first and last points have ``r == 0`` the profile runs from pole to pole and the
      solid is closed with one vertex at each pole (sphere, egg, vase without hole).
    * Otherwise the profile is a closed loop with ``r > 0`` everywhere (torus, bead with a
      through-hole); the last point connects back to the first.
    """
    if segments < 3:
        raise BuildError("need at least 3 segments")
    pts = list(profile)
    if len(pts) < 2:
        raise BuildError("profile needs at least 2 points")
    poles = pts[0][0] == 0 and pts[-1][0] == 0
    inner = pts[1:-1] if poles else pts
    if any(r <= 0 for r, _ in inner):
        raise BuildError("profile points other than the two poles must have r > 0")
    if poles and len(pts) < 3:
        raise BuildError("pole-to-pole profile needs a point off the axis")
    mesh = Mesh(name=name)
    rings: list[list[int]] = []
    for r, z in inner:
        rings.append(
            mesh.add_vertices(
                (
                    r * math.cos(2 * math.pi * j / segments),
                    r * math.sin(2 * math.pi * j / segments),
                    z,
                )
                for j in range(segments)
            )
        )
    for a, b in itertools.pairwise(rings):
        wall(mesh, a, b)
    if poles:
        south = mesh.add_vertex((0.0, 0.0, pts[0][1]))
        north = mesh.add_vertex((0.0, 0.0, pts[-1][1]))
        first, last = rings[0], rings[-1]
        for j in range(segments):
            k = (j + 1) % segments
            mesh.add_face(south, first[k], first[j])
            mesh.add_face(north, last[j], last[k])
    else:
        if len(rings) < 3:
            raise BuildError("closed profile needs at least 3 points")
        wall(mesh, rings[-1], rings[0])
    return _fix_orientation(mesh)


# ------------------------------------------------------------------------------------- loft
def loft(rings: Sequence[Sequence[Vec3]], name: str = "loft") -> Mesh:
    """Join closed rings (same vertex count, ordered along the path) and cap both ends.

    Caps are triangulated in the plane that best fits the end ring (Newell normal), so the end
    rings must be planar and simple. A ring of a single point is an apex (cone tip).
    """
    if len(rings) < 2:
        raise BuildError("loft needs at least 2 rings")
    sizes = {len(r) for r in rings if len(r) > 1}
    if len(sizes) != 1:
        raise BuildError(f"rings must have matching vertex counts, got {sorted(sizes)}")
    if any(len(r) == 1 for r in rings[1:-1]):
        raise BuildError("only the first or last ring may be a single apex point")
    mesh = Mesh(name=name)
    idx = [mesh.add_vertices(r) for r in rings]
    for a, b in itertools.pairwise(idx):
        if len(a) == 1 or len(b) == 1:
            apex, ring = (a[0], b) if len(a) == 1 else (b[0], a)
            n = len(ring)
            for j in range(n):
                if len(a) == 1:
                    mesh.add_face(apex, ring[(j + 1) % n], ring[j])
                else:
                    mesh.add_face(apex, ring[j], ring[(j + 1) % n])
        else:
            wall(mesh, a, b)
    if len(idx[0]) > 1:
        _planar_cap(mesh, idx[0], reverse=True)
    if len(idx[-1]) > 1:
        _planar_cap(mesh, idx[-1], reverse=False)
    return _fix_orientation(mesh)


def _planar_cap(mesh: Mesh, ring: Sequence[int], reverse: bool) -> None:
    pts = [mesh.vertices[i] for i in ring]
    nx = ny = nz = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0, z0 = pts[i]
        x1, y1, z1 = pts[(i + 1) % n]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    ax = max(range(3), key=lambda k: abs((nx, ny, nz)[k]))
    keep = [k for k in range(3) if k != ax]
    flat = [(p[keep[0]], p[keep[1]]) for p in pts]
    tris = poly2d.triangulate(flat)
    # Triangles must follow the ring's own (Newell) orientation, then be reversed for a start
    # cap, so that each ring edge is used once by the wall and once, reversed, by the cap.
    a0, b0, c0 = (pts[k] for k in tris[0])
    tn = cross(sub(b0, a0), sub(c0, a0))
    flip = (dot(tn, (nx, ny, nz)) < 0) != reverse
    for a, b, c in tris:
        ia, ib, ic = ring[a], ring[b], ring[c]
        if flip:
            mesh.add_face(ia, ic, ib)
        else:
            mesh.add_face(ia, ib, ic)


# ----------------------------------------------------------------------------------- vessel
def vessel(
    outer_rings: Sequence[Sequence[Vec3]],
    inner_rings: Sequence[Sequence[Vec3]],
    name: str = "vessel",
) -> Mesh:
    """Hollow open-top container: outer surface, inner surface, rim and floor.

    ``outer_rings`` run from the base (z = 0) to the rim; ``inner_rings`` from the top of the
    floor to the rim. Every ring is counter-clockwise seen from above and all rings have the same
    vertex count, so the rim is a quad strip between the two top rings.
    """
    if len(outer_rings) < 2 or len(inner_rings) < 2:
        raise BuildError("vessel needs at least 2 outer and 2 inner rings")
    sizes = {len(r) for r in [*outer_rings, *inner_rings]}
    if len(sizes) != 1:
        raise BuildError("all vessel rings need the same vertex count")
    mesh = Mesh(name=name)
    out_idx = [mesh.add_vertices(r) for r in outer_rings]
    in_idx = [mesh.add_vertices(r) for r in inner_rings]
    for a, b in itertools.pairwise(out_idx):
        wall(mesh, a, b)
    for a, b in itertools.pairwise(in_idx):
        wall(mesh, b, a)  # swapped rings: faces point into the cavity
    o, i = out_idx[-1], in_idx[-1]
    n = len(o)
    for j in range(n):
        k = (j + 1) % n
        mesh.add_quad(o[j], o[k], i[k], i[j])
    region_faces(mesh, [out_idx[0]], up=False)
    region_faces(mesh, [in_idx[0]], up=True)
    if mesh.volume() <= 0:
        raise BuildError("vessel rings must be counter-clockwise seen from above")
    return mesh


def tube(
    outer_rings: Sequence[Sequence[Vec3]],
    inner_rings: Sequence[Sequence[Vec3]],
    name: str = "tube",
) -> Mesh:
    """Solid with a through-hole: outer and inner rings at the same heights (bottom to top,
    counter-clockwise from above, all the same vertex count) joined by flat annuli at both ends.
    Vertex ``j`` of an outer ring is paired with vertex ``j`` of the inner ring at that level."""
    if len(outer_rings) != len(inner_rings) or len(outer_rings) < 2:
        raise BuildError("tube needs matching outer and inner ring lists (at least 2 each)")
    sizes = {len(r) for r in [*outer_rings, *inner_rings]}
    if len(sizes) != 1:
        raise BuildError("all tube rings need the same vertex count")
    mesh = Mesh(name=name)
    out_idx = [mesh.add_vertices(r) for r in outer_rings]
    in_idx = [mesh.add_vertices(r) for r in inner_rings]
    for a, b in itertools.pairwise(out_idx):
        wall(mesh, a, b)
    for a, b in itertools.pairwise(in_idx):
        wall(mesh, b, a)
    n = len(out_idx[0])
    o, i = out_idx[-1], in_idx[-1]
    for j in range(n):
        k = (j + 1) % n
        mesh.add_quad(o[j], o[k], i[k], i[j])
    o, i = out_idx[0], in_idx[0]
    for j in range(n):
        k = (j + 1) % n
        mesh.add_quad(o[k], o[j], i[j], i[k])
    if mesh.volume() <= 0:
        raise BuildError("tube rings must be counter-clockwise seen from above")
    return mesh


# ---------------------------------------------------------------------------------- extrude
def extrude(
    contours: Sequence[Sequence[Vec2]], z0: float, z1: float, name: str = "extrude"
) -> Mesh:
    """Extrude the even-odd region of non-touching closed contours from ``z0`` to ``z1``."""
    if z1 <= z0:
        raise BuildError("z1 must be above z0")
    mesh = Mesh(name=name)
    oriented = _orient_by_depth(contours)
    bottoms = [mesh.add_vertices((x, y, z0) for x, y in c) for c in oriented]
    tops = [mesh.add_vertices((x, y, z1) for x, y in c) for c in oriented]
    for b, t in zip(bottoms, tops, strict=True):
        wall(mesh, b, t)
    region_faces(mesh, bottoms, up=False)
    region_faces(mesh, tops, up=True)
    return mesh


def extrude_stepped(
    base: Sequence[Sequence[Vec2]],
    raised: Sequence[Sequence[Vec2]],
    z0: float,
    z1: float,
    z2: float,
    name: str = "stepped",
) -> Mesh:
    """One solid: the ``base`` region from ``z0`` to ``z1`` with the ``raised`` region standing
    on it from ``z1`` to ``z2``. The raised region must lie strictly inside the base region.

    The base's top face is triangulated with the raised contours as holes, and the raised walls
    start from those same vertices, so the step is joined without a boolean union.
    """
    if not (z0 < z1 < z2):
        raise BuildError("need z0 < z1 < z2")
    mesh = Mesh(name=name)
    base_o = _orient_by_depth(base)
    raised_o = _orient_by_depth(raised)
    b_bot = [mesh.add_vertices((x, y, z0) for x, y in c) for c in base_o]
    b_top = [mesh.add_vertices((x, y, z1) for x, y in c) for c in base_o]
    r_bot = [mesh.add_vertices((x, y, z1) for x, y in c) for c in raised_o]
    r_top = [mesh.add_vertices((x, y, z2) for x, y in c) for c in raised_o]
    for b, t in zip(b_bot, b_top, strict=True):
        wall(mesh, b, t)
    for b, t in zip(r_bot, r_top, strict=True):
        wall(mesh, b, t)
    region_faces(mesh, b_bot, up=False)
    region_faces(mesh, b_top + r_bot, up=True)
    region_faces(mesh, r_top, up=True)
    return mesh


# ------------------------------------------------------------------------------------ helix
def helix_rings(
    section: Sequence[Vec2],
    radius: float,
    pitch: float,
    turns: float,
    steps_per_turn: int,
    frame: str = "radial",
) -> list[list[Vec3]]:
    """Rings of a section swept along a helix of ``radius`` and ``pitch`` (mm per turn).

    ``frame="radial"``: section coordinates (u, v) are (radial offset, height) in the plane
    through the axis -- a coil or thread. ``frame="horizontal"``: (u, v) lie in the horizontal
    plane and turn with the helix -- a twisted, wobbling prism; every horizontal slice is the
    section itself, so the solid never overlaps itself.
    """
    if frame not in ("radial", "horizontal"):
        raise BuildError(f"unknown helix frame {frame!r}")
    if turns == 0:
        raise BuildError("turns must be non-zero")
    steps = max(2, round(steps_per_turn * abs(turns)))
    rings = []
    for k in range(steps + 1):
        t = turns * k / steps
        th = 2 * math.pi * t
        c, s = math.cos(th), math.sin(th)
        zc = pitch * t
        if frame == "radial":
            rings.append([((radius + u) * c, (radius + u) * s, zc + v) for u, v in section])
        else:
            rings.append(
                [((radius + u) * c - v * s, (radius + u) * s + v * c, zc) for u, v in section]
            )
    return rings


def sweep_helix(
    section: Sequence[Vec2],
    radius: float,
    pitch: float,
    turns: float,
    steps_per_turn: int = 48,
    frame: str = "radial",
    name: str = "helix",
) -> Mesh:
    """Closed solid of a section swept along a helix (see :func:`helix_rings`)."""
    if frame == "radial":
        _, vmin, _, vmax = poly2d.bounds2d(section)
        if turns > 1 and pitch <= vmax - vmin:
            raise BuildError("pitch must exceed the section height or the coil hits itself")
        umin = min(u for u, _ in section)
        if radius + umin <= 0:
            raise BuildError("section crosses the helix axis")
    sec = poly2d.ccw(section)
    return loft(helix_rings(sec, radius, pitch, turns, steps_per_turn, frame), name=name)


# --------------------------------------------------------------------------- simple solids
def box(sx: float, sy: float, sz: float, name: str = "box") -> Mesh:
    hx, hy = sx / 2, sy / 2
    return extrude([[(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)]], 0.0, sz, name=name)


def cylinder(radius: float, height: float, segments: int = 64, name: str = "cylinder") -> Mesh:
    return extrude([poly2d.circle(radius, segments)], 0.0, height, name=name)


def sphere(radius: float, segments: int = 48, rings: int = 24, name: str = "sphere") -> Mesh:
    prof = [
        (radius * math.sin(math.pi * i / rings), -radius * math.cos(math.pi * i / rings))
        for i in range(rings + 1)
    ]
    prof[0] = (0.0, -radius)
    prof[-1] = (0.0, radius)
    return revolve(prof, segments, name=name)
