# 实验配置清单

返回 [README](../README.md) · [字段说明](../docs/configuration.md) ·
[执行顺序与历史索引](../docs/experiments.md)。

本目录现有 11 个 YAML；没有额外 schema。所有命令从仓库根目录执行。
表中的路径均为本地生成物，不随 clone 分发。随仓库 YAML 的
`data_dir: ../data`、`output_dir: ../outputs` 相对 YAML 目录解析。
输出根为 `outputs/experiments/<experiment_id>/`，当前 ID 与 YAML 文件干同名。
保留历史结果或更改任何配置时，先复制 YAML、设置新 ID，再运行；
同 ID 不同配置会被快照检查拒绝。

天气策略更新：2026-10-27。下表的完成状态与数值结论只描述历史产物，
不表示当前 G2F 统一策略已重跑通过。即使沿用示例文件名，也不得混用旧快照/
历史产物：新建实验 ID，forecast 同时新建 ID 并更新 `source_experiment_id`。
新快照自动记录
`weather_policy={source: g2f_full_year, end_date: 2024-11-10, continuation: explicit_g2f_environment_mapping}`；
不要手工给旧快照补标识，没有新增 `weather_source` 选项。

## 共用前提

- 安装与 13 个自备源文件见 [快速上手](../docs/getting-started.md)；
  EC 和 seasons_only 虽不输入模型，也必须存在。
- 主实验的 `run` 自动在缺 prepare manifest 时准备数据，随后运行
  baseline → calibrate → validate → scan → report，不含 forecast。
  单独 validate 需要校准产物，单独 scan 需要 prepared 表与 held_year 参数。
- 三模型统一从当前环境 `normalized/weather.parquet` 读取 G2F `full_year`
  原始分表标准化天气，不读取 legacy POWER CSV/provenance，不需外部天气缓存。
- 只有 `simulation.scan_horizon: cross_year` 且
  `simulation.continuation_weather_by_environment` 显式映射下一年同站点
  G2F 环境时才追加记录；无映射不自动替代。受实际天气截止日限制并记录
  尾部截断，内部缺日期/核心值继续保留失败。
- 2024 相关模拟与 scan/forecast 候选播期最晚为 2024-11-10（315 天，
  保留 2/29）；7/12–7/14 核心缺测不得补零、外部替代或改标成熟。
  此数据截止日不等于 `forecast_cutoff_*` 信息截止日。
- APSIM/DSSAT 主实验仍需独立安装/授权的引擎和参考输入；原 G2F 天气不保证
  跨年完整，“有配置”不等于“完整实验已复现”。模型结果缓存及断点恢复保留，
  不等于天气缓存。

## 主实验与广域研究（5 个）

demo 三模型都选 INH1、MOH2、NYH2 在 2022/2023 的六个环境。
三个主 demo 的显式延续映射一致：

```yaml
continuation_weather_by_environment:
  INH1_2022: INH1_2023
  MOH2_2022: MOH2_2023
  NYH2_2022: NYH2_2023
  INH1_2023: INH1_2024
  NYH2_2023: NYH2_2024
```

本地不存在 `MOH2_2024`，不配置或伪造。映射到不完整的 2024 也不证明跨年
资格通过；refined/history 保留空映射，仍有跨年研究缺口。
下面命令的 `make run` 可等价替换为
`.venv/bin/python -m snowwindow run --config <YAML路径>`。

| YAML | 模型 / 用途 | 选参年 → 评估年 | 运行命令 | 前置产物 / 外部条件 | 输出目录与状态、限制 |
| --- | --- | --- | --- | --- | --- |
| [g2f_demo.yaml](g2f_demo.yaml) | AquaCrop 六环境基准 | 2022 → 2023 | `make run CONFIG=configs/g2f_demo.yaml` | 13 源文件；完整驱动；prepare 可自动创建 | `outputs/experiments/g2f_demo/`；历史报告已运行，当前 normalized 天气链路不保证复刻历史数值 |
| [g2f_apsim_demo.yaml](g2f_apsim_demo.yaml) | APSIM 六环境固定探索情景 | 2022 → 2023 | `make run CONFIG=configs/g2f_apsim_demo.yaml` | 13 源文件、G2F 天气覆盖审计、APSIM/.NET/模板 | `outputs/experiments/g2f_apsim_demo/`；历史闭环；固定水氮、土壤和品种，非实测管理 |
| [g2f_dssat_demo.yaml](g2f_dssat_demo.yaml) | DSSAT 六环境参考情景 | 2022 → 2023 | `make run CONFIG=configs/g2f_dssat_demo.yaml` | 13 源文件、G2F 天气覆盖审计、DSSAT/官方数据/profile | `outputs/experiments/g2f_dssat_demo/`；历史闭环；固定 IB0035/IB00000007/120 kg N/ha，留年产量并未因校准而改善 |
| [g2f_aquacrop_refined.yaml](g2f_aquacrop_refined.yaml) | AquaCrop 全部候选环境、站点偏移研究 | 2014–2022 → 2023 | `make run CONFIG=configs/g2f_aquacrop_refined.yaml` | 13 源文件；先 audit/prepare 检查资格；站点偏移至少 3 训练年 | `outputs/experiments/g2f_aquacrop_refined/`；历史仅有准备/审计依据，不承诺完整闭环，continuation 空映射与跨年天气仍有缺口 |
| [g2f_history.yaml](g2f_history.yaml) | AquaCrop 全历史候选环境、全局参数 | 2014–2022 → 2023 | `make run CONFIG=configs/g2f_history.yaml` | 13 源文件；先 audit/prepare 检查资格与天气 | `outputs/experiments/g2f_history/`；广域研究入口，不承诺已完成；无 site_calibrated 组，跨年缺口未补齐 |

主实验常见产物为 `report/report.md`、`validation/metrics.csv`、
`calibration/parameters.{json,parquet}`、`scan/summary.{csv,parquet}` 和
`scan/windows.csv`；失败/未成熟记录与指纹保留。
refined/history 不建议新环境直接长跑，应先查看审计排除原因。

## 回顾式 forecast（6 个）

六个配置都只预测三个 2023 环境；参数来自源实验 2022 校准，2023 为回顾
评估年，信息截止 2023-03-01，候选步长 1 天、阈值 0.95。±14 天含 29
候选日，±30 天含 61 日，始终包含实际播期，不代表全年最优。

先运行对应源实验的 prepare、calibrate、scan（或满足前提后 `run`）。
forecast 读取源实验 `normalized/{environments,management_units,soil_profiles,weather}.parquet`、
`calibration/parameters.parquet` 和 `scan/summary.parquet`，不会自动创建它们。
预测自身的输出位于各行目录的 `forecast/`，包括 scenario_results、
forecast_curves、recommendations、manifest、report 和 figures。

| YAML | 模型 / 半径 | 选参年 → 目标评估年 | 运行命令 | 前置 source experiment | 输出目录与状态、限制 |
| --- | --- | --- | --- | --- | --- |
| [g2f_forecast_demo.yaml](g2f_forecast_demo.yaml) | AquaCrop / ±14 天 | 2022 → 2023 | `make forecast CONFIG=configs/g2f_forecast_demo.yaml` | `g2f_demo` 上述源产物 | `outputs/experiments/g2f_forecast_demo/`；历史回顾演示，oracle 是模拟而非观测 |
| [g2f_forecast_demo_radius30.yaml](g2f_forecast_demo_radius30.yaml) | AquaCrop / ±30 天 | 2022 → 2023 | `make forecast CONFIG=configs/g2f_forecast_demo_radius30.yaml` | `g2f_demo` 上述源产物 | `outputs/experiments/g2f_forecast_demo_radius30/`；历史候选域扩展，不是新田间试验 |
| [g2f_apsim_forecast_demo.yaml](g2f_apsim_forecast_demo.yaml) | APSIM / ±14 天 | 2022 → 2023 | `make forecast CONFIG=configs/g2f_apsim_forecast_demo.yaml` | `g2f_apsim_demo` 上述源产物；APSIM/.NET | `outputs/experiments/g2f_apsim_forecast_demo/`；历史回顾演示，保留未成熟情景 |
| [g2f_apsim_forecast_demo_radius30.yaml](g2f_apsim_forecast_demo_radius30.yaml) | APSIM / ±30 天 | 2022 → 2023 | `make forecast CONFIG=configs/g2f_apsim_forecast_demo_radius30.yaml` | `g2f_apsim_demo` 上述源产物；APSIM/.NET | `outputs/experiments/g2f_apsim_forecast_demo_radius30/`；历史候选域扩展，水氮/品种为固定假设 |
| [g2f_dssat_forecast_demo.yaml](g2f_dssat_forecast_demo.yaml) | DSSAT / ±14 天 | 2022 → 2023 | `make forecast CONFIG=configs/g2f_dssat_forecast_demo.yaml` | `g2f_dssat_demo` 上述源产物；DSSAT/官方数据 | `outputs/experiments/g2f_dssat_forecast_demo/`；历史回顾演示，参考管理并非实测 |
| [g2f_dssat_forecast_demo_radius30.yaml](g2f_dssat_forecast_demo_radius30.yaml) | DSSAT / ±30 天 | 2022 → 2023 | `make forecast CONFIG=configs/g2f_dssat_forecast_demo_radius30.yaml` | `g2f_dssat_demo` 上述源产物；DSSAT/官方数据 | `outputs/experiments/g2f_dssat_forecast_demo_radius30/`；历史候选域扩展，不是稳定增产证明 |

预测天气来自源实验 normalized 表：截止日当日以前用目标年天气，其后使用
同站点更早年份日值情景；不读取未来预报服务，也不会用 oracle 选模型参数。
历史源实验生成 oracle 所用 legacy 天气与预测 normalized 情景可能不同，
且模拟时限可能不同，旧比较必须保留该披露；当前策略须使用同策略的新源实验，
不能将旧 oracle 与新 forecast 混用。六个配置仍评估 2023，原训练网格与科学
参数不变；若另建 2024 研究，候选域/模拟硬截止不得晚于 11/10，但不得因此
放宽 forecast 信息截止政策。历史汇报另有指标口径，
不可把不同定义的窗口覆盖率混用。源码 `_report` 仍有固定 demo 叙述，
改半径/阈值后请以 manifest 和结果表核对实际设置，不照搬模板结论。

## 索引与后续研究

```bash
make catalog CONFIG=configs/g2f_demo.yaml
```

catalog 使用该 YAML 的 `output_dir`，生成其 `experiments/INDEX.md`、
`catalog.json`，不创建配置快照或自动补跑实验。
历史消融、ML 图文汇报不属于这 11 个 YAML 的逐项重建承诺；
现有 ML 函数调用与新输出目录约束见 [ML 指南](../docs/ml-experiments.md)。
