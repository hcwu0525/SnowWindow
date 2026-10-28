"""Experiment input assembly shared by calibration and planting-date scans."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from snowwindow.adapters import ModelAdapter
from snowwindow.config import ExperimentConfig
from snowwindow.domain import (
    Environment,
    ManagementUnit,
    RunStatus,
    SimulationRequest,
    SimulationResult,
    SoilLayer,
    WeatherRecord,
)
from snowwindow.models.aquacrop import simulation_end_for_planting
from snowwindow.weather import G2F_END_DATE, WEATHER_POLICY

WEATHER_COLUMNS = (
    "T2M_MIN",
    "T2M_MAX",
    "PRECTOTCORR",
    "RH2M",
    "WS2M",
    "PS",
    "ALLSKY_SFC_SW_DWN",
)


def select_representative_units(
    management_units: pd.DataFrame, environment_ids: tuple[str, ...]
) -> pd.DataFrame:
    """Choose the largest management experiment in each configured environment."""

    selected = management_units.copy()
    if environment_ids:
        selected = selected.loc[selected["environment_id"].isin(environment_ids)]
    if "plot_count" not in selected:
        selected["plot_count"] = 0
    if "experiment" not in selected:
        selected["experiment"] = ""
    selected["plot_count"] = pd.to_numeric(
        selected["plot_count"], errors="coerce"
    ).fillna(0)
    selected = selected.sort_values(
        ["environment_id", "plot_count", "experiment", "management_unit_id"],
        ascending=[True, False, True, True],
    )
    return (
        selected.groupby("environment_id", sort=True, as_index=False)
        .head(1)
        .reset_index(drop=True)
    )


def build_simulation_request(
    unit: dict[str, Any],
    environment: dict[str, Any],
    soil_profile: dict[str, Any],
    weather: pd.DataFrame,
    *,
    parameter_set_id: str,
    model_parameters: dict[str, Any],
    planting_date: date | None = None,
    output_dir: Path | None = None,
) -> SimulationRequest:
    """Build a validated model-independent request from normalized rows."""

    sowing = planting_date or unit["planting_date"]
    if not isinstance(sowing, date):
        timestamp = pd.Timestamp(sowing)
        if pd.isna(timestamp):
            raise ValueError("planting date is missing")
        sowing = timestamp.date()
    if sowing > G2F_END_DATE:
        raise ValueError(f"planting date exceeds G2F weather end {G2F_END_DATE}")
    dates = pd.to_datetime(weather["date"], errors="raise")
    horizon_days = model_parameters.get("simulation_horizon_days")
    planned_end = (
        sowing + timedelta(days=int(horizon_days))
        if horizon_days is not None
        else simulation_end_for_planting(sowing)[0]
    )
    valid_dates = dates.dropna()
    if valid_dates.empty:
        raise ValueError(f"weather is empty for {environment['environment_id']}")
    weather_end = valid_dates.max().date()
    end_date = min(planned_end, weather_end, G2F_END_DATE)
    if end_date < sowing:
        raise ValueError(f"G2F weather ends before planting date {sowing}")
    subset = weather.loc[
        dates.between(pd.Timestamp(sowing.year, 1, 1), pd.Timestamp(end_date))
    ].copy()
    subset["date"] = pd.to_datetime(subset["date"]).dt.date
    records = tuple(
        WeatherRecord(
            environment_id=str(environment["environment_id"]),
            date=row["date"],
            values={column: row[column] for column in WEATHER_COLUMNS},
            source=str(row.get("source", "normalized")),
        )
        for row in subset.sort_values("date").to_dict("records")
    )
    management = ManagementUnit(
        management_unit_id=str(unit["management_unit_id"]),
        environment_id=str(environment["environment_id"]),
        planting_date=sowing,
        population_plants_m2=(
            float(unit["population_plants_ha"]) / 10_000
            if unit.get("population_plants_ha") is not None
            and pd.notna(unit.get("population_plants_ha"))
            else None
        ),
        irrigation_assumption=str(
            unit.get("irrigation_assumption")
            or unit.get("irrigation_status")
            or "unknown"
        ),
        metadata={
            "experiment": unit.get("experiment"),
            "plot_count": unit.get("plot_count"),
        },
    )
    model_environment = Environment(
        environment_id=str(environment["environment_id"]),
        year=sowing.year,
        location=str(
            environment.get("field_location")
            or environment.get("city")
            or environment["environment_id"]
        ),
        latitude=float(environment["latitude"]),
        longitude=float(environment["longitude"]),
        weather=records,
        soil=(
            SoilLayer(
                top_depth_m=0.0,
                bottom_depth_m=float(model_parameters.get("soil_depth_m", 2.0)),
                properties={
                    "aquacrop_soil_type": soil_profile["aquacrop_soil_type"],
                    "profile_source": soil_profile.get("profile_source"),
                },
                source=str(soil_profile.get("profile_source", "normalized")),
            ),
        ),
        metadata={
            "elevation_m": float(environment.get("elevation_m", 0.0) or 0.0),
            "coordinate_source": environment.get("coordinate_source"),
            "weather_source": "g2f_full_year",
            "planned_end_date": planned_end.isoformat(),
            "weather_end_date": weather_end.isoformat(),
            "simulation_end_date": end_date.isoformat(),
            "weather_horizon_truncated": end_date < planned_end,
        },
    )
    return SimulationRequest(
        request_id=(
            f"{unit['management_unit_id']}::{parameter_set_id}::{sowing.isoformat()}"
        ),
        environment=model_environment,
        management=management,
        start_date=date(sowing.year, 1, 1),
        end_date=end_date,
        model_parameters=model_parameters,
        parameter_set_id=parameter_set_id,
        output_dir=output_dir,
    )


def weather_failure_result(
    request: SimulationRequest, model: ModelAdapter
) -> SimulationResult | None:
    """Keep G2F gaps as invalid inputs before native dispatch or cache hashing."""

    if request.environment.metadata.get("weather_source") != "g2f_full_year":
        return None
    records = request.environment.weather
    dates = [record.date for record in records]
    expected = {
        request.start_date + timedelta(days=index)
        for index in range((request.end_date - request.start_date).days + 1)
    }
    reason = None
    if len(dates) != len(expected) or set(dates) != expected:
        missing = sorted(expected - set(dates))[:5]
        reason = "G2F weather calendar gaps/duplicates: " + ", ".join(map(str, missing))
    else:
        for record in records:
            try:
                complete = all(
                    math.isfinite(float(record.values[column]))
                    for column in WEATHER_COLUMNS
                )
            except (KeyError, TypeError, ValueError):
                complete = False
            if not complete:
                reason = f"G2F weather core values missing on {record.date}"
                break
    if reason is None:
        return None
    return SimulationResult(
        request_id=request.request_id,
        adapter_name=model.name,
        adapter_version=model.version,
        status=RunStatus.INVALID_INPUT,
        summary={"dry_yield_mg_ha": None, "flowering_proxy_dap": None},
        failure_reason=reason,
        diagnostics={"weather_policy": WEATHER_POLICY},
    )


def load_prepared_tables(config: ExperimentConfig) -> dict[str, pd.DataFrame]:
    root = config.experiment_dir
    paths = {
        "environments": root / "normalized/environments.parquet",
        "management_units": root / "normalized/management_units.parquet",
        "observations": root / "normalized/observations.parquet",
        "soil_profiles": root / "normalized/soil_profiles.parquet",
        "eligibility": root / "audit/eligibility.parquet",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "prepared experiment artifacts are missing: " + ", ".join(missing)
        )
    return {name: pd.read_parquet(path) for name, path in paths.items()}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_g2f_weather(
    config: ExperimentConfig, environment_id: str
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load only prepared G2F weather, with explicitly mapped continuation."""

    weather_path = config.experiment_dir / "normalized/weather.parquet"
    if not weather_path.is_file():
        raise FileNotFoundError(f"prepared weather table is missing: {weather_path}")
    frame = pd.read_parquet(
        weather_path,
        columns=["environment_id", "date", *WEATHER_COLUMNS, "source_filename"],
    )
    environment_ids = [environment_id]
    year = int(environment_id.rsplit("_", 1)[1])
    horizon = config.simulation.options.get("scan_horizon", "cross_year")
    if horizon not in {"same_year", "cross_year"}:
        raise ValueError(f"unsupported scan_horizon: {horizon}")
    mapping = config.simulation.options.get("continuation_weather_by_environment", {})
    if horizon == "cross_year" and year < G2F_END_DATE.year:
        continuation_id = mapping.get(environment_id)
        if continuation_id:
            expected = f"{environment_id.rsplit('_', 1)[0]}_{year + 1}"
            if continuation_id != expected:
                raise ValueError(
                    f"G2F continuation for {environment_id} must be {expected}"
                )
            environment_ids.append(continuation_id)
    for selected_id in environment_ids:
        if not frame["environment_id"].eq(selected_id).any():
            raise ValueError(
                f"G2F weather is missing for {selected_id}: {weather_path}"
            )
    environment_rows = frame.loc[frame["environment_id"].isin(environment_ids)].copy()
    environment_rows["date"] = pd.to_datetime(environment_rows["date"]).dt.date
    expected_years = environment_rows["environment_id"].str.rsplit("_", n=1).str[-1]
    actual_years = environment_rows["date"].map(lambda day: str(day.year))
    if not actual_years.eq(expected_years).all():
        raise ValueError("G2F weather dates do not match environment years")
    environment_rows = environment_rows.loc[
        environment_rows["date"].le(G2F_END_DATE)
    ]
    if environment_rows.empty:
        raise ValueError(f"no G2F weather on or before {G2F_END_DATE}")
    if environment_rows["date"].duplicated().any():
        raise ValueError("duplicate dates in G2F weather")
    weather = environment_rows.sort_values("date").reset_index(drop=True)
    weather["source"] = weather["source_filename"]
    provenance = {
        "source": "G2F full-year weather",
        "environment_ids": environment_ids,
        "end_date": weather["date"].max().isoformat(),
        "files": [
            {
                "path": str(weather_path),
                "sha256": _sha256_file(weather_path),
            }
        ],
        "elevation_m": 0.0,
    }
    return weather, provenance


def build_observed_requests(
    config: ExperimentConfig,
    *,
    parameter_set_id: str = "default",
    model_parameters: dict[str, Any] | None = None,
    units: pd.DataFrame | None = None,
) -> tuple[dict[str, SimulationRequest], pd.DataFrame]:
    tables = load_prepared_tables(config)
    if units is None:
        units = select_representative_units(
            tables["management_units"], config.selection.environments
        )
    environments = tables["environments"].set_index("environment_id")
    soils = tables["soil_profiles"].set_index("environment_id")
    parameters = {**dict(config.model.parameters), **(model_parameters or {})}
    requests: dict[str, SimulationRequest] = {}
    provenance_rows = []
    for unit in units.to_dict("records"):
        environment_id = str(unit["environment_id"])
        weather, provenance = load_g2f_weather(config, environment_id)
        environment = environments.loc[environment_id].to_dict()
        environment["environment_id"] = environment_id
        environment["elevation_m"] = provenance["elevation_m"]
        soil = soils.loc[environment_id].to_dict()
        request = build_simulation_request(
            unit,
            environment,
            soil,
            weather,
            parameter_set_id=parameter_set_id,
            model_parameters=parameters,
            output_dir=config.experiment_dir / "model_cache",
        )
        requests[str(unit["management_unit_id"])] = request
        provenance_rows.append(
            {
                "management_unit_id": unit["management_unit_id"],
                "environment_id": environment_id,
                "weather_provenance": json.dumps(provenance, sort_keys=True),
            }
        )
    return requests, pd.DataFrame(provenance_rows)
