"""Every generated mesh must pass ``stl-doctor check`` without errors.

stl-doctor (github.com/projectbin07-stack/stl-doctor) is an independent mesh checker: it welds
the STL's vertices itself and reports non-manifold edges, holes, flipped faces and bed-fit
problems as errors. The test is skipped when stl-doctor is not installed; CI installs v0.2.0 and
sets PRINT_FORGE_REQUIRE_STL_DOCTOR=1 so that a missing install fails instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from conftest import REQUIRE_STL_DOCTOR, optional_import
from print_forge.families import FAMILIES
from print_forge.io_stl import write_stl
from print_forge.printers import PRINTERS
from print_forge.validate import PrintSettings


def _doctor() -> tuple[Any, Any]:
    analysis = optional_import("stl_doctor.analysis", REQUIRE_STL_DOCTOR)
    mesh = optional_import("stl_doctor.mesh", REQUIRE_STL_DOCTOR)
    return analysis, mesh


@pytest.mark.parametrize(
    ("family", "preset"), [(f, p) for f, fam in FAMILIES.items() for p in fam.presets]
)
def test_preset_passes_stl_doctor(family: str, preset: str, tmp_path: Path) -> None:
    analysis, sd_mesh = _doctor()
    fam = FAMILIES[family]
    part = fam.generate(fam.make_params(preset), PrintSettings(PRINTERS["a1-mini"]))
    path = tmp_path / f"{family}-{preset}.stl"
    write_stl(path, part.mesh.on_bed())
    opts = analysis.Options(
        bed=analysis.PRINTERS["a1-mini"], suggest_orientation=False, check_thin_walls=False
    )
    report = analysis.analyze(sd_mesh.load_mesh(path), opts, path=str(path))
    errors = [f for f in report.findings if f.severity == analysis.ERROR]
    assert not errors, [(f.code, f.message) for f in errors]
    assert report.stats["watertight"]
    assert report.stats["shells"] == 1
    assert report.stats["volume_mm3"] == pytest.approx(part.mesh.volume(), rel=1e-4)
    # no self-intersections either (a warning in stl-doctor, but a defect for us)
    assert report.finding("self_intersections") is None
