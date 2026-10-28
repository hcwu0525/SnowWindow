"""Human-readable reports for planting-date experiments."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from snowwindow.config import ExperimentConfig
from snowwindow.domain import ModelCapabilities
from snowwindow.weather import G2F_END_DATE, weather_end_for_year

DEFAULT_REPORT_NOTES = (
    "- 开花日期采用 AquaCrop `HIstart` 首次跨越的日末代理，并非独立花粉事件。",
    "- 默认土壤仅用于探索；缺失灌溉信息按配置标记为假定雨养。",
    "- 全局校准仅拟合 `phenology_scale` 与 `HI0`；根深、灌溉和土壤水力参数固定。",
    "- `site_calibrated` 在全局参数基础上应用满足训练年数要求的站点偏移。",
)


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_无数据_"
    values = frame.fillna("").astype(str)
    header = "| " + " | ".join(values.columns) + " |"
    separator = "| " + " | ".join("---" for _ in values.columns) + " |"
    rows = [
        "| " + " | ".join(value.replace("|", "\\|") for value in row) + " |"
        for row in values.itertuples(index=False, name=None)
    ]
    return "\n".join([header, separator, *rows])


def _observed_points(
    metrics: pd.DataFrame,
    predictions: pd.DataFrame,
    baseline: pd.DataFrame,
    *,
    variable: str,
) -> pd.DataFrame:
    if predictions.empty or baseline.empty:
        return pd.DataFrame(
            columns=["environment_id", "planting_date", "observed_value"]
        )
    if (
        metrics.empty
        or "environment_id" not in metrics
        or "observed_value" not in metrics
    ):
        metrics = predictions
    held = metrics.loc[
        metrics["fold"].eq("held_year") & metrics["variable"].eq(variable)
    ]
    if held.empty:
        return pd.DataFrame(
            columns=["environment_id", "planting_date", "observed_value"]
        )
    points = (
        held[["environment_id", "observed_value"]]
        .drop_duplicates("environment_id")
        .merge(
            baseline[["environment_id", "planting_date"]],
            on="environment_id",
            how="inner",
            validate="one_to_one",
        )
    )
    return points.sort_values("environment_id").reset_index(drop=True)


def observed_yield_points(
    metrics: pd.DataFrame,
    predictions: pd.DataFrame,
    baseline: pd.DataFrame,
) -> pd.DataFrame:
    """Return one G2F observed yield point per representative environment."""

    return _observed_points(
        metrics,
        predictions,
        baseline,
        variable="dry_yield_mg_ha",
    )


def observed_flowering_points(
    metrics: pd.DataFrame,
    predictions: pd.DataFrame,
    baseline: pd.DataFrame,
) -> pd.DataFrame:
    """Return one G2F observed pollen-date point per representative environment."""

    points = _observed_points(
        metrics,
        predictions,
        baseline,
        variable="pollen_dap",
    )
    points["observed_date"] = pd.to_datetime(
        points["planting_date"], errors="coerce"
    ) + pd.to_timedelta(
        pd.to_numeric(points["observed_value"], errors="coerce"), unit="D"
    )
    return points


def simulated_flowering_dates(frame: pd.DataFrame) -> pd.Series:
    """Convert planting dates and flowering DAP to calendar timestamps."""

    return pd.to_datetime(frame["planting_date"], errors="coerce") + pd.to_timedelta(
        pd.to_numeric(frame["flowering_proxy_dap"], errors="coerce"),
        unit="D",
    )


def report_stage(config: ExperimentConfig) -> Path:
    capabilities = getattr(
        getattr(config, "model", None),
        "capabilities",
        ModelCapabilities(display_name="AquaCrop", report_notes=DEFAULT_REPORT_NOTES),
    )
    model_label = capabilities.display_name
    scan_root = config.experiment_dir / "scan"
    summary_path = scan_root / "summary.parquet"
    windows_path = scan_root / "windows.json"
    if not summary_path.is_file() or not windows_path.is_file():
        raise FileNotFoundError("scan artifacts are missing")
    summary = pd.read_parquet(summary_path)
    windows = json.loads(windows_path.read_text(encoding="utf-8"))
    if "dry_yield_mg_ha" not in summary:
        raise ValueError(
            "scan summary is missing dry_yield_mg_ha for observed comparison"
        )
    metrics_path = config.experiment_dir / "validation/metrics.parquet"
    metrics = (
        pd.read_parquet(metrics_path) if metrics_path.is_file() else pd.DataFrame()
    )
    predictions_path = config.experiment_dir / "validation/predictions.parquet"
    predictions = (
        pd.read_parquet(predictions_path)
        if predictions_path.is_file()
        else pd.DataFrame()
    )
    baseline_path = config.experiment_dir / "baseline/summary.parquet"
    baseline = (
        pd.read_parquet(baseline_path) if baseline_path.is_file() else pd.DataFrame()
    )
    observations = observed_yield_points(metrics, predictions, baseline)
    flowering_observations = observed_flowering_points(metrics, predictions, baseline)

    figure_dir = config.experiment_dir / "report/figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    for environment_id, group in summary.groupby("environment_id", sort=True):
        figure, axis = plt.subplots(figsize=(9, 4.5))
        for parameter_set, series in group.groupby("parameter_set", sort=True):
            ordered = series.sort_values("planting_date")
            dates = pd.to_datetime(ordered["planting_date"])
            yield_values = pd.to_numeric(
                ordered["dry_yield_mg_ha"], errors="coerce"
            ).where(ordered["status"].eq("matured"))
            axis.plot(dates, yield_values, label=parameter_set)
        if not observations.empty:
            observed = observations.loc[
                observations["environment_id"].eq(environment_id)
            ]
            if not observed.empty:
                axis.scatter(
                    pd.to_datetime(observed["planting_date"]),
                    pd.to_numeric(observed["observed_value"], errors="coerce"),
                    marker="*",
                    s=90,
                    color="black",
                    label="G2F observed",
                    zorder=3,
                )
        axis.set_title(f"{environment_id} full-year planting scan")
        axis.set_ylabel("Dry yield (Mg/ha)")
        axis.set_xlabel("Planting date")
        axis.legend()
        figure.autofmt_xdate()
        figure.tight_layout()
        figure.savefig(figure_dir / f"{environment_id}.png", dpi=150)
        plt.close(figure)

        if "flowering_proxy_dap" in group:
            flowering_figure, flowering_axis = plt.subplots(figsize=(9, 4.5))
            for parameter_set, series in group.groupby("parameter_set", sort=True):
                ordered = series.sort_values("planting_date")
                flowering_axis.plot(
                    pd.to_datetime(ordered["planting_date"]),
                    pd.to_numeric(ordered["flowering_proxy_dap"], errors="coerce"),
                    label=parameter_set,
                )
            if not flowering_observations.empty:
                observed = flowering_observations.loc[
                    flowering_observations["environment_id"].eq(environment_id)
                ]
                if not observed.empty:
                    flowering_axis.scatter(
                        pd.to_datetime(observed["planting_date"]),
                        pd.to_numeric(observed["observed_value"], errors="coerce"),
                        marker="*",
                        s=90,
                        color="black",
                        label="G2F observed pollen",
                        zorder=3,
                    )
            flowering_axis.set_title(f"{environment_id} flowering response")
            flowering_axis.set_ylabel("Flowering after planting (days)")
            flowering_axis.set_xlabel("Planting date")
            flowering_axis.legend()
            flowering_figure.autofmt_xdate()
            flowering_figure.tight_layout()
            flowering_figure.savefig(
                figure_dir / f"{environment_id}_flowering.png", dpi=150
            )
            plt.close(flowering_figure)

        if "flowering_proxy_dap" in group:
            flowering_date_figure, flowering_date_axis = plt.subplots(figsize=(9, 4.5))
            for parameter_set, series in group.groupby("parameter_set", sort=True):
                ordered = series.sort_values("planting_date")
                flowering_date_axis.plot(
                    pd.to_datetime(ordered["planting_date"]),
                    simulated_flowering_dates(ordered),
                    label=parameter_set,
                )
            if not flowering_observations.empty:
                observed = flowering_observations.loc[
                    flowering_observations["environment_id"].eq(environment_id)
                ]
                if not observed.empty:
                    flowering_date_axis.scatter(
                        pd.to_datetime(observed["planting_date"]),
                        observed["observed_date"],
                        marker="*",
                        s=90,
                        color="black",
                        label="G2F observed pollen",
                        zorder=3,
                    )
            flowering_date_axis.set_title(f"{environment_id} flowering calendar date")
            flowering_date_axis.set_ylabel("Flowering date")
            flowering_date_axis.set_xlabel("Planting date")
            flowering_date_axis.yaxis.set_major_locator(mdates.MonthLocator(interval=2))
            flowering_date_axis.yaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
            flowering_date_axis.legend()
            flowering_date_figure.autofmt_xdate()
            flowering_date_figure.tight_layout()
            flowering_date_figure.savefig(
                figure_dir / f"{environment_id}_flowering_date.png",
                dpi=150,
            )
            plt.close(flowering_date_figure)

    status = (
        summary.groupby(["environment_id", "parameter_set", "status"])
        .size()
        .rename("count")
        .reset_index()
    )
    held_metrics = (
        metrics.loc[
            metrics.get("fold", pd.Series(dtype=str)).eq("held_year")
            & metrics.get("split", pd.Series(dtype=str)).eq("test")
        ]
        if not metrics.empty
        else metrics
    )
    model_notes = list(capabilities.report_notes)
    evaluation_years = getattr(
        getattr(config, "selection", None), "evaluation_years", ()
    )
    evaluation_label = ", ".join(str(year) for year in evaluation_years)
    calendar_notes = []
    for year in evaluation_years:
        start = date(year, 1, 1)
        end = weather_end_for_year(year)
        days = (end - start).days + 1
        calendar_notes.append(
            f"- 评估年播期日历范围：{start.isoformat()} 至 {end.isoformat()}"
            f"（含首尾 {days} 天）。"
        )
    report = [
        f"# G2F {model_label} 全年播期扫描报告",
        "",
        f"- 扫描记录：{len(summary):,} 行。",
        f"- 环境数：{summary['environment_id'].nunique()}。",
        f"- 参数组：{', '.join(sorted(summary['parameter_set'].unique()))}。",
        "- 气象驱动：仅使用规范化 G2F `full_year` 天气；"
        f"最晚日期为 {G2F_END_DATE.isoformat()}（含当日）。",
        "- 保留闰日，缺日与缺失值保持原样，不补齐、不插值或零填充；"
        "不使用外部天气下载或历史缓存回退。",
        *calendar_notes,
        *model_notes,
        "- 实际播期观测点仅用于验证当年真实处理；"
        "日历范围内的逐日播期曲线是反事实情景，不代表每天均有完整气象或成功模拟。",
        "",
        "## 状态统计",
        "",
        _markdown_table(status),
        "",
        "## 90% 与 95% 适播窗口",
        "",
        _markdown_table(pd.DataFrame(windows)),
    ]
    if not held_metrics.empty:
        report.extend(
            [
                "",
                (
                    f"## {evaluation_label} 留年验证"
                    if evaluation_label
                    else "## 留年验证"
                ),
                "",
                _markdown_table(held_metrics),
            ]
        )
    report.extend(
        [
            "",
            "## 使用限制",
            "",
            "结果用于流程验证和播期响应比较。绝对产量受通用品种参数、均质土层、雨养假设及气象来源影响；异常状态完整保留，不参与适播窗口计算。",
            "",
        ]
    )
    path = config.experiment_dir / "report/report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(report), encoding="utf-8")
    return path
