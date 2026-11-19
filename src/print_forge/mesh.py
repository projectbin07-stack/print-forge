"""Indexed triangle mesh with transforms, measurements and a topology audit.

A :class:`Mesh` is a list of vertex positions and a list of index triples. Faces are wound
counter-clockwise when seen from outside (right-hand rule gives the outward normal), which is
what STL and 3MF expect.

``volume``/``area`` have an optional numpy path for large meshes; the pure-Python path gives the
same numbers (tested) so numpy is never required.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from .vec import Vec3, cross, dot, sub

Face = tuple[int, int, int]

try:  # optional speed-up
    import numpy as _np

    HAVE_NUMPY = True
except ImportError:  # pragma: no cover - exercised in the CI job that uninstalls numpy
    _np = None  # type: ignore[assignment]
    HAVE_NUMPY = False

_NUMPY_MIN_FACES = 2000


def _use_numpy(flag: bool | None, n_faces: int) -> bool:
    if flag is None:
        return HAVE_NUMPY and n_faces >= _NUMPY_MIN_FACES
    if flag and not HAVE_NUMPY:
        raise RuntimeError("numpy requested but not installed")
    return flag


@dataclass
class Topology:
    """Result of :meth:`Mesh.topology`. A printable solid has every count at zero."""

    boundary_edges: int
    non_manifold_edges: int
    inconsistent_edges: int
    degenerate_faces: int
    shells: int
    unused_vertices: int

    @property
    def closed(self) -> bool:
        """Every edge is shared by exactly two faces that traverse it in opposite directions."""
        return (
            self.boundary_edges == 0
            and self.non_manifold_edges == 0
            and self.inconsistent_edges == 0
            and self.degenerate_faces == 0
        )


@dataclass
class Mesh:
    vertices: list[Vec3] = field(default_factory=list)
    faces: list[Face] = field(default_factory=list)
    name: str = "part"

    # ------------------------------------------------------------------ construction helpers
    def add_vertex(self, p: Vec3) -> int:
        self.vertices.append((float(p[0]), float(p[1]), float(p[2])))
        return len(self.vertices) - 1

    def add_vertices(self, pts: Iterable[Vec3]) -> list[int]:
        return [self.add_vertex(p) for p in pts]

    def add_face(self, a: int, b: int, c: int) -> None:
        self.faces.append((a, b, c))

    def add_quad(self, a: int, b: int, c: int, d: int) -> None:
        """Add quad a-b-c-d (counter-clockwise from outside) as two triangles.

        The shorter diagonal is used, which keeps twisted quads closer to the intended surface.
        """
        va, vb, vc, vd = (self.vertices[i] for i in (a, b, c, d))
        ac = sub(vc, va)
        bd = sub(vd, vb)
        if dot(ac, ac) <= dot(bd, bd):
            self.faces.append((a, b, c))
            self.faces.append((a, c, d))
        else:
            self.faces.append((a, b, d))
            self.faces.append((b, c, d))

    def flip(self) -> Mesh:
        """Reverse the winding of every face in place and return self."""
        self.faces = [(a, c, b) for a, b, c in self.faces]
        return self

    def copy(self, name: str | None = None) -> Mesh:
        return Mesh(list(self.vertices), list(self.faces), self.name if name is None else name)

    # ------------------------------------------------------------------------------ transforms
    def mapped(self, fn: Callable[[Vec3], Vec3], *, mirror: bool = False) -> Mesh:
        """New mesh with ``fn`` applied to every vertex. Pass ``mirror`` for maps with a
        negative determinant so the winding is reversed and normals stay outward."""
        out = Mesh([fn(p) for p in self.vertices], list(self.faces), self.name)
        return out.flip() if mirror else out

    def translated(self, dx: float, dy: float, dz: float) -> Mesh:
        return self.mapped(lambda p: (p[0] + dx, p[1] + dy, p[2] + dz))

    def scaled(self, sx: float, sy: float | None = None, sz: float | None = None) -> Mesh:
        sy = sx if sy is None else sy
        sz = sx if sz is None else sz
        if sx == 0 or sy == 0 or sz == 0:
            raise ValueError("scale factors must be non-zero")
        return self.mapped(lambda p: (p[0] * sx, p[1] * sy, p[2] * sz), mirror=sx * sy * sz < 0)

    def rotated_z(self, degrees: float) -> Mesh:
        c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
        return self.mapped(lambda p: (c * p[0] - s * p[1], s * p[0] + c * p[1], p[2]))

    def rotated_x(self, degrees: float) -> Mesh:
        c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
        return self.mapped(lambda p: (p[0], c * p[1] - s * p[2], s * p[1] + c * p[2]))

    def rotated_y(self, degrees: float) -> Mesh:
        c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
        return self.mapped(lambda p: (c * p[0] + s * p[2], p[1], -s * p[0] + c * p[2]))

    def on_bed(self) -> Mesh:
        """Translate so the lowest point is at z = 0 and the footprint is centred on x = y = 0."""
        lo, hi = self.bounds()
        return self.translated(-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2])

    @staticmethod
    def merged(meshes: Sequence[Mesh], name: str = "merged") -> Mesh:
        """Disjoint union: vertices and faces are concatenated, nothing is joined."""
        out = Mesh(name=name)
        for m in meshes:
            base = len(out.vertices)
            out.vertices.extend(m.vertices)
            out.faces.extend((a + base, b + base, c + base) for a, b, c in m.faces)
        return out

    # ---------------------------------------------------------------------------- measurement
    def triangles(self) -> list[tuple[Vec3, Vec3, Vec3]]:
        v = self.vertices
        return [(v[a], v[b], v[c]) for a, b, c in self.faces]

    def bounds(self) -> tuple[Vec3, Vec3]:
        if not self.vertices:
            return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
        xs = [p[0] for p in self.vertices]
        ys = [p[1] for p in self.vertices]
        zs = [p[2] for p in self.vertices]
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))

    def size(self) -> Vec3:
        lo, hi = self.bounds()
        return (hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])

    def volume(self, use_numpy: bool | None = None) -> float:
        """Signed volume (mm^3) by the divergence theorem; positive for outward winding."""
        if _use_numpy(use_numpy, len(self.faces)):
            v = _np.asarray(self.vertices, dtype=float)
            f = _np.asarray(self.faces, dtype=_np.int64).reshape(-1, 3)
            a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
            return float(_np.einsum("ij,ij->", a, _np.cross(b, c)) / 6.0)
        total = 0.0
        vs = self.vertices
        for i, j, k in self.faces:
            total += dot(vs[i], cross(vs[j], vs[k]))
        return total / 6.0

    def area(self, use_numpy: bool | None = None) -> float:
        if _use_numpy(use_numpy, len(self.faces)):
            v = _np.asarray(self.vertices, dtype=float)
            f = _np.asarray(self.faces, dtype=_np.int64).reshape(-1, 3)
            cr = _np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
            return float(_np.linalg.norm(cr, axis=1).sum() / 2.0)
        total = 0.0
        vs = self.vertices
        for i, j, k in self.faces:
            c = cross(sub(vs[j], vs[i]), sub(vs[k], vs[i]))
            total += math.sqrt(dot(c, c))
        return total / 2.0

    def face_normal(self, f: int) -> Vec3:
        a, b, c = (self.vertices[i] for i in self.faces[f])
        n = cross(sub(b, a), sub(c, a))
        ln = math.sqrt(dot(n, n))
        return (0.0, 0.0, 0.0) if ln == 0 else (n[0] / ln, n[1] / ln, n[2] / ln)

    # -------------------------------------------------------------------------------- topology
    def topology(self) -> Topology:
        directed: dict[tuple[int, int], int] = {}
        degenerate = 0
        vs = self.vertices
        for a, b, c in self.faces:
            if a in (b, c) or b == c:
                degenerate += 1
                continue
            n = cross(sub(vs[b], vs[a]), sub(vs[c], vs[a]))
            if dot(n, n) <= 1e-24:
                degenerate += 1
            for e in ((a, b), (b, c), (c, a)):
                directed[e] = directed.get(e, 0) + 1
        undirected: dict[tuple[int, int], tuple[int, int]] = {}
        for (a, b), uses in directed.items():
            key = (a, b) if a < b else (b, a)
            fwd, rev = undirected.get(key, (0, 0))
            undirected[key] = (fwd + uses, rev) if a < b else (fwd, rev + uses)
        boundary = non_manifold = inconsistent = 0
        for fwd, rev in undirected.values():
            total = fwd + rev
            if total == 1:
                boundary += 1
            elif total > 2:
                non_manifold += 1
            elif fwd != 1:  # two uses in the same direction
                inconsistent += 1
        used = {i for f in self.faces for i in f}
        return Topology(
            boundary_edges=boundary,
            non_manifold_edges=non_manifold,
            inconsistent_edges=inconsistent,
            degenerate_faces=degenerate,
            shells=self.shell_count(),
            unused_vertices=len(self.vertices) - len(used),
        )

    def shell_count(self) -> int:
        """Number of edge-connected face groups (union-find over vertices of faces)."""
        parent = list(range(len(self.vertices)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for a, b, c in self.faces:
            ra, rb, rc = find(a), find(b), find(c)
            parent[rb] = ra
            parent[find(rc)] = ra
        return len({find(i) for f in self.faces for i in f})

    def close_vertex_pairs(self, tolerance: float) -> int:
        """Count distinct vertices closer than ``tolerance`` (they would be welded by a reader
        such as stl-doctor and could change the topology). Uses a spatial hash."""
        cell = max(tolerance, 1e-12)
        grid: dict[tuple[int, int, int], list[int]] = {}
        count = 0
        tol2 = tolerance * tolerance
        for i, p in enumerate(self.vertices):
            key = (math.floor(p[0] / cell), math.floor(p[1] / cell), math.floor(p[2] / cell))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        for j in grid.get((key[0] + dx, key[1] + dy, key[2] + dz), ()):
                            q = self.vertices[j]
                            d = sub(p, q)
                            if dot(d, d) < tol2:
                                count += 1
            grid.setdefault(key, []).append(i)
        return count
