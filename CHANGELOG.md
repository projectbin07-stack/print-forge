# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.1] - 2026-11-24

### Fixed

- `cap-height` was documented as the height of capital letters, but it set the height of the
  stroke centre lines. The stroke then added half its width above and below, so letters came out
  a full stroke taller than asked: 12 mm capitals with a 1.6 mm stroke were 13.59 mm. The centre
  lines are now laid out at `cap-height - stroke`, so finished capitals measure `cap-height`, and
  a stroke at least as wide as the cap height is rejected. Letter parts made with 0.1.0 parameters
  are now smaller; the README figures and the letters catalogue screenshot were regenerated.
- The README told users to clear only `print_time` after adding a `gcode_json` analysis to
  `jobs.csv`. printfarm-planner gives CSV values priority, so print-forge's rough mass, material,
  nozzle and size silently stayed in force. The README now says to clear those columns too.

### Changed

- CI installs stl-doctor v0.2.0 (was v0.1.0) and printfarm-planner v0.4.0 (was v0.3.0). With
  stl-doctor 0.1.0, the CI check of `plate-01.3mf` read only the first of the plate's 84 build
  items; CI now also asserts that the per-item breakdown is printed.

## [0.1.0] - 2026-11-19

### Added

- Mesh kernel: indexed triangle mesh with transforms, volume, area, bounds and a topology audit
  (open, non-manifold and flipped edges, degenerate faces, shells, weld-close vertices); optional
  numpy path for volume and area with a tested pure-Python fallback.
- Closed-by-construction constructors without booleans: revolve (pole-to-pole or closed loop),
  loft with planar caps, vessel, tube, extrusion of polygons with holes, stepped extrusion
  (raised regions on a base), helix sweep (radial and horizontal frames).
- 2D tools: ear clipping with hole bridging, collinear-vertex handling and retries, nesting,
  offsets, bounded-error simplification, spike removal, rounded rectangles and inscribed holes.
- Hershey Roman Simplex font (printable ASCII) with stroke thickening by distance field and
  marching squares.
- Product families with documented parameters, presets and printability checks: vase (profile
  curves, polygon/wavy sections, twist, spiral-vase-mode body), bead (sphere, faceted, torus,
  barrel, twist; cord hole with clearance; supportless chamfer), letter tile / keychain, clicker
  top / keycap-style cap for MX-style stems with dish and optional legend.
- Binary/ASCII STL writer and 3MF writer (named objects, build-item transforms, millimetre units).
- MaxRects plate packer with spacing, brim and edge margin; one 3MF per distinct plate.
- Batch manifest (CSV and JSON) with a stated filament/time model, and a printfarm-planner jobs
  CSV; TOML parts files (tomllib or a subset parser on Python 3.10).
- Self-contained HTML catalogue with inline-SVG renders, parameter tables and validation notes,
  light and dark themes.
- `print-forge vase | bead | letter | cap | plate | catalogue` command-line interface.
- Tests: seeded property tests for every constructor and family, hand-derived volumes, hole and
  socket dimensions, glyph coverage, packer invariants, IO round trips, manifest totals, HTML
  well-formedness, CLI; stl-doctor and printfarm-planner compatibility tests required in CI.

[0.1.1]: https://github.com/projectbin07-stack/print-forge/releases/tag/v0.1.1
[0.1.0]: https://github.com/projectbin07-stack/print-forge/releases/tag/v0.1.0
