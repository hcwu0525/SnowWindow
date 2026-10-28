"""Small leave-one-site-out experiments over model response surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd

from snowwindow.experiment import WEATHER_COLUMNS


@dataclass(frozen=True)
class SiteYearFeatures:
    """Deterministic seasonal weather features for a site-year."""

    row_count: int
    mean_temperature_c: float
    maximum_temperature_c: float
    minimum_temperature_c: float
    total_precipitation_mm: float
    mean_relative_humidity_pct: float
    mean_wind_speed_ms: float
    total_solar_radiation_mj_m2: float


class WeatherFeatureBuilder(Protocol):
    """Build features from daily weather without target-year oracle leakage."""

    def build(
        self, weather: pd.DataFrame, planting_date: pd.Timestamp
    ) -> SiteYearFeatures: ...


class FixedWindowFeatureBuilder:
    """Weather aggregates around planting for operational pre-plant decisions."""

    def __init__(
        self,
        *,
        pre_plant_days: int = 45,
        post_plant_days: int = 60,
    ) -> None:
        self.pre_plant_days = pre_plant_days
        self.post_plant_days = post_plant_days

    def build(
        self, weather: pd.DataFrame, planting_date: pd.Timestamp
    ) -> SiteYearFeatures:
        required = {
            "date",
            "T2M_MIN",
            "T2M_MAX",
            "PRECTOTCORR",
            "RH2M",
            "WS2M",
            "ALLSKY_SFC_SW_DWN",
        }
        if missing := required.difference(weather.columns):
            raise ValueError(f"weather is missing columns: {sorted(missing)}")
        start = planting_date - pd.Timedelta(days=self.pre_plant_days)
        end = planting_date + pd.Timedelta(days=self.post_plant_days)
        frame = weather.loc[weather["date"].between(start, end)].copy()
        if frame.empty:
            raise ValueError("fixed weather window is empty")
        frame["mean_temperature"] = (frame["T2M_MIN"] + frame["T2M_MAX"]) / 2

        # Rounding is intentional: only compact evidence is persisted here.
        def clean(value: float) -> float:
            return round(float(value), 6)

        return SiteYearFeatures(
            row_count=int(len(frame)),
            mean_temperature_c=clean(frame["mean_temperature"].mean()),
            maximum_temperature_c=clean(frame["T2M_MAX"].max()),
            minimum_temperature_c=clean(frame["T2M_MIN"].min()),
            total_precipitation_mm=clean(frame["PRECTOTCORR"].sum()),
            mean_relative_humidity_pct=clean(frame["RH2M"].mean()),
            mean_wind_speed_ms=clean(frame["WS2M"].mean()),
            total_solar_radiation_mj_m2=clean(frame["ALLSKY_SFC_SW_DWN"].sum()),
        )


def ridge_fit(
    frame: pd.DataFrame,
    features: tuple[str, ...],
    target: str = "dry_yield_mg_ha",
    *,
    alpha: float = 1.0,
) -> tuple[np.ndarray, float]:
    """Fit centered ridge regression without external dependencies."""

    if alpha <= 0:
        raise ValueError("alpha must be positive")
    if not features:
        raise ValueError("at least one feature is required")
    if target not in frame:
        raise ValueError(f"frame is missing target: {target}")
    y_frame = frame.loc[:, [target]].dropna()
    usable_frame = frame.loc[y_frame.index]
    x_frame = usable_frame.loc[:, features]
    y_values = pd.to_numeric(usable_frame[target], errors="raise").to_numpy(dtype=float)
    means = x_frame.mean(axis=0)
    scales = x_frame.std(axis=0, ddof=0).replace(0, 1.0)
    x = ((x_frame - means) / scales).to_numpy(dtype=float)
    x = np.column_stack([np.ones(len(x)), x])
    penalty = np.eye(x.shape[1]) * alpha
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(x.T @ x + penalty, x.T @ y_values)
    return coefficients, float(y_values.mean())


def ridge_predict(
    frame: pd.DataFrame,
    coefficients: np.ndarray,
    train_means: pd.Series,
    train_scales: pd.Series,
    features: tuple[str, ...],
) -> np.ndarray:
    """Predict from a fitted ridge model with train-time standardization."""

    x = ((frame.loc[:, list(features)] - train_means) / train_scales).to_numpy(
        dtype=float
    )
    x = np.column_stack([np.ones(len(x)), x])
    return x @ coefficients


def _standardization(
    frame: pd.DataFrame, features: tuple[str, ...]
) -> tuple[pd.Series, pd.Series]:
    means = frame.loc[:, features].mean(axis=0)
    scales = frame.loc[:, features].std(axis=0, ddof=0).replace(0, 1.0)
    return means, scales


def response_surface_dataset(
    table: pd.DataFrame,
    *,
    alpha: float = 1.0,
    features: tuple[str, ...] = ("day_of_year",),
) -> dict[str, pd.DataFrame]:
    """Fit leave-one-site-out ridge models over simulation response surfaces."""

    required = {
        "model",
        "environment_id",
        "site",
        "year",
        "planting_date",
        "dry_yield_mg_ha",
    }
    missing = required.difference(table.columns)
    if missing:
        raise ValueError(f"table is missing columns: {sorted(missing)}")
    if missing := set(features).difference(table.columns):
        raise ValueError(f"table is missing feature columns: {sorted(missing)}")
    frame = table.copy()
    frame["planting_date"] = pd.to_datetime(frame["planting_date"], errors="raise")
    frame["day_of_year"] = frame["planting_date"].dt.dayofyear
    frame["sin_doy"] = np.sin(2 * np.pi * frame["day_of_year"] / 365.25)
    frame["cos_doy"] = np.cos(2 * np.pi * frame["day_of_year"] / 365.25)
    model_features = tuple(dict.fromkeys((*features, "sin_doy", "cos_doy")))
    predictions: list[dict[str, object]] = []
    metrics: list[dict[str, object]] = []
    for model in sorted(frame["model"].unique()):
        model_frame = frame.loc[frame["model"].eq(model)].copy()
        for site in sorted(model_frame["site"].unique()):
            train = model_frame.loc[~model_frame["site"].eq(site)]
            test = model_frame.loc[model_frame["site"].eq(site)]
            means, scales = _standardization(train, model_features)
            coefficients, _ = ridge_fit(train, model_features, alpha=alpha)
            usable_test = test.loc[test["dry_yield_mg_ha"].notna()].copy()
            predicted = ridge_predict(
                usable_test, coefficients, means, scales, model_features
            )
            actual = pd.to_numeric(
                usable_test["dry_yield_mg_ha"], errors="raise"
            ).to_numpy(dtype=float)
            test_records = usable_test.assign(predicted_yield_mg_ha=predicted)
            for row in test_records.itertuples(index=False):
                predictions.append(
                    {
                        "model": row.model,
                        "environment_id": row.environment_id,
                        "planting_date": row.planting_date,
                        "dry_yield_mg_ha": row.dry_yield_mg_ha,
                        "predicted_yield_mg_ha": row.predicted_yield_mg_ha,
                        "holdout_site": site,
                        "leave_one_site_out": True,
                    }
                )
            metrics.append(
                {
                    "model": model,
                    "holdout_site": site,
                    "leave_one_site_out": True,
                    "record_count": len(usable_test),
                    "mean_absolute_error_mg_ha": float(
                        np.mean(np.abs(predicted - actual))
                    ),
                    "rmse_mg_ha": float(np.sqrt(np.mean((predicted - actual) ** 2))),
                }
            )
    return {
        "features": frame.loc[:, list(model_features)].assign(intercept=1.0)[
            ["intercept", *model_features]
        ],
        "predictions": pd.DataFrame(predictions),
        "metrics": pd.DataFrame(metrics),
    }


def add_weather_features(
    table: pd.DataFrame,
    weather: pd.DataFrame,
    *,
    pre_plant_days: int = 45,
    post_plant_days: int = 60,
) -> pd.DataFrame:
    """Add local weather aggregates around each candidate planting date."""

    required = {"environment_id", "date", *WEATHER_COLUMNS}
    if missing := required.difference(weather.columns):
        raise ValueError(f"weather is missing columns: {sorted(missing)}")
    required_table = {"environment_id", "planting_date"}
    if missing := required_table.difference(table.columns):
        raise ValueError(f"table is missing columns: {sorted(missing)}")
    frame = table.copy()
    frame["planting_date"] = pd.to_datetime(frame["planting_date"], errors="raise")
    weather_frame = weather.copy()
    weather_frame["date"] = pd.to_datetime(weather_frame["date"], errors="raise")
    weather_by_environment = {
        environment_id: group.sort_values("date")
        for environment_id, group in weather_frame.groupby("environment_id")
    }
    feature_rows: list[dict[str, object]] = []
    seen_keys: set[tuple[str, pd.Timestamp]] = set()
    builder = FixedWindowFeatureBuilder(
        pre_plant_days=pre_plant_days,
        post_plant_days=post_plant_days,
    )
    for row in frame.itertuples(index=False):
        environment_id = str(row.environment_id)
        environment_weather = weather_by_environment.get(environment_id)
        if environment_weather is None:
            raise ValueError(f"weather is missing environment {environment_id}")
        features = builder.build(environment_weather, row.planting_date)
        key = (environment_id, row.planting_date)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        feature_rows.append(
            {
                "environment_id": environment_id,
                "planting_date": row.planting_date,
                **vars(features),
            }
        )
    feature_table = pd.DataFrame(feature_rows)
    if feature_table[["environment_id", "planting_date"]].duplicated().any():
        raise ValueError("weather feature keys are duplicated")
    output = frame.merge(
        feature_table,
        on=["environment_id", "planting_date"],
        validate="many_to_one",
    )
    return output


def add_multiscale_residual_features(
    frame: pd.DataFrame,
    *,
    windows: tuple[int, ...] = (3, 5, 9),
) -> pd.DataFrame:
    """Add time-scale features to forecast-vs-oracle residual curves.

    Rolling features are intentionally computed within each environment and model.
    Interior windows are not padded, so edge missingness remains explicit.
    """

    required = {"model", "environment_id", "planting_date", "residual_mg_ha"}
    if missing := required.difference(frame.columns):
        raise ValueError(f"frame is missing columns: {sorted(missing)}")
    if not windows:
        raise ValueError("at least one window is required")
    if any(window < 1 or window % 2 == 0 for window in windows):
        raise ValueError("windows must be positive and odd")
    output = frame.copy()
    output["planting_date"] = pd.to_datetime(output["planting_date"], errors="raise")
    output = output.sort_values(["model", "environment_id", "planting_date"])
    grouped = output.groupby(["model", "environment_id"], sort=False)["residual_mg_ha"]
    environment_mean = grouped.transform("mean")
    output["residual_centered_mg_ha"] = output["residual_mg_ha"] - environment_mean
    for window in windows:
        output[f"residual_{window}d_mean_mg_ha"] = grouped.transform(
            lambda values: values.rolling(
                window, center=True, min_periods=window
            ).mean()
        )
    output["residual_shift_1d_mg_ha"] = grouped.shift(1)
    output["day_of_year"] = output["planting_date"].dt.dayofyear
    output["sin_doy"] = np.sin(2 * np.pi * output["day_of_year"] / 365.25)
    output["cos_doy"] = np.cos(2 * np.pi * output["day_of_year"] / 365.25)
    return output.reset_index(drop=True)


def _required_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    if missing := required.difference(frame.columns):
        raise ValueError(f"{name} is missing columns: {sorted(missing)}")


def residual_correction_dataset(
    curves: pd.DataFrame,
    *,
    alpha: float = 1.0,
    features: tuple[str, ...] = (
        "forecast_mean_yield_mg_ha",
        "forecast_p10_yield_mg_ha",
        "forecast_p90_yield_mg_ha",
        "residual_centered_mg_ha",
        "residual_3d_mean_mg_ha",
        "residual_5d_mean_mg_ha",
        "residual_9d_mean_mg_ha",
        "sin_doy",
        "cos_doy",
    ),
) -> dict[str, pd.DataFrame]:
    """Leave-one-environment-out residual correction for forecast curves.

    The target is the model-independent residual ``oracle - forecast``. The fitted
    correction is added to the original forecast. In small retrospective datasets
    this is best interpreted as a diagnostic rather than a deployable model.
    """

    _required_columns(
        curves,
        {
            "model",
            "environment_id",
            "planting_date",
            "forecast_mean_yield_mg_ha",
            "oracle_yield_mg_ha",
        },
        "curves",
    )
    effective_features = tuple(
        feature
        for feature in features
        if feature == "forecast_mean_yield_mg_ha"
        or feature in curves.columns
        or feature.startswith("residual_")
        or feature in {"sin_doy", "cos_doy"}
    )
    frame = curves.copy()
    frame["planting_date"] = pd.to_datetime(frame["planting_date"], errors="raise")
    frame["residual_mg_ha"] = pd.to_numeric(
        frame["oracle_yield_mg_ha"], errors="raise"
    ) - pd.to_numeric(frame["forecast_mean_yield_mg_ha"], errors="raise")
    frame = add_multiscale_residual_features(frame)
    effective_features = tuple(
        feature for feature in effective_features if feature in frame.columns
    )
    if not effective_features:
        raise ValueError("no residual-correction features are available")
    usable = frame.loc[frame[list(effective_features)].notna().all(axis=1)].copy()
    if usable.empty:
        # Short diagnostic curves may not support interior rolling windows.
        # Fall back to features that are defined on every candidate date.
        usable = frame.copy()
        effective_features = tuple(
            feature for feature in effective_features if usable[feature].notna().all()
        )
    if missing := set(effective_features).difference(usable.columns):
        raise ValueError(f"feature columns are missing: {sorted(missing)}")
    predictions: list[dict[str, object]] = []
    metrics: list[dict[str, object]] = []
    environments = sorted(usable["environment_id"].unique())
    for holdout in environments:
        train = usable.loc[~usable["environment_id"].eq(holdout)].copy()
        test = usable.loc[usable["environment_id"].eq(holdout)].copy()
        if train.empty or test.empty:
            raise ValueError("residual correction requires nonempty train/test folds")
        means, scales = _standardization(train, effective_features)
        coefficients, _ = ridge_fit(
            train, effective_features, target="residual_mg_ha", alpha=alpha
        )
        correction = ridge_predict(
            test, coefficients, means, scales, effective_features
        )
        corrected = (
            pd.to_numeric(test["forecast_mean_yield_mg_ha"], errors="raise").to_numpy(
                dtype=float
            )
            + correction
        )
        baseline = pd.to_numeric(
            test["forecast_mean_yield_mg_ha"], errors="raise"
        ).to_numpy(dtype=float)
        oracle = pd.to_numeric(test["oracle_yield_mg_ha"], errors="raise").to_numpy(
            dtype=float
        )
        for row, value, base, truth in zip(
            test.itertuples(index=False), correction, baseline, oracle, strict=True
        ):
            predictions.append(
                {
                    "model": row.model,
                    "environment_id": row.environment_id,
                    "holdout_environment_id": holdout,
                    "planting_date": row.planting_date,
                    "forecast_mean_yield_mg_ha": base,
                    "oracle_yield_mg_ha": truth,
                    "residual_mg_ha": truth - base,
                    "residual_fitted_mg_ha": value,
                    "corrected_forecast_yield_mg_ha": base + value,
                }
            )
        metrics.append(
            {
                "model": "multimodel",
                "holdout_environment_id": holdout,
                "fold": "leave_one_environment_out",
                "record_count": len(test),
                "baseline_mae_mg_ha": float(np.mean(np.abs(baseline - oracle))),
                "corrected_mae_mg_ha": float(np.mean(np.abs(corrected - oracle))),
                "mae_reduction_mg_ha": float(
                    np.mean(np.abs(baseline - oracle))
                    - np.mean(np.abs(corrected - oracle))
                ),
            }
        )
    return {
        "predictions": pd.DataFrame(predictions),
        "metrics": pd.DataFrame(metrics),
    }
