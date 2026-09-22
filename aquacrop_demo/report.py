"""Scientific plots and a Chinese report generated from saved experiment outputs."""
from __future__ import annotations

import json
import os
import importlib.metadata
import platform
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(".cache/matplotlib").resolve()))
os.environ.setdefault("XDG_CACHE_HOME", str(Path(".cache").resolve()))
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
Path(".cache/fontconfig").mkdir(parents=True, exist_ok=True)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .data import write_json, sha256_file


def markdown_table(frame):
    def fmt(x):
        if x is None: return "—"
        if isinstance(x, (float, np.floating)):
            return "—" if not np.isfinite(x) else f"{x:.3f}"
        return str(x).replace("|", "/").replace("\n", " ")
    return "\n".join(["| " + " | ".join(frame.columns) + " |", "| " + " | ".join(["---"] * len(frame.columns)) + " |"] +
                     ["| " + " | ".join(fmt(v) for v in row) + " |" for row in frame.itertuples(index=False, name=None)])


def stage_covariates(out, scenarios, weather):
    rows = []
    for r in scenarios.loc[scenarios.sensitivity.eq("baseline")].to_dict("records"):
        path = out / "runs" / f"{r['run_id']}.parquet"
        if not path.exists(): continue
        d = pd.read_parquet(path)
        params = json.loads((out / "runs" / f"{r['run_id']}.crop.json").read_text())
        g = d.loc[d.growing_season].merge(weather[r["Env"]][["Date", "MinTemp", "MaxTemp"]], on="Date", validate="one_to_one")
        # Half-open thermal bins have no shared boundary days. They are proxy
        # periods, not separate observed pollen/silk/ear-development stages.
        bins = [0, params["Emergence"], params["HIstart"], params["HIstart"] + params["Flowering"], params["HIstart"] + params["YldForm"], np.inf]
        labels = ["pre_emergence_thermal_proxy", "vegetative_thermal_proxy", "flowering_thermal_proxy", "yield_formation_thermal_proxy", "late_season_thermal_proxy"]
        if any(bins[i+1] <= bins[i] for i in range(len(bins)-1)): continue
        g["stage_proxy"] = pd.cut(g.gdd_cum, bins=bins, labels=labels, right=False)
        for stage, group in g.groupby("stage_proxy", observed=True):
            trpot = float(group.TrPot.sum())
            rows.append({"Env": r["Env"], "run_id": r["run_id"], "offset_days": r["offset_days"], "parameter_set": r["parameter_set"],
                         "stage_proxy": str(stage), "start_day": group.Date.min().strftime("%Y-%m-%d"), "end_day": group.Date.max().strftime("%Y-%m-%d"),
                         "n_days": len(group), "precipitation_mm": float(group.Precipitation_mm_day.sum()), "gdd_sum_C_day": float(group.gdd.sum()),
                         "evaporation_mm": float(group.Es.sum()), "transpiration_mm": float(group.Tr.sum()), "transpiration_potential_mm": trpot,
                         "transpiration_deficit_fraction": float(1 - group.Tr.sum() / trpot) if trpot > 0 else None,
                         "max_temperature_mean_C": float(group.MaxTemp.mean()), "cold_threshold_exposure_days": int((group.MinTemp < params["Tmin_up"]).sum()),
                         "heat_threshold_exposure_days": int((group.MaxTemp > params["Tmax_up"]).sum()),
                         "note": "exposure counts only; not the model's pollination loss coefficient; thermal bins ignore drought-induced development delays"})
    pd.DataFrame(rows).to_csv(out / "stage_covariates.csv", index=False)


def build_report(cfg):
    out = Path(cfg["output_dir"])
    figs = out / "figures"
    figs.mkdir(exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "savefig.dpi": 180, "axes.grid": True, "grid.alpha": .18})
    units = pd.read_csv(out / "environments.csv")
    scenarios = pd.read_csv(out / "scenario_summary.csv")
    windows = json.loads((out / "planting_windows.json").read_text())
    parameters = json.loads((out / "calibration_parameters.json").read_text())
    p = next(r for r in parameters if r["name"] == "heldout_year")
    distribution = importlib.metadata.distribution("aquacrop")
    license_files = [distribution.locate_file(f) for f in distribution.files if str(f).endswith("licenses/LICENSE")]
    if len(license_files) != 1: raise ValueError("Installed AquaCrop license file not found")
    license_file = license_files[0]
    license_text = license_file.read_text()
    if "Apache License" not in license_text[:200]: raise ValueError("Unexpected installed license")
    (out / "aquacrop-3.1.0.LICENSE.txt").write_text(license_text)
    write_json(out / "installed_environment.json", {"python": platform.python_version(), "platform": platform.platform(),
               "dependencies": {d.metadata['Name']: d.version for d in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata['Name'].lower())},
               "installed_aquacrop_license": "Apache-2.0", "license_sha256": sha256_file(license_file),
               "pypi_license_metadata": "MIT (inconsistent with distributed LICENSE)",
               "code_sha256": {str(f): sha256_file(f) for f in sorted(Path('aquacrop_demo').glob('*.py'))},
               "default_config_file_sha256": sha256_file(Path('aquacrop_demo/config.yaml')),
               "effective_configuration": cfg,
               "requirements_sha256": sha256_file(Path('requirements-aquacrop.lock.txt'))})
    validation = pd.read_csv(out / "validation_predictions.csv")
    metrics = pd.read_csv(out / "validation_metrics.csv")
    baseline = scenarios.loc[scenarios.sensitivity.eq("baseline")]
    modes = [("default", "Default", "#64748b"), ("phenology_only", "Phenology fitted", "#d18a26"), ("phenology_and_yield", "Phenology + HI fitted", "#237a6a")]
    weather = {env: pd.read_csv(out / "weather" / f"{env}.csv", parse_dates=["Date"]) for env in units.Env}
    fig, axes = plt.subplots(3, 2, figsize=(11, 10), sharex=True)
    for ax, (_, unit) in zip(axes.flat, units.iterrows()):
        for mode, label, color in modes:
            g = baseline.loc[baseline.unit_id.eq(unit.unit_id) & baseline.parameter_set.eq(mode)].sort_values("offset_days")
            good = g.status.eq("matured")
            ax.plot(g.offset_days, g.dry_yield_Mg_ha.where(good), "o-", label=label, color=color, lw=1.7, ms=4)
            abnormal = g.loc[~good & g.dry_yield_Mg_ha.notna()]
            ax.scatter(abnormal.offset_days, abnormal.dry_yield_Mg_ha, marker="x", color=color, s=50)
        ax.axhline(unit.observed_dry_yield_Mg_ha, ls="--", color="#933b45", label="Observed at original date")
        ax.set_title(f"{unit.Env} ({unit.split})")
        ax.set_ylabel("Dry yield (Mg/ha)")
    for ax in axes[-1]: ax.set_xlabel("Planting-date offset (days)")
    handles, legend_labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, legend_labels, loc="lower center", ncol=4, fontsize=8)
    fig.suptitle("Nine planting dates: independent full simulations\nDashed observation applies only to offset 0; x = abnormal termination", fontsize=12)
    fig.tight_layout(rect=(0, .04, 1, .94)); fig.savefig(figs / "planting_yield_curves.png"); plt.close(fig)

    heldout = validation.loc[validation.fold.eq("heldout_year") & validation.validation_split.eq("test")]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.4))
    for ax, pred, obs, label in [(axes[0], "flowering_proxy_DAP", "observed_pollen_DAP", "Flowering proxy vs 50% pollen (days)"),
                                 (axes[1], "dry_yield_Mg_ha", "observed_dry_yield_Mg_ha", "Dry yield (Mg/ha)")]:
        values = []
        for mode, name, color in modes:
            g = heldout.loc[heldout.parameter_set.eq(mode) & heldout.status.eq("matured")]
            ax.scatter(g[obs], g[pred], s=50, label=name, color=color)
            values.extend(g[obs].tolist() + g[pred].tolist())
            if mode == "phenology_and_yield":
                for _, r in g.iterrows(): ax.annotate(r.site, (r[obs], r[pred]), xytext=(4, 3), textcoords="offset points", fontsize=8)
        limits = [min(values) - 1, max(values) + 1]
        ax.plot(limits, limits, ls="--", color="#999999"); ax.set_xlim(limits); ax.set_ylim(limits)
        ax.set_xlabel("Observed"); ax.set_ylabel("Simulated"); ax.set_title(label)
    axes[0].legend(fontsize=8)
    fig.suptitle("Held-out 2023; parameters selected using 2022 only", fontsize=12)
    fig.tight_layout(); fig.savefig(figs / "heldout_validation.png"); plt.close(fig)

    representative = units.loc[units.site.eq(units.site.iloc[0]) & units.split.eq("test")].iloc[0]
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    for offset, color in [(-20, "#4878a8"), (0, "#237a6a"), (20, "#d18a26")]:
        r = baseline.loc[baseline.unit_id.eq(representative.unit_id) & baseline.parameter_set.eq("phenology_and_yield") & baseline.offset_days.eq(offset)].iloc[0]
        path = out / "runs" / f"{r.run_id}.parquet"
        if not path.exists(): continue
        d = pd.read_parquet(path)
        axes[0].plot(d.Date, d.canopy_cover, color=color, label=f"Offset {offset:+d} days")
        axes[1].plot(d.Date, d.soil_water_mm, color=color)
        axes[2].plot(d.Date, d.biomass / 100, color=color)
    for ax, label in zip(axes, ["Canopy cover (fraction)", "Profile water (mm)", "Biomass (Mg/ha)"]): ax.set_ylabel(label)
    axes[0].legend(fontsize=9); axes[-1].set_xlabel("Calendar date")
    fig.suptitle(f"{representative.Env}: planting shifts the entire process", fontsize=12)
    fig.tight_layout(); fig.savefig(figs / "daily_process_comparison.png"); plt.close(fig)

    fig, axes = plt.subplots(3, 2, figsize=(11, 9), sharex=True)
    for ax, (_, unit) in zip(axes.flat, units.iterrows()):
        g = scenarios.loc[scenarios.unit_id.eq(unit.unit_id) & scenarios.parameter_set.eq("phenology_and_yield")]
        for sensitivity, group in g.groupby("sensitivity"):
            group = group.sort_values("offset_days")
            ax.plot(group.offset_days, group.dry_yield_Mg_ha.where(group.status.eq("matured")), "o-", label=sensitivity.replace("initial_available_water_pct", "Initial TAW %").replace("root_depth_scale", "Root scale"), ms=3)
        ax.set_title(unit.Env); ax.set_ylabel("Dry yield (Mg/ha)")
    handles, legend_labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, legend_labels, loc="lower center", ncol=3, fontsize=8)
    for ax in axes[-1]: ax.set_xlabel("Planting-date offset (days)")
    fig.suptitle("Input sensitivity; crop parameters are frozen\nRoot +20% is clipped by the fixed 2 m profile and overlaps baseline", fontsize=12)
    fig.tight_layout(rect=(0, .06, 1, .93)); fig.savefig(figs / "input_sensitivity.png"); plt.close(fig)

    stage_covariates(out, scenarios, weather)
    # Whole-fold metrics additionally retain valid simulated death yields;
    # the primary mature-only statistics always disclose excluded counts.
    diagnostic_metrics = []
    for (fold, split, mode), g in validation.groupby(["fold", "validation_split", "parameter_set"]):
        valid = g.loc[g.status.isin(["matured", "crop_died"])].dropna(subset=["dry_yield_Mg_ha"])
        residual = valid.dry_yield_Mg_ha - valid.observed_dry_yield_Mg_ha
        diagnostic_metrics.append({"fold": fold, "split": split, "parameter_set": mode, "n_total": len(g), "n_simulated_final_yield": len(valid),
                                   "n_crop_died": int(g.status.eq("crop_died").sum()), "mae_including_crop_died_Mg_ha": float(residual.abs().mean()) if len(valid) else None})
    pd.DataFrame(diagnostic_metrics).to_csv(out / "validation_final_yield_diagnostics.csv", index=False)
    sensitivity_rows = []
    for unit_id in units.unit_id:
        records = [r for r in windows if r["unit_id"] == unit_id and r["parameter_set"] == "phenology_and_yield" and r["fraction"] == .95]
        reference = next(r for r in records if r["sensitivity"] == "baseline")
        for r in records:
            a, b = set(reference["dates"]), set(r["dates"])
            sensitivity_rows.append({"Env": r["Env"], "sensitivity": r["sensitivity"], "window_95_jaccard": len(a & b) / len(a | b) if a | b else None,
                                     "best_dates": ",".join(r.get("best_dates", [])), "edge_peak": r.get("edge_peak"),
                                     "max_dry_yield_Mg_ha": r.get("max_dry_yield_Mg_ha")})
    pd.DataFrame(sensitivity_rows).to_csv(out / "window_sensitivity.csv", index=False)
    usable = scenarios.loc[~scenarios.status.isin(["execution_failed", "insufficient_thermal_time"])]
    observed_times = usable.drop_duplicates("run_id").elapsed_seconds
    qc = {"scenario_rows": len(scenarios), "base_scenario_rows_per_parameter_set": baseline.groupby("parameter_set").size().to_dict(),
          "status_counts": scenarios.groupby(["parameter_set", "sensitivity", "status"]).size().reset_index(name="n").to_dict("records"),
          "max_water_balance_abs_mm_day": float(usable.water_balance_max_abs_mm_day.max()),
          "all_soil_water_bounds_ok": bool(usable.soil_water_bounds_ok.all()),
          "all_actual_dates_match_nominal": bool((usable.actual_planting_date == usable.planting_date).all()),
          "all_irrigation_zero": bool((usable.seasonal_irrigation_mm == 0).all()),
          "all_have_preplant_days": bool((usable.preplant_days_simulated > 0).all()),
          "hi0_at_lower_search_boundary": p["hi0_boundary"],
          "not_a_counterfactual_validation": True,
          "timing_scope": "run times include model construction, diagnostics and optional output serialization; 3 worker processes; no general benchmark claim"}
    write_json(out / "quality_checks.json", qc)
    main_metrics = metrics.loc[metrics.fold.eq("heldout_year")].copy()
    main_metrics = main_metrics[["split", "parameter_set", "target", "n", "n_excluded", "mae", "rmse", "bias"]]
    window_table = pd.DataFrame([{ "Env": r["Env"], "阈值": f"{r['fraction']:.0%}", "最大干产量 Mg/ha": r.get("max_dry_yield_Mg_ha"),
                                  "最优日期": ", ".join(r.get("best_dates", [])), "窗口区段": "; ".join(f"{a} 至 {b}" for a, b in r["segments"]),
                                  "边界峰": r.get("edge_peak", "—"), "最优邻接异常日期": r.get("adjacent_abnormal_candidate", "—"), "状态": r["status"]}
                                 for r in windows if r["parameter_set"] == "phenology_and_yield" and r["sensitivity"] == "baseline"])
    status_table = scenarios.groupby(["parameter_set", "sensitivity", "status"]).size().reset_index(name="n")
    timing_files = sorted(out.glob("timing_*.json"))
    timings = [json.loads(f.read_text()) for f in timing_files]
    error_count = int(scenarios.status.eq("execution_failed").sum())
    txt = f"""# G2F × AquaCrop-OSPy 快速验证：实际执行结果

## 决策结果

已完成 Python 3.10 独立环境、AquaCrop-OSPy {cfg['model_version']} 安装、示例冒烟测试、严格雨养子集核验、默认模拟、有限校准、留年份/留地点验证、九播期情景和输入敏感性。

实际样本是 **3 地点 × 2 年，共 {len(units)} 个环境**。每套参数运行 {len(units) * len(cfg['offsets_days'])} 个播期情景，三套参数共 {len(baseline)} 行；另有四项单因素敏感性，共 {len(scenarios)} 行。完整流程可运行不等于播期响应已获真实试验验证。

2022 年训练选择 **物候热时间倍率 {p['phenology_scale']}、HI0={p['HI0']}**。HI0 位于搜索下界，未依据 2023 年测试表现扩大范围。这里的参数是输入与通用玉米假设下的拟合结果，不应视为已识别的品种生理参数。

## 1. 环境与数据输入

{markdown_table(units[['Env','experiment','planting_date','texture','split','n_hybrids','observed_pollen_DAP','observed_dry_yield_Mg_ha']])}

仅 2022–2023 年存在明确的本地雨养标记，三年目标无法在同一严格筛选规则下满足，未把空白 Irrigated 自动解释为雨养。选择最大主试验由原始小区数决定，不按产量大小筛选；其他管理单元、排除环境和备注保存在 selection_audit.csv。

先按材料平均重复小区，再对材料等权平均。当前主试验标识为 G2F_2022_23_LH244；没有逐杂交种参数、没有 SNP 输入。材料间标准差是样本异质性描述，不是模拟置信区间。

天气采用已缓存的 **NASA POWER AG 全年重新获取数据**，不是原竞赛天气的精确复现。原始 API JSON、请求 URL、单位和哈希全部保存；另有原天气与新天气数值差异表。短波辐射为 MJ/m²/day，未乘 3.6；降水 mm/day、温度 °C、湿度 %、风速 m/s、气压 kPa。

参考 ET0 按 FAO-56 日尺度 Penman–Monteith 计算，地热通量 G=0，使用 RHmean 估算实际水汽压（公式19，精度弱于 RHmin/RHmax），心理常数使用 PS，晴空辐射使用 POWER 返回高程。Rs/Rso比值限于0.3–1，以避免负的云量修正项；计算ET0负数归零；传给 OSPy 时另按包内 prepare_weather 的做法设置最小 0.1 mm/day。两种口径均可追溯。

土壤采用当前环境质地对应的包内水力参数，**20 个 0.1 m 隔室、2 m 均质假设剖面**。不是完整实测分层水力剖面。年度质地差异保留，尤其 MOH2 与 NYH2 的年际分类变化应优先追溯。底界留 0.1 m 缓冲，最大有效根深受限为 1.9 m；库默认根深为 2.3 m，已显式记录这一差异。

竞赛产量按 15.5% 含水率调整，观测干产量 = Yield_Mg_ha × 0.845；模拟干产量 ÷ 0.845 可转换回竞赛口径。没有再用收获 Grain_Moisture 重复校正。OSPy 自带 Fresh yield 的默认口径不同，未用于对照。

来源：[G2F竞赛数据说明](https://link.springer.com/article/10.1186/s13104-026-07629-5)、[NASA POWER](https://power.larc.nasa.gov/)、[FAO-56](https://www.fao.org/4/X0490E/x0490e06.htm)。

## 2. 管理、初始化与播期重运行

全部情景从当年 1 月 1 日起算，以该共同日期的 50% 总可利用水量初始化。不是 50% 田间持水量。off_season=True，裸地播前水分每日运行；不在不同播期重新初始化。雨养灌溉方法显式为0，无地下水、地表蓄水堤、覆盖物、前茬或施肥调整；CO₂使用冻结包版本的默认历史设置，具体值可在运行输入与库内查阅。

固定密度 75,000 plants/ha、土壤、品种参数和初始状态，只改变原播期 −20 至 +20 天、每隔5天的九个播期。关闭自适应播种，记录实际日期。模型达到成熟时结束，否则在12月31日之前因死亡、最新收获或热时间不足等记录不同状态。原收获日期仅诊断，不能当成熟观测。

发现并处理的两个接口问题：

1. 天气列名验证不保证顺序；引擎按位置读取 MinTemp/MaxTemp/Precipitation/ReferenceET/Date，日期固定第五列。
2. 引擎要求土壤深度至少大于等于 Zmax+0.1 m，否则可能增厚底隔室。初期水量残差来自核对时仍用输入隔室厚度。当前预留缓冲，增加剖面不得变形的断言，不修改模型核心。

未达到年内所需热时间的配置会被 OSPy 在初始化阶段拒绝。本实验保留 insufficient_thermal_time 及原错误，不补成0产量、不伪造逐日过程。crop_died 是模型死亡状态，不能仅凭这条标记归因于霜冻或认定成熟。

## 3. 校准和独立评价

先把 Emergence/MaxRooting/Senescence/Maturity/HIstart/Flowering/YldForm 按共同热时间倍率缩放；其他参数固定。搜索0.8–1.2，步长0.02。这里不独立率定成熟期，没有成熟观测；固定 CGC/CDC 与阶段结构可能改变衰老相对成熟的关系，需要多性状数据后再检验。

开花代理定义为逐日累计GDD第一次达到HIstart的日末，与观测50%散粉DAP对照。HIstart是产量形成起点，**不是散粉或吐丝的独立生殖过程**；Flowering是持续热时间。水分诱导发育延迟可能使该代理与模型实际生殖时序不同，开花误差仅按代理解释。

冻结物候后，HI0 在0.35–0.55、步长0.01搜索。目标分别为训练环境开花代理MAE和干产量MAE。一个参数候选必须在全部训练环境正常成熟且提供目标值，否则记无效损失，不能靠丢弃困难环境得到好成绩。因死亡/未成熟排除的数量在评价中明确显示，并另外输出包含死亡终止产量的诊断指标。

主验证按年份：2022训练、2023测试。留地点三折单独重新率定：测试地点两个年份均不参与该折率定。跨折可以共享同配置模拟结果，但每折损失只读该折训练标签；无逐环境调参、无测试开花辅助构造品种。

### 留年份结果（干产量单位 Mg/ha，开花代理单位天）

{markdown_table(main_metrics)}

### 留地点测试结果

{markdown_table(metrics.loc[metrics.fold.ne('heldout_year') & metrics.split.eq('test'), ['fold','parameter_set','target','n','n_excluded','mae','rmse','bias']])}

样本仅三个测试环境/每折两个环境，不给显著性或泛化能力承诺。默认参数和校准参数可能有不同终止状态，评价需同时看 n_excluded。评价数据不存在真实多播期实测对照，**原播期拟合改善不能证明九播期产量响应可信**。

![留出验证](figures/heldout_validation.png)

## 4. 播期曲线、窗口与过程

![九播期产量曲线](figures/planting_yield_curves.png)

虚线观测只适用于原播期0，不是其他候选日期的实测产量。默认 NYH2_2022 曾出现模型死亡终止；其他终止状态按实际结果表为准，异常终止有产量时图中以×显示，不连入正常成熟曲线。

下表是训练参数冻结后、各环境**候选日期中的成熟模拟最优值**。90%/95%窗口是达到该环境候选成熟情景最大产量阈值的离散日期集合，不是连续可作业日期、不是真实生产推荐、不表示置信水平。相邻5天日期合成区段，不连续分别报告；边界峰意味着搜索域没有覆盖完整最优区域，不自动外推。

若最优日期邻接一个死亡或热时间不足候选，另标记 adjacent_abnormal_candidate，避免将可行日期集合截断误读为已覆盖完整曲线。NYH2_2023的+20天配置热时间不足，最优+15天因此有这一标记。

{markdown_table(window_table)}

![完整过程变化](figures/daily_process_comparison.png)

逐日保存冠层覆盖、生物量、根深、GDD、蒸发、蒸腾、降雨、径流、排水、20隔室含水量和水量残差。阶段表 stage_covariates.csv 使用不重叠的热时间代理区间，重新聚合各播期降水/GDD/蒸散与温度暴露。温度暴露计数不等于模型授粉损失系数；蒸腾缺口为派生诊断，不是完整氮/生殖胁迫状态。未输出虚构的LAI、氮循环、独立散粉/吐丝或粒数。

## 5. 输入不确定性、状态与质量检查

![输入敏感性](figures/input_sensitivity.png)

分别扰动共同起点初始可利用水25%/75%和根深倍率0.8/1.2，作物校准参数不重新拟合。根深−20%得到1.52 m；+20%因固定2 m剖面及底部缓冲仍限制为1.9 m，因此其曲线与基准重叠，**不能把这条重叠解释成作物对根深增加不敏感**。进一步向上检验根深需单独设计更深剖面实验。

window_sensitivity.csv 保存95%日期集合的Jaccard重叠、最优日期和边界峰。土壤水力参数、质地映射、成熟热时间及管理缺口未被这四项敏感性穷尽。

{markdown_table(status_table)}

当前可模拟情景水量最大日残差为 **{qc['max_water_balance_abs_mm_day']:.3g} mm/day**；土壤水边界通过：{qc['all_soil_water_bounds_ok']}；实际播期一致：{qc['all_actual_dates_match_nominal']}；全部雨养无隐含灌溉：{qc['all_irrigation_zero']}；播前过程存在：{qc['all_have_preplant_days']}。正式情景 execution_failed 数量为 {error_count}；热时间不足与死亡状态另见上表。开发期错误与校准无效候选仍保留在runs日志，不混入正式情景成功数量。

测试覆盖ET0基本行为、非连续/并列/边界窗口、无正成熟产量、校准标签隔离、无效候选不能被静默丢弃、零偏移重复、共同播前水分轨迹、固定剖面几何、热时间不足不补零，以及真实初始水分扰动和根深截断。

从正式情景中去重的可模拟任务日志读取，本机单次构建/模拟/诊断及可选保存耗时中位数为 **{observed_times.median():.3f} 秒**，95%分位为 **{observed_times.quantile(.95):.3f} 秒**。这是当前环境/设置的实测进程耗时，不是其他地点、机器或大规模率定的保证。

计算耗时来自本机 macOS ARM64、Python3.10、3个进程和当前输出设置；依赖下载、缓存命中与首次导入分开看，不能外推成通用性能benchmark。分阶段计时（缓存命中阶段可能很短）：

{markdown_table(pd.DataFrame(timings)) if timings else '见 timing_*.json。'}

## 6. 证据层级与下一步判断

- **模型可以运行：已建立证据。** 固定版本、原始输入/单位、完整逐日重运行、状态日志及过程检查均可复现。
- **原播期表现得到验证：有限证据。** 三个2023测试环境和三折留地点评价已完成，但只有代表性玉米、估计土壤/初始化与管理假设；开花只是代理，HI0边界提示参数补偿风险。
- **反事实播期响应可信：尚未建立。** 没有多播期实测对照，也没有独立冠层、成熟、生物量/水分过程验证，窗口只描述本实验的模型条件最优。

下一版优先核实年度土壤差异、播种密度及实际管理；增加成熟或冠层/水分观测后再释放成熟热时间或更多作物参数。再用独立多播期玉米试验评价曲线形状、最优日、窗口和边界，不依据本次2023成绩直接增加参数或更换输入以改善同一测试集。

## 7. 文件和复现

主入口：项目目录运行 `.venv/bin/python -m aquacrop_demo all`。分阶段支持 smoke/prepare/baseline/calibrate/validate/scenarios/report；使用相同配置与来源哈希恢复已完成任务。依赖锁文件 requirements-aquacrop.lock.txt，配置 aquacrop_demo/config.yaml，操作说明 aquacrop_demo/README.md。

关键产物：environments.csv、selection_audit.csv、weather_manifest.json、calibration_parameters.json、calibration_search.csv、validation_predictions.csv、validation_metrics.csv、validation_final_yield_diagnostics.csv、scenario_summary.csv、planting_windows.json/csv、stage_covariates.csv、window_sensitivity.csv、quality_checks.json，以及 runs/ 中逐情景参数/土壤/逐日Parquet。

[OSPy源码](https://github.com/aquacropos/aquacrop)、[3.1.0发行包](https://pypi.org/project/aquacrop/3.1.0/)、[作物参数定义](https://github.com/aquacropos/aquacrop/blob/master/aquacrop/entities/crops/crop_params.py)。已直接核验本次3.1.0发行包附带LICENSE为 **Apache-2.0**，全文副本和哈希见 aquacrop-3.1.0.LICENSE.txt 与 installed_environment.json；PyPI许可元数据标作MIT，与实际LICENSE不一致。
"""
    (out / "结果报告.md").write_text(txt, encoding="utf-8")
    print(f"Report ready: {out / '结果报告.md'}", flush=True)
    return qc
