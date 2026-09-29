"""Full-year planting-date scans and planting-window summaries."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from calendar import isleap
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from snowwindow.adapters import ModelAdapter, resolve_model_adapter
from snowwindow.config import ExperimentConfig
from snowwindow.domain import ScanRequestStrategy, SimulationRequest, WeatherStrategy
from snowwindow.experiment import (
    build_simulation_request,
    load_cached_power_weather,
    load_legacy_crossyear_weather,
    load_prepared_tables,
    select_representative_units,
)


def calendar_dates(year: int) -> tuple[date, ...]:
    return tuple(
        timestamp.date()
        for timestamp in pd.date_range(
            date(year, 1, 1), periods=366 if isleap(year) else 365
        )
    )


def _segments(dates: list[date]) -> list[list[str]]:
    if not dates:
        return []
    groups: list[list[date]] = [[dates[0]]]
    for current in dates[1:]:
        if (current - groups[-1][-1]).days == 1:
            groups[-1].append(current)
        else:
            groups.append([current])
    return [[value.isoformat() for value in group] for group in groups]


def derive_planting_windows(
    frame: pd.DataFrame, fractions: tuple[float, ...]
) -> list[dict[str, Any]]:
    usable = frame.loc[
        frame["status"].eq("matured")
        & pd.to_numeric(frame["dry_yield_mg_ha"], errors="coerce").gt(0)
    ].copy()
    if usable.empty:
        return [
            {
                "fraction": float(fraction),
                "status": "no_positive_mature_yield",
                "maximum_yield_mg_ha": None,
                "dates": [],
                "segments": [],
                "best_dates": [],
            }
            for fraction in fractions
        ]
    usable["planting_date"] = pd.to_datetime(usable["planting_date"]).dt.date
    maximum = float(usable["dry_yield_mg_ha"].max())
    best = sorted(
        usable.loc[usable["dry_yield_mg_ha"].eq(maximum), "planting_date"].unique()
    )
    rows = []
    for fraction in fractions:
        dates = sorted(
            usable.loc[
                usable["dry_yield_mg_ha"].ge(maximum * fraction), "planting_date"
            ].unique()
        )
        rows.append(
            {
                "fraction": float(fraction),
                "status": "ok",
                "maximum_yield_mg_ha": maximum,
                "dates": [value.isoformat() for value in dates],
                "segments": _segments(dates),
                "best_dates": [value.isoformat() for value in best],
            }
        )
    return rows


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    temporary.write_text(
        json.dumps(value, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _atomic_table(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    if path.suffix == ".parquet":
        frame.to_parquet(temporary, index=False)
    else:
        frame.to_csv(temporary, index=False)
    os.replace(temporary, path)


def native_scan_requests(
    config: ExperimentConfig, adapter: ModelAdapter | None = None
) -> tuple[SimulationRequest, ...]:
    """Build deterministic requests for every environment/parameter/date."""

    model = adapter if adapter is not None else resolve_model_adapter(config)
    capabilities = model.capabilities
    tables = load_prepared_tables(config)
    units = select_representative_units(
        tables["management_units"], config.selection.environments
    )
    environments = tables["environments"].set_index("environment_id")
    soils = tables["soil_profiles"].set_index("environment_id")

    parameter_path = config.experiment_dir / "calibration/parameters.parquet"
    parameters = pd.read_parquet(parameter_path) if parameter_path.is_file() else None
    if parameters is None or parameters.empty:
        raise FileNotFoundError("calibration parameters are missing")
    held_year = parameters.loc[parameters["fold"].eq("held_year")]
    if held_year.empty:
        raise ValueError("held_year calibration parameters are missing")
    calibrated_parameters = {
        capabilities.phenology_parameter.name: float(
            held_year.iloc[0][capabilities.phenology_parameter.name]
        ),
        capabilities.yield_parameter.name: float(
            held_year.iloc[0][capabilities.yield_parameter.name]
        ),
    }
    site_offsets = pd.DataFrame()
    site_offset_path = config.experiment_dir / "calibration/site_offsets.parquet"
    if site_offset_path.is_file():
        site_offsets = pd.read_parquet(site_offset_path)
    site_offset_map: dict[str, dict[str, float]] = {}
    if not site_offsets.empty:
        site_offset_map = {
            str(offset["site"]): {
                capabilities.site_yield_parameter: float(offset["HI0_site"]),
                capabilities.site_phenology_parameter: float(
                    offset["phenology_scale_site"]
                ),
            }
            for offset in site_offsets.to_dict("records")
        }

    requests: list[SimulationRequest] = []
    for unit in units.sort_values("management_unit_id").to_dict("records"):
        environment_id = str(unit["environment_id"])
        loader = (
            load_legacy_crossyear_weather
            if capabilities.weather_strategy is WeatherStrategy.LEGACY_CROSSYEAR
            else load_cached_power_weather
        )
        weather, _ = loader(config, environment_id)
        environment = environments.loc[environment_id].to_dict()
        environment["environment_id"] = environment_id
        soil = soils.loc[environment_id].to_dict()
        for parameter_set_id, parameter_values in sorted(
            config.simulation.parameter_sets.items()
        ):
            if (
                parameter_set_id == "calibrated"
                and isinstance(parameter_values, Mapping)
                and parameter_values.get("source") == "calibration"
            ):
                model_parameters = {
                    **dict(config.model.parameters),
                    **calibrated_parameters,
                }
            elif (
                parameter_set_id == "site_calibrated"
                and isinstance(parameter_values, Mapping)
                and parameter_values.get("source") == "site_calibration"
            ):
                site = environment_id.rsplit("_", 1)[0]
                model_parameters = {
                    **dict(config.model.parameters),
                    **calibrated_parameters,
                    **site_offset_map.get(site, {}),
                }
            else:
                model_parameters = {
                    **dict(config.model.parameters),
                    **dict(parameter_values),
                }
            year = int(environment["year"])
            planting_dates = calendar_dates(year)
            if capabilities.scan_request_strategy is (
                ScanRequestStrategy.SLICE_WEATHER_HORIZON
            ):
                # All dates share the same normalized weather records. Construct
                # them once, then slice the immutable tuple for each horizon.
                base = build_simulation_request(
                    unit,
                    environment,
                    soil,
                    weather,
                    parameter_set_id=parameter_set_id,
                    model_parameters=model_parameters,
                    planting_date=planting_dates[-1],
                    output_dir=config.experiment_dir / "model_cache",
                )
                for planting_date in planting_dates:
                    horizon = int(model_parameters["simulation_horizon_days"])
                    end_date = min(
                        base.end_date, planting_date + timedelta(days=horizon)
                    )
                    count = (end_date - base.start_date).days + 1
                    requests.append(
                        replace(
                            base,
                            request_id=(
                                f"{unit['management_unit_id']}::"
                                f"{parameter_set_id}::{planting_date.isoformat()}"
                            ),
                            management=replace(
                                base.management, planting_date=planting_date
                            ),
                            environment=replace(
                                base.environment,
                                weather=base.environment.weather[:count],
                            ),
                            end_date=end_date,
                        )
                    )
                continue
            for planting_date in planting_dates:
                requests.append(
                    build_simulation_request(
                        unit,
                        environment,
                        soil,
                        weather,
                        parameter_set_id=parameter_set_id,
                        model_parameters=model_parameters,
                        planting_date=planting_date,
                        output_dir=config.experiment_dir / "model_cache",
                    )
                )
    expected = sum(
        len(units.loc[units["environment_id"].eq(environment_id)])
        * len(config.simulation.parameter_sets)
        * len(calendar_dates(int(environment["year"])))
        for environment_id, environment in environments.iterrows()
        if environment_id in set(units["environment_id"])
    )
    if len(requests) != expected:
        raise ValueError(
            "native scan request count mismatch: "
            f"expected {expected}, got {len(requests)}"
        )
    return tuple(requests)


def run_simulation_requests(
    requests: tuple[SimulationRequest, ...],
    model: ModelAdapter,
    *,
    workers: int,
) -> dict[str, Any]:
    """Run scan requests, grouping adapters which support batch execution."""

    run_many = getattr(model, "run_many", None)
    if not callable(run_many):
        return {request.request_id: model.run(request) for request in requests}
    grouped: dict[tuple[str, str], list[SimulationRequest]] = {}
    for request in requests:
        key = (request.environment.environment_id, request.parameter_set_id)
        grouped.setdefault(key, []).append(request)
    results: dict[str, Any] = {}
    ordered_groups = [grouped[key] for key in sorted(grouped)]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for batch_results in executor.map(run_many, ordered_groups):
            results.update(batch_results)
    return results


def _scan_progress_path(config: ExperimentConfig, model: ModelAdapter) -> Path:
    return config.experiment_dir / "model_cache" / model.name / "scan_progress.jsonl"


def _write_progress(path: Path, key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"cache_key": key}) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def scan_stage(
    config: ExperimentConfig, adapter: ModelAdapter | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run native full-year simulations and derive planting windows."""

    model = adapter if adapter is not None else resolve_model_adapter(config)
    requests = native_scan_requests(config, model)
    progress_path = _scan_progress_path(config, model)
    completed: set[str] = set()
    if progress_path.is_file():
        completed = {
            json.loads(line)["cache_key"]
            for line in progress_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    adapter_cache = getattr(model, "cache_key", None)
    keys = (
        {request.request_id: adapter_cache(request) for request in requests}
        if callable(adapter_cache)
        else {}
    )
    if keys:
        outstanding = [
            request
            for request in requests
            if keys.get(request.request_id) not in completed
        ]
        start = time.perf_counter()
        for index, request in enumerate(outstanding, start=1):
            model.run(request)
            _write_progress(progress_path, keys[request.request_id])
            if index == 1 or index % 100 == 0 or index == len(outstanding):
                elapsed = index / max(time.perf_counter() - start, 1e-9)
                remaining = (len(outstanding) - index) / elapsed
                print(
                    f"scan progress: {index}/{len(outstanding)} "
                    f"({index / len(outstanding):.1%}), remaining≈{remaining:.0f}s",
                    flush=True,
                )
    results = run_simulation_requests(
        tuple(requests),
        model,
        workers=config.simulation.workers,
    )

    rows: list[dict[str, Any]] = []
    for request in requests:
        result = results[request.request_id]
        row = {
            "environment_id": request.environment.environment_id,
            "year": request.environment.year,
            "management_unit_id": request.management.management_unit_id,
            "parameter_set": request.parameter_set_id,
            "request_id": result.request_id,
            "status": result.status.value,
            "failure_reason": result.failure_reason,
            "cache_key": result.diagnostics.get("cache_key"),
            **dict(result.summary),
        }
        row["planting_date"] = request.management.planting_date
        rows.append(row)
    selected = (
        pd.DataFrame(rows)
        .sort_values(["environment_id", "parameter_set", "planting_date"])
        .reset_index(drop=True)
    )
    if len(selected) != len(requests):
        raise ValueError(
            "native scan row count mismatch: "
            f"expected {len(requests)}, got {len(selected)}"
        )
    if selected.duplicated(["environment_id", "parameter_set", "planting_date"]).any():
        raise ValueError(
            "native scan requests contain duplicate environment/parameter/date keys"
        )

    window_rows = []
    for (environment_id, parameter_set), group in selected.groupby(
        ["environment_id", "parameter_set"], sort=True
    ):
        for window in derive_planting_windows(group, config.simulation.scan_fractions):
            window_rows.append(
                {
                    "environment_id": environment_id,
                    "parameter_set": parameter_set,
                    **window,
                }
            )
    windows = pd.DataFrame(window_rows)
    root = config.experiment_dir / "scan"
    _atomic_table(root / "summary.parquet", selected)
    csv_frame = selected.copy()
    csv_frame["planting_date"] = csv_frame["planting_date"].astype(str)
    _atomic_table(root / "summary.csv", csv_frame)
    _atomic_json(root / "windows.json", window_rows)
    _atomic_table(root / "windows.csv", windows)
    _atomic_json(
        root / "manifest.json",
        {
            "row_count": len(selected),
            "unique_key_count": int(
                selected[["environment_id", "parameter_set", "planting_date"]]
                .drop_duplicates()
                .shape[0]
            ),
            "parameter_sets": sorted(config.simulation.parameter_sets),
            "weather_source": "NASA POWER AG cached full-year and continuation forcing",
            "execution_mode": f"native {model.name} adapter",
            "adapter_name": model.name,
            "adapter_version": model.version,
        },
    )
    return selected, windows
