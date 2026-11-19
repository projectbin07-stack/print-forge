from __future__ import annotations

import random

import pytest

from print_forge.packer import Item, PackError, Placed, Rect, pack


def check_layout(
    placed: list[Placed], items: list[Item], bed: float, spacing: float, brim: float, margin: float
) -> None:
    assert len(placed) == len(items)
    for p, it in zip(placed, items, strict=True):
        assert p.key == it.key
        assert sorted((p.w, p.h)) == pytest.approx(sorted((it.w, it.h)))
        # footprint plus brim stays inside the bed minus the edge margin
        assert p.x - brim >= margin - 1e-9
        assert p.y - brim >= margin - 1e-9
        assert p.x + p.w + brim <= bed - margin + 1e-9
        assert p.y + p.h + brim <= bed - margin + 1e-9
    by_plate: dict[int, list[Placed]] = {}
    for p in placed:
        by_plate.setdefault(p.plate, []).append(p)
    for group in by_plate.values():
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                # brims of two parts must be at least `spacing` apart on one axis
                gap_x = max(b.x - (a.x + a.w), a.x - (b.x + b.w)) - 2 * brim
                gap_y = max(b.y - (a.y + a.h), a.y - (b.y + b.h)) - 2 * brim
                assert max(gap_x, gap_y) >= spacing - 1e-9


@pytest.mark.parametrize("seed", range(25))
def test_random_packings_never_overlap(seed: int) -> None:
    rng = random.Random(seed)
    bed = rng.choice([180.0, 256.0])
    spacing = rng.uniform(0, 8)
    brim = rng.choice([0.0, 0.0, 3.0])
    margin = rng.uniform(0, 10)
    items = [
        Item(f"p{i}", rng.uniform(3, 60), rng.uniform(3, 60)) for i in range(rng.randint(1, 120))
    ]
    placed = pack(items, bed, bed, spacing, brim, margin)
    check_layout(placed, items, bed, spacing, brim, margin)


def test_grid_of_equal_squares_fills_plate_exactly() -> None:
    # 10 mm parts, 5 mm spacing, 5 mm margin on a 180 mm bed: (180 - 10 + 5) / 15 = 11.67
    # -> 11 per row and column, 121 per plate
    items = [Item("bead", 10, 10) for _ in range(130)]
    placed = pack(items, 180, 180, spacing=5, brim=0, edge_margin=5)
    assert sum(p.plate == 0 for p in placed) == 121
    assert sum(p.plate == 1 for p in placed) == 9
    check_layout(placed, items, 180, 5, 0, 5)


def test_rotation_lets_a_long_part_fit() -> None:
    items = [Item("bar", 10, 150), Item("plank", 150, 30)]
    placed = pack(items, 180, 180, spacing=5, edge_margin=5)
    assert {p.plate for p in placed} == {0}
    no_rot = pack([Item("x", 170, 20)], 180, 180, spacing=0, edge_margin=5, allow_rotate=False)
    assert not no_rot[0].rotated


def test_too_big_and_bad_arguments() -> None:
    with pytest.raises(PackError, match="does not fit"):
        pack([Item("huge", 200, 50)], 180, 180)
    with pytest.raises(PackError):
        pack([Item("a", 1, 1)], 180, 180, spacing=-1)


def test_rect_helpers() -> None:
    a = Rect(0, 0, 10, 10)
    assert a.contains(Rect(1, 1, 2, 2))
    assert not a.contains(Rect(9, 9, 2, 2))
    assert a.overlaps(Rect(9, 9, 2, 2))
    assert not a.overlaps(Rect(10, 0, 5, 5))  # touching is not overlapping
