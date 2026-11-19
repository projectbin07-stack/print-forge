"""Rectangle packing of part footprints onto printer beds.

Each part's footprint (bounding box in plan view) is grown by its brim width on every side;
parts are then kept ``spacing`` mm apart and ``edge_margin`` mm from the bed edge. Placement uses
the MaxRects algorithm with the best-short-side-fit rule (Jukka Jylanki, "A Thousand Ways to Pack
the Bin", 2010): the free space is a list of maximal empty rectangles, each part goes where the
leftover short side is smallest, and free rectangles are split and pruned after every placement.
When a part fits nowhere on the current plate a new plate is started.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def x2(self) -> float:
        return self.x + self.w

    @property
    def y2(self) -> float:
        return self.y + self.h

    def contains(self, o: Rect) -> bool:
        eps = 1e-9
        return (
            o.x >= self.x - eps
            and o.y >= self.y - eps
            and o.x2 <= self.x2 + eps
            and o.y2 <= self.y2 + eps
        )

    def overlaps(self, o: Rect) -> bool:
        eps = 1e-9
        return (
            self.x < o.x2 - eps
            and o.x < self.x2 - eps
            and self.y < o.y2 - eps
            and o.y < self.y2 - eps
        )


@dataclass(frozen=True)
class Item:
    """``key`` identifies the part; ``w`` x ``h`` is its footprint in mm (without brim)."""

    key: str
    w: float
    h: float


@dataclass(frozen=True)
class Placed:
    key: str
    plate: int
    x: float  # lower-left corner of the footprint (without brim) on the bed, mm
    y: float
    w: float  # footprint as placed (swapped when rotated)
    h: float
    rotated: bool


class PackError(ValueError):
    """A part is larger than the usable bed area."""


class _Bin:
    def __init__(self, w: float, h: float) -> None:
        self.free = [Rect(0.0, 0.0, w, h)]

    def find(self, w: float, h: float, allow_rotate: bool) -> tuple[Rect, bool] | None:
        best: tuple[float, float, Rect, bool] | None = None
        for fr in self.free:
            for rot in (False, True) if allow_rotate else (False,):
                rw, rh = (h, w) if rot else (w, h)
                if rw <= fr.w + 1e-9 and rh <= fr.h + 1e-9:
                    short = min(fr.w - rw, fr.h - rh)
                    long_ = max(fr.w - rw, fr.h - rh)
                    if best is None or (short, long_) < (best[0], best[1]):
                        best = (short, long_, Rect(fr.x, fr.y, rw, rh), rot)
        return None if best is None else (best[2], best[3])

    def place(self, r: Rect) -> None:
        new_free: list[Rect] = []
        for fr in self.free:
            if not fr.overlaps(r):
                new_free.append(fr)
                continue
            if r.x > fr.x:
                new_free.append(Rect(fr.x, fr.y, r.x - fr.x, fr.h))
            if r.x2 < fr.x2:
                new_free.append(Rect(r.x2, fr.y, fr.x2 - r.x2, fr.h))
            if r.y > fr.y:
                new_free.append(Rect(fr.x, fr.y, fr.w, r.y - fr.y))
            if r.y2 < fr.y2:
                new_free.append(Rect(fr.x, r.y2, fr.w, fr.y2 - r.y2))
        new_free = [f for f in new_free if f.w > 1e-9 and f.h > 1e-9]
        pruned = []
        for i, a in enumerate(new_free):
            if any(j != i and b.contains(a) and (b != a or j < i) for j, b in enumerate(new_free)):
                continue
            pruned.append(a)
        self.free = pruned


def pack(
    items: Sequence[Item],
    bed_w: float,
    bed_h: float,
    spacing: float = 5.0,
    brim: float = 0.0,
    edge_margin: float = 5.0,
    allow_rotate: bool = True,
) -> list[Placed]:
    """Place every item; returns placements in input order (plates numbered from 0).

    Trick for spacing: every footprint is padded by ``spacing / 2 + brim`` on each side and the
    usable bed is shrunk by ``edge_margin - spacing / 2`` per side, so padded rectangles may
    touch while real footprints (with brims) stay ``spacing`` apart and ``edge_margin`` from the
    edge.
    """
    if spacing < 0 or brim < 0 or edge_margin < 0:
        raise PackError("spacing, brim and edge margin must not be negative")
    pad = spacing / 2 + brim
    inset = edge_margin + brim - pad  # = edge_margin - spacing / 2
    usable_w = bed_w - 2 * inset
    usable_h = bed_h - 2 * inset
    order = sorted(range(len(items)), key=lambda i: (-items[i].w * items[i].h, i))
    bins: list[_Bin] = []
    result: dict[int, Placed] = {}
    for i in order:
        it = items[i]
        pw, ph = it.w + 2 * pad, it.h + 2 * pad
        fits_plain = pw <= usable_w + 1e-9 and ph <= usable_h + 1e-9
        fits_rot = allow_rotate and ph <= usable_w + 1e-9 and pw <= usable_h + 1e-9
        if not (fits_plain or fits_rot):
            raise PackError(
                f"{it.key}: footprint {it.w:.1f} x {it.h:.1f} mm (+{brim:g} mm brim) does not "
                f"fit the {bed_w:g} x {bed_h:g} mm bed with {edge_margin:g} mm margins"
            )
        spot = None
        for b_idx, b in enumerate(bins):
            found = b.find(pw, ph, allow_rotate)
            if found is not None:
                spot = (b_idx, *found)
                break
        if spot is None:
            bins.append(_Bin(usable_w, usable_h))
            found = bins[-1].find(pw, ph, allow_rotate)
            assert found is not None  # checked above
            spot = (len(bins) - 1, *found)
        b_idx, r, rot = spot
        bins[b_idx].place(r)
        w, h = (it.h, it.w) if rot else (it.w, it.h)
        result[i] = Placed(it.key, b_idx, r.x + inset + pad, r.y + inset + pad, w, h, rot)
    return [result[i] for i in range(len(items))]
