"""Immutable model-independent domain records."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path, PurePath
from types import MappingProxyType
from typing import Any


class WeatherStrategy(Enum):
    """How an adapter expects experiment weather to be assembled."""

    G2F = "g2f"


class ScanRequestStrategy(Enum):
    """How scan requests should be materialized for an adapter."""

    PER_DATE = "per_date"
    SLICE_WEATHER_HORIZON = "slice_weather_horizon"


class FoldStrategy(Enum):
    """Validation/calibration folds supported by an adapter."""

    HELD_YEAR = "held_year"
    LEAVE_SITE = "leave_site"


@dataclass(frozen=True)
class CalibrationParameter:
    """A model parameter exposed to the shared coarse/fine calibration search."""

    name: str
    default: float
    coarse_grid: tuple[float, float, float]
    fine_step: float


@dataclass(frozen=True)
class ModelCapabilities:
    """Declarative contract consumed by model-independent orchestration."""

    display_name: str = "Unknown model"
    phenology_parameter: CalibrationParameter = CalibrationParameter(
        "phenology_scale", 1.0, (0.8, 1.2, 0.02), 0.005
    )
    yield_parameter: CalibrationParameter = CalibrationParameter(
        "HI0", 0.48, (0.35, 0.55, 0.01), 0.0025
    )
    site_calibration_supported: bool = False
    site_phenology_parameter: str = "phenology_scale_site"
    site_yield_parameter: str = "HI0_site"
    supported_folds: tuple[FoldStrategy, ...] = (FoldStrategy.HELD_YEAR,)
    weather_strategy: WeatherStrategy = WeatherStrategy.G2F
    scan_request_strategy: ScanRequestStrategy = ScanRequestStrategy.PER_DATE
    report_notes: tuple[str, ...] = ()

    @property
    def supports_site_calibration(self) -> bool:
        return self.site_calibration_supported


class RunStatus(str, Enum):
    MATURED = "matured"
    CROP_DIED = "crop_died"
    NOT_GERMINATED = "not_germinated"
    NOT_MATURED = "not_matured"
    INSUFFICIENT_THERMAL_TIME = "insufficient_thermal_time"
    MODEL_LIMIT = "model_limit"
    INVALID_INPUT = "invalid_input"
    EXECUTION_FAILED = "execution_failed"


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((_freeze(item) for item in value), key=repr))
    return value


def _json_key(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, PurePath):
        return str(value)
    return str(value)


def _to_json_compatible(value: Any) -> Any:
    if isinstance(value, Enum):
        return _to_json_compatible(value.value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, PurePath):
        return str(value)
    if is_dataclass(value):
        return {
            item.name: _to_json_compatible(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Mapping):
        converted: dict[str, Any] = {}
        for key, item in value.items():
            json_key = _json_key(key)
            if json_key in converted:
                raise ValueError(
                    f"mapping keys collide after serialization: {json_key}"
                )
            converted[json_key] = _to_json_compatible(item)
        return {key: converted[key] for key in sorted(converted)}
    if isinstance(value, (tuple, list)):
        return [_to_json_compatible(item) for item in value]
    if isinstance(value, (set, frozenset)):
        converted_items = [_to_json_compatible(item) for item in value]
        return sorted(converted_items, key=repr)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"{type(value).__name__} is not JSON-compatible")


class StableRecord:
    """Shared immutable serialization and hashing behavior."""

    def __post_init__(self) -> None:
        for item in fields(self):
            object.__setattr__(self, item.name, _freeze(getattr(self, item.name)))

    def to_json_dict(self) -> dict[str, Any]:
        serialized = _to_json_compatible(self)
        if not isinstance(serialized, dict):
            raise TypeError("record serialization must produce a dictionary")
        return serialized

    def to_dict(self) -> dict[str, Any]:
        return self.to_json_dict()

    def canonical_json(self) -> str:
        return json.dumps(
            self.to_json_dict(),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class WeatherRecord(StableRecord):
    environment_id: str
    date: date
    values: Mapping[str, Any] = field(default_factory=dict)
    source: str = ""

    __hash__ = None


@dataclass(frozen=True)
class SoilLayer(StableRecord):
    top_depth_m: float
    bottom_depth_m: float
    properties: Mapping[str, Any] = field(default_factory=dict)
    source: str = ""

    __hash__ = None


@dataclass(frozen=True)
class Environment(StableRecord):
    environment_id: str
    year: int
    location: str
    latitude: float
    longitude: float
    weather: tuple[WeatherRecord, ...] = ()
    soil: tuple[SoilLayer, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    __hash__ = None


@dataclass(frozen=True)
class ManagementUnit(StableRecord):
    management_unit_id: str
    environment_id: str
    planting_date: date
    cultivar_id: str = ""
    population_plants_m2: float | None = None
    irrigation_assumption: str = "unknown"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    __hash__ = None


@dataclass(frozen=True)
class Observation(StableRecord):
    observation_id: str
    management_unit_id: str
    variable: str
    value: float
    unit: str
    observed_on: date | None = None
    source_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    __hash__ = None


@dataclass(frozen=True)
class SimulationRequest(StableRecord):
    request_id: str
    environment: Environment
    management: ManagementUnit
    start_date: date
    end_date: date
    model_parameters: Mapping[str, Any] = field(default_factory=dict)
    parameter_set_id: str = "default"
    output_dir: Path | None = None

    __hash__ = None


@dataclass(frozen=True)
class SimulationResult(StableRecord):
    request_id: str
    adapter_name: str
    adapter_version: str
    status: RunStatus
    summary: Mapping[str, Any] = field(default_factory=dict)
    artifacts: Mapping[str, Path] = field(default_factory=dict)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    failure_reason: str | None = None

    __hash__ = None
