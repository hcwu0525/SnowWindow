"""Typed YAML configuration for SnowWindow experiments."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when an experiment configuration is invalid."""


def _frozen_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    frozen: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, Mapping):
            frozen[str(key)] = _frozen_mapping(item)
        elif isinstance(item, list):
            frozen[str(key)] = tuple(item)
        else:
            frozen[str(key)] = item
    return MappingProxyType(frozen)


@dataclass(frozen=True)
class ModelConfig:
    name: str
    parameters: Mapping[str, Any]


@dataclass(frozen=True)
class SelectionConfig:
    calibration_years: tuple[int, ...]
    evaluation_years: tuple[int, ...]
    environments: tuple[str, ...] = ()
    all_eligible_environments: bool = False
    allow_assumed_rainfed: bool = False
    exclude_default_soil_from_calibration: bool = True
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SimulationConfig:
    scan_fractions: tuple[float, ...]
    workers: int
    scan_all_dates: bool = False
    parameter_sets: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExperimentConfig:
    experiment_id: str
    data_dir: Path
    output_dir: Path
    model: ModelConfig
    selection: SelectionConfig
    simulation: SimulationConfig
    source_path: Path

    @property
    def experiment_dir(self) -> Path:
        return self.output_dir / "experiments" / self.experiment_id


def _require(data: Mapping[str, Any], key: str, context: str = "configuration") -> Any:
    if key not in data:
        raise ConfigError(f"{context} requires {key}")
    return data[key]


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigError(f"{name} must be a mapping")
    return value


def _nonempty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name} must be a nonempty string")
    return value.strip()


def _years(value: Any, name: str) -> tuple[int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ConfigError(f"{name} must be a sequence of years")
    years = []
    for year in value:
        if isinstance(year, bool) or not isinstance(year, int):
            raise ConfigError(f"{name} must contain integer years")
        years.append(year)
    return tuple(years)


def _fractions(value: Any) -> tuple[float, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise ConfigError("simulation.scan_fractions must be a nonempty sequence")
    fractions = []
    for fraction in value:
        if isinstance(fraction, bool) or not isinstance(fraction, (int, float)):
            raise ConfigError("simulation.scan_fractions must contain numbers")
        normalized = float(fraction)
        if not 0.0 < normalized <= 1.0:
            raise ConfigError("simulation.scan_fractions values must be in (0, 1]")
        fractions.append(normalized)
    return tuple(fractions)


def _resolve_path(value: Any, config_dir: Path, name: str) -> Path:
    if not isinstance(value, (str, Path)):
        raise ConfigError(f"{name} must be a path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = config_dir / path
    return path.resolve()


def _extra_options(
    data: Mapping[str, Any], known_keys: Sequence[str]
) -> Mapping[str, Any]:
    return _frozen_mapping(
        {key: value for key, value in data.items() if key not in known_keys}
    )


def load_config(path: Path) -> ExperimentConfig:
    source_path = Path(path).expanduser().resolve()
    try:
        loaded = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read configuration {source_path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {source_path}: {exc}") from exc

    root = _require_mapping(loaded, "configuration")
    experiment_id = _nonempty_string(_require(root, "experiment_id"), "experiment_id")
    data_dir = _resolve_path(_require(root, "data_dir"), source_path.parent, "data_dir")
    output_dir = _resolve_path(
        _require(root, "output_dir"), source_path.parent, "output_dir"
    )

    model_data = _require_mapping(_require(root, "model"), "model")
    model_name = _nonempty_string(_require(model_data, "name", "model"), "model.name")
    model_parameters = _require_mapping(
        _require(model_data, "parameters", "model"), "model.parameters"
    )
    model = ModelConfig(
        name=model_name,
        parameters=_frozen_mapping(model_parameters),
    )

    selection_data = _require_mapping(_require(root, "selection"), "selection")
    calibration_years = _years(
        _require(selection_data, "calibration_years", "selection"),
        "selection.calibration_years",
    )
    evaluation_years = _years(
        _require(selection_data, "evaluation_years", "selection"),
        "selection.evaluation_years",
    )
    overlap = sorted(set(calibration_years).intersection(evaluation_years))
    if overlap:
        raise ConfigError(
            "selection.calibration_years and selection.evaluation_years "
            f"must be disjoint; overlap: {overlap}"
        )
    environments_value = selection_data.get("environments", ())
    if not isinstance(environments_value, Sequence) or isinstance(
        environments_value, (str, bytes)
    ):
        raise ConfigError("selection.environments must be a sequence")
    environments = tuple(
        _nonempty_string(value, "selection.environments entry")
        for value in environments_value
    )
    selection = SelectionConfig(
        calibration_years=calibration_years,
        evaluation_years=evaluation_years,
        environments=environments,
        all_eligible_environments=bool(
            selection_data.get("all_eligible_environments", False)
        ),
        allow_assumed_rainfed=bool(selection_data.get("allow_assumed_rainfed", False)),
        exclude_default_soil_from_calibration=bool(
            selection_data.get("exclude_default_soil_from_calibration", True)
        ),
        options=_extra_options(
            selection_data,
            (
                "calibration_years",
                "evaluation_years",
                "environments",
                "all_eligible_environments",
                "allow_assumed_rainfed",
                "exclude_default_soil_from_calibration",
            ),
        ),
    )

    simulation_data = _require_mapping(_require(root, "simulation"), "simulation")
    scan_fractions = _fractions(
        _require(simulation_data, "scan_fractions", "simulation")
    )
    workers = _require(simulation_data, "workers", "simulation")
    if isinstance(workers, bool) or not isinstance(workers, int) or workers <= 0:
        raise ConfigError("simulation.workers must be a positive integer")
    parameter_sets_data = _require_mapping(
        simulation_data.get("parameter_sets", {}), "simulation.parameter_sets"
    )
    parameter_sets: dict[str, Mapping[str, Any]] = {}
    for name, parameters in parameter_sets_data.items():
        normalized_name = _nonempty_string(name, "parameter set name")
        parameter_sets[normalized_name] = _frozen_mapping(
            _require_mapping(parameters, f"simulation.parameter_sets.{normalized_name}")
        )
    simulation = SimulationConfig(
        scan_fractions=scan_fractions,
        workers=workers,
        scan_all_dates=bool(simulation_data.get("scan_all_dates", False)),
        parameter_sets=MappingProxyType(parameter_sets),
        options=_extra_options(
            simulation_data,
            ("scan_fractions", "workers", "scan_all_dates", "parameter_sets"),
        ),
    )

    return ExperimentConfig(
        experiment_id=experiment_id,
        data_dir=data_dir,
        output_dir=output_dir,
        model=model,
        selection=selection,
        simulation=simulation,
        source_path=source_path,
    )
