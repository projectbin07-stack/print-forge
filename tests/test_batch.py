"""Batch plan, manifest totals and the printfarm-planner jobs CSV.

printfarm-planner documents its jobs CSV in its README ("Jobs CSV"): columns name, copies,
print_time, material, nozzle_mm, size_mm, mass_g, due, priority, models, gcode_json; name is
required and unique; copies is a whole number >= 1; print_time is minutes (``90``), ``H:MM`` or
``1h30m``; material is spools joined with ``+``, each ``TYPE`` or ``TYPE:label``; size is
``XxYxZ`` in mm; mass is a positive number; lines starting with ``#`` are ignored.
``check_jobs_csv`` below re-implements exactly those rules. When printfarm-planner itself is
installed (CI installs it from its public repository), the CSV is also loaded with its own
loader.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from conftest import REQUIRE_PLANNER, assert_solid, optional_import
from print_forge.batch import (
    JOBS_COLUMNS,
    BatchConfig,
    BatchError,
    PartSpec,
    jobs_csv,
    load_parts_file,
    manifest_csv,
    manifest_dict,
    parse_parts,
    plan_batch,
    totals,
    write_outputs,
)
from print_forge.estimate import FilamentModel, estimate
from print_forge.io_3mf import read_3mf
from print_forge.printers import PRINTERS

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "parts.toml"
PLANNER_COLUMNS = (
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
_DURATION = re.compile(r"^(\d+(\.\d+)?|\d+:\d{2}|(\d+(\.\d+)?h)?(\d+(\.\d+)?m)?)$")
_SPOOL = re.compile(r"^[A-Za-z0-9-]+(:[^+]+)?$")
_SIZE = re.compile(r"^\d+(\.\d+)?x\d+(\.\d+)?x\d+(\.\d+)?$")


def check_jobs_csv(text: str, bed: tuple[float, float, float]) -> list[dict[str, str]]:
    """Validate a jobs CSV against printfarm-planner's documented rules; return the rows."""
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    reader = csv.DictReader(lines)
    assert reader.fieldnames is not None
    assert "name" in reader.fieldnames
    assert set(reader.fieldnames) <= set(PLANNER_COLUMNS)
    rows = list(reader)
    names = [r["name"] for r in rows]
    assert all(names) and len(set(names)) == len(names)
    for r in rows:
        assert int(r["copies"]) >= 1
        assert r["print_time"] and _DURATION.match(r["print_time"]), r["print_time"]
        assert all(_SPOOL.match(sp) for sp in r["material"].split("+")), r["material"]
        assert float(r["nozzle_mm"]) > 0
        assert _SIZE.match(r["size_mm"]), r["size_mm"]
        size = [float(v) for v in r["size_mm"].split("x")]
        assert size[0] <= bed[0] and size[1] <= bed[1] and size[2] <= bed[2]
        assert float(r["mass_g"]) > 0
        assert r["priority"] == "" or int(r["priority"]) >= 0
        assert r["gcode_json"] == ""
    return rows


@pytest.fixture(scope="module")
def example_plan() -> Any:
    config, specs = load_parts_file(EXAMPLE)
    return plan_batch(specs, config)


def test_example_parts_file(example_plan: Any) -> None:
    plan = example_plan
    assert plan.config.printer.key == "a1-mini"
    assert set(plan.parts) == {
        "bead-round-10",
        "bead-gem-12",
        "keychain-NAV",
        "cap-legend-n",
        "vase-tulip",
    }
    for part in plan.parts.values():
        assert_solid(part.mesh)
    # every requested copy is on some plate, counting identical plates
    t = totals(plan)
    assert t["parts"] == {
        "bead-gem-12": 24,
        "bead-round-10": 60,
        "cap-legend-n": 12,
        "keychain-NAV": 6,
        "vase-tulip": 4,
    }
    # one material per plate
    assert {p.material for p in plan.plates} == {"PLA:red", "PLA:white"}


def test_manifest_totals_add_up(example_plan: Any) -> None:
    plan = example_plan
    m = manifest_dict(plan)
    grams = sum(p["filament_g"] * p["copies"] for p in m["plates"])
    assert m["totals"]["filament_g"] == pytest.approx(grams, abs=0.2)
    rows = list(csv.DictReader(manifest_csv(plan).splitlines()))
    by_plate: dict[str, float] = {}
    for r in rows:
        # each value is rounded to 0.01 g, so the product can be off by count x 0.005
        assert float(r["filament_g_on_plate"]) == pytest.approx(
            float(r["filament_g_each"]) * int(r["count"]), abs=0.005 * int(r["count"]) + 0.006
        )
        by_plate[r["plate"]] = by_plate.get(r["plate"], 0.0) + float(r["filament_g_on_plate"])
    for p in m["plates"]:
        assert by_plate[p["file"]] == pytest.approx(p["filament_g"], abs=0.1)
    json.dumps(m)  # serialisable


def test_jobs_csv_follows_planner_rules(example_plan: Any) -> None:
    text = jobs_csv(example_plan)
    assert text.startswith("#")
    bed = PRINTERS["a1-mini"]
    rows = check_jobs_csv(text, (bed.x, bed.y, bed.z))
    assert len(rows) == len(example_plan.plates)
    assert tuple(text.splitlines()[1].split(",")) == JOBS_COLUMNS == PLANNER_COLUMNS


def test_jobs_csv_loads_in_printfarm_planner(example_plan: Any, tmp_path: Path) -> None:
    jobs_mod = optional_import("printfarm_planner.jobs", REQUIRE_PLANNER)
    path = tmp_path / "jobs.csv"
    path.write_text(jobs_csv(example_plan), encoding="utf-8")
    jobs = jobs_mod.load_jobs_csv(path, datetime(2026, 11, 23, 8, 0))  # type: ignore[attr-defined]
    assert [j.name for j in jobs] == [p.file_name.removesuffix(".3mf") for p in example_plan.plates]
    for job, plate in zip(jobs, example_plan.plates, strict=True):
        assert job.copies == plate.copies
        assert job.spools == (plate.material,)
        assert job.mass_g == pytest.approx(round(example_plan.plate_grams(plate), 1))
        assert job.print_time_min == pytest.approx(example_plan.plate_minutes(plate), abs=1.0)


def test_identical_plates_are_merged(tmp_path: Path) -> None:
    config = BatchConfig(printer=PRINTERS["a1-mini"], spacing=5, edge_margin=5)
    spec = PartSpec("bead", "bead", "round-10", {}, copies=250, material="PLA:blue")
    plan = plan_batch([spec], config)
    # 121 beads per plate (see test_packer): 121 + 121 + 8
    assert [(p.copies, len(p.entries)) for p in plan.plates] == [(2, 121), (1, 8)]
    written = write_outputs(plan, tmp_path)
    assert sorted(p.name for p in written) == [
        "jobs.csv",
        "manifest.csv",
        "manifest.json",
        "plate-01.3mf",
        "plate-02.3mf",
    ]
    doc = read_3mf(tmp_path / "plate-01.3mf")
    assert len(doc.objects) == 1 and len(doc.items) == 121
    rows = check_jobs_csv((tmp_path / "jobs.csv").read_text(), (180, 180, 180))
    assert [r["copies"] for r in rows] == ["2", "1"]
    # mass on a full plate = 121 x the per-bead estimate (rounded to 0.1 g)
    est = estimate(plan.parts["bead"].mesh, FilamentModel())
    assert float(rows[0]["mass_g"]) == pytest.approx(121 * est.grams, abs=0.06)


def test_rotated_parts_in_3mf(tmp_path: Path) -> None:
    config = BatchConfig(printer=PRINTERS["a1-mini"], spacing=4, edge_margin=4)
    specs = [
        PartSpec("long", "letter", "keychain", {"text": "PRINTFARM", "cap_height": 12}, 3, "PLA"),
    ]
    plan = plan_batch(specs, config)
    write_outputs(plan, tmp_path)
    for plate in plan.plates:
        doc = read_3mf(tmp_path / plate.file_name)
        for mesh in doc.placed():
            lo, hi = mesh.bounds()
            assert lo[0] >= 4 - 1e-6 and lo[1] >= 4 - 1e-6
            assert hi[0] <= 176 + 1e-6 and hi[1] <= 176 + 1e-6
            assert lo[2] == pytest.approx(0, abs=1e-6)


def test_parts_file_errors() -> None:
    with pytest.raises(BatchError, match="at least one"):
        parse_parts("[plate]\nprinter = 'p1s'\n")
    with pytest.raises(BatchError, match="family"):
        parse_parts("[[part]]\nfamily = 'spoon'\n")
    with pytest.raises(BatchError, match="copies"):
        parse_parts("[[part]]\nfamily = 'bead'\ncopies = 0\n")
    with pytest.raises(BatchError, match="unknown key"):
        parse_parts("[filament]\ncolour = 'red'\n[[part]]\nfamily = 'bead'\n")
    with pytest.raises(BatchError, match="printer"):
        parse_parts("[plate]\nprinter = 'ender'\n[[part]]\nfamily = 'bead'\n")
    config, specs = parse_parts(
        "[[part]]\nfamily = 'bead'\n[[part]]\nfamily = 'bead'\n", printer_override="a1"
    )
    assert config.printer.key == "a1"
    assert [s.name for s in specs] == ["bead-round-10", "bead-round-10-2"]


def test_failing_part_needs_force() -> None:
    config = BatchConfig(printer=PRINTERS["p1s"])
    bad = PartSpec("flare", "vase", "tulip", {"profile": "0:5,1:40", "height": 20}, 1, "PLA")
    with pytest.raises(BatchError, match="--force"):
        plan_batch([bad], config)
    assert plan_batch([bad], config, force=True).plates
    with pytest.raises(BatchError, match="no parameter"):
        plan_batch([PartSpec("x", "bead", None, {"nope": 1}, 1, "PLA")], config)
