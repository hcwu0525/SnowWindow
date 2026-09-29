"""Stable adapter for the pinned AquaCrop-OSPy implementation."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import time
import traceback
import uuid
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from aquacrop import (
    AquaCropModel,
    Crop,
    InitialWaterContent,
    IrrigationManagement,
    Soil,
)
from aquacrop.entities.crops.crop_params import crop_params
from aquacrop.utils import get_filepath, prepare_weather

from snowwindow.domain import (
    CalibrationParameter,
    FoldStrategy,
    ModelCapabilities,
    RunStatus,
    ScanRequestStrategy,
    SimulationRequest,
    SimulationResult,
    WeatherStrategy,
)
from snowwindow.models.aquacrop.physics import reference_et

ADAPTER_NAME = "aquacrop"
MODEL_VERSION = "3.1.0"
DEFAULT_CROP = "MaizeGDD"
THERMAL_KEYS = (
    "Emergence",
    "MaxRooting",
    "Senescence",
    "Maturity",
    "HIstart",
    "Flowering",
    "YldForm",
)
REQUIRED_WEATHER_VALUES = (
    "T2M_MIN",
    "T2M_MAX",
    "PRECTOTCORR",
    "RH2M",
    "WS2M",
    "PS",
    "ALLSKY_SFC_SW_DWN",
)


class RequestValidationError(ValueError):
    """A request cannot be represented by the supported AquaCrop contract."""


def simulation_end_for_planting(planting_date: date) -> tuple[date, bool]:
    """Return the supported recurring-calendar end and adjustment flag."""

    anniversary = date(planting_date.year + 1, 4, 30)
    adjusted = anniversary.month == 2 and anniversary.day == 29
    if adjusted:
        anniversary -= timedelta(days=1)
    return anniversary, adjusted


def map_exception_status(error: BaseException) -> RunStatus:
    """Map known AquaCrop restrictions without collapsing unexpected failures."""

    message = str(error).lower()
    if "not enough growing degree days in simulation" in message:
        return RunStatus.INSUFFICIENT_THERMAL_TIME
    if "crop will take longer than 1 year to mature" in message:
        return RunStatus.MODEL_LIMIT
    return RunStatus.EXECUTION_FAILED


def map_crop_state(crop_mature: bool, crop_dead: bool, germinated: bool) -> RunStatus:
    """Map AquaCrop's final state flags to the stable domain status."""

    if crop_mature:
        return RunStatus.MATURED
    if crop_dead:
        return RunStatus.CROP_DIED
    if not germinated:
        return RunStatus.NOT_GERMINATED
    return RunStatus.NOT_MATURED


def _sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


@lru_cache(maxsize=1)
def adapter_source_fingerprint() -> str:
    return _sha256_tree(Path(__file__).parent)


@lru_cache(maxsize=1)
def aquacrop_source_fingerprint() -> str:
    import aquacrop

    return _sha256_tree(Path(aquacrop.__file__).parent)


def _plain_request(request: SimulationRequest) -> dict[str, Any]:
    content = request.to_json_dict()
    content.pop("request_id", None)
    content.pop("output_dir", None)
    parameters = dict(content["model_parameters"])
    parameters.pop("save_daily", None)
    content["model_parameters"] = parameters
    return content


def _as_date(value: object) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise RequestValidationError(f"invalid planting date: {value!r}") from exc


def _number(
    parameters: dict[str, Any],
    name: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
    minimum_inclusive: bool = True,
) -> float:
    try:
        value = float(parameters.get(name, default))
    except (TypeError, ValueError) as exc:
        raise RequestValidationError(f"{name} must be numeric") from exc
    lower_ok = value >= minimum if minimum_inclusive else value > minimum
    if not math.isfinite(value) or not lower_ok or value > maximum:
        bracket = "[" if minimum_inclusive else "("
        raise RequestValidationError(
            f"{name} must be in {bracket}{minimum}, {maximum}]"
        )
    return value


def _json_default(value: object) -> object:
    if isinstance(value, (date, pd.Timestamp, Path)):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(
                value,
                allow_nan=False,
                default=_json_default,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    try:
        frame.to_parquet(temporary, index=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _soil_type(request: SimulationRequest, parameters: dict[str, Any]) -> str:
    if "soil_type" in parameters:
        return str(parameters["soil_type"])
    if request.environment.soil:
        properties = request.environment.soil[0].properties
        for key in ("aquacrop_soil_type", "soil_type", "texture"):
            if key in properties:
                return str(properties[key])
    for key in ("aquacrop_soil_type", "soil_type", "default_soil_type"):
        if key in request.environment.metadata:
            return str(request.environment.metadata[key])
    return "Loam"


def _cache_paths(output_dir: Path, key: str) -> dict[str, Path]:
    root = output_dir / "aquacrop"
    return {
        "summary": root / f"{key}.json",
        "daily": root / f"{key}.daily.parquet",
        "crop": root / f"{key}.crop.json",
        "soil": root / f"{key}.soil.parquet",
    }


def _cached_result(path: Path) -> SimulationResult:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return SimulationResult(
        request_id=payload["request_id"],
        adapter_name=payload["adapter_name"],
        adapter_version=payload["adapter_version"],
        status=RunStatus(payload["status"]),
        summary=payload.get("summary", {}),
        artifacts={
            name: Path(artifact_path)
            for name, artifact_path in payload.get("artifacts", {}).items()
        },
        diagnostics=payload.get("diagnostics", {}),
        failure_reason=payload.get("failure_reason"),
    )


class AquaCropAdapter:
    """Translate model-independent requests to AquaCrop 3.1.0."""

    name = ADAPTER_NAME
    version = MODEL_VERSION
    capabilities = ModelCapabilities(
        display_name="AquaCrop",
        phenology_parameter=CalibrationParameter(
            "phenology_scale", 1.0, (0.8, 1.2, 0.02), 0.005
        ),
        yield_parameter=CalibrationParameter("HI0", 0.48, (0.35, 0.55, 0.01), 0.0025),
        site_calibration_supported=True,
        site_phenology_parameter="phenology_scale_site",
        site_yield_parameter="HI0_site",
        supported_folds=(FoldStrategy.HELD_YEAR, FoldStrategy.LEAVE_SITE),
        weather_strategy=WeatherStrategy.CACHED_POWER,
        scan_request_strategy=ScanRequestStrategy.PER_DATE,
        report_notes=(
            "- 开花日期采用 AquaCrop `HIstart` 首次跨越的日末代理，并非独立花粉事件。",
            "- 默认土壤仅用于探索；缺失灌溉信息按配置标记为假定雨养。",
            "- 全局校准仅拟合 `phenology_scale` 与 `HI0`；"
            "根深、灌溉和土壤水力参数固定。",
            "- `site_calibrated` 在全局参数基础上应用满足训练年数要求的站点偏移。",
        ),
    )

    @property
    def source_fingerprints(self) -> dict[str, str]:
        return {
            "adapter_source_sha256": adapter_source_fingerprint(),
            "model_source_sha256": aquacrop_source_fingerprint(),
        }

    def cache_key(self, request: SimulationRequest) -> str:
        identity = {
            "request": _plain_request(request),
            "adapter_source_sha256": self.source_fingerprints["adapter_source_sha256"],
            "model_version": self.version,
            "model_source_sha256": self.source_fingerprints["model_source_sha256"],
        }
        payload = json.dumps(
            identity,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def validate(self, request: SimulationRequest) -> None:
        self._validate_request(request)
        try:
            json.dumps(
                _plain_request(request),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError) as exc:
            raise RequestValidationError(str(exc)) from exc

    def _validate_request(self, request: SimulationRequest) -> None:
        parameters = dict(request.model_parameters)
        installed_version = importlib.metadata.version("aquacrop")
        requested_version = str(parameters.get("model_version", self.version))
        if installed_version != self.version or requested_version != self.version:
            raise RequestValidationError(
                "model version must be AquaCrop 3.1.0 "
                f"(installed={installed_version}, requested={requested_version})"
            )

        requested_planting = _as_date(
            parameters.get("planting_date", request.management.planting_date)
        )
        if requested_planting != request.management.planting_date:
            raise RequestValidationError(
                "requested planting date must equal management planting date"
            )
        if request.environment.environment_id != request.management.environment_id:
            raise RequestValidationError(
                "management environment does not match request environment"
            )
        if request.environment.year != request.management.planting_date.year:
            raise RequestValidationError("environment year must equal planting year")
        expected_start = date(request.environment.year, 1, 1)
        if request.start_date != expected_start:
            raise RequestValidationError(
                "simulation must start on January 1 of the planting year"
            )
        weather_end = max(record.date for record in request.environment.weather)
        if request.end_date > weather_end:
            raise RequestValidationError(
                "every calendar day in the inclusive simulation interval "
                "must have exactly one weather row"
            )
        expected_end, _ = simulation_end_for_planting(request.management.planting_date)
        if request.end_date > expected_end:
            raise RequestValidationError(
                "simulation end must be one day before the next sowing anniversary"
            )

        expected_dates = pd.date_range(request.start_date, request.end_date)
        weather_dates = [record.date for record in request.environment.weather]
        if (
            len(weather_dates) != len(expected_dates)
            or len(set(weather_dates)) != len(weather_dates)
            or set(weather_dates) != {timestamp.date() for timestamp in expected_dates}
        ):
            raise RequestValidationError(
                "every calendar day in the inclusive simulation interval "
                "must have exactly one weather row"
            )
        for record in request.environment.weather:
            if record.environment_id != request.environment.environment_id:
                raise RequestValidationError(
                    "weather environment does not match request environment"
                )
            values = record.values
            if any(name not in values for name in REQUIRED_WEATHER_VALUES):
                raise RequestValidationError("weather row is missing required values")
            try:
                numeric = {
                    name: float(values[name]) for name in REQUIRED_WEATHER_VALUES
                }
            except (TypeError, ValueError) as exc:
                raise RequestValidationError("weather values must be numeric") from exc
            if not all(math.isfinite(value) for value in numeric.values()):
                raise RequestValidationError("weather values must be finite")
            physical = (
                numeric["T2M_MIN"] <= numeric["T2M_MAX"]
                and numeric["PRECTOTCORR"] >= 0
                and 0 <= numeric["RH2M"] <= 100
                and numeric["WS2M"] >= 0
                and numeric["PS"] > 0
                and numeric["ALLSKY_SFC_SW_DWN"] >= 0
            )
            if not physical:
                raise RequestValidationError("weather values are physically invalid")

        irrigation = request.management.irrigation_assumption
        if irrigation not in {
            "rainfed_confirmed",
            "irrigated_confirmed",
            "unknown",
        }:
            raise RequestValidationError("unsupported irrigation assumption")
        irrigation_smt = parameters.get("irrigation_smt", [70, 75, 80, 70])
        if (
            not isinstance(irrigation_smt, (list, tuple))
            or len(irrigation_smt) != 4
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0 <= float(value) <= 100
                for value in irrigation_smt
            )
        ):
            raise RequestValidationError(
                "irrigation_smt must contain four percentages in [0, 100]"
            )

        soil_depth = _number(parameters, "soil_depth_m", 2.0, minimum=0.2, maximum=5.0)
        compartment = _number(
            parameters,
            "soil_compartment_m",
            0.1,
            minimum=0.05,
            maximum=0.5,
        )
        count = round(soil_depth / compartment)
        if not math.isclose(count * compartment, soil_depth, abs_tol=1e-9):
            raise RequestValidationError(
                "soil depth must be divisible by compartment thickness"
            )
        if len(request.environment.soil) > 1:
            raise RequestValidationError(
                "only one homogeneous AquaCrop soil layer is supported"
            )
        if request.environment.soil:
            layer = request.environment.soil[0]
            if not math.isclose(layer.top_depth_m, 0.0, abs_tol=1e-9) or not (
                math.isclose(layer.bottom_depth_m, soil_depth, abs_tol=1e-9)
            ):
                raise RequestValidationError(
                    "soil layer must span the configured profile depth"
                )

        crop = str(parameters.get("crop", DEFAULT_CROP))
        if crop not in crop_params:
            raise RequestValidationError(f"unsupported AquaCrop crop: {crop}")
        _number(
            parameters,
            "phenology_scale",
            1.0,
            minimum=0.1,
            maximum=3.0,
            minimum_inclusive=False,
        )
        _number(
            parameters,
            "phenology_scale_site",
            1.0,
            minimum=0.0,
            maximum=4.0,
            minimum_inclusive=False,
        )
        _number(
            parameters,
            "HI0",
            float(crop_params[crop]["HI0"]),
            minimum=0.0,
            maximum=1.0,
            minimum_inclusive=False,
        )
        _number(
            parameters,
            "HI0_site",
            1.0,
            minimum=0.0,
            maximum=4.0,
            minimum_inclusive=False,
        )
        _number(
            parameters,
            "initial_available_water_pct",
            50.0,
            minimum=0.0,
            maximum=100.0,
        )
        _number(
            parameters,
            "root_depth_scale",
            1.0,
            minimum=0.0,
            maximum=3.0,
            minimum_inclusive=False,
        )
        default_population = (
            request.management.population_plants_m2 * 10_000
            if request.management.population_plants_m2 is not None
            else 75_000.0
        )
        _number(
            parameters,
            "plant_population_ha",
            default_population,
            minimum=0.0,
            maximum=10_000_000.0,
            minimum_inclusive=False,
        )
        if not isinstance(parameters.get("save_daily", False), bool):
            raise RequestValidationError("save_daily must be boolean")
        moisture_fraction = _number(
            parameters,
            "grain_standard_moisture_fraction",
            0.155,
            minimum=0.0,
            maximum=1.0,
        )
        if not math.isclose(moisture_fraction, 0.155, abs_tol=1e-12):
            raise RequestValidationError(
                "grain_standard_moisture_fraction must equal 0.155"
            )
        try:
            soil = Soil(
                _soil_type(request, parameters),
                dz=[compartment] * count,
            )
        except Exception as exc:
            raise RequestValidationError(
                "unsupported AquaCrop soil/profile assumptions"
            ) from exc
        profile = soil.profile
        if not (
            (profile["th_wp"] < profile["th_fc"]) & (profile["th_fc"] < profile["th_s"])
        ).all():
            raise RequestValidationError("unsupported AquaCrop soil hydraulic ordering")

    def smoke(self) -> dict[str, Any]:
        """Run AquaCrop's bundled reference example through the pinned engine."""

        if importlib.metadata.version("aquacrop") != self.version:
            raise RuntimeError("AquaCrop version mismatch")
        model = AquaCropModel(
            "1979/10/01",
            "1980/05/30",
            prepare_weather(get_filepath("tunis_climate.txt")),
            Soil("SandyLoam"),
            Crop("Wheat", "10/01"),
            InitialWaterContent(value=["FC"]),
        )
        model.run_model(
            till_termination=True,
            initialize_model=True,
            process_outputs=False,
        )
        results = model.get_simulation_results()
        if len(results) != 1:
            raise RuntimeError("bundled AquaCrop smoke example returned no season")
        dry_yield = float(results["Dry yield (tonne/ha)"].iloc[0])
        if not math.isfinite(dry_yield):
            raise RuntimeError("bundled AquaCrop smoke example returned invalid yield")
        return {
            "model_version": self.version,
            "model_source_sha256": self.source_fingerprints["model_source_sha256"],
            "dry_yield_mg_ha": dry_yield,
        }

    def run(self, request: SimulationRequest) -> SimulationResult:
        started = time.perf_counter()
        try:
            self.validate(request)
        except RequestValidationError as exc:
            return SimulationResult(
                request_id=request.request_id,
                adapter_name=self.name,
                adapter_version=self.version,
                status=RunStatus.INVALID_INPUT,
                diagnostics={
                    "cache_hit": False,
                    "traceback": traceback.format_exc(),
                },
                failure_reason=str(exc),
            )
        except Exception as exc:
            return SimulationResult(
                request_id=request.request_id,
                adapter_name=self.name,
                adapter_version=self.version,
                status=RunStatus.EXECUTION_FAILED,
                diagnostics={
                    "cache_hit": False,
                    "traceback": traceback.format_exc(),
                },
                failure_reason=str(exc),
            )

        try:
            key = self.cache_key(request)
        except (TypeError, ValueError) as exc:
            return SimulationResult(
                request_id=request.request_id,
                adapter_name=self.name,
                adapter_version=self.version,
                status=RunStatus.INVALID_INPUT,
                diagnostics={
                    "cache_hit": False,
                    "traceback": traceback.format_exc(),
                },
                failure_reason=str(exc),
            )
        except Exception as exc:
            return SimulationResult(
                request_id=request.request_id,
                adapter_name=self.name,
                adapter_version=self.version,
                status=RunStatus.EXECUTION_FAILED,
                diagnostics={
                    "cache_hit": False,
                    "traceback": traceback.format_exc(),
                },
                failure_reason=str(exc),
            )
        save_daily = bool(request.model_parameters.get("save_daily", False))
        paths = (
            _cache_paths(request.output_dir, key)
            if request.output_dir is not None
            else None
        )
        if paths is not None and paths["summary"].is_file():
            try:
                cached = _cached_result(paths["summary"])
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                cached = None
            if cached is not None:
                requested_artifacts_exist = not save_daily or all(
                    paths[name].is_file() for name in ("daily", "crop", "soil")
                )
                if (
                    cached.status
                    not in {
                        RunStatus.EXECUTION_FAILED,
                        RunStatus.INVALID_INPUT,
                        RunStatus.MODEL_LIMIT,
                        RunStatus.INSUFFICIENT_THERMAL_TIME,
                    }
                    and requested_artifacts_exist
                ):
                    diagnostics = dict(cached.diagnostics)
                    diagnostics["cache_hit"] = True
                    result = SimulationResult(
                        request_id=request.request_id,
                        adapter_name=cached.adapter_name,
                        adapter_version=cached.adapter_version,
                        status=cached.status,
                        summary=cached.summary,
                        artifacts=cached.artifacts,
                        diagnostics=diagnostics,
                        failure_reason=cached.failure_reason,
                    )
                    try:
                        _atomic_json(paths["summary"], result.to_json_dict())
                        return result
                    except Exception as exc:
                        return SimulationResult(
                            request_id=request.request_id,
                            adapter_name=self.name,
                            adapter_version=self.version,
                            status=RunStatus.EXECUTION_FAILED,
                            diagnostics={
                                "cache_hit": False,
                                "cache_key": key,
                                **self.source_fingerprints,
                                "traceback": traceback.format_exc(),
                            },
                            failure_reason=str(exc),
                        )

        try:
            status, summary, daily, crop_values, soil_profile = self._run_model(request)
            failure_reason = None
            diagnostics = {
                "cache_hit": False,
                "cache_key": key,
                **self.source_fingerprints,
            }
        except Exception as exc:
            status = map_exception_status(exc)
            summary = {
                "dry_yield_mg_ha": None,
                "yield_at_15p5_mg_ha": None,
            }
            daily = None
            crop_values = None
            soil_profile = None
            failure_reason = str(exc)
            diagnostics = {
                "cache_hit": False,
                "cache_key": key,
                **self.source_fingerprints,
                "traceback": traceback.format_exc(),
            }

        summary["elapsed_seconds"] = time.perf_counter() - started
        artifacts: dict[str, Path] = {}
        if paths is not None:
            try:
                artifacts["summary"] = paths["summary"]
                if save_daily and daily is not None:
                    _atomic_parquet(paths["daily"], daily)
                    _atomic_json(paths["crop"], crop_values)
                    _atomic_parquet(paths["soil"], soil_profile)
                    artifacts.update(
                        daily=paths["daily"],
                        crop=paths["crop"],
                        soil=paths["soil"],
                    )
                result = SimulationResult(
                    request_id=request.request_id,
                    adapter_name=self.name,
                    adapter_version=self.version,
                    status=status,
                    summary=summary,
                    artifacts=artifacts,
                    diagnostics=diagnostics,
                    failure_reason=failure_reason,
                )
                _atomic_json(paths["summary"], result.to_json_dict())
                return result
            except Exception as exc:
                return SimulationResult(
                    request_id=request.request_id,
                    adapter_name=self.name,
                    adapter_version=self.version,
                    status=RunStatus.EXECUTION_FAILED,
                    summary={
                        "dry_yield_mg_ha": None,
                        "yield_at_15p5_mg_ha": None,
                        "elapsed_seconds": time.perf_counter() - started,
                    },
                    diagnostics={
                        "cache_hit": False,
                        "cache_key": key,
                        **self.source_fingerprints,
                        "traceback": traceback.format_exc(),
                    },
                    failure_reason=str(exc),
                )
        return SimulationResult(
            request_id=request.request_id,
            adapter_name=self.name,
            adapter_version=self.version,
            status=status,
            summary=summary,
            artifacts=artifacts,
            diagnostics=diagnostics,
            failure_reason=failure_reason,
        )

    def _run_model(
        self, request: SimulationRequest
    ) -> tuple[
        RunStatus,
        dict[str, Any],
        pd.DataFrame,
        dict[str, Any],
        pd.DataFrame,
    ]:
        parameters = dict(request.model_parameters)
        crop_name = str(parameters.get("crop", DEFAULT_CROP))
        base = dict(crop_params[crop_name])
        phenology_scale = float(parameters.get("phenology_scale", 1.0))
        hi0 = float(parameters.get("HI0", base["HI0"]))
        phenology_site_scale = float(parameters.get("phenology_scale_site", 1.0))
        hi0_site = float(parameters.get("HI0_site", 1.0))
        if not 0 < phenology_site_scale <= 4:
            raise ValueError("phenology_scale_site must be in (0, 4]")
        if not 0 < hi0_site <= 4:
            raise ValueError("HI0_site must be in (0, 4]")
        effective_phenology_scale = phenology_scale * phenology_site_scale
        effective_hi0 = hi0 * hi0_site
        water_pct = float(parameters.get("initial_available_water_pct", 50.0))
        root_scale = float(parameters.get("root_depth_scale", 1.0))
        population = float(
            parameters.get(
                "plant_population_ha",
                (
                    request.management.population_plants_m2 * 10_000
                    if request.management.population_plants_m2 is not None
                    else base["PlantPop"]
                ),
            )
        )
        soil_depth = float(parameters.get("soil_depth_m", 2.0))
        compartment = float(parameters.get("soil_compartment_m", 0.1))
        irrigation_smt = [
            float(value) for value in parameters.get("irrigation_smt", (70, 75, 80, 70))
        ]
        irrigation_management = (
            IrrigationManagement(
                irrigation_method=1,
                SMT=irrigation_smt,
                MaxIrr=50.0,
            )
            if request.management.irrigation_assumption == "irrigated_confirmed"
            else IrrigationManagement(irrigation_method=0)
        )
        moisture_fraction = float(
            parameters.get("grain_standard_moisture_fraction", 0.155)
        )
        dz = [compartment] * round(soil_depth / compartment)
        soil = Soil(_soil_type(request, parameters), dz=dz)
        profile = soil.profile.copy()
        theta_initial = (
            profile["th_wp"].to_numpy()
            + water_pct / 100 * (profile["th_fc"] - profile["th_wp"]).to_numpy()
        )

        crop_kwargs = {
            key: float(base[key]) * effective_phenology_scale for key in THERMAL_KEYS
        }
        root_cap = soil_depth - 0.1
        effective_root_depth = min(float(base["Zmax"]) * root_scale, root_cap)
        crop_kwargs.update(
            HI0=effective_hi0,
            PlantPop=population,
            Zmax=effective_root_depth,
        )
        simulation_end, leap_adjusted = simulation_end_for_planting(
            request.management.planting_date
        )
        harvest_rule = None
        crop = Crop(
            crop_name,
            request.management.planting_date.strftime("%m/%d"),
            harvest_date=request.end_date.strftime("%m/%d"),
            **crop_kwargs,
        )
        harvest_rule = request.end_date.strftime("%m/%d")
        crop.harvest_date = harvest_rule
        crop.PlantTrigger = None
        effective_crop = dict(crop.__dict__)

        rows = []
        for record in sorted(request.environment.weather, key=lambda item: item.date):
            rows.append({"date": record.date, **dict(record.values)})
        weather = reference_et(
            pd.DataFrame(rows),
            latitude_deg=request.environment.latitude,
            elevation_m=float(request.environment.metadata.get("elevation_m", 0.0)),
        )
        model_weather = pd.DataFrame(
            {
                "MinTemp": weather["T2M_MIN"].to_numpy(),
                "MaxTemp": weather["T2M_MAX"].to_numpy(),
                "Precipitation": weather["PRECTOTCORR"].to_numpy(),
                "ReferenceET": weather["ReferenceET"].to_numpy(),
                "Date": pd.to_datetime(weather["date"]),
            }
        )
        model = AquaCropModel(
            request.start_date.strftime("%Y/%m/%d"),
            request.end_date.strftime("%Y/%m/%d"),
            model_weather,
            soil,
            crop,
            InitialWaterContent(
                wc_type="Pct",
                method="Layer",
                depth_layer=[1],
                value=[water_pct],
            ),
            irrigation_management=irrigation_management,
            off_season=True,
        )
        model.run_model(till_termination=True)
        if not np.allclose(soil.profile["dz"].to_numpy(), dz, rtol=0, atol=1e-12):
            raise ValueError(
                "engine changed soil geometry; lower root buffer was insufficient"
            )

        statistics = model.get_simulation_results()
        growth = model.get_crop_growth().copy()
        flux = model.get_water_flux().copy()
        storage = model.get_water_storage().copy()
        simulated_indices = np.flatnonzero(growth["time_step_counter"].to_numpy() > 0)
        count = int(simulated_indices[-1] + 1) if len(simulated_indices) else 1
        growth = growth.iloc[:count].copy()
        flux = flux.iloc[:count].copy()
        storage = storage.iloc[:count].copy()
        expected_steps = np.arange(count)
        for frame in (growth, flux, storage):
            if not np.array_equal(
                frame["time_step_counter"].to_numpy(), expected_steps
            ):
                raise ValueError("AquaCrop output time-step alignment failed")

        daily = growth.copy()
        for column in flux:
            if column not in daily:
                daily[column] = flux[column].to_numpy()
        daily["growing_season"] = storage["growing_season"].to_numpy().astype(bool)
        for column in storage:
            if column.startswith("th"):
                daily[column] = storage[column].to_numpy()
        daily["Date"] = pd.date_range(request.start_date, periods=count)
        daily["Precipitation_mm_day"] = weather["PRECTOTCORR"].iloc[:count].to_numpy()
        daily["ET0_unclipped_mm_day"] = (
            weather["ET0_unclipped_mm_day"].iloc[:count].to_numpy()
        )
        daily["ReferenceET_mm_day"] = weather["ReferenceET"].iloc[:count].to_numpy()

        theta_columns = [f"th{number + 1}" for number in range(len(dz))]
        theta = daily[theta_columns].to_numpy()
        daily["soil_water_mm"] = (theta * np.asarray(dz) * 1000).sum(axis=1)
        initial_storage = float((theta_initial * np.asarray(dz) * 1000).sum())
        total_storage = (
            daily["soil_water_mm"].to_numpy() + daily["surface_storage"].to_numpy()
        )
        storage_change = total_storage - np.r_[initial_storage, total_storage[:-1]]
        net_flux = (
            daily["Precipitation_mm_day"]
            + daily["IrrDay"]
            + daily["CR"]
            + daily["GwIn"]
            - daily["Runoff"]
            - daily["DeepPerc"]
            - daily["TileDrain"]
            - daily["Es"]
            - daily["Tr"]
        )
        daily["water_balance_residual_mm"] = storage_change - net_flux.to_numpy()

        active = daily.loc[daily["growing_season"]]
        actual_sowing = active["Date"].iloc[0].date() if not active.empty else None
        if actual_sowing != request.management.planting_date:
            raise ValueError("actual sowing date differs from requested intervention")
        preplant = daily.loc[
            daily["Date"] < pd.Timestamp(request.management.planting_date)
        ]
        condition = model._init_cond
        status = map_crop_state(
            condition.crop_mature,
            condition.crop_dead,
            condition.germination,
        )

        if len(statistics) and pd.notna(
            statistics["Harvest Date (YYYY/MM/DD)"].iloc[0]
        ):
            termination_date = pd.Timestamp(
                statistics["Harvest Date (YYYY/MM/DD)"].iloc[0]
            )
        else:
            termination_date = daily["Date"].iloc[-1] + pd.Timedelta(days=1)
        if len(statistics):
            dry_yield = float(statistics["Dry yield (tonne/ha)"].iloc[0])
        elif not active.empty:
            dry_yield = float(active["DryYield"].iloc[-1])
        else:
            dry_yield = 0.0
        flowering = active.loc[active["gdd_cum"] >= float(crop_kwargs["HIstart"])]
        flowering_date = (
            flowering["Date"].iloc[0] + pd.Timedelta(days=1)
            if not flowering.empty
            else None
        )
        summary = {
            "cache_key": self.cache_key(request),
            "model_version": self.version,
            "crop": crop_name,
            "parameter_set_id": request.parameter_set_id,
            "phenology_scale": phenology_scale,
            "HI0": hi0,
            "phenology_scale_site": phenology_site_scale,
            "HI0_site": hi0_site,
            "effective_phenology_scale": effective_phenology_scale,
            "effective_HI0": effective_hi0,
            "initial_available_water_pct": water_pct,
            "root_depth_scale": root_scale,
            "plant_population_ha": population,
            "irrigation_method": (
                "soil_moisture_target"
                if request.management.irrigation_assumption == "irrigated_confirmed"
                else "rainfed"
            ),
            "irrigation_smt": irrigation_smt,
            "simulation_start_date": request.start_date.isoformat(),
            "simulation_end_date": simulation_end.isoformat(),
            "configured_harvest_rule": harvest_rule,
            "leap_day_harvest_rule_adjusted": leap_adjusted,
            "requested_sowing_date": request.management.planting_date.isoformat(),
            "actual_sowing_date": actual_sowing.isoformat(),
            "last_simulated_date": daily["Date"].iloc[-1].date().isoformat(),
            "termination_date": termination_date.date().isoformat(),
            "maturity_date": (
                termination_date.date().isoformat()
                if status is RunStatus.MATURED
                else None
            ),
            "termination_reason": (
                status.value
                if status is not RunStatus.NOT_MATURED
                else "anniversary cutoff before maturity"
            ),
            "dry_yield_mg_ha": dry_yield,
            "yield_at_15p5_mg_ha": dry_yield / (1 - moisture_fraction),
            "biomass_mg_ha": float(daily["biomass"].max() / 100),
            "flowering_proxy_date": (
                flowering_date.date().isoformat()
                if flowering_date is not None
                else None
            ),
            "flowering_proxy_dap": (
                (flowering_date.date() - request.management.planting_date).days
                if flowering_date is not None
                else None
            ),
            "flowering_proxy_note": (
                "first end-of-day crossing of HIstart; not an independent pollen event"
            ),
            "seasonal_precipitation_mm": float(active["Precipitation_mm_day"].sum()),
            "seasonal_irrigation_mm": float(active["IrrDay"].sum()),
            "seasonal_evaporation_mm": float(active["Es"].sum()),
            "seasonal_transpiration_mm": float(active["Tr"].sum()),
            "seasonal_et_mm": float((active["Es"] + active["Tr"]).sum()),
            "initial_soil_water_mm": initial_storage,
            "preplant_days_simulated": len(preplant),
            "day_before_planting_soil_water_mm": (
                float(preplant["soil_water_mm"].iloc[-1]) if len(preplant) else None
            ),
            "preplant_soil_water_range_mm": (
                float(preplant["soil_water_mm"].max() - preplant["soil_water_mm"].min())
                if len(preplant)
                else 0.0
            ),
            "soil_water_bounds_ok": bool(
                (theta >= profile["th_dry"].to_numpy() - 1e-6).all()
                and (theta <= profile["th_s"].to_numpy() + 1e-6).all()
            ),
            "soil_profile_depth_m": soil_depth,
            "soil_compartment_m": compartment,
            "soil_type": _soil_type(request, parameters),
            "effective_max_root_depth_m": effective_root_depth,
            "root_depth_clipped_by_profile": (
                float(base["Zmax"]) * root_scale > root_cap
            ),
            "max_simulated_root_depth_m": (
                float(active["z_root"].max()) if len(active) else 0.0
            ),
            "water_balance_max_abs_mm_day": float(
                daily["water_balance_residual_mm"].abs().max()
            ),
            "water_balance_total_residual_mm": float(
                daily["water_balance_residual_mm"].sum()
            ),
            "et0_unclipped_min_mm_day": float(daily["ET0_unclipped_mm_day"].min()),
            "et0_model_input_min_mm_day": float(daily["ReferenceET_mm_day"].min()),
        }
        if not math.isfinite(dry_yield) or not summary["soil_water_bounds_ok"]:
            raise ValueError("AquaCrop returned invalid yield or soil-water bounds")
        if summary["water_balance_max_abs_mm_day"] > 1:
            raise ValueError("water-balance residual exceeds 1 mm/day")
        return status, summary, daily, effective_crop, profile
