"""G2F-only experiment forcing and the inclusive 2024 data boundary."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import yaml

from snowwindow.adapters import default_adapter_registry
from snowwindow.calibration import _prediction_rows, validate_parameter_sets
from snowwindow.config import ConfigError, load_config, save_config_snapshot
from snowwindow.data import audit_weather_coverage
from snowwindow.domain import RunStatus, SimulationResult
from snowwindow.experiment import (
    WEATHER_COLUMNS,
    build_observed_requests,
    load_g2f_weather,
)
from snowwindow.forecast import candidate_dates, forecast_stage, weather_scenarios
from snowwindow.scan import native_scan_requests, run_simulation_requests, scan_stage
from snowwindow.weather import WEATHER_POLICY

ROOT = Path(__file__).resolve().parents[2]


def _prepared_config(
    tmp_path: Path, model: str, *, year: int = 2024, continuation: bool = False
):
    config = load_config(ROOT / "configs/g2f_demo.yaml")
    parameters = {}
    if model != "aquacrop":
        parameters["simulation_horizon_days"] = 365
    config = replace(
        config,
        experiment_id="g2f-only",
        output_dir=tmp_path / "outputs",
        model=replace(config.model, name=model, parameters=parameters),
        selection=replace(
            config.selection,
            environments=(f"A_{year}",),
            calibration_years=(2021,) if year == 2022 else (2022,),
            evaluation_years=(year,),
        ),
        simulation=replace(
            config.simulation,
            parameter_sets={"default": {}},
            options={
                "scan_horizon": "cross_year" if continuation else "same_year",
                "continuation_weather_by_environment": (
                    {f"A_{year}": f"A_{year + 1}"} if continuation else {}
                ),
            },
        ),
    )
    save_config_snapshot(config)
    normalized = config.experiment_dir / "normalized"
    normalized.mkdir(parents=True)
    tables = {
        "environments": pd.DataFrame(
            [
                {
                    "environment_id": f"A_{year}",
                    "year": year,
                    "latitude": 40.0,
                    "longitude": -90.0,
                    "field_location": "A",
                }
            ]
        ),
        "management_units": pd.DataFrame(
            [
                {
                    "management_unit_id": f"A_{year}-unit",
                    "environment_id": f"A_{year}",
                    "year": year,
                    "planting_date": date(year, 5, 1),
                    "population_plants_ha": 80_000,
                    "irrigation_assumption": "rainfed_confirmed",
                }
            ]
        ),
        "soil_profiles": pd.DataFrame(
            [
                {
                    "environment_id": f"A_{year}",
                    "aquacrop_soil_type": "Loam",
                    "profile_source": "observed",
                }
            ]
        ),
        "observations": pd.DataFrame({"value": []}),
    }
    for name, frame in tables.items():
        frame.to_parquet(normalized / f"{name}.parquet", index=False)
    audit = config.experiment_dir / "audit"
    audit.mkdir()
    pd.DataFrame({"scan_eligible": [True]}).to_parquet(
        audit / "eligibility.parquet", index=False
    )
    frames = []
    for weather_year in (year, year + 1) if continuation else (year,):
        days = pd.date_range(f"{weather_year}-01-01", f"{weather_year}-12-31")
        frames.append(
            pd.DataFrame(
                {
                    "environment_id": f"A_{weather_year}",
                    "date": days,
                    "T2M_MIN": 10.0,
                    "T2M_MAX": 25.0,
                    "PRECTOTCORR": 1.0,
                    "RH2M": 60.0,
                    "WS2M": 2.0,
                    "PS": 100.0,
                    "ALLSKY_SFC_SW_DWN": 15.0,
                    "source_filename": f"G2F_{weather_year}_full_year.csv",
                }
            )
        )
    pd.concat(frames, ignore_index=True).to_parquet(
        normalized / "weather.parquet", index=False
    )
    adapter = default_adapter_registry().get(model)
    calibration = config.experiment_dir / "calibration"
    calibration.mkdir()
    pd.DataFrame(
        [
            {
                "fold": "held_year",
                adapter.capabilities.phenology_parameter.name: (
                    adapter.capabilities.phenology_parameter.default
                ),
                adapter.capabilities.yield_parameter.name: (
                    adapter.capabilities.yield_parameter.default
                ),
            }
        ]
    ).to_parquet(calibration / "parameters.parquet", index=False)
    return config


def _poison_legacy_weather(config) -> None:
    for layout in (config.output_dir, config.output_dir / "experiments/legacy"):
        for experiment in ("aquacrop_demo", "aquacrop_crossyear"):
            directory = layout / experiment / "weather"
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "A_2024.csv").write_text(
                "<html>not G2F weather</html>\n", encoding="utf-8"
            )


@pytest.mark.parametrize("model", ["aquacrop", "apsim", "dssat"])
def test_observed_requests_use_g2f_and_never_legacy_weather(
    tmp_path: Path, model: str
) -> None:
    config = _prepared_config(tmp_path, model)
    _poison_legacy_weather(config)

    requests, provenance = build_observed_requests(config)

    request = requests["A_2024-unit"]
    assert request.end_date == date(2024, 11, 10)
    assert len(request.environment.weather) == 315
    assert request.environment.weather[-1].date == date(2024, 11, 10)
    assert request.environment.weather[-1].values["T2M_MAX"] == 25.0
    assert request.environment.metadata["simulation_end_date"] == "2024-11-10"
    assert request.environment.metadata["weather_horizon_truncated"] is True
    evidence = json.loads(provenance.iloc[0]["weather_provenance"])
    assert evidence["source"] == "G2F full-year weather"
    assert evidence["end_date"] == "2024-11-10"
    assert evidence["files"][0]["path"].endswith("normalized/weather.parquet")


@pytest.mark.parametrize("model", ["aquacrop", "apsim", "dssat"])
def test_missing_g2f_weather_is_not_replaced_by_a_legacy_layout(
    tmp_path: Path, model: str
) -> None:
    config = _prepared_config(tmp_path, model)
    _poison_legacy_weather(config)
    (config.experiment_dir / "normalized/weather.parquet").unlink()

    with pytest.raises(FileNotFoundError, match="normalized/weather.parquet"):
        build_observed_requests(config)


@pytest.mark.parametrize("model", ["aquacrop", "apsim", "dssat"])
def test_explicit_g2f_continuation_is_used_by_observed_requests(
    tmp_path: Path, model: str
) -> None:
    config = _prepared_config(tmp_path, model, year=2023, continuation=True)
    units_path = config.experiment_dir / "normalized/management_units.parquet"
    units = pd.read_parquet(units_path)
    units["planting_date"] = date(2023, 12, 31)
    units.to_parquet(units_path, index=False)

    requests, provenance = build_observed_requests(
        config, model_parameters={"simulation_horizon_days": 365}
    )

    request = requests["A_2023-unit"]
    assert request.end_date == date(2024, 11, 10)
    assert request.environment.weather[-1].date == date(2024, 11, 10)
    evidence = json.loads(provenance.iloc[0]["weather_provenance"])
    assert evidence["environment_ids"] == ["A_2023", "A_2024"]


@pytest.mark.parametrize("model", ["aquacrop", "apsim", "dssat"])
def test_scan_has_315_candidates_and_cannot_pass_the_2024_boundary(
    tmp_path: Path, model: str
) -> None:
    config = _prepared_config(tmp_path, model)
    requests = native_scan_requests(config)

    assert len(requests) == 315
    assert requests[0].management.planting_date == date(2024, 1, 1)
    assert requests[-1].management.planting_date == date(2024, 11, 10)
    assert date(2024, 2, 29) in {
        request.management.planting_date for request in requests
    }
    assert all(request.end_date <= date(2024, 11, 10) for request in requests)
    assert all(
        max(row.date for row in request.environment.weather) <= date(2024, 11, 10)
        for request in requests
    )


def test_g2f_core_missing_values_are_preserved_not_filled(tmp_path: Path) -> None:
    config = _prepared_config(tmp_path, "aquacrop")
    path = config.experiment_dir / "normalized/weather.parquet"
    weather = pd.read_parquet(path)
    weather.loc[weather["date"].eq(pd.Timestamp("2024-07-12")), "T2M_MAX"] = float(
        "nan"
    )
    weather.to_parquet(path, index=False)

    requests, _ = build_observed_requests(config)
    row = next(
        row
        for row in requests["A_2024-unit"].environment.weather
        if row.date == date(2024, 7, 12)
    )
    assert pd.isna(row.values["T2M_MAX"])


def test_2024_audit_accepts_the_declared_period_without_demanding_december() -> None:
    weather = pd.DataFrame(
        {
            "Env": "A_2024",
            "Date": pd.date_range("2024-01-01", "2024-11-10").strftime("%Y%m%d"),
            **dict.fromkeys(WEATHER_COLUMNS, 1.0),
        }
    )

    coverage = audit_weather_coverage(weather)["A_2024"]

    assert coverage["calendar_complete"] is True
    assert coverage["missing_calendar_dates"] == []
    assert coverage["required_end_date"] == "2024-11-10"
    assert coverage["full_year_calendar_complete"] is False


def test_2024_audit_still_reports_core_gaps_inside_the_declared_period() -> None:
    weather = pd.DataFrame(
        {
            "Env": "A_2024",
            "Date": pd.date_range("2024-01-01", "2024-11-10").strftime("%Y%m%d"),
            **dict.fromkeys(WEATHER_COLUMNS, 1.0),
        }
    )
    weather.loc[weather["Date"].eq("20240712"), "RH2M"] = -999

    coverage = audit_weather_coverage(weather)["A_2024"]

    assert coverage["date_calendar_complete"] is True
    assert coverage["calendar_complete"] is False
    assert coverage["core_gap_dates"] == ["2024-07-12"]


def test_forecast_scenarios_stop_at_the_2024_data_end() -> None:
    frames = []
    for year in (2023, 2024):
        days = pd.date_range(f"{year}-01-01", f"{year}-12-31")
        frames.append(
            pd.DataFrame(
                {
                    "environment_id": f"A_{year}",
                    "date": days,
                    **dict.fromkeys(WEATHER_COLUMNS, float(year)),
                }
            )
        )
    scenarios = weather_scenarios(
        pd.concat(frames, ignore_index=True),
        environment_id="A_2024",
        site="A",
        target_year=2024,
        cutoff_date=date(2024, 3, 1),
    )

    assert len(scenarios[2023]) == 315
    assert scenarios[2023]["date"].max() == pd.Timestamp("2024-11-10")
    future = scenarios[2023].loc[scenarios[2023]["date"].gt(pd.Timestamp("2024-03-01"))]
    assert future["T2M_MIN"].eq(2023.0).all()


def test_forecast_candidates_never_include_dates_after_2024_november_10() -> None:
    candidates = candidate_dates(date(2024, 11, 8), radius_days=4)

    assert candidates[-1] == date(2024, 11, 10)
    assert len(candidates) == 7


def test_old_weather_policy_cannot_be_resumed_under_the_same_experiment_id(
    tmp_path: Path,
) -> None:
    config = load_config(ROOT / "configs/g2f_demo.yaml")
    config = replace(config, experiment_id="old", output_dir=tmp_path)
    path = save_config_snapshot(config)
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document.pop("weather_policy", None)
    path.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(ConfigError, match="new experiment_id"):
        save_config_snapshot(config)


@pytest.mark.parametrize("mapped_id", ["OTHER_2023", "A_2024"])
def test_g2f_continuation_rejects_a_different_site_or_nonconsecutive_year(
    tmp_path: Path, mapped_id: str
) -> None:
    config = _prepared_config(tmp_path, "aquacrop", year=2022)
    config = replace(
        config,
        simulation=replace(
            config.simulation,
            options={
                "scan_horizon": "cross_year",
                "continuation_weather_by_environment": {"A_2022": mapped_id},
            },
        ),
    )

    with pytest.raises(ValueError, match="must be A_2023"):
        load_g2f_weather(config, "A_2022")


def test_g2f_missing_explicit_continuation_is_not_substituted(tmp_path: Path) -> None:
    config = _prepared_config(tmp_path, "aquacrop", year=2022)
    config = replace(
        config,
        simulation=replace(
            config.simulation,
            options={
                "scan_horizon": "cross_year",
                "continuation_weather_by_environment": {"A_2022": "A_2023"},
            },
        ),
    )

    with pytest.raises(ValueError, match="G2F weather is missing for A_2023"):
        load_g2f_weather(config, "A_2022")


def test_2024_does_not_require_2025_weather(tmp_path: Path) -> None:
    config = _prepared_config(tmp_path, "aquacrop")
    config = replace(
        config,
        simulation=replace(
            config.simulation,
            options={
                "scan_horizon": "cross_year",
                "continuation_weather_by_environment": {},
            },
        ),
    )

    weather, evidence = load_g2f_weather(config, "A_2024")
    assert len(weather) == 315
    assert evidence["environment_ids"] == ["A_2024"]


def test_dssat_sliced_weather_does_not_cross_end_date_when_a_day_is_missing(
    tmp_path: Path,
) -> None:
    config = _prepared_config(tmp_path, "dssat")
    config = replace(
        config,
        model=replace(config.model, parameters={"simulation_horizon_days": 10}),
    )
    path = config.experiment_dir / "normalized/weather.parquet"
    weather = pd.read_parquet(path)
    weather.loc[weather["date"].ne(pd.Timestamp("2024-01-03"))].to_parquet(
        path, index=False
    )

    requests = native_scan_requests(config)

    first = requests[0]
    assert first.end_date == date(2024, 1, 11)
    assert max(row.date for row in first.environment.weather) <= first.end_date
    assert date(2024, 1, 3) not in {row.date for row in first.environment.weather}


def test_observed_planting_after_the_data_end_is_rejected(tmp_path: Path) -> None:
    config = _prepared_config(tmp_path, "aquacrop")
    path = config.experiment_dir / "normalized/management_units.parquet"
    units = pd.read_parquet(path)
    units["planting_date"] = date(2024, 11, 11)
    units.to_parquet(path, index=False)

    with pytest.raises(ValueError, match="planting date exceeds G2F"):
        build_observed_requests(config)


@pytest.mark.parametrize("batched", [False, True])
@pytest.mark.parametrize(
    ("invalid_day", "expected_statuses"),
    [
        ("2024-07-12", ["matured", "invalid_input"]),
        ("2023-01-03", ["invalid_input", "invalid_input"]),
    ],
)
def test_scan_retains_weather_failures_before_native_cache_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    batched: bool,
    invalid_day: str,
    expected_statuses: list[str],
) -> None:
    config = _prepared_config(tmp_path, "dssat", year=2023, continuation=True)
    path = config.experiment_dir / "normalized/weather.parquet"
    weather = pd.read_parquet(path)
    weather.loc[weather["date"].eq(pd.Timestamp(invalid_day)), "T2M_MAX"] = float("nan")
    weather.to_parquet(path, index=False)
    monkeypatch.setattr(
        "snowwindow.scan.calendar_dates",
        lambda year: (date(year, 1, 1), date(year, 8, 1)),
    )
    calls = []

    class NativeEngine:
        name = "dssat"
        version = "fixture"
        capabilities = default_adapter_registry().get("dssat").capabilities

        def _check(self, request):
            if any(
                pd.isna(row.values["T2M_MAX"]) for row in request.environment.weather
            ):
                raise ValueError("native validation cannot serialize missing weather")

        def cache_key(self, request):
            self._check(request)
            return request.request_id

        def run(self, request):
            self._check(request)
            calls.append(request.management.planting_date)
            return SimulationResult(
                request_id=request.request_id,
                adapter_name=self.name,
                adapter_version=self.version,
                status=RunStatus.MATURED,
                summary={"dry_yield_mg_ha": 8.0},
            )

        def run_many(self, requests):
            return {request.request_id: self.run(request) for request in requests}

    engine = NativeEngine()
    if batched:
        engine.cache_key = None
    else:
        engine.run_many = None
    summary, _ = scan_stage(config, engine)

    assert summary["status"].tolist() == expected_statuses
    failed = summary.iloc[1]
    assert pd.isna(failed["dry_yield_mg_ha"])
    assert invalid_day in failed["failure_reason"]
    assert all(day == date(2023, 1, 1) for day in calls)
    if expected_statuses == ["invalid_input", "invalid_input"]:
        assert calls == []
    persisted = pd.read_parquet(config.experiment_dir / "scan/summary.parquet")
    assert persisted["status"].tolist() == expected_statuses


def test_weather_preflight_does_not_mask_missing_engine_errors(tmp_path: Path) -> None:
    config = _prepared_config(tmp_path, "dssat")
    requests, _ = build_observed_requests(config)

    class UnavailableEngine:
        name = "dssat"
        version = "fixture"

        def run(self, request):
            raise FileNotFoundError("native engine is not installed")

    with pytest.raises(FileNotFoundError, match="native engine is not installed"):
        run_simulation_requests(
            tuple(requests.values()), UnavailableEngine(), workers=1
        )


def test_weather_gaps_remain_failed_in_calibration_and_validation(
    tmp_path: Path,
) -> None:
    config = _prepared_config(tmp_path, "dssat")
    path = config.experiment_dir / "normalized/weather.parquet"
    weather = pd.read_parquet(path)
    weather.loc[weather["date"].eq(pd.Timestamp("2024-07-12")), "T2M_MAX"] = float(
        "nan"
    )
    weather.to_parquet(path, index=False)
    requests, _ = build_observed_requests(config)
    observations = pd.DataFrame(
        [
            {
                "observation_id": "yield",
                "management_unit_id": "A_2024-unit",
                "variable": "dry_yield_mg_ha",
                "value": 8.0,
            }
        ]
    )

    class NativeEngine:
        name = "dssat"
        version = "fixture"

        def run(self, request):
            raise ValueError("native validation cannot serialize missing weather")

    search = _prediction_rows(
        NativeEngine(),
        requests,
        observations,
        parameter_name="G2",
        parameter_values=(800.0,),
        fixed_parameters={},
        prediction_name="dry_yield_mg_ha",
    )
    assert search["status"].eq("invalid_input").all()
    assert search["predicted_value"].isna().all()
    assert search["failure_reason"].str.contains("2024-07-12").all()
    predictions, metrics = validate_parameter_sets(
        NativeEngine(),
        requests,
        observations,
        fold_name="held_year",
        split_by_unit={"A_2024-unit": "test"},
        parameter_sets={"default": {}},
    )
    assert predictions["status"].eq("invalid_input").all()
    assert predictions["predicted_value"].isna().all()
    assert metrics["coverage"].eq(0).all()


def test_all_failed_forecast_scenarios_are_persisted_before_reporting_error(
    tmp_path: Path,
) -> None:
    config = _prepared_config(tmp_path, "dssat")
    path = config.experiment_dir / "normalized/weather.parquet"
    weather = pd.read_parquet(path)
    historical = weather.copy()
    historical["environment_id"] = "A_2023"
    historical["date"] = historical["date"] - pd.DateOffset(years=1)
    historical = historical.drop_duplicates(["environment_id", "date"])
    weather.loc[weather["date"].eq(pd.Timestamp("2024-01-03")), "T2M_MAX"] = float(
        "nan"
    )
    pd.concat([historical, weather], ignore_index=True).to_parquet(path, index=False)
    scan = config.experiment_dir / "scan"
    scan.mkdir()
    (scan / "manifest.json").write_text(
        json.dumps({"weather_policy": WEATHER_POLICY}), encoding="utf-8"
    )
    pd.DataFrame(
        [
            {
                "environment_id": "A_2024",
                "parameter_set": "calibrated",
                "planting_date": date(2024, 5, 1),
                "status": "matured",
                "dry_yield_mg_ha": 8.0,
            }
        ]
    ).to_parquet(scan / "summary.parquet", index=False)

    class NativeEngine:
        name = "dssat"
        version = "fixture"
        capabilities = default_adapter_registry().get("dssat").capabilities

        def run(self, request):
            raise AssertionError("invalid weather must not reach native dispatch")

    with pytest.raises(ValueError, match="all forecast scenarios failed"):
        forecast_stage(config, NativeEngine())

    results = pd.read_parquet(
        config.experiment_dir / "forecast/scenario_results.parquet"
    )
    assert len(results) == 29
    assert results["status"].eq("invalid_input").all()
    assert results["dry_yield_mg_ha"].isna().all()
    assert results["failure_reason"].str.contains("2024-01-03").all()


def test_forecast_rejects_a_legacy_source_even_under_a_new_forecast_id(
    tmp_path: Path,
) -> None:
    config = load_config(ROOT / "configs/g2f_forecast_demo.yaml")
    config = replace(config, experiment_id="new-forecast", output_dir=tmp_path)
    source_id = config.selection.options["source_experiment_id"]
    source_root = tmp_path / "experiments" / source_id
    source_root.mkdir(parents=True)
    (source_root / "config.yaml").write_text(
        yaml.safe_dump({"experiment_id": source_id}), encoding="utf-8"
    )

    with pytest.raises(ConfigError, match="new.*source experiment"):
        forecast_stage(config)


@pytest.mark.parametrize("manifest", [None, {"weather_source": "legacy POWER"}])
def test_forecast_rejects_a_scan_without_matching_weather_evidence(
    tmp_path: Path, manifest: dict | None
) -> None:
    config = load_config(ROOT / "configs/g2f_forecast_demo.yaml")
    config = replace(config, experiment_id="new-forecast", output_dir=tmp_path)
    source_id = config.selection.options["source_experiment_id"]
    source_root = tmp_path / "experiments" / source_id
    source_root.mkdir(parents=True)
    (source_root / "config.yaml").write_text(
        yaml.safe_dump({"experiment_id": source_id, "weather_policy": WEATHER_POLICY}),
        encoding="utf-8",
    )
    if manifest is not None:
        (source_root / "scan").mkdir()
        (source_root / "scan/manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

    with pytest.raises(ConfigError, match="new.*source experiment"):
        forecast_stage(config)
