"""Rerun the three established parameter sets with next-year weather."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .crossyear_weather import OUT, prepare
from .data import sha256_file, write_json
from .model import Experiment, model_fingerprint
from .physics import planting_windows
from .pipeline import run_many
from .plot_three_scenarios import main as plot_scenarios


def run(cfg: dict) -> pd.DataFrame:
    e = Experiment(cfg)
    params = json.loads(Path("outputs/aquacrop_annual/calibration_parameters.json").read_text())
    optimized = next(x for x in params if x["name"] == "heldout_year")
    modes = {"default": (1.0, e.base["HI0"]), "first_calibration": (.94, .35),
             "optimized": (optimized["phenology_scale"], optimized["HI0"])}
    rows = []
    for mode, (scale, hi0) in modes.items():
        print(f"Cross-year scan: {mode}", flush=True)
        tasks = [(u, {"planting_date": date.strftime("%Y-%m-%d"), "scale": scale, "hi0": hi0})
                 for u in e.units
                 for date in pd.date_range(f"{u['year']}-01-01", f"{u['year']}-12-31")]
        results = run_many(e, tasks)
        rows.extend({**r, "parameter_set": mode} for r in results)
        pd.DataFrame(rows).to_csv(OUT / "annual_scenarios.csv", index=False)
    data = pd.DataFrame(rows)
    for u in e.units:
        weather = e.weather[u["Env"]]
        date_index = pd.DatetimeIndex(weather.Date)
        cold = np.r_[0, np.cumsum(weather.MinTemp.to_numpy() < 0)]
        group = data.loc[data.Env.eq(u["Env"])]
        indices = date_index.get_indexer(pd.to_datetime(group.planting_date))
        ends = np.minimum(indices + 14, len(weather))
        data.loc[group.index, "first14_air_below0_days"] = cold[ends] - cold[indices]
        data.loc[group.index, "first14_available_days"] = ends - indices
    data.to_csv(OUT / "annual_scenarios.csv", index=False)

    windows = []
    for (env, mode), group in data.groupby(["Env", "parameter_set"]):
        windows.extend({**r, "Env": env, "parameter_set": mode}
                       for r in planting_windows(group, step_days=1))
    write_json(OUT / "planting_windows.json", windows)

    old = pd.read_csv("outputs/aquacrop_annual/annual_scenarios.csv",
                      usecols=["Env", "parameter_set", "planting_date", "status", "dry_yield_Mg_ha"])
    comparison = data.merge(old, on=["Env", "parameter_set", "planting_date"],
                            suffixes=("_crossyear", "_sameyear"), validate="one_to_one")
    comparison["became_mature"] = comparison.status_sameyear.ne("matured") & comparison.status_crossyear.eq("matured")
    comparison["maturity_next_year"] = comparison.status_crossyear.eq("matured") & (
        pd.to_datetime(comparison.maturity_date, errors="coerce").dt.year > comparison.year)
    comparison.to_csv(OUT / "crossyear_vs_sameyear.csv", index=False)

    # Store daily processes for the observed sowing, old cutoff + 1,
    # August 1, and December 31. The summary table contains every date.
    representative = []
    for u in e.units:
        subset = old.loc[old.Env.eq(u["Env"]) & old.parameter_set.eq("optimized")].sort_values("planting_date")
        last = subset.loc[subset.status.eq("matured"), "planting_date"].max()
        targets = {u["planting_date"]: "observed", (pd.Timestamp(last) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"): "first_old_failure",
                   f"{u['year']}-08-01": "august", f"{u['year']}-12-31": "last_candidate"}
        for date, role in targets.items():
            result = e.run(u, planting_date=date, scale=optimized["phenology_scale"],
                           hi0=optimized["HI0"], store_daily=True)
            representative.append({"Env": u["Env"], "planting_date": date, "role": role,
                                   "run_id": result["run_id"], "status": result["status"]})
    pd.DataFrame(representative).to_csv(OUT / "representative_runs.csv", index=False)
    return data


def report(cfg: dict, data: pd.DataFrame) -> None:
    out = OUT
    # Air-freezing exposure is descriptive evidence, not a frost mortality
    # rule. Count from requested planting through the last simulated day.
    for env, group in data.groupby("Env"):
        weather = pd.read_csv(out / "weather_combined" / f"{env}.csv", parse_dates=["Date"])
        dates = pd.DatetimeIndex(weather.Date)
        cold = np.r_[0, np.cumsum(weather.MinTemp.to_numpy() < 0)]
        begins = dates.searchsorted(pd.to_datetime(group.planting_date))
        ends = dates.searchsorted(pd.to_datetime(group.termination_date, errors="coerce"))
        valid = pd.notna(group.termination_date).to_numpy()
        count = np.full(len(group), np.nan)
        count[valid] = cold[np.minimum(ends[valid], len(weather))] - cold[begins[valid]]
        data.loc[group.index, "growing_season_air_below0_days"] = count
    data.to_csv(out / "annual_scenarios.csv", index=False)
    comparison = pd.read_csv(out / "crossyear_vs_sameyear.csv")
    windows = json.loads((out / "planting_windows.json").read_text())
    reps = pd.read_csv(out / "representative_runs.csv")
    count = data.groupby(["parameter_set", "status"]).size().unstack(fill_value=0)
    count.to_csv(out / "status_counts.csv")
    rows = []
    for env, group in data.loc[data.parameter_set.eq("optimized")].groupby("Env"):
        valid = group.loc[group.status.eq("matured") & group.dry_yield_Mg_ha.notna()]
        best = valid.loc[valid.dry_yield_Mg_ha.idxmax()] if len(valid) else None
        no_freeze = valid.loc[valid.growing_season_air_below0_days.eq(0)]
        best_no_freeze = no_freeze.loc[no_freeze.dry_yield_Mg_ha.idxmax()] if len(no_freeze) else None
        rows.append({"Env": env, "n_matured": len(valid), "n_matured_next_year": int((pd.to_datetime(valid.maturity_date).dt.year > valid.year).sum()),
                     "best_planting_date": best.planting_date if best is not None else None,
                     "max_dry_yield_Mg_ha": best.dry_yield_Mg_ha if best is not None else None,
                     "best_maturity_date": best.maturity_date if best is not None else None,
                     "first14_below0_days_at_best": best.first14_air_below0_days if best is not None else None,
                     "growing_season_below0_days_at_best": best.growing_season_air_below0_days if best is not None else None,
                     "n_zero_air_freeze_days": len(no_freeze),
                     "best_zero_air_freeze_planting_date": best_no_freeze.planting_date if best_no_freeze is not None else None,
                     "best_zero_air_freeze_dry_yield_Mg_ha": best_no_freeze.dry_yield_Mg_ha if best_no_freeze is not None else None})
    summary = pd.DataFrame(rows)
    summary.to_csv(out / "environment_summary.csv", index=False)

    checks = {
        "six_environments_three_modes_365_dates": len(data) == 6 * 3 * 365 and all(len(g) == 365 and g.planting_date.nunique() == 365 for _, g in data.groupby(["Env", "parameter_set"])),
        "weather_two_full_years": all(x["rows"] in [730, 731] for x in json.loads((out / "weather_manifest.json").read_text())),
        "no_technical_failures": not data.status.eq("execution_failed").any(),
        "no_yield_for_engine_rejections": data.loc[data.status.isin(["insufficient_thermal_time", "exceeds_model_one_year_limit"]), "dry_yield_Mg_ha"].isna().all(),
        "water_balance_below_1e_7": (data.loc[data.water_balance_max_abs_mm_day.notna(), "water_balance_max_abs_mm_day"] < 1e-7).all(),
        "soil_water_bounds": data.loc[data.soil_water_bounds_ok.notna(), "soil_water_bounds_ok"].all(),
        "all_reported_window_dates_matured": all(all(d in set(data.loc[data.Env.eq(w["Env"]) & data.parameter_set.eq(w["parameter_set"]) & data.status.eq("matured"), "planting_date"]) for d in w["dates"]) for w in windows),
        "representative_daily_saved": all((out / "runs" / f"{r['run_id']}.parquet").exists() for r in reps.to_dict("records") if r["status"] in ["matured", "crop_died", "not_matured", "not_germinated"]),
        "leap_day_rule_logged": int(data.leap_day_harvest_rule_adjusted.fillna(False).sum()) == 3 * 3,
    }
    # Original-date simulations end before New Year. Extending the possible
    # calendar must not change those successful first-year predictions.
    units = pd.read_csv(out / "environments.csv")
    observed = comparison.merge(units[["Env", "planting_date"]].rename(columns={"planting_date": "observed_date"}), on="Env")
    observed = observed.loc[observed.planting_date.eq(observed.observed_date)]
    equality = observed.loc[observed.status_sameyear.eq("matured") & observed.status_crossyear.eq("matured")]
    checks["original_date_mature_yield_unchanged"] = bool(np.allclose(equality.dry_yield_Mg_ha_crossyear, equality.dry_yield_Mg_ha_sameyear, atol=1e-9, rtol=0))
    checks = {k: bool(v) for k, v in checks.items()}
    write_json(out / "acceptance_checks.json", checks)
    plot_scenarios(root=out, cross_year=True)

    from .report import markdown_table
    count_table = count.reset_index()
    effect = comparison.groupby("parameter_set").agg(became_mature=("became_mature", "sum"),
                                                      maturity_next_year=("maturity_next_year", "sum")).reset_index()
    report_text = f"""# AquaCrop 跨年播期重实验

## 实验设置

仍使用INH1、MOH2、NYH2三个地点各2022、2023年共六个环境，沿用第一版环境筛选、土壤、初始水分、雨养管理与三套作物参数：默认、第一版率定、优化参数。每个环境扫描当年1月1日至12月31日全部365个播期，总计{len(data):,}个情景。每个情景均从当年1月1日相同初始状态开始，播种日不重新设置土壤水分。作物可使用次年天气继续生长；单季截止为下一个播种周年日前一天，提前成熟或死亡则提前结束。这个一周年截止是为了遵守安装版AquaCrop-OSPy 3.1.0对单季成熟天数小于365天的内部限制，不代表田间收获管理。

第一年天气复用原实验已核验的NASA POWER AG输入；第二年在**同一原环境坐标**重新取得POWER AG全年天气，2022情景接续2023年，2023情景接续2024年。日蒸散仍按原FAO-56近似方法计算。完整请求URL、坐标、单位、原始响应哈希见weather_manifest.json及weather_raw目录；不是将2024测试集的315天不完整天气拼接使用。对于2023年3月1日播种，周年日前一日是2024年2月29日；OSPy以非闰年的1990年解析月日规则，故该情景截止改为2月28日，差一天且显式记录在`leap_day_harvest_rule_adjusted`字段。

## 主要结果

{markdown_table(count_table)}

相较于原先12月31日截止，原本异常但在跨年方案正常成熟的候选数：

{markdown_table(effect)}

优化参数各环境概览（干物质产量，t/ha）：

{markdown_table(summary)}

六个环境的全年模拟最高产情景，在播种至成熟期间均经历了最低气温低于0℃的日子（见上表），因此不能据此推荐秋播。表中的“零个零下气温日”子集只是诊断性筛查，不是土壤冻结、霜冻伤害或田间适播性判定。

完整逐日播期、产量、成熟日期、年末跨越和冬季气温暴露记录分别见annual_scenarios.csv、crossyear_vs_sameyear.csv与environment_summary.csv。90%/95%产量窗口保存在planting_windows.json，仅由正常成熟且有效正产量的候选构成；不连续集合分段报告。原播期实测产量只在原始播期位置标记。

![默认参数跨年播期曲线](figures/播期产量_默认参数.png)

![第一版率定参数跨年播期曲线](figures/播期产量_第一版率定.png)

![优化参数跨年播期曲线](figures/播期产量_优化参数.png)

## 解释与限制

跨年运行回答了“放宽12月31日截止后，模型如何响应晚播”，**没有增加晚播或冬播的实测产量证据**。安装版OSPy的萌发判断主要依据表层可利用水，不以最低气温直接判定种子冻死。跨年晚播可在次年春季积温累积后生长，形成冬季平台或不现实高产；这不能解释成田间越冬可行。annual_scenarios.csv的播后14天最低气温低于0℃天数只是气温暴露筛查，不是冻害模型。初始水分、土壤水力性质、养分和品种参数仍有原实验的简化。

![当年截止与跨年优化参数对照](figures/当年截止与跨年对比.png)

原始播期的模拟产量若保持一致，仅说明截止日期扩展没有改变这些已在当年结束的运行。最高模拟产量及窗口仍属于反事实模型结果，不能直接作为农学推荐。模型拒绝、未萌发、死亡和未成熟日期不填零产量。

验收结果：

{markdown_table(pd.DataFrame([{"检查": k, "通过": v} for k, v in checks.items()]))}

模型接口及参数详见项目的`aquacrop_demo/model.py`、`aquacrop_demo/crossyear.py`、配置文件和[OSPy官方代码](https://github.com/aquacropos/aquacrop)。
"""
    (out / "结果报告.md").write_text(report_text, encoding="utf-8")
    write_json(out / "execution_manifest.json", {"model_source_sha256": model_fingerprint(),
              "code_sha256": {str(p): sha256_file(p) for p in [Path("aquacrop_demo/model.py"), Path("aquacrop_demo/crossyear.py"), Path("aquacrop_demo/crossyear_weather.py")]},
              "config": cfg})
    print("Acceptance:", checks, flush=True)


def main() -> None:
    start = time.perf_counter()
    cfg = prepare()
    data = run(cfg)
    report(cfg, data)
    write_json(OUT / "timing.json", {"seconds": time.perf_counter() - start,
                                      "workers": cfg["workers"], "includes_weather_download_and_cache": True})


if __name__ == "__main__":
    main()
