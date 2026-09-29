# 配置指南

返回 [README](../README.md)。

## 最小结构

```yaml
experiment_id: g2f_demo
data_dir: ../data
output_dir: ../outputs

model:
  name: aquacrop
  parameters: {}

selection:
  environments: [INH1_2022]
  calibration_years: [2022]
  evaluation_years: [2023]

simulation:
  scan_fractions: [0.90, 0.95]
  scan_all_dates: true
  workers: 1
```

## 模型选择

`model.name` 通过 `AdapterRegistry` 解析：

- `aquacrop`：AquaCrop-OSPy 3.1.0。
- `apsim`：APSIM NG 2026.9.8116。
- `dssat`：DSSAT-CSM 4.8.6.2 / CERES-Maize。

模型特定翻译必须留在 `src/snowwindow/models/<model>/`，编排层只消费
`ModelCapabilities`。

## 校准与评估

- `selection.calibration_years`：允许用于参数选择的年份。
- `selection.evaluation_years`：独立评估年份，不能与校准年份相交。
- `selection.environments`：显式环境列表。
- `selection.all_eligible_environments`：使用全部合格环境。
- `selection.allow_assumed_rainfed`：允许显式标记的假定雨养样本。

统一推荐配置：

```yaml
calibration:
  phenology_grid: [0.8, 1.2, 0.02]
  phenology_fine_step: 0.005
  yield_grid: [0.35, 0.55, 0.01]
  yield_fine_step: 0.0025
```

旧模型专属键仍可使用：

| 模型 | 旧物候键 | 旧产量键 |
| --- | --- | --- |
| AquaCrop | `phenology_scale_grid`、`phenology_scale_fine_step` | `harvest_index_grid`、`harvest_index_fine_step` |
| APSIM | `juvenile_tt_grid`、`juvenile_tt_fine_step` | `grain_number_scale_grid`、`grain_number_scale_fine_step` |
| DSSAT | `P1_grid`、`P1_fine_step` | `G2_grid`、`G2_fine_step` |

统一键优先；未设置时按模型能力契约提供安全默认值。

## 播期扫描

- `simulation.scan_fractions`：窗口产量阈值，必须在 `(0, 1]`。
- `simulation.scan_all_dates`：启用全年逐日扫描。
- `simulation.workers`：并行度，`1` 表示串行确定性执行。
- `simulation.parameter_sets`：`default`、`calibrated`、
  `site_calibrated` 等参数组。

全年扫描是反事实模拟。只有实际 G2F 播期可以作为观测验证点。

## 配置快照

实验运行时应保留一份解析后的配置快照到
`outputs/experiments/<experiment_id>/config.yaml`，便于 catalog 识别模型
和追溯复现输入。该文件属于生成物，不提交到 Git。
