"""Read-only G2F source normalization, audit, and artifact preparation."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from collections import Counter
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

AQUACROP_TEXTURES = {
    "Clay": "Clay",
    "Clay Loam": "ClayLoam",
    "Loam": "Loam",
    "Loamy Sand": "LoamySand",
    "Sand": "Sand",
    "Sandy Clay": "SandyClay",
    "Sandy Clay Loam": "SandyClayLoam",
    "Sandy Loam": "SandyLoam",
    "Silt": "Silt",
    "Silt Loam": "SiltLoam",
    "Silty Clay": "SiltClay",
    "Silty Clay Loam": "SiltClayLoam",
}

SEVERE_ISSUE_RULE = (
    r"lodging|greensnap|goose.?neck|cranes|mixed seeds|mixed between|"
    r"planter (?:had an issue|error|jammed)|planting mistake|busted berm|"
    r"plots.*irrigated|uneven germination|extremely variable|"
    r"some seed.*(?:did not|didn't)|plants died|abandoned these plots|"
    r"excluded all pass|hogs? damage"
)
SEVERE_ISSUE_PATTERN = re.compile(SEVERE_ISSUE_RULE, re.IGNORECASE)

TRAINING_KEY = ("Env", "Experiment", "Replicate", "Block", "Plot")

SOURCE_FILES = {
    "training_traits": ("Training_data/1_Training_Trait_Data_2014_2023.csv"),
    "training_metadata": ("Training_data/2_Training_Meta_Data_2014_2023.csv"),
    "training_soil": "Training_data/3_Training_Soil_Data_2015_2023.csv",
    "training_weather": (
        "Training_data/4_Training_Weather_Data_2014_2023_full_year.csv"
    ),
    "testing_template": "Testing_data/1_Submission_Template_2024.csv",
    "testing_metadata": "Testing_data/2_Testing_Meta_Data_2024.csv",
    "testing_soil": "Testing_data/3_Testing_Soil_Data_2024.csv",
    "testing_weather": ("Testing_data/4_Testing_Weather_Data_2024_full_year.csv"),
    "testing_observations": "Testing_data/7_Testing_Observed_Values.csv",
}

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


class DataPreparationError(ValueError):
    """Raised when source data violate a required normalization contract."""


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
    assumptions: dict[str, Any]


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
    duplicates = plots.duplicated(list(TRAINING_KEY), keep=False)
    if duplicates.any():
        examples = (
            plots.loc[duplicates, list(TRAINING_KEY)].head(5).to_dict(orient="records")
        )
        raise DataPreparationError(
            f"duplicate training plot natural key {TRAINING_KEY}: {examples}"
        )


def _valid_latitude(value: object) -> float | None:
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number) or not -90 <= float(number) <= 90:
        return None
    return float(number)


def _valid_longitude(value: object) -> float | None:
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number) or not -180 <= float(number) <= 180:
        return None
    return float(number)


def resolve_coordinates(
    row: Mapping[str, object],
) -> tuple[float | None, float | None, str]:
    """Resolve a coordinate pair without mixing station and field sources."""

    station_lat = _valid_latitude(
        row.get("Weather_Station_Latitude (in decimal numbers NOT DMS)")
    )
    station_lon = _valid_longitude(
        row.get("Weather_Station_Longitude (in decimal numbers NOT DMS)")
    )
    if station_lat is not None and station_lon is not None:
        return station_lat, station_lon, "weather_station"

    pairs: list[tuple[float, float]] = []
    for number in range(1, 5):
        lat_prefix = f"Latitude_of_Field_Corner_#{number}"
        lon_prefix = f"Longitude_of_Field_Corner_#{number}"
        lat_key = next((key for key in row if str(key).startswith(lat_prefix)), None)
        lon_key = next((key for key in row if str(key).startswith(lon_prefix)), None)
        if lat_key is None or lon_key is None:
            continue
        latitude = _valid_latitude(row.get(lat_key))
        longitude = _valid_longitude(row.get(lon_key))
        if latitude is not None and longitude is not None:
            pairs.append((latitude, longitude))
    if pairs:
        return (
            sum(pair[0] for pair in pairs) / len(pairs),
            sum(pair[1] for pair in pairs) / len(pairs),
            "field_centroid",
        )
    return None, None, "missing"


def normalize_irrigation(value: object) -> str:
    if value is None or pd.isna(value):
        return "unknown"
    normalized = str(value).strip().lower()
    if normalized == "no":
        return "rainfed_confirmed"
    if normalized == "yes":
        return "irrigated_confirmed"
    return "unknown"


def classify_severe_issue(comments: list[str] | tuple[str, ...]) -> bool:
    return any(SEVERE_ISSUE_PATTERN.search(comment) for comment in comments)


def derive_soil_profiles(
    environments: pd.DataFrame,
    samples: pd.DataFrame,
    *,
    default_texture: str,
) -> pd.DataFrame:
    if default_texture not in AQUACROP_TEXTURES:
        raise DataPreparationError(
            f"default soil texture is not recognized: {default_texture}"
        )
    rows: list[dict[str, Any]] = []
    grouped = {
        environment_id: group
        for environment_id, group in samples.groupby("environment_id", sort=False)
    }
    for environment_id in environments["environment_id"].astype(str):
        group = grouped.get(environment_id)
        recognized: list[str] = []
        sample_count = 0
        if group is not None:
            sample_count = len(group)
            recognized = [
                str(value).strip()
                for value in group["texture"].dropna()
                if str(value).strip() in AQUACROP_TEXTURES
            ]
        if recognized:
            counts = Counter(recognized)
            maximum = max(counts.values())
            texture = min(
                texture for texture, count in counts.items() if count == maximum
            )
            source = "texture_lookup"
            conflict = len(counts) > 1
        else:
            texture = default_texture
            source = "default"
            conflict = False
        rows.append(
            {
                "environment_id": environment_id,
                "texture": texture,
                "aquacrop_soil_type": AQUACROP_TEXTURES[texture],
                "profile_source": source,
                "texture_conflict": conflict,
                "sample_count": sample_count,
                "recognized_textures": json.dumps(
                    sorted(set(recognized)), separators=(",", ":")
                ),
                "laboratory_depth_used_as_model_layer_depth": False,
            }
        )
    return pd.DataFrame(rows)


def _mean_or_none(series: pd.Series) -> float | None:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return None
    return float(numeric.mean())


def _mean_date(dates: pd.Series) -> date | None:
    valid = [value for value in dates if isinstance(value, date)]
    if not valid:
        return None
    ordinal = sum(value.toordinal() for value in valid) / len(valid)
    return date.fromordinal(math.floor(ordinal + 0.5))


def aggregate_representative_maize(
    plots: pd.DataFrame,
    *,
    grain_standard_moisture_fraction: float,
) -> pd.DataFrame:
    """Average plots within hybrid, then average hybrid means equally."""

    required = {"management_unit_id", "hybrid"}
    missing = sorted(required - set(plots))
    if missing:
        raise DataPreparationError(
            f"plot observations are missing aggregation columns: {missing}"
        )
    rows: list[dict[str, Any]] = []
    variables = (
        ("pollen_dap", "pollen_dap_days", "days"),
        ("silk_dap", "silk_dap_days", "days"),
        (
            "yield_at_supplied_moisture_mg_ha",
            "yield_mg_ha",
            "Mg/ha",
        ),
    )
    valid_units = plots.loc[plots["management_unit_id"].notna()]
    for management_unit_id, unit in valid_units.groupby(
        "management_unit_id", sort=True
    ):
        for variable, column, unit_name in variables:
            hybrid_values: list[float] = []
            source_rows = 0
            if column in unit:
                for _, hybrid in unit.groupby("hybrid", sort=True):
                    numeric = pd.to_numeric(hybrid[column], errors="coerce").dropna()
                    if not numeric.empty:
                        hybrid_values.append(float(numeric.mean()))
                        source_rows += len(numeric)
            value = sum(hybrid_values) / len(hybrid_values) if hybrid_values else None
            rows.append(
                {
                    "management_unit_id": management_unit_id,
                    "variable": variable,
                    "value": value,
                    "unit": unit_name,
                    "observed_date": None,
                    "source_row_count": source_rows,
                    "hybrid_count": len(hybrid_values),
                }
            )
            if variable == "yield_at_supplied_moisture_mg_ha":
                rows.append(
                    {
                        "management_unit_id": management_unit_id,
                        "variable": "dry_yield_mg_ha",
                        "value": (
                            value * (1.0 - grain_standard_moisture_fraction)
                            if value is not None
                            else None
                        ),
                        "unit": "Mg/ha",
                        "observed_date": None,
                        "source_row_count": source_rows,
                        "hybrid_count": len(hybrid_values),
                    }
                )

        hybrid_dates: list[date] = []
        source_rows = 0
        if "harvest_date" in unit:
            for _, hybrid in unit.groupby("hybrid", sort=True):
                hybrid_date = _mean_date(hybrid["harvest_date"])
                if hybrid_date is not None:
                    hybrid_dates.append(hybrid_date)
                    source_rows += sum(
                        isinstance(value, date) for value in hybrid["harvest_date"]
                    )
        rows.append(
            {
                "management_unit_id": management_unit_id,
                "variable": "observed_harvest_date",
                "value": None,
                "unit": "ISO-8601 date",
                "observed_date": _mean_date(pd.Series(hybrid_dates, dtype=object)),
                "source_row_count": source_rows,
                "hybrid_count": len(hybrid_dates),
            }
        )
    return pd.DataFrame(rows)


def _date_from_environment(environment_id: str) -> int | None:
    match = re.search(r"_(\d{4})$", environment_id)
    return int(match.group(1)) if match else None


def _weather_dates(frame: pd.DataFrame) -> pd.Series:
    return frame["Date"].map(lambda value: parse_g2f_date(value, source="weather"))


def _valid_core_mask(frame: pd.DataFrame) -> pd.Series:
    values = frame.loc[:, CORE_WEATHER_COLUMNS].apply(pd.to_numeric, errors="coerce")
    present = values.notna().all(axis=1) & values.gt(-900).all(axis=1)
    physical = (
        values["T2M_MIN"].le(values["T2M_MAX"])
        & values["PRECTOTCORR"].ge(0)
        & values["RH2M"].between(0, 100)
        & values["WS2M"].ge(0)
        & values["PS"].gt(0)
        & values["ALLSKY_SFC_SW_DWN"].ge(0)
    )
    return present & physical


def audit_weather_coverage(weather: pd.DataFrame) -> dict[str, dict[str, Any]]:
    weather = weather.reset_index(drop=True)
    missing = sorted({"Env", "Date", *CORE_WEATHER_COLUMNS} - set(weather))
    if missing:
        raise DataPreparationError(f"weather table is missing columns: {missing}")
    dates = _weather_dates(weather)
    if dates.isna().any():
        rows = (dates[dates.isna()].index + 1).tolist()[:10]
        raise DataPreparationError(f"weather dates failed to parse at rows {rows}")
    keys = pd.DataFrame({"Env": weather["Env"], "Date": dates})
    duplicates = keys.duplicated(["Env", "Date"], keep=False)
    if duplicates.any():
        examples = keys.loc[duplicates].head(5).to_dict(orient="records")
        raise DataPreparationError(f"duplicate weather (Env, Date) keys: {examples}")

    valid_core = _valid_core_mask(weather)
    result: dict[str, dict[str, Any]] = {}
    for environment_id, indexes in weather.groupby("Env", sort=True).groups.items():
        environment_dates = dates.loc[indexes]
        source_year = _date_from_environment(str(environment_id))
        observed_years = sorted({value.year for value in environment_dates})
        aligned = source_year is None or observed_years == [source_year]
        year = source_year if source_year is not None else observed_years[0]
        expected = set(
            timestamp.date()
            for timestamp in pd.date_range(f"{year}-01-01", f"{year}-12-31")
        )
        observed = set(environment_dates)
        missing_dates = sorted(expected - observed)
        gap_dates = sorted(
            environment_dates.loc[
                [index for index in indexes if not bool(valid_core.loc[index])]
            ].tolist()
        )
        date_calendar_complete = aligned and not missing_dates
        result[str(environment_id)] = {
            "year": year,
            "first_date": min(observed).isoformat(),
            "last_date": max(observed).isoformat(),
            "row_count": len(indexes),
            "environment_year_aligned": aligned,
            "date_calendar_complete": date_calendar_complete,
            "calendar_complete": date_calendar_complete and not gap_dates,
            "missing_calendar_dates": [
                missing_date.isoformat() for missing_date in missing_dates
            ],
            "core_gap_dates": [gap_date.isoformat() for gap_date in gap_dates],
        }
    return result


def _source_paths(config: ExperimentConfig) -> dict[str, Path]:
    paths = {
        name: (config.data_dir / relative).resolve()
        for name, relative in SOURCE_FILES.items()
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise DataPreparationError(f"required G2F source files are missing: {missing}")
    return paths


def _read_sources(paths: Mapping[str, Path]) -> dict[str, pd.DataFrame]:
    return {name: pd.read_csv(path, low_memory=False) for name, path in paths.items()}


def _json_value(value: object) -> object:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _raw_row_json(row: pd.Series) -> str:
    return json.dumps(
        {str(key): _json_value(value) for key, value in row.items()},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _issue_comments(row: Mapping[str, object]) -> list[str]:
    comments = []
    for key, value in row.items():
        if not str(key).startswith("Issue/comment_"):
            continue
        if value is None or pd.isna(value):
            continue
        comment = str(value).strip()
        if comment:
            comments.append(comment)
    return comments


def _normalize_environments(
    training_metadata: pd.DataFrame,
    testing_metadata: pd.DataFrame,
    training_traits: pd.DataFrame,
) -> pd.DataFrame:
    field_locations = {}
    for environment_id, group in training_traits.groupby("Env", sort=False):
        values = group["Field_Location"].dropna().astype(str)
        if not values.empty:
            counts = values.value_counts()
            field_locations[str(environment_id)] = min(
                value for value, count in counts.items() if count == counts.max()
            )
    frames = []
    for split, source_name, metadata in (
        (
            "training",
            SOURCE_FILES["training_metadata"],
            training_metadata,
        ),
        ("testing", SOURCE_FILES["testing_metadata"], testing_metadata),
    ):
        if metadata["Env"].duplicated().any():
            duplicates = metadata.loc[
                metadata["Env"].duplicated(keep=False), "Env"
            ].tolist()
            raise DataPreparationError(
                f"duplicate {split} environment metadata rows: {duplicates[:10]}"
            )
        rows = []
        for source_index, source_row in metadata.iterrows():
            row = source_row.to_dict()
            latitude, longitude, coordinate_source = resolve_coordinates(row)
            comments = _issue_comments(row)
            rows.append(
                {
                    "environment_id": str(row["Env"]),
                    "source_split": split,
                    "year": int(row["Year"]),
                    "experiment_code": str(row.get("Experiment_Code", "")),
                    "field_location": (
                        field_locations.get(str(row["Env"]))
                        if split == "training"
                        else None
                    ),
                    "city": _json_value(row.get("City")),
                    "farm": _json_value(row.get("Farm")),
                    "field": _json_value(row.get("Field")),
                    "latitude": latitude,
                    "longitude": longitude,
                    "coordinate_source": coordinate_source,
                    "irrigation_status": normalize_irrigation(row.get("Irrigated")),
                    "issue_comments": json.dumps(
                        comments, ensure_ascii=False, separators=(",", ":")
                    ),
                    "severe_issue": classify_severe_issue(comments),
                    "source_filename": source_name,
                    "source_row_number": int(source_index) + 1,
                }
            )
        frames.append(pd.DataFrame(rows))
    return (
        pd.concat(frames, ignore_index=True)
        .sort_values("environment_id")
        .reset_index(drop=True)
    )


def _normalize_training_plots(
    traits: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    validate_training_natural_keys(traits)
    frame = traits.copy()
    frame["source_row_number"] = range(1, len(frame) + 1)
    frame["planting_date"] = frame["Date_Planted"].map(
        lambda value: parse_g2f_date(value, source="training")
    )
    frame["harvest_date"] = frame["Date_Harvested"].map(
        lambda value: parse_g2f_date(value, source="training")
    )
    frame["management_unit_id"] = frame.apply(
        lambda row: (
            f"{row['Env']}__{row['Experiment']}__{row['planting_date'].isoformat()}"
            if isinstance(row["planting_date"], date)
            else None
        ),
        axis=1,
    )
    numeric_columns = {
        "Pollen_DAP_days": "pollen_dap_days",
        "Silk_DAP_days": "silk_dap_days",
        "Yield_Mg_ha": "yield_mg_ha",
        "Grain_Moisture": "grain_moisture",
        "Plot_Area_ha": "plot_area_ha",
        "Stand_Count_plants": "stand_count_plants",
    }
    normalized = pd.DataFrame(
        {
            "source_split": "training",
            "environment_id": frame["Env"].astype(str),
            "management_unit_id": frame["management_unit_id"],
            "env": frame["Env"].astype(str),
            "year": pd.to_numeric(frame["Year"], errors="coerce").astype("Int64"),
            "field_location": frame["Field_Location"].astype("string"),
            "experiment": frame["Experiment"].astype(str),
            "replicate": pd.to_numeric(frame["Replicate"], errors="coerce").astype(
                "Int64"
            ),
            "block": pd.to_numeric(frame["Block"], errors="coerce").astype("Int64"),
            "plot": pd.to_numeric(frame["Plot"], errors="coerce").astype("Int64"),
            "hybrid": frame["Hybrid"].astype(str),
            "planting_date": frame["planting_date"],
            "harvest_date": frame["harvest_date"],
            "source_filename": SOURCE_FILES["training_traits"],
            "source_row_number": frame["source_row_number"],
            "observation_source_filename": SOURCE_FILES["training_traits"],
            "observation_source_row_number": frame["source_row_number"],
        }
    )
    for source, target in numeric_columns.items():
        if source in frame:
            normalized[target] = pd.to_numeric(frame[source], errors="coerce")
        else:
            normalized[target] = None
    for column in ("pollen_dap_days", "silk_dap_days"):
        normalized.loc[~normalized[column].between(1, 200), column] = None
    normalized.loc[normalized["yield_mg_ha"].lt(0), "yield_mg_ha"] = None

    valid = normalized.loc[normalized["management_unit_id"].notna()]
    units = valid.groupby(
        [
            "management_unit_id",
            "environment_id",
            "experiment",
            "planting_date",
        ],
        as_index=False,
        sort=True,
    ).agg(
        source_row_number=("source_row_number", "min"),
        plot_count=("source_row_number", "size"),
    )
    units["source_split"] = "training"
    units["source_filename"] = SOURCE_FILES["training_traits"]
    return normalized, units


def _normalize_testing_plots(
    template: pd.DataFrame,
    observed: pd.DataFrame,
    metadata: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    template = template.copy()
    observed = observed.copy()
    template["source_row_number"] = range(1, len(template) + 1)
    observed["observation_source_row_number"] = range(1, len(observed) + 1)
    key = ["Env", "Hybrid"]
    if template.duplicated(key).any():
        raise DataPreparationError("duplicate testing template (Env, Hybrid) key")
    if observed.duplicated(key).any():
        raise DataPreparationError("duplicate testing observation (Env, Hybrid) key")
    joined = template.drop(columns=["Yield_Mg_ha"]).merge(
        observed[key + ["Yield_Mg_ha", "observation_source_row_number"]],
        how="outer",
        on=key,
        validate="one_to_one",
    )
    joined = joined.merge(
        metadata[["Env", "Year", "Experiment_Code", "Date_Planted"]],
        how="left",
        on="Env",
        validate="many_to_one",
    )
    joined["planting_date"] = joined["Date_Planted"].map(
        lambda value: parse_g2f_date(value, source="testing")
    )
    joined["management_unit_id"] = joined.apply(
        lambda row: (
            f"{row['Env']}__{row['Experiment_Code']}__"
            f"{row['planting_date'].isoformat()}"
            if isinstance(row["planting_date"], date)
            else None
        ),
        axis=1,
    )
    normalized = pd.DataFrame(
        {
            "source_split": "testing",
            "environment_id": joined["Env"].astype(str),
            "management_unit_id": joined["management_unit_id"],
            "env": joined["Env"].astype(str),
            "year": pd.to_numeric(joined["Year"], errors="coerce").astype("Int64"),
            "field_location": pd.Series(pd.NA, index=joined.index, dtype="string"),
            "experiment": joined["Experiment_Code"].astype(str),
            "replicate": pd.Series(pd.NA, index=joined.index, dtype="Int64"),
            "block": pd.Series(pd.NA, index=joined.index, dtype="Int64"),
            "plot": pd.Series(pd.NA, index=joined.index, dtype="Int64"),
            "hybrid": joined["Hybrid"].astype(str),
            "planting_date": joined["planting_date"],
            "harvest_date": None,
            "pollen_dap_days": pd.Series(float("nan"), index=joined.index),
            "silk_dap_days": pd.Series(float("nan"), index=joined.index),
            "yield_mg_ha": pd.to_numeric(joined["Yield_Mg_ha"], errors="coerce"),
            "grain_moisture": pd.Series(float("nan"), index=joined.index),
            "plot_area_ha": pd.Series(float("nan"), index=joined.index),
            "stand_count_plants": pd.Series(float("nan"), index=joined.index),
            "source_filename": SOURCE_FILES["testing_template"],
            "source_row_number": pd.to_numeric(
                joined["source_row_number"], errors="coerce"
            ).astype("Int64"),
            "observation_source_filename": joined["observation_source_row_number"].map(
                lambda value: (
                    SOURCE_FILES["testing_observations"] if pd.notna(value) else None
                )
            ),
            "observation_source_row_number": pd.to_numeric(
                joined["observation_source_row_number"], errors="coerce"
            ).astype("Int64"),
        }
    )

    unit_rows = []
    for source_index, row in metadata.iterrows():
        planting_date = parse_g2f_date(row.get("Date_Planted"), source="testing")
        if planting_date is None:
            continue
        environment_id = str(row["Env"])
        experiment = str(row["Experiment_Code"])
        unit_rows.append(
            {
                "management_unit_id": (
                    f"{environment_id}__{experiment}__{planting_date.isoformat()}"
                ),
                "environment_id": environment_id,
                "experiment": experiment,
                "planting_date": planting_date,
                "source_row_number": source_index + 1,
                "plot_count": int(
                    normalized["environment_id"].eq(environment_id).sum()
                ),
                "source_split": "testing",
                "source_filename": SOURCE_FILES["testing_metadata"],
            }
        )
    return normalized, pd.DataFrame(unit_rows)


def _normalize_soil(training: pd.DataFrame, testing: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for split, source_name, source in (
        ("training", SOURCE_FILES["training_soil"], training),
        ("testing", SOURCE_FILES["testing_soil"], testing),
    ):
        rows = []
        for index, row in source.iterrows():
            rows.append(
                {
                    "environment_id": str(row["Env"]),
                    "source_split": split,
                    "year": pd.to_numeric(row.get("Year"), errors="coerce"),
                    "lab_id": _json_value(row.get("LabID")),
                    "raw_sample_depth": _json_value(row.get("E Depth")),
                    "raw_sample_depth_field": "E Depth",
                    "texture": _json_value(row.get("Texture")),
                    "soil_ph": pd.to_numeric(row.get("1:1 Soil pH"), errors="coerce"),
                    "sand_percent": pd.to_numeric(row.get("% Sand"), errors="coerce"),
                    "silt_percent": pd.to_numeric(row.get("% Silt"), errors="coerce"),
                    "clay_percent": pd.to_numeric(row.get("% Clay"), errors="coerce"),
                    "comments": _json_value(row.get("Comments")),
                    "raw_values": _raw_row_json(row),
                    "source_filename": source_name,
                    "source_row_number": index + 1,
                }
            )
        frames.append(pd.DataFrame(rows))
    return (
        pd.concat(frames, ignore_index=True)
        .sort_values(["environment_id", "source_row_number"])
        .reset_index(drop=True)
    )


def _normalize_weather(
    training: pd.DataFrame, testing: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    raw = pd.concat(
        [
            training.assign(
                source_split="training",
                source_filename=SOURCE_FILES["training_weather"],
                source_row_number=range(1, len(training) + 1),
            ),
            testing.assign(
                source_split="testing",
                source_filename=SOURCE_FILES["testing_weather"],
                source_row_number=range(1, len(testing) + 1),
            ),
        ],
        ignore_index=True,
        sort=False,
    )
    coverage = audit_weather_coverage(raw)
    raw["date"] = _weather_dates(raw)
    raw["environment_id"] = raw["Env"].astype(str)
    raw["year"] = raw["date"].map(lambda value: value.year)
    raw["core_weather_valid"] = _valid_core_mask(raw)
    weather_variables = [
        column
        for column in raw.columns
        if column
        not in {
            "Env",
            "Date",
            "environment_id",
            "date",
            "year",
            "source_split",
            "source_filename",
            "source_row_number",
            "core_weather_valid",
        }
    ]
    for column in weather_variables:
        raw[column] = pd.to_numeric(raw[column], errors="coerce")
        raw.loc[raw[column].le(-900), column] = None
    columns = [
        "environment_id",
        "source_split",
        "year",
        "date",
        *weather_variables,
        "core_weather_valid",
        "source_filename",
        "source_row_number",
    ]
    normalized = (
        raw.loc[:, columns]
        .sort_values(["environment_id", "date"])
        .reset_index(drop=True)
    )
    return normalized, coverage


def _management_with_environment(
    units: pd.DataFrame, environments: pd.DataFrame
) -> pd.DataFrame:
    environment_fields = environments[
        [
            "environment_id",
            "year",
            "irrigation_status",
            "severe_issue",
            "issue_comments",
        ]
    ]
    result = units.merge(
        environment_fields,
        how="left",
        on="environment_id",
        validate="many_to_one",
    )
    return result.sort_values("management_unit_id").reset_index(drop=True)


def _eligibility(
    config: ExperimentConfig,
    management_units: pd.DataFrame,
    environments: pd.DataFrame,
    observations: pd.DataFrame,
    soil_profiles: pd.DataFrame,
    weather_coverage: Mapping[str, Mapping[str, Any]],
) -> pd.DataFrame:
    observation_values = observations.pivot(
        index="management_unit_id", columns="variable", values="value"
    )
    environment_map = environments.set_index("environment_id")
    soil_map = soil_profiles.set_index("environment_id")
    allow_default_scan = bool(
        config.selection.options.get("allow_default_soil_for_scan", True)
    )
    rows = []
    for unit in management_units.to_dict(orient="records"):
        management_unit_id = unit["management_unit_id"]
        environment_id = unit["environment_id"]
        environment = environment_map.loc[environment_id]
        soil = soil_map.loc[environment_id]
        weather = weather_coverage.get(environment_id)
        irrigation = environment["irrigation_status"]
        if irrigation == "unknown" and config.selection.allow_assumed_rainfed:
            eligibility_irrigation = "assumed_rainfed"
        else:
            eligibility_irrigation = irrigation

        shared_reasons = []
        if pd.isna(environment["latitude"]) or pd.isna(environment["longitude"]):
            shared_reasons.append("coordinates_missing")
        if not isinstance(unit["planting_date"], date):
            shared_reasons.append("planting_date_missing")
        if weather is None:
            shared_reasons.append("weather_missing")
        elif not weather["calendar_complete"]:
            shared_reasons.append("weather_incomplete")
        if irrigation == "irrigated_confirmed":
            shared_reasons.append("irrigated_confirmed")
        elif irrigation == "unknown" and not config.selection.allow_assumed_rainfed:
            shared_reasons.append("rainfed_unconfirmed")

        calibration_reasons = list(shared_reasons)
        if int(unit["year"]) not in config.selection.calibration_years:
            calibration_reasons.append("not_calibration_year")
        unit_observations = (
            observation_values.loc[management_unit_id]
            if management_unit_id in observation_values.index
            else pd.Series(dtype=float)
        )
        if pd.isna(unit_observations.get("pollen_dap")):
            calibration_reasons.append("pollen_observation_missing")
        if pd.isna(unit_observations.get("yield_at_supplied_moisture_mg_ha")):
            calibration_reasons.append("yield_observation_missing")
        if soil["profile_source"] == "default":
            calibration_reasons.append("default_soil")
        if bool(environment["severe_issue"]):
            calibration_reasons.append("severe_issue")

        scan_reasons = list(shared_reasons)
        if soil["profile_source"] == "default" and not allow_default_scan:
            scan_reasons.append("default_soil")
        rows.append(
            {
                "management_unit_id": management_unit_id,
                "environment_id": environment_id,
                "year": int(unit["year"]),
                "irrigation_assumption": eligibility_irrigation,
                "calibration_eligible": not calibration_reasons,
                "calibration_reason_codes": json.dumps(
                    calibration_reasons, separators=(",", ":")
                ),
                "scan_eligible": not scan_reasons,
                "scan_reason_codes": json.dumps(scan_reasons, separators=(",", ":")),
            }
        )
    return pd.DataFrame(rows).sort_values("management_unit_id").reset_index(drop=True)


def _build_audit(
    config: ExperimentConfig,
    sources: Mapping[str, pd.DataFrame],
    environments: pd.DataFrame,
    management_units: pd.DataFrame,
    soil_samples: pd.DataFrame,
    soil_profiles: pd.DataFrame,
    weather_coverage: Mapping[str, Mapping[str, Any]],
    eligibility: pd.DataFrame,
) -> dict[str, Any]:
    training_environments = set(
        environments.loc[environments["source_split"].eq("training"), "environment_id"]
    )
    testing_environments = set(
        environments.loc[environments["source_split"].eq("testing"), "environment_id"]
    )
    weather_environments = set(weather_coverage)
    testing_coverage = {
        environment_id: weather_coverage[environment_id]
        for environment_id in sorted(testing_environments & weather_environments)
    }
    testing_gap_dates = sorted(
        {
            gap
            for coverage in testing_coverage.values()
            for gap in coverage["core_gap_dates"]
        }
    )
    coordinate_counts = (
        environments["coordinate_source"].value_counts().sort_index().to_dict()
    )
    irrigation_counts = (
        environments["irrigation_status"].value_counts().sort_index().to_dict()
    )
    profile_counts = (
        soil_profiles["profile_source"].value_counts().sort_index().to_dict()
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "counts": {
            "training_plot_rows": len(sources["training_traits"]),
            "training_environments": len(training_environments),
            "testing_template_rows": len(sources["testing_template"]),
            "testing_observation_rows": len(sources["testing_observations"]),
            "testing_environments": len(testing_environments),
            "training_management_units": int(
                management_units["source_split"].eq("training").sum()
            ),
            "testing_management_units": int(
                management_units["source_split"].eq("testing").sum()
            ),
            "soil_samples": len(soil_samples),
            "weather_rows": sum(
                coverage["row_count"] for coverage in weather_coverage.values()
            ),
        },
        "weather": {
            "training_missing_environments": sorted(
                training_environments - weather_environments
            ),
            "testing_environment_count_ending_2024_11_10": sum(
                coverage["last_date"] == "2024-11-10"
                for coverage in testing_coverage.values()
            ),
            "testing_core_gap_dates": testing_gap_dates,
            "environment_coverage": dict(weather_coverage),
        },
        "coverage": {
            "soil_sample_environments": int(soil_samples["environment_id"].nunique()),
            "soil_profile_sources": profile_counts,
            "coordinate_sources": coordinate_counts,
            "irrigation_statuses": irrigation_counts,
            "severe_issue_environments": int(environments["severe_issue"].sum()),
        },
        "eligibility": {
            "calibration_eligible_count": int(
                eligibility["calibration_eligible"].sum()
            ),
            "scan_eligible_count": int(eligibility["scan_eligible"].sum()),
            "calibration_years": list(config.selection.calibration_years),
            "evaluation_years": list(config.selection.evaluation_years),
        },
        "rules": {
            "severe_issue_regex": SEVERE_ISSUE_RULE,
            "yield_magnitude_used_for_selection": False,
        },
    }


def _normalize(config: ExperimentConfig) -> _NormalizedData:
    paths = _source_paths(config)
    sources = _read_sources(paths)
    environments = _normalize_environments(
        sources["training_metadata"],
        sources["testing_metadata"],
        sources["training_traits"],
    )
    training_plots, training_units = _normalize_training_plots(
        sources["training_traits"]
    )
    testing_plots, testing_units = _normalize_testing_plots(
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
    units = _management_with_environment(
        pd.concat([training_units, testing_units], ignore_index=True, sort=False),
        environments,
    )
    moisture_fraction = float(
        config.model.parameters.get("grain_standard_moisture_fraction", 0.155)
    )
    if not 0 <= moisture_fraction < 1:
        raise DataPreparationError("grain_standard_moisture_fraction must be in [0, 1)")
    observations = aggregate_representative_maize(
        plots, grain_standard_moisture_fraction=moisture_fraction
    )
    default_texture = str(config.model.parameters.get("default_soil_texture", "Loam"))
    soil_samples = _normalize_soil(sources["training_soil"], sources["testing_soil"])
    soil_profiles = derive_soil_profiles(
        environments,
        soil_samples,
        default_texture=default_texture,
    )
    weather, weather_coverage = _normalize_weather(
        sources["training_weather"], sources["testing_weather"]
    )
    eligibility = _eligibility(
        config,
        units,
        environments,
        observations,
        soil_profiles,
        weather_coverage,
    )
    audit = _build_audit(
        config,
        sources,
        environments,
        units,
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
    }
    return _NormalizedData(
        environments=environments,
        management_units=units,
        plot_observations=plots,
        observations=observations,
        soil_samples=soil_samples,
        soil_profiles=soil_profiles,
        weather=weather,
        eligibility=eligibility,
        audit=audit,
        source_paths=paths,
        assumptions=assumptions,
    )


def audit_g2f(config: ExperimentConfig) -> dict[str, Any]:
    """Audit source data without writing normalized or audit artifacts."""

    return _normalize(config).audit


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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


def _atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    frame.to_parquet(temporary, index=False, engine="pyarrow")
    os.replace(temporary, path)


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
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
            "row_count": (
                len(frames[relative_path]) if relative_path in frames else None
            ),
        }
    source_metadata = {
        name: {
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        for name, path in sorted(data.source_paths.items())
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "sources": source_metadata,
        "artifacts": artifact_metadata,
        "counts": data.audit["counts"],
        "assumptions": data.assumptions,
    }
    manifest_path = root / "manifests/prepare_manifest.json"
    _atomic_json(manifest_path, manifest)

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
