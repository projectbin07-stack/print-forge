"""2D polygon tools: orientation, containment, nesting, shapes, offsets and ear clipping.

Triangulation is ear clipping with holes joined to the outer ring by bridge edges (the method
described by David Eberly, "Triangulation by Ear Clipping", Geometric Tools, 2002). Triangles
reference the input points by index, so a cap triangulated here shares its boundary vertices with
the side walls built from the same contour: that is what makes the solids watertight.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from .vec import Vec2

Tri = tuple[int, int, int]


class TriangulationError(ValueError):
    """The polygon could not be triangulated (it is probably self-intersecting)."""


# ------------------------------------------------------------------------------------- basics
def signed_area(poly: Sequence[Vec2]) -> float:
    """Shoelace area; positive for counter-clockwise rings."""
    total = 0.0
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        total += x0 * y1 - x1 * y0
    return total / 2.0


def is_ccw(poly: Sequence[Vec2]) -> bool:
    return signed_area(poly) > 0


def ccw(poly: Sequence[Vec2]) -> list[Vec2]:
    return list(poly) if is_ccw(poly) else list(reversed(poly))


def cw(poly: Sequence[Vec2]) -> list[Vec2]:
    return list(reversed(poly)) if is_ccw(poly) else list(poly)


def _cross(o: Vec2, a: Vec2, b: Vec2) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def point_in_polygon(pt: Vec2, poly: Sequence[Vec2]) -> bool:
    """Even-odd ray test. Points exactly on an edge may go either way."""
    x, y = pt
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def bounds2d(poly: Sequence[Vec2]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _segments_cross(a: Vec2, b: Vec2, c: Vec2, d: Vec2) -> bool:
    d1 = _cross(c, d, a)
    d2 = _cross(c, d, b)
    d3 = _cross(a, b, c)
    d4 = _cross(a, b, d)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and 0 not in (d1, d2, d3, d4)


def is_simple(poly: Sequence[Vec2]) -> bool:
    """True when no two non-adjacent edges cross (O(n^2), meant for validation)."""
    n = len(poly)
    if n < 3:
        return False
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            if _segments_cross(a, b, poly[j], poly[(j + 1) % n]):
                return False
    return True


def min_edge_distance(p: Vec2, poly: Sequence[Vec2]) -> float:
    """Distance from ``p`` to the nearest edge of the closed ring ``poly``."""
    best = math.inf
    n = len(poly)
    for i in range(n):
        best = min(best, _point_segment_distance(p, poly[i], poly[(i + 1) % n]))
    return best


def _point_segment_distance(p: Vec2, a: Vec2, b: Vec2) -> float:
    abx, aby = b[0] - a[0], b[1] - a[1]
    ln2 = abx * abx + aby * aby
    t = 0.0 if ln2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * abx + (p[1] - a[1]) * aby) / ln2))
    dx = a[0] + t * abx - p[0]
    dy = a[1] + t * aby - p[1]
    return math.hypot(dx, dy)


def ring_distance(a: Sequence[Vec2], b: Sequence[Vec2]) -> float:
    """Smallest vertex-to-edge distance between two rings (both directions)."""
    return min(
        min(min_edge_distance(p, b) for p in a),
        min(min_edge_distance(p, a) for p in b),
    )


# ------------------------------------------------------------------------------------- shapes
def circle(radius: float, segments: int, phase: float = 0.0) -> list[Vec2]:
    """Regular polygon with its vertices on the circle (counter-clockwise)."""
    return [
        (
            radius * math.cos(phase + 2 * math.pi * i / segments),
            radius * math.sin(phase + 2 * math.pi * i / segments),
        )
        for i in range(segments)
    ]


def hole_circle(radius: float, segments: int) -> list[Vec2]:
    """Polygon whose *inscribed* circle has ``radius``, so a pin of that radius fits.

    Slicers print a polygonal hole exactly as modelled; using vertices on the circle would make
    the hole narrower than nominal between vertices by ``r * (1 - cos(pi / n))``.
    """
    return circle(radius / math.cos(math.pi / segments), segments, math.pi / segments)


def rounded_rect(
    width: float, depth: float, radius: float, corner_segments: int = 6, edge_segments: int = 1
) -> list[Vec2]:
    """Counter-clockwise rounded rectangle centred on the origin.

    The vertex count is ``4 * (corner_segments + 1 + edge_segments - 1) ...`` and depends only on
    the segment counts, never on the size, so two rounded rectangles of different sizes can be
    lofted vertex-to-vertex. Straight edges are split into ``edge_segments`` pieces.
    """
    hw, hd = width / 2.0, depth / 2.0
    r = max(0.0, min(radius, hw * 0.999, hd * 0.999))
    centres = ((hw - r, hd - r), (-hw + r, hd - r), (-hw + r, -hd + r), (hw - r, -hd + r))
    pts: list[Vec2] = []
    for k, (cx, cy) in enumerate(centres):
        start = k * math.pi / 2
        for i in range(corner_segments + 1):
            a = start + (math.pi / 2) * i / corner_segments
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        nxt = centres[(k + 1) % 4]
        end_a = start + math.pi / 2
        p0 = (cx + r * math.cos(end_a), cy + r * math.sin(end_a))
        na = (k + 1) * math.pi / 2
        p1 = (nxt[0] + r * math.cos(na), nxt[1] + r * math.sin(na))
        for i in range(1, edge_segments):
            t = i / edge_segments
            pts.append((p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t))
    if r == 0.0:
        # all corner points of one corner coincide; keep one per corner
        dedup: list[Vec2] = []
        for p in pts:
            if not dedup or math.dist(dedup[-1], p) > 1e-12:
                dedup.append(p)
        if math.dist(dedup[0], dedup[-1]) <= 1e-12:
            dedup.pop()
        return dedup
    return pts


def translate2d(poly: Sequence[Vec2], dx: float, dy: float) -> list[Vec2]:
    return [(x + dx, y + dy) for x, y in poly]


def simplify(poly: Sequence[Vec2], tolerance: float) -> list[Vec2]:
    """Drop vertices of a closed ring while every dropped vertex stays within ``tolerance`` of
    the edge that replaces it (greedy; the error is bounded, not accumulated). Removes
    duplicates and collinear points."""
    pts = list(poly)
    n = len(pts)
    if n <= 3:
        return pts
    # start from the vertex farthest from its neighbours' chord: it is surely kept
    start = max(
        range(n), key=lambda i: _point_segment_distance(pts[i], pts[i - 1], pts[(i + 1) % n])
    )
    ring = pts[start:] + pts[:start]
    kept = [ring[0]]
    anchor = 0
    i = 1
    while i < n:
        # extend the edge from the anchor as far as all skipped points stay within tolerance
        j = i
        while j + 1 <= n:
            end = ring[(j + 1) % n]
            if all(
                _point_segment_distance(ring[k], ring[anchor], end) < tolerance
                for k in range(anchor + 1, j + 1)
            ):
                j += 1
            else:
                break
        if j >= n:
            break
        kept.append(ring[j])
        anchor = j
        i = j + 1
    return kept if len(kept) >= 3 else pts


def remove_spikes(poly: Sequence[Vec2], tolerance: float = 1e-7) -> list[Vec2]:
    """Remove zero-width spikes: a vertex on the line through its neighbours but outside the
    segment between them (the ring doubles back on itself), and repeated points.

    Marching squares produces such spikes where a notch is narrower than one grid cell: both
    sides of the notch cross the same grid line.
    """
    pts = list(poly)
    guard = 0
    while len(pts) > 3 and guard < 4 * len(poly) + 8:
        guard += 1
        n = len(pts)
        removed = False
        for k in range(n):
            a, b, c = pts[k - 1], pts[k], pts[(k + 1) % n]
            if math.dist(a, b) <= tolerance:
                pts.pop(k)
                removed = True
                break
            dx, dy = c[0] - a[0], c[1] - a[1]
            ln2 = dx * dx + dy * dy
            if ln2 == 0.0:
                pts.pop(k)
                removed = True
                break
            t = ((b[0] - a[0]) * dx + (b[1] - a[1]) * dy) / ln2
            if (t <= 0 or t >= 1) and abs(_cross(a, b, c)) <= tolerance * math.sqrt(ln2):
                pts.pop(k)
                removed = True
                break
        if not removed:
            break
    return pts


def densify(poly: Sequence[Vec2], max_edge: float) -> list[Vec2]:
    """Split edges of a closed ring so none is longer than ``max_edge``."""
    out: list[Vec2] = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        pieces = max(1, math.ceil(math.dist(a, b) / max_edge))
        for k in range(pieces):
            t = k / pieces
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def offset_ring(ring: Sequence[Vec2], distance: float, max_miter: float = 3.0) -> list[Vec2]:
    """Move each vertex of a counter-clockwise ring inward by ``distance`` along the bisector
    of its two edge normals (mitred, capped at ``max_miter`` times the distance)."""
    n = len(ring)
    out: list[Vec2] = []
    for i in range(n):
        a, b, c = ring[i - 1], ring[i], ring[(i + 1) % n]
        n1 = _left_normal(a, b)
        n2 = _left_normal(b, c)
        bx, by = n1[0] + n2[0], n1[1] + n2[1]
        bl = math.hypot(bx, by)
        if bl < 1e-12:
            bx, by, bl = n1[0], n1[1], 1.0
        bx, by = bx / bl, by / bl
        cos_half = bx * n1[0] + by * n1[1]
        k = distance / max(cos_half, 1.0 / max_miter)
        out.append((b[0] + bx * k, b[1] + by * k))
    return out


def _left_normal(a: Vec2, b: Vec2) -> Vec2:
    dx, dy = b[0] - a[0], b[1] - a[1]
    ln = math.hypot(dx, dy)
    if ln == 0:
        return (0.0, 0.0)
    return (-dy / ln, dx / ln)


# ------------------------------------------------------------------------------------ nesting
def nest(contours: Sequence[Sequence[Vec2]]) -> list[tuple[int, list[int]]]:
    """Group non-crossing closed contours into even-odd filled regions.

    Returns ``(outer_index, [hole_indices])`` for every contour at even nesting depth; its holes
    are the contours directly inside it. Contours must not touch or cross.
    """
    depth, parent = nesting(contours)
    regions = []
    for i in range(len(contours)):
        if depth[i] % 2 == 0:
            holes = [j for j in range(len(contours)) if parent[j] == i]
            regions.append((i, holes))
    return regions


def nesting(contours: Sequence[Sequence[Vec2]]) -> tuple[list[int], list[int]]:
    """Nesting depth of every contour and the index of its innermost container (-1 if none)."""
    n = len(contours)
    areas = [abs(signed_area(c)) for c in contours]
    boxes = [bounds2d(c) for c in contours]
    parent: list[int] = [-1] * n
    depth: list[int] = [0] * n
    for i in range(n):
        p = contours[i][0]
        containers = []
        for j in range(n):
            if i == j or areas[j] <= areas[i]:
                continue
            bx = boxes[j]
            if not (bx[0] <= p[0] <= bx[2] and bx[1] <= p[1] <= bx[3]):
                continue
            if point_in_polygon(p, contours[j]):
                containers.append(j)
        depth[i] = len(containers)
        if containers:
            parent[i] = min(containers, key=lambda j: areas[j])
    return depth, parent


# ------------------------------------------------------------------------------ ear clipping
def triangulate(outer: Sequence[Vec2], holes: Sequence[Sequence[Vec2]] = ()) -> list[Tri]:
    """Triangulate a simple polygon with holes.

    Indices refer to the concatenation ``outer + holes[0] + holes[1] + ...`` in the order given
    (the input orientation does not matter). Triangles are counter-clockwise. Raises
    :class:`TriangulationError` when no ear can be found.
    """
    pts: list[Vec2] = list(outer)
    outer_idx = list(range(len(outer)))
    if signed_area(outer) < 0:
        outer_idx.reverse()
    hole_rings: list[list[int]] = []
    for h in holes:
        idx = list(range(len(pts), len(pts) + len(h)))
        pts.extend(h)
        if signed_area(h) > 0:
            idx.reverse()
        hole_rings.append(idx)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    tol = 1e-9 * max(max(xs) - min(xs), max(ys) - min(ys), 1e-9)
    inserts: dict[tuple[int, int], list[int]] = {}
    ring = _drop_collinear(pts, outer_idx, tol, inserts)
    kept_holes = [_drop_collinear(pts, h, tol, inserts) for h in hole_rings]
    for h_idx in sorted(kept_holes, key=lambda r: -max(pts[i][0] for i in r)):
        ring = _bridge_hole(pts, ring, h_idx)
    # Ear order matters only for robustness: vertices of different contours can be exactly
    # collinear (straight strokes of a letter), and an unlucky order can leave a zero-area
    # remainder. Retry with a different ear-selection window and start vertex.
    error: TriangulationError | None = None
    n_ring = len(ring)
    attempts = [(w, n_ring * k // 5) for k in range(5) for w in (_EAR_WINDOW, 0, 4)]
    for window, start in attempts:
        try:
            tris, drops = _ear_clip(pts, ring, window, start, tol)
            # vertices dropped while clipping go back first (last dropped first), then the
            # collinear input vertices removed before clipping
            return _reinsert(tris, [*reversed(drops), *inserts.items()])
        except TriangulationError as exc:
            error = exc
    assert error is not None
    raise error


def _drop_collinear(
    pts: list[Vec2], ring: list[int], tol: float, inserts: dict[tuple[int, int], list[int]]
) -> list[int]:
    """Remove vertices lying on the straight line between their neighbours.

    Collinear vertices give ear clipping zero-area candidates and can stall it. They are
    triangulated without, then put back by splitting the triangle on their edge
    (:func:`_reinsert`), so the boundary keeps every input vertex and no T-junction appears.
    ``inserts`` maps each kept edge (u, v) to the removed vertices on it, in ring order.
    """
    if len(ring) <= 3:
        return list(ring)
    keep = [True] * len(ring)
    n = len(ring)

    def neighbour(k: int, step: int) -> int:
        j = (k + step) % n
        while not keep[j]:
            j = (j + step) % n
        return j

    changed = True
    while changed and sum(keep) > 3:
        changed = False
        for k in range(n):
            if not keep[k] or sum(keep) <= 3:
                continue
            a, b = pts[ring[neighbour(k, -1)]], pts[ring[neighbour(k, 1)]]
            p = pts[ring[k]]
            dx, dy = b[0] - a[0], b[1] - a[1]
            ln2 = dx * dx + dy * dy
            if ln2 == 0:
                continue
            t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / ln2
            if 0 < t < 1 and _point_segment_distance(p, a, b) <= tol:
                keep[k] = False
                changed = True
    kept = [ring[k] for k in range(n) if keep[k]]
    if len(kept) == n:
        return kept
    first = next(k for k in range(n) if keep[k])
    run: list[int] = []
    prev = ring[first]
    for step in range(1, n + 1):
        k = (first + step) % n
        if keep[k]:
            if run:
                inserts[(prev, ring[k])] = run
            run = []
            prev = ring[k]
        else:
            run.append(ring[k])
    return kept


Insert = tuple[tuple[int, int], list[int]]


def _reinsert(tris: list[Tri], inserts: Sequence[Insert]) -> list[Tri]:
    """Split the triangle on each directed edge (u, v) into a fan through the removed
    collinear vertices on that edge, in the order given."""
    tris = list(tris)
    by_edge: dict[tuple[int, int], int] = {}
    for t, (a, b, c) in enumerate(tris):
        for u, v in ((a, b), (b, c), (c, a)):
            by_edge[(u, v)] = t
    for (u, v), mids in inserts:
        t_found = by_edge.get((u, v))
        if t_found is None:
            raise TriangulationError("boundary edge missing after triangulation")
        t = t_found
        a, b, c = tris[t]
        while (a, b) != (u, v):
            a, b, c = b, c, a
        chain = [u, *mids, v]
        del by_edge[(u, v)]
        for i in range(len(chain) - 1):
            tri = (chain[i], chain[i + 1], c)
            if i == 0:
                tris[t] = tri
                idx = t
            else:
                tris.append(tri)
                idx = len(tris) - 1
            for e in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
                by_edge[e] = idx
    return tris


def _bridge_hole(pts: list[Vec2], ring: list[int], hole: list[int]) -> list[int]:
    m_pos = max(range(len(hole)), key=lambda k: (pts[hole[k]][0], -pts[hole[k]][1]))
    m = hole[m_pos]
    mx, my = pts[m]
    best_x = math.inf
    best_k = -1
    n = len(ring)
    for k in range(n):
        a = pts[ring[k]]
        b = pts[ring[(k + 1) % n]]
        if (a[1] > my) == (b[1] > my) and a[1] != my and b[1] != my:
            continue
        if a[1] == b[1]:
            if a[1] != my:
                continue
            x = min(a[0], b[0]) if min(a[0], b[0]) >= mx else max(a[0], b[0])
        else:
            x = a[0] + (my - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
        if mx <= x < best_x:
            best_x = x
            best_k = k
    if best_k < 0:
        raise TriangulationError("hole is not inside the outer contour")
    a_k, b_k = best_k, (best_k + 1) % n
    cand_k = a_k if pts[ring[a_k]][0] > pts[ring[b_k]][0] else b_k
    ix, iy = best_x, my
    px, py = pts[ring[cand_k]]
    # Reflex vertices inside triangle (M, I, P) would block the bridge; take the one with the
    # smallest angle to the ray instead.
    if not (px == ix and py == iy):
        best_angle = math.inf
        best_dist = math.inf
        tri = ((mx, my), (ix, iy), (px, py))
        for k in range(n):
            q = pts[ring[k]]
            if k == cand_k or q[0] < mx:
                continue
            if not _point_in_triangle(q, *tri):
                continue
            if not _is_reflex(pts, ring, k):
                continue
            ang = abs(math.atan2(q[1] - my, q[0] - mx))
            dist = math.hypot(q[0] - mx, q[1] - my)
            if ang < best_angle or (ang == best_angle and dist < best_dist):
                best_angle, best_dist, cand_k = ang, dist, k
    p = ring[cand_k]
    # When P occurs several times (earlier bridges), splice at the copy whose wedge contains M.
    copies = [k for k in range(n) if ring[k] == p] if ring.count(p) > 1 else [cand_k]
    k_use = copies[0]
    for k in copies:
        if _locally_inside(pts, ring, k, (mx, my)):
            k_use = k
            break
    rotated = hole[m_pos:] + hole[:m_pos]
    return [*ring[: k_use + 1], *rotated, m, p, *ring[k_use + 1 :]]


def _is_reflex(pts: list[Vec2], ring: list[int], k: int) -> bool:
    n = len(ring)
    return _cross(pts[ring[k - 1]], pts[ring[k]], pts[ring[(k + 1) % n]]) <= 0


def _locally_inside(pts: list[Vec2], ring: list[int], k: int, q: Vec2) -> bool:
    n = len(ring)
    a, p, b = pts[ring[k - 1]], pts[ring[k]], pts[ring[(k + 1) % n]]
    if _cross(a, p, b) >= 0:
        return _cross(a, p, q) >= 0 and _cross(p, b, q) >= 0
    return _cross(a, p, q) >= 0 or _cross(p, b, q) >= 0


def _point_in_triangle(p: Vec2, a: Vec2, b: Vec2, c: Vec2) -> bool:
    """Inclusive test for a counter-clockwise or clockwise triangle."""
    d1 = _cross(a, b, p)
    d2 = _cross(b, c, p)
    d3 = _cross(c, a, p)
    has_neg = d1 < 0 or d2 < 0 or d3 < 0
    has_pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (has_neg and has_pos)


_EAR_WINDOW = 12


def _between(a: Vec2, p: Vec2, b: Vec2, tol: float) -> bool:
    """``p`` lies on segment a-b (within ``tol``), strictly between its ends."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    ln2 = dx * dx + dy * dy
    if ln2 == 0.0:
        return False
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / ln2
    return 0.0 < t < 1.0 and _point_segment_distance(p, a, b) <= tol


def _strictly_inside(p: Vec2, a: Vec2, b: Vec2, c: Vec2) -> bool:
    """Strict test for a counter-clockwise triangle."""
    return _cross(a, b, p) > 0 and _cross(b, c, p) > 0 and _cross(c, a, p) > 0


def _ear_clip(
    pts: list[Vec2], ring: list[int], window: int, start: int, tol: float
) -> tuple[list[Tri], list[Insert]]:
    """Ear clipping on one ring (holes already bridged).

    Returns the triangles and the vertices dropped on the way: when no ear is left because a
    vertex lies on the straight line between its neighbours (vertices of different contours
    can be exactly collinear), that vertex is taken out and the triangle later built on the
    edge between its neighbours is split at it (:func:`_reinsert`)."""
    n = len(ring)
    if n < 3:
        raise TriangulationError("polygon has fewer than 3 vertices")
    xs = [pts[i][0] for i in ring]
    ys = [pts[i][1] for i in ring]
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1e-9)
    eps = 1e-14 * span * span
    prev = [(i - 1) % n for i in range(n)]
    nxt = [(i + 1) % n for i in range(n)]
    alive = [True] * n
    # uniform grid of nodes for containment queries
    cells = max(1, int(math.sqrt(n)))
    x0, y0 = min(xs), min(ys)
    cw_ = span / cells
    grid: dict[tuple[int, int], list[int]] = {}

    def cell_of(x: float, y: float) -> tuple[int, int]:
        return (int((x - x0) / cw_), int((y - y0) / cw_))

    for node in range(n):
        p = pts[ring[node]]
        grid.setdefault(cell_of(*p), []).append(node)

    def is_ear(node: int) -> bool:
        ia, ib, ic = ring[prev[node]], ring[node], ring[nxt[node]]
        a, b, c = pts[ia], pts[ib], pts[ic]
        if _cross(a, b, c) <= eps:
            return False
        lo = cell_of(min(a[0], b[0], c[0]), min(a[1], b[1], c[1]))
        hi = cell_of(max(a[0], b[0], c[0]), max(a[1], b[1], c[1]))
        for gx in range(lo[0], hi[0] + 1):
            for gy in range(lo[1], hi[1] + 1):
                for other in grid.get((gx, gy), ()):
                    if not alive[other] or other in (node, prev[node], nxt[node]):
                        continue
                    q = pts[ring[other]]
                    if q in (a, b, c):
                        # A copy of a corner (bridge vertex): the ear is invalid if one of the
                        # copy's own edges runs into the triangle.
                        for w in (pts[ring[prev[other]]], pts[ring[nxt[other]]]):
                            if w in (a, b, c):
                                continue  # runs along a triangle edge, not into it
                            probe = (q[0] + (w[0] - q[0]) * 1e-6, q[1] + (w[1] - q[1]) * 1e-6)
                            if _strictly_inside(probe, a, b, c):
                                return False
                        continue
                    if _point_in_triangle(q, a, b, c):
                        return False
        return True

    def quality(node: int) -> float:
        """4 sqrt(3) area / sum of squared edges: 1 for equilateral, 0 for a sliver."""
        a, b, c = pts[ring[prev[node]]], pts[ring[node]], pts[ring[nxt[node]]]
        area2 = _cross(a, b, c)
        s2 = sum((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 for p, q in ((a, b), (b, c), (c, a)))
        return 2 * math.sqrt(3) * area2 / s2 if s2 > 0 else 0.0

    def _flat_vertex(from_node: int) -> int | None:
        """A live vertex lying on the segment between its neighbours, if any."""
        v = from_node
        for _ in range(remaining):
            if _between(pts[ring[prev[v]]], pts[ring[v]], pts[ring[nxt[v]]], tol):
                return v
            v = nxt[v]
        return None

    tris: list[Tri] = []
    drops: list[Insert] = []
    remaining = n
    node = start % n
    stall = 0
    while remaining > 3:
        if is_ear(node):
            # Among the next few ears, clip the best-shaped one: first-found ears tend to be
            # slivers that leave nearly collinear vertices for the end.
            best, best_q = node, quality(node)
            cand = nxt[node]
            for _ in range(min(window, remaining - 1)):
                q = quality(cand)
                if q > best_q and is_ear(cand):
                    best, best_q = cand, q
                cand = nxt[cand]
            node = best
            tris.append((ring[prev[node]], ring[node], ring[nxt[node]]))
            alive[node] = False
            before, after = prev[node], nxt[node]
            nxt[before] = after
            prev[after] = before
            remaining -= 1
            stall = 0
            node = after
        else:
            node = nxt[node]
            stall += 1
            if stall > remaining:
                flat = _flat_vertex(node)
                if flat is None:
                    raise TriangulationError(
                        f"no ear found with {remaining} vertices left; is the polygon simple?"
                    )
                before, after = prev[flat], nxt[flat]
                drops.append(((ring[before], ring[after]), [ring[flat]]))
                alive[flat] = False
                nxt[before] = after
                prev[after] = before
                remaining -= 1
                stall = 0
                node = after
    a, b, c = prev[node], node, nxt[node]
    if _cross(pts[ring[a]], pts[ring[b]], pts[ring[c]]) <= eps:
        # Zero-area remainder of three collinear vertices: split the triangle already built on
        # the long side at the middle vertex instead of emitting a sliver.
        for mid, (u, w) in ((b, (a, c)), (a, (c, b)), (c, (b, a))):
            if _between(pts[ring[u]], pts[ring[mid]], pts[ring[w]], tol):
                drops.append(((ring[u], ring[w]), [ring[mid]]))
                return tris, drops
        raise TriangulationError(f"final triangle is degenerate ({ring[a]}, {ring[b]}, {ring[c]})")
    tris.append((ring[a], ring[b], ring[c]))
    return tris, drops
