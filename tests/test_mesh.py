from __future__ import annotations

import math

import pytest

from conftest import assert_solid
from print_forge import build
from print_forge.mesh import HAVE_NUMPY, Mesh


def test_box_volume_area_bounds() -> None:
    m = build.box(10, 20, 30)
    # 10 * 20 * 30 = 6000; area 2 * (200 + 300 + 600) = 2200
    assert m.volume() == pytest.approx(6000)
    assert m.area() == pytest.approx(2200)
    assert m.bounds() == ((-5, -10, 0), (5, 10, 30))
    assert m.size() == (10, 20, 30)
    assert_solid(m)


@pytest.mark.skipif(not HAVE_NUMPY, reason="numpy not installed")
def test_numpy_and_pure_python_agree() -> None:
    m = build.sphere(7, 64, 32)
    assert len(m.faces) > 2000
    assert m.volume(use_numpy=True) == pytest.approx(m.volume(use_numpy=False), rel=1e-12)
    assert m.area(use_numpy=True) == pytest.approx(m.area(use_numpy=False), rel=1e-12)


def test_numpy_flag_without_numpy_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import print_forge.mesh as mesh_mod

    monkeypatch.setattr(mesh_mod, "HAVE_NUMPY", False)
    with pytest.raises(RuntimeError):
        build.box(1, 1, 1).volume(use_numpy=True)
    # automatic choice falls back to pure Python
    assert build.sphere(5, 64, 32).volume() > 0


def test_transforms_keep_solid_and_volume() -> None:
    m = build.cylinder(5, 10, 32)
    v = m.volume()
    for t in (
        m.translated(3, -2, 7),
        m.rotated_x(30),
        m.rotated_y(-45),
        m.rotated_z(90),
        m.scaled(-1, 1, 1),  # mirror: winding must be reversed to stay outward
    ):
        assert t.volume() == pytest.approx(v)
        assert_solid(t)
    assert m.scaled(2).volume() == pytest.approx(8 * v)
    with pytest.raises(ValueError):
        m.scaled(0)


def test_on_bed_centres_footprint() -> None:
    m = build.box(4, 6, 2).translated(10, 20, 5).on_bed()
    lo, hi = m.bounds()
    assert lo == pytest.approx((-2, -3, 0))
    assert hi == pytest.approx((2, 3, 2))


def test_topology_detects_problems() -> None:
    m = build.box(1, 1, 1)
    open_m = Mesh(list(m.vertices), m.faces[:-1])
    assert open_m.topology().boundary_edges == 3
    flipped = Mesh(list(m.vertices), [*m.faces[:-1], tuple(reversed(m.faces[-1]))])  # type: ignore[list-item]
    assert flipped.topology().inconsistent_edges == 3
    doubled = Mesh(list(m.vertices), [*m.faces, m.faces[0]])
    assert doubled.topology().non_manifold_edges == 3
    degen = Mesh([(0, 0, 0), (1, 0, 0), (2, 0, 0)], [(0, 1, 2), (0, 0, 1)])
    assert degen.topology().degenerate_faces == 2
    assert not degen.topology().closed


def test_merged_counts_shells() -> None:
    a = build.box(1, 1, 1)
    b = build.box(1, 1, 1).translated(5, 0, 0)
    m = Mesh.merged([a, b])
    assert m.shell_count() == 2
    assert m.volume() == pytest.approx(2)
    assert m.topology().closed


def test_close_vertex_pairs() -> None:
    m = Mesh([(0, 0, 0), (0, 0, 5e-5), (1, 0, 0), (1.001, 0, 0)])
    assert m.close_vertex_pairs(1e-4) == 1
    assert m.close_vertex_pairs(1e-2) == 2


def test_add_quad_uses_shorter_diagonal() -> None:
    m = Mesh()
    ids = m.add_vertices([(0, 0, 0), (10, 0, 0), (10, 1, 0), (0, 1, 0)])
    m.add_quad(*ids)
    # diagonals 0-2 and 1-3 have equal length here; with a skewed quad the shorter one wins
    m2 = Mesh()
    ids2 = m2.add_vertices([(0, 0, 0), (10, 0, 0), (12, 1, 0), (2, 1, 0)])
    m2.add_quad(*ids2)
    used = {frozenset(e) for f in m2.faces for e in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0]))}
    assert frozenset((1, 3)) in used  # |1-3| = sqrt(65) < |0-2| = sqrt(145)
    assert math.isclose(m.area(), 10.0)
