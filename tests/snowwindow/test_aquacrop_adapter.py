from __future__ import annotations

import json
from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd
import pytest

from snowwindow.domain import (
    Environment,
    ManagementUnit,
    RunStatus,
    SimulationRequest,
    SoilLayer,
    WeatherRecord,
)
from snowwindow.models.aquacrop import (
    AquaCropAdapter,
    map_crop_state,
    map_exception_status,
    reference_et,
    simulation_end_for_planting,
)


def _weather_records(start: date, end: date) -> tuple[WeatherRecord, ...]:
    return tuple(
        WeatherRecord(
            environment_id="TEST_2023",
            date=timestamp.date(),
            values={
                "T2M_MIN": 15.0,
                "T2M_MAX": 28.0,
                "PRECTOTCORR": 1.0,
                "RH2M": 60.0,
                "WS2M": 2.0,
                "PS": 100.0,
                "ALLSKY_SFC_SW_DWN": 20.0,
            },
            source="synthetic",
        )
        for timestamp in pd.date_range(start, end)
    )


def _cold_weather_records(start: date, end: date) -> tuple[WeatherRecord, ...]:
    return tuple(
        WeatherRecord(
            environment_id="TEST_2023",
            date=timestamp.date(),
            values={
                "T2M_MIN": 0.0,
                "T2M_MAX": 5.0,
                "PRECTOTCORR": 1.0,
                "RH2M": 70.0,
                "WS2M": 2.0,
                "PS": 100.0,
                "ALLSKY_SFC_SW_DWN": 8.0,
            },
            source="synthetic-cold",
        )
        for timestamp in pd.date_range(start, end)
    )


def _request(
    *,
    planting_date: date = date(2023, 5, 10),
    output_dir=None,
    parameters=None,
) -> SimulationRequest:
    end_date, _ = simulation_end_for_planting(planting_date)
    return SimulationRequest(
        request_id="request-1",
        environment=Environment(
            environment_id="TEST_2023",
            year=2023,
            location="Test",
            latitude=40.0,
            longitude=-86.0,
            weather=_weather_records(date(2023, 1, 1), end_date),
            soil=(
                SoilLayer(
                    top_depth_m=0.0,
                    bottom_depth_m=2.0,
                    properties={"aquacrop_soil_type": "Loam"},
                    source="synthetic",
                ),
            ),
            metadata={"elevation_m": 200.0},
        ),
        management=ManagementUnit(
            management_unit_id="unit-1",
            environment_id="TEST_2023",
            planting_date=planting_date,
            population_plants_m2=7.5,
            irrigation_assumption="rainfed_confirmed",
        ),
        start_date=date(2023, 1, 1),
        end_date=end_date,
        model_parameters=parameters or {},
        output_dir=output_dir,
    )


def test_reference_et_preserves_raw_value_and_clips_only_model_input() -> None:
    weather = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-15", "2024-07-15"]),
            "T2M_MIN": [15.0, 15.0],
            "T2M_MAX": [25.0, 25.0],
            "RH2M": [100.0, 60.0],
            "WS2M": [0.0, 2.0],
            "PS": [100.0, 100.0],
            "ALLSKY_SFC_SW_DWN": [0.0, 22.0],
        }
    )

    result = reference_et(weather, latitude_deg=42.0, elevation_m=100.0)

    assert result.loc[0, "ET0_unclipped_mm_day"] < 0.1
    assert result.loc[0, "ReferenceET"] == 0.1
    assert result.loc[1, "ReferenceET"] > result.loc[0, "ReferenceET"]


def test_reference_et_increases_with_summer_radiation() -> None:
    weather = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-07-15", "2024-07-15"]),
            "T2M_MIN": [15.0, 15.0],
            "T2M_MAX": [25.0, 25.0],
            "RH2M": [60.0, 60.0],
            "WS2M": [2.0, 2.0],
            "PS": [100.0, 100.0],
            "ALLSKY_SFC_SW_DWN": [20.0, 22.0],
        }
    )

    result = reference_et(weather, latitude_deg=42.0, elevation_m=100.0)

    assert result.loc[1, "ET0_unclipped_mm_day"] > result.loc[0, "ET0_unclipped_mm_day"]


def test_cross_year_end_avoids_non_leap_recurring_february_29() -> None:
    end_date, adjusted = simulation_end_for_planting(date(2023, 3, 1))

    assert end_date == date(2024, 2, 28)
    assert adjusted is True
    assert simulation_end_for_planting(date(2023, 12, 31)) == (
        date(2024, 12, 30),
        False,
    )


def test_cache_key_excludes_output_location_and_save_daily(tmp_path) -> None:
    adapter = AquaCropAdapter()
    base = _request(output_dir=tmp_path / "one")
    daily = replace(
        base,
        output_dir=tmp_path / "two",
        model_parameters={"save_daily": True},
    )
    changed = replace(base, model_parameters={"HI0": 0.4})

    assert adapter.cache_key(base) == adapter.cache_key(daily)
    assert adapter.cache_key(changed) != adapter.cache_key(base)


def test_validate_accepts_supported_complete_request() -> None:
    AquaCropAdapter().validate(_request())


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda request: replace(
                request,
                model_parameters={"planting_date": "2023-05-11"},
            ),
            "planting date",
        ),
        (
            lambda request: replace(
                request,
                model_parameters={"model_version": "3.0.0"},
            ),
            "model version",
        ),
        (
            lambda request: replace(
                request,
                management=replace(
                    request.management,
                    irrigation_assumption="irrigated_confirmed",
                ),
            ),
            "rainfed",
        ),
        (
            lambda request: replace(
                request,
                environment=replace(
                    request.environment,
                    weather=request.environment.weather[:-1],
                ),
            ),
            "calendar day",
        ),
        (
            lambda request: replace(
                request,
                environment=replace(
                    request.environment,
                    weather=(
                        replace(
                            request.environment.weather[0],
                            values={
                                **request.environment.weather[0].values,
                                "RH2M": 101.0,
                            },
                        ),
                        *request.environment.weather[1:],
                    ),
                ),
            ),
            "weather",
        ),
        (
            lambda request: replace(
                request,
                model_parameters={"initial_available_water_pct": 101},
            ),
            "initial_available_water_pct",
        ),
        (
            lambda request: replace(
                request,
                model_parameters={"grain_standard_moisture_fraction": 1.0},
            ),
            "grain_standard_moisture_fraction",
        ),
    ],
)
def test_validate_rejects_unsupported_requests(mutate, message) -> None:
    with pytest.raises(ValueError, match=message):
        AquaCropAdapter().validate(mutate(_request()))


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            RuntimeError("not enough growing degree days in simulation"),
            RunStatus.INSUFFICIENT_THERMAL_TIME,
        ),
        (
            RuntimeError("crop will take longer than 1 year to mature"),
            RunStatus.MODEL_LIMIT,
        ),
        (RuntimeError("unexpected"), RunStatus.EXECUTION_FAILED),
    ],
)
def test_expected_aquacrop_errors_have_stable_statuses(error, expected) -> None:
    assert map_exception_status(error) is expected


@pytest.mark.parametrize(
    ("mature", "dead", "germinated", "expected"),
    [
        (True, False, True, RunStatus.MATURED),
        (False, True, True, RunStatus.CROP_DIED),
        (False, False, False, RunStatus.NOT_GERMINATED),
        (False, False, True, RunStatus.NOT_MATURED),
    ],
)
def test_aquacrop_crop_state_has_stable_status(
    mature, dead, germinated, expected
) -> None:
    assert map_crop_state(mature, dead, germinated) is expected


def test_run_returns_invalid_input_instead_of_raising() -> None:
    invalid = replace(_request(), model_parameters={"HI0": 2.0})

    result = AquaCropAdapter().run(invalid)

    assert result.status is RunStatus.INVALID_INPUT
    assert result.failure_reason
    assert result.summary == {}


@pytest.mark.integration
def test_bundled_aquacrop_smoke_example_runs() -> None:
    smoke = AquaCropAdapter().smoke()

    assert smoke["model_version"] == "3.1.0"
    assert np.isfinite(smoke["dry_yield_mg_ha"])


@pytest.mark.integration
def test_real_model_run_is_reproducible_and_writes_requested_artifacts(
    tmp_path,
) -> None:
    adapter = AquaCropAdapter()
    request = _request(
        output_dir=tmp_path,
        parameters={"save_daily": True},
    )

    first = adapter.run(request)
    second = adapter.run(request)

    assert first.status is second.status is RunStatus.MATURED
    assert first.summary["dry_yield_mg_ha"] == second.summary["dry_yield_mg_ha"]
    assert first.summary["requested_sowing_date"] == "2023-05-10"
    assert first.summary["actual_sowing_date"] == "2023-05-10"
    assert first.summary["crop"] == "MaizeGDD"
    assert first.summary["water_balance_max_abs_mm_day"] < 1e-7
    assert abs(first.summary["water_balance_total_residual_mm"]) < 1e-6
    assert first.summary["soil_water_bounds_ok"] is True
    assert first.summary["soil_profile_depth_m"] == 2.0
    assert first.summary["soil_compartment_m"] == 0.1
    assert first.summary["preplant_days_simulated"] == 129
    assert first.summary["flowering_proxy_note"] == (
        "first end-of-day crossing of HIstart; not an independent pollen event"
    )
    assert second.diagnostics["cache_hit"] is True
    assert set(first.artifacts) == {"summary", "daily", "crop", "soil"}
    assert all(path.exists() for path in first.artifacts.values())
    persisted = json.loads(first.artifacts["summary"].read_text())
    assert persisted["status"] == "matured"


@pytest.mark.integration
def test_missing_requested_daily_artifact_forces_rerun(tmp_path) -> None:
    adapter = AquaCropAdapter()
    without_daily = _request(output_dir=tmp_path)
    with_daily = replace(
        without_daily,
        model_parameters={"save_daily": True},
    )

    first = adapter.run(without_daily)
    second = adapter.run(with_daily)

    assert first.status is RunStatus.MATURED
    assert set(first.artifacts) == {"summary"}
    assert second.status is RunStatus.MATURED
    assert second.diagnostics["cache_hit"] is False
    assert set(second.artifacts) == {"summary", "daily", "crop", "soil"}


@pytest.mark.integration
def test_cached_scientific_result_uses_current_request_id(tmp_path) -> None:
    adapter = AquaCropAdapter()
    first = _request(output_dir=tmp_path)
    second = replace(first, request_id="request-2")

    adapter.run(first)
    result = adapter.run(second)

    assert result.diagnostics["cache_hit"] is True
    assert result.request_id == "request-2"


@pytest.mark.integration
def test_corrupt_cached_summary_is_recomputed(tmp_path) -> None:
    adapter = AquaCropAdapter()
    request = _request(output_dir=tmp_path)
    summary_path = tmp_path / "aquacrop" / f"{adapter.cache_key(request)}.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text("{not-json")

    result = adapter.run(request)

    assert result.status is RunStatus.MATURED
    assert result.diagnostics["cache_hit"] is False
    assert json.loads(summary_path.read_text())["status"] == "matured"


@pytest.mark.integration
def test_model_parameter_overrides_are_applied_together(tmp_path) -> None:
    parameters = {
        "phenology_scale": 0.9,
        "HI0": 0.4,
        "initial_available_water_pct": 40.0,
        "root_depth_scale": 0.7,
        "plant_population_ha": 80_000,
        "save_daily": True,
    }

    result = AquaCropAdapter().run(_request(output_dir=tmp_path, parameters=parameters))
    crop = json.loads(result.artifacts["crop"].read_text())

    assert result.status is RunStatus.MATURED
    assert result.summary["phenology_scale"] == 0.9
    assert result.summary["HI0"] == 0.4
    assert result.summary["initial_available_water_pct"] == 40.0
    assert result.summary["plant_population_ha"] == 80_000
    assert result.summary["effective_max_root_depth_m"] == pytest.approx(1.61)
    assert crop["Emergence"] == pytest.approx(72.0)
    assert crop["MaxRooting"] == pytest.approx(1268.1)
    assert crop["Senescence"] == pytest.approx(1260.0)
    assert crop["Maturity"] == pytest.approx(1530.0)
    assert crop["HIstart"] == pytest.approx(792.0)
    assert crop["Flowering"] == pytest.approx(162.0)
    assert crop["YldForm"] == pytest.approx(675.0)
    assert crop["HI0"] == 0.4
    assert crop["PlantPop"] == 80_000


@pytest.mark.integration
def test_artifact_write_failure_returns_execution_failed(tmp_path) -> None:
    blocked_output = tmp_path / "not-a-directory"
    blocked_output.write_text("occupied")

    result = AquaCropAdapter().run(_request(output_dir=blocked_output))

    assert result.status is RunStatus.EXECUTION_FAILED
    assert "NotADirectoryError" in result.diagnostics["traceback"]


@pytest.mark.integration
def test_preplant_water_path_is_shared_before_earliest_sowing(tmp_path) -> None:
    adapter = AquaCropAdapter()
    later = _request(
        output_dir=tmp_path,
        parameters={"save_daily": True},
    )
    earlier = _request(
        planting_date=date(2023, 4, 20),
        output_dir=tmp_path,
        parameters={"save_daily": True},
    )

    later_result = adapter.run(later)
    earlier_result = adapter.run(earlier)
    later_daily = pd.read_parquet(later_result.artifacts["daily"])
    earlier_daily = pd.read_parquet(earlier_result.artifacts["daily"])
    before = pd.Timestamp(earlier.management.planting_date)

    assert later_result.status is earlier_result.status is RunStatus.MATURED
    np.testing.assert_allclose(
        later_daily.loc[later_daily["Date"] < before, "soil_water_mm"],
        earlier_daily.loc[earlier_daily["Date"] < before, "soil_water_mm"],
        atol=1e-10,
    )
    assert later_result.summary["preplant_soil_water_range_mm"] > 0


@pytest.mark.integration
def test_december_cross_year_sowing_can_mature(tmp_path) -> None:
    request = _request(
        planting_date=date(2023, 12, 31),
        output_dir=tmp_path,
        parameters={"save_daily": True},
    )

    result = AquaCropAdapter().run(request)

    assert result.status is RunStatus.MATURED
    assert result.summary["maturity_date"].startswith("2024-")
    assert result.summary["simulation_end_date"] == "2024-12-30"
    assert result.summary["leap_day_harvest_rule_adjusted"] is False


@pytest.mark.integration
def test_insufficient_thermal_time_has_no_yield(tmp_path) -> None:
    request = _request(output_dir=tmp_path)
    cold_environment = replace(
        request.environment,
        weather=_cold_weather_records(request.start_date, request.end_date),
    )

    result = AquaCropAdapter().run(replace(request, environment=cold_environment))

    assert result.status is RunStatus.INSUFFICIENT_THERMAL_TIME
    assert result.summary["dry_yield_mg_ha"] is None
    assert "growing degree days" in result.failure_reason
