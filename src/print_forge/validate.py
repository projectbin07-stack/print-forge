"""Printability checks shared by every product family.

Severities: ``error`` means the part should not be printed as designed (the CLI refuses to write
it without ``--force``), ``warning`` means it will probably print but with a known risk, ``note``
is information such as a bridge span or a slicer setting to use.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .mesh import Mesh
from .printers import DEFAULT_PRINTER, PRINTERS, Printer

ERROR = "error"
WARNING = "warning"
NOTE = "note"

#: Facets of a tessellated curved surface can be slightly steeper than the smooth design.
OVERHANG_TOLERANCE_DEG = 1.0
#: Downward faces this close to horizontal are treated as bridges, not slopes.
BRIDGE_ANGLE_DEG = 85.0


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code, "message": self.message}


@dataclass(frozen=True)
class PrintSettings:
    """The machine context a part is validated against."""

    printer: Printer = field(default_factory=lambda: PRINTERS[DEFAULT_PRINTER])
    nozzle: float = 0.4
    overhang_limit: float = 45.0  # degrees from vertical
    layer_height: float = 0.2

    def __post_init__(self) -> None:
        if self.nozzle <= 0:
            raise ValueError("nozzle must be positive")
        if not 0 < self.overhang_limit < 90:
            raise ValueError("overhang limit must be between 0 and 90 degrees")
        if self.layer_height <= 0:
            raise ValueError("layer height must be positive")


def wall_issue(label: str, value: float, settings: PrintSettings, code: str) -> list[Issue]:
    """A wall narrower than one nozzle width cannot be printed; below two widths it prints as
    single extrusion lines (weak, and slicers may drop parts of it)."""
    nz = settings.nozzle
    if value < nz:
        return [Issue(ERROR, code, f"{label} is {value:.2f} mm, below the {nz:g} mm nozzle")]
    if value < 2 * nz - 1e-9:
        return [
            Issue(
                WARNING,
                code,
                f"{label} is {value:.2f} mm, below two line widths ({2 * nz:g} mm): it will "
                "print as single lines",
            )
        ]
    return []


def bed_issues(mesh: Mesh, settings: PrintSettings) -> list[Issue]:
    sx, sy, sz = mesh.size()
    p = settings.printer
    if sz > p.z:
        return [Issue(ERROR, "bed_fit", f"height {sz:.1f} mm exceeds {p.label()}")]
    fits = (sx <= p.x and sy <= p.y) or (sy <= p.x and sx <= p.y)
    if not fits:
        return [Issue(ERROR, "bed_fit", f"footprint {sx:.1f} x {sy:.1f} mm exceeds {p.label()}")]
    return []


@dataclass
class OverhangReport:
    max_angle: float  # steepest downward face that is not on the bed, degrees from vertical
    over_limit_area: float  # mm^2 steeper than the limit (bridges excluded)
    bridge_area: float  # mm^2 of near-horizontal downward faces above the bed
    bridge_levels: list[float]  # distinct heights (mm) of bridge faces


def overhangs(mesh: Mesh, limit: float) -> OverhangReport:
    lo, _ = mesh.bounds()
    z0 = lo[2]
    max_angle = 0.0
    over = 0.0
    bridge = 0.0
    levels: set[float] = set()
    vs = mesh.vertices
    for f, (a, b, c) in enumerate(mesh.faces):
        za, zb, zc = vs[a][2], vs[b][2], vs[c][2]
        if max(za, zb, zc) - z0 < 1e-6:
            continue  # rests on the bed
        n = mesh.face_normal(f)
        if n[2] >= 0:
            continue
        ang = math.degrees(math.asin(min(1.0, -n[2])))
        x1, y1, z1 = vs[a]
        ux, uy, uz = vs[b][0] - x1, vs[b][1] - y1, vs[b][2] - z1
        wx, wy, wz = vs[c][0] - x1, vs[c][1] - y1, vs[c][2] - z1
        area = 0.5 * math.sqrt(
            (uy * wz - uz * wy) ** 2 + (uz * wx - ux * wz) ** 2 + (ux * wy - uy * wx) ** 2
        )
        if ang >= BRIDGE_ANGLE_DEG:
            bridge += area
            levels.add(round((za + zb + zc) / 3 - z0, 2))
            continue
        max_angle = max(max_angle, ang)
        if ang > limit + OVERHANG_TOLERANCE_DEG:
            over += area
    return OverhangReport(max_angle, over, bridge, sorted(levels))


def overhang_issues(mesh: Mesh, settings: PrintSettings, bridges_ok: bool = False) -> list[Issue]:
    rep = overhangs(mesh, settings.overhang_limit)
    out: list[Issue] = []
    if rep.over_limit_area > 0.05:
        out.append(
            Issue(
                ERROR,
                "overhang",
                f"{rep.over_limit_area:.1f} mm^2 of surface is steeper than the "
                f"{settings.overhang_limit:g} deg overhang limit (steepest "
                f"{rep.max_angle:.1f} deg): needs support",
            )
        )
    if rep.bridge_area > 0.05:
        levels = ", ".join(f"{z:g}" for z in rep.bridge_levels[:4])
        if bridges_ok:
            out.append(
                Issue(
                    NOTE,
                    "bridge",
                    f"{rep.bridge_area:.1f} mm^2 of horizontal ceiling at z = {levels} mm is "
                    "printed as a bridge (no support)",
                )
            )
        else:
            out.append(
                Issue(
                    ERROR,
                    "bridge",
                    f"{rep.bridge_area:.1f} mm^2 of horizontal downward surface at z = "
                    f"{levels} mm needs support",
                )
            )
    return out


def mesh_issues(mesh: Mesh) -> list[Issue]:
    """Topology audit; a failure here is a bug in print-forge, reported rather than hidden."""
    t = mesh.topology()
    if t.closed:
        return []
    return [
        Issue(
            ERROR,
            "mesh",
            f"internal error: mesh is not closed ({t.boundary_edges} open, "
            f"{t.non_manifold_edges} non-manifold, {t.inconsistent_edges} flipped edges, "
            f"{t.degenerate_faces} degenerate faces)",
        )
    ]


def has_errors(issues: list[Issue]) -> bool:
    return any(i.severity == ERROR for i in issues)
