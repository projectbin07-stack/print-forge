from __future__ import annotations

import xml.etree.ElementTree as ET
from html.parser import HTMLParser

import pytest

from print_forge import build
from print_forge.estimate import FilamentModel, estimate
from print_forge.families import FAMILIES
from print_forge.preview import VIEWS, catalogue_html, coarse_params_for_preview, render_svg

VOID = {"meta", "br", "img", "input", "link", "hr", "polygon"}


class TagChecker(HTMLParser):
    """Checks that every non-void element is closed in the right order."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.tags: set[str] = set()
        self.in_svg = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.add(tag)
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.add(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unexpected </{tag}>, open: {self.stack[-3:]}")
            return
        self.stack.pop()


def test_render_svg_painter_order_and_culling() -> None:
    cube = build.box(10, 10, 10)
    top = render_svg(cube, VIEWS[2])
    root = ET.fromstring(top)
    polys = root.findall("{http://www.w3.org/2000/svg}polygon")
    # looking straight down only the two top triangles face the viewer
    assert len(polys) == 2
    iso = ET.fromstring(render_svg(cube, VIEWS[0]))
    # three faces visible in the isometric view: 6 triangles
    assert len(iso.findall("{http://www.w3.org/2000/svg}polygon")) == 6
    assert render_svg(build.box(1, 1, 1).flip(), VIEWS[2]).count("<polygon") == 2  # bottom now


def test_catalogue_is_well_formed() -> None:
    sections = []
    for fam in FAMILIES.values():
        preset = next(iter(fam.presets))
        params = fam.make_params(preset)
        part = fam.generate(params, name=f"{fam.name} <{preset}> & co")
        sections.append(
            (fam.name, fam.summary, [(part, estimate(part.mesh, FilamentModel()), None)])
        )
    page = catalogue_html(sections, "Bambu Lab A1 mini (180 x 180 x 180 mm)", 0.4)
    checker = TagChecker()
    checker.feed(page)
    checker.close()
    assert not checker.errors, checker.errors[:5]
    assert checker.stack == []
    assert "script" not in checker.tags
    assert "http://" not in page.replace("http://www.w3.org/2000/svg", "")
    assert "https://" not in page
    assert "prefers-color-scheme:dark" in page
    assert "&lt;" in page and "<tulip>" not in page  # names are escaped
    # every inline SVG parses as XML
    start = 0
    count = 0
    while (i := page.find("<svg", start)) >= 0:
        j = page.index("</svg>", i) + len("</svg>")
        ET.fromstring(page[i:j])
        count += 1
        start = j
    assert count == 3 * len(sections)


def test_coarse_preview_params() -> None:
    vase = FAMILIES["vase"]
    params = vase.make_params("tulip")
    coarse = coarse_params_for_preview(params, 6000)
    assert coarse["segments"] < params.segments and coarse["rings"] < params.rings
    assert coarse_params_for_preview(FAMILIES["letter"].make_params("keychain"), 6000) == {}


def test_render_empty_mesh() -> None:
    from print_forge.mesh import Mesh

    assert render_svg(Mesh(), VIEWS[0]) == "<svg></svg>"


@pytest.mark.parametrize("view", VIEWS)
def test_views_are_orthonormal(view: object) -> None:
    from print_forge.vec import cross, dot

    v = view
    assert dot(v.right, v.up) == pytest.approx(0, abs=1e-12)  # type: ignore[attr-defined]
    assert cross(v.right, v.up) == pytest.approx(v.toward)  # type: ignore[attr-defined]
