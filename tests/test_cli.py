from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from print_forge.cli import main
from print_forge.io_3mf import read_3mf
from print_forge.io_stl import read_stl

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "parts.toml"


def run(*args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = main(list(args), out, err)
    return code, out.getvalue(), err.getvalue()


def test_vase_stl(tmp_path: Path) -> None:
    path = tmp_path / "vase.stl"
    code, out, _ = run(
        "vase", "--preset", "tulip", "--height", "60", "--segments", "48", "--rings", "30",
        "--out", str(path),
    )  # fmt: skip
    assert code == 0, out
    assert "closed and consistently wound" in out
    assert "verdict: OK" in out
    m = read_stl(path)
    assert m.size()[2] == pytest.approx(60, abs=1e-4)
    assert m.topology().closed


def test_letter_3mf_and_json(tmp_path: Path) -> None:
    path = tmp_path / "nav.3mf"
    code, out, _ = run("letter", "--text", "NAV", "--out", str(path), "--json")
    assert code == 0
    data = json.loads(out)
    assert data["written"] and data["closed"] and data["params"]["text"] == "NAV"
    doc = read_3mf(path)
    assert doc.unit == "millimeter"
    assert next(iter(doc.objects.values())).name == "keychain-NAV"


def test_bead_and_cap_ascii(tmp_path: Path) -> None:
    code, out, _ = run("bead", "--preset", "gem-12", "--out", str(tmp_path / "b.stl"), "--ascii")
    assert code == 0 and "ASCII STL" in out
    code, out, _ = run("cap", "--legend", "N", "--out", str(tmp_path / "c.stl"))
    assert code == 0
    assert "warning" in out and "stem wall" in out


def test_default_output_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    code, _, _ = run("bead")
    assert code == 0
    assert (tmp_path / "bead-sphere-10mm.stl").exists()


def test_errors_refuse_to_write_without_force(tmp_path: Path) -> None:
    path = tmp_path / "flare.stl"
    code, out, _ = run("vase", "--profile", "0:5,1:40", "--height", "20", "--out", str(path))
    assert code == 2
    assert "not written" in out and "verdict: FAIL" in out
    assert not path.exists()
    code, _, _ = run(
        "vase", "--profile", "0:5,1:40", "--height", "20", "--out", str(path), "--force"
    )
    assert code == 0 and path.exists()


def test_bad_parameters_are_reported() -> None:
    code, _, err = run("bead", "--diameter", "abc")
    assert code == 2 and "not a valid float" in err
    code, _, err = run("letter", "--text", "é")
    assert code == 2 and "unsupported" in err
    with pytest.raises(SystemExit):
        run("bead", "--shape", "cube")


def test_list_presets() -> None:
    code, out, _ = run("cap", "--list-presets")
    assert code == 0
    assert out.splitlines()[0].startswith("spherical-1u")


def test_boolean_flags(tmp_path: Path) -> None:
    code, out, _ = run(
        "vase", "--vase-mode", "--segments", "32", "--rings", "16", "--out", str(tmp_path / "v.stl")
    )
    assert code == 0 and "spiral vase" in out.lower()
    code, out, _ = run("bead", "--no-supportless", "--out", str(tmp_path / "s.stl"), "--force")
    assert code == 0 and "overhang" in out


def test_bead_batch(tmp_path: Path) -> None:
    out_dir = tmp_path / "beads"
    code, out, _ = run(
        "bead", "--count", "150", "--printer", "a1-mini", "--spacing", "5", "--out", str(out_dir)
    )
    assert code == 0, out
    assert (out_dir / "plate-01.3mf").exists() and (out_dir / "jobs.csv").exists()
    assert "plate(s) to print" in out
    code, _, err = run("bead", "--count", "5")
    assert code == 2 and "--out" in err


def test_plate_command(tmp_path: Path) -> None:
    code, out, _ = run("plate", str(EXAMPLE), "--out", str(tmp_path / "plates"))
    assert code == 0, out
    assert "Bambu Lab A1 mini" in out
    assert (tmp_path / "plates" / "manifest.json").exists()
    code, out, _ = run(
        "plate", str(EXAMPLE), "--printer", "p1s", "--out", str(tmp_path / "p1s"), "--json"
    )
    assert code == 0
    assert json.loads(out)["printer"].startswith("Bambu Lab P1S")
    code, _, err = run("plate", str(tmp_path / "missing.toml"), "--out", str(tmp_path))
    assert code == 2 and "error" in err


def test_catalogue_command(tmp_path: Path) -> None:
    page = tmp_path / "cat.html"
    code, out, _ = run("catalogue", "--family", "bead", "--family", "cap", "--out", str(page))
    assert code == 0
    assert "10 parts from 2 families" in out
    text = page.read_text(encoding="utf-8")
    assert text.count("<svg") == 30


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "print-forge" in capsys.readouterr().out
