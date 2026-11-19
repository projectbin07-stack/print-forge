from __future__ import annotations

import math

import pytest

from print_forge import build
from print_forge.estimate import FilamentModel, estimate


def test_cube_by_hand() -> None:
    # 20 mm cube: V = 8000 mm^3, A = 2400 mm^2
    # shell = 2400 * 2 walls * 0.42 = 2016; interior = 8000 - 2016 = 5984; infill 15 % = 897.6
    # filament = 2913.6 mm^3 -> 2.9136 cm^3 * 1.24 g/cm^3 = 3.612864 g
    est = estimate(build.box(20, 20, 20), FilamentModel())
    assert est.volume_mm3 == pytest.approx(8000)
    assert est.filament_mm3 == pytest.approx(2913.6)
    assert est.grams == pytest.approx(3.612864)
    assert est.metres == pytest.approx(2913.6 / (math.pi * 0.875**2) / 1000)
    assert est.print_min == pytest.approx(2913.6 / 8.0 / 60)


def test_thin_part_is_solid() -> None:
    # 20 x 20 x 1 plate: shell term exceeds the volume, so the whole volume is filament
    est = estimate(build.box(20, 20, 1), FilamentModel(infill=0.0))
    assert est.filament_mm3 == pytest.approx(400)


def test_vase_mode_by_hand() -> None:
    # square tube 10 x 10 x 30 as a solid: side area 1200, bottom 100, top 100
    # filament = 1200 * 0.42 + 100 * 0.8 = 584 mm^3
    est = estimate(build.box(10, 10, 30), FilamentModel(), vase_mode=True)
    assert est.filament_mm3 == pytest.approx(584)


def test_model_validation() -> None:
    for bad in ({"infill": 1.5}, {"density": 0}, {"walls": 0}, {"flow_mm3_s": -1}):
        with pytest.raises(ValueError):
            FilamentModel(**bad)
