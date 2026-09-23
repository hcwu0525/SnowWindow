from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from snowwindow.config import load_config
from snowwindow.domain import (
    Environment,
    ManagementUnit,
    RunStatus,
    SimulationRequest,
    SimulationResult,
)
from snowwindow.scan import (
    calendar_dates,
    derive_planting_windows,
    native_scan_requests,
    scan_stage,
)


def test_calendar_dates_preserve_leap_year() -> None:
    assert len(calendar_dates(2023)) == 365
    assert len(calendar_dates(2024)) == 366


def test_windows_use_only_mature_positive_yield_and_preserve_segments() -> None:
    frame = pd.DataFrame(
        {
            "planting_date": pd.date_range("2023-04-01", periods=6).date,
            "status": [
                "matured",
                "matured",
                "not_matured",
                "matured",
                "matured",
                "execution_failed",
            ],
            "dry_yield_mg_ha": [10.0, 9.6, None, 9.7, 10.0, None],
        }
    )

    window = derive_planting_windows(frame, (0.95,))[0]

    assert window["dates"] == [
        "2023-04-01",
        "2023-04-02",
        "2023-04-04",
        "2023-04-05",
    ]
    assert window["segments"] == [
        ["2023-04-01", "2023-04-02"],
        ["2023-04-04", "2023-04-05"],
    ]
    assert window["best_dates"] == ["2023-04-01", "2023-04-05"]


def test_native_scan_requests_cover_all_configured_combinations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "experiment.yaml"
    config_path.write_text(
        """
experiment_id: scan-test
data_dir: data
output_dir: outputs
model:
  name: aquacrop
  parameters:
    model_version: "3.1.0"
selection:
  environments: [A_2022, B_2022]
  calibration_years: [2022]
  evaluation_years: [2023]
simulation:
  scan_fractions: [0.90, 0.95]
  scan_all_dates: true
  workers: 1
  parameter_sets:
    default: {}
    calibrated:
      source: calibration
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)

    monkeypatch.setattr(
        "snowwindow.scan.calendar_dates",
        lambda year: (date(year, 1, 1), date(year, 1, 2)),
    )
    monkeypatch.setattr(
        "snowwindow.scan.load_prepared_tables",
        lambda config: {
            "environments": pd.DataFrame(
                [
                    {
                        "environment_id": "A_2022",
                        "year": 2022,
                        "field_location": "A",
                        "latitude": 40.0,
                        "longitude": -90.0,
                        "elevation": 200.0,
                    },
                    {
                        "environment_id": "B_2022",
                        "year": 2022,
                        "field_location": "B",
                        "latitude": 41.0,
                        "longitude": -91.0,
                        "elevation": 220.0,
                    },
                ]
            ),
            "management_units": pd.DataFrame(
                [
                    {
                        "management_unit_id": f"{env}-unit",
                        "environment_id": env,
                        "planting_date": date(2022, 5, 1),
                        "population_plants_m2": 8.0,
                        "irrigation_assumption": "rainfed_confirmed",
                    }
                    for env in ("A_2022", "B_2022")
                ]
            ),
            "soil_profiles": pd.DataFrame(
                [
                    {
                        "environment_id": env,
                        "aquacrop_soil_type": "Loam",
                        "profile_source": "observed",
                    }
                    for env in ("A_2022", "B_2022")
                ]
            ),
        },
    )
    weather = pd.DataFrame(
        {
            "date": pd.date_range("2022-01-01", "2022-12-31"),
            "T2M_MIN": 10.0,
            "T2M_MAX": 25.0,
            "PRECTOTCORR": 0.0,
            "RH2M": 60.0,
            "WS2M": 2.0,
            "PS": 100.0,
            "ALLSKY_SFC_SW_DWN": 15.0,
        }
    )
    monkeypatch.setattr(
        "snowwindow.scan.load_cached_power_weather",
        lambda config, environment_id: (weather, {"source": "test"}),
    )
    calibration_dir = config.experiment_dir / "calibration"
    calibration_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "fold": "held_year",
                "phenology_scale": 0.95,
                "HI0": 0.35,
            }
        ]
    ).to_parquet(calibration_dir / "parameters.parquet", index=False)

    class RecordingAdapter:
        name = "fake"
        version = "1"

        def __init__(self) -> None:
            self.requests = []

        def validate(self, request) -> None:
            self.requests.append(request)

        def run(self, request) -> SimulationResult:
            return SimulationResult(
                request_id=request.request_id,
                adapter_name=self.name,
                adapter_version=self.version,
                status=RunStatus.MATURED,
                summary={"dry_yield_mg_ha": 10.0},
            )

    adapter = RecordingAdapter()
    requests = native_scan_requests(config, adapter)

    assert len(requests) == 8
    assert {request.parameter_set_id for request in requests} == {
        "default",
        "calibrated",
    }
    assert {request.management.planting_date for request in requests} == {
        date(2022, 1, 1),
        date(2022, 1, 2),
    }
    assert {
        request.request_id
        for request in requests
        if request.parameter_set_id == "calibrated"
    } == {
        "A_2022-unit::calibrated::2022-01-01",
        "A_2022-unit::calibrated::2022-01-02",
        "B_2022-unit::calibrated::2022-01-01",
        "B_2022-unit::calibrated::2022-01-02",
    }
    calibrated = [
        request for request in requests if request.parameter_set_id == "calibrated"
    ]
    assert all(
        request.model_parameters["phenology_scale"] == 0.95 for request in calibrated
    )
    assert all(request.model_parameters["HI0"] == 0.35 for request in calibrated)


def test_scan_stage_executes_every_request_and_preserves_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "experiment.yaml"
    config_path.write_text(
        """
experiment_id: scan-stage-test
data_dir: data
output_dir: outputs
model:
  name: aquacrop
  parameters: {}
selection:
  environments: [A_2022]
  calibration_years: [2022]
  evaluation_years: [2023]
simulation:
  scan_fractions: [1.0]
  scan_all_dates: true
  workers: 1
  parameter_sets:
    default: {}
""".strip(),
        encoding="utf-8",
    )
    config = load_config(config_path)
    request = SimulationRequest(
        request_id="request-1",
        environment=Environment(
            environment_id="A_2022",
            year=2022,
            location="A",
            latitude=40.0,
            longitude=-90.0,
        ),
        management=ManagementUnit(
            management_unit_id="unit-1",
            environment_id="A_2022",
            planting_date=date(2022, 1, 1),
        ),
        start_date=date(2022, 1, 1),
        end_date=date(2022, 12, 31),
        parameter_set_id="default",
    )
    second_request = SimulationRequest(
        request_id="request-2",
        environment=request.environment,
        management=ManagementUnit(
            management_unit_id="unit-1",
            environment_id="A_2022",
            planting_date=date(2022, 1, 2),
        ),
        start_date=date(2022, 1, 1),
        end_date=date(2022, 12, 31),
        parameter_set_id="default",
    )

    class StatusAdapter:
        name = "status"
        version = "1"

        def __init__(self) -> None:
            self.calls = 0

        def validate(self, request) -> None:
            return None

        def run(self, request) -> SimulationResult:
            self.calls += 1
            status = RunStatus.MATURED if self.calls == 1 else RunStatus.CROP_DIED
            return SimulationResult(
                request_id=request.request_id,
                adapter_name=self.name,
                adapter_version=self.version,
                status=status,
                summary={
                    "dry_yield_mg_ha": 10.0
                    if status is RunStatus.MATURED
                    else None
                },
                failure_reason=None if status is RunStatus.MATURED else "died",
            )

    adapter = StatusAdapter()
    monkeypatch.setattr(
        "snowwindow.scan.native_scan_requests",
        lambda config, model: (request, second_request),
    )

    summary, windows = scan_stage(config, adapter)

    assert adapter.calls == 2
    assert summary["status"].tolist() == ["matured", "crop_died"]
    assert summary["failure_reason"].tolist() == [None, "died"]
    assert len(windows) == 1
    assert windows.iloc[0]["environment_id"] == "A_2022"
    assert windows.iloc[0]["status"] == "ok"
    assert (config.experiment_dir / "scan/summary.parquet").is_file()
    assert (config.experiment_dir / "scan/windows.json").is_file()
