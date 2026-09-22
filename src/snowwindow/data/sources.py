"""G2F source catalog, parsing, loading, and provenance."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from snowwindow.config import ExperimentConfig

SCHEMA_VERSION = "g2f-normalized-v1"

CORE_WEATHER_COLUMNS = (
    "T2M_MIN",
    "T2M_MAX",
    "PRECTOTCORR",
    "RH2M",
    "WS2M",
    "PS",
    "ALLSKY_SFC_SW_DWN",
)

WEATHER_UNITS = {
    "T2M_MIN": "degrees_C",
    "T2M_MAX": "degrees_C",
    "PRECTOTCORR": "mm/day",
    "RH2M": "percent",
    "WS2M": "m/s",
    "PS": "kPa",
    "ALLSKY_SFC_SW_DWN": "MJ/m^2/day",
    "T2MWET": "degrees_C",
    "GWETTOP": "fraction",
    "QV2M": "g/kg",
    "GWETPROF": "fraction",
    "T2MDEW": "degrees_C",
    "T2M": "degrees_C",
    "GWETROOT": "fraction",
    "ALLSKY_SFC_PAR_TOT": "W/m^2",
    "ALLSKY_SFC_SW_DNI": "MJ/m^2/day",
}

TRAINING_KEY = ("Env", "Experiment", "Replicate", "Block", "Plot")


class DataPreparationError(ValueError):
    """Raised when source data violate a required normalization contract."""


@dataclass(frozen=True)
class SourceSpec:
    relative_path: str
    role: str


SOURCE_CATALOG = {
    "training_traits": SourceSpec(
        "Training_data/1_Training_Trait_Data_2014_2023.csv", "model_input"
    ),
    "training_metadata": SourceSpec(
        "Training_data/2_Training_Meta_Data_2014_2023.csv", "model_input"
    ),
    "training_soil": SourceSpec(
        "Training_data/3_Training_Soil_Data_2015_2023.csv", "model_input"
    ),
    "training_weather": SourceSpec(
        "Training_data/4_Training_Weather_Data_2014_2023_full_year.csv",
        "model_input",
    ),
    "training_weather_seasons_only": SourceSpec(
        "Training_data/4_Training_Weather_Data_2014_2023_seasons_only.csv",
        "excluded_from_model_inputs",
    ),
    "training_ec": SourceSpec(
        "Training_data/6_Training_EC_Data_2014_2023.csv",
        "excluded_from_model_inputs",
    ),
    "testing_template": SourceSpec(
        "Testing_data/1_Submission_Template_2024.csv", "model_input"
    ),
    "testing_metadata": SourceSpec(
        "Testing_data/2_Testing_Meta_Data_2024.csv", "model_input"
    ),
    "testing_soil": SourceSpec(
        "Testing_data/3_Testing_Soil_Data_2024.csv", "model_input"
    ),
    "testing_weather": SourceSpec(
        "Testing_data/4_Testing_Weather_Data_2024_full_year.csv", "model_input"
    ),
    "testing_weather_seasons_only": SourceSpec(
        "Testing_data/4_Testing_Weather_Data_2024_seasons_only.csv",
        "excluded_from_model_inputs",
    ),
    "testing_ec": SourceSpec(
        "Testing_data/6_Testing_EC_Data_2024.csv",
        "excluded_from_model_inputs",
    ),
    "testing_observations": SourceSpec(
        "Testing_data/7_Testing_Observed_Values.csv", "model_input"
    ),
}


def parse_g2f_date(value: object, *, source: str) -> date | None:
    """Parse one date using the documented format for its G2F source."""

    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    formats = {
        "training": "%m/%d/%y",
        "testing": "%m/%d/%Y",
        "weather": "%Y%m%d",
    }
    if source not in formats:
        raise DataPreparationError(f"unknown G2F date source: {source}")
    parsed = pd.to_datetime(str(value).strip(), format=formats[source], errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def validate_training_natural_keys(plots: pd.DataFrame) -> None:
    missing = [column for column in TRAINING_KEY if column not in plots]
    if missing:
        raise DataPreparationError(
            f"training plot table is missing natural-key columns: {missing}"
        )
    null_keys = plots.loc[
        plots.loc[:, TRAINING_KEY].isna().any(axis=1), list(TRAINING_KEY)
    ]
    if not null_keys.empty:
        raise DataPreparationError(
            "null training plot natural key components: "
            f"{null_keys.head(5).to_dict(orient='records')}"
        )
    duplicates = plots.duplicated(list(TRAINING_KEY), keep=False)
    if duplicates.any():
        examples = (
            plots.loc[duplicates, list(TRAINING_KEY)].head(5).to_dict(orient="records")
        )
        raise DataPreparationError(
            f"duplicate training plot natural key {TRAINING_KEY}: {examples}"
        )


def source_paths(config: ExperimentConfig) -> dict[str, Path]:
    paths = {
        name: (config.data_dir / spec.relative_path).resolve()
        for name, spec in SOURCE_CATALOG.items()
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise DataPreparationError(f"required G2F source files are missing: {missing}")
    return paths


def read_model_input_sources(
    paths: Mapping[str, Path],
) -> dict[str, pd.DataFrame]:
    return {
        name: pd.read_csv(paths[name], low_memory=False)
        for name, spec in SOURCE_CATALOG.items()
        if spec.role == "model_input"
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_source_inventory(paths: Mapping[str, Path]) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "path": str(paths[name]),
            "size_bytes": paths[name].stat().st_size,
            "sha256": sha256_file(paths[name]),
            "role": spec.role,
        }
        for name, spec in sorted(SOURCE_CATALOG.items())
    }
