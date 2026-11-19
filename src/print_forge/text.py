"""Turn single-stroke text into printable outlines.

The Hershey strokes are centre lines. To give them a width we sample the distance to the nearest
stroke on a fine grid, subtract half the stroke width, and trace the zero level with marching
squares. The result is the outline of the union of all thickened strokes -- overlapping strokes
and touching letters merge automatically -- as closed, non-crossing contours: outer boundaries
counter-clockwise, counters (the hole in "A", "O", "8") clockwise.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from . import poly2d
from .font_data import GLYPHS
from .vec import Vec2

CAP_UNITS = 21.0  # Hershey Roman Simplex capitals span 21 units
SUPPORTED = "".join(sorted(GLYPHS))

Segment = tuple[Vec2, Vec2]


class TextError(ValueError):
    """Unsupported character or impossible text parameters."""


def unsupported(text: str) -> list[str]:
    return sorted({ch for ch in text if ch not in GLYPHS})


def layout(text: str, cap_height: float, tracking: float = 0.0) -> list[list[Vec2]]:
    """Stroke centre lines (polylines in mm) for ``text`` starting at x = 0, baseline y = 0."""
    bad = unsupported(text)
    if bad:
        raise TextError(f"unsupported character(s): {' '.join(repr(c) for c in bad)}")
    s = cap_height / CAP_UNITS
    x = 0.0
    out: list[list[Vec2]] = []
    for i, ch in enumerate(text):
        left, right, strokes = GLYPHS[ch]
        ox = x - left * s
        for st in strokes:
            out.append([(ox + px * s, py * s) for px, py in st])
        x += (right - left) * s
        if i < len(text) - 1:
            x += tracking
    return out


@dataclass
class Outline:
    contours: list[list[Vec2]]
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    @property
    def width(self) -> float:
        return self.xmax - self.xmin

    @property
    def height(self) -> float:
        return self.ymax - self.ymin

    def moved(self, dx: float, dy: float) -> Outline:
        return Outline(
            [poly2d.translate2d(c, dx, dy) for c in self.contours],
            self.xmin + dx,
            self.ymin + dy,
            self.xmax + dx,
            self.ymax + dy,
        )

    def centred(self) -> Outline:
        return self.moved(-(self.xmin + self.xmax) / 2, -(self.ymin + self.ymax) / 2)


def _segments(polylines: list[list[Vec2]]) -> list[Segment]:
    segs: list[Segment] = []
    for pl in polylines:
        if len(pl) == 1:
            segs.append((pl[0], pl[0]))
        segs.extend(itertools.pairwise(pl))
    return segs


def _seg_dist(px: float, py: float, a: Vec2, b: Vec2) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    ln2 = dx * dx + dy * dy
    if ln2 == 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / ln2
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


#: Distinct outline vertices must stay this far apart (mm), well above the 1e-4 mm weld
#: tolerance mesh readers such as stl-doctor use.
MIN_VERTEX_GAP = 2e-3


def _min_vertex_gap(contours: list[list[Vec2]], limit: float) -> bool:
    """True when no two vertices (other than neighbours on one contour) are closer than
    ``limit``. Spatial hash, linear time."""
    grid: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for ci, c in enumerate(contours):
        n = len(c)
        for vi, (x, y) in enumerate(c):
            key = (math.floor(x / limit), math.floor(y / limit))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for cj, vj in grid.get((key[0] + dx, key[1] + dy), ()):
                        if cj == ci and (abs(vi - vj) <= 1 or abs(vi - vj) == n - 1):
                            continue
                        q = contours[cj][vj]
                        if math.hypot(x - q[0], y - q[1]) < limit:
                            return False
            grid.setdefault(key, []).append((ci, vi))
    return True


def thicken(
    polylines: list[list[Vec2]],
    width: float,
    cell: float | None = None,
    simplify_tol: float | None = None,
) -> Outline:
    """Outline of the strokes thickened to ``width`` (round caps and joins).

    ``cell`` is the grid spacing (default width / 6); ``simplify_tol`` the largest distance a
    simplified edge may move (default 1 % of a cell)."""
    if width <= 0:
        raise TextError("stroke width must be positive")
    segs = _segments(polylines)
    if not segs:
        raise TextError("text has no visible strokes")
    r = width / 2
    h = cell if cell is not None else max(width / 6.0, 0.02)
    xs = [p[0] for s in segs for p in s]
    ys = [p[1] for s in segs for p in s]
    # odd fractions of a cell keep straight stroke edges off the grid lines
    x0 = min(xs) - r - 2.37 * h
    y0 = min(ys) - r - 2.61 * h
    nx = math.ceil((max(xs) + r + 2 * h - x0) / h) + 1
    ny = math.ceil((max(ys) + r + 2 * h - y0) / h) + 1
    big = 1e9
    field = [[big] * nx for _ in range(ny)]
    reach = r + 2 * h
    for a, b in segs:
        i0 = max(0, int((min(a[0], b[0]) - reach - x0) / h))
        i1 = min(nx - 1, int((max(a[0], b[0]) + reach - x0) / h) + 1)
        j0 = max(0, int((min(a[1], b[1]) - reach - y0) / h))
        j1 = min(ny - 1, int((max(a[1], b[1]) + reach - y0) / h) + 1)
        for j in range(j0, j1 + 1):
            row = field[j]
            py = y0 + j * h
            for i in range(i0, i1 + 1):
                d = _seg_dist(x0 + i * h, py, a, b) - r
                if d < row[i]:
                    row[i] = d
    # Trace the outline; if two outlines (or two parts of one) pass the same grid corner or
    # saddle they can get closer than a mesh reader's weld tolerance. Then retry with the
    # iso-level moved by a few thousandths of a cell (the strokes grow by the same amount).
    tol = 0.01 * h if simplify_tol is None else simplify_tol
    contours: list[list[Vec2]] = []
    for k in range(41):
        level = 0.0031 * h * ((k + 1) // 2) * (1 if k % 2 else -1)
        shifted = [[v - level if v - level != 0.0 else 1e-12 for v in row] for row in field]
        contours = marching_squares(shifted, x0, y0, h)
        contours = [poly2d.remove_spikes(c) for c in contours]
        contours = [poly2d.remove_spikes(poly2d.simplify(c, tol)) for c in contours]
        # specks smaller than half a cell are sampling noise, not features of the strokes
        contours = [c for c in contours if len(c) >= 3 and abs(poly2d.signed_area(c)) > 0.5 * h * h]
        if _min_vertex_gap(contours, MIN_VERTEX_GAP):
            break
    else:  # pragma: no cover - no tested input needs more than a few retries
        raise TextError("could not trace a clean outline; change the stroke width slightly")
    all_x = [p[0] for c in contours for p in c]
    all_y = [p[1] for c in contours for p in c]
    return Outline(contours, min(all_x), min(all_y), max(all_x), max(all_y))


def marching_squares(field: list[list[float]], x0: float, y0: float, h: float) -> list[list[Vec2]]:
    """Closed zero-level contours of ``field`` (negative = inside), inside on the left.

    Saddle cells are resolved with the cell-centre average. Each crossing point is keyed by the
    grid edge it lies on, so loops are linked exactly, without coordinate comparisons.
    """
    ny = len(field)
    nx = len(field[0])
    nxt: dict[tuple[str, int, int], tuple[str, int, int]] = {}
    pos: dict[tuple[str, int, int], Vec2] = {}

    def crossing(key: tuple[str, int, int]) -> Vec2:
        if key not in pos:
            kind, i, j = key
            if kind == "h":  # edge (i, j) - (i + 1, j)
                va, vb = field[j][i], field[j][i + 1]
                t = va / (va - vb)
                pos[key] = (x0 + (i + t) * h, y0 + j * h)
            else:  # edge (i, j) - (i, j + 1)
                va, vb = field[j][i], field[j + 1][i]
                t = va / (va - vb)
                pos[key] = (x0 + i * h, y0 + (j + t) * h)
        return pos[key]

    for j in range(ny - 1):
        for i in range(nx - 1):
            v = (field[j][i], field[j][i + 1], field[j + 1][i + 1], field[j + 1][i])
            inside = [x < 0 for x in v]
            if all(inside) or not any(inside):
                continue
            # cell edges in counter-clockwise order: bottom, right, top (reversed), left (reversed)
            edges = (("h", i, j), ("v", i + 1, j), ("h", i, j + 1), ("v", i, j))
            cross_list: list[tuple[tuple[str, int, int], bool]] = []
            for k in range(4):
                a_in, b_in = inside[k], inside[(k + 1) % 4]
                if a_in != b_in:
                    cross_list.append((edges[k], a_in))  # True: leaving the inside
            centre_inside = sum(v) / 4 < 0
            m = len(cross_list)
            for k, (key, leaving) in enumerate(cross_list):
                if not leaving:
                    continue
                partner = cross_list[(k + 1) % m] if centre_inside or m == 2 else cross_list[k - 1]
                crossing(key)
                crossing(partner[0])
                nxt[key] = partner[0]
    loops: list[list[Vec2]] = []
    seen: set[tuple[str, int, int]] = set()
    for start in nxt:
        if start in seen:
            continue
        loop = []
        key = start
        while key not in seen:
            seen.add(key)
            loop.append(pos[key])
            key = nxt[key]
        loops.append(loop)
    return loops


def text_outline(text: str, cap_height: float, stroke: float, tracking: float = 0.0) -> Outline:
    """Thickened outline of ``text``; letters ``tracking`` mm further apart than the font's
    own spacing."""
    return thicken(layout(text, cap_height, tracking), stroke)
