# 实验结果索引

返回 [README](../README.md)。

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

`config.yaml` 是运行时配置快照；`INDEX.md` 和 `catalog.json` 由命令生成，
不要手工编辑。

## 生成索引

```bash
.venv/bin/python -m snowwindow catalog --config configs/g2f_demo.yaml
```

输出：

- `outputs/experiments/INDEX.md`：人类可读表。
- `outputs/experiments/catalog.json`：机器可读记录。

每条记录包含 `experiment_id`、`model`、`status`、`config_path`、
`report_path`、`metrics_path`、`summary_path`、`windows_path`、
`parameters_path` 和 `notes`。

## 状态定义

- `complete`：报告、指标、扫描摘要、适播窗口和校准参数均存在。
- `partial`：标准产物存在但不完整。
- `legacy`：位于 `legacy/` 且缺少标准报告结构的历史输出。
- `setup`：安装、冒烟或运行时验证目录。

## 当前主要实验

| 实验 | 模型 | 入口 |
| --- | --- | --- |
| 六环境演示 | AquaCrop | `outputs/experiments/g2f_demo/report/report.md` |
| APSIM 六环境 | APSIM | `outputs/experiments/g2f_apsim_demo/report/report.md` |
| DSSAT 六环境 | DSSAT | `outputs/experiments/g2f_dssat_demo/report/report.md` |
| refined 历史实验 | AquaCrop | `outputs/experiments/g2f_aquacrop_refined/` |

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
