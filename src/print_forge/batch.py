"""Batch planning: parts file -> packed plates (3MF) -> manifest and printfarm-planner jobs CSV.

A parts file (TOML) lists what to make::

    [plate]
    printer = "a1-mini"      # p1s, a1, a1-mini (the CLI --printer overrides it)
    spacing = 5.0            # mm between parts (between brims, if any)
    brim = 0.0               # mm brim allowance around every part
    edge_margin = 5.0        # mm kept clear at the bed edge
    material = "PLA:white"   # default spool, printfarm-planner syntax TYPE[:label]

    [filament]               # estimate model, see print_forge.estimate
    infill = 0.15

    [[part]]
    family = "bead"
    preset = "round-10"
    copies = 40
    material = "PLA:red"     # optional
    params = { cord = 1.5 }  # optional overrides

Parts are packed per material (one spool per plate). Plates with identical content and layout
are written once and counted as copies.
"""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__
from .estimate import Estimate, FilamentModel, estimate
from .families import FAMILIES, ParamError, Part
from .io_3mf import Placement, write_3mf
from .mesh import Mesh
from .packer import Item, pack
from .printers import Printer, get_printer
from .tomlread import loads
from .validate import ERROR, PrintSettings

#: Column order accepted by printfarm-planner's jobs CSV (its README, "Jobs CSV").
JOBS_COLUMNS = (
    "name",
    "copies",
    "print_time",
    "material",
    "nozzle_mm",
    "size_mm",
    "mass_g",
    "due",
    "priority",
    "models",
    "gcode_json",
)


class BatchError(ValueError):
    """The parts file is invalid or a part failed validation."""


@dataclass
class PartSpec:
    name: str
    family: str
    preset: str | None
    params: dict[str, Any]
    copies: int
    material: str


@dataclass
class BatchConfig:
    printer: Printer
    nozzle: float = 0.4
    overhang_limit: float = 45.0
    spacing: float = 5.0
    brim: float = 0.0
    edge_margin: float = 5.0
    material: str = "PLA"
    model: FilamentModel = field(default_factory=FilamentModel)

    def settings(self) -> PrintSettings:
        return PrintSettings(self.printer, self.nozzle, self.overhang_limit)


@dataclass
class PlateEntry:
    part: str  # part name
    x: float  # centre of the footprint on the bed, mm
    y: float
    rotated: bool


@dataclass
class Plate:
    number: int  # 1-based, after de-duplication
    material: str
    entries: list[PlateEntry]
    copies: int = 1

    @property
    def file_name(self) -> str:
        return f"plate-{self.number:02d}.3mf"

    def counts(self) -> dict[str, int]:
        return dict(sorted(Counter(e.part for e in self.entries).items()))


@dataclass
class BatchPlan:
    config: BatchConfig
    parts: dict[str, Part]
    specs: dict[str, PartSpec]
    estimates: dict[str, Estimate]
    plates: list[Plate]

    def plate_grams(self, plate: Plate) -> float:
        return sum(self.estimates[e.part].grams for e in plate.entries)

    def plate_minutes(self, plate: Plate) -> float:
        extrude = sum(self.estimates[e.part].print_min for e in plate.entries)
        return extrude + self.config.model.plate_overhead_min

    def plate_size(self, plate: Plate) -> tuple[float, float, float]:
        xs: list[float] = []
        ys: list[float] = []
        zmax = 0.0
        for e in plate.entries:
            sx, sy, sz = self.parts[e.part].mesh.size()
            w, h = (sy, sx) if e.rotated else (sx, sy)
            xs += [e.x - w / 2, e.x + w / 2]
            ys += [e.y - h / 2, e.y + h / 2]
            zmax = max(zmax, sz)
        return (max(xs) - min(xs), max(ys) - min(ys), zmax)


# --------------------------------------------------------------------------- parts file
def parse_parts(
    text: str, printer_override: str | None = None
) -> tuple[BatchConfig, list[PartSpec]]:
    data = loads(text)
    plate = data.get("plate", {})
    fil = data.get("filament", {})
    if not isinstance(plate, dict) or not isinstance(fil, dict):
        raise BatchError("[plate] and [filament] must be tables")
    try:
        printer = get_printer(printer_override or str(plate.get("printer", "p1s")))
        model = FilamentModel(
            **{k: v for k, v in fil.items() if k in FilamentModel.__dataclass_fields__}
        )
        config = BatchConfig(
            printer=printer,
            nozzle=float(plate.get("nozzle", 0.4)),
            overhang_limit=float(plate.get("overhang_limit", 45.0)),
            spacing=float(plate.get("spacing", 5.0)),
            brim=float(plate.get("brim", 0.0)),
            edge_margin=float(plate.get("edge_margin", 5.0)),
            material=str(plate.get("material", "PLA")),
            model=model,
        )
    except (TypeError, ValueError) as exc:
        raise BatchError(f"[plate]/[filament]: {exc}") from None
    unknown_fil = set(fil) - set(FilamentModel.__dataclass_fields__)
    if unknown_fil:
        raise BatchError(f"[filament] has unknown key(s): {', '.join(sorted(unknown_fil))}")
    raw_parts = data.get("part", [])
    if not isinstance(raw_parts, list) or not raw_parts:
        raise BatchError("the parts file needs at least one [[part]]")
    specs: list[PartSpec] = []
    used: set[str] = set()
    for i, rp in enumerate(raw_parts, start=1):
        if not isinstance(rp, dict):
            raise BatchError(f"part {i}: must be a table")
        family = str(rp.get("family", ""))
        if family not in FAMILIES:
            raise BatchError(f"part {i}: family must be one of {', '.join(FAMILIES)}")
        preset = rp.get("preset")
        copies = rp.get("copies", 1)
        if not isinstance(copies, int) or copies < 1:
            raise BatchError(f"part {i}: copies must be a positive whole number")
        params = rp.get("params", {})
        if not isinstance(params, dict):
            raise BatchError(f"part {i}: params must be a table")
        base = str(rp.get("name") or f"{family}-{preset or FAMILIES[family].default_preset}")
        name = base
        k = 2
        while name in used:
            name = f"{base}-{k}"
            k += 1
        used.add(name)
        specs.append(
            PartSpec(
                name=name,
                family=family,
                preset=str(preset) if preset is not None else None,
                params=dict(params),
                copies=copies,
                material=str(rp.get("material", config.material)),
            )
        )
    return config, specs


def load_parts_file(
    path: str | Path, printer_override: str | None = None
) -> tuple[BatchConfig, list[PartSpec]]:
    return parse_parts(Path(path).read_text(encoding="utf-8"), printer_override)


# ------------------------------------------------------------------------------ planning
def plan_batch(specs: list[PartSpec], config: BatchConfig, force: bool = False) -> BatchPlan:
    settings = config.settings()
    parts: dict[str, Part] = {}
    estimates: dict[str, Estimate] = {}
    spec_by_name: dict[str, PartSpec] = {}
    for spec in specs:
        fam = FAMILIES[spec.family]
        try:
            params = fam.make_params(spec.preset, spec.params)
            part = fam.generate(params, settings, name=spec.name)
        except ParamError as exc:
            raise BatchError(f"{spec.name}: {exc}") from None
        errors = [i for i in part.issues if i.severity == ERROR]
        if errors and not force:
            raise BatchError(
                f"{spec.name}: " + "; ".join(i.message for i in errors) + " (use --force to "
                "plate it anyway)"
            )
        part.mesh = part.mesh.on_bed()
        parts[spec.name] = part
        spec_by_name[spec.name] = spec
        estimates[spec.name] = estimate(part.mesh, config.model, vase_mode=part.vase_mode)

    plates: list[Plate] = []
    for material in dict.fromkeys(s.material for s in specs):
        items: list[Item] = []
        for spec in specs:
            if spec.material != material:
                continue
            sx, sy, _ = parts[spec.name].mesh.size()
            items.extend(Item(spec.name, sx, sy) for _ in range(spec.copies))
        placed = pack(
            items,
            config.printer.x,
            config.printer.y,
            config.spacing,
            config.brim,
            config.edge_margin,
        )
        by_plate: dict[int, list[PlateEntry]] = {}
        for pl in placed:
            by_plate.setdefault(pl.plate, []).append(
                PlateEntry(pl.key, pl.x + pl.w / 2, pl.y + pl.h / 2, pl.rotated)
            )
        for idx in sorted(by_plate):
            entries = sorted(by_plate[idx], key=lambda e: (e.part, e.y, e.x))
            sig = [(e.part, round(e.x, 3), round(e.y, 3), e.rotated) for e in entries]
            for existing in plates:
                if (
                    existing.material == material
                    and [
                        (e.part, round(e.x, 3), round(e.y, 3), e.rotated) for e in existing.entries
                    ]
                    == sig
                ):
                    existing.copies += 1
                    break
            else:
                plates.append(Plate(len(plates) + 1, material, entries))
    return BatchPlan(config, parts, spec_by_name, estimates, plates)


# ------------------------------------------------------------------------------- outputs
def plate_meshes(plan: BatchPlan, plate: Plate) -> tuple[list[Mesh], list[Placement]]:
    objects: list[Mesh] = []
    index: dict[tuple[str, bool], int] = {}
    items: list[Placement] = []
    for e in plate.entries:
        key = (e.part, e.rotated)
        if key not in index:
            mesh = plan.parts[e.part].mesh
            if e.rotated:
                mesh = mesh.rotated_z(90).on_bed()
                mesh.name = f"{e.part} (rotated)"
            index[key] = len(objects)
            objects.append(mesh)
        items.append(Placement(index[key], e.x, e.y, 0.0))
    return objects, items


def _duration(minutes: float) -> str:
    total = max(1, round(minutes))
    return f"{total // 60}h{total % 60:02d}m"


def jobs_csv(plan: BatchPlan) -> str:
    """printfarm-planner jobs CSV: one row per distinct plate, ``copies`` = identical plates.

    ``print_time`` is print-forge's rough estimate; after slicing, put a gcode-insight analysis
    in ``gcode_json`` and clear ``print_time`` so the planner uses the slicer's number."""
    buf = io.StringIO()
    buf.write(
        f"# print-forge {__version__}: print_time and mass_g are rough pre-slicing estimates "
        "(see README); replace with gcode-insight analyses after slicing.\n"
    )
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(JOBS_COLUMNS)
    for plate in plan.plates:
        sx, sy, sz = plan.plate_size(plate)
        writer.writerow(
            [
                plate.file_name.removesuffix(".3mf"),
                plate.copies,
                _duration(plan.plate_minutes(plate)),
                plate.material,
                f"{plan.config.nozzle:g}",
                f"{sx:.1f}x{sy:.1f}x{sz:.1f}",
                f"{plan.plate_grams(plate):.1f}",
                "",
                0,
                "",
                "",
            ]
        )
    return buf.getvalue()


def manifest_rows(plan: BatchPlan) -> list[dict[str, Any]]:
    rows = []
    for plate in plan.plates:
        for name, count in plate.counts().items():
            est = plan.estimates[name]
            rows.append(
                {
                    "plate": plate.file_name,
                    "plate_copies": plate.copies,
                    "material": plate.material,
                    "part": name,
                    "family": plan.parts[name].family,
                    "count": count,
                    "volume_mm3_each": round(est.volume_mm3, 1),
                    "filament_g_each": round(est.grams, 2),
                    "filament_g_on_plate": round(est.grams * count, 2),
                }
            )
    return rows


def manifest_csv(plan: BatchPlan) -> str:
    rows = manifest_rows(plan)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def totals(plan: BatchPlan) -> dict[str, Any]:
    parts_made = Counter[str]()
    grams = 0.0
    minutes = 0.0
    for plate in plan.plates:
        for name, count in plate.counts().items():
            parts_made[name] += count * plate.copies
        grams += plan.plate_grams(plate) * plate.copies
        minutes += plan.plate_minutes(plate) * plate.copies
    return {
        "plates_to_print": sum(p.copies for p in plan.plates),
        "distinct_plates": len(plan.plates),
        "parts": dict(sorted(parts_made.items())),
        "filament_g": round(grams, 1),
        "print_time_min": round(minutes, 1),
    }


def manifest_dict(plan: BatchPlan) -> dict[str, Any]:
    m = plan.config.model
    return {
        "generator": f"print-forge {__version__}",
        "printer": plan.config.printer.label(),
        "estimate_model": {
            "density_g_cm3": m.density,
            "infill": m.infill,
            "walls": m.walls,
            "line_width_mm": m.line_width,
            "flow_mm3_s": m.flow_mm3_s,
            "plate_overhead_min": m.plate_overhead_min,
            "note": "rough pre-slicing model; slicer numbers will differ",
        },
        "parts": {
            name: {
                "family": part.family,
                "params": part.params,
                "size_mm": [round(v, 2) for v in part.mesh.size()],
                "volume_mm3": round(plan.estimates[name].volume_mm3, 1),
                "filament_g": round(plan.estimates[name].grams, 2),
                "issues": [i.to_dict() for i in part.issues],
            }
            for name, part in plan.parts.items()
        },
        "plates": [
            {
                "file": plate.file_name,
                "copies": plate.copies,
                "material": plate.material,
                "counts": plate.counts(),
                "filament_g": round(plan.plate_grams(plate), 1),
                "print_time_min": round(plan.plate_minutes(plate), 1),
                "size_mm": [round(v, 1) for v in plan.plate_size(plate)],
            }
            for plate in plan.plates
        ],
        "totals": totals(plan),
    }


def write_outputs(plan: BatchPlan, out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for plate in plan.plates:
        objects, items = plate_meshes(plan, plate)
        path = out / plate.file_name
        write_3mf(path, objects, items, title=f"print-forge {plate.file_name}")
        written.append(path)
    for fname, text in (
        ("jobs.csv", jobs_csv(plan)),
        ("manifest.csv", manifest_csv(plan)),
        ("manifest.json", json.dumps(manifest_dict(plan), indent=2) + "\n"),
    ):
        path = out / fname
        path.write_text(text, encoding="utf-8", newline="")
        written.append(path)
    return written
