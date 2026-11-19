"""A deliberately simple filament and time model, for batch planning before slicing.

Normal parts:  shell = surface area x (walls x line width)
               filament volume = min(solid volume, shell + (solid volume - shell) x infill)
Vase mode:     filament volume = (side area) x line width + bottom area x bottom thickness
Mass:          volume x density (PLA 1.24 g/cm^3, the same default gcode-insight uses)
Time:          filament volume / effective flow + a fixed overhead per plate

The shell term treats top and bottom skins like walls of the same thickness and ignores
overlap at edges, brims, purge lines and supports, and the flow rate is an assumption, not a
measurement. Slicer estimates will differ (this project has not measured by how much); replace
the numbers with a gcode-insight analysis of the sliced file when you have it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .mesh import Mesh

FILAMENT_DIAMETER = 1.75


@dataclass(frozen=True)
class FilamentModel:
    density: float = 1.24  # g/cm^3
    infill: float = 0.15  # fraction of the interior
    walls: int = 2  # perimeters (also used as skin layers)
    line_width: float = 0.42  # mm
    bottom_thickness: float = 0.8  # mm, vase mode solid bottom
    flow_mm3_s: float = 8.0  # effective average volumetric rate including travel and slowdowns
    plate_overhead_min: float = 6.0  # heating, levelling, purge

    def __post_init__(self) -> None:
        if not 0 <= self.infill <= 1:
            raise ValueError("infill must be between 0 and 1")
        if self.density <= 0 or self.line_width <= 0 or self.flow_mm3_s <= 0:
            raise ValueError("density, line width and flow must be positive")
        if self.walls < 1:
            raise ValueError("walls must be at least 1")


@dataclass(frozen=True)
class Estimate:
    volume_mm3: float  # solid volume of the mesh
    filament_mm3: float  # extruded volume by the model
    grams: float
    metres: float
    print_min: float  # extrusion time only (no plate overhead)


def _flat_area(mesh: Mesh, at_bottom: bool) -> float:
    lo, hi = mesh.bounds()
    z_ref = lo[2] if at_bottom else hi[2]
    total = 0.0
    for f, face in enumerate(mesh.faces):
        if all(abs(mesh.vertices[i][2] - z_ref) < 1e-6 for i in face):
            n = mesh.face_normal(f)
            if (n[2] < -0.999) if at_bottom else (n[2] > 0.999):
                a, b, c = (mesh.vertices[i] for i in face)
                ux, uy = b[0] - a[0], b[1] - a[1]
                wx, wy = c[0] - a[0], c[1] - a[1]
                total += abs(ux * wy - uy * wx) / 2
    return total


def estimate(mesh: Mesh, model: FilamentModel, vase_mode: bool = False) -> Estimate:
    volume = mesh.volume()
    area = mesh.area()
    if vase_mode:
        bottom = _flat_area(mesh, at_bottom=True)
        top = _flat_area(mesh, at_bottom=False)
        fil = (area - bottom - top) * model.line_width + bottom * model.bottom_thickness
        fil = min(fil, volume)
    else:
        shell = area * model.walls * model.line_width
        fil = min(volume, shell + max(0.0, volume - shell) * model.infill)
    grams = fil / 1000.0 * model.density
    metres = fil / (math.pi * (FILAMENT_DIAMETER / 2) ** 2) / 1000.0
    return Estimate(volume, fil, grams, metres, fil / model.flow_mm3_s / 60.0)
