"""G2F preparation orchestration and atomic artifact writing."""

from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow

from snowwindow.config import ExperimentConfig
from snowwindow.data.audit import (
    audit_weather_coverage,
    build_audit,
    evaluate_eligibility,
)
from snowwindow.data.normalization import (
    aggregate_representative_maize,
    derive_soil_profiles,
    management_with_environment,
    normalize_environments,
    normalize_soil,
    normalize_testing_plots,
    normalize_training_plots,
    normalize_weather,
)
from snowwindow.data.sources import (
    SCHEMA_VERSION,
    WEATHER_UNITS,
    build_source_inventory,
    read_model_input_sources,
    sha256_file,
    source_paths,
)

EXPECTED_ARTIFACT_PATHS = (
    "normalized/environments.parquet",
    "normalized/management_units.parquet",
    "normalized/plot_observations.parquet",
    "normalized/observations.parquet",
    "normalized/soil_samples.parquet",
    "normalized/soil_profiles.parquet",
    "normalized/weather.parquet",
    "normalized/data_dictionary.json",
    "audit/data_audit.json",
    "audit/eligibility.parquet",
    "manifests/prepare_manifest.json",
)


@dataclass(frozen=True)
class PreparationResult:
    generated_artifacts: tuple[Path, ...]
    counts: Mapping[str, int]
    calibration_eligible_management_unit_ids: tuple[str, ...]
    scan_eligible_management_unit_ids: tuple[str, ...]

    @property
    def eligible_management_unit_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                set(self.calibration_eligible_management_unit_ids)
                | set(self.scan_eligible_management_unit_ids)
            )
        )


@dataclass
class _NormalizedData:
    environments: pd.DataFrame
    management_units: pd.DataFrame
    plot_observations: pd.DataFrame
    observations: pd.DataFrame
    soil_samples: pd.DataFrame
    soil_profiles: pd.DataFrame
    weather: pd.DataFrame
    eligibility: pd.DataFrame
    audit: dict[str, Any]
    source_paths: dict[str, Path]
    source_inventory: dict[str, dict[str, Any]]
    assumptions: dict[str, Any]


def _normalize(config: ExperimentConfig) -> _NormalizedData:
    paths = source_paths(config)
    source_inventory = build_source_inventory(paths)
    sources = read_model_input_sources(paths)
    environments = normalize_environments(
        sources["training_metadata"],
        sources["testing_metadata"],
        sources["training_traits"],
    )
    training_plots, training_units, source_exclusions = normalize_training_plots(
        sources["training_traits"]
    )
    testing_plots, testing_units = normalize_testing_plots(
        sources["testing_template"],
        sources["testing_observations"],
        sources["testing_metadata"],
    )
    plots = (
        pd.concat([training_plots, testing_plots], ignore_index=True, sort=False)
        .sort_values(
            [
                "source_split",
                "environment_id",
                "experiment",
                "replicate",
                "block",
                "plot",
                "hybrid",
            ],
            na_position="last",
        )
        .reset_index(drop=True)
    )
    management_units = management_with_environment(
        pd.concat([training_units, testing_units], ignore_index=True, sort=False),
        environments,
    )
    moisture_fraction = float(
        config.model.parameters.get("grain_standard_moisture_fraction", 0.155)
    )
    if not 0 <= moisture_fraction < 1:
        raise ValueError("grain_standard_moisture_fraction must be in [0, 1)")
    observations = aggregate_representative_maize(
        plots, grain_standard_moisture_fraction=moisture_fraction
    )
    default_texture = str(config.model.parameters.get("default_soil_texture", "Loam"))
    soil_samples = normalize_soil(
        sources["training_soil"], sources["testing_soil"]
    )
    soil_profiles = derive_soil_profiles(
        environments, soil_samples, default_texture=default_texture
    )
    source_weather = pd.concat(
        [sources["training_weather"], sources["testing_weather"]],
        ignore_index=True,
        sort=False,
    )
    weather_coverage = audit_weather_coverage(source_weather)
    weather = normalize_weather(
        sources["training_weather"], sources["testing_weather"]
    )
    eligibility = evaluate_eligibility(
        config,
        management_units,
        environments,
        observations,
        soil_profiles,
        weather_coverage,
    )
    audit = build_audit(
        config,
        sources,
        source_inventory,
        source_exclusions,
        environments,
        management_units,
        soil_samples,
        soil_profiles,
        weather_coverage,
        eligibility,
    )
    assumptions = {
        "grain_standard_moisture_fraction": moisture_fraction,
        "dry_yield_conversion": (
            "dry_yield_mg_ha = yield_at_supplied_moisture_mg_ha * "
            "(1 - grain_standard_moisture_fraction)"
        ),
        "dry_yield_source_row_count": int(
            observations.loc[
                observations["variable"].eq("dry_yield_mg_ha"),
                "source_row_count",
            ].sum()
        ),
        "default_soil_texture": default_texture,
        "representative_maize": (
            "mean valid plots within hybrid, then mean hybrid means equally"
        ),
        "yield_magnitude_used_for_selection": False,
        "soil_sample_depth": (
            "raw laboratory E Depth is preserved and is not a model layer depth"
        ),
        "scan_horizon": str(
            config.simulation.options.get("scan_horizon", "cross_year")
        ),
        "continuation_weather_requires_explicit_mapping": True,
    }
    return _NormalizedData(
        environments=environments,
        management_units=management_units,
        plot_observations=plots,
        observations=observations,
        soil_samples=soil_samples,
        soil_profiles=soil_profiles,
        weather=weather,
        eligibility=eligibility,
        audit=audit,
        source_paths=paths,
        source_inventory=source_inventory,
        assumptions=assumptions,
    )


def audit_g2f(config: ExperimentConfig) -> dict[str, Any]:
    """Audit source data without writing normalized or audit artifacts."""

    return _normalize(config).audit


def _json_default(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
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
        frame.to_parquet(temporary, index=False, engine="pyarrow")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _data_dictionary(data: _NormalizedData) -> dict[str, Any]:
    frames = {
        "environments": data.environments,
        "management_units": data.management_units,
        "plot_observations": data.plot_observations,
        "observations": data.observations,
        "soil_samples": data.soil_samples,
        "soil_profiles": data.soil_profiles,
        "weather": data.weather,
        "eligibility": data.eligibility,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "tables": {
            name: {
                "columns": [
                    {"name": column, "dtype": str(frame[column].dtype)}
                    for column in frame.columns
                ]
            }
            for name, frame in frames.items()
        },
        "weather_source_units": WEATHER_UNITS,
        "soil_depth_note": (
            "raw_sample_depth reproduces laboratory field E Depth; it is not "
            "interpreted as an AquaCrop layer boundary"
        ),
        "irrigation_values": [
            "rainfed_confirmed",
            "irrigated_confirmed",
            "unknown",
        ],
    }


def _producer_metadata() -> dict[str, str]:
    try:
        version = importlib.metadata.version("snowwindow")
    except importlib.metadata.PackageNotFoundError:
        version = "0.1.0"
    if not version:
        version = "0.1.0"
    return {"name": "snowwindow", "version": version}


def prepare_g2f(config: ExperimentConfig) -> PreparationResult:
    """Normalize G2F sources and atomically write the preparation artifacts."""

    data = _normalize(config)
    root = config.experiment_dir
    frames = {
        "normalized/environments.parquet": data.environments,
        "normalized/management_units.parquet": data.management_units,
        "normalized/plot_observations.parquet": data.plot_observations,
        "normalized/observations.parquet": data.observations,
        "normalized/soil_samples.parquet": data.soil_samples,
        "normalized/soil_profiles.parquet": data.soil_profiles,
        "normalized/weather.parquet": data.weather,
        "audit/eligibility.parquet": data.eligibility,
    }
    for relative_path, frame in frames.items():
        _atomic_parquet(root / relative_path, frame)
    json_artifacts = {
        "normalized/data_dictionary.json": _data_dictionary(data),
        "audit/data_audit.json": data.audit,
    }
    for relative_path, value in json_artifacts.items():
        _atomic_json(root / relative_path, value)

    artifact_metadata = {}
    for relative_path in (*frames, *json_artifacts):
        path = root / relative_path
        artifact_metadata[relative_path] = {
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
            "row_count": (
                len(frames[relative_path]) if relative_path in frames else None
            ),
        }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "producer": _producer_metadata(),
        "runtime": {
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "pyarrow": pyarrow.__version__,
        },
        "sources": data.source_inventory,
        "artifacts": artifact_metadata,
        "counts": data.audit["counts"],
        "assumptions": data.assumptions,
    }
    _atomic_json(root / "manifests/prepare_manifest.json", manifest)

    calibration_ids = tuple(
        data.eligibility.loc[
            data.eligibility["calibration_eligible"], "management_unit_id"
        ].astype(str)
    )
    scan_ids = tuple(
        data.eligibility.loc[
            data.eligibility["scan_eligible"], "management_unit_id"
        ].astype(str)
    )
    generated = tuple(root / relative for relative in EXPECTED_ARTIFACT_PATHS)
    return PreparationResult(
        generated_artifacts=generated,
        counts=dict(data.audit["counts"]),
        calibration_eligible_management_unit_ids=calibration_ids,
        scan_eligible_management_unit_ids=scan_ids,
    )
