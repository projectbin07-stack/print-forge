"""Self-contained HTML catalogue with inline-SVG renders. No JavaScript, no CDN.

Each view projects the mesh orthographically, drops faces turned away from the viewer (the
meshes are closed, so back faces are hidden anyway), sorts the rest by depth and draws them back
to front (painter's algorithm). Faces are shaded by a fixed light plus a small depth cue into
twelve levels that are CSS classes, so the page follows the light/dark preference of the
browser.
"""

from __future__ import annotations

import html
import math
from collections.abc import Sequence
from dataclasses import dataclass

from . import __version__
from .estimate import Estimate
from .families import FAMILIES
from .families.base import Part, param_fields
from .mesh import Mesh
from .vec import Vec3, dot, normalize

_LEVELS = 12
_S2 = 2**-0.5
_S3 = 3**-0.5
_S6 = 6**-0.5


@dataclass(frozen=True)
class View:
    title: str
    toward: Vec3  # unit vector from the model to the viewer
    right: Vec3
    up: Vec3


VIEWS = (
    View("Isometric", (_S3, -_S3, _S3), (_S2, _S2, 0.0), (-_S6, _S6, 2 * _S6)),
    View("Front", (0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    View("Top", (0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
)
LIGHT = normalize((0.35, -0.6, 0.72))


def render_svg(mesh: Mesh, view: View, size: float = 220.0, pad: float = 10.0) -> str:
    """One view as an ``<svg>`` element (polygons with shade classes ``s0``..``s7``)."""
    vs = mesh.vertices
    proj = [(dot(p, view.right), dot(p, view.up), dot(p, view.toward)) for p in vs]
    if not proj:
        return "<svg></svg>"
    xs = [p[0] for p in proj]
    ys = [p[1] for p in proj]
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1e-9)
    scale = (size - 2 * pad) / span
    cx = (max(xs) + min(xs)) / 2
    cy = (max(ys) + min(ys)) / 2
    zs = [p[2] for p in proj]
    z_lo, z_span = min(zs), max(max(zs) - min(zs), 1e-9)
    polys = []
    for f, (a, b, c) in enumerate(mesh.faces):
        n = mesh.face_normal(f)
        facing = dot(n, view.toward)
        if facing <= 1e-9:
            continue
        depth = proj[a][2] + proj[b][2] + proj[c][2]
        # Lambert shading plus a depth cue (nearer is lighter), so parallel faces at different
        # heights -- raised letters on a plate seen from above -- stay distinguishable.
        near = (depth / 3 - z_lo) / z_span
        light = 0.12 + 0.58 * max(0.0, dot(n, LIGHT)) + 0.3 * near
        level = min(_LEVELS - 1, int(light * _LEVELS))
        pts = " ".join(
            f"{(proj[i][0] - cx) * scale + size / 2:.1f},{size / 2 - (proj[i][1] - cy) * scale:.1f}"
            for i in (a, b, c)
        )
        polys.append((depth, level, pts))
    polys.sort(key=lambda t: t[0])
    body = "".join(f'<polygon class="s{lv}" points="{pts}"/>' for _, lv, pts in polys)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size:g} {size:g}" '
        f'width="{size:g}" height="{size:g}" role="img" aria-label="{html.escape(view.title)}">'
        f"{body}</svg>"
    )


_CSS = """
:root{--bg:#f6f6f3;--card:#fff;--fg:#1c1e21;--muted:#5b636b;--line:#d8dbde;
--error:#b3261e;--warning:#8f5c00;--note:#2a5a96;--ok:#1f7a3d;
__LIGHT_SHADES__}
@media (prefers-color-scheme:dark){:root{--bg:#111315;--card:#1a1d20;--fg:#e5e7e9;--muted:#9aa2aa;
--line:#30353a;--error:#ff6b61;--warning:#e5a73a;--note:#7fb0ff;--ok:#5cc47e;
__DARK_SHADES__}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1280px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:18px;margin:32px 0 10px;border-bottom:1px solid var(--line);padding-bottom:4px}
h3{font-size:15px;margin:0 0 6px}
.muted{color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,520px),1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 16px}
.views{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin:8px 0}
.views figure{margin:0;text-align:center}.views figcaption{font-size:12px;color:var(--muted)}
.views svg{max-width:100%;height:auto;display:block}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;vertical-align:top;padding:3px 6px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:600}
td.num{font-variant-numeric:tabular-nums;white-space:nowrap}
details{margin-top:8px}summary{cursor:pointer;color:var(--muted)}
ul.issues{margin:6px 0;padding-left:18px}
.sev{font-weight:600;text-transform:uppercase;font-size:11px;letter-spacing:.04em}
.sev-error{color:var(--error)}.sev-warning{color:var(--warning)}.sev-note{color:var(--note)}
.ok{color:var(--ok);font-weight:600}.bad{color:var(--error);font-weight:600}
""" + "".join(
    f".s{i}{{fill:var(--s{i});stroke:var(--s{i});stroke-width:.7;stroke-linejoin:round}}"
    for i in range(_LEVELS)
)


def _ramp(dark: tuple[int, int, int], light: tuple[int, int, int]) -> str:
    out = []
    for i in range(_LEVELS):
        t = i / (_LEVELS - 1)
        r, g, b = (round(d + (lt - d) * t) for d, lt in zip(dark, light, strict=True))
        out.append(f"--s{i}:#{r:02x}{g:02x}{b:02x}")
    return ";".join(out)


_CSS = _CSS.replace("__LIGHT_SHADES__", _ramp((0x3A, 0x48, 0x59), (0xB4, 0xC6, 0xD6))).replace(
    "__DARK_SHADES__", _ramp((0x28, 0x32, 0x3E), (0x93, 0xA6, 0xBA))
)


def _fmt(v: object) -> str:
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def part_card(part: Part, est: Estimate | None, render: Mesh | None = None) -> str:
    """HTML card for one part. ``render`` may be a lower-resolution mesh used only for the
    pictures (the numbers always come from ``part``)."""
    mesh = render or part.mesh
    views = "".join(
        f"<figure>{render_svg(mesh, v)}<figcaption>{v.title}</figcaption></figure>" for v in VIEWS
    )
    fam = FAMILIES[part.family]
    rows = []
    for f in param_fields(fam.params_type):
        unit = f.metadata["unit"]
        rows.append(
            f"<tr><td><code>{f.name}</code></td>"
            f'<td class="num">{html.escape(_fmt(part.params[f.name]))}'
            f"{' ' + unit if unit else ''}</td>"
            f"<td class='muted'>{html.escape(f.metadata['help'])}</td></tr>"
        )
    sx, sy, sz = part.mesh.size()
    topo = part.mesh.topology()
    closed = '<span class="ok">yes</span>' if topo.closed else '<span class="bad">no</span>'
    stats = [
        ("Size", f"{sx:.1f} x {sy:.1f} x {sz:.1f} mm"),
        ("Volume", f"{part.mesh.volume():.0f} mm&#179;"),
        ("Triangles", str(len(part.mesh.faces))),
        ("Closed and consistently wound", closed),
    ]
    if est is not None:
        stats.append(("Filament (rough model)", f"{est.grams:.2f} g PLA"))
    stat_html = "".join(f"<tr><th>{k}</th><td class='num'>{v}</td></tr>" for k, v in stats)
    issues = "".join(
        f'<li><span class="sev sev-{i.severity}">{i.severity}</span> {html.escape(i.message)}</li>'
        for i in part.issues
    )
    notes = "".join(f"<li>{html.escape(n)}</li>" for n in part.notes)
    caption = ""
    if render is not None and render is not part.mesh:
        caption = (
            "<p class='muted' style='font-size:12px'>Pictures drawn from a coarser copy "
            f"({len(render.faces)} triangles) to keep the page small.</p>"
        )
    return f"""<div class="card">
<h3>{html.escape(part.name)}</h3>
<div class="views">{views}</div>{caption}
<table>{stat_html}</table>
<p style="margin:8px 0 0"><b>Validation</b></p><ul class="issues">{issues}</ul>
{f'<p style="margin:8px 0 0"><b>Notes</b></p><ul class="issues">{notes}</ul>' if notes else ""}
<details><summary>Parameters</summary><table>
<thead><tr><th>Name</th><th>Value</th><th>Meaning</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></details>
</div>"""


def catalogue_html(
    sections: Sequence[tuple[str, str, Sequence[tuple[Part, Estimate | None, Mesh | None]]]],
    printer_label: str,
    nozzle: float,
) -> str:
    """``sections`` are (title, description, [(part, estimate, render mesh)]) tuples."""
    body = []
    count = 0
    for title, desc, items in sections:
        cards = "".join(part_card(p, e, r) for p, e, r in items)
        count += len(items)
        body.append(
            f"<h2>{html.escape(title)}</h2><p class='muted'>{html.escape(desc)}</p>"
            f'<div class="cards">{cards}</div>'
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="print-forge {__version__}">
<title>print-forge catalogue</title>
<style>{_CSS}</style>
</head>
<body>
<main>
<h1>print-forge catalogue</h1>
<p class="muted">{count} parts generated by print-forge {__version__}, validated for
{html.escape(printer_label)} with a {nozzle:g} mm nozzle. Every mesh is closed by construction;
the designs are checked geometrically only and have not been sliced or printed by this
project. Filament figures come from a rough pre-slicing model.</p>
{"".join(body)}
</main>
</body>
</html>
"""


def coarse_params_for_preview(params: object, max_faces_hint: int) -> dict[str, int]:
    """Lower ``segments``/``rings`` so a preview mesh has roughly ``max_faces_hint`` faces."""
    out: dict[str, int] = {}
    seg = getattr(params, "segments", None)
    rings = getattr(params, "rings", None)
    if isinstance(seg, int) and isinstance(rings, int):
        k = math.sqrt(max_faces_hint / max(1, 4 * seg * rings))
        if k < 1:
            out["segments"] = max(24, int(seg * k))
            out["rings"] = max(8, int(rings * k))
    return out
