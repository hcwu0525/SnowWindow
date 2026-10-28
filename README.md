# SnowWindow

SnowWindow 是 G2F 玉米播期情景实验流水线：只读审计与标准化数据，
通过统一适配器运行 AquaCrop、APSIM 和 DSSAT，开展校准、独立年份验证、
全年播期扫描、回顾式预测和探索性 ML 分析。它不是业务化播期预报系统。

## 快速开始

```bash
uv venv --python 3.10 --seed .venv
.venv/bin/python -m pip install -r requirements-aquacrop.lock.txt -e '.[dev]'
.venv/bin/python -m pip check
# 按“数据下载指南”取得全部 13 个 G2F 文件后，先检查数据链路
make audit prepare CONFIG=configs/g2f_demo.yaml
```

推荐 Python 3.10；项目元信息支持 3.10–3.12。`make setup` 等价于创建环境、
安装并检查依赖。官方入口、下载步骤与首次校验见
[数据下载指南](docs/data-download.md)；天气缺口和引擎前提见
[快速上手](docs/getting-started.md)。新 clone 不包含数据或引擎；三模型统一
使用 G2F `full_year` 原始分表标准化天气，不需要外部天气缓存。
G2F 自身缺测仍可能导致失败，APSIM/DSSAT 引擎也仍需独立安装。

天气策略更新（2026-10-27）：不读取 legacy POWER CSV 或其 provenance；
仅在 `simulation.scan_horizon: cross_year` 且配置显式映射下一年同站点
G2F 环境时追加延续记录，无映射不自动替代。2024 相关模拟与 scan/forecast
候选播期最晚为 2024-11-10（当年 315 天，保留 2/29）；7/12–7/14
核心缺测不得补零、外部替代或改标成熟。天气不足时受实际可用截止日限制并
记录截断，内部缺口仍保留失败。历史实验不追认为新策略验证通过；
新策略必须使用新实验 ID，模型结果缓存与断点恢复仍保留。

## 仓库结构与 Git 边界

| 路径 | 职责 |
| --- | --- |
| `src/snowwindow/` | 数据契约、适配器、校准、扫描、报告、forecast 与 ML |
| `tests/snowwindow/` | 对应模块测试；真实数据/引擎测试标为 integration |
| `configs/` | 11 份实验 YAML 与[配置清单](configs/README.md) |
| `docs/` | 用户指南、历史日志与研究材料；`docs/superpowers/` 为实施计划 |
| `scripts/` | 辅助绘图脚本，不等同于主流水线 |
| `bin/` | 可维护的引擎启动器，不含引擎本体 |
| `patches/` | 指定版本的本地兼容补丁 |

`data/`（只读、自备）、`outputs/`（全部生成物）、`.tools/`（本地引擎）、
`dssat-csm-os/`（第三方源码）和虚拟环境不入库。表格、缓存、图、manifest
及报告写入 `outputs/experiments/<experiment_id>/`，不提交历史产物。

## 三类模型能力概览

| 能力 | AquaCrop 3.1.0 | APSIM NG 2026.9.8116.0 | DSSAT 4.8.6.2 |
| --- | --- | --- | --- |
| 分发方式 | 锁定的 Python 依赖 | 本地原生引擎，独立安装/授权 | 本地原生引擎及数据，独立安装/授权 |
| 校准参数 | `phenology_scale`、`HI0` | `juvenile_tt`、`grain_number_scale` | `P1`、`G2` |
| 站点校准 | 支持 | 暂不支持 | 暂不支持 |
| 已有历史验证 | 六环境闭环 | 固定探索情景六环境闭环 | 固定参考情景六环境闭环 |
| 主要限制 | 单层土壤、无完整氮循环 | 土壤水氮与品种为固定假设 | 土壤、品种、施氮为固定参考输入 |

详细边界见各模型指南：
[AquaCrop](docs/models/aquacrop.md)、
[APSIM](docs/models/apsim.md)、
[DSSAT](docs/models/dssat.md)。

## 文档索引

- [快速上手](docs/getting-started.md)：环境、数据、AquaCrop 示例和可选引擎。
- [数据下载指南](docs/data-download.md)：官方 DOI、下载与放置、13 文件校验和来源记录。
- [配置指南](docs/configuration.md)：配置结构、统一校准键和兼容策略。
- [配置清单](configs/README.md)：11 个实验的年份、命令、前置产物与限制。
- [实验结果索引](docs/experiments.md)：目录规范、catalog 和复现入口。
- [ML 实验](docs/ml-experiments.md)：现有函数的可执行示例与信息泄漏边界。
- [G2F 数据映射](docs/g2f-data.md)：字段、单位、覆盖范围和缺口。
- [模型比较](docs/model-comparison.md)：机制、输入输出和适用范围。
- [研究日志](docs/model-usage-log.md)：历史实验证据和结论边界。
- [文档目录](docs/README.md)：持续维护约定。

## 常用命令

```bash
# 数据、驱动与引擎前提满足后，完整运行至报告（不含 forecast）
make run CONFIG=configs/g2f_demo.yaml
# 独立预测：先完成其 source experiment 的校准和扫描
make forecast CONFIG=configs/g2f_forecast_demo.yaml
make catalog CONFIG=configs/g2f_demo.yaml
```

Make 也提供 `venv/install/setup/check/test/test-integration` 及
`audit/prepare/baseline/calibrate/validate/simulate/scan/report/forecast/run/catalog`。
默认 `CONFIG=configs/g2f_demo.yaml`、`PYTHON=.venv/bin/python`、
`VENV_PYTHON=python3.10`。CLI 不变，例如
`.venv/bin/python -m snowwindow scan --config configs/g2f_demo.yaml`。
结果总索引为配置 `output_dir` 下的 `experiments/INDEX.md` 和 `catalog.json`。

## 验证

提交前运行：

```bash
make check
make test
# 已恢复外部数据与对应引擎时再运行
make test-integration
```

`test` 仅运行非 integration，`test-integration` 仅运行 integration；
标记通过 `PYTEST_ADDOPTS` 传递，避免命令行 `-m` 与 AquaCrop 的解析冲突。
本次独立安装、测试与原生冒烟的范围见
[仓库整理验收记录](docs/reproducibility-validation.md)，不代表重跑历史科学实验，
也不代替本次 G2F 统一天气策略的验证；其中旧天气缓存测试属于当时记录。

## 科学使用边界

`data/` 保持只读；所有生成物写入 `outputs/experiments/<experiment_id>/`。
校准与评估年份必须不相交；不得用评估年份观测选择参数。失败和未成熟
运行必须保留原始状态与输入指纹。相同配置可恢复扫描；更改配置必须使用
新 `experiment_id`。全年播期是反事实情景，oracle 是模拟而非田间真值；
历史结果不保证在当前源码下数值逐项复刻。
