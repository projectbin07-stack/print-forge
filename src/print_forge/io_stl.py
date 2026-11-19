"""Binary and ASCII STL writer, plus a reader used for round-trip tests.

STL stores loose triangles; the reader re-indexes them by exact coordinate match (float32 values
written by :func:`write_stl` come back bit-identical), which is enough to check a round trip.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from pathlib import Path

from .mesh import Mesh
from .vec import Vec3, triangle_normal

_HEADER = b"print-forge binary STL, units: mm"


def stl_bytes(mesh: Mesh, ascii: bool = False) -> bytes:
    if ascii:
        name = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in mesh.name) or "part"
        lines = [f"solid {name}"]
        for a, b, c in mesh.triangles():
            n = triangle_normal(a, b, c)
            lines.append(f"  facet normal {n[0]:.6e} {n[1]:.6e} {n[2]:.6e}")
            lines.append("    outer loop")
            for p in (a, b, c):
                lines.append(f"      vertex {p[0]:.6e} {p[1]:.6e} {p[2]:.6e}")
            lines.append("    endloop")
            lines.append("  endfacet")
        lines.append(f"endsolid {name}")
        return ("\n".join(lines) + "\n").encode("ascii")
    out = bytearray(_HEADER.ljust(80, b" "))
    out += struct.pack("<I", len(mesh.faces))
    pack = struct.Struct("<12fH").pack
    for a, b, c in mesh.triangles():
        n = triangle_normal(a, b, c)
        out += pack(*n, *a, *b, *c, 0)
    return bytes(out)


def write_stl(path: str | Path, mesh: Mesh, ascii: bool = False) -> None:
    Path(path).write_bytes(stl_bytes(mesh, ascii=ascii))


def read_stl(path: str | Path) -> Mesh:
    data = Path(path).read_bytes()
    if len(data) >= 84:
        (count,) = struct.unpack_from("<I", data, 80)
        if 84 + 50 * count == len(data):
            tris = []
            for i in range(count):
                vals = struct.unpack_from("<12f", data, 84 + 50 * i)
                tris.append((vals[3:6], vals[6:9], vals[9:12]))
            return _index(tris, Path(path).stem)
    text = data.decode("ascii", errors="replace")
    verts: list[Vec3] = []
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0] == "vertex":
            verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
    if len(verts) % 3:
        raise ValueError(f"{path}: vertex count {len(verts)} is not a multiple of 3")
    tris_a = [(verts[i], verts[i + 1], verts[i + 2]) for i in range(0, len(verts), 3)]
    return _index(tris_a, Path(path).stem)


def _index(tris: Sequence[Sequence[Sequence[float]]], name: str) -> Mesh:
    mesh = Mesh(name=name)
    lookup: dict[tuple[float, ...], int] = {}
    for tri in tris:
        ids = []
        for p in tri:
            key = tuple(p)
            if key not in lookup:
                lookup[key] = mesh.add_vertex((p[0], p[1], p[2]))
            ids.append(lookup[key])
        mesh.add_face(ids[0], ids[1], ids[2])
    return mesh
