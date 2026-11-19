"""Constructors: closed by construction (property tests) and volumes against hand formulas."""

from __future__ import annotations

import math
import random

import pytest

from conftest import assert_solid
from print_forge import build, poly2d
from print_forge.vec import Vec2, Vec3


def prism_area(r: float, n: int) -> float:
    """Area of a regular n-gon with circumradius r: n/2 r^2 sin(2 pi / n)."""
    return n / 2 * r * r * math.sin(2 * math.pi / n)


def test_revolved_cylinder_is_exact_prism() -> None:
    # profile: axis -> (r, 0) -> (r, h) -> axis; the solid is an n-gon prism
    r, h, n = 6.0, 11.0, 40
    m = build.revolve([(0, 0), (r, 0), (r, h), (0, h)], n)
    assert_solid(m)
    assert m.volume() == pytest.approx(prism_area(r, n) * h, rel=1e-12)


@pytest.mark.parametrize(("segments", "rings", "tol"), [(32, 16, 0.03), (128, 64, 0.002)])
def test_revolved_sphere_converges(segments: int, rings: int, tol: float) -> None:
    r = 9.0
    m = build.sphere(r, segments, rings)
    assert_solid(m)
    exact = 4 / 3 * math.pi * r**3
    # an inscribed polyhedron is always smaller than the sphere
    assert m.volume() < exact
    assert m.volume() == pytest.approx(exact, rel=tol)


def test_revolved_ring_section_annulus() -> None:
    # rectangle section r in [4, 7], z in [0, 3] -> hollow n-gon prism, exact
    n = 36
    m = build.revolve([(4, 0), (7, 0), (7, 3), (4, 3)], n)
    assert_solid(m)
    assert m.volume() == pytest.approx((prism_area(7, n) - prism_area(4, n)) * 3, rel=1e-12)


def test_revolve_rejects_bad_profiles() -> None:
    with pytest.raises(build.BuildError):
        build.revolve([(0, 0), (1, 1), (0, 2)], 2)
    with pytest.raises(build.BuildError):
        build.revolve([(0, 0), (0, 1)], 8)
    with pytest.raises(build.BuildError):
        build.revolve([(0, 0), (1, 0), (0, 1), (1, 2), (0, 3)], 8)
    with pytest.raises(build.BuildError):
        build.revolve([(1, 0), (2, 0)], 8)


def test_loft_frustum_formula() -> None:
    # similar, aligned regular polygons: V = h/3 (A1 + A2 + sqrt(A1 A2))
    n, r1, r2, h = 24, 10.0, 6.0, 8.0
    rings: list[list[Vec3]] = [
        [(x, y, 0.0) for x, y in poly2d.circle(r1, n)],
        [(x, y, h) for x, y in poly2d.circle(r2, n)],
    ]
    m = build.loft(rings)
    assert_solid(m)
    a1, a2 = prism_area(r1, n), prism_area(r2, n)
    assert m.volume() == pytest.approx(h / 3 * (a1 + a2 + math.sqrt(a1 * a2)), rel=1e-12)


def test_loft_with_apex_is_pyramid() -> None:
    n, r, h = 4, 5.0, 9.0
    m = build.loft([[(x, y, 0.0) for x, y in poly2d.circle(r, n)], [(0.0, 0.0, h)]])
    assert_solid(m)
    assert m.volume() == pytest.approx(prism_area(r, n) * h / 3)
    m2 = build.loft([[(0.0, 0.0, -h)], [(x, y, 0.0) for x, y in poly2d.circle(r, n)]])
    assert_solid(m2)


def test_loft_errors() -> None:
    ring: list[Vec3] = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    with pytest.raises(build.BuildError):
        build.loft([ring])
    with pytest.raises(build.BuildError):
        build.loft([ring, [*ring, (0.5, 0.5, 0)]])
    with pytest.raises(build.BuildError):
        build.loft([ring, [(0, 0, 1)], ring])


def test_vessel_volume() -> None:
    n, ro, ri, h, floor = 32, 10.0, 8.0, 20.0, 2.0
    outer = [[(x, y, z) for x, y in poly2d.circle(ro, n)] for z in (0.0, h)]
    inner = [[(x, y, z) for x, y in poly2d.circle(ri, n)] for z in (floor, h)]
    m = build.vessel(outer, inner)
    assert_solid(m)
    assert m.volume() == pytest.approx(prism_area(ro, n) * h - prism_area(ri, n) * (h - floor))
    with pytest.raises(build.BuildError):
        build.vessel(outer, [[(x, y, z) for x, y in poly2d.circle(ri, n + 1)] for z in (2.0, h)])
    cw_outer = [list(reversed(r)) for r in outer]
    cw_inner = [list(reversed(r)) for r in inner]
    with pytest.raises(build.BuildError):
        build.vessel(cw_outer, cw_inner)


def test_tube_volume() -> None:
    n = 24
    outer = [[(x, y, z) for x, y in poly2d.circle(5.0, n)] for z in (0.0, 2.0, 6.0)]
    inner = [[(x, y, z) for x, y in poly2d.circle(1.0, n)] for z in (0.0, 2.0, 6.0)]
    m = build.tube(outer, inner)
    assert_solid(m)
    assert m.volume() == pytest.approx((prism_area(5, n) - prism_area(1, n)) * 6)
    with pytest.raises(build.BuildError):
        build.tube(outer, inner[:2])


def test_extrude_even_odd_regions() -> None:
    contours = [poly2d.circle(10, 32), poly2d.circle(6, 32), poly2d.circle(3, 16)]
    m = build.extrude(contours, 1.0, 4.0)
    assert_solid(m)
    expected = (prism_area(10, 32) - prism_area(6, 32) + prism_area(3, 16)) * 3
    assert m.volume() == pytest.approx(expected)
    assert m.shell_count() == 2
    with pytest.raises(build.BuildError):
        build.extrude(contours, 1.0, 1.0)


def test_extrude_stepped_volume() -> None:
    base = [poly2d.rounded_rect(40, 20, 0), poly2d.translate2d(poly2d.circle(2, 16), -15, 0)]
    raised = [poly2d.circle(5, 32), poly2d.circle(2, 16)]
    m = build.extrude_stepped(base, raised, 0.0, 2.0, 3.5)
    assert_solid(m)
    base_area = 800 - prism_area(2, 16)
    raised_area = prism_area(5, 32) - prism_area(2, 16)
    assert m.volume() == pytest.approx(base_area * 2 + raised_area * 1.5)
    assert m.shell_count() == 1
    with pytest.raises(build.BuildError):
        build.extrude_stepped(base, raised, 0.0, 2.0, 2.0)


def test_helix_radial_pappus() -> None:
    # Pappus for a helical sweep of a section in the radial plane: V = A * 2 pi * r_c * turns
    # (the vertical rise does not change the volume, Cavalieri). The chord error of the
    # discretised helix keeps the mesh slightly smaller.
    section: list[Vec2] = [(0.0, 0.0), (2.0, 0.0), (2.0, 1.5), (0.0, 1.5)]
    radius, pitch, turns = 10.0, 2.0, 2.5
    m = build.sweep_helix(section, radius, pitch, turns, steps_per_turn=180)
    assert_solid(m)
    exact = 3.0 * 2 * math.pi * 11.0 * turns
    assert m.volume() == pytest.approx(exact, rel=2e-4)


def test_helix_horizontal_cavalieri() -> None:
    # every horizontal slice is the section itself: V = A * height
    section = poly2d.circle(2.0, 12)
    m = build.sweep_helix(section, 1.5, 40.0, 0.5, steps_per_turn=720, frame="horizontal")
    assert_solid(m)
    assert m.volume() == pytest.approx(prism_area(2.0, 12) * 20.0, rel=2e-3)


def test_helix_errors() -> None:
    sec: list[Vec2] = [(0.0, 0.0), (1.0, 0.0), (0.5, 2.0)]
    with pytest.raises(build.BuildError):
        build.sweep_helix(sec, 5, 1.0, 2)  # pitch below section height: coil hits itself
    with pytest.raises(build.BuildError):
        build.sweep_helix([(-6.0, 0.0), (1.0, 0.0), (0.5, 1.0)], 5, 3.0, 1)
    with pytest.raises(build.BuildError):
        build.helix_rings(sec, 5, 3, 1, 10, frame="sideways")
    with pytest.raises(build.BuildError):
        build.helix_rings(sec, 5, 3, 0, 10)


# --------------------------------------------------------------- property tests (seeded)
@pytest.mark.parametrize("seed", range(15))
def test_random_revolve_profiles(seed: int) -> None:
    rng = random.Random(seed)
    n = rng.randint(3, 8)
    zs = sorted(rng.uniform(0, 30) for _ in range(n))
    prof: list[Vec2] = (
        [(0.0, zs[0] - 1)] + [(rng.uniform(1, 15), z) for z in zs] + [(0.0, zs[-1] + 1)]
    )
    m = build.revolve(prof, rng.randint(3, 64))
    assert_solid(m)


@pytest.mark.parametrize("seed", range(15))
def test_random_lofts(seed: int) -> None:
    rng = random.Random(seed)
    n = rng.randint(3, 40)
    rings: list[list[Vec3]] = []
    z = 0.0
    for _ in range(rng.randint(2, 8)):
        r = rng.uniform(2, 20)
        twist = rng.uniform(-0.3, 0.3)
        rings.append([(x, y, z) for x, y in poly2d.circle(r, n, twist)])
        z += rng.uniform(0.5, 5)
    assert_solid(build.loft(rings))


@pytest.mark.parametrize("seed", range(15))
def test_random_extrusions_with_holes(seed: int) -> None:
    rng = random.Random(seed)
    outer = poly2d.rounded_rect(rng.uniform(20, 60), rng.uniform(20, 60), rng.uniform(0, 8), 6)
    holes = [
        poly2d.translate2d(
            poly2d.circle(rng.uniform(0.5, 3), rng.randint(3, 24)), -6 + 6 * k, rng.uniform(-3, 3)
        )
        for k in range(rng.randint(0, 3))
    ]
    assert_solid(build.extrude([outer, *holes], 0, rng.uniform(0.5, 5)))


@pytest.mark.parametrize("seed", range(10))
def test_random_helix_sweeps(seed: int) -> None:
    rng = random.Random(seed)
    w, h = rng.uniform(0.5, 3), rng.uniform(0.5, 3)
    section: list[Vec2] = [(0.0, 0.0), (w, 0.0), (w / 2, h)]
    pitch = h + rng.uniform(0.2, 3)
    m = build.sweep_helix(
        section, rng.uniform(2, 20), pitch, rng.uniform(0.3, 4), rng.randint(12, 64)
    )
    assert_solid(m)
