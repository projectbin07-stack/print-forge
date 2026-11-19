"""What every product family provides, and the generic parameter plumbing.

A family is a module with a parameter dataclass, named presets, a ``build`` function that returns
a closed :class:`~print_forge.mesh.Mesh`, and a ``check`` function that returns printability
issues. Parameters are dataclass fields whose metadata carries the help text, unit and limits,
which the CLI, the catalogue and the README tables are generated from.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from ..mesh import Mesh
from ..validate import Issue, PrintSettings, bed_issues, mesh_issues

P = TypeVar("P")


def param(
    default: Any,
    help: str,
    unit: str = "",
    lo: float | None = None,
    hi: float | None = None,
    choices: tuple[str, ...] | None = None,
) -> Any:
    """A parameter field: default plus documentation and simple range limits."""
    meta = {"help": help, "unit": unit, "lo": lo, "hi": hi, "choices": choices}
    return field(default=default, metadata=meta)


class ParamError(ValueError):
    """A parameter value is out of range or of the wrong type."""


def param_fields(cls: type) -> list[dataclasses.Field[Any]]:
    return [f for f in dataclasses.fields(cls) if "help" in f.metadata]


def coerce(f: dataclasses.Field[Any], value: Any) -> Any:
    """Convert a CLI/TOML value to the field's type and check its limits."""
    kind: type[Any] = type(f.default)
    try:
        if kind is bool:
            if isinstance(value, str):
                low = value.strip().lower()
                if low not in ("true", "false", "yes", "no", "1", "0", "on", "off"):
                    raise ValueError(value)
                value = low in ("true", "yes", "1", "on")
            else:
                value = bool(value)
        elif kind is int:
            if isinstance(value, float) and not value.is_integer():
                raise ValueError(value)
            value = int(value)
        elif kind is float:
            value = float(value)
        else:
            value = str(value)
    except (TypeError, ValueError):
        raise ParamError(f"{f.name}: {value!r} is not a valid {kind.__name__}") from None
    md = f.metadata
    if md["choices"] and value not in md["choices"]:
        raise ParamError(f"{f.name}: {value!r} is not one of {', '.join(md['choices'])}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if md["lo"] is not None and value < md["lo"]:
            raise ParamError(f"{f.name}: {value} is below the minimum {md['lo']}")
        if md["hi"] is not None and value > md["hi"]:
            raise ParamError(f"{f.name}: {value} is above the maximum {md['hi']}")
    return value


@dataclass
class Part:
    """A generated part: mesh, the parameters that made it and what validation found."""

    family: str
    name: str
    mesh: Mesh
    params: dict[str, Any]
    issues: list[Issue]
    notes: list[str] = field(default_factory=list)
    vase_mode: bool = False

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)


@dataclass(frozen=True)
class Family(Generic[P]):
    name: str
    summary: str
    params_type: type[P]
    presets: Mapping[str, Mapping[str, Any]]
    default_preset: str
    build_fn: Callable[[P], Mesh]
    check_fn: Callable[[P, PrintSettings, Mesh], list[Issue]]
    notes_fn: Callable[[P], list[str]]
    label_fn: Callable[[P], str]

    def make_params(
        self, preset: str | None = None, overrides: Mapping[str, Any] | None = None
    ) -> P:
        preset = preset or self.default_preset
        if preset not in self.presets:
            raise ParamError(
                f"unknown {self.name} preset {preset!r}; choose one of {', '.join(self.presets)}"
            )
        fields = {f.name: f for f in param_fields(self.params_type)}
        values: dict[str, Any] = {}
        for source in (self.presets[preset], overrides or {}):
            for key, value in source.items():
                key = key.replace("-", "_")
                if key not in fields:
                    raise ParamError(f"{self.name} has no parameter {key!r}")
                values[key] = coerce(fields[key], value)
        return self.params_type(**values)

    def generate(
        self, params: P, settings: PrintSettings | None = None, name: str | None = None
    ) -> Part:
        settings = settings or PrintSettings()
        mesh = self.build_fn(params)
        mesh.name = name or self.label_fn(params)
        issues = mesh_issues(mesh) + bed_issues(mesh, settings)
        issues += self.check_fn(params, settings, mesh)
        return Part(
            family=self.name,
            name=mesh.name,
            mesh=mesh,
            params=dataclasses.asdict(params),  # type: ignore[call-overload]
            issues=issues,
            notes=self.notes_fn(params),
            vase_mode=bool(getattr(params, "vase_mode", False)),
        )
