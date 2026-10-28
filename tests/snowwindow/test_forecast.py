from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from snowwindow.forecast import _report as forecast_report
from snowwindow.forecast import (
    candidate_dates,
    score_forecast_recommendation,
    weather_scenarios,
)


def test_candidate_dates_center_on_observed_planting_date() -> None:
    dates = candidate_dates(date(2023, 5, 10), radius_days=3, step_days=2)

    assert dates == (
        date(2023, 5, 7),
        date(2023, 5, 9),
        date(2023, 5, 10),
        date(2023, 5, 11),
        date(2023, 5, 13),
    )


def test_weather_scenarios_preserve_target_prefix_and_avoid_future_leakage() -> None:
    weather = pd.concat(
        [
            pd.DataFrame(
                {
                    "environment_id": ["A_2022"] * 365,
                    "date": pd.date_range("2022-01-01", "2022-12-31"),
                    "T2M_MIN": 1.0,
                    "T2M_MAX": 10.0,
                    "PRECTOTCORR": 0.0,
                    "RH2M": 50.0,
                    "WS2M": 2.0,
                    "PS": 100.0,
                    "ALLSKY_SFC_SW_DWN": 10.0,
                }
            ),
            pd.DataFrame(
                {
                    "environment_id": ["A_2023"] * 60,
                    "date": pd.date_range("2023-01-01", "2023-03-01"),
                    "T2M_MIN": 2.0,
                    "T2M_MAX": 11.0,
                    "PRECTOTCORR": 0.1,
                    "RH2M": 51.0,
                    "WS2M": 2.1,
                    "PS": 100.1,
                    "ALLSKY_SFC_SW_DWN": 10.1,
                }
            ),
        ],
        ignore_index=True,
    )

    scenarios = weather_scenarios(
        weather,
        environment_id="A_2023",
        site="A",
        target_year=2023,
        cutoff_date=date(2023, 3, 1),
    )

    assert set(scenarios) == {2022}
    scenario = scenarios[2022]
    assert len(scenario) == 365
    assert scenario["date"].min() == pd.Timestamp("2023-01-01")
    assert scenario["date"].max() == pd.Timestamp("2023-12-31")
    assert not scenario["date"].duplicated().any()
    prefix = scenario.loc[scenario["date"] <= pd.Timestamp("2023-03-01")]
    suffix = scenario.loc[scenario["date"] > pd.Timestamp("2023-03-01")]
    assert (prefix["T2M_MIN"] == 2.0).all()
    assert (suffix["T2M_MIN"] == 1.0).all()
    assert suffix["date"].min() == pd.Timestamp("2023-03-02")


def test_score_forecast_recommendation_against_actual_oracle() -> None:
    forecast = pd.DataFrame(
        {
            "planting_date": pd.date_range("2023-05-01", periods=5).date,
            "forecast_mean_yield_mg_ha": [10.0, 9.8, 9.6, 9.0, 8.5],
        }
    )
    oracle = pd.DataFrame(
        {
            "planting_date": pd.date_range("2023-05-01", periods=5).date,
            "dry_yield_mg_ha": [9.0, 10.0, 9.9, 9.0, 8.5],
        }
    )

    score = score_forecast_recommendation(
        forecast,
        oracle,
        fraction=0.95,
        observed_planting_date=date(2023, 5, 3),
    )

    assert score["forecast_recommended_dates"] == [
        "2023-05-01",
        "2023-05-02",
        "2023-05-03",
    ]
    assert score["oracle_recommended_dates"] == [
        "2023-05-02",
        "2023-05-03",
    ]
    assert score["overlap_days"] == 2
    assert score["recommended_window_coverage"] == 2 / 3
    assert score["forecast_best_date"] == "2023-05-01"
    assert score["oracle_best_date"] == "2023-05-02"
    assert score["forecast_best_oracle_yield_mg_ha"] == 9.0
    assert score["oracle_maximum_yield_mg_ha"] == 10.0
    assert score["forecast_best_regret_mg_ha"] == 1.0
    assert score["observed_oracle_yield_mg_ha"] == 9.9
    assert score["observed_regret_mg_ha"] == pytest.approx(0.1)
    assert score["forecast_gain_over_observed_mg_ha"] == pytest.approx(-0.9)


def test_report_uses_configured_model_display_name() -> None:
    config = type(
        "Config",
        (),
        {
            "experiment_dir": Path("/tmp/demo"),
            "experiment_id": "demo_forecast",
            "selection": type(
                "Selection",
                (),
                {"options": {}},
            )(),
            "simulation": type(
                "Simulation",
                (),
                {"options": {
                    "forecast_radius_days": 30,
                    "forecast_fraction": 0.90,
                }},
            )(),
            "source_path": Path("configs/demo_forecast.yaml"),
        },
    )()
    recommendations = pd.DataFrame(
        {
            "environment_id": ["A_2023"],
            "forecast_recommended_dates": [["2023-05-01"]],
            "oracle_recommended_dates": [["2023-05-01"]],
            "overlap_days": [1],
            "recommended_window_coverage": [1.0],
            "forecast_best_date": ["2023-05-01"],
            "oracle_best_date": ["2023-05-01"],
            "forecast_best_regret_mg_ha": [0.0],
            "observed_regret_mg_ha": [0.5],
            "forecast_gain_over_observed_mg_ha": [0.5],
        }
    )
    results = pd.DataFrame(
        {
            "environment_id": ["A_2023"],
            "status": ["matured"],
        }
    )
    report = forecast_report(
        config, recommendations, results, 9, date(2024, 3, 1), "APSIM"
    )

    assert "利用已有的 APSIM 最小仿真闭环" in report
    assert "APSIM 适配器" in report
    assert "AquaCrop" not in report
    assert "2024-11-10" in report
    assert "各 30 天" in report
    assert "90%" in report
    assert "两个环境的预测窗口" not in report
    assert "2023 年全年真实天气" not in report
    assert "G2F" in report
