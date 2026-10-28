# 现有 ML 响应面与残差诊断

返回 [文档目录](README.md) · [实验执行与历史索引](experiments.md)。

本页调用已有 [snowwindow.ml.experiment](../src/snowwindow/ml/experiment.py)
函数，不新增算法、依赖、YAML schema 或 CLI 子命令。Python 依赖按
[上手指南](getting-started.md)安装；无需 scikit-learn。
这些是模拟响应面的留站/留环境诊断，不是用真实田间标签证明预测精度。

## 前置输入与输出边界

从仓库根目录执行下列 here-doc。需要已经存在的三个 demo 扫描与三个
±14 天 forecast 表：

```text
outputs/experiments/g2f_demo/scan/summary.csv
outputs/experiments/g2f_apsim_demo/scan/summary.csv
outputs/experiments/g2f_dssat_demo/scan/summary.csv
outputs/experiments/g2f_forecast_demo/forecast/forecast_curves.csv
outputs/experiments/g2f_apsim_forecast_demo/forecast/forecast_curves.csv
outputs/experiments/g2f_dssat_forecast_demo/forecast/forecast_curves.csv
```

这些都是本地产物，clone 不包含。生成前提见 [配置清单](../configs/README.md)；
缺文件会明确失败，不自动补跑、不从历史脚本生成数据。
切换 ±30 天研究时，把下面三个 forecast ID 一致改为相应 `_radius30` ID，
并使用新的目标实验 ID，不能混用候选域。

示例默认写入新目录
`outputs/experiments/g2f_ml_reproduction_20261027/ml/`，目标实验目录已存在就
拒绝执行。可通过 `ML_EXPERIMENT_ID` 设置另一个新 ID；源文件始终只读，
不会覆盖历史 `g2f_window_ml_exploration`。

## 可复制执行的两个函数调用

第一部分显式构造 `day_of_year`：当前 `response_surface_dataset` 在生成
该列之前就会检查所请求特征，不能只依赖函数内部自动派生日期。
只使用 `calibrated`、`matured` 且正产量的扫描记录；原始失败记录仍留在源表。
第二部分按环境/播期将 forecast 与各自模型的 calibrated oracle 一一关联，
目标是 `oracle - forecast`，不是“观测产量残差”。

```bash
ML_EXPERIMENT_ID=g2f_ml_reproduction_20261027 .venv/bin/python - <<'PY'
import hashlib
import json
import os
import re
from pathlib import Path

import pandas as pd

from snowwindow.ml.experiment import (
    residual_correction_dataset,
    response_surface_dataset,
)

experiment_id = os.environ.get(
    "ML_EXPERIMENT_ID", "g2f_ml_reproduction_20261027"
)
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", experiment_id):
    raise SystemExit("ML_EXPERIMENT_ID 必须是安全的新目录名")
root = Path("outputs/experiments")
experiment_dir = root / experiment_id
if experiment_dir.exists():
    raise SystemExit(f"拒绝覆盖已有实验：{experiment_dir}；请使用新 ID")

runs = {
    "aquacrop": ("g2f_demo", "g2f_forecast_demo"),
    "apsim": ("g2f_apsim_demo", "g2f_apsim_forecast_demo"),
    "dssat": ("g2f_dssat_demo", "g2f_dssat_forecast_demo"),
}
paths = {
    model: (
        root / source_id / "scan/summary.csv",
        root / forecast_id / "forecast/forecast_curves.csv",
    )
    for model, (source_id, forecast_id) in runs.items()
}
missing = [
    str(path)
    for pair in paths.values()
    for path in pair
    if not path.is_file()
]
if missing:
    raise SystemExit("缺少前置产物，请先完成源实验与 forecast：\n" + "\n".join(missing))


def require_columns(frame, columns, path):
    missing_columns = set(columns).difference(frame.columns)
    if missing_columns:
        raise SystemExit(f"{path} 缺少列：{sorted(missing_columns)}")


surface_frames = []
residual_frames = []
for model, (scan_path, forecast_path) in paths.items():
    scan = pd.read_csv(scan_path)
    require_columns(
        scan,
        ("environment_id", "planting_date", "parameter_set", "status",
         "dry_yield_mg_ha"),
        scan_path,
    )
    scan["planting_date"] = pd.to_datetime(scan["planting_date"], errors="raise")
    scan["dry_yield_mg_ha"] = pd.to_numeric(
        scan["dry_yield_mg_ha"], errors="coerce"
    )
    oracle = scan.loc[
        scan["parameter_set"].eq("calibrated")
        & scan["status"].eq("matured")
        & scan["dry_yield_mg_ha"].gt(0),
        ["environment_id", "planting_date", "dry_yield_mg_ha"],
    ].copy()
    if oracle.empty:
        raise SystemExit(f"{scan_path} 没有正产量的 matured/calibrated 记录")
    if oracle.duplicated(["environment_id", "planting_date"]).any():
        raise SystemExit(f"{scan_path} 的 oracle 键重复")
    oracle["model"] = model
    oracle["site"] = oracle["environment_id"].str.rsplit("_", n=1).str[0]
    oracle["year"] = oracle["planting_date"].dt.year
    oracle["day_of_year"] = oracle["planting_date"].dt.dayofyear
    if oracle["site"].nunique() < 2:
        raise SystemExit(f"{scan_path} 至少需要两个站点做留站评估")
    surface_frames.append(oracle)

    forecast = pd.read_csv(forecast_path)
    require_columns(
        forecast,
        ("environment_id", "planting_date", "forecast_mean_yield_mg_ha"),
        forecast_path,
    )
    forecast["planting_date"] = pd.to_datetime(
        forecast["planting_date"], errors="raise"
    )
    curves = forecast.merge(
        oracle[
            ["environment_id", "planting_date", "model", "dry_yield_mg_ha"]
        ].rename(columns={"dry_yield_mg_ha": "oracle_yield_mg_ha"}),
        on=["environment_id", "planting_date"],
        how="inner",
        validate="one_to_one",
    )
    if curves.empty:
        raise SystemExit(f"{forecast_path} 与成熟 oracle 没有共同候选日期")
    print(f"{model}: forecast {len(forecast)} 行，成熟 oracle 匹配 {len(curves)} 行")
    residual_frames.append(curves)

surface_input = pd.concat(surface_frames, ignore_index=True)
surface = response_surface_dataset(
    surface_input, alpha=1.0, features=("day_of_year",)
)
residual_input = pd.concat(residual_frames, ignore_index=True)
if residual_input["environment_id"].nunique() < 2:
    raise SystemExit("残差诊断至少需要两个环境做留环境评估")
# 默认含 oracle 派生残差特征：这是泄漏诊断，不是可部署模型。
residual = residual_correction_dataset(residual_input, alpha=1.0)
for label, dataset in (("surface", surface), ("residual", residual)):
    if dataset["metrics"].empty:
        raise SystemExit(f"{label} 未生成有效评估记录")
    print(label)
    print(dataset["metrics"].to_string(index=False))

# 全部输入与计算成功后才创建新实验，所有写入限定在其 ml/ 下。
output = experiment_dir / "ml"
experiment_dir.mkdir(parents=True, exist_ok=False)
output.mkdir()
surface_input.to_csv(output / "surface_input.csv", index=False)
residual_input.to_csv(output / "residual_input.csv", index=False)
for label, dataset in (("surface", surface), ("residual", residual)):
    for name, frame in dataset.items():
        frame.to_csv(output / f"{label}_{name}.csv", index=False)
fingerprints = {
    str(path): hashlib.sha256(path.read_bytes()).hexdigest()
    for pair in paths.values()
    for path in pair
}
(output / "manifest.json").write_text(
    json.dumps(
        {
            "experiment_id": experiment_id,
            "alpha": 1.0,
            "surface_features": ["day_of_year", "sin_doy", "cos_doy"],
            "residual_features": "函数默认值，含 oracle 派生特征",
            "source_fingerprints": fingerprints,
            "interpretation": "模拟响应面与 oracle 泄漏诊断，非实时部署验证",
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n",
    encoding="utf-8",
)
print(f"结果已写入 {output}")
PY
```

结果包括 `surface_{features,predictions,metrics}.csv`、
`residual_{predictions,metrics}.csv`、两个输入表和输入指纹 manifest。
没有在此示例中实现新的参数搜索、窗口优化算法或历史汇报模板。

## 解释与信息边界

- 响应面函数按模型分别留一站点，拟合的是扫描模拟产量，不是田间产量。
  扫描可含 2022/2023；此折法评估跨站点的模拟面近似，不等于留年预测验证。
- 默认残差函数按 environment 留一折；不同模型同一环境一起留出。
  `residual_centered_mg_ha`、居中 3/5/9 日滑窗和滞后残差都从
  `oracle_yield_mg_ha` 派生，包括留出环境的 oracle 信息。
  所以即使训练拟合未用留出行标签，特征仍泄漏目标；这只是 oracle 残差
  多尺度的诊断上界，不可实时部署，也不能声称独立无泄漏评估。
- 可显式传 `features=("forecast_mean_yield_mg_ha",)` 研究较少泄漏的特征口径，
  但仍需另做按站点/年份隔离、真实预测时信息可得性和样本量审计；
  改一行参数不构成部署验证。
- `FixedWindowFeatureBuilder` / `add_weather_features` 默认窗口为播前 45 天、
  播后 60 天；如果输入是播后实测天气，它不可能是播前业务可用输入。
  固定窗口不等于无泄漏。若用预报或情景，必须记录来源及信息截止日。
- forecast 的窗口覆盖率有历史口径差异，oracle 又可能与情景采用不同天气
  或时限。不要把上述 MAE 当成观测精度、推荐命中率或田间增益。
- 历史消融、离线图文汇报及 `g2f_window_ml_exploration` 内脚本属于附加研究。
  保留 [历史索引](experiments.md) 和日志，但不承诺逐项复刻；不要修改历史
  outputs 脚本、manifest 或结论来使当前示例“对齐”。
