from __future__ import annotations

import pandas as pd
import pytest

from snowwindow.ml.experiment import (
    FixedWindowFeatureBuilder,
    add_multiscale_residual_features,
    residual_correction_dataset,
    response_surface_dataset,
)


def test_fixed_window_feature_builder_uses_only_local_weather() -> None:
    dates = pd.date_range("2022-01-01", periods=120)
    weather = pd.DataFrame(
        {
            "date": dates,
            "T2M_MIN": [0.0] * 120,
            "T2M_MAX": [10.0] * 120,
            "PRECTOTCORR": [1.0] * 120,
            "RH2M": [50.0] * 120,
            "WS2M": [2.0] * 120,
            "ALLSKY_SFC_SW_DWN": [3.0] * 120,
        }
    )

    features = FixedWindowFeatureBuilder(pre_plant_days=2, post_plant_days=2).build(
        weather, pd.Timestamp("2022-03-01")
    )

    assert features.row_count == 5
    assert features.total_precipitation_mm == pytest.approx(5.0)
    assert features.mean_temperature_c == pytest.approx(5.0)


def test_response_surface_dataset_computes_unbiased_ridge_by_leave_one_site_out() -> (
    None
):
    # Smooth synthetic response with no site-specific intercept. Ridge can
    # approximately recover it and rank dates well when the held-out site is absent.
    n_sites = 4
    rows = []
    for site_index in range(n_sites):
        site = f"S{site_index}_2023"
        temperature = 18 + site_index * 0.1
        for day in range(10):
            planting_date = pd.Timestamp("2023-05-01") + pd.Timedelta(days=day)
            # sinusoidal curve peaked at day=6
            y = 10 - 0.08 * (day - 6) ** 2 + 0.05 * temperature
            rows.append(
                {
                    "model": "synthetic",
                    "environment_id": site,
                    "site": f"S{site_index}",
                    "year": 2023,
                    "planting_date": planting_date,
                    "air_temperature_c": temperature,
                    "day_of_year": planting_date.dayofyear,
                    "dry_yield_mg_ha": y,
                }
            )
    table = pd.DataFrame(rows)

    dataset = response_surface_dataset(
        table, alpha=1e-4, features=("air_temperature_c",)
    )

    assert dataset["metrics"].shape[0] == n_sites
    assert (dataset["metrics"]["mean_absolute_error_mg_ha"] < 0.5).all()
    assert dataset["metrics"]["leave_one_site_out"].all()
    assert set(dataset["features"].columns) == {
        "intercept",
        "air_temperature_c",
        "sin_doy",
        "cos_doy",
    }


def test_residual_correction_dataset_uses_only_training_environments() -> None:
    rows = []
    for env in ("A", "B", "C"):
        for day in range(6):
            baseline = 10 - 0.10 * (day - 3) ** 2
            rows.append(
                {
                    "model": "synthetic",
                    "environment_id": env,
                    "planting_date": pd.Timestamp("2023-05-01")
                    + pd.Timedelta(days=day),
                    "forecast_mean_yield_mg_ha": baseline,
                    "oracle_yield_mg_ha": baseline + 0.05,
                }
            )
    curves = pd.DataFrame(rows)

    dataset = residual_correction_dataset(curves, alpha=0.01)

    assert set(dataset["predictions"]["holdout_environment_id"]) == {"A", "B", "C"}
    assert dataset["metrics"].shape[0] == 3
    assert (dataset["metrics"]["mae_reduction_mg_ha"] >= -1e-9).all()
    assert dataset["predictions"]["residual_fitted_mg_ha"].notna().all()


def test_multiscale_residual_features_capture_windows_and_doy() -> None:
    frame = pd.DataFrame(
        {
            "model": ["m"] * 5,
            "environment_id": ["A"] * 5,
            "planting_date": pd.date_range("2023-05-01", periods=5),
            "residual_mg_ha": [0.0, 1.0, 2.0, 1.0, 0.0],
        }
    )

    enriched = add_multiscale_residual_features(frame)

    assert {
        "residual_centered_mg_ha",
        "residual_3d_mean_mg_ha",
        "residual_5d_mean_mg_ha",
        "residual_shift_1d_mg_ha",
        "sin_doy",
        "cos_doy",
    }.issubset(enriched.columns)
    assert enriched["residual_3d_mean_mg_ha"].isna().sum() == 2
    assert enriched["residual_5d_mean_mg_ha"].isna().sum() == 4
    assert enriched.loc[2, "residual_shift_1d_mg_ha"] == pytest.approx(1.0)
