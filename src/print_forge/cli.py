"""Command-line interface.

``print-forge vase|bead|letter|cap [--preset NAME] [--param value ...] --out FILE``
``print-forge plate parts.toml --printer a1-mini --out plates/``
``print-forge catalogue --out catalogue.html``
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from . import __version__
from .batch import (
    BatchConfig,
    BatchError,
    PartSpec,
    load_parts_file,
    plan_batch,
    totals,
    write_outputs,
)
from .estimate import FilamentModel, estimate
from .families import FAMILIES, ParamError, Part
from .families.base import Family, param_fields
from .io_3mf import write_3mf
from .io_stl import write_stl
from .preview import catalogue_html, coarse_params_for_preview
from .printers import DEFAULT_PRINTER, PRINTERS, printer_key
from .validate import ERROR, WARNING, PrintSettings

EXIT_OK = 0
EXIT_ERROR = 2


def _positive(text: str) -> float:
    try:
        v = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
    if v <= 0:
        raise argparse.ArgumentTypeError(f"must be positive: {text!r}")
    return v


def _machine_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--printer",
        type=printer_key,
        choices=sorted(PRINTERS),
        default=None,
        help=f"bed to validate and pack for (default {DEFAULT_PRINTER})",
    )
    p.add_argument("--nozzle", type=_positive, default=0.4, metavar="MM", help="default 0.4")
    p.add_argument(
        "--overhang",
        type=_positive,
        default=45.0,
        metavar="DEG",
        help="overhang limit from vertical for supportless printing (default 45)",
    )


def _family_parser(sub: Any, fam: Family[Any]) -> None:
    p = sub.add_parser(
        fam.name,
        help=fam.summary,
        description=f"Generate {fam.summary}. Presets: {', '.join(fam.presets)}.",
    )
    p.add_argument(
        "--preset", default=None, help=f"start from a preset (default {fam.default_preset})"
    )
    p.add_argument("--list-presets", action="store_true", help="list presets and exit")
    p.add_argument("--out", "-o", metavar="FILE", help="output .stl or .3mf (default: <name>.stl)")
    p.add_argument("--ascii", action="store_true", help="write ASCII STL instead of binary")
    p.add_argument("--json", action="store_true", help="print the summary as JSON")
    p.add_argument("--force", action="store_true", help="write the file even with errors")
    _machine_args(p)
    if fam.name == "bead":
        p.add_argument(
            "--count",
            type=int,
            default=0,
            metavar="N",
            help="make N beads packed on plates; --out is then a directory",
        )
        p.add_argument("--spacing", type=float, default=3.0, metavar="MM", help="with --count")
    group = p.add_argument_group("parameters")
    for f in param_fields(fam.params_type):
        flag = "--" + f.name.replace("_", "-")
        md = f.metadata
        unit = f" [{md['unit']}]" if md["unit"] else ""
        help_text = f"{md['help']}{unit} (default {f.default!r})"
        if isinstance(f.default, bool):
            group.add_argument(
                flag,
                dest=f.name,
                action=argparse.BooleanOptionalAction,
                default=None,
                help=help_text,
            )
        else:
            group.add_argument(
                flag,
                dest=f.name,
                default=None,
                metavar=(
                    "{" + ",".join(md["choices"]) + "}"
                    if md["choices"]
                    else md["unit"].upper() or type(f.default).__name__.upper()
                ),
                choices=md["choices"],
                help=help_text,
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="print-forge",
        description="Parametric generators for small FDM batch products: closed meshes, "
        "packed plates and a batch plan.",
    )
    parser.add_argument("--version", action="version", version=f"print-forge {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    for fam in FAMILIES.values():
        _family_parser(sub, fam)
    plate = sub.add_parser(
        "plate",
        help="pack the parts listed in a TOML file onto plates (3MF) with a batch manifest",
        description="Generate every part in PARTS, pack them onto plates per material and "
        "write plate-NN.3mf, manifest.csv/json and a printfarm-planner jobs.csv.",
    )
    plate.add_argument("parts", help="parts file (TOML), see examples/parts.toml")
    plate.add_argument("--out", "-o", required=True, metavar="DIR", help="output directory")
    plate.add_argument(
        "--printer", type=printer_key, choices=sorted(PRINTERS), help="overrides [plate] printer"
    )
    plate.add_argument("--force", action="store_true", help="plate parts even with errors")
    plate.add_argument("--json", action="store_true", help="print the manifest as JSON")
    cat = sub.add_parser(
        "catalogue",
        help="write an HTML catalogue of every preset with renders and validation",
        description="Render every preset of every family into one self-contained HTML page.",
    )
    cat.add_argument("--out", "-o", required=True, metavar="HTML")
    cat.add_argument(
        "--family",
        action="append",
        choices=sorted(FAMILIES),
        help="only these families (repeatable; default all)",
    )
    _machine_args(cat)
    return parser


def _settings(args: argparse.Namespace) -> PrintSettings:
    return PrintSettings(PRINTERS[args.printer or DEFAULT_PRINTER], args.nozzle, args.overhang)


def _overrides(args: argparse.Namespace, fam: Family[Any]) -> dict[str, Any]:
    return {
        f.name: getattr(args, f.name)
        for f in param_fields(fam.params_type)
        if getattr(args, f.name) is not None
    }


def _summary_lines(part: Part, settings: PrintSettings, wrote: str | None) -> list[str]:
    sx, sy, sz = part.mesh.size()
    topo = part.mesh.topology()
    est = estimate(part.mesh, FilamentModel(), vase_mode=part.vase_mode)
    lines = [f"print-forge {__version__}  {part.family}: {part.name}"]
    if wrote:
        lines.append(f"  wrote      {wrote}")
    lines += [
        f"  size       {sx:.2f} x {sy:.2f} x {sz:.2f} mm  ({settings.printer.label()})",
        f"  volume     {part.mesh.volume():.1f} mm^3, surface {part.mesh.area():.1f} mm^2",
        f"  mesh       {len(part.mesh.faces)} triangles, "
        + ("closed and consistently wound" if topo.closed else "NOT CLOSED")
        + f", {topo.shells} shell(s)",
        f"  filament   ~{est.grams:.2f} g PLA (rough model: 2 walls x 0.42 mm, 15% infill)",
    ]
    for i in part.issues:
        lines.append(f"  {i.severity:<10} {i.message}")
    for n in part.notes:
        lines.append(f"  -          {n}")
    errors = sum(i.severity == ERROR for i in part.issues)
    warnings = sum(i.severity == WARNING for i in part.issues)
    verdict = "FAIL" if errors else "OK"
    lines.append(
        f"verdict: {verdict} ({errors} error{'s' * (errors != 1)}, "
        f"{warnings} warning{'s' * (warnings != 1)})"
    )
    return lines


def cmd_family(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    fam = FAMILIES[args.command]
    if args.list_presets:
        for name, values in fam.presets.items():
            vals = ", ".join(f"{k}={v}" for k, v in values.items())
            out.write(f"{name:<20} {vals}\n")
        return EXIT_OK
    settings = _settings(args)
    params = fam.make_params(args.preset, _overrides(args, fam))
    if fam.name == "bead" and args.count:
        return _bead_batch(args, params, settings, out)
    part = fam.generate(params, settings)
    part.mesh = part.mesh.on_bed()
    wrote = None
    if not part.ok and not args.force:
        lines = _summary_lines(part, settings, None)
        lines.insert(1, "  not written: fix the errors below or pass --force")
    else:
        path = Path(args.out or f"{part.name}.stl")
        if path.suffix.lower() == ".3mf":
            write_3mf(path, [part.mesh], title=part.name)
            wrote = f"{path} (3MF, {len(part.mesh.faces)} triangles, units mm)"
        else:
            write_stl(path, part.mesh, ascii=args.ascii)
            kind = "ASCII" if args.ascii else "binary"
            wrote = f"{path} ({kind} STL, {len(part.mesh.faces)} triangles)"
        lines = _summary_lines(part, settings, wrote)
    if args.json:
        payload = {
            "family": part.family,
            "name": part.name,
            "written": wrote is not None,
            "output": str(args.out or f"{part.name}.stl") if wrote else None,
            "params": part.params,
            "size_mm": [round(v, 3) for v in part.mesh.size()],
            "volume_mm3": round(part.mesh.volume(), 3),
            "triangles": len(part.mesh.faces),
            "closed": part.mesh.topology().closed,
            "issues": [i.to_dict() for i in part.issues],
            "notes": part.notes,
        }
        out.write(json.dumps(payload, indent=2) + "\n")
    else:
        out.write("\n".join(lines) + "\n")
    return EXIT_OK if wrote else EXIT_ERROR


def _bead_batch(args: argparse.Namespace, params: Any, settings: PrintSettings, out: TextIO) -> int:
    if args.count < 1:
        raise BatchError("--count must be positive")
    if not args.out:
        raise BatchError("--count needs --out DIR")
    config = BatchConfig(
        printer=settings.printer,
        nozzle=settings.nozzle,
        overhang_limit=settings.overhang_limit,
        spacing=args.spacing,
    )
    spec = PartSpec(
        name=FAMILIES["bead"].label_fn(params),
        family="bead",
        preset=None,  # every field is given in params
        params=dataclasses.asdict(params),
        copies=args.count,
        material=config.material,
    )
    plan = plan_batch([spec], config, force=args.force)
    written = write_outputs(plan, args.out)
    _print_plan(plan, written, out)
    return EXIT_OK


def _print_plan(plan: Any, written: list[Path], out: TextIO) -> None:
    t = totals(plan)
    out.write(f"print-forge {__version__}  batch for {plan.config.printer.label()}\n")
    for plate in plan.plates:
        counts = ", ".join(f"{n} x{c}" for n, c in plate.counts().items())
        out.write(
            f"  {plate.file_name}  x{plate.copies}  {plate.material:<10} {counts}; "
            f"~{plan.plate_grams(plate):.1f} g, ~{plan.plate_minutes(plate):.0f} min\n"
        )
    for name, part in plan.parts.items():
        for i in part.issues:
            if i.severity in (ERROR, WARNING):
                out.write(f"  {i.severity}: {name}: {i.message}\n")
    out.write(
        f"  total: {t['plates_to_print']} plate(s) to print ({t['distinct_plates']} distinct), "
        f"~{t['filament_g']:.0f} g filament, ~{t['print_time_min'] / 60:.1f} h (rough model)\n"
    )
    out.write("  wrote " + ", ".join(p.name for p in written) + f" to {written[0].parent}\n")


def cmd_plate(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    config, specs = load_parts_file(args.parts, args.printer)
    plan = plan_batch(specs, config, force=args.force)
    written = write_outputs(plan, args.out)
    if args.json:
        out.write((Path(args.out) / "manifest.json").read_text(encoding="utf-8"))
    else:
        _print_plan(plan, written, out)
    return EXIT_OK


def cmd_catalogue(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    settings = _settings(args)
    model = FilamentModel()
    sections = []
    n = 0
    for fam in FAMILIES.values():
        if args.family and fam.name not in args.family:
            continue
        items = []
        for preset in fam.presets:
            params = fam.make_params(preset)
            part = fam.generate(params, settings, name=f"{fam.name} / {preset}")
            part.mesh = part.mesh.on_bed()
            render = None
            coarse = coarse_params_for_preview(params, 6000)
            if coarse:
                render = fam.build_fn(dataclasses.replace(params, **coarse)).on_bed()
            items.append((part, estimate(part.mesh, model, part.vase_mode), render))
            n += 1
        sections.append((fam.name.capitalize(), fam.summary, items))
    Path(args.out).write_text(
        catalogue_html(sections, settings.printer.label(), settings.nozzle), encoding="utf-8"
    )
    out.write(f"wrote {args.out}: {n} parts from {len(sections)} families\n")
    return EXIT_OK


def main(
    argv: Sequence[str] | None = None, out: TextIO | None = None, err: TextIO | None = None
) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    args = build_parser().parse_args(argv)
    try:
        if args.command == "plate":
            return cmd_plate(args, out, err)
        if args.command == "catalogue":
            return cmd_catalogue(args, out, err)
        return cmd_family(args, out, err)
    except (ParamError, BatchError, ValueError, OSError) as exc:
        print(f"print-forge: error: {exc}", file=err)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
