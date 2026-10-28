"""Retrospective planting-date forecast demo built on the simulation loop."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
import yaml

from snowwindow.adapters import ModelAdapter, resolve_model_adapter
from snowwindow.config import ConfigError, ExperimentConfig
from snowwindow.domain import SimulationRequest, SimulationResult
from snowwindow.experiment import (
    WEATHER_COLUMNS,
    build_simulation_request,
    select_representative_units,
    weather_failure_result,
)
from snowwindow.weather import G2F_END_DATE, WEATHER_POLICY, weather_end_for_year

DEFAULT_CUTOFF_MONTH = 3
DEFAULT_CUTOFF_DAY = 1
DEFAULT_RADIUS_DAYS = 14
DEFAULT_STEP_DAYS = 1
DEFAULT_FRACTION = 0.95


def candidate_dates(
    observed_planting_date: date,
    *,
    radius_days: int = DEFAULT_RADIUS_DAYS,
    step_days: int = DEFAULT_STEP_DAYS,
) -> tuple[date, ...]:
    """Return candidates around the observed date within the G2F data boundary."""

    if radius_days < 0 or step_days <= 0:
        raise ValueError("radius_days must be nonnegative and step_days positive")
    if observed_planting_date > G2F_END_DATE:
        raise ValueError(f"planting date exceeds G2F weather end {G2F_END_DATE}")
    offsets = set(range(-radius_days, radius_days + 1, step_days))
    offsets.add(0)
    return tuple(
        date.fromordinal(observed_planting_date.toordinal() + offset)
        for offset in sorted(offsets)
        if date.fromordinal(observed_planting_date.toordinal() + offset) <= G2F_END_DATE
    )


def weather_scenarios(
    weather: pd.DataFrame,
    *,
    environment_id: str,
    site: str,
    target_year: int,
    cutoff_date: date,
) -> dict[int, pd.DataFrame]:
    """Construct historical-weather scenarios without target-year future leakage.

    Each scenario keeps realized target weather through ``cutoff_date`` and
    substitutes weather after that date with the corresponding day from one
    historical year at the same site. Calendar dates remain in the target year.
    """

    required = {"environment_id", "date", *WEATHER_COLUMNS}
    period_end = weather_end_for_year(target_year)
    if cutoff_date.year != target_year or cutoff_date > period_end:
        raise ValueError(
            f"forecast cutoff must be within {target_year}-01-01..{period_end}"
        )
    missing = required.difference(weather.columns)
    if missing:
        raise ValueError(f"weather is missing columns: {sorted(missing)}")
    frame = weather.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    target = frame.loc[frame["environment_id"].eq(environment_id)].copy()
    prefix = target.loc[target["date"].le(pd.Timestamp(cutoff_date))].sort_values(
        "date"
    )
    if prefix.empty:
        raise ValueError(f"no realized target weather through {cutoff_date}")
    expected_prefix = pd.date_range(date(target_year, 1, 1), cutoff_date)
    if set(prefix["date"]) != set(expected_prefix):
        raise ValueError(
            f"target weather is not complete from {date(target_year, 1, 1)} "
            f"through {cutoff_date}"
        )

    target_dates = pd.date_range(date(target_year, 1, 1), period_end)
    history = frame.loc[
        frame["environment_id"].str.fullmatch(rf"{re_escape(site)}_\d{{4}}")
        & frame["environment_id"].ne(environment_id)
    ].copy()
    history_rows = {
        environment_id: group.sort_values("date").reset_index(drop=True)
        for environment_id, group in history.groupby("environment_id", sort=True)
    }
    prefix_by_day = {row.date.date(): row for row in prefix.itertuples(index=False)}
    scenarios: dict[int, pd.DataFrame] = {}
    for source_environment_id, source_year in sorted(
        (
            (str(value), int(value.rsplit("_", 1)[1]))
            for value in history["environment_id"].unique()
        ),
        key=lambda item: item[1],
    ):
        if source_year >= target_year:
            continue
        rows: list[dict[str, Any]] = []
        for target_timestamp in target_dates:
            target_day = target_timestamp.date()
            if target_day <= cutoff_date:
                source_row = prefix_by_day[target_day]
                rows.append(
                    {
                        "environment_id": environment_id,
                        "date": target_timestamp,
                        **{
                            column: getattr(source_row, column)
                            for column in WEATHER_COLUMNS
                        },
                        "scenario_year": target_year,
                        "scenario_source_environment_id": environment_id,
                        "scenario_source_date": target_timestamp,
                    }
                )
                continue
            source_environment_rows = history_rows[source_environment_id]
            if (
                target_timestamp.month,
                target_timestamp.day,
            ) == (2, 29) and source_year % 4 != 0:
                source_date = pd.Timestamp(source_year, 2, 28)
            else:
                source_date = pd.Timestamp(
                    source_year,
                    target_timestamp.month,
                    target_timestamp.day,
                )
            source_row = source_environment_rows.loc[
                source_environment_rows["date"].eq(source_date)
            ]
            if source_row.empty:
                continue
            source_row = source_row.iloc[0]
            rows.append(
                {
                    "environment_id": environment_id,
                    "date": target_timestamp,
                    **{
                        column: getattr(source_row, column)
                        for column in WEATHER_COLUMNS
                    },
                    "scenario_year": source_year,
                    "scenario_source_environment_id": source_environment_id,
                    "scenario_source_date": source_row.date,
                }
            )
        if len(rows) != len(target_dates):
            raise ValueError(
                f"incomplete {source_environment_id} scenario: "
                f"expected {len(target_dates)} rows, got {len(rows)}"
            )
        scenario = pd.DataFrame(rows)
        if scenario["date"].duplicated().any():
            raise ValueError(f"duplicate dates in {source_year} weather scenario")
        scenarios[source_year] = scenario.sort_values("date").reset_index(drop=True)
    return scenarios


def re_escape(value: str) -> str:
    """Escape a site identifier for use in an exact regular-expression match."""

    return "".join(
        character if character.isalnum() else f"\\{character}" for character in value
    )


def _dates_as_date(frame: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(frame["planting_date"], errors="raise").dt.date


def _recommended_dates(
    frame: pd.DataFrame, value_column: str, fraction: float
) -> list[date]:
    values = pd.to_numeric(frame[value_column], errors="coerce")
    usable = frame.loc[values.gt(0)].copy()
    usable["planting_date"] = _dates_as_date(usable)
    if usable.empty:
        return []
    maximum = float(values.loc[usable.index].max())
    return sorted(
        usable.loc[values.loc[usable.index].ge(maximum * fraction), "planting_date"]
        .unique()
        .tolist()
    )


def score_forecast_recommendation(
    forecast: pd.DataFrame,
    oracle: pd.DataFrame,
    *,
    fraction: float,
    observed_planting_date: date,
) -> dict[str, Any]:
    """Score a forecast curve against the actual-year simulation oracle."""

    if not 0 < fraction <= 1:
        raise ValueError("fraction must be in (0, 1]")
    if "forecast_mean_yield_mg_ha" not in forecast:
        raise ValueError("forecast curve is missing forecast_mean_yield_mg_ha")
    if "dry_yield_mg_ha" not in oracle:
        raise ValueError("oracle is missing dry_yield_mg_ha")
    usable_oracle = oracle.copy()
    if "status" in usable_oracle:
        usable_oracle = usable_oracle.loc[usable_oracle["status"].eq("matured")].copy()
    oracle_values = pd.to_numeric(usable_oracle["dry_yield_mg_ha"], errors="coerce")
    usable_oracle = usable_oracle.loc[oracle_values.gt(0)].copy()
    if usable_oracle.empty:
        raise ValueError("oracle has no positive matured yields")

    forecast_dates = _recommended_dates(forecast, "forecast_mean_yield_mg_ha", fraction)
    usable_oracle["planting_date"] = _dates_as_date(usable_oracle)
    oracle_window = usable_oracle.loc[
        usable_oracle["planting_date"].isin(forecast_dates)
    ]
    if oracle_window.empty:
        raise ValueError("oracle has no positive matured yields in candidate window")
    oracle_dates = _recommended_dates(oracle_window, "dry_yield_mg_ha", fraction)
    overlap = sorted(set(forecast_dates).intersection(oracle_dates))
    merged = forecast.copy()
    merged["planting_date"] = _dates_as_date(merged)
    merged = merged.merge(
        usable_oracle.assign(planting_date=_dates_as_date(usable_oracle))[
            ["planting_date", "dry_yield_mg_ha"]
        ],
        on="planting_date",
        how="inner",
        validate="one_to_one",
    )
    if merged.empty:
        raise ValueError("forecast and oracle planting dates do not overlap")
    merged["dry_yield_mg_ha"] = pd.to_numeric(
        merged["dry_yield_mg_ha"], errors="coerce"
    )
    forecast_means = pd.to_numeric(merged["forecast_mean_yield_mg_ha"], errors="coerce")
    forecast_best = merged.loc[forecast_means.idxmax()]
    oracle_best = merged.loc[merged["dry_yield_mg_ha"].idxmax()]
    observed = merged.loc[merged["planting_date"].eq(observed_planting_date)]
    if observed.empty:
        raise ValueError("observed planting date is absent from the oracle curve")
    observed_yield = float(observed.iloc[0]["dry_yield_mg_ha"])
    oracle_maximum = float(merged["dry_yield_mg_ha"].max())
    forecast_best_yield = float(forecast_best["dry_yield_mg_ha"])
    recommended_yields = merged.loc[
        merged["planting_date"].isin(forecast_dates), "dry_yield_mg_ha"
    ]
    return {
        "fraction": float(fraction),
        "forecast_recommended_dates": [value.isoformat() for value in forecast_dates],
        "oracle_recommended_dates": [value.isoformat() for value in oracle_dates],
        "overlap_days": len(overlap),
        "recommended_window_coverage": (
            len(overlap) / len(forecast_dates) if forecast_dates else None
        ),
        "forecast_best_date": forecast_best["planting_date"].isoformat(),
        "oracle_best_date": oracle_best["planting_date"].isoformat(),
        "forecast_best_forecast_yield_mg_ha": float(
            forecast_best["forecast_mean_yield_mg_ha"]
        ),
        "forecast_best_oracle_yield_mg_ha": forecast_best_yield,
        "oracle_maximum_yield_mg_ha": oracle_maximum,
        "forecast_best_regret_mg_ha": oracle_maximum - forecast_best_yield,
        "recommended_window_mean_oracle_yield_mg_ha": (
            float(recommended_yields.mean()) if not recommended_yields.empty else None
        ),
        "recommended_window_median_regret_mg_ha": (
            float((oracle_maximum - recommended_yields).median())
            if not recommended_yields.empty
            else None
        ),
        "observed_planting_date": observed_planting_date.isoformat(),
        "observed_oracle_yield_mg_ha": observed_yield,
        "observed_regret_mg_ha": oracle_maximum - observed_yield,
        "forecast_gain_over_observed_mg_ha": forecast_best_yield - observed_yield,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    temporary.write_text(
        json.dumps(value, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _atomic_table(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    if path.suffix == ".parquet":
        frame.to_parquet(temporary, index=False)
    else:
        frame.to_csv(temporary, index=False)
    os.replace(temporary, path)


def _markdown_table(frame: pd.DataFrame) -> str:
    """Render a compact Markdown table without optional tabulate support."""

    if frame.empty:
        return "_无数据_"
    values = frame.copy()
    for column in values.select_dtypes(include=["float", "float64"]).columns:
        values[column] = values[column].map(lambda value: f"{value:.3f}")
    values = values.fillna("").astype(str)
    header = "| " + " | ".join(values.columns) + " |"
    separator = "| " + " | ".join("---" for _ in values.columns) + " |"
    rows = [
        "| " + " | ".join(str(value).replace("|", "\\|") for value in row) + " |"
        for row in values.itertuples(index=False, name=None)
    ]
    return "\n".join([header, separator, *rows])


def _compact_dates(values: list[str]) -> str:
    """Render recommended dates as contiguous segments for a readable report."""

    if not values:
        return "-"
    dates = pd.to_datetime(values).date.tolist()
    groups: list[list[date]] = [[dates[0]]]
    for current in dates[1:]:
        if (current - groups[-1][-1]).days == 1:
            groups[-1].append(current)
        else:
            groups.append([current])
    return "; ".join(
        group[0].isoformat() if len(group) == 1 else f"{group[0]}..{group[-1]}"
        for group in groups
    )


def _source_experiment_dir(config: ExperimentConfig) -> Path:
    source_id = str(
        config.selection.options.get("source_experiment_id", config.experiment_id)
    )
    return config.output_dir / "experiments" / source_id


def _forecast_options(config: ExperimentConfig) -> tuple[date, int, int, float]:
    options = config.simulation.options
    cutoff = date(
        int(options.get("forecast_cutoff_year", config.selection.evaluation_years[0])),
        int(options.get("forecast_cutoff_month", DEFAULT_CUTOFF_MONTH)),
        int(options.get("forecast_cutoff_day", DEFAULT_CUTOFF_DAY)),
    )
    return (
        cutoff,
        int(options.get("forecast_radius_days", DEFAULT_RADIUS_DAYS)),
        int(options.get("forecast_step_days", DEFAULT_STEP_DAYS)),
        float(options.get("forecast_fraction", DEFAULT_FRACTION)),
    )


def _figure(
    environment_id: str,
    curve: pd.DataFrame,
    oracle: pd.DataFrame,
    observed_planting_date: date,
    output_path: Path,
) -> None:
    figure, axis = plt.subplots(figsize=(9, 4.8))
    dates = pd.to_datetime(curve["planting_date"])
    axis.fill_between(
        dates,
        curve["forecast_p10_yield_mg_ha"],
        curve["forecast_p90_yield_mg_ha"],
        alpha=0.2,
        label="10–90% scenario interval",
    )
    axis.plot(
        dates,
        curve["forecast_mean_yield_mg_ha"],
        label="Historical-scenario mean",
        linewidth=2,
    )
    oracle_dates = pd.to_datetime(oracle["planting_date"])
    oracle_yields = pd.to_numeric(oracle["dry_yield_mg_ha"], errors="coerce").where(
        oracle["status"].eq("matured")
    )
    axis.plot(
        oracle_dates, oracle_yields, "--",
        label=f"{observed_planting_date.year} actual-weather oracle",
    )
    observed = oracle.loc[
        pd.to_datetime(oracle["planting_date"]).dt.date.eq(observed_planting_date)
    ]
    if not observed.empty:
        axis.scatter(
            pd.to_datetime(observed["planting_date"]),
            pd.to_numeric(observed["dry_yield_mg_ha"], errors="coerce"),
            marker="*",
            s=100,
            color="black",
            label="Observed G2F planting",
            zorder=3,
        )
    axis.axvline(pd.Timestamp(observed_planting_date), color="black", alpha=0.25)
    axis.set_title(f"{environment_id}: forecast vs. actual-weather simulation")
    axis.set_xlabel("Candidate planting date")
    axis.set_ylabel("Dry yield (Mg/ha)")
    axis.legend()
    figure.autofmt_xdate()
    figure.tight_layout()
    figure.savefig(output_path, dpi=150)
    plt.close(figure)


def _report(
    config: ExperimentConfig,
    recommendations: pd.DataFrame,
    simulation_results: pd.DataFrame,
    scenario_count: int,
    cutoff: date,
    display_name: str,
) -> str:
    model_label = str(display_name)
    columns = [
        "environment_id",
        "forecast_recommended_dates",
        "oracle_recommended_dates",
        "overlap_days",
        "recommended_window_coverage",
        "forecast_best_date",
        "oracle_best_date",
        "forecast_best_regret_mg_ha",
        "observed_regret_mg_ha",
        "forecast_gain_over_observed_mg_ha",
    ]
    table = recommendations[columns].copy()
    table["forecast_recommended_dates"] = table["forecast_recommended_dates"].map(
        _compact_dates
    )
    table["oracle_recommended_dates"] = table["oracle_recommended_dates"].map(
        _compact_dates
    )
    markdown_table = _markdown_table(table)
    status_table = _markdown_table(
        simulation_results.groupby(["environment_id", "status"], sort=True)
        .size()
        .rename("count")
        .reset_index()
    )
    figure_links = "\n".join(
        f"![{row.environment_id} forecast]"
        f"(figures/{row.environment_id}_forecast_vs_actual.png)"
        for row in recommendations.itertuples(index=False)
    )
    source_experiment_id = str(
        config.selection.options.get("source_experiment_id", config.experiment_id)
    )
    target_year = cutoff.year
    radius = int(
        config.simulation.options.get("forecast_radius_days", DEFAULT_RADIUS_DAYS)
    )
    fraction = float(
        config.simulation.options.get("forecast_fraction", DEFAULT_FRACTION)
    )
    period_end = weather_end_for_year(target_year).isoformat()
    training_years = getattr(config.selection, "calibration_years", ())
    training_label = "、".join(map(str, training_years)) or "源实验训练年份"
    return f"""# G2F 播期预测可行性 Demo

## 阶段结论

本实验利用已有的 {model_label} 最小仿真闭环，完成了一个**回顾式预测实验**：
假设信息截止于 {cutoff.isoformat()}，仅使用截止日前已实现的 {target_year} 年
G2F 天气和此前同站点历史天气情景；随后用 G2F 实际天气扫描作为 oracle 检验。
目标年天气与模拟最晚到 {period_end}，这不是预测的信息截止日。

- 共执行 {len(recommendations)} 个环境、{scenario_count} 个历史天气情景、
  {len(simulation_results)} 条情景仿真记录；失败状态完整保留，只在汇总曲线
  中排除，不重新标记为成熟。
- 推荐口径为情景均值产量达到该环境候选日期最大均值的 {fraction:.0%}。
- 窗口覆盖率按下表实际结果解释，不沿用历史报告中的固定结论。
- 以预测最优日相对 oracle 最优日的产量遗憾计，环境平均遗憾为
  {recommendations["forecast_best_regret_mg_ha"].mean():.3f} Mg/ha。
- 相对 G2F 实际播期，预测最优日的模拟产量增益并不稳定；因此本实验证明的是
  预测流程和不确定性表达可运行，而不是已经具备稳定增产能力。
- 主要检验指标包括推荐窗口与 oracle 窗口的重叠、最优推荐日期的 oracle
  产量遗憾，以及相对实际播期的产量增益。
- 兼容指标限制：oracle 阈值在 forecast 推荐日期子集中计算，覆盖率可能偏高；
  最优预测日期在关联成功 oracle 后选取，不等同于评估前冻结的部署推荐。
  本次天气切换不更改既有指标定义。
- 结论：在统一候选窗口内，“截止日前实测天气 + 历史天气情景 + {model_label}”
  可生成播期推荐和区间；但样本仅 {len(recommendations)} 个环境，绝对产量
  受通用品种、均质土壤、管理假设和 G2F 天气覆盖/缺测影响，不能替代
  业务化预报或直接得出增产结论。

## 推荐与检验

{markdown_table}

## 情景状态

{status_table}

## 图表

{figure_links}

## 方法与信息边界

1. 读取 `{source_experiment_id}` 已完成的 {training_label} 校准参数，
   不在预测阶段使用评估年观测选择参数。
2. 候选播期为每个环境实际播期前后各 {radius} 天，包含实际播期；
   不生成晚于 {G2F_END_DATE.isoformat()} 的候选。
3. 对每个历史年构造目标年天气序列（1 月 1 日至 {period_end}）：
   {cutoff.isoformat()} 及以前使用 {target_year} 年已实现值；
   之后替换为历史年同月日的值，不使用目标年截止日后的实际天气。
4. 每个情景调用 {model_label} 适配器，汇总成熟运行的均值和 10/50/90 分位数。
5. 使用同天气策略的 {target_year} 年 G2F 天气扫描中 `calibrated` 组作为 oracle，
   对比窗口覆盖率和产量遗憾。

## 复现

```bash
.venv/bin/python -m snowwindow forecast --config {config.source_path}
```
"""


def forecast_stage(
    config: ExperimentConfig, adapter: ModelAdapter | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run the retrospective forecast experiment and persist all evidence."""

    model = adapter if adapter is not None else resolve_model_adapter(config)
    cutoff, radius_days, step_days, fraction = _forecast_options(config)
    if not config.selection.evaluation_years:
        raise ValueError("forecast requires at least one evaluation year")
    target_year = int(config.selection.evaluation_years[0])
    source_dir = _source_experiment_dir(config)
    evidence_paths = (
        source_dir / "config.yaml",
        source_dir / "scan/manifest.json",
    )
    for path in evidence_paths:
        try:
            text = path.read_text(encoding="utf-8")
            evidence = (
                yaml.safe_load(text) if path.suffix == ".yaml" else json.loads(text)
            )
        except (OSError, ValueError, yaml.YAMLError) as exc:
            raise ConfigError(
                f"forecast needs G2F weather policy evidence at {path}; "
                "run a new G2F source experiment first"
            ) from exc
        if not isinstance(evidence, dict) or evidence.get(
            "weather_policy"
        ) != WEATHER_POLICY:
            raise ConfigError(
                f"incompatible weather policy at {path}; "
                "run a new G2F source experiment first"
            )
    paths = {
        "config": evidence_paths[0],
        "scan_manifest": evidence_paths[1],
        "environments": source_dir / "normalized/environments.parquet",
        "management_units": source_dir / "normalized/management_units.parquet",
        "soil_profiles": source_dir / "normalized/soil_profiles.parquet",
        "weather": source_dir / "normalized/weather.parquet",
        "calibration": source_dir / "calibration/parameters.parquet",
        "oracle": source_dir / "scan/summary.parquet",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "forecast source artifacts are missing: " + ", ".join(missing)
        )
    tables = {
        name: pd.read_parquet(path)
        for name, path in paths.items()
        if name not in {"calibration", "oracle", "config", "scan_manifest"}
    }
    parameters = pd.read_parquet(paths["calibration"])
    held_year = parameters.loc[parameters["fold"].eq("held_year")]
    if held_year.empty:
        raise ValueError("held_year calibration parameters are missing")
    calibrated_parameters = {
        model.capabilities.phenology_parameter.name: float(
            held_year.iloc[0][model.capabilities.phenology_parameter.name]
        ),
        model.capabilities.yield_parameter.name: float(
            held_year.iloc[0][model.capabilities.yield_parameter.name]
        ),
    }
    model_parameters = {**dict(config.model.parameters), **calibrated_parameters}
    oracle = pd.read_parquet(paths["oracle"])
    units = select_representative_units(
        tables["management_units"], config.selection.environments
    )
    environments = tables["environments"].set_index("environment_id")
    soils = tables["soil_profiles"].set_index("environment_id")
    output_root = config.experiment_dir / "forecast"
    figure_root = output_root / "figures"
    figure_root.mkdir(parents=True, exist_ok=True)

    result_rows: list[dict[str, Any]] = []
    curve_frames: list[pd.DataFrame] = []
    recommendation_rows: list[dict[str, Any]] = []
    scenario_years: set[int] = set()
    for unit in units.sort_values("management_unit_id").to_dict("records"):
        environment_id = str(unit["environment_id"])
        if int(unit["year"]) != target_year:
            continue
        site = environment_id.rsplit("_", 1)[0]
        scenarios = weather_scenarios(
            tables["weather"],
            environment_id=environment_id,
            site=site,
            target_year=target_year,
            cutoff_date=cutoff,
        )
        if not scenarios:
            raise ValueError(f"no historical weather scenarios for {environment_id}")
        scenario_years.update(scenarios)
        environment = environments.loc[environment_id].to_dict()
        environment["environment_id"] = environment_id
        soil = soils.loc[environment_id].to_dict()
        planting_dates = candidate_dates(
            unit["planting_date"], radius_days=radius_days, step_days=step_days
        )
        environment_result_rows: list[dict[str, Any]] = []
        requests: list[SimulationRequest] = []
        request_meta: dict[str, tuple[int, date]] = {}
        for scenario_year, scenario_weather in sorted(scenarios.items()):
            for planting_date in planting_dates:
                request = build_simulation_request(
                    unit,
                    environment,
                    soil,
                    scenario_weather,
                    parameter_set_id="forecast",
                    model_parameters=model_parameters,
                    planting_date=planting_date,
                    output_dir=config.experiment_dir / "model_cache",
                )
                request_id = (
                    f"{unit['management_unit_id']}::forecast::"
                    f"{scenario_year}::{planting_date.isoformat()}"
                )
                request = replace(request, request_id=request_id)
                requests.append(request)
                request_meta[request_id] = (scenario_year, planting_date)

        results: dict[str, SimulationResult] = {}
        valid_requests = []
        for request in requests:
            failure = weather_failure_result(request, model)
            if failure is None:
                valid_requests.append(request)
            else:
                results[request.request_id] = failure
        run_many = getattr(model, "run_many", None)
        if callable(run_many):
            grouped: dict[tuple[str, int], list[SimulationRequest]] = {}
            for request in valid_requests:
                scenario_year = request_meta[request.request_id][0]
                key = (request.environment.environment_id, scenario_year)
                grouped.setdefault(key, []).append(request)
            for group in grouped.values():
                results.update(run_many(tuple(group)))
        else:
            results.update(
                (request.request_id, model.run(request)) for request in valid_requests
            )

        for request in requests:
            result = results[request.request_id]
            scenario_year, planting_date = request_meta[request.request_id]
            row = {
                "environment_id": environment_id,
                "scenario_year": scenario_year,
                "planting_date": planting_date,
                "request_id": result.request_id,
                "status": result.status.value,
                "failure_reason": result.failure_reason,
                **dict(result.summary),
                "simulation_end_date": request.end_date.isoformat(),
                "weather_horizon_truncated": request.environment.metadata.get(
                    "weather_horizon_truncated"
                ),
            }
            environment_result_rows.append(row)
        environment_results = pd.DataFrame(environment_result_rows)
        result_rows.extend(environment_result_rows)
        usable = environment_results.loc[
            environment_results["status"].eq("matured")
            & pd.to_numeric(environment_results["dry_yield_mg_ha"], errors="coerce").gt(
                0
            )
        ].copy()
        if usable.empty:
            # Keep unsuccessful evidence even when no recommendation can be made.
            failed_results = pd.DataFrame(result_rows)
            _atomic_table(output_root / "scenario_results.parquet", failed_results)
            _atomic_table(output_root / "scenario_results.csv", failed_results)
            raise ValueError(f"all forecast scenarios failed for {environment_id}")
        curve = (
            usable.groupby("planting_date", as_index=False)
            .agg(
                scenario_count=("scenario_year", "size"),
                forecast_mean_yield_mg_ha=("dry_yield_mg_ha", "mean"),
                forecast_p10_yield_mg_ha=(
                    "dry_yield_mg_ha",
                    lambda values: values.quantile(0.10),
                ),
                forecast_p50_yield_mg_ha=("dry_yield_mg_ha", "median"),
                forecast_p90_yield_mg_ha=(
                    "dry_yield_mg_ha",
                    lambda values: values.quantile(0.90),
                ),
                forecast_min_yield_mg_ha=("dry_yield_mg_ha", "min"),
                forecast_max_yield_mg_ha=("dry_yield_mg_ha", "max"),
                forecast_mean_flowering_proxy_dap=(
                    "flowering_proxy_dap",
                    "mean",
                ),
            )
            .sort_values("planting_date")
            .reset_index(drop=True)
        )
        curve.insert(0, "environment_id", environment_id)
        curve_frames.append(curve)
        environment_oracle = oracle.loc[
            oracle["environment_id"].eq(environment_id)
            & oracle["parameter_set"].eq("calibrated")
        ].copy()
        score = score_forecast_recommendation(
            curve,
            environment_oracle,
            fraction=fraction,
            observed_planting_date=unit["planting_date"],
        )
        recommendation_rows.append({"environment_id": environment_id, **score})
        _figure(
            environment_id,
            curve,
            environment_oracle,
            unit["planting_date"],
            figure_root / f"{environment_id}_forecast_vs_actual.png",
        )

    results = pd.DataFrame(result_rows)
    curves = pd.concat(curve_frames, ignore_index=True)
    recommendations = pd.DataFrame(recommendation_rows)
    if results.empty or curves.empty or recommendations.empty:
        raise ValueError("forecast produced no usable environments")
    _atomic_table(output_root / "scenario_results.parquet", results)
    _atomic_table(output_root / "scenario_results.csv", results)
    _atomic_table(output_root / "forecast_curves.parquet", curves)
    _atomic_table(output_root / "forecast_curves.csv", curves)
    _atomic_table(output_root / "recommendations.parquet", recommendations)
    _atomic_table(output_root / "recommendations.csv", recommendations)
    _atomic_json(
        output_root / "recommendations.json",
        recommendations.to_dict("records"),
    )
    _atomic_json(
        output_root / "manifest.json",
        {
            "source_experiment_id": str(
                config.selection.options.get(
                    "source_experiment_id", config.experiment_id
                )
            ),
            "model": model.name,
            "model_version": model.version,
            "target_year": target_year,
            "information_cutoff_date": cutoff.isoformat(),
            "weather_policy": WEATHER_POLICY,
            "simulation_end_limit": weather_end_for_year(target_year).isoformat(),
            "future_weather_policy": (
                "target weather on/before cutoff; historical weather after cutoff"
            ),
            "scenario_years": sorted(scenario_years),
            "candidate_radius_days": radius_days,
            "candidate_step_days": step_days,
            "recommendation_fraction": fraction,
            "scenario_result_count": len(results),
            "forecast_curve_count": len(curves),
            "environment_count": len(recommendations),
            "input_fingerprints": {
                name: _sha256_file(path) for name, path in paths.items()
            },
        },
    )
    (output_root / "report.md").write_text(
        _report(
            config,
            recommendations,
            results,
            len(scenario_years),
            cutoff,
            str(model.capabilities.display_name),
        ),
        encoding="utf-8",
    )
    return curves, recommendations
