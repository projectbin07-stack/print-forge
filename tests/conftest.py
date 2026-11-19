"""Shared test helpers."""

from __future__ import annotations

import os

import pytest

from print_forge.mesh import Mesh

#: CI sets these so that optional cross-project checks fail instead of being skipped.
REQUIRE_STL_DOCTOR = os.environ.get("PRINT_FORGE_REQUIRE_STL_DOCTOR") == "1"
REQUIRE_PLANNER = os.environ.get("PRINT_FORGE_REQUIRE_PLANNER") == "1"


def assert_solid(mesh: Mesh, weld_tol: float = 1e-4) -> None:
    """Closed, consistently wound, outward (positive volume), no vertices a reader would weld."""
    topo = mesh.topology()
    assert topo.boundary_edges == 0, topo
    assert topo.non_manifold_edges == 0, topo
    assert topo.inconsistent_edges == 0, topo
    assert topo.degenerate_faces == 0, topo
    assert topo.unused_vertices == 0, topo
    assert mesh.volume() > 0
    assert mesh.close_vertex_pairs(weld_tol) == 0


def optional_import(module: str, required: bool) -> object:
    """Import ``module`` or skip the test; when ``required`` (CI), fail instead."""
    try:
        return __import__(module, fromlist=["_"])
    except ImportError:
        if required:
            pytest.fail(f"{module} is required in this environment but is not installed")
        pytest.skip(f"{module} not installed")
