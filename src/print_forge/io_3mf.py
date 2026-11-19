"""3MF writer (zip + XML, 3MF Core Specification 1.x) and a small reader for round trips.

Each distinct mesh becomes one ``<object type="model" name="...">``; every placed copy is a
``<build><item>`` that references it with a translation transform, so 40 identical beads are
stored once. Units are millimetres (``unit="millimeter"``).
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from . import __version__
from .mesh import Mesh
from .vec import Vec3

CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
</Types>
"""
_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel0"
  Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""


@dataclass(frozen=True)
class Placement:
    """A copy of object ``obj`` (index into the object list) translated by (x, y, z) mm."""

    obj: int
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


def _num(v: float) -> str:
    text = f"{v:.6f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def model_xml(objects: list[Mesh], items: list[Placement], title: str) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<model unit="millimeter" xml:lang="en-US" xmlns="{CORE_NS}">',
        f' <metadata name="Title">{escape(title)}</metadata>',
        f' <metadata name="Application">print-forge {__version__}</metadata>',
        " <resources>",
    ]
    for i, mesh in enumerate(objects, start=1):
        parts.append(f'  <object id="{i}" type="model" name={quoteattr(mesh.name)}>')
        parts.append("   <mesh>")
        parts.append("    <vertices>")
        parts.extend(
            f'     <vertex x="{_num(x)}" y="{_num(y)}" z="{_num(z)}"/>' for x, y, z in mesh.vertices
        )
        parts.append("    </vertices>")
        parts.append("    <triangles>")
        parts.extend(f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in mesh.faces)
        parts.append("    </triangles>")
        parts.append("   </mesh>")
        parts.append("  </object>")
    parts.append(" </resources>")
    parts.append(" <build>")
    for it in items:
        if not 0 <= it.obj < len(objects):
            raise ValueError(f"placement refers to missing object {it.obj}")
        tr = f"1 0 0 0 1 0 0 0 1 {_num(it.x)} {_num(it.y)} {_num(it.z)}"
        parts.append(f'  <item objectid="{it.obj + 1}" transform="{tr}"/>')
    parts.append(" </build>")
    parts.append("</model>")
    return "\n".join(parts) + "\n"


def threemf_bytes(
    objects: list[Mesh], items: list[Placement] | None = None, title: str = ""
) -> bytes:
    if items is None:
        items = [Placement(i) for i in range(len(objects))]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
        zf.writestr("_rels/.rels", _RELS)
        zf.writestr("3D/3dmodel.model", model_xml(objects, items, title or objects[0].name))
    return buf.getvalue()


def write_3mf(
    path: str | Path, objects: list[Mesh], items: list[Placement] | None = None, title: str = ""
) -> None:
    Path(path).write_bytes(threemf_bytes(objects, items, title))


@dataclass
class ThreeMF:
    """What :func:`read_3mf` found: objects by id, build items and the model attributes."""

    unit: str
    title: str
    objects: dict[int, Mesh]
    items: list[tuple[int, tuple[float, ...]]]

    def placed(self) -> list[Mesh]:
        """Every build item as a mesh in plate coordinates (transforms applied)."""
        out = []
        for oid, m in self.items:
            out.append(self.objects[oid].mapped(_affine(m)))
        return out


def _affine(m: tuple[float, ...]) -> Callable[[Vec3], Vec3]:
    """3MF row-vector transform (12 numbers) as a point function."""

    def apply(p: Vec3) -> Vec3:
        return (
            p[0] * m[0] + p[1] * m[3] + p[2] * m[6] + m[9],
            p[0] * m[1] + p[1] * m[4] + p[2] * m[7] + m[10],
            p[0] * m[2] + p[1] * m[5] + p[2] * m[8] + m[11],
        )

    return apply


def read_3mf(path: str | Path) -> ThreeMF:
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("3D/3dmodel.model"))
    q = f"{{{CORE_NS}}}"
    title = ""
    for md in root.findall(f"{q}metadata"):
        if md.get("name") == "Title":
            title = md.text or ""
    objects: dict[int, Mesh] = {}
    for obj in root.iter(f"{q}object"):
        mesh = Mesh(name=obj.get("name", ""))
        for v in obj.iter(f"{q}vertex"):
            mesh.add_vertex((float(v.get("x", 0)), float(v.get("y", 0)), float(v.get("z", 0))))
        for t in obj.iter(f"{q}triangle"):
            mesh.add_face(int(t.get("v1", 0)), int(t.get("v2", 0)), int(t.get("v3", 0)))
        objects[int(obj.get("id", 0))] = mesh
    items = []
    for it in root.iter(f"{q}item"):
        tr = it.get("transform", "1 0 0 0 1 0 0 0 1 0 0 0")
        items.append((int(it.get("objectid", 0)), tuple(float(x) for x in tr.split())))
    return ThreeMF(root.get("unit", "millimeter"), title, objects, items)
