from __future__ import annotations

import json
from dataclasses import replace
from datetime import date

import pandas as pd
import pytest

from snowwindow.calibration import (
    apply_site_offsets,
    compute_metrics,
    freeze_observation_set,
    make_validation_folds,
    parameter_grid,
    refined_grid,
    run_two_stage_calibration,
    select_parameter,
    validate_parameter_sets,
)
from snowwindow.domain import (
    Environment,
    ManagementUnit,
    RunStatus,
    SimulationRequest,
    SimulationResult,
)
from snowwindow.experiment import build_simulation_request, select_representative_units


def test_parameter_grid_is_decimal_stable_and_inclusive() -> None:
    assert parameter_grid(0.8, 0.82, 0.01) == (0.8, 0.81, 0.82)
    assert refined_grid(0.8, lower=0.8, upper=1.2, radius=0.02, step=0.005) == (
        0.8,
        0.805,
        0.81,
        0.815,
        0.82,
    )


def test_select_parameter_rejects_incomplete_candidates_and_breaks_ties() -> None:
    rows = pd.DataFrame(
        [
            ("a", 0.9, "matured", 9.0, 10.0),
            ("b", 0.9, "matured", 19.0, 20.0),
            ("a", 1.0, "matured", 11.0, 10.0),
            ("b", 1.0, "matured", 19.0, 20.0),
            ("a", 1.1, "matured", 11.0, 10.0),
            ("b", 1.1, "matured", 21.0, 20.0),
        ],
        columns=[
            "observation_id",
            "phenology_scale",
            "status",
            "predicted_value",
            "observed_value",
        ],
    )

    selected, scores = select_parameter(
        rows,
        parameter_name="phenology_scale",
        default=1.0,
        expected_observation_ids=("a", "b"),
    )

    assert selected == 1.0
    assert scores.set_index("phenology_scale").loc[1.0, "valid"] == True  # noqa: E712
    assert scores.set_index("phenology_scale").loc[1.1, "valid"] == True  # noqa: E712


def test_compute_metrics_uses_fixed_denominator_for_coverage() -> None:
    predictions = pd.DataFrame(
        {
            "status": ["matured", "not_matured", "matured"],
            "observed_value": [10.0, 20.0, 30.0],
            "predicted_value": [12.0, None, 27.0],
        }
    )

    metrics = compute_metrics(predictions, expected_count=3)

    assert metrics["n"] == 2
    assert metrics["coverage"] == pytest.approx(2 / 3)
    assert metrics["mae"] == 2.5
    assert metrics["rmse"] == pytest.approx((6.5) ** 0.5)
    assert metrics["bias"] == -0.5


def test_freeze_observation_set_uses_only_eligible_calibration_years() -> None:
    units = pd.DataFrame(
        [
            {"management_unit_id": "u22", "environment_id": "A_2022", "year": 2022},
            {"management_unit_id": "u23", "environment_id": "A_2023", "year": 2023},
        ]
    )
    observations = pd.DataFrame(
        [
            {"management_unit_id": unit, "variable": variable, "value": value}
            for unit, year in (("u22", 2022), ("u23", 2023))
            for variable, value in (
                ("pollen_dap", 60 + year % 10),
                ("dry_yield_mg_ha", 8.0),
            )
        ]
    )
    eligibility = pd.DataFrame(
        [
            {"management_unit_id": "u22", "calibration_eligible": True},
            {"management_unit_id": "u23", "calibration_eligible": True},
        ]
    )

    frozen = freeze_observation_set(
        units,
        observations,
        eligibility,
        calibration_years=(2022,),
    )

    assert set(frozen["management_unit_id"]) == {"u22"}
    assert set(frozen["variable"]) == {"pollen_dap", "dry_yield_mg_ha"}
    assert frozen["observation_id"].is_unique


def test_validation_folds_keep_evaluation_year_out_of_training() -> None:
    units = pd.DataFrame(
        [
            {"management_unit_id": "a22", "environment_id": "A_2022", "year": 2022},
            {"management_unit_id": "b22", "environment_id": "B_2022", "year": 2022},
            {"management_unit_id": "a23", "environment_id": "A_2023", "year": 2023},
        ]
    )

    folds = make_validation_folds(
        units, calibration_years=(2022,), evaluation_years=(2023,)
    )

    held = next(fold for fold in folds if fold["name"] == "held_year")
    assert held["train_ids"] == ("a22", "b22")
    assert held["test_ids"] == ("a23",)
    assert all("a23" not in fold["train_ids"] for fold in folds)


def test_representative_unit_is_largest_experiment_without_using_yield() -> None:
    units = pd.DataFrame(
        [
            {
                "management_unit_id": "small",
                "environment_id": "A_2022",
                "experiment": "A",
                "plot_count": 20,
            },
            {
                "management_unit_id": "large",
                "environment_id": "A_2022",
                "experiment": "B",
                "plot_count": 500,
            },
        ]
    )

    selected = select_representative_units(units, ("A_2022",))

    assert selected["management_unit_id"].tolist() == ["large"]
    assert select_representative_units(units, ())["management_unit_id"].tolist() == [
        "large"
    ]


def test_build_request_uses_full_cross_year_weather_and_profile() -> None:
    planting = date(2023, 12, 31)
    dates = pd.date_range("2023-01-01", "2024-12-30")
    weather = pd.DataFrame(
        {
            "date": dates.date,
            "T2M_MIN": 10.0,
            "T2M_MAX": 20.0,
            "PRECTOTCORR": 0.0,
            "RH2M": 60.0,
            "WS2M": 2.0,
            "PS": 100.0,
            "ALLSKY_SFC_SW_DWN": 15.0,
        }
    )

    request = build_simulation_request(
        {
            "management_unit_id": "u",
            "environment_id": "A_2023",
            "planting_date": planting,
            "irrigation_status": "rainfed_confirmed",
            "population_plants_ha": 74_000.0,
        },
        {
            "environment_id": "A_2023",
            "year": 2023,
            "field_location": "A",
            "latitude": 40.0,
            "longitude": -90.0,
        },
        {"aquacrop_soil_type": "Loam", "profile_source": "observed"},
        weather,
        parameter_set_id="default",
        model_parameters={},
    )

    assert request.start_date == date(2023, 1, 1)
    assert request.end_date == date(2024, 4, 30)
    assert len(request.environment.weather) == 486
    assert request.environment.soil[0].bottom_depth_m == 2.0
    assert request.management.population_plants_m2 == pytest.approx(7.4)


def test_build_request_supports_apsim_fixed_day_horizon() -> None:
    planting = date(2022, 5, 12)
    dates = pd.date_range("2022-01-01", "2023-05-12")
    weather = pd.DataFrame(
        {
            "date": dates.date,
            "T2M_MIN": 10.0,
            "T2M_MAX": 20.0,
            "PRECTOTCORR": 0.0,
            "RH2M": 60.0,
            "WS2M": 2.0,
            "PS": 100.0,
            "ALLSKY_SFC_SW_DWN": 15.0,
        }
    )

    request = build_simulation_request(
        {
            "management_unit_id": "u",
            "environment_id": "A_2022",
            "planting_date": planting,
            "irrigation_status": "rainfed_confirmed",
        },
        {
            "environment_id": "A_2022",
            "year": 2022,
            "field_location": "A",
            "latitude": 40.0,
            "longitude": -90.0,
        },
        {"aquacrop_soil_type": "Loam", "profile_source": "fixed"},
        weather,
        parameter_set_id="default",
        model_parameters={"simulation_horizon_days": 365},
    )

    assert request.end_date == date(2023, 5, 12)
    assert len(request.environment.weather) == 497


class _FakeAdapter:
    name = "fake"
    version = "1"

    def validate(self, request: SimulationRequest) -> None:
        return None

    def run(self, request: SimulationRequest) -> SimulationResult:
        scale = float(request.model_parameters.get("phenology_scale", 1.0)) * float(
            request.model_parameters.get("phenology_scale_site", 1.0)
        )
        hi0 = float(request.model_parameters.get("HI0", 0.48)) * float(
            request.model_parameters.get("HI0_site", 1.0)
        )
        return SimulationResult(
            request_id=request.request_id,
            adapter_name=self.name,
            adapter_version=self.version,
            status=RunStatus.MATURED,
            summary={
                "flowering_proxy_dap": 60.0 + (scale - 0.9) * 100,
                "dry_yield_mg_ha": 8.0 + (hi0 - 0.4) * 10,
            },
        )


class _FakeAPSIMAdapter:
    name = "apsim"
    version = "1"

    def validate(self, request: SimulationRequest) -> None:
        return None

    def run(self, request: SimulationRequest) -> SimulationResult:
        juvenile = float(request.model_parameters.get("juvenile_tt", 211.0))
        grain_scale = float(request.model_parameters.get("grain_number_scale", 1.0))
        return SimulationResult(
            request_id=request.request_id,
            adapter_name=self.name,
            adapter_version=self.version,
            status=RunStatus.MATURED,
            summary={
                "flowering_proxy_dap": juvenile / 4,
                "dry_yield_mg_ha": grain_scale * 8,
            },
        )


def _request(unit_id: str, year: int) -> SimulationRequest:
    environment_id = f"A_{year}"
    planting = date(year, 5, 1)
    return SimulationRequest(
        request_id=unit_id,
        environment=Environment(
            environment_id=environment_id,
            year=year,
            location="A",
            latitude=40.0,
            longitude=-90.0,
        ),
        management=ManagementUnit(
            management_unit_id=unit_id,
            environment_id=environment_id,
            planting_date=planting,
        ),
        start_date=date(year, 1, 1),
        end_date=date(year + 1, 4, 30),
    )


def test_held_year_fold_includes_evaluation_environment_test_units() -> None:
    units = pd.DataFrame(
        [
            {
                "management_unit_id": "u22",
                "environment_id": "A_2022",
                "year": 2022,
            },
            {
                "management_unit_id": "u23",
                "environment_id": "A_2023",
                "year": 2023,
            },
        ]
    )

    folds = make_validation_folds(
        units,
        calibration_years=(2022,),
        evaluation_years=(2023,),
    )
    held_year = next(fold for fold in folds if fold["name"] == "held_year")

    assert held_year["train_ids"] == ("u22",)
    assert held_year["test_ids"] == ("u23",)


def test_two_stage_calibration_does_not_use_evaluation_labels() -> None:
    observations = pd.DataFrame(
        [
            {
                "observation_id": f"{unit}::{variable}",
                "management_unit_id": unit,
                "variable": variable,
                "value": value,
            }
            for unit, values in {
                "u22": (60.0, 8.0),
                "u23": (999.0, 999.0),
            }.items()
            for variable, value in zip(("pollen_dap", "dry_yield_mg_ha"), values)
        ]
    )
    requests = {"u22": _request("u22", 2022), "u23": _request("u23", 2023)}

    first = run_two_stage_calibration(
        _FakeAdapter(),
        requests,
        observations,
        training_ids=("u22",),
        phenology_values=(0.9, 1.0),
        hi0_values=(0.4, 0.5),
        default_phenology=1.0,
        default_hi0=0.48,
    )
    changed = observations.copy()
    changed.loc[changed["management_unit_id"].eq("u23"), "value"] = -5000
    second = run_two_stage_calibration(
        _FakeAdapter(),
        requests,
        changed,
        training_ids=("u22",),
        phenology_values=(0.9, 1.0),
        hi0_values=(0.4, 0.5),
        default_phenology=1.0,
        default_hi0=0.48,
    )

    assert (
        first.parameters
        == second.parameters
        == {
            "phenology_scale": 0.9,
            "HI0": 0.4,
        }
    )
    pd.testing.assert_frame_equal(first.search, second.search)


def test_two_stage_calibration_supports_model_specific_parameter_names() -> None:
    observations = pd.DataFrame(
        [
            {
                "observation_id": f"u22::{variable}",
                "management_unit_id": "u22",
                "variable": variable,
                "value": value,
            }
            for variable, value in (
                ("pollen_dap", 50.0),
                ("dry_yield_mg_ha", 9.6),
            )
        ]
    )

    result = run_two_stage_calibration(
        _FakeAPSIMAdapter(),
        {"u22": _request("u22", 2022)},
        observations,
        training_ids=("u22",),
        phenology_values=(200.0, 225.0),
        hi0_values=(1.0, 1.2),
        default_phenology=211.0,
        default_hi0=1.0,
        phenology_parameter_name="juvenile_tt",
        yield_parameter_name="grain_number_scale",
    )

    assert result.parameters == {
        "juvenile_tt": 200.0,
        "grain_number_scale": 1.2,
    }


def test_validation_preserves_abnormal_rows_and_fixed_coverage() -> None:
    observations = pd.DataFrame(
        [
            {
                "observation_id": f"u22::{variable}",
                "management_unit_id": "u22",
                "variable": variable,
                "value": value,
            }
            for variable, value in (("pollen_dap", 60.0), ("dry_yield_mg_ha", 8.0))
        ]
    )

    predictions, metrics = validate_parameter_sets(
        _FakeAdapter(),
        {"u22": _request("u22", 2022)},
        observations,
        fold_name="held_year",
        split_by_unit={"u22": "train"},
        parameter_sets={"default": {}, "calibrated": {"phenology_scale": 0.9}},
    )

    assert len(predictions) == 4
    assert set(metrics["coverage"]) == {1.0}
    assert {
        "observation_id",
        "site",
        "residual",
        "request_id",
    }.issubset(predictions.columns)


def test_site_offsets_use_only_sites_with_minimum_training_years() -> None:
    observations = pd.DataFrame(
        [
            {
                "observation_id": f"{unit}::{variable}",
                "management_unit_id": unit,
                "environment_id": env,
                "year": year,
                "variable": variable,
                "value": value,
            }
            for unit, env, year, values in (
                ("a1", "A_2020", 2020, (60.0, 8.0)),
                ("a2", "A_2021", 2021, (61.0, 9.0)),
                ("a3", "A_2022", 2022, (62.0, 10.0)),
                ("b1", "B_2022", 2022, (70.0, 12.0)),
            )
            for variable, value in zip(("pollen_dap", "dry_yield_mg_ha"), values)
        ]
    )
    predictions = pd.DataFrame(
        {
            "management_unit_id": ["a1", "a1", "a2", "a2", "a3", "a3"],
            "environment_id": [
                "A_2020",
                "A_2020",
                "A_2021",
                "A_2021",
                "A_2022",
                "A_2022",
            ],
            "year": [2020, 2020, 2021, 2021, 2022, 2022],
            "parameter_set_id": ["global"] * 6,
            "variable": [
                "dry_yield_mg_ha",
                "pollen_dap",
                "dry_yield_mg_ha",
                "pollen_dap",
                "dry_yield_mg_ha",
                "pollen_dap",
            ],
            "status": ["matured"] * 6,
            "observed_value": [60.0, 60.0, 61.0, 61.0, 62.0, 62.0],
            "predicted_value": [62.0, 61.0, 63.0, 61.0, 64.0, 61.0],
        }
    )

    result = apply_site_offsets(
        observations,
        predictions,
        parameter_set_id="global",
        site_parameter_set_id="site",
        minimum_training_years=3,
        maximum_scale=2.0,
    )

    assert set(result["site"]) == {"A"}
    offset = result[result["site"].eq("A")].iloc[0]
    assert offset["HI0_site"] == pytest.approx(
        float(pd.Series([60 / 62, 61 / 63, 62 / 64]).median())
    )
    assert offset["phenology_scale_site"] == pytest.approx(1.0)
    assert offset["training_years"] == 3
    assert offset["fold"] == "site_offset_A"
    assert json.loads(offset["train_ids"]) == ["a1", "a2", "a3"]


def test_validation_applies_site_overrides_by_site() -> None:
    observations = pd.DataFrame(
        [
            {
                "observation_id": f"{unit}::{variable}",
                "management_unit_id": unit,
                "variable": variable,
                "value": value,
            }
            for unit, values in (("a", (60.0, 8.0)), ("b", (60.0, 8.0)))
            for variable, value in zip(("pollen_dap", "dry_yield_mg_ha"), values)
        ]
    )
    requests = {unit: _request(unit, 2022) for unit in ("a", "b")}
    requests["b"] = replace(
        requests["b"],
        environment=replace(requests["b"].environment, environment_id="B_2022"),
    )

    predictions, _ = validate_parameter_sets(
        _FakeAdapter(),
        requests,
        observations,
        fold_name="held_year",
        split_by_unit={"a": "train", "b": "train"},
        parameter_sets={
            "site": {
                "phenology_scale": 0.9,
                "site_overrides": {
                    "A": {"phenology_scale_site": 1.2},
                    "B": {"HI0_site": 1.5},
                },
            }
        },
    )
    site_predictions = predictions.loc[
        predictions["parameter_set_id"].eq("site")
    ].set_index(["management_unit_id", "variable"])

    assert site_predictions.loc[("a", "pollen_dap"), "predicted_value"] == (
        pytest.approx(78.0)
    )
    assert site_predictions.loc[("b", "dry_yield_mg_ha"), "predicted_value"] == (
        pytest.approx(11.2)
    )
