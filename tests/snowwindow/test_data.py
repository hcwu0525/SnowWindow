from __future__ import annotations

import json
import platform
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow
import pytest
import yaml

from snowwindow.cli import main
from snowwindow.config import (
    CalibrationConfig,
    ExperimentConfig,
    ModelConfig,
    SelectionConfig,
    SimulationConfig,
)
from snowwindow.data import (
    DataPreparationError,
    PreparationResult,
    add_density_to_management_units,
    aggregate_representative_maize,
    audit_g2f,
    audit_weather_coverage,
    classify_severe_issue,
    classify_usda_texture,
    derive_soil_profiles,
    evaluate_eligibility,
    normalize_irrigation,
    parse_g2f_date,
    prepare_g2f,
    resolve_coordinates,
    validate_training_natural_keys,
)
from snowwindow.domain import (
    ModelCapabilities,
    RunStatus,
    SimulationRequest,
    SimulationResult,
)

EXPECTED_ARTIFACTS = {
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
}

CORE_WEATHER = {
    "T2M_MIN": 10.0,
    "T2M_MAX": 20.0,
    "PRECTOTCORR": 1.0,
    "RH2M": 60.0,
    "WS2M": 2.0,
    "PS": 100.0,
    "ALLSKY_SFC_SW_DWN": 15.0,
}


def _config(
    data_dir: Path,
    output_dir: Path,
    *,
    simulation_options: dict[str, object] | None = None,
) -> ExperimentConfig:
    return ExperimentConfig(
        experiment_id="fixture",
        data_dir=data_dir,
        output_dir=output_dir,
        model=ModelConfig(
            name="aquacrop",
            parameters={
                "grain_standard_moisture_fraction": 0.155,
                "default_soil_texture": "Loam",
            },
        ),
        selection=SelectionConfig(
            calibration_years=(2022,),
            evaluation_years=(2024,),
            allow_assumed_rainfed=True,
        ),
        simulation=SimulationConfig(
            scan_fractions=(1.0,),
            workers=1,
            scan_all_dates=True,
            options=simulation_options or {"scan_horizon": "cross_year"},
        ),
        calibration=CalibrationConfig(
            phenology_grid=(0.8, 1.2, 0.02),
            phenology_fine_step=0.005,
            yield_grid=(0.35, 0.55, 0.01),
            yield_fine_step=0.0025,
        ),
        source_path=output_dir / "fixture.yaml",
    )


def _metadata_row(
    env: str,
    year: int,
    experiment_code: str,
    *,
    planting_date: str | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "Year": year,
        "Env": env,
        "Experiment_Code": experiment_code,
        "Treatment": "Standard",
        "City": "Ames",
        "Farm": "Research Farm",
        "Field": "One",
        "Weather_Station_Latitude (in decimal numbers NOT DMS)": 42.0,
        "Weather_Station_Longitude (in decimal numbers NOT DMS)": -93.0,
        "Irrigated": "no",
        "Issue/comment_#1": "",
    }
    if planting_date is not None:
        row["Date_Planted"] = planting_date
        row["Plot_Area_ha"] = 0.001
    return row


def _weather_rows(env: str, year: int) -> list[dict[str, object]]:
    rows = []
    for timestamp in pd.date_range(f"{year}-01-01", f"{year}-12-31"):
        rows.append(
            {
                "Env": env,
                "Date": int(timestamp.strftime("%Y%m%d")),
                **CORE_WEATHER,
            }
        )
    return rows


def _write_fixture_data(root: Path) -> None:
    training = root / "Training_data"
    testing = root / "Testing_data"
    training.mkdir(parents=True)
    testing.mkdir(parents=True)

    pd.DataFrame(
        [
            {
                "Env": "IAH1_2022",
                "Year": 2022,
                "Field_Location": "IAH1",
                "Experiment": "EXP_A",
                "Replicate": 1,
                "Block": 1,
                "Plot": 1,
                "Hybrid": "A",
                "Date_Planted": "5/1/22",
                "Date_Harvested": "10/1/22",
                "Pollen_DAP_days": 60,
                "Silk_DAP_days": 62,
                "Yield_Mg_ha": 2.0,
                "Grain_Moisture": 15.5,
            },
            {
                "Env": "IAH1_2022",
                "Year": 2022,
                "Field_Location": "IAH1",
                "Experiment": "EXP_A",
                "Replicate": 1,
                "Block": 1,
                "Plot": 2,
                "Hybrid": "A",
                "Date_Planted": "5/1/22",
                "Date_Harvested": "10/3/22",
                "Pollen_DAP_days": 64,
                "Silk_DAP_days": 66,
                "Yield_Mg_ha": 4.0,
                "Grain_Moisture": 15.5,
            },
            {
                "Env": "IAH1_2022",
                "Year": 2022,
                "Field_Location": "IAH1",
                "Experiment": "EXP_A",
                "Replicate": 2,
                "Block": 1,
                "Plot": 3,
                "Hybrid": "B",
                "Date_Planted": "5/1/22",
                "Date_Harvested": "10/5/22",
                "Pollen_DAP_days": 70,
                "Silk_DAP_days": 72,
                "Yield_Mg_ha": 10.0,
                "Grain_Moisture": 15.5,
            },
            {
                "Env": "IAH1_2022",
                "Year": 2022,
                "Field_Location": "IAH1",
                "Experiment": "EXP_A",
                "Replicate": 2,
                "Block": 1,
                "Plot": 4,
                "Hybrid": "C",
                "Date_Planted": None,
                "Date_Harvested": None,
                "Pollen_DAP_days": None,
                "Silk_DAP_days": None,
                "Yield_Mg_ha": None,
                "Grain_Moisture": None,
            },
        ]
    ).to_csv(training / "1_Training_Trait_Data_2014_2023.csv", index=False)
    pd.DataFrame([_metadata_row("IAH1_2022", 2022, "IAH1")]).to_csv(
        training / "2_Training_Meta_Data_2014_2023.csv", index=False
    )
    pd.DataFrame(
        [
            {
                "Year": 2022,
                "Env": "IAH1_2022",
                "LabID": "lab-1",
                "E Depth": 12,
                "Texture": "Clay Loam",
                "1:1 Soil pH": 6.5,
            }
        ]
    ).to_csv(training / "3_Training_Soil_Data_2015_2023.csv", index=False)
    pd.DataFrame(
        _weather_rows("IAH1_2022", 2022) + _weather_rows("IAH1_2023", 2023)
    ).to_csv(training / "4_Training_Weather_Data_2014_2023_full_year.csv", index=False)
    pd.DataFrame(_weather_rows("IAH1_2022", 2022)[:2]).to_csv(
        training / "4_Training_Weather_Data_2014_2023_seasons_only.csv",
        index=False,
    )
    pd.DataFrame([{"Env": "IAH1_2022", "EC_feature": 1.0}]).to_csv(
        training / "6_Training_EC_Data_2014_2023.csv", index=False
    )

    pd.DataFrame(
        [
            {"Env": "IAH1_2024", "Hybrid": "A", "Yield_Mg_ha": None},
            {"Env": "IAH1_2024", "Hybrid": "B", "Yield_Mg_ha": None},
        ]
    ).to_csv(testing / "1_Submission_Template_2024.csv", index=False)
    pd.DataFrame(
        [
            _metadata_row(
                "IAH1_2024",
                2024,
                "IAH1",
                planting_date="5/2/2024",
            )
        ]
    ).to_csv(testing / "2_Testing_Meta_Data_2024.csv", index=False)
    pd.DataFrame(
        [
            {
                "Year": 2024,
                "Env": "IAH1_2024",
                "LabID": "lab-2",
                "E Depth": 8,
                "Texture": "Loam",
                "1:1 Soil pH": 6.8,
            }
        ]
    ).to_csv(testing / "3_Testing_Soil_Data_2024.csv", index=False)
    pd.DataFrame(_weather_rows("IAH1_2024", 2024)).to_csv(
        testing / "4_Testing_Weather_Data_2024_full_year.csv", index=False
    )
    pd.DataFrame(_weather_rows("IAH1_2024", 2024)[:2]).to_csv(
        testing / "4_Testing_Weather_Data_2024_seasons_only.csv", index=False
    )
    pd.DataFrame([{"Env": "IAH1_2024", "EC_feature": 2.0}]).to_csv(
        testing / "6_Testing_EC_Data_2024.csv", index=False
    )
    pd.DataFrame([{"Env": "IAH1_2024", "Hybrid": "A", "Yield_Mg_ha": 8.0}]).to_csv(
        testing / "7_Testing_Observed_Values.csv", index=False
    )


@pytest.mark.parametrize(
    ("value", "source", "expected"),
    [
        ("5/5/14", "training", date(2014, 5, 5)),
        ("4/25/2024", "testing", date(2024, 4, 25)),
        (20240712, "weather", date(2024, 7, 12)),
        ("", "training", None),
        (None, "testing", None),
    ],
)
def test_parse_g2f_date_uses_documented_source_formats(
    value: object, source: str, expected: date | None
) -> None:
    assert parse_g2f_date(value, source=source) == expected


def test_training_natural_key_duplicate_is_rejected() -> None:
    plots = pd.DataFrame(
        [
            {
                "Env": "IAH1_2022",
                "Experiment": "EXP",
                "Replicate": 1,
                "Block": 1,
                "Plot": 7,
                "Hybrid": "A",
            },
            {
                "Env": "IAH1_2022",
                "Experiment": "EXP",
                "Replicate": 1,
                "Block": 1,
                "Plot": 7,
                "Hybrid": "B",
            },
        ]
    )

    with pytest.raises(DataPreparationError, match="training plot natural key"):
        validate_training_natural_keys(plots)


@pytest.mark.parametrize("column", ["Env", "Experiment", "Replicate", "Block", "Plot"])
def test_training_natural_key_null_component_is_rejected(column: str) -> None:
    plot = {
        "Env": "IAH1_2022",
        "Experiment": "EXP",
        "Replicate": 1,
        "Block": 1,
        "Plot": 7,
    }
    plot[column] = None

    with pytest.raises(DataPreparationError, match="null training plot natural key"):
        validate_training_natural_keys(pd.DataFrame([plot]))


def test_coordinates_prefer_station_then_complete_field_centroid() -> None:
    station = {
        "Weather_Station_Latitude (in decimal numbers NOT DMS)": "42.1",
        "Weather_Station_Longitude (in decimal numbers NOT DMS)": "-93.2",
        "Latitude_of_Field_Corner_#1 (lower left)": 40,
        "Longitude_of_Field_Corner_#1 (lower left)": -90,
    }
    assert resolve_coordinates(station) == (42.1, -93.2, "weather_station")

    field = {
        "Weather_Station_Latitude (in decimal numbers NOT DMS)": 999,
        "Weather_Station_Longitude (in decimal numbers NOT DMS)": -93.2,
        "Latitude_of_Field_Corner_#1 (lower left)": 40.0,
        "Longitude_of_Field_Corner_#1 (lower left)": -90.0,
        "Latitude_of_Field_Corner_#2 (lower right)": 42.0,
        "Longitude_of_Field_Corner_#2 (lower right)": -92.0,
    }
    assert resolve_coordinates(field) == (41.0, -91.0, "field_centroid")
    assert resolve_coordinates({}) == (None, None, "missing")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("no", "rainfed_confirmed"),
        (" NO ", "rainfed_confirmed"),
        ("yes", "irrigated_confirmed"),
        ("Yes", "irrigated_confirmed"),
        ("", "unknown"),
        (None, "unknown"),
        ("supplemental", "unknown"),
    ],
)
def test_irrigation_normalization_preserves_uncertainty(
    raw: object, expected: str
) -> None:
    assert normalize_irrigation(raw) == expected


def test_severe_issue_rule_flags_non_modelled_plot_damage() -> None:
    assert classify_severe_issue(["Hogs damaged plots throughout the field"])
    assert not classify_severe_issue(
        [
            "Field was harvested before traits were measured; "
            "lodging not reported as an issue in any plots by technician"
        ]
    )
    assert not classify_severe_issue(
        [
            "Field was harvested before plant traits (Plant Height, Ear Height, "
            "Stand Count, Root Lodging, Stalk Lodging) could be measured, lodging "
            "not reported as an issue in any plots by technician who harvested trial"
        ]
    )
    assert classify_severe_issue(
        [
            "Lodging not reported as an issue in any plots | "
            "planter error affected pass 3"
        ]
    )
    assert not classify_severe_issue(
        ["Additional weather data are available from the university station"]
    )


def test_soil_profiles_use_modal_texture_tie_break_and_default_provenance() -> None:
    environments = pd.DataFrame(
        [{"environment_id": "A_2022"}, {"environment_id": "B_2022"}]
    )
    samples = pd.DataFrame(
        [
            {"environment_id": "A_2022", "texture": "Sandy Loam"},
            {"environment_id": "A_2022", "texture": "Clay Loam"},
            {"environment_id": "B_2022", "texture": "not classified"},
        ]
    )

    profiles = derive_soil_profiles(
        environments, samples, default_texture="Loam"
    ).set_index("environment_id")

    assert profiles.loc["A_2022", "texture"] == "Clay Loam"
    assert profiles.loc["A_2022", "aquacrop_soil_type"] == "ClayLoam"
    assert profiles.loc["A_2022", "profile_source"] == "texture_lookup"
    assert bool(profiles.loc["A_2022", "texture_conflict"]) is True
    assert profiles.loc["B_2022", "texture"] == "Loam"
    assert profiles.loc["B_2022", "profile_source"] == "default"
    assert bool(profiles.loc["B_2022", "texture_conflict"]) is False


def test_soil_profiles_include_default_category_in_modal_selection() -> None:
    environments = pd.DataFrame([{"environment_id": "A_2022"}])
    samples = pd.DataFrame(
        [
            {"environment_id": "A_2022", "texture": "Clay"},
            {"environment_id": "A_2022", "texture": None},
            {"environment_id": "A_2022", "texture": "unrecognized"},
        ]
    )

    profile = derive_soil_profiles(environments, samples, default_texture="Loam").iloc[
        0
    ]

    assert profile["texture"] == "Loam"
    assert profile["profile_source"] == "default"
    assert bool(profile["texture_conflict"]) is True
    assert json.loads(profile["sample_texture_categories"]) == [
        "Clay",
        "Loam",
        "Loam",
    ]


@pytest.mark.parametrize(
    ("sand", "clay", "expected"),
    [
        (40, 20, "Loam"),
        (65, 10, "Sandy Loam"),
        (20, 40, "Clay Loam"),
        (10, 45, "Silty Clay"),
        (90, 5, "Sand"),
    ],
)
def test_usda_texture_triangle_maps_particle_fractions(sand, clay, expected) -> None:
    assert classify_usda_texture(sand, clay) == expected


def test_usda_texture_triangle_requires_valid_fractions() -> None:
    with pytest.raises(DataPreparationError):
        classify_usda_texture(80, 30)


def test_soil_profiles_use_particle_fractions_before_texture_labels() -> None:
    environments = pd.DataFrame(
        [{"environment_id": "A_2022"}, {"environment_id": "B_2022"}]
    )
    samples = pd.DataFrame(
        [
            {
                "environment_id": "A_2022",
                "texture": "Loam",
                "sand_percent": 65,
                "silt_percent": 25,
                "clay_percent": 10,
                "soil_ph": 6.2,
                "raw_sample_depth": 12,
            },
            {
                "environment_id": "B_2022",
                "texture": "Loam",
                "sand_percent": 40,
                "silt_percent": 40,
                "clay_percent": 20,
            },
        ]
    )

    profiles = derive_soil_profiles(
        environments, samples, default_texture="Loam"
    ).set_index("environment_id")

    assert profiles.loc["A_2022", "texture"] == "Sandy Loam"
    assert profiles.loc["A_2022", "aquacrop_soil_type"] == "SandyLoam"
    assert profiles.loc["A_2022", "profile_source"] == "particle_fractions"
    assert profiles.loc["A_2022", "particle_fraction_sample_count"] == 1
    assert profiles.loc["A_2022", "representative_depth_m"] == 0.12
    assert profiles.loc["A_2022", "representative_soil_ph"] == pytest.approx(6.2)
    assert profiles.loc["B_2022", "profile_source"] == "particle_fractions"
    assert pd.isna(profiles.loc["B_2022", "representative_depth_m"])


def test_management_density_uses_trimmed_median_and_default_fallback() -> None:
    units = pd.DataFrame(
        [
            {"management_unit_id": "a", "environment_id": "A_2022", "year": 2022},
            {"management_unit_id": "b", "environment_id": "B_2022", "year": 2022},
            {"management_unit_id": "c", "environment_id": "C_2022", "year": 2022},
        ]
    )
    plots = pd.DataFrame(
        [
            {
                "management_unit_id": "a",
                "environment_id": "A_2022",
                "stand_count_plants": 70,
                "plot_area_ha": 0.001,
            },
            {
                "management_unit_id": "a",
                "environment_id": "A_2022",
                "stand_count_plants": 90,
                "plot_area_ha": 0.001,
            },
            {
                "management_unit_id": "a",
                "environment_id": "A_2022",
                "stand_count_plants": 1,
                "plot_area_ha": 0.001,
            },
            {
                "management_unit_id": "b",
                "environment_id": "B_2022",
                "stand_count_plants": 80,
                "plot_area_ha": 0.001,
            },
            {
                "management_unit_id": "c",
                "environment_id": "C_2022",
                "stand_count_plants": None,
                "plot_area_ha": 0.001,
            },
        ]
    )

    result = add_density_to_management_units(
        units,
        plots,
        minimum_density=20000,
        maximum_density=160000,
        default_density=75000,
    ).set_index("management_unit_id")
    population_source = result["population_source"]

    assert result.loc["a", "population_plants_ha"] == pytest.approx(80000)
    assert population_source.loc["a"] == "plot_trimmed_median"
    assert result.loc["a", "population_source_count"] == 2
    assert result.loc["b", "population_plants_ha"] == pytest.approx(80000)
    assert result.loc["c", "population_plants_ha"] == pytest.approx(75000)
    assert population_source.loc["c"] == "default"


def test_eligibility_keeps_confirmed_irrigated_units_and_records_quality() -> None:
    config = _config(Path("/tmp/data"), Path("/tmp/outputs"))
    management_units = pd.DataFrame(
        [
            {
                "management_unit_id": "irrigated",
                "environment_id": "A_2022",
                "year": 2022,
                "planting_date": date(2022, 5, 1),
                "irrigation_status": "irrigated_confirmed",
                "population_source": "plot_trimmed_median",
                "population_source_count": 10,
            }
        ]
    )
    environments = pd.DataFrame(
        [
            {
                "environment_id": "A_2022",
                "latitude": 40.0,
                "longitude": -90.0,
                "irrigation_status": "irrigated_confirmed",
                "severe_issue": False,
            }
        ]
    )
    observations = pd.DataFrame(
        [
            {
                "management_unit_id": "irrigated",
                "variable": "pollen_dap",
                "value": 65.0,
            },
            {
                "management_unit_id": "irrigated",
                "variable": "yield_at_supplied_moisture_mg_ha",
                "value": 10.0,
            },
        ]
    )
    soil_profiles = pd.DataFrame(
        [
            {
                "environment_id": "A_2022",
                "profile_source": "particle_fractions",
                "texture_conflict": False,
            }
        ]
    )
    weather = {"A_2022": {"calendar_complete": True}}

    eligibility = evaluate_eligibility(
        config,
        management_units,
        environments,
        observations,
        soil_profiles,
        weather,
    )

    row = eligibility.set_index("management_unit_id").loc["irrigated"]
    assert bool(row["calibration_eligible"]) is True
    assert row["irrigation_assumption"] == "irrigated_confirmed"
    assert row["population_source"] == "plot_trimmed_median"
    assert row["soil_profile_source"] == "particle_fractions"
    assert row["data_quality"] == "high"


def test_eligibility_separates_calibration_and_evaluation_years() -> None:
    config = _config(Path("/tmp/data"), Path("/tmp/outputs"))
    management_units = pd.DataFrame(
        [
            {
                "management_unit_id": "evaluation",
                "environment_id": "B_2024",
                "year": 2024,
                "planting_date": date(2024, 5, 1),
                "irrigation_status": "rainfed_confirmed",
            }
        ]
    )
    environments = pd.DataFrame(
        [
            {
                "environment_id": "B_2024",
                "latitude": 40.0,
                "longitude": -90.0,
                "irrigation_status": "rainfed_confirmed",
                "severe_issue": False,
            }
        ]
    )
    observations = pd.DataFrame(
        [
            {
                "management_unit_id": "evaluation",
                "variable": "pollen_dap",
                "value": 65.0,
            },
            {
                "management_unit_id": "evaluation",
                "variable": "yield_at_supplied_moisture_mg_ha",
                "value": 10.0,
            },
        ]
    )
    soil_profiles = pd.DataFrame(
        [
            {
                "environment_id": "B_2024",
                "profile_source": "particle_fractions",
                "texture_conflict": False,
            }
        ]
    )

    eligibility = evaluate_eligibility(
        config,
        management_units,
        environments,
        observations,
        soil_profiles,
        {"B_2024": {"calendar_complete": True}},
    )

    row = eligibility.set_index("management_unit_id").loc["evaluation"]
    assert bool(row["calibration_eligible"]) is False
    assert bool(row["evaluation_eligible"]) is True
    assert json.loads(row["calibration_reason_codes"]) == ["not_calibration_year"]
    assert json.loads(row["evaluation_reason_codes"]) == []


def test_representative_maize_weights_hybrid_means_equally() -> None:
    plots = pd.DataFrame(
        [
            {
                "management_unit_id": "unit",
                "hybrid": "A",
                "pollen_dap_days": 60.0,
                "silk_dap_days": 62.0,
                "yield_mg_ha": 2.0,
                "harvest_date": date(2022, 10, 1),
            },
            {
                "management_unit_id": "unit",
                "hybrid": "A",
                "pollen_dap_days": 64.0,
                "silk_dap_days": 66.0,
                "yield_mg_ha": 4.0,
                "harvest_date": date(2022, 10, 3),
            },
            {
                "management_unit_id": "unit",
                "hybrid": "B",
                "pollen_dap_days": 70.0,
                "silk_dap_days": 72.0,
                "yield_mg_ha": 10.0,
                "harvest_date": date(2022, 10, 5),
            },
        ]
    )

    observations = aggregate_representative_maize(
        plots, grain_standard_moisture_fraction=0.155
    ).set_index("variable")

    assert observations.loc["pollen_dap", "value"] == pytest.approx(66.0)
    assert observations.loc["silk_dap", "value"] == pytest.approx(68.0)
    assert observations.loc["yield_at_supplied_moisture_mg_ha", "value"] == (
        pytest.approx(6.5)
    )
    assert observations.loc["dry_yield_mg_ha", "value"] == pytest.approx(6.5 * 0.845)
    assert observations.loc["observed_harvest_date", "observed_date"] == date(
        2022, 10, 4
    )
    assert observations.loc["yield_at_supplied_moisture_mg_ha", "source_row_count"] == 3
    assert observations.loc["yield_at_supplied_moisture_mg_ha", "hybrid_count"] == 2


def test_weather_audit_detects_calendar_end_and_core_gaps() -> None:
    complete = pd.DataFrame(_weather_rows("IAH1_2023", 2023))
    incomplete = pd.DataFrame(_weather_rows("IAH1_2024", 2024)[:315])
    incomplete.loc[
        incomplete["Date"].isin([20240712, 20240713, 20240714]), "RH2M"
    ] = -999

    audit = audit_weather_coverage(pd.concat([complete, incomplete]))

    assert audit["IAH1_2023"]["calendar_complete"] is True
    assert audit["IAH1_2024"]["calendar_complete"] is False
    assert audit["IAH1_2024"]["last_date"] == "2024-11-10"
    assert audit["IAH1_2024"]["core_gap_dates"] == [
        "2024-07-12",
        "2024-07-13",
        "2024-07-14",
    ]


def test_prepare_writes_complete_atomic_stable_artifact_set(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "outputs"
    _write_fixture_data(data_dir)
    config = _config(data_dir, output_dir)

    first = prepare_g2f(config)
    manifest_path = config.experiment_dir / "manifests/prepare_manifest.json"
    first_manifest = manifest_path.read_bytes()
    second = prepare_g2f(config)

    assert isinstance(first, PreparationResult)
    assert {
        str(path.relative_to(config.experiment_dir))
        for path in first.generated_artifacts
    } == EXPECTED_ARTIFACTS
    assert first.counts["training_plot_rows"] == 4
    assert first.counts["training_management_units"] == 1
    assert first.counts["testing_environments"] == 1
    assert first.calibration_eligible_management_unit_ids == (
        "IAH1_2022__EXP_A__2022-05-01",
    )
    assert second.generated_artifacts == first.generated_artifacts
    assert manifest_path.read_bytes() == first_manifest
    assert not list(config.experiment_dir.rglob("*.tmp-*"))

    manifest = json.loads(first_manifest)
    assert manifest["schema_version"] == "g2f-normalized-v1"
    assert set(manifest["sources"]) == {
        "testing_ec",
        "testing_metadata",
        "testing_observations",
        "testing_soil",
        "testing_template",
        "testing_weather",
        "testing_weather_seasons_only",
        "training_ec",
        "training_metadata",
        "training_soil",
        "training_traits",
        "training_weather",
        "training_weather_seasons_only",
    }
    for name in (
        "training_weather_seasons_only",
        "testing_weather_seasons_only",
        "training_ec",
        "testing_ec",
    ):
        assert manifest["sources"][name]["role"] == "excluded_from_model_inputs"
    assert manifest["producer"]["name"] == "snowwindow"
    assert manifest["producer"]["version"]
    assert manifest["runtime"] == {
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "pyarrow": pyarrow.__version__,
    }
    assert set(manifest["artifacts"]) == EXPECTED_ARTIFACTS - {
        "manifests/prepare_manifest.json"
    }
    assert manifest["assumptions"]["grain_standard_moisture_fraction"] == 0.155
    assert manifest["assumptions"]["default_soil_texture"] == "Loam"
    assert (
        manifest["assumptions"]["representative_maize"]
        == "mean valid plots within hybrid, then mean hybrid means equally"
    )

    plots = pd.read_parquet(
        config.experiment_dir / "normalized/plot_observations.parquet"
    )
    environments = pd.read_parquet(
        config.experiment_dir / "normalized/environments.parquet"
    )
    assert (
        environments.set_index("environment_id").loc["IAH1_2022", "field_location"]
        == "IAH1"
    )
    missing_test = plots.loc[
        plots["source_split"].eq("testing") & plots["hybrid"].eq("B"),
        "yield_mg_ha",
    ]
    assert missing_test.isna().all()
    assert plots["source_row_number"].min() == 1

    audit = json.loads((config.experiment_dir / "audit/data_audit.json").read_text())
    assert audit["source_exclusion_counts"] == {"planting_date_missing": 1}
    assert audit["source_exclusions"] == [
        {
            "environment_id": "IAH1_2022",
            "reason": "planting_date_missing",
            "source_filename": ("Training_data/1_Training_Trait_Data_2014_2023.csv"),
            "source_row_number": 4,
        }
    ]
    for name in (
        "training_weather_seasons_only",
        "testing_weather_seasons_only",
        "training_ec",
        "testing_ec",
    ):
        assert audit["source_inventory"][name]["role"] == "excluded_from_model_inputs"

    eligibility = pd.read_parquet(
        config.experiment_dir / "audit/eligibility.parquet"
    ).set_index("management_unit_id")
    training_unit = eligibility.loc["IAH1_2022__EXP_A__2022-05-01"]
    assert bool(training_unit["scan_eligible"]) is False
    assert "crossyear_weather_missing" in json.loads(training_unit["scan_reason_codes"])


def test_crossyear_scan_uses_only_explicit_continuation_mapping(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    _write_fixture_data(data_dir)

    without_mapping = prepare_g2f(_config(data_dir, tmp_path / "without"))
    assert (
        "IAH1_2022__EXP_A__2022-05-01"
        not in without_mapping.scan_eligible_management_unit_ids
    )

    with_mapping = prepare_g2f(
        _config(
            data_dir,
            tmp_path / "with",
            simulation_options={
                "scan_horizon": "cross_year",
                "continuation_weather_by_environment": {"IAH1_2022": "IAH1_2023"},
            },
        )
    )
    assert (
        "IAH1_2022__EXP_A__2022-05-01" in with_mapping.scan_eligible_management_unit_ids
    )


def test_minimal_cli_pipeline_keeps_inputs_and_failed_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise real stages with synthetic inputs and a deterministic adapter."""
    data_dir = tmp_path / "inputs"
    _write_fixture_data(data_dir)
    original_inputs = {
        path: path.read_bytes() for path in data_dir.rglob("*.csv")
    }
    config_path = tmp_path / "pipeline.yaml"
    document = {
        "experiment_id": "pipeline",
        "data_dir": "inputs",
        "output_dir": "custom-results",
        "model": {"name": "aquacrop", "parameters": {}},
        "selection": {
            "calibration_years": [2022],
            "evaluation_years": [2024],
            "environments": ["IAH1_2022", "IAH1_2024"],
            "allow_assumed_rainfed": True,
            "exclude_default_soil_from_calibration": False,
        },
        "calibration": {
            "phenology_grid": [0.9, 1.1, 0.1],
            "phenology_fine_step": 0.1,
            "yield_grid": [0.4, 0.5, 0.1],
            "yield_fine_step": 0.1,
        },
        "simulation": {
            "scan_fractions": [0.95],
            "workers": 1,
            "scan_all_dates": True,
            "parameter_sets": {
                "default": {},
                "calibrated": {"source": "calibration"},
            },
            "forecast_radius_days": 1,
        },
    }
    config_path.write_text(yaml.safe_dump(document), encoding="utf-8")

    class FixtureAdapter:
        name = "fixture"
        version = "1"
        capabilities = ModelCapabilities(display_name="Fixture model")

        def run(self, request: SimulationRequest) -> SimulationResult:
            failed = request.management.planting_date.day == 3
            return SimulationResult(
                request_id=request.request_id,
                adapter_name=self.name,
                adapter_version=self.version,
                status=RunStatus.NOT_MATURED if failed else RunStatus.MATURED,
                summary={
                    "simulation_end_date": "2025-04-30",
                    "flowering_proxy_dap": (
                        None
                        if failed
                        else 62.0
                        * float(request.model_parameters.get("phenology_scale", 1.0))
                    ),
                    "dry_yield_mg_ha": (
                        None
                        if failed
                        else 8.0 * float(request.model_parameters.get("HI0", 0.48))
                    ),
                },
                failure_reason="synthetic non-maturity" if failed else None,
            )

    adapter = FixtureAdapter()
    for module in ("stages", "scan", "forecast"):
        monkeypatch.setattr(
            f"snowwindow.{module}.resolve_model_adapter", lambda config: adapter
        )
    monkeypatch.setattr(
        "snowwindow.scan.calendar_dates",
        lambda year: tuple(date(year, 5, day) for day in (1, 2, 3)),
    )
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "custom-results"
    root = output / "experiments/pipeline"
    assert main(["audit", "--config", str(config_path)]) == 0
    assert not output.exists()
    for stage in (
        "prepare", "baseline", "calibrate", "validate", "scan", "report", "run"
    ):
        assert main([stage, "--config", str(config_path)]) == 0, stage
    assert not (root / "forecast").exists(), "run must not implicitly forecast"
    assert (root / "config.yaml").is_file()
    assert (root / "report/report.md").is_file()
    baseline = pd.read_parquet(root / "baseline/summary.parquet")
    assert pd.to_datetime(baseline["simulation_end_date"]).le(
        pd.Timestamp("2024-11-10")
    ).all()
    parameters = pd.read_parquet(root / "calibration/parameters.parquet")
    held = parameters.loc[parameters["fold"].eq("held_year")].iloc[0]
    assert all("2022" in unit for unit in json.loads(held["train_ids"]))
    assert all("2024" in unit for unit in json.loads(held["test_ids"]))
    summary = pd.read_parquet(root / "scan/summary.parquet")
    failed = summary.loc[summary["status"].eq("not_matured")]
    assert len(summary) == 12
    assert len(failed) == 4
    assert pd.to_datetime(summary["simulation_end_date"]).le(
        pd.Timestamp("2024-11-10")
    ).all()
    scan_manifest = json.loads((root / "scan/manifest.json").read_text())
    assert scan_manifest["weather_source"] == "G2F full-year weather"
    assert scan_manifest["weather_policy"]["end_date"] == "2024-11-10"
    assert failed["failure_reason"].eq("synthetic non-maturity").all()
    assert failed["dry_yield_mg_ha"].isna().all()

    document["experiment_id"] = "pipeline_forecast"
    document["selection"]["source_experiment_id"] = "pipeline"
    forecast_config = tmp_path / "forecast.yaml"
    forecast_config.write_text(yaml.safe_dump(document), encoding="utf-8")
    assert main(["forecast", "--config", str(forecast_config)]) == 0
    forecast_root = output / "experiments/pipeline_forecast/forecast"
    scenarios = pd.read_parquet(forecast_root / "scenario_results.parquet")
    assert len(scenarios) == 6
    assert scenarios["status"].eq("not_matured").sum() == 2
    assert pd.to_datetime(scenarios["simulation_end_date"]).le(
        pd.Timestamp("2024-11-10")
    ).all()
    assert (forecast_root / "report.md").is_file()
    assert main(["catalog", "--config", str(forecast_config)]) == 0
    catalog = json.loads((output / "experiments/catalog.json").read_text())
    assert {entry["experiment_id"] for entry in catalog} == {
        "pipeline", "pipeline_forecast"
    }
    assert not (tmp_path / "outputs").exists()
    assert {
        path: path.read_bytes() for path in data_dir.rglob("*.csv")
    } == original_inputs


@pytest.mark.integration
def test_real_data_audit_measures_known_g2f_coverage(tmp_path: Path) -> None:
    if not (Path("data") / "Training_data").is_dir():
        pytest.skip("local G2F data are not distributed with the repository")
    config = _config(Path("data").resolve(), tmp_path / "unused-output")

    audit = audit_g2f(config)

    assert not config.experiment_dir.exists()
    assert audit["counts"]["training_plot_rows"] == 173_960
    assert audit["counts"]["training_environments"] == 272
    assert audit["counts"]["testing_environments"] == 23
    assert audit["counts"]["training_management_units"] == 418
    assert audit["source_exclusion_counts"]["planting_date_missing"] == 363
    assert audit["weather"]["training_missing_environments"] == [
        "TXH2_2015",
        "TXH2_2016",
        "TXH2_2017",
    ]
    assert audit["weather"]["testing_environment_count_ending_2024_11_10"] == 23
    assert audit["weather"]["testing_core_gap_dates"] == [
        "2024-07-12",
        "2024-07-13",
        "2024-07-14",
    ]
