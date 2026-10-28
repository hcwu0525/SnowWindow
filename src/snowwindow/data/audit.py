"""Weather, source-exclusion, and management eligibility audits."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from datetime import date
from typing import Any

import pandas as pd

from snowwindow.config import ExperimentConfig
from snowwindow.data.normalization import (
    SEVERE_ISSUE_RULE,
    valid_core_mask,
    weather_dates,
)
from snowwindow.data.sources import CORE_WEATHER_COLUMNS, DataPreparationError
from snowwindow.weather import G2F_END_DATE, weather_end_for_year


def _year_from_environment(environment_id: str) -> int | None:
    match = re.search(r"_(\d{4})$", environment_id)
    return int(match.group(1)) if match else None


def audit_weather_coverage(weather: pd.DataFrame) -> dict[str, dict[str, Any]]:
    weather = weather.reset_index(drop=True)
    missing = sorted({"Env", "Date", *CORE_WEATHER_COLUMNS} - set(weather))
    if missing:
        raise DataPreparationError(f"weather table is missing columns: {missing}")
    dates = weather_dates(weather)
    if dates.isna().any():
        rows = (dates[dates.isna()].index + 1).tolist()[:10]
        raise DataPreparationError(f"weather dates failed to parse at rows {rows}")
    keys = pd.DataFrame({"Env": weather["Env"], "Date": dates})
    duplicates = keys.duplicated(["Env", "Date"], keep=False)
    if duplicates.any():
        examples = keys.loc[duplicates].head(5).to_dict(orient="records")
        raise DataPreparationError(f"duplicate weather (Env, Date) keys: {examples}")

    valid_core = valid_core_mask(weather)
    result = {}
    for environment_id, indexes in weather.groupby("Env", sort=True).groups.items():
        environment_dates = dates.loc[indexes]
        source_year = _year_from_environment(str(environment_id))
        observed_years = sorted({value.year for value in environment_dates})
        aligned = source_year is None or observed_years == [source_year]
        year = source_year if source_year is not None else observed_years[0]
        required_end = weather_end_for_year(year)
        expected = {
            timestamp.date()
            for timestamp in pd.date_range(f"{year}-01-01", required_end)
        }
        observed = set(environment_dates)
        missing_dates = sorted(expected - observed)
        gap_dates = sorted(
            environment_dates.loc[
                [
                    index for index in indexes
                    if not bool(valid_core.loc[index]) and dates.loc[index] in expected
                ]
            ].tolist()
        )
        date_calendar_complete = aligned and not missing_dates
        result[str(environment_id)] = {
            "year": year,
            "first_date": min(observed).isoformat(),
            "last_date": max(observed).isoformat(),
            "row_count": len(indexes),
            "environment_year_aligned": aligned,
            "required_end_date": required_end.isoformat(),
            "full_year_calendar_complete": (
                aligned
                and len(observed) == len(
                    pd.date_range(f"{year}-01-01", f"{year}-12-31")
                )
                and bool(valid_core.loc[indexes].all())
            ),
            "date_calendar_complete": date_calendar_complete,
            "calendar_complete": date_calendar_complete and not gap_dates,
            "missing_calendar_dates": [
                missing_date.isoformat() for missing_date in missing_dates
            ],
            "core_gap_dates": [gap_date.isoformat() for gap_date in gap_dates],
        }
    return result


def _weather_reason(
    weather: Mapping[str, Any] | None,
    *,
    missing_reason: str = "weather_missing",
    incomplete_reason: str = "weather_incomplete",
) -> str | None:
    if weather is None:
        return missing_reason
    if not weather["calendar_complete"]:
        return incomplete_reason
    return None


def _scan_weather_reason(
    config: ExperimentConfig,
    environment_id: str,
    year: int,
    weather_coverage: Mapping[str, Mapping[str, Any]],
) -> str | None:
    current_reason = _weather_reason(weather_coverage.get(environment_id))
    if current_reason is not None:
        return current_reason
    horizon = str(config.simulation.options.get("scan_horizon", "cross_year"))
    if horizon == "same_year":
        return None
    if horizon != "cross_year":
        raise DataPreparationError(f"unsupported scan_horizon: {horizon}")
    if year == G2F_END_DATE.year:
        return None
    mapping = config.simulation.options.get(
        "continuation_weather_by_environment", {}
    )
    if not isinstance(mapping, Mapping):
        raise DataPreparationError(
            "continuation_weather_by_environment must be a mapping"
        )
    continuation_id = mapping.get(environment_id)
    if not isinstance(continuation_id, str) or not continuation_id:
        return "crossyear_weather_missing"
    continuation = weather_coverage.get(continuation_id)
    if (
        continuation is None
        or continuation_id != f"{environment_id.rsplit('_', 1)[0]}_{year + 1}"
        or continuation.get("year") != year + 1
        or not continuation.get("calendar_complete", False)
    ):
        return "crossyear_weather_missing"
    return None


def evaluate_eligibility(
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
        year = int(unit["year"])
        environment = environment_map.loc[environment_id]
        soil = soil_map.loc[environment_id]
        irrigation = environment["irrigation_status"]
        eligibility_irrigation = (
            "assumed_rainfed"
            if irrigation == "unknown"
            and config.selection.allow_assumed_rainfed
            else irrigation
        )

        base_reasons = []
        if pd.isna(environment["latitude"]) or pd.isna(environment["longitude"]):
            base_reasons.append("coordinates_missing")
        if not isinstance(unit["planting_date"], date):
            base_reasons.append("planting_date_missing")
        if irrigation == "unknown" and not config.selection.allow_assumed_rainfed:
            base_reasons.append("rainfed_unconfirmed")

        scientific_reasons = list(base_reasons)
        current_weather_reason = _weather_reason(weather_coverage.get(environment_id))
        if current_weather_reason is not None:
            scientific_reasons.append(current_weather_reason)
        unit_observations = (
            observation_values.loc[management_unit_id]
            if management_unit_id in observation_values.index
            else pd.Series(dtype=float)
        )
        if pd.isna(unit_observations.get("pollen_dap")):
            scientific_reasons.append("pollen_observation_missing")
        if pd.isna(unit_observations.get("yield_at_supplied_moisture_mg_ha")):
            scientific_reasons.append("yield_observation_missing")
        if soil["profile_source"] == "default":
            scientific_reasons.append("default_soil")
        if bool(environment["severe_issue"]):
            scientific_reasons.append("severe_issue")

        calibration_reasons = list(scientific_reasons)
        if year not in config.selection.calibration_years:
            calibration_reasons.append("not_calibration_year")
        evaluation_reasons = list(scientific_reasons)
        if year not in config.selection.evaluation_years:
            evaluation_reasons.append("not_evaluation_year")

        scan_reasons = list(base_reasons)
        scan_weather_reason = _scan_weather_reason(
            config, environment_id, year, weather_coverage
        )
        if scan_weather_reason is not None:
            scan_reasons.append(scan_weather_reason)
        if soil["profile_source"] == "default" and not allow_default_scan:
            scan_reasons.append("default_soil")
        rows.append(
            {
                "management_unit_id": management_unit_id,
                "environment_id": environment_id,
                "year": year,
                "irrigation_assumption": eligibility_irrigation,
                "scan_horizon": str(
                    config.simulation.options.get("scan_horizon", "cross_year")
                ),
                "continuation_weather_environment_id": (
                    config.simulation.options.get(
                        "continuation_weather_by_environment", {}
                    ).get(environment_id)
                    if isinstance(
                        config.simulation.options.get(
                            "continuation_weather_by_environment", {}
                        ),
                        Mapping,
                    )
                    else None
                ),
                "population_source": unit.get("population_source"),
                "population_source_count": unit.get("population_source_count"),
                "soil_profile_source": soil["profile_source"],
                "soil_texture_conflict": bool(soil["texture_conflict"]),
                "data_quality": (
                    "high"
                    if soil["profile_source"] == "particle_fractions"
                    and unit.get("population_source") == "plot_trimmed_median"
                    else "standard"
                ),
                "calibration_eligible": not calibration_reasons,
                "calibration_reason_codes": json.dumps(
                    calibration_reasons, separators=(",", ":")
                ),
                "evaluation_eligible": not evaluation_reasons,
                "evaluation_reason_codes": json.dumps(
                    evaluation_reasons, separators=(",", ":")
                ),
                "scan_eligible": not scan_reasons,
                "scan_reason_codes": json.dumps(scan_reasons, separators=(",", ":")),
            }
        )
    return pd.DataFrame(rows).sort_values("management_unit_id").reset_index(drop=True)


def build_audit(
    config: ExperimentConfig,
    sources: Mapping[str, pd.DataFrame],
    source_inventory: Mapping[str, Mapping[str, Any]],
    source_exclusions: list[dict[str, Any]],
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
    exclusion_counts = dict(
        sorted(Counter(item["reason"] for item in source_exclusions).items())
    )
    return {
        "schema_version": "g2f-normalized-v1",
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
        "source_inventory": dict(source_inventory),
        "source_exclusions": sorted(
            source_exclusions,
            key=lambda item: (
                item["source_filename"],
                item["source_row_number"],
                item["reason"],
            ),
        ),
        "source_exclusion_counts": exclusion_counts,
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
            "soil_profile_sources": (
                soil_profiles["profile_source"]
                .value_counts()
                .sort_index()
                .to_dict()
            ),
            "coordinate_sources": (
                environments["coordinate_source"]
                .value_counts()
                .sort_index()
                .to_dict()
            ),
            "irrigation_statuses": (
                environments["irrigation_status"]
                .value_counts()
                .sort_index()
                .to_dict()
            ),
            "severe_issue_environments": int(environments["severe_issue"].sum()),
        },
        "eligibility": {
            "calibration_eligible_count": int(
                eligibility["calibration_eligible"].sum()
            ),
            "scan_eligible_count": int(eligibility["scan_eligible"].sum()),
            "calibration_years": list(config.selection.calibration_years),
            "evaluation_years": list(config.selection.evaluation_years),
            "scan_horizon": str(
                config.simulation.options.get("scan_horizon", "cross_year")
            ),
        },
        "rules": {
            "severe_issue_regex": SEVERE_ISSUE_RULE,
            "severe_issue_negation": (
                "A severe term is ignored only when its clause explicitly "
                "negates or reports absence of that issue."
            ),
            "yield_magnitude_used_for_selection": False,
            "continuation_weather": (
                "Cross-year forcing is accepted only through the explicit "
                "continuation_weather_by_environment mapping."
            ),
        },
    }
