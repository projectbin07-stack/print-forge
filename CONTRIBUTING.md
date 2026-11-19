# Contributing

Bug reports, new product families and pull requests are welcome.

## Development setup

```console
git clone https://github.com/projectbin07-stack/print-forge.git
cd print-forge
python -m venv .venv
.venv/bin/pip install -e ".[dev]"      # Windows: .venv\Scripts\pip
# optional, enables the cross-project tests that CI always runs:
.venv/bin/pip install "stl-doctor @ git+https://github.com/projectbin07-stack/stl-doctor@v0.1.0"
.venv/bin/pip install "printfarm-planner @ git+https://github.com/projectbin07-stack/printfarm-planner@v0.3.0"
```

## Checks

All four must pass; CI runs them on Ubuntu and Windows with Python 3.10 and 3.13.

```console
ruff check .
ruff format --check .
mypy
pytest --cov
```

## Guidelines

- Runtime code uses the standard library only. numpy may be used as an optional speed-up with a
  pure-Python path that gives the same result (and is tested).
- No mesh booleans. A new shape must be built so that it is closed by construction, and its
  tests must call `assert_solid` (closed, consistently wound, positive volume, no vertices close
  enough to be welded) for seeded random parameters, not only for the presets.
- Where a volume, area or dimension can be derived by hand, assert against that derivation and
  write it in a comment. Do not assert against numbers copied from print-forge's own output.
- Every family parameter needs help text, a unit and limits (`param(...)`), because the CLI,
  catalogue and README tables come from them.
- Do not claim print results you did not get. If you print a part and want to report it, say
  which printer, filament and slicer settings you used.
- Keep commits small with imperative messages (`Add ...`, `Fix ...`).
