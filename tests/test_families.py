"""Product families: presets, seeded parameter sweeps, analytic checks and validation rules."""

from __future__ import annotations

import dataclasses
import math
import random
import string
from typing import Any

import pytest

from conftest import assert_solid
from print_forge import poly2d
from print_forge.families import FAMILIES, ParamError, bead, cap, letter, vase
from print_forge.families.base import param_fields
from print_forge.printers import PRINTERS
from print_forge.validate import ERROR, WARNING, PrintSettings

MINI = PrintSettings(PRINTERS["a1-mini"])


def codes(issues: list[Any], severity: str) -> set[str]:
    return {i.code for i in issues if i.severity == severity}


@pytest.mark.parametrize(
    ("family", "preset"), [(f, p) for f, fam in FAMILIES.items() for p in fam.presets]
)
def test_every_preset_is_solid_and_passes(family: str, preset: str) -> None:
    fam = FAMILIES[family]
    part = fam.generate(fam.make_params(preset), MINI)
    assert_solid(part.mesh)
    assert part.ok, part.issues
    assert part.mesh.shell_count() == 1


def test_params_documented() -> None:
    for fam in FAMILIES.values():
        for f in param_fields(fam.params_type):
            assert f.metadata["help"]
        assert fam.default_preset in fam.presets


def test_make_params_errors() -> None:
    fam = FAMILIES["bead"]
    with pytest.raises(ParamError, match="unknown bead preset"):
        fam.make_params("nope")
    with pytest.raises(ParamError, match="no parameter"):
        fam.make_params(None, {"colour": "red"})
    with pytest.raises(ParamError, match="below the minimum"):
        fam.make_params(None, {"diameter": 1})
    with pytest.raises(ParamError, match="not one of"):
        fam.make_params(None, {"shape": "cube"})
    with pytest.raises(ParamError, match="not a valid int"):
        fam.make_params(None, {"facets": 2.5})
    with pytest.raises(ParamError, match="not a valid bool"):
        fam.make_params(None, {"supportless": "maybe"})
    p = fam.make_params(None, {"supportless": "no", "segments": "32"})
    assert p.supportless is False and p.segments == 32


# --------------------------------------------------------------------------------- vase
def test_vase_mode_cylinder_volume_is_exact() -> None:
    # constant radius, no twist: an n-gon prism, V = n/2 r^2 sin(2 pi/n) h
    p = vase.VaseParams(profile="0:10,1:10", height=30, vase_mode=True, segments=48, rings=10)
    m = vase.build_vase(p)
    assert_solid(m)
    assert m.volume() == pytest.approx(24 * 100 * math.sin(2 * math.pi / 48) * 30, rel=1e-9)


def test_hollow_cylinder_vase_volume() -> None:
    # outer n-gon prism minus inner prism whose apothem is smaller by the wall
    n, r, h, wall, floor = 48, 10.0, 30.0, 1.6, 2.0
    p = vase.VaseParams(profile="0:10,1:10", height=h, wall=wall, floor=floor, segments=n, rings=10)
    m = vase.build_vase(p)
    assert_solid(m)
    apothem_in = r * math.cos(math.pi / n) - wall
    r_in = apothem_in / math.cos(math.pi / n)

    def area(rr: float) -> float:
        return n / 2 * rr * rr * math.sin(2 * math.pi / n)

    assert m.volume() == pytest.approx(area(r) * h - area(r_in) * (h - floor), rel=1e-9)


@pytest.mark.parametrize("seed", range(12))
def test_vase_parameter_sweep(seed: int) -> None:
    rng = random.Random(seed)
    radii = [rng.uniform(12, 25) for _ in range(rng.randint(2, 5))]
    zs = [0.0, *sorted(rng.uniform(0.1, 0.9) for _ in range(len(radii) - 2)), 1.0]
    profile = ",".join(f"{z:.3f}:{r:.2f}" for z, r in zip(zs, radii, strict=True))
    section = rng.choice(["circle", "polygon", "wavy"])
    p = vase.VaseParams(
        height=rng.uniform(20, 80),
        profile=profile,
        curve=rng.choice(["catmull-rom", "bezier"]),
        section=section,
        sides=rng.randint(3, 10),
        wave_depth=rng.uniform(0, 0.12),
        twist=rng.uniform(-120, 120),
        vase_mode=rng.random() < 0.3,
        wall=rng.uniform(0.8, 2.5),
        floor=rng.uniform(0.8, 2.5),
        segments=rng.randint(24, 72),
        rings=rng.randint(8, 30),
    )
    part = vase.FAMILY.generate(p, MINI)
    assert_solid(part.mesh)
    assert "mesh" not in codes(part.issues, ERROR)


def test_vase_validation() -> None:
    flare = vase.FAMILY.generate(vase.VaseParams(profile="0:5,1:40", height=20), MINI)
    assert "overhang" in codes(flare.issues, ERROR)
    tall = vase.FAMILY.generate(vase.VaseParams(profile="0:10,1:10", height=200), MINI)
    assert "bed_fit" in codes(tall.issues, ERROR)
    assert "stability" in codes(tall.issues, WARNING)
    thin = vase.FAMILY.generate(vase.VaseParams(wall=0.3), MINI)
    assert "wall" in codes(thin.issues, ERROR)
    narrow = vase.FAMILY.generate(
        vase.VaseParams(profile="0:3,1:3", height=20, wall=2.5, segments=24, rings=8), MINI
    )
    assert "wall" in codes(narrow.issues, ERROR) or "opening" in codes(narrow.issues, WARNING)
    vm = vase.FAMILY.generate(vase.VaseParams(vase_mode=True), MINI)
    assert any("spiral vase" in n.lower() for n in vm.notes)


def test_vase_profile_errors() -> None:
    for bad in (
        "0:10",
        "0:10,0.5",
        "0.1:10,1:10",
        "0:10,0.5:10,0.4:10,1:10",
        "0:10,1:-1",
        "0:a,1:2",
    ):
        with pytest.raises(ParamError):
            vase.parse_profile(bad)


# --------------------------------------------------------------------------------- bead
@pytest.mark.parametrize("shape", ["sphere", "faceted", "barrel", "twist"])
def test_bead_hole_diameter(shape: str) -> None:
    p = bead.BeadParams(shape=shape, diameter=12, height=10, cord=1.5, clearance=0.25, facets=8)
    m = bead.build_bead(p)
    assert_solid(m)
    # The hole's faces are the faces nearest the axis. At the height of each face's centroid,
    # its plane must be cord/2 + clearance = 1.0 mm from the axis (horizontal distance).
    dists = []
    for f, (a, b, c) in enumerate(m.faces):
        pts = [m.vertices[i] for i in (a, b, c)]
        if max(math.hypot(x, y) for x, y, _ in pts) > 1.5:
            continue
        nx, ny, nz = m.face_normal(f)
        if abs(nz) > 0.1:
            continue
        zc = sum(z for _, _, z in pts) / 3
        x, y, z = pts[0]
        dists.append(-(nx * x + ny * y + nz * (z - zc)) / math.hypot(nx, ny))
    assert dists
    # straight holes are exact; the twisted hole's triangles chord across each turn step
    tol = 2e-3 if shape == "twist" else 1e-9
    assert min(dists) == pytest.approx(1.0, abs=tol)
    assert max(dists) == pytest.approx(1.0, abs=tol)


def test_bead_supportless_foot_and_heights() -> None:
    p = bead.BeadParams(shape="sphere", diameter=10, cord=1, clearance=0.2)
    m = bead.build_bead(p)
    lo, hi = m.bounds()
    # the sphere (R = 5, centre z = 5) is cut by the hole polygon, whose vertices sit at
    # rv = 0.7 / cos(pi / 48); the top rim is at 5 + sqrt(25 - rv^2)
    rv = 0.7 / math.cos(math.pi / 48)
    assert lo[2] == 0
    assert hi[2] == pytest.approx(5 + math.sqrt(25 - rv * rv))
    # foot radius = R (1 - sin 45) / cos 45 = 5 * 0.41421
    foot = max(math.hypot(x, y) for x, y, z in m.vertices if z == 0)
    assert foot == pytest.approx(5 * (math.sqrt(2) - 1))
    assert bead.foot_ratio(45) == pytest.approx(math.sqrt(2) - 1)


def test_bead_torus_volume_pappus() -> None:
    # without the supportless chamfer the torus is a revolved polygonal circle
    p = bead.BeadParams(shape="torus", diameter=14, tube=4, supportless=False, segments=256)
    m = bead.build_bead(p)
    assert_solid(m)
    exact = 2 * math.pi * 5.0 * math.pi * 2.0**2  # 2 pi R * pi r^2
    assert m.volume() == pytest.approx(exact, rel=2e-3)


@pytest.mark.parametrize("seed", range(15))
def test_bead_parameter_sweep(seed: int) -> None:
    rng = random.Random(100 + seed)
    p = bead.BeadParams(
        shape=rng.choice(["sphere", "faceted", "torus", "barrel", "twist"]),
        diameter=rng.uniform(8, 20),
        height=rng.uniform(5, 20),
        cord=rng.uniform(0.5, 2),
        clearance=rng.uniform(0, 0.4),
        tube=rng.uniform(2.5, 4),
        end_ratio=rng.uniform(0.6, 1),
        facets=rng.randint(4, 12),
        twist=rng.uniform(-90, 90),
        wobble=rng.uniform(0, 0.8),
        supportless=rng.random() < 0.8,
        segments=rng.randint(16, 64),
    )
    assert_solid(bead.build_bead(p))


def test_bead_validation() -> None:
    hollow = bead.FAMILY.generate(bead.BeadParams(diameter=4, cord=3, supportless=False), MINI)
    assert "wall" in codes(hollow.issues, ERROR)
    with pytest.raises(ParamError, match="too small"):
        bead.build_bead(bead.BeadParams(diameter=4, cord=2.5))
    donut = bead.FAMILY.generate(
        bead.BeadParams(shape="torus", diameter=10, tube=4.5, cord=3), MINI
    )
    assert "hole" in codes(donut.issues, ERROR)
    full = bead.FAMILY.generate(bead.BeadParams(supportless=False), MINI)
    assert "overhang" in codes(full.issues, ERROR)
    steep = bead.FAMILY.generate(bead.BeadParams(support_angle=55), MINI)
    assert "chamfer" in codes(steep.issues, WARNING)
    tiny = bead.FAMILY.generate(bead.BeadParams(cord=0.3, clearance=0.1, diameter=5), MINI)
    assert "hole" in codes(tiny.issues, WARNING)


# ------------------------------------------------------------------------------- letter
@pytest.mark.parametrize("ch", list(string.ascii_uppercase + string.digits))
def test_letter_tile_for_every_character(ch: str) -> None:
    p = letter.LetterParams(text=ch, style="tile", cap_height=10, stroke=1.4, min_size=16)
    part = letter.FAMILY.generate(p, MINI)
    assert_solid(part.mesh)
    assert part.mesh.shell_count() == 1
    assert part.ok, part.issues


def test_letter_keychain_volume_and_hole() -> None:
    p = letter.LetterParams(text="NAV")
    lay = letter.letter_layout(p)
    m = letter.build_letter(p)
    assert_solid(m)
    assert lay.hole is not None and lay.hole_centre is not None
    base_area = poly2d.signed_area(lay.base) - abs(poly2d.signed_area(lay.hole))
    text_area = sum(poly2d.signed_area(c) for c in lay.outline.contours)  # holes negative
    expected = base_area * p.base_thickness + text_area * p.relief
    assert m.volume() == pytest.approx(expected, rel=1e-9)
    # keyring hole: edges are 2.5 mm from the centre (inscribed radius = hole / 2)
    hx, hy = lay.hole_centre
    h = lay.hole
    for i in range(len(h)):
        a, b = h[i], h[(i + 1) % len(h)]
        assert math.hypot((a[0] + b[0]) / 2 - hx, (a[1] + b[1]) / 2 - hy) == pytest.approx(2.5)


def test_letter_validation() -> None:
    with pytest.raises(ParamError, match="unsupported"):
        letter.FAMILY.generate(letter.LetterParams(text="Å"), MINI)
    with pytest.raises(ParamError):
        letter.letter_layout(letter.LetterParams(text="   "))
    thin = letter.FAMILY.generate(letter.LetterParams(stroke=0.6), MINI)
    assert "stroke" in codes(thin.issues, WARNING)
    # 'I' advances 8/21 of the cap height (3.81 mm); stroke 1.5 and tracking -2 leave
    # 3.81 - 2 - 1.5 = 0.31 mm between the letters, under the 0.4 mm nozzle
    tight = letter.FAMILY.generate(
        letter.LetterParams(text="II", cap_height=10, stroke=1.5, tracking=-2.0), MINI
    )
    assert "gap" in codes(tight.issues, WARNING)
    long_text = letter.FAMILY.generate(
        letter.LetterParams(text="ABCDEFGHIJKL", cap_height=20), MINI
    )
    assert "bed_fit" in codes(long_text.issues, ERROR)


# ---------------------------------------------------------------------------------- cap
def test_cap_socket_dimensions() -> None:
    p = cap.CapParams(length_clearance=0.2, width_clearance=0.07)
    m = cap.build_cap(p)
    assert_solid(m)
    socket = [v for v in m.vertices if v[2] == pytest.approx(p.socket_depth)]
    xs = [x for x, _, _ in socket]
    ys = [y for _, y, _ in socket]
    assert max(xs) - min(xs) == pytest.approx(4.03 + 0.2)
    assert max(ys) - min(ys) == pytest.approx(4.23 + 0.2)
    slot = cap.cross_slot(p)
    widths = sorted({round(abs(y) * 2, 6) for x, y in slot if abs(x) > 2})
    assert widths == [pytest.approx(1.25 + 0.07)]
    # farthest socket corner: vertical slot half-width (1.15 + 0.07) / 2, half-length
    # (4.23 + 0.2) / 2
    assert cap.stem_wall(p) == pytest.approx(2.75 - math.hypot(0.61, 2.215))


@pytest.mark.parametrize("seed", range(10))
def test_cap_parameter_sweep(seed: int) -> None:
    rng = random.Random(200 + seed)
    p = cap.CapParams(
        base_width=rng.uniform(16, 20),
        base_depth=rng.uniform(16, 20),
        top_width=rng.uniform(11, 14),
        top_depth=rng.uniform(11, 14),
        height=rng.uniform(7, 11),
        corner_radius=rng.uniform(0.5, 2.5),
        top_corner_radius=rng.uniform(0.5, 3),
        wall=rng.uniform(0.8, 1.6),
        top_thickness=rng.uniform(1, 2),
        dish=rng.choice(["flat", "cylindrical", "spherical"]),
        dish_depth=rng.uniform(0, 1.2),
        legend=rng.choice(["", "A", "7", "OK"]),
        legend_height=rng.uniform(3, 5),
        segments=rng.randint(16, 64),
    )
    m = cap.build_cap(p)
    assert_solid(m)
    assert m.shell_count() == 1


def test_cap_validation() -> None:
    with pytest.raises(ParamError, match="too low"):
        cap.build_cap(cap.CapParams(height=5, top_thickness=1.5, socket_depth=4))
    wide = cap.FAMILY.generate(cap.CapParams(top_width=20), MINI)
    assert "taper" in codes(wide.issues, ERROR)
    part = cap.FAMILY.generate(cap.CapParams(), MINI)
    assert "stem_wall" in codes(part.issues, WARNING)  # MX stems are thin by nature
    assert any(i.code == "bridge" and i.severity == "note" for i in part.issues)
    with pytest.raises(ParamError, match="does not fit"):
        cap.build_cap(cap.CapParams(legend="WWW", legend_height=8))
    with pytest.raises(ParamError, match="unsupported"):
        cap.legend_contours(cap.CapParams(legend="é"))


def test_dish_shapes() -> None:
    for dish, centre, edge_mid_x in (
        ("flat", 8.0, 8.0),
        ("cylindrical", 7.2, 8.0),
        ("spherical", 7.2, 8.0),
    ):
        p = dataclasses.replace(cap.CapParams(), dish=dish, height=8.0, dish_depth=0.8)
        z = cap.dish_fn(p)
        assert z(0, 0) == pytest.approx(centre)
        assert z(p.top_width / 2, 0) == pytest.approx(edge_mid_x)


@pytest.mark.parametrize("seed", range(40))
def test_random_text_keychains(seed: int) -> None:
    # random printable strings, sizes, strokes and spacing: overlapping and nearly touching
    # strokes, counters and collinear edges across letters are all exercised
    from print_forge.text import SUPPORTED

    rng = random.Random(500 + seed)
    chars = SUPPORTED.replace(" ", "")
    p = letter.LetterParams(
        text="".join(rng.choice(chars) for _ in range(rng.randint(1, 5))),
        style=rng.choice(["tile", "keychain"]),
        cap_height=rng.uniform(5, 20),
        stroke=rng.uniform(0.6, 2.5),
        tracking=rng.uniform(-1, 3),
    )
    m = letter.build_letter(p)
    assert_solid(m)
    assert m.shell_count() == 1
