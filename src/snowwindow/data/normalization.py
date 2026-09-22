"""Source-specific G2F normalization and representative aggregation."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Mapping
from datetime import date
from typing import Any

import pandas as pd

from snowwindow.data.sources import (
    CORE_WEATHER_COLUMNS,
    SOURCE_CATALOG,
    DataPreparationError,
    parse_g2f_date,
    validate_training_natural_keys,
)

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
NEGATED_SEVERE_BEFORE = re.compile(
    r"\b(?:no|not|without)\b.{0,50}$", re.IGNORECASE
)
NEGATED_SEVERE_AFTER = re.compile(
    r"^\s*(?:was |were )?(?:not reported|not observed|not an issue|absent)",
    re.IGNORECASE,
)
NEGATED_SEVERE_FAMILY = re.compile(
    r"\b(?P<issue>lodging|greensnap|goose.?neck)\b\s+"
    r"(?:was |were )?(?:not reported|not observed|not an issue|absent)",
    re.IGNORECASE,
)


def _source_name(name: str) -> str:
    return SOURCE_CATALOG[name].relative_path


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


def _issue_clauses(comments: list[str] | tuple[str, ...]) -> list[str]:
    clauses = []
    for comment in comments:
        clauses.extend(
            part.strip()
            for part in re.split(r"[|\n;]+|(?<=[.!?])\s+", comment)
            if part.strip()
        )
    return clauses


def positive_severe_issue_clauses(
    comments: list[str] | tuple[str, ...],
) -> list[str]:
    positive = []
    for clause in _issue_clauses(comments):
        negated_families = {
            match.group("issue").lower()
            for match in NEGATED_SEVERE_FAMILY.finditer(clause)
        }
        for match in SEVERE_ISSUE_PATTERN.finditer(clause):
            matched_issue = match.group(0).lower()
            if any(family in matched_issue for family in negated_families):
                continue
            before = clause[max(0, match.start() - 50) : match.start()]
            after = clause[match.end() : match.end() + 70]
            if NEGATED_SEVERE_BEFORE.search(before):
                continue
            if NEGATED_SEVERE_AFTER.search(after):
                continue
            positive.append(clause)
            break
    return positive


def classify_severe_issue(comments: list[str] | tuple[str, ...]) -> bool:
    return bool(positive_severe_issue_clauses(comments))


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
    grouped = {
        environment_id: group
        for environment_id, group in samples.groupby("environment_id", sort=False)
    }
    rows = []
    for environment_id in environments["environment_id"].astype(str):
        group = grouped.get(environment_id)
        mapped_samples: list[tuple[str, str]] = []
        if group is not None:
            for raw_texture in group["texture"]:
                texture = str(raw_texture).strip() if pd.notna(raw_texture) else ""
                if texture in AQUACROP_TEXTURES:
                    mapped_samples.append((texture, "texture_lookup"))
                else:
                    mapped_samples.append((default_texture, "default"))
        if mapped_samples:
            categories = [texture for texture, _ in mapped_samples]
            counts = Counter(categories)
            maximum = max(counts.values())
            texture = min(
                category
                for category, count in counts.items()
                if count == maximum
            )
            selected_sources = [
                source
                for category, source in mapped_samples
                if category == texture
            ]
            profile_source = (
                "default"
                if selected_sources.count("default")
                > selected_sources.count("texture_lookup")
                else "texture_lookup"
            )
            conflict = len(set(categories)) > 1
        else:
            categories = []
            texture = default_texture
            profile_source = "default"
            conflict = False
        rows.append(
            {
                "environment_id": environment_id,
                "texture": texture,
                "aquacrop_soil_type": AQUACROP_TEXTURES[texture],
                "profile_source": profile_source,
                "texture_conflict": conflict,
                "sample_count": len(mapped_samples),
                "recognized_textures": json.dumps(
                    sorted(
                        {
                            category
                            for category, source in mapped_samples
                            if source == "texture_lookup"
                        }
                    ),
                    separators=(",", ":"),
                ),
                "sample_texture_categories": json.dumps(
                    categories, separators=(",", ":")
                ),
                "laboratory_depth_used_as_model_layer_depth": False,
            }
        )
    return pd.DataFrame(rows)


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

    missing = sorted({"management_unit_id", "hybrid"} - set(plots))
    if missing:
        raise DataPreparationError(
            f"plot observations are missing aggregation columns: {missing}"
        )
    rows = []
    variables = (
        ("pollen_dap", "pollen_dap_days", "days"),
        ("silk_dap", "silk_dap_days", "days"),
        ("yield_at_supplied_moisture_mg_ha", "yield_mg_ha", "Mg/ha"),
    )
    valid_units = plots.loc[plots["management_unit_id"].notna()]
    for management_unit_id, unit in valid_units.groupby(
        "management_unit_id", sort=True
    ):
        for variable, column, unit_name in variables:
            hybrid_values = []
            source_rows = 0
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
        hybrid_dates = []
        source_rows = 0
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


def normalize_environments(
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
    for split, source_key, metadata in (
        ("training", "training_metadata", training_metadata),
        ("testing", "testing_metadata", testing_metadata),
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
            positive_clauses = positive_severe_issue_clauses(comments)
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
                    "severe_issue_comments": json.dumps(
                        positive_clauses,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "severe_issue": bool(positive_clauses),
                    "source_filename": _source_name(source_key),
                    "source_row_number": int(source_index) + 1,
                }
            )
        frames.append(pd.DataFrame(rows))
    return (
        pd.concat(frames, ignore_index=True)
        .sort_values("environment_id")
        .reset_index(drop=True)
    )


def normalize_training_plots(
    traits: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
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
    source_filename = _source_name("training_traits")
    exclusions = []
    for index in frame.index[frame["planting_date"].isna()]:
        raw_date = frame.at[index, "Date_Planted"]
        reason = (
            "planting_date_missing"
            if raw_date is None or pd.isna(raw_date) or not str(raw_date).strip()
            else "planting_date_invalid"
        )
        exclusions.append(
            {
                "environment_id": str(frame.at[index, "Env"]),
                "reason": reason,
                "source_filename": source_filename,
                "source_row_number": int(frame.at[index, "source_row_number"]),
            }
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
            "replicate": pd.to_numeric(
                frame["Replicate"], errors="coerce"
            ).astype("Int64"),
            "block": pd.to_numeric(frame["Block"], errors="coerce").astype("Int64"),
            "plot": pd.to_numeric(frame["Plot"], errors="coerce").astype("Int64"),
            "hybrid": frame["Hybrid"].astype(str),
            "planting_date": frame["planting_date"],
            "harvest_date": frame["harvest_date"],
            "source_filename": source_filename,
            "source_row_number": frame["source_row_number"],
            "observation_source_filename": source_filename,
            "observation_source_row_number": frame["source_row_number"],
        }
    )
    for source, target in numeric_columns.items():
        normalized[target] = (
            pd.to_numeric(frame[source], errors="coerce")
            if source in frame
            else None
        )
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
    units["source_filename"] = source_filename
    return normalized, units, exclusions


def normalize_testing_plots(
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
            "source_filename": _source_name("testing_template"),
            "source_row_number": pd.to_numeric(
                joined["source_row_number"], errors="coerce"
            ).astype("Int64"),
            "observation_source_filename": joined[
                "observation_source_row_number"
            ].map(
                lambda value: (
                    _source_name("testing_observations")
                    if pd.notna(value)
                    else None
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
                "source_filename": _source_name("testing_metadata"),
            }
        )
    return normalized, pd.DataFrame(unit_rows)


def normalize_soil(
    training: pd.DataFrame, testing: pd.DataFrame
) -> pd.DataFrame:
    frames = []
    for split, source_key, source in (
        ("training", "training_soil", training),
        ("testing", "testing_soil", testing),
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
                    "source_filename": _source_name(source_key),
                    "source_row_number": index + 1,
                }
            )
        frames.append(pd.DataFrame(rows))
    return (
        pd.concat(frames, ignore_index=True)
        .sort_values(["environment_id", "source_row_number"])
        .reset_index(drop=True)
    )


def weather_dates(frame: pd.DataFrame) -> pd.Series:
    return frame["Date"].map(lambda value: parse_g2f_date(value, source="weather"))


def valid_core_mask(frame: pd.DataFrame) -> pd.Series:
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


def normalize_weather(
    training: pd.DataFrame, testing: pd.DataFrame
) -> pd.DataFrame:
    raw = pd.concat(
        [
            training.assign(
                source_split="training",
                source_filename=_source_name("training_weather"),
                source_row_number=range(1, len(training) + 1),
            ),
            testing.assign(
                source_split="testing",
                source_filename=_source_name("testing_weather"),
                source_row_number=range(1, len(testing) + 1),
            ),
        ],
        ignore_index=True,
        sort=False,
    )
    raw["date"] = weather_dates(raw)
    raw["environment_id"] = raw["Env"].astype(str)
    raw["year"] = raw["date"].map(lambda value: value.year)
    raw["core_weather_valid"] = valid_core_mask(raw)
    excluded = {
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
    weather_variables = [column for column in raw.columns if column not in excluded]
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
    return (
        raw.loc[:, columns]
        .sort_values(["environment_id", "date"])
        .reset_index(drop=True)
    )


def management_with_environment(
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
