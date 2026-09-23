"""Human-readable reports for planting-date experiments."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from snowwindow.config import ExperimentConfig


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


def observed_yield_points(
    metrics: pd.DataFrame,
    predictions: pd.DataFrame,
    baseline: pd.DataFrame,
) -> pd.DataFrame:
    """Return one G2F observed yield point per representative environment."""

    if metrics.empty or predictions.empty or baseline.empty:
        return pd.DataFrame(
            columns=["environment_id", "planting_date", "observed_value"]
        )
    if "environment_id" not in metrics or "observed_value" not in metrics:
        metrics = predictions
    held = metrics.loc[
        metrics["fold"].eq("held_year") & metrics["variable"].eq("dry_yield_mg_ha")
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


def report_stage(config: ExperimentConfig) -> Path:
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

    figure_dir = config.experiment_dir / "report/figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
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
    report = [
        "# G2F AquaCrop 全年播期扫描报告",
        "",
        f"- 扫描记录：{len(summary):,} 行。",
        f"- 环境数：{summary['environment_id'].nunique()}。",
        f"- 参数组：{', '.join(sorted(summary['parameter_set'].unique()))}。",
        "- 气象驱动：已缓存的同坐标 NASA POWER AG 全年数据；不等同于竞赛站点原始天气。",
        "- 开花日期采用 AquaCrop `HIstart` 首次跨越的日末代理，并非独立花粉事件。",
        "- 默认土壤仅用于探索；缺失灌溉信息按配置标记为假定雨养。",
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
                "## 2023 留年验证",
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
