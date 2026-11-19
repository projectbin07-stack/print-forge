"""Profile curves through a few control points: centripetal Catmull-Rom and Bezier."""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence

from .vec import Vec2


def catmull_rom(points: Sequence[Vec2], samples_per_segment: int = 16) -> list[Vec2]:
    """Centripetal Catmull-Rom spline (alpha = 0.5) through every point.

    The centripetal form does not form loops or cusps inside a segment, unlike the uniform form.
    End segments use mirrored phantom points so the curve starts and ends at the given points.
    """
    pts = list(points)
    if len(pts) < 2:
        raise ValueError("need at least 2 control points")
    if len(pts) == 2:
        return [
            (
                pts[0][0] + (pts[1][0] - pts[0][0]) * i / samples_per_segment,
                pts[0][1] + (pts[1][1] - pts[0][1]) * i / samples_per_segment,
            )
            for i in range(samples_per_segment + 1)
        ]
    first = (2 * pts[0][0] - pts[1][0], 2 * pts[0][1] - pts[1][1])
    last = (2 * pts[-1][0] - pts[-2][0], 2 * pts[-1][1] - pts[-2][1])
    ext = [first, *pts, last]
    out: list[Vec2] = [pts[0]]
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        t0 = 0.0
        t1 = t0 + max(math.dist(p0, p1), 1e-9) ** 0.5
        t2 = t1 + max(math.dist(p1, p2), 1e-9) ** 0.5
        t3 = t2 + max(math.dist(p2, p3), 1e-9) ** 0.5
        for s in range(1, samples_per_segment + 1):
            t = t1 + (t2 - t1) * s / samples_per_segment
            out.append(_cr_point(p0, p1, p2, p3, t0, t1, t2, t3, t))
    out[-1] = pts[-1]
    return out


def _lerp(a: Vec2, b: Vec2, ta: float, tb: float, t: float) -> Vec2:
    if tb == ta:
        return a
    u = (t - ta) / (tb - ta)
    return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)


def _cr_point(
    p0: Vec2,
    p1: Vec2,
    p2: Vec2,
    p3: Vec2,
    t0: float,
    t1: float,
    t2: float,
    t3: float,
    t: float,
) -> Vec2:
    a1 = _lerp(p0, p1, t0, t1, t)
    a2 = _lerp(p1, p2, t1, t2, t)
    a3 = _lerp(p2, p3, t2, t3, t)
    b1 = _lerp(a1, a2, t0, t2, t)
    b2 = _lerp(a2, a3, t1, t3, t)
    return _lerp(b1, b2, t1, t2, t)


def bezier(points: Sequence[Vec2], samples: int = 64) -> list[Vec2]:
    """One Bezier curve with the given control polygon (De Casteljau evaluation)."""
    ctrl = list(points)
    if len(ctrl) < 2:
        raise ValueError("need at least 2 control points")
    out = []
    for s in range(samples + 1):
        t = s / samples
        work = list(ctrl)
        while len(work) > 1:
            work = [
                (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                for a, b in itertools.pairwise(work)
            ]
        out.append(work[0])
    return out


def resample_by_y(curve: Sequence[Vec2], ys: Sequence[float]) -> list[float]:
    """For a curve whose y increases monotonically, return x at each requested y."""
    for a, b in itertools.pairwise(curve):
        if b[1] < a[1] - 1e-9:
            raise ValueError("profile curve must rise monotonically")
    out = []
    j = 0
    for y in ys:
        while j < len(curve) - 2 and curve[j + 1][1] < y:
            j += 1
        a, b = curve[j], curve[j + 1]
        if b[1] == a[1]:
            out.append(b[0])
        else:
            u = min(1.0, max(0.0, (y - a[1]) / (b[1] - a[1])))
            out.append(a[0] + (b[0] - a[0]) * u)
    return out
