from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from snowwindow.reporting import (
    observed_flowering_points,
    observed_yield_points,
    report_stage,
    simulated_flowering_dates,
)


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


def test_observed_flowering_points_include_pollen_observations() -> None:
    predictions = pd.DataFrame(
        {
            "fold": ["held_year", "held_year", "held_year"],
            "environment_id": ["A_2022", "A_2022", "A_2023"],
            "variable": ["pollen_dap", "pollen_dap", "pollen_dap"],
            "parameter_set_id": ["default", "calibrated", "calibrated"],
            "observed_value": [62.5, 62.5, 67.0],
        }
    )
    baseline = pd.DataFrame(
        {
            "environment_id": ["A_2022", "A_2023"],
            "planting_date": ["2022-05-12", "2023-05-04"],
        }
    )

    points = observed_flowering_points(
        pd.DataFrame(), predictions, baseline
    )

    assert points[
        ["environment_id", "observed_value", "planting_date"]
    ].to_dict("records") == [
        {
            "environment_id": "A_2022",
            "observed_value": 62.5,
            "planting_date": "2022-05-12",
        },
        {
            "environment_id": "A_2023",
            "observed_value": 67.0,
            "planting_date": "2023-05-04",
        },
    ]


def test_observed_flowering_points_include_calendar_dates() -> None:
    predictions = pd.DataFrame(
        {
            "fold": ["held_year"],
            "environment_id": ["A_2023"],
            "variable": ["pollen_dap"],
            "parameter_set_id": ["calibrated"],
            "observed_value": [67.0],
        }
    )
    baseline = pd.DataFrame(
        {
            "environment_id": ["A_2023"],
            "planting_date": ["2023-05-04"],
        }
    )

    points = observed_flowering_points(
        pd.DataFrame(), predictions, baseline
    )

    assert points.loc[0, "observed_date"] == pd.Timestamp("2023-07-10")


def test_simulated_flowering_dates_are_derived_from_planting_and_dap() -> None:
    frame = pd.DataFrame(
        {
            "planting_date": ["2023-05-04"],
            "flowering_proxy_dap": [77.0],
            "flowering_date": ["2023-10-21"],
        }
    )

    dates = simulated_flowering_dates(frame)

    assert dates.iloc[0] == pd.Timestamp("2023-07-20")


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
            "flowering_proxy_dap": [65.0, 62.0],
            "flowering_proxy_date": ["2022-07-05", "2022-07-02"],
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
            "fold": ["held_year", "held_year"],
            "split": ["train", "train"],
            "variable": ["dry_yield_mg_ha", "pollen_dap"],
            "parameter_set_id": ["calibrated", "calibrated"],
            "environment_id": ["A_2022", "A_2022"],
            "observed_value": [9.5, 63.0],
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
    assert (report / "figures" / "A_2022_flowering.png").is_file()
    assert (report / "figures" / "A_2022_flowering_date.png").is_file()
    assert output.is_file()
    assert "# G2F AquaCrop" in output.read_text(encoding="utf-8")

    apsim_config = type(
        "Config",
        (),
        {
            "experiment_dir": experiment,
            "model": type("Model", (), {"name": "apsim"})(),
        },
    )()
    apsim_output = report_stage(apsim_config)  # type: ignore[arg-type]

    text = apsim_output.read_text(encoding="utf-8")
    assert "# G2F APSIM" in text
    assert "`juvenile_tt` 与 `grain_number_scale`" in text


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
