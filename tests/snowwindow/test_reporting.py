from __future__ import annotations

import runpy
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from snowwindow.domain import ModelCapabilities
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

    points = observed_flowering_points(pd.DataFrame(), predictions, baseline)

    assert points[["environment_id", "observed_value", "planting_date"]].to_dict(
        "records"
    ) == [
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

    points = observed_flowering_points(pd.DataFrame(), predictions, baseline)

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

    capabilities_config = type(
        "Config",
        (),
        {
            "experiment_dir": experiment,
            "model": type(
                "Model",
                (),
                {
                    "capabilities": ModelCapabilities(
                        display_name="APSIM",
                        report_notes=["Custom capability note."],
                    )
                },
            )(),
        },
    )()
    apsim_output = report_stage(capabilities_config)  # type: ignore[arg-type]

    text = apsim_output.read_text(encoding="utf-8")
    assert "# G2F APSIM" in text
    assert "Custom capability note." in text


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


@pytest.fixture
def report_config(tmp_path: Path) -> SimpleNamespace:
    experiment = tmp_path / "experiments" / "reporting"
    scan = experiment / "scan"
    scan.mkdir(parents=True)
    pd.DataFrame(
        {
            "environment_id": ["A_2024", "A_2024"],
            "parameter_set": ["calibrated", "calibrated"],
            "planting_date": ["2024-05-01", "2024-05-02"],
            "status": ["matured", "failed_weather"],
            "dry_yield_mg_ha": [8.45, None],
        }
    ).to_parquet(scan / "summary.parquet", index=False)
    (scan / "windows.json").write_text("[]", encoding="utf-8")
    validation = experiment / "validation"
    validation.mkdir()
    pd.DataFrame(
        {
            "fold": ["held_year"],
            "split": ["test"],
            "variable": ["dry_yield_mg_ha"],
            "rmse": [1.25],
        }
    ).to_parquet(validation / "metrics.parquet", index=False)
    return SimpleNamespace(
        experiment_dir=experiment,
        selection=SimpleNamespace(evaluation_years=(2024,)),
        model=SimpleNamespace(capabilities=ModelCapabilities(display_name="AquaCrop")),
    )


@pytest.mark.parametrize("model_label", ["AquaCrop", "APSIM", "DSSAT"])
def test_report_stage_describes_normalized_g2f_weather_only(
    report_config: SimpleNamespace,
    model_label: str,
) -> None:
    report_config.model.capabilities = ModelCapabilities(display_name=model_label)

    text = report_stage(report_config).read_text(encoding="utf-8")

    assert f"# G2F {model_label}" in text
    assert "规范化 G2F `full_year`" in text
    assert "2024-11-10（含当日）" in text
    assert "缺日与缺失值保持原样" in text
    assert "不补齐" in text
    assert "外部天气" in text
    assert "回退" in text
    assert "NASA POWER" not in text


@pytest.mark.parametrize(
    ("evaluation_years", "heading", "periods"),
    [
        (
            (2022,),
            "## 2022 留年验证",
            ("2022-01-01 至 2022-12-31（含首尾 365 天）",),
        ),
        (
            (2024,),
            "## 2024 留年验证",
            ("2024-01-01 至 2024-11-10（含首尾 315 天）",),
        ),
        (
            (2022, 2024),
            "## 2022, 2024 留年验证",
            (
                "2022-01-01 至 2022-12-31（含首尾 365 天）",
                "2024-01-01 至 2024-11-10（含首尾 315 天）",
            ),
        ),
        ((), "## 留年验证", ()),
    ],
)
def test_report_stage_uses_configured_evaluation_calendar(
    report_config: SimpleNamespace,
    evaluation_years: tuple[int, ...],
    heading: str,
    periods: tuple[str, ...],
) -> None:
    report_config.selection.evaluation_years = evaluation_years

    text = report_stage(report_config).read_text(encoding="utf-8")

    assert heading in text.splitlines()
    for period in periods:
        assert period in text
    assert "## 2023 留年验证" not in text
    assert "全年 365 天曲线" not in text
    assert "| held_year | test | dry_yield_mg_ha | 1.25 |" in text
    assert "| A_2024 | calibrated | failed_weather | 1 |" in text
    assert "| A_2024 | calibrated | matured | 1 |" in text


def test_forecast_oracle_legend_uses_environment_year(tmp_path: Path) -> None:
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "plot_forecast_oracle.py"
    )
    plot_model = runpy.run_path(str(script))["plot_model"]
    forecast_dir = tmp_path / "forecast"
    scan_dir = tmp_path / "oracle" / "scan"
    validation_dir = tmp_path / "oracle" / "validation"
    for directory in (forecast_dir, scan_dir, validation_dir):
        directory.mkdir(parents=True)
    dates = ["2024-05-01", "2024-05-02", "2024-05-03"]
    pd.DataFrame(
        {
            "environment_id": ["A_2024"] * 3,
            "planting_date": dates,
            "forecast_mean_yield_mg_ha": [8.0, 9.0, 8.5],
            "forecast_p10_yield_mg_ha": [7.0, 8.0, 7.5],
            "forecast_p90_yield_mg_ha": [9.0, 10.0, 9.5],
        }
    ).to_csv(forecast_dir / "forecast_curves.csv", index=False)
    pd.DataFrame(
        {
            "environment_id": ["A_2024"],
            "forecast_best_date": ["2024-05-02"],
            "oracle_best_date": ["2024-05-03"],
            "observed_planting_date": ["2024-05-01"],
            "forecast_best_forecast_yield_mg_ha": [9.0],
            "forecast_best_oracle_yield_mg_ha": [9.5],
            "observed_oracle_yield_mg_ha": [8.0],
            "oracle_maximum_yield_mg_ha": [10.0],
        }
    ).to_csv(forecast_dir / "recommendations.csv", index=False)
    pd.DataFrame(
        {
            "environment_id": ["A_2024"] * 3,
            "parameter_set": ["calibrated"] * 3,
            "status": ["matured"] * 3,
            "planting_date": dates,
            "dry_yield_mg_ha": [8.0, 9.5, 10.0],
        }
    ).to_csv(scan_dir / "summary.csv", index=False)
    pd.DataFrame(
        {
            "environment_id": ["A_2024"],
            "fold": ["held_year"],
            "parameter_set_id": ["calibrated"],
            "variable": ["dry_yield_mg_ha"],
            "management_unit_id": ["A_2024:2024-05-01"],
            "observed_value": [8.2],
        }
    ).to_csv(validation_dir / "predictions.csv", index=False)

    output = plot_model(
        "aquacrop",
        {
            "label": "AquaCrop",
            "forecast_dir": "forecast",
            "oracle_file": "oracle/scan/summary.csv",
        },
        "A_2024",
        30,
        tmp_path,
        tmp_path / "figures",
    )

    svg = output.with_suffix(".svg").read_text(encoding="utf-8")
    assert "Oracle (2024 actual weather)" in svg
    assert "Oracle (2023 actual weather)" not in svg
