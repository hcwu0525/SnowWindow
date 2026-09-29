"""Experiment input assembly shared by calibration and planting-date scans."""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from snowwindow.adapters import resolve_model_adapter
from snowwindow.config import ExperimentConfig
from snowwindow.domain import (
    Environment,
    ManagementUnit,
    SimulationRequest,
    SoilLayer,
    WeatherRecord,
    WeatherStrategy,
)
from snowwindow.models.aquacrop import simulation_end_for_planting

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
    end_date = min(planned_end, weather_end)
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


def load_cached_power_weather(
    config: ExperimentConfig, environment_id: str
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load audited current/next-year POWER forcing from the prepared tables."""

    weather_path = config.experiment_dir / "normalized/weather.parquet"
    if not weather_path.is_file():
        raise FileNotFoundError(f"prepared weather table is missing: {weather_path}")
    frame = pd.read_parquet(
        weather_path,
        columns=["environment_id", "date", *WEATHER_COLUMNS, "source_filename"],
    )
    environment_rows = frame.loc[frame["environment_id"].eq(environment_id)].copy()
    environment_rows["date"] = pd.to_datetime(environment_rows["date"]).dt.date
    weather = environment_rows.sort_values("date").reset_index(drop=True)
    provenance = {
        "source": "G2F full-year NASA POWER forcing",
        "files": [
            {
                "path": str(weather_path),
                "sha256": _sha256_file(weather_path),
            }
        ],
        "elevation_m": 0.0,
    }
    return weather, provenance

    # Retained legacy loader for explicit cross-year POWER cache users.
    current = config.output_dir / "aquacrop_demo/weather" / f"{environment_id}.csv"
    continuation = (
        config.output_dir
        / "aquacrop_crossyear/weather"
        / f"{environment_id}_next_year.csv"
    )
    current_provenance = (
        config.output_dir
        / "aquacrop_demo/weather_raw"
        / f"{environment_id}.provenance.json"
    )
    continuation_provenance = (
        config.output_dir
        / "aquacrop_crossyear/weather_raw"
        / f"{environment_id}_next_year.provenance.json"
    )
    required = (current, continuation, current_provenance, continuation_provenance)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "complete cached POWER forcing is missing: " + ", ".join(missing)
        )
    frames = []
    for path in (current, continuation):
        current_frame = pd.read_csv(path, usecols=["Date", *WEATHER_COLUMNS])
        current_frame = current_frame.rename(columns={"Date": "date"})
        current_frame["date"] = pd.to_datetime(current_frame["date"]).dt.date
        current_frame["source"] = str(path)
        frames.append(current_frame)
    weather = (
        pd.concat(frames, ignore_index=True)
        .sort_values("date")
        .drop_duplicates("date", keep="first")
        .reset_index(drop=True)
    )
    provenance_rows = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (current_provenance, continuation_provenance)
    ]
    provenance = {
        "source": "NASA POWER AG cached full-year forcing",
        "files": [
            {"path": str(path), "sha256": _sha256_file(path)} for path in required
        ],
        "elevation_m": float(provenance_rows[0].get("elevation_m", 0.0)),
    }
    return weather, provenance


def load_legacy_crossyear_weather(
    config: ExperimentConfig, environment_id: str
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load the explicit legacy current/next-year POWER cache."""

    current = config.output_dir / "aquacrop_demo/weather" / f"{environment_id}.csv"
    continuation = (
        config.output_dir
        / "aquacrop_crossyear/weather"
        / f"{environment_id}_next_year.csv"
    )
    current_provenance = (
        config.output_dir
        / "aquacrop_demo/weather_raw"
        / f"{environment_id}.provenance.json"
    )
    continuation_provenance = (
        config.output_dir
        / "aquacrop_crossyear/weather_raw"
        / f"{environment_id}_next_year.provenance.json"
    )
    required = (current, continuation, current_provenance, continuation_provenance)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "complete cached POWER forcing is missing: " + ", ".join(missing)
        )
    frames = []
    for path in (current, continuation):
        frame = pd.read_csv(path, usecols=["Date", *WEATHER_COLUMNS])
        frame = frame.rename(columns={"Date": "date"})
        frame["date"] = pd.to_datetime(frame["date"]).dt.date
        frame["source"] = str(path)
        frames.append(frame)
    weather = (
        pd.concat(frames, ignore_index=True)
        .sort_values("date")
        .drop_duplicates("date", keep="first")
        .reset_index(drop=True)
    )
    provenance_rows = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (current_provenance, continuation_provenance)
    ]
    return weather, {
        "source": "NASA POWER AG cached full-year forcing",
        "files": [
            {"path": str(path), "sha256": _sha256_file(path)} for path in required
        ],
        "elevation_m": float(provenance_rows[0].get("elevation_m", 0.0)),
    }


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
    model = resolve_model_adapter(config)
    loader = (
        load_legacy_crossyear_weather
        if model.capabilities.weather_strategy is WeatherStrategy.LEGACY_CROSSYEAR
        else load_cached_power_weather
    )
    for unit in units.to_dict("records"):
        environment_id = str(unit["environment_id"])
        weather, provenance = loader(config, environment_id)
        if weather.empty:
            continue
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
