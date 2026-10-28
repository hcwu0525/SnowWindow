#!/usr/bin/env python
"""Draw one-model forecast-versus-oracle planting-date comparison figures."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

MODEL_RUNS = {
    "aquacrop": {
        "label": "AquaCrop",
        "forecast_dir": "outputs/experiments/g2f_forecast_demo_radius30/forecast",
        "oracle_file": "outputs/experiments/g2f_demo/scan/summary.csv",
    },
    "apsim": {
        "label": "APSIM",
        "forecast_dir": "outputs/experiments/g2f_apsim_forecast_demo_radius30/forecast",
        "oracle_file": "outputs/experiments/g2f_apsim_demo/scan/summary.csv",
    },
    "dssat": {
        "label": "DSSAT",
        "forecast_dir": "outputs/experiments/g2f_dssat_forecast_demo_radius30/forecast",
        "oracle_file": "outputs/experiments/g2f_dssat_demo/scan/summary.csv",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", default="NYH2_2023")
    parser.add_argument("--radius", type=int, default=30, choices=[14, 30])
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path)


def environment_record(frame: pd.DataFrame, environment_id: str) -> pd.Series:
    records = frame.loc[frame["environment_id"] == environment_id]
    if records.empty:
        raise ValueError(
            f"No record for environment {environment_id!r} in {frame.shape}",
        )
    if len(records) != 1:
        raise ValueError(
            f"Expected one recommendation for {environment_id!r}, got {len(records)}",
        )
    return records.iloc[0]


def plot_model(
    model_key: str,
    model_config: dict[str, str],
    environment_id: str,
    radius: int,
    root: Path,
    output_dir: Path,
) -> Path:
    forecast_dir = root / model_config["forecast_dir"]
    forecast = read_csv(forecast_dir / "forecast_curves.csv")
    recommendations = read_csv(forecast_dir / "recommendations.csv")
    oracle = read_csv(root / model_config["oracle_file"])

    forecast = forecast.loc[forecast["environment_id"] == environment_id].copy()
    recommendation = environment_record(recommendations, environment_id)

    oracle = oracle.loc[
        (oracle["environment_id"] == environment_id)
        & (oracle["parameter_set"] == "calibrated")
        & (oracle["status"] == "matured")
        & oracle["dry_yield_mg_ha"].notna()
    ].copy()
    if forecast.empty or oracle.empty:
        raise ValueError(f"Insufficient curves for {model_key} / {environment_id}")

    date_columns = [
        "planting_date",
        "forecast_best_date",
        "oracle_best_date",
        "observed_planting_date",
    ]
    for column in date_columns:
        if column == "planting_date":
            forecast[column] = pd.to_datetime(forecast[column])
            oracle[column] = pd.to_datetime(oracle[column])
        else:
            recommendation[column] = pd.to_datetime(recommendation[column])

    observed_date = recommendation["observed_planting_date"]
    observations = read_csv(
        (root / model_config["oracle_file"]).parent.parent
        / "validation/predictions.csv"
    )
    observation = observations.loc[
        observations["environment_id"].eq(environment_id)
        & observations["fold"].eq("held_year")
        & observations["parameter_set_id"].eq("calibrated")
        & observations["variable"].eq("dry_yield_mg_ha")
    ]
    if len(observation) != 1:
        raise ValueError(f"Expected one observed yield for {environment_id}")
    if not str(observation.iloc[0]["management_unit_id"]).endswith(
        observed_date.date().isoformat()
    ):
        raise ValueError("Observed yield does not match the actual planting date")
    actual_observed_yield = float(observation.iloc[0]["observed_value"])
    if not pd.notna(actual_observed_yield) or actual_observed_yield <= 0:
        raise ValueError("Observed dry yield must be positive and finite")
    window_start = observed_date - pd.Timedelta(days=radius)
    window_end = observed_date + pd.Timedelta(days=radius)
    forecast = forecast.loc[
        forecast["planting_date"].between(window_start, window_end)
    ].sort_values("planting_date")
    oracle = oracle.loc[
        oracle["planting_date"].between(window_start, window_end)
    ].sort_values("planting_date")

    fig, ax = plt.subplots(figsize=(14.5, 8.2), constrained_layout=True)
    fig.patch.set_facecolor("#fafafa")
    ax.set_facecolor("#ffffff")

    ax.fill_between(
        forecast["planting_date"],
        forecast["forecast_p10_yield_mg_ha"],
        forecast["forecast_p90_yield_mg_ha"],
        color="#F28E2B",
        alpha=0.17,
        linewidth=0,
        label="Forecast P10–P90",
        zorder=1,
    )
    ax.plot(
        forecast["planting_date"],
        forecast["forecast_mean_yield_mg_ha"],
        color="#F28E2B",
        linewidth=3.0,
        label="Forecast mean",
        zorder=3,
    )
    ax.plot(
        oracle["planting_date"],
        oracle["dry_yield_mg_ha"],
        color="#2CA02C",
        linewidth=3.0,
        label=f"Oracle ({observed_date.year} actual weather)",
        zorder=4,
    )

    observed_date_num = mdates.date2num(observed_date)
    forecast_date_num = mdates.date2num(recommendation["forecast_best_date"])
    oracle_date_num = mdates.date2num(recommendation["oracle_best_date"])

    y_min = min(
        actual_observed_yield,
        forecast["forecast_p10_yield_mg_ha"].min(),
        oracle["dry_yield_mg_ha"].min(),
        float(recommendation["forecast_best_forecast_yield_mg_ha"]),
        float(recommendation["forecast_best_oracle_yield_mg_ha"]),
        float(recommendation["observed_oracle_yield_mg_ha"]),
        float(recommendation["oracle_maximum_yield_mg_ha"]),
    )
    y_max = max(
        actual_observed_yield,
        forecast["forecast_p90_yield_mg_ha"].max(),
        oracle["dry_yield_mg_ha"].max(),
        float(recommendation["forecast_best_forecast_yield_mg_ha"]),
        float(recommendation["forecast_best_oracle_yield_mg_ha"]),
        float(recommendation["observed_oracle_yield_mg_ha"]),
        float(recommendation["oracle_maximum_yield_mg_ha"]),
    )
    y_padding = max(0.45, (y_max - y_min) * 0.09)
    y_bottom = y_min - y_padding
    y_top = y_max + y_padding
    ax.set_ylim(y_bottom, y_top)

    observed_yield = float(recommendation["observed_oracle_yield_mg_ha"])
    ax.vlines(
        observed_date_num,
        y_bottom,
        max(observed_yield, actual_observed_yield),
        color="#4E79A7",
        linestyle="--",
        linewidth=2.3,
        alpha=0.88,
        zorder=5,
    )
    ax.scatter(
        observed_date_num,
        observed_yield,
        s=160,
        marker="s",
        facecolor="white",
        edgecolor="#4E79A7",
        linewidth=2.3,
        label="Actual planting (oracle yield)",
        zorder=7,
    )
    ax.scatter(
        observed_date_num,
        actual_observed_yield,
        s=160,
        marker="s",
        color="#4E79A7",
        edgecolor="white",
        linewidth=1.6,
        label="Actual planting (observed yield)",
        zorder=7,
    )

    forecast_predicted_yield = float(
        recommendation["forecast_best_forecast_yield_mg_ha"],
    )
    forecast_oracle_yield = float(
        recommendation["forecast_best_oracle_yield_mg_ha"],
    )
    forecast_line_top = max(forecast_predicted_yield, forecast_oracle_yield)
    ax.vlines(
        forecast_date_num,
        y_bottom,
        forecast_line_top,
        color="#F28E2B",
        linestyle="--",
        linewidth=2.3,
        alpha=0.82,
        zorder=5,
    )
    ax.scatter(
        forecast_date_num,
        forecast_predicted_yield,
        s=175,
        marker="^",
        color="#F28E2B",
        edgecolor="white",
        linewidth=1.6,
        label="Forecast best (forecast yield)",
        zorder=8,
    )
    ax.scatter(
        forecast_date_num,
        forecast_oracle_yield,
        s=175,
        marker="v",
        facecolor="white",
        edgecolor="#F28E2B",
        linewidth=2.3,
        label="Forecast best (oracle yield)",
        zorder=8,
    )

    oracle_max_yield = float(recommendation["oracle_maximum_yield_mg_ha"])
    ax.vlines(
        oracle_date_num,
        y_bottom,
        oracle_max_yield,
        color="#009E73",
        linestyle="--",
        linewidth=2.3,
        alpha=0.88,
        zorder=5,
    )
    ax.scatter(
        oracle_date_num,
        oracle_max_yield,
        s=190,
        marker="D",
        color="#009E73",
        edgecolor="white",
        linewidth=1.6,
        label="Oracle best",
        zorder=8,
    )

    annotations = [
        ("Actual", observed_date_num, actual_observed_yield, "#4E79A7", (14, 18)),
        (
            "Forecast",
            forecast_date_num,
            forecast_line_top,
            "#F28E2B",
            (14, -38),
        ),
        ("Oracle", oracle_date_num, oracle_max_yield, "#009E73", (14, 24)),
    ]
    for label, x_value, y_value, color, offset in annotations:
        ax.annotate(
            label,
            xy=(x_value, y_value),
            xytext=offset,
            textcoords="offset points",
            color=color,
            fontsize=12,
            fontweight="bold",
            va="center",
            bbox={
                "boxstyle": "round,pad=0.25",
                "facecolor": "white",
                "edgecolor": "none",
                "alpha": 0.9,
            },
            zorder=9,
        )

    ax.set_title(
        f"{model_config['label']} · {environment_id}",
        loc="left",
        fontsize=19,
        fontweight="bold",
        pad=18,
    )
    ax.text(
        0.0,
        1.015,
        f"Forecast vs. oracle response · ±{radius} days around actual planting",
        transform=ax.transAxes,
        fontsize=12,
        color="#4d4d4d",
    )
    ax.set_xlabel("Candidate planting date", fontsize=12)
    ax.set_ylabel("Dry yield (Mg/ha)", fontsize=12)
    ax.grid(axis="y", color="#d9d9d9", linewidth=0.8, alpha=0.65)
    ax.grid(axis="x", color="#e8e8e8", linewidth=0.6, alpha=0.5)
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=5))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax.tick_params(axis="both", labelsize=10)
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.12),
        ncols=4,
        frameon=False,
        fontsize=10,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / (
        f"model_comparison_{environment_id}_{model_key}_forecastoracle_radius{radius}.png"
    )
    fig.savefig(
        output_path,
        dpi=240,
        bbox_inches="tight",
        facecolor=fig.get_facecolor(),
    )
    fig.savefig(
        output_path.with_suffix(".pdf"),
        bbox_inches="tight",
        facecolor=fig.get_facecolor(),
    )
    fig.savefig(
        output_path.with_suffix(".svg"),
        bbox_inches="tight",
        facecolor=fig.get_facecolor(),
    )
    plt.close(fig)
    return output_path


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    output_dir = args.output_dir
    if output_dir is None:
        output_dir = root / "outputs/experiments/g2f_window_ml_exploration/figures"
    output_dir = output_dir.resolve()

    paths = [
        plot_model(key, config, args.environment, args.radius, root, output_dir)
        for key, config in MODEL_RUNS.items()
    ]
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
