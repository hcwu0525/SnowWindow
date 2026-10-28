"""Typed YAML configuration for SnowWindow experiments."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from snowwindow.weather import WEATHER_POLICY


@dataclass(frozen=True)
class CalibrationConfig:
    phenology_grid: tuple[float, float, float]
    phenology_fine_step: float
    yield_grid: tuple[float, float, float]
    yield_fine_step: float


class ConfigError(ValueError):
    """Raised when an experiment configuration is invalid."""


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _frozen_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    return value


def _frozen_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(
        {str(key): _freeze_value(item) for key, item in value.items()}
    )


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
    calibration: CalibrationConfig
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


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{name} must be a boolean")
    return value


def _years(value: Any, name: str) -> tuple[int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ConfigError(f"{name} must be a sequence of years")
    years = []
    for year in value:
        if isinstance(year, bool) or not isinstance(year, int):
            raise ConfigError(f"{name} must contain integer years")
        years.append(year)
    return tuple(years)


def _grid(value: Any, name: str) -> tuple[float, float, float]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 3
    ):
        raise ConfigError(f"{name} must be a three-number [start, stop, step] grid")
    numbers = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ConfigError(f"{name} must contain numbers")
        numbers.append(float(item))
    start, stop, step = numbers
    if not step > 0 or stop <= start:
        raise ConfigError(f"{name} must have stop > start and positive step")
    return start, stop, step


def _fine_step(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{name} must be a positive number")
    number = float(value)
    if not number > 0:
        raise ConfigError(f"{name} must be a positive number")
    return number


def _calibration_config(
    root: Mapping[str, Any], selection: SelectionConfig, model_name: str
) -> CalibrationConfig:
    unified = _require_mapping(root.get("calibration", {}), "calibration")
    options = dict(selection.options)
    legacy_keys = {
        "aquacrop": ("phenology_scale", "harvest_index"),
        "apsim": ("juvenile_tt", "grain_number_scale"),
        "dssat": ("P1", "G2"),
    }
    legacy_phenology, legacy_yield = legacy_keys.get(model_name, ("", ""))

    def first(*keys: str, default: Any) -> Any:
        for key in keys:
            if key in unified:
                return unified[key]
        for key in keys:
            if key in options:
                return options[key]
        return default

    phenology_default = (0.8, 1.2, 0.02)
    yield_default = (0.35, 0.55, 0.01)
    if model_name == "apsim":
        phenology_default = (100.0, 350.0, 25.0)
        yield_default = (0.5, 1.5, 0.1)
    elif model_name == "dssat":
        phenology_default = (150.0, 350.0, 50.0)
        yield_default = (700.0, 950.0, 50.0)
    phenology_fine_default = 0.005
    yield_fine_default = 0.0025
    if model_name == "apsim":
        phenology_fine_default = 5.0
        yield_fine_default = 0.02
    elif model_name == "dssat":
        phenology_fine_default = 10.0
        yield_fine_default = 10.0

    return CalibrationConfig(
        phenology_grid=_grid(
            first(
                "phenology_grid",
                f"{legacy_phenology}_grid",
                default=phenology_default,
            ),
            "calibration.phenology_grid",
        ),
        phenology_fine_step=_fine_step(
            first(
                "phenology_fine_step",
                f"{legacy_phenology}_fine_step",
                default=phenology_fine_default,
            ),
            "calibration.phenology_fine_step",
        ),
        yield_grid=_grid(
            first("yield_grid", f"{legacy_yield}_grid", default=yield_default),
            "calibration.yield_grid",
        ),
        yield_fine_step=_fine_step(
            first(
                "yield_fine_step",
                f"{legacy_yield}_fine_step",
                default=yield_fine_default,
            ),
            "calibration.yield_fine_step",
        ),
    )


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
        all_eligible_environments=_boolean(
            selection_data.get("all_eligible_environments", False),
            "selection.all_eligible_environments",
        ),
        allow_assumed_rainfed=_boolean(
            selection_data.get("allow_assumed_rainfed", False),
            "selection.allow_assumed_rainfed",
        ),
        exclude_default_soil_from_calibration=_boolean(
            selection_data.get("exclude_default_soil_from_calibration", True),
            "selection.exclude_default_soil_from_calibration",
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
        scan_all_dates=_boolean(
            simulation_data.get("scan_all_dates", False),
            "simulation.scan_all_dates",
        ),
        parameter_sets=MappingProxyType(parameter_sets),
        options=_extra_options(
            simulation_data,
            ("scan_fractions", "workers", "scan_all_dates", "parameter_sets"),
        ),
    )
    calibration = _calibration_config(root, selection, model_name)

    return ExperimentConfig(
        experiment_id=experiment_id,
        data_dir=data_dir,
        output_dir=output_dir,
        model=model,
        selection=selection,
        simulation=simulation,
        calibration=calibration,
        source_path=source_path,
    )


def _snapshot_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _snapshot_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_snapshot_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _snapshot_document(config: ExperimentConfig) -> dict[str, Any]:
    return _snapshot_value(
        {
            "experiment_id": config.experiment_id,
            "weather_policy": WEATHER_POLICY,
            "data_dir": config.data_dir,
            "output_dir": config.output_dir,
            "model": {
                "name": config.model.name,
                "parameters": config.model.parameters,
            },
            "selection": {
                **config.selection.options,
                "calibration_years": config.selection.calibration_years,
                "evaluation_years": config.selection.evaluation_years,
                "environments": config.selection.environments,
                "all_eligible_environments": config.selection.all_eligible_environments,
                "allow_assumed_rainfed": config.selection.allow_assumed_rainfed,
                "exclude_default_soil_from_calibration": (
                    config.selection.exclude_default_soil_from_calibration
                ),
            },
            "calibration": {
                "phenology_grid": config.calibration.phenology_grid,
                "phenology_fine_step": config.calibration.phenology_fine_step,
                "yield_grid": config.calibration.yield_grid,
                "yield_fine_step": config.calibration.yield_fine_step,
            },
            "simulation": {
                **config.simulation.options,
                "scan_fractions": config.simulation.scan_fractions,
                "workers": config.simulation.workers,
                "scan_all_dates": config.simulation.scan_all_dates,
                "parameter_sets": config.simulation.parameter_sets,
            },
        }
    )


def save_config_snapshot(config: ExperimentConfig) -> Path:
    """Persist a reloadable CLI configuration without replacing prior settings."""

    path = config.experiment_dir / "config.yaml"
    expected = _snapshot_document(config)
    if not path.exists():
        serialized = yaml.safe_dump(expected, allow_unicode=True, sort_keys=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_prefix = f".{path.name}-"
        artifacts = [
            entry for entry in path.parent.iterdir()
            if entry != path and not (
                entry.name.startswith(temporary_prefix) and entry.name.endswith(".tmp")
            )
        ]
        if artifacts and not path.exists():
            raise ConfigError(
                f"experiment_id {config.experiment_id!r} has existing outputs "
                f"without a configuration snapshot at {path}; "
                "use a new experiment_id to preserve historical outputs"
            )
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=temporary_prefix,
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                # Publish a complete document without replacing a competing writer.
                os.link(temporary, path)
            except FileExistsError:
                pass
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    try:
        stored = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid configuration snapshot at {path}: {exc}") from exc
    if not isinstance(stored, dict) or stored.get("weather_policy") != WEATHER_POLICY:
        raise ConfigError(
            f"experiment_id {config.experiment_id!r} has an incompatible "
            "weather policy "
            f"at {path}; use a new experiment_id"
        )
    existing = load_config(path)
    if _snapshot_document(existing) != expected:
        raise ConfigError(
            f"experiment_id {config.experiment_id!r} already has a different "
            f"configuration at {path}; use a new experiment_id"
        )
    return path
