from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from snowwindow.reporting import observed_yield_points, report_stage


def test_observed_yield_points_include_validation_observations(
    tmp_path: Path,
) -> None:
    metrics = pd.DataFrame(
        {
            "fold": ["held_year", "held_year"],
            "split": ["train", "test"],
            "variable": ["dry_yield_mg_ha", "dry_yield_mg_ha"],
            "environment_id": ["A_2022", "A_2023"],
            "observed_value": [9.0, 10.0],
        }
    )
    predictions = pd.DataFrame(
        {
            "environment_id": ["A_2022", "A_2023"],
            "split": ["train", "test"],
            "variable": ["dry_yield_mg_ha", "dry_yield_mg_ha"],
            "parameter_set_id": ["calibrated", "calibrated"],
            "observed_value": [9.0, 10.0],
        }
    )
    baseline = pd.DataFrame(
        {
            "environment_id": ["A_2022", "A_2023"],
            "planting_date": ["2022-05-12", "2023-05-04"],
        }
    )

    points = observed_yield_points(metrics, predictions, baseline)

    assert points[["environment_id", "planting_date", "observed_value"]].to_dict(
        "records"
    ) == [
        {
            "environment_id": "A_2022",
            "planting_date": "2022-05-12",
            "observed_value": 9.0,
        },
        {
            "environment_id": "A_2023",
            "planting_date": "2023-05-04",
            "observed_value": 10.0,
        },
    ]


def test_report_stage_overlays_observed_points(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment = tmp_path / "experiments" / "demo"
    scan = experiment / "scan"
    report = experiment / "report"
    scan.mkdir(parents=True)
    report.mkdir(parents=True)
    pd.DataFrame(
        {
            "environment_id": ["A_2022"] * 2,
            "parameter_set": ["default", "calibrated"],
            "planting_date": ["2022-05-01", "2022-05-01"],
            "status": ["matured", "matured"],
            "yield_at_15p5_mg_ha": [10.0, 9.0],
            "dry_yield_mg_ha": [8.45, 7.605],
        }
    ).to_parquet(scan / "summary.parquet", index=False)
    (scan / "windows.json").write_text("[]", encoding="utf-8")
    validation = experiment / "validation"
    validation.mkdir()
    pd.DataFrame(
        {
            "fold": ["held_year"],
            "split": ["train"],
            "variable": ["dry_yield_mg_ha"],
            "environment_id": ["A_2022"],
            "observed_value": [9.5],
        }
    ).to_parquet(validation / "metrics.parquet", index=False)
    pd.DataFrame(
        {
            "fold": ["held_year"],
            "split": ["train"],
            "variable": ["dry_yield_mg_ha"],
            "parameter_set_id": ["calibrated"],
            "environment_id": ["A_2022"],
            "observed_value": [9.5],
        }
    ).to_parquet(validation / "predictions.parquet", index=False)
    baseline = experiment / "baseline"
    baseline.mkdir()
    pd.DataFrame(
        {
            "environment_id": ["A_2022"],
            "planting_date": ["2022-05-01"],
        }
    ).to_parquet(baseline / "summary.parquet", index=False)

    config = type("Config", (), {"experiment_dir": experiment})()
    output = report_stage(config)  # type: ignore[arg-type]

    assert (report / "figures" / "A_2022.png").is_file()
    assert output.is_file()


def test_report_stage_requires_dry_yield_for_observed_comparison(
    tmp_path: Path,
) -> None:
    experiment = tmp_path / "experiments" / "demo"
    scan = experiment / "scan"
    scan.mkdir(parents=True)
    pd.DataFrame(
        {
            "environment_id": ["A_2022"],
            "parameter_set": ["calibrated"],
            "planting_date": ["2022-05-01"],
            "status": ["matured"],
            "yield_at_15p5_mg_ha": [10.0],
        }
    ).to_parquet(scan / "summary.parquet", index=False)
    (scan / "windows.json").write_text("[]", encoding="utf-8")

    config = type("Config", (), {"experiment_dir": experiment})()

    with pytest.raises(ValueError, match="dry_yield_mg_ha"):
        report_stage(config)  # type: ignore[arg-type]
