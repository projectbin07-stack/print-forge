from __future__ import annotations

import struct
import zipfile
from pathlib import Path

import pytest

from print_forge import build
from print_forge.families import FAMILIES
from print_forge.io_3mf import Placement, model_xml, read_3mf, threemf_bytes, write_3mf
from print_forge.io_stl import read_stl, stl_bytes, write_stl
from print_forge.mesh import Mesh


def sample() -> Mesh:
    fam = FAMILIES["letter"]
    m = fam.generate(fam.make_params("tile-a")).mesh
    m.name = "tile A"
    return m


def test_binary_stl_layout() -> None:
    m = build.box(1, 2, 3)
    data = stl_bytes(m)
    assert len(data) == 84 + 50 * len(m.faces)
    assert struct.unpack_from("<I", data, 80)[0] == 12
    # first facet: stored normal equals the face normal
    normal = struct.unpack_from("<3f", data, 84)
    assert normal == pytest.approx(m.face_normal(0))


@pytest.mark.parametrize("ascii_stl", [False, True])
def test_stl_round_trip(tmp_path: Path, ascii_stl: bool) -> None:
    m = sample()
    path = tmp_path / "part.stl"
    write_stl(path, m, ascii=ascii_stl)
    back = read_stl(path)
    assert len(back.faces) == len(m.faces)
    assert len(back.vertices) == len(m.vertices)  # re-indexed to the same vertex set
    assert back.topology().closed
    assert back.volume() == pytest.approx(m.volume(), rel=1e-5)
    lo, hi = back.bounds()
    lo0, hi0 = m.bounds()
    assert lo == pytest.approx(lo0, abs=1e-4) and hi == pytest.approx(hi0, abs=1e-4)


def test_ascii_stl_header_and_bad_file(tmp_path: Path) -> None:
    text = stl_bytes(sample(), ascii=True).decode()
    assert text.startswith("solid tile_A")
    assert text.rstrip().endswith("endsolid tile_A")
    bad = tmp_path / "bad.stl"
    bad.write_text("solid x\n vertex 0 0 0\n vertex 1 0 0\nendsolid x\n")
    with pytest.raises(ValueError):
        read_stl(bad)


def test_3mf_round_trip_with_shared_objects(tmp_path: Path) -> None:
    a = sample()
    b = build.cylinder(3, 4, 24, name="peg & <cap>")
    items = [Placement(0, 10, 20), Placement(0, 50, 20), Placement(1, 30, 60, 0)]
    path = tmp_path / "plate.3mf"
    write_3mf(path, [a, b], items, title="plate 1")
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
    assert {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"} <= names
    doc = read_3mf(path)
    assert doc.unit == "millimeter"
    assert doc.title == "plate 1"
    assert [o.name for o in doc.objects.values()] == ["tile A", "peg & <cap>"]
    assert len(doc.items) == 3
    placed = doc.placed()
    assert placed[0].volume() == pytest.approx(a.volume(), rel=1e-6)
    lo, _ = placed[1].bounds()
    lo_a, _ = a.bounds()
    assert lo[0] == pytest.approx(lo_a[0] + 50, abs=1e-5)
    for m in placed:
        assert m.topology().closed


def test_3mf_defaults_and_errors() -> None:
    data = threemf_bytes([build.box(1, 1, 1, name="cube")])
    assert data[:2] == b"PK"
    with pytest.raises(ValueError):
        model_xml([build.box(1, 1, 1)], [Placement(3)], "x")
    xml = model_xml([build.box(1, 1, 1)], [Placement(0, -0.0000001, 1.5)], "t")
    assert 'transform="1 0 0 0 1 0 0 0 1 0 1.5 0"' in xml
