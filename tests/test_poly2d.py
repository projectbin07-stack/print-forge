from __future__ import annotations

import math
import random

import pytest

from print_forge import poly2d
from print_forge.vec import Vec2


def tri_area(pts: list[Vec2], t: tuple[int, int, int]) -> float:
    a, b, c = (pts[i] for i in t)
    return ((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) / 2


def check_triangulation(outer: list[Vec2], holes: list[list[Vec2]]) -> None:
    pts = list(outer) + [p for h in holes for p in h]
    tris = poly2d.triangulate(outer, holes)
    expected = abs(poly2d.signed_area(outer)) - sum(abs(poly2d.signed_area(h)) for h in holes)
    areas = [tri_area(pts, t) for t in tris]
    assert min(areas) > 0  # all counter-clockwise, none degenerate
    assert sum(areas) == pytest.approx(expected, rel=1e-9, abs=1e-9)
    # every boundary edge is used exactly once; interior edges twice in opposite directions
    directed: dict[tuple[int, int], int] = {}
    for a, b, c in tris:
        for e in ((a, b), (b, c), (c, a)):
            directed[e] = directed.get(e, 0) + 1
    assert all(v == 1 for v in directed.values())
    n_vertices = len(pts)
    n_holes = len(holes)
    # Euler: triangles = n + 2 * holes - 2 for a polygon with holes
    assert len(tris) == n_vertices + 2 * n_holes - 2


def star(n: int, r_out: float, r_in: float, rng: random.Random) -> list[Vec2]:
    pts = []
    for i in range(2 * n):
        r = r_out if i % 2 == 0 else r_in
        r *= rng.uniform(0.9, 1.0)
        a = math.pi * i / n
        pts.append((r * math.cos(a), r * math.sin(a)))
    return pts


def test_square_and_orientation() -> None:
    sq = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    assert poly2d.signed_area(sq) == 1
    assert poly2d.is_ccw(sq)
    assert poly2d.ccw(list(reversed(sq))) == sq
    assert not poly2d.is_ccw(poly2d.cw(sq))
    check_triangulation(list(reversed(sq)), [])


@pytest.mark.parametrize("seed", range(20))
def test_random_stars_with_holes(seed: int) -> None:
    rng = random.Random(seed)
    outer = star(rng.randint(3, 12), 30, rng.uniform(12, 20), rng)
    holes = []
    for k in range(rng.randint(0, 3)):
        cx = -6 + 6 * k
        holes.append(
            poly2d.translate2d(
                poly2d.circle(rng.uniform(0.8, 2.0), rng.randint(3, 20)), cx, rng.uniform(-3, 3)
            )
        )
    check_triangulation(outer, holes)


def test_collinear_vertices_are_kept() -> None:
    # hexagon with 7 points per side (exactly the vase inner ring that once stalled ear clipping)
    hexagon = poly2d.circle(10, 6)
    ring = []
    for i in range(6):
        a, b = hexagon[i], hexagon[(i + 1) % 6]
        ring += [(a[0] + (b[0] - a[0]) * t / 7, a[1] + (b[1] - a[1]) * t / 7) for t in range(7)]
    check_triangulation(ring, [])
    rect = poly2d.rounded_rect(10, 6, 0, 1, 5)
    check_triangulation(rect, [poly2d.circle(1, 8)])


def test_letter_like_shape_with_counter() -> None:
    outer = [(0, 0), (10, 0), (10, 10), (6, 10), (6, 4), (4, 4), (4, 10), (0, 10)]
    hole = [(1, 1), (1, 3), (3, 3), (3, 1)]
    check_triangulation(
        [(float(x), float(y)) for x, y in outer], [[(float(x), float(y)) for x, y in hole]]
    )


def test_hole_bridges_share_a_vertex() -> None:
    # Several holes on one horizontal line all bridge to the same outer vertex.
    outer = [(0.0, -5.0), (40.0, 0.0), (0.0, 5.0)]
    holes = [poly2d.translate2d(poly2d.circle(0.5, 6), x, 0.0) for x in (5.0, 10.0, 15.0)]
    check_triangulation(outer, holes)


def test_bad_polygons_raise() -> None:
    with pytest.raises(poly2d.TriangulationError):
        poly2d.triangulate([(0.0, 0.0), (1.0, 1.0)])
    bow_tie = [(0.0, 0.0), (2.0, 2.0), (2.0, 0.0), (0.0, 2.0)]
    assert not poly2d.is_simple(bow_tie)
    with pytest.raises(poly2d.TriangulationError):
        poly2d.triangulate(
            [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)], [[(5.0, 5.0), (6.0, 5.0), (6.0, 6.0)]]
        )


def test_hole_circle_inscribed_radius() -> None:
    for n in (6, 8, 32):
        h = poly2d.hole_circle(1.5, n)
        # distance from the centre to every edge equals the requested radius
        for i in range(n):
            a, b = h[i], h[(i + 1) % n]
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            assert math.hypot(mx, my) == pytest.approx(1.5)


def test_rounded_rect_counts_and_area() -> None:
    a = poly2d.rounded_rect(18, 18, 2, 6, 4)
    b = poly2d.rounded_rect(12, 14, 3, 6, 4)
    assert len(a) == len(b) == 4 * (7 + 3)
    assert poly2d.is_ccw(a)
    # area of a rounded rectangle: w*d - (4 - pi) r^2 (polygonal arcs are slightly smaller)
    assert poly2d.signed_area(a) == pytest.approx(18 * 18 - (4 - math.pi) * 4, rel=2e-3)
    sharp = poly2d.rounded_rect(4, 2, 0)
    assert len(sharp) == 4
    assert poly2d.signed_area(sharp) == pytest.approx(8)


def test_offset_regular_polygon() -> None:
    hexagon = poly2d.circle(10, 6)
    inner = poly2d.offset_ring(hexagon, 1.0)
    apothem = 10 * math.cos(math.pi / 6)
    for i in range(6):
        a, b = inner[i], inner[(i + 1) % 6]
        assert math.hypot((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) == pytest.approx(apothem - 1)


def test_simplify_densify_and_distances() -> None:
    sq = [(0.0, 0.0), (0.5, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    simple = poly2d.simplify(sq, 1e-6)
    assert sorted(simple) == [(0.0, 0.0), (0.0, 1.0), (1.0, 0.0), (1.0, 1.0)]
    assert poly2d.signed_area(simple) == pytest.approx(1.0)
    # error is bounded: a circle simplified at 0.01 stays within 0.01 of the original
    circ = poly2d.circle(5, 400)
    s2 = poly2d.simplify(circ, 0.01)
    assert len(s2) < 100
    assert all(5 - 0.01 - 1e-9 <= math.hypot(*p) <= 5 + 1e-9 for p in s2)
    assert all(poly2d.min_edge_distance(p, s2) < 0.01 for p in circ)
    spiky = [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (2.0, 3.0), (2.0, 2.0), (0.0, 2.0)]
    assert poly2d.remove_spikes(spiky) == [
        (0.0, 0.0),
        (2.0, 0.0),
        (2.0, 1.0),
        (2.0, 2.0),
        (0.0, 2.0),
    ]
    d = poly2d.densify([(0.0, 0.0), (3.0, 0.0), (3.0, 1.0)], 1.0)
    assert len(d) == 3 + 1 + 4  # 3 + 1 + ceil(sqrt(10)) pieces
    assert poly2d.min_edge_distance((0.0, 0.0), poly2d.rounded_rect(1, 1, 0)) == pytest.approx(0.5)
    a = poly2d.circle(1, 16)
    b = poly2d.translate2d(poly2d.circle(1, 16), 5, 0)
    assert poly2d.ring_distance(a, b) == pytest.approx(3.0)
    assert poly2d.point_in_polygon((0.0, 0.0), a)
    assert not poly2d.point_in_polygon((2.0, 0.0), a)


def test_nesting_depths() -> None:
    contours = [
        poly2d.circle(10, 16),
        poly2d.circle(6, 16),
        poly2d.circle(3, 16),
        poly2d.translate2d(poly2d.circle(1, 8), 20, 0),
    ]
    depth, parent = poly2d.nesting(contours)
    assert depth == [0, 1, 2, 0]
    assert parent == [-1, 0, 1, -1]
    assert poly2d.nest(contours) == [(0, [1]), (2, []), (3, [])]
