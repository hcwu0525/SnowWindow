# 实验结果索引

返回 [README](../README.md)。

本页 `outputs/` 路径和证据链接均指向本地产物，clone 不包含。
历史实验与汇报索引保留原有内容；以下执行指南于 2026-10-27 核对，
不表示重新执行了历史实验。

## 执行指南

先完成 [安装、13 文件清单与 G2F 天气核对](getting-started.md)，并阅读
[11 个配置的前提与状态](../configs/README.md)。不要直接覆盖历史实验：
改配置时复制 YAML、设置新 `experiment_id`；已有同 ID 不同配置会拒绝覆盖。
同配置可继续分阶段运行。所有命令从仓库根目录执行。

顺序为 audit/prepare → baseline → calibrate → validate → scan → report
→ forecast（独立配置）→ catalog。逐步运行示例：

```bash
.venv/bin/python -m snowwindow audit --config configs/g2f_demo.yaml
.venv/bin/python -m snowwindow prepare --config configs/g2f_demo.yaml
.venv/bin/python -m snowwindow baseline --config configs/g2f_demo.yaml
.venv/bin/python -m snowwindow calibrate --config configs/g2f_demo.yaml
.venv/bin/python -m snowwindow validate --config configs/g2f_demo.yaml
.venv/bin/python -m snowwindow scan --config configs/g2f_demo.yaml
.venv/bin/python -m snowwindow report --config configs/g2f_demo.yaml
.venv/bin/python -m snowwindow forecast --config configs/g2f_forecast_demo.yaml
.venv/bin/python -m snowwindow catalog --config configs/g2f_demo.yaml
```

`simulate` 是实际播期 baseline 的别名，不替代全年 scan。
`audit` 只返回内存审计并打印计数，不落盘；`prepare` 才保存审计与标准化表。
baseline/calibrate 缺 prepare manifest 时会准备数据；validate 必须有校准
产物，scan 必须有 prepared 表和 held_year 校准参数，report 使用已有结果。
不要把命令顺序当成自动修复缺输入的承诺。

三模型主 `run`（每条都需先满足对应天气/引擎前提）：

```bash
make run CONFIG=configs/g2f_demo.yaml
make run CONFIG=configs/g2f_apsim_demo.yaml
make run CONFIG=configs/g2f_dssat_demo.yaml
```

`run` 仅包含 prepare（按需）至 report，不含 forecast。六个预测命令：

```bash
make forecast CONFIG=configs/g2f_forecast_demo.yaml
make forecast CONFIG=configs/g2f_apsim_forecast_demo.yaml
make forecast CONFIG=configs/g2f_dssat_forecast_demo.yaml
make forecast CONFIG=configs/g2f_forecast_demo_radius30.yaml
make forecast CONFIG=configs/g2f_apsim_forecast_demo_radius30.yaml
make forecast CONFIG=configs/g2f_dssat_forecast_demo_radius30.yaml
```

三对预测分别依赖 `g2f_demo`、`g2f_apsim_demo`、`g2f_dssat_demo` 的
`normalized/{environments,management_units,soil_profiles,weather}.parquet`、
`calibration/parameters.parquet` 和 `scan/summary.parquet`。先完成源实验
校准与扫描；仅执行预测配置的 prepare 不够，也不会自动回填源实验。
新建源实验 ID 后，还须在新预测配置中同步 `selection.source_experiment_id`。

六个预测均以 2023-03-01 为信息截止日，比较 ±14/±30 天候选域。
它们是历史天气情景与模型 oracle 的回顾式诊断，不是全年最优或田间增产证明。
源实验、预测 manifest、天气来源和时限都要一起核对；历史结果不保证当前
代码数值完全复刻。refined/history 仅为广域研究配置，跨年缺口未解决，
不能按三模型 demo 的历史完成状态推断它们也已完成。

天气策略变更（2026-10-27）：三模型统一只用 G2F `full_year` 原始分表
标准化天气，不读取 legacy POWER CSV/provenance，不需外部天气缓存。
普通模拟先读当前环境 `normalized/weather.parquet`，只有
`simulation.scan_horizon: cross_year` 且显式映射下一年同站点 G2F 环境
才追加记录；无映射不自动替代。实际天气不足时记录尾部截断，内部缺日期/
核心值仍保留失败。2024 相关模拟与 scan/forecast 候选播期不晚于
2024-11-10（315 天，保留 2/29）；7/12–7/14 核心缺测不得补零、外部替代
或改标成熟。该数据截止日不是 forecast 信息截止日；预测仍用 G2F 历史
同站点情景，不用目标年未来实测选参，六个配置仍评估 2023。

以下历史索引、数值与日期原样保留，不代表新策略实验已完成。
新策略必须使用新实验 ID 和带 `weather_policy` 的新快照，不能复用旧扫描
oracle、参数或结果缓存；forecast 也须新 ID 并指向同策略的新源实验。
详见[配置快照](configuration.md#配置快照与重跑)。

## 标准目录

```text
outputs/experiments/<experiment_id>/
  config.yaml
  report/report.md
  validation/metrics.csv
  scan/summary.csv
  scan/windows.csv
  calibration/parameters.json
```

`config.yaml` 是运行时配置快照，自动记录 G2F `weather_policy`；
`INDEX.md` 和 `catalog.json` 由命令生成，
不要手工编辑。

## 生成索引

```bash
.venv/bin/python -m snowwindow catalog --config configs/g2f_demo.yaml
```

输出位于该配置 `output_dir` 下，而不是固定使用当前目录 `outputs`；
随仓库 YAML 的输出如下：

- `outputs/experiments/INDEX.md`：人类可读表。
- `outputs/experiments/catalog.json`：机器可读记录。

每条记录包含 `experiment_id`、`model`、`status`、`config_path`、
`report_path`、`metrics_path`、`summary_path`、`windows_path`、
`parameters_path` 和 `notes`。
预测实验另有 `forecast_report_path`。catalog 不创建实验 `config.yaml`，
不补跑缺失阶段，也不按指标判断科学有效性。

## 状态定义

- `complete`：报告、指标、扫描摘要、适播窗口和校准参数均存在。
- `partial`：标准产物存在但不完整。
- `legacy`：位于 `legacy/` 且缺少标准报告结构的历史输出。
- `setup`：安装、冒烟或运行时验证目录。

预测实验若 `forecast/report.md` 和 `forecast/manifest.json` 均存在，
catalog 也可标 `complete`；这是文件齐备判断，不表示所有情景成熟或业务验证通过。

## 当前主要实验

| 实验 | 模型 | 入口 |
| --- | --- | --- |
| 六环境演示 | AquaCrop | `outputs/experiments/g2f_demo/report/report.md` |
| APSIM 六环境 | APSIM | `outputs/experiments/g2f_apsim_demo/report/report.md` |
| DSSAT 六环境 | DSSAT | `outputs/experiments/g2f_dssat_demo/report/report.md` |
| refined 历史实验 | AquaCrop | `outputs/experiments/g2f_aquacrop_refined/` |
| 播期预测 Demo | AquaCrop | `outputs/experiments/g2f_forecast_demo/forecast/report.md` |
| APSIM 播期预测 | APSIM | `outputs/experiments/g2f_apsim_forecast_demo/forecast/report.md` |
| DSSAT 播期预测 | DSSAT | `outputs/experiments/g2f_dssat_forecast_demo/forecast/report.md` |
| 播期预测 ±30 天扩展 | AquaCrop | `outputs/experiments/g2f_forecast_demo_radius30/forecast/report.md` |
| APSIM 播期预测 ±30 天扩展 | APSIM | `outputs/experiments/g2f_apsim_forecast_demo_radius30/forecast/report.md` |
| DSSAT 播期预测 ±30 天扩展 | DSSAT | `outputs/experiments/g2f_dssat_forecast_demo_radius30/forecast/report.md` |
| 窗口 ML 探索 | 多模型 | `outputs/experiments/g2f_window_ml_exploration/ml/experiment.md` |
| 残差修正探索 | 多模型 | `outputs/experiments/g2f_window_ml_exploration/ml/residual/experiment.md` |
| 播期预测讲解与结果核对（2026-10-11） | 多模型 | [完整汇报](../outputs/experiments/g2f_window_ml_exploration/briefing/播期预测研究汇报.md) · [离线图文版](../outputs/experiments/g2f_window_ml_exploration/briefing/播期预测研究汇报.html) |

汇报采用独立候选域 oracle 阈值重新计算推荐命中率，保留旧指标供对照；
请勿将旧 forecast 报告的 `recommended_window_coverage` 与新定义混用。
汇报还区分田间观测验证与 oracle 仿真比较，并披露存量天气驱动和模拟时限差异。

当前 CLI 为兼容既有研究，仍保留原有预测指标定义：oracle 阈值窗口在
forecast 推荐日期子集中计算，而不是整个候选域，因此覆盖率可能偏高；
`forecast_best_date` 在与成功 oracle 记录关联后选择，oracle 失败的日期
可能被排除，不能将它解读为评估前已冻结的部署推荐。天气策略更新没有修改
这两个计算口径；使用结果时须披露限制，不能直接据此宣称推荐命中或增产。
若需独立候选域阈值或冻结推荐评估，应作为单独方法变更，用新实验 ID 验证。

历史输出已统一迁移到 `outputs/experiments/legacy/`，包括：
`aquacrop_all_environment_audit`、`aquacrop_annual`、
`aquacrop_crossyear`、`aquacrop_demo`、`data_audit_20260922`
和 `scan-refined.log`。

## 复现

优先使用源码配置：

```bash
.venv/bin/python -m snowwindow run --config configs/g2f_demo.yaml
```

对中断的全年扫描，重新执行同一 `scan` 命令即可从
`model_cache/<model>/scan_progress.jsonl` 恢复。不要删除失败或未成熟记录。

扫描日志与适配器缓存一起保留；进度键不意味着成熟成功，也不保证所有模型
都有相同的断点机制。AquaCrop/DSSAT 可按请求缓存复用，APSIM 按批次缓存复用。
缺缓存不能只凭进度 JSONL 假定结果完整；让适配器重新核对，不手工跳过。
这些模型输入/结果缓存及断点恢复继续保留，不属于已取消的外部天气缓存；
恢复仅限相同天气策略与可信快照的新实验，不能跨新旧策略混用。
不要并发运行同一实验 ID。更换代码、数据、引擎或参数假设时使用新 ID，
保留源文件 SHA256、prepare manifest、固定校准观测、引擎/模板指纹与失败原因。
catalog 或历史报告不是这些复现依据的替代品。

## ML 与附加研究

现有 `response_surface_dataset`、`residual_correction_dataset` 的可复制调用
见 [ML 实验指南](ml-experiments.md)，只写新的实验 ID 下 `ml/`。
历史消融与上表离线汇报是附加研究索引，不承诺由主 CLI 或现有 11 个 YAML
逐项重建；不要改写历史 `outputs/` 下脚本、manifest 或结论。
