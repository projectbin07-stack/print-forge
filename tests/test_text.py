from __future__ import annotations

import math
import string

import pytest

from print_forge import poly2d, text
from print_forge.font_data import GLYPHS


def test_font_covers_required_characters() -> None:
    required = string.ascii_uppercase + string.digits
    assert all(ch in GLYPHS for ch in required)
    assert set(text.SUPPORTED) == {chr(c) for c in range(32, 127)}


def test_cap_height_scaling() -> None:
    strokes = text.layout("H", cap_height=21.0)
    ys = [y for s in strokes for _, y in s]
    # Hershey 'H' spans 0..21 units; with cap_height 21 one unit is one millimetre
    assert min(ys) == pytest.approx(0)
    assert max(ys) == pytest.approx(21)


def test_layout_rejects_unsupported() -> None:
    assert text.unsupported("ABé\t") == ["\t", "é"]
    with pytest.raises(text.TextError):
        text.layout("café", 10)


def test_stadium_area() -> None:
    # one straight stroke of length L thickened to width w: area = L * w + pi * (w / 2)^2
    length, width = 10.0, 2.0
    exact = length * width + math.pi
    fine = text.thicken([[(0.0, 0.0), (length, 0.0)]], width, cell=0.05, simplify_tol=1e-5)
    assert len(fine.contours) == 1
    area = poly2d.signed_area(fine.contours[0])
    assert area > 0  # outer boundary counter-clockwise
    assert area == pytest.approx(exact, rel=1e-3)
    assert fine.width == pytest.approx(length + width, abs=0.01)
    assert fine.height == pytest.approx(width, abs=0.01)
    # default simplification moves the outline by at most 0.01 mm:
    # area loss <= perimeter * 0.01 = (2 L + pi w) * 0.01
    default = text.thicken([[(0.0, 0.0), (length, 0.0)]], width, cell=0.05)
    loss = exact - poly2d.signed_area(default.contours[0])
    assert 0 <= loss <= (2 * length + math.pi * width) * 0.01 + 1e-3


def test_single_point_stroke_is_a_disc() -> None:
    out = text.thicken([[(0.0, 0.0)]], 2.0, cell=0.04, simplify_tol=1e-5)
    assert poly2d.signed_area(out.contours[0]) == pytest.approx(math.pi, rel=1e-3)


def test_counters_are_clockwise_holes() -> None:
    out = text.text_outline("O", 12, 1.5)
    areas = sorted(poly2d.signed_area(c) for c in out.contours)
    assert len(areas) == 2
    assert areas[0] < 0 < areas[1]  # the counter is a clockwise hole inside the outline
    depth, _ = poly2d.nesting(out.contours)
    assert sorted(depth) == [0, 1]


def test_overlapping_letters_merge() -> None:
    # negative tracking pushes the letters into each other: one outline, still simple
    apart = text.text_outline("II", 10, 1.5, tracking=2)
    merged = text.text_outline("II", 10, 1.5, tracking=-3)
    assert len(apart.contours) == 2
    assert len(merged.contours) == 1
    assert poly2d.is_simple(merged.contours[0])


@pytest.mark.parametrize("ch", [c for c in text.SUPPORTED if c != " "])
def test_every_glyph_thickens_to_simple_contours(ch: str) -> None:
    out = text.text_outline(ch, 10, 1.2)
    assert out.contours
    for c in out.contours:
        assert poly2d.is_simple(c)
        assert abs(poly2d.signed_area(c)) > 1e-3
    # contours never cross each other: nesting gives an outer boundary at depth 0
    depth, _ = poly2d.nesting(out.contours)
    assert 0 in depth
    assert out.centred().xmin == pytest.approx(-out.width / 2)


def test_empty_and_bad_width() -> None:
    with pytest.raises(text.TextError):
        text.text_outline(" ", 10, 1)
    with pytest.raises(text.TextError):
        text.thicken([[(0.0, 0.0), (1.0, 0.0)]], 0)
