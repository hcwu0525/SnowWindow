# SnowWindow

SnowWindow 是一个玉米播期模拟与分析工具，用于整理 G2F 田间试验数据，
运行 AquaCrop、APSIM 和 DSSAT，并比较不同播期下的模拟产量与适播窗口。

例如：在同一地点，将玉米播期提前或推迟两周，模型给出的产量会怎样变化？
用 2022 年观测校准后，模型对 2023 年的表现如何？
SnowWindow 提供数据准备、模拟、校准、验证和分析所需的分阶段命令，
也可以在 Python 脚本或 Notebook 中调用相应函数。

[安装](#安装) · [第一个实验](#第一个实验) · [按任务使用](#按任务使用) ·
[自定义实验](#自定义实验) · [文档](#文档)

## 工作方式

一个典型的研究流程是：

```text
G2F 原始数据 → 整理模型输入 → 实际播期模拟 → 参数校准与验证 → 播期扫描 → 图表与报告
```

- **实际播期模拟**：使用田间记录中的播期，查看模型在这些环境下的产量和生育期。
- **参数校准与验证**：用训练年份选择参数，再用独立年份的观测评估模型。
- **播期扫描**：保持其他输入固定，逐日改变播期，得到产量曲线和适播窗口。
- **回顾式预测**：设定一个天气信息截止日，用历史天气情景比较候选播期。

这里的“环境”指一个站点与年份的组合，例如 `INH1_2022`。
各阶段通过 CSV、Parquet 和配置快照衔接，可以逐步运行并检查中间结果。

## 支持的模型

| 模型 | 安装方式 | 当前校准参数 | 指南 |
| --- | --- | --- | --- |
| AquaCrop-OSPy 3.1.0 | 随 Python 依赖安装 | `phenology_scale`、`HI0`；支持站点偏移 | [AquaCrop](docs/models/aquacrop.md) |
| APSIM NG 2026.9.8116.0 | 安装 APSIM 与 .NET 运行时 | `juvenile_tt`、`grain_number_scale` | [APSIM](docs/models/apsim.md) |
| DSSAT-CSM 4.8.6.2 | 安装原生引擎与官方参考数据 | `P1`、`G2` | [DSSAT](docs/models/dssat.md) |

建议从 AquaCrop 示例开始熟悉数据与输出，再按研究需要配置其他模型。
三种模型的输入映射和管理假设见[模型比较](docs/model-comparison.md)。

## 安装

推荐 Python 3.10，项目声明支持 Python 3.10–3.12。
以下命令使用 Bash 风格路径，在仓库根目录执行：

```bash
uv venv --python 3.10 --seed .venv
.venv/bin/python -m pip install -r requirements-aquacrop.lock.txt -e '.[dev]'
.venv/bin/python -m pip check
.venv/bin/python -m snowwindow --help
```

也可以使用 `python3.10 -m venv .venv` 创建环境，再执行相同的 pip 命令。
`make setup` 提供环境创建、依赖安装和兼容检查的快捷入口。
安装完成后，CLI 帮助可以列出所有实验命令。
环境问题和原生引擎安装步骤见[快速上手](docs/getting-started.md)。

## 第一个实验

这个例子使用 AquaCrop，先在实际播期运行模拟，查看模型输入和结果表。
示例配置选取 INH1、MOH2、NYH2 三个站点在 2022、2023 年的六个环境。

### 1. 准备 G2F 数据

使用 **G2F 2024 Maize Genotype by Environment Prediction Competition**
发布数据，DOI：`10.25739/78mn-4394`。
按[数据下载指南](docs/data-download.md)取得 13 个原始 CSV，放入：

```text
data/
├── Training_data/    # 6 个训练文件
└── Testing_data/     # 7 个测试文件
```

数据整理从这些原始分表开始。天气使用 G2F `full_year` 表，
EC 与 `seasons_only` 文件用于完整性审计；完整文件名和字段说明见
[G2F 数据映射](docs/g2f-data.md)。
原始文件作为只读输入保存在 `data/`，整理后的表格和实验结果统一写入 `outputs/`。

### 2. 创建实验配置

复制示例，给自己的实验起一个名字：

```bash
cp -n configs/g2f_demo.yaml configs/first_experiment.local.yaml
```

打开 `configs/first_experiment.local.yaml`，将顶层 `experiment_id` 改为：

```yaml
experiment_id: first_experiment
```

其余字段保持示例设置。`experiment_id` 决定输出目录；
`data_dir: ../data` 和 `output_dir: ../outputs` 相对 YAML 所在目录解析。
Git 会忽略 `configs/*.local.yaml`，便于保存本地实验设置。
再次使用本例时，可以沿用相同配置恢复运行，或用新 ID 开始另一组实验。

### 3. 检查数据并运行模拟

```bash
.venv/bin/python -m snowwindow audit --config configs/first_experiment.local.yaml
.venv/bin/python -m snowwindow prepare --config configs/first_experiment.local.yaml
.venv/bin/python -m snowwindow baseline --config configs/first_experiment.local.yaml
```

这三步分别做什么：

| 命令 | 工作 | 查看什么 |
| --- | --- | --- |
| `audit` | 检查源文件并在内存中整理数据 | 终端中的数据计数 |
| `prepare` | 保存标准化输入、详细审计和来源记录 | `audit/data_audit.json`、`audit/eligibility.parquet`、`normalized/` |
| `baseline` | 用默认参数在各环境实际播期运行模型 | `baseline/summary.csv` |

结果位于：

```text
outputs/experiments/first_experiment/
├── config.yaml                    # 本次实验的配置快照
├── audit/                         # 数据质量与环境资格
├── normalized/                    # 环境、管理、土壤、天气和观测表
├── manifests/                     # 输入来源与文件指纹
└── baseline/
    ├── summary.csv
    └── summary.parquet
```

打开 `baseline/summary.csv`，先查看 `environment_id`、`planting_date`、
`status` 和 `dry_yield_mg_ha`。产量单位为 Mg/ha；
`matured` 表示成熟运行，其他状态结合 `failure_reason` 阅读。
数据质量与天气覆盖会影响运行状态，详细依据保存在 `audit/` 中。

## 按任务使用

完成数据准备后，可以按研究问题选择后续阶段。下面的命令接着使用
`first_experiment.local.yaml`：

| 任务 | 命令 | 主要输出 |
| --- | --- | --- |
| 用训练年观测选择参数 | `make calibrate CONFIG=configs/first_experiment.local.yaml` | `calibration/parameters.parquet` |
| 在独立年份评估参数 | `make validate CONFIG=configs/first_experiment.local.yaml` | `validation/metrics.csv` |
| 逐日改变播期，计算适播窗口 | `make scan CONFIG=configs/first_experiment.local.yaml` | `scan/summary.csv`、`scan/windows.csv` |
| 汇总扫描、绘图与已有验证结果 | `make report CONFIG=configs/first_experiment.local.yaml` | `report/report.md` |

校准直接读取 `prepare` 的输入表，`baseline` 便于提前检查默认模拟。
`validate` 和示例中的 `scan` 都依赖校准产物，可以分别执行；
`report` 读取扫描结果，并合并已有的验证结果。
可以先阅读每一步的结果，再继续下一步。
扫描规模由环境数、参数组数和候选播期数共同决定，通常比实际播期模拟更耗时。
阶段依赖、断点恢复和完整命令见[实验指南](docs/experiments.md)。

Make 命令与 CLI 对应，例如：

```bash
.venv/bin/python -m snowwindow scan --config configs/first_experiment.local.yaml
```

熟悉各阶段后，可以用 `run` 顺序执行数据准备、baseline、calibrate、
validate、scan 和 report：

```bash
make run CONFIG=configs/first_experiment.local.yaml
```

### 运行回顾式预测

forecast 是独立阶段：它使用源实验的校准参数、扫描结果和标准化天气，
根据给定信息截止日构造历史天气情景。示例以 2023-03-01 为信息截止日，
评估实际播期前后 ±14 天或 ±30 天的候选日期。

先完成上面源实验的校准和扫描，再复制预测配置：

```bash
cp -n configs/g2f_forecast_demo.yaml configs/first_forecast.local.yaml
```

在副本的对应位置修改以下字段，保留其余设置。
其中 `source_experiment_id` 是现有 `selection` 下的一个字段：

```yaml
experiment_id: first_forecast
selection:
  source_experiment_id: first_experiment
```

预测配置的 `output_dir` 应与源实验相同；源实验按
`<output_dir>/experiments/<source_experiment_id>/` 定位。
源实验的 `config.yaml` 与 `scan/manifest.json` 记录天气策略，
与标准化表、校准参数和扫描结果一起参与来源检查。随后执行：

```bash
make forecast CONFIG=configs/first_forecast.local.yaml
```

预测结果和说明位于 `outputs/experiments/first_forecast/forecast/`。
三模型的六个预测示例及各自前提见[配置清单](configs/README.md)。

### 汇总本地实验

```bash
make catalog CONFIG=configs/first_experiment.local.yaml
```

该命令在配置的输出目录下生成 `experiments/INDEX.md` 和
`experiments/catalog.json`，列出本地各实验的产物与状态。

## 自定义实验

从最接近研究目的的 YAML 开始，每套设置使用独立的 `experiment_id`。
例如，为同一站点的跨年验证创建配置副本后，将 `selection` 改为：

```yaml
selection:
  environments: [INH1_2022, INH1_2023]
  calibration_years: [2022]
  evaluation_years: [2023]
  allow_assumed_rainfed: true
  exclude_default_soil_from_calibration: true
```

这表示选择两个环境，用 2022 年选参、2023 年评估。
模型参数放在 `model.parameters`，搜索网格放在 `calibration`，
扫描参数组和并行度放在 `simulation`。
切换模型时，可分别从 `g2f_apsim_demo.yaml` 或 `g2f_dssat_demo.yaml` 开始，
使用对应模型的参数尺度。

完整字段、默认网格和跨年天气映射见[配置指南](docs/configuration.md)；
11 个已有配置的用途、年份和输出位置见[配置清单](configs/README.md)。

### 在 Python 中使用

各阶段也提供 Python 函数。完成上面的 `prepare` 后，接着使用第一个实验的
配置，可以在脚本或 Notebook 中取得实际播期模拟的结果表：

```python
from pathlib import Path

from snowwindow.config import load_config, save_config_snapshot
from snowwindow.stages import baseline_stage

config = load_config(Path("configs/first_experiment.local.yaml"))
save_config_snapshot(config)
results = baseline_stage(config)

print(results[["environment_id", "status", "dry_yield_mg_ha"]])
```

此例从仓库根目录运行，返回 pandas DataFrame，并将结果写入同一实验目录。
后续分析可以直接读取各阶段的 CSV 或 Parquet；响应面与残差分析示例见
[ML 实验指南](docs/ml-experiments.md)。

## 数据与结果说明

- 天气统一来自 G2F `full_year`。普通模拟通过显式映射追加下一年同站点
  天气。逐日扫描按所选环境的年份生成候选，2024 年范围为 1 月 1 日至
  11 月 10 日，共 315 天；2024 相关模拟结束日和预测候选播期同样以
  **2024-11-10** 为上限。forecast 的信息截止日由预测配置另行设置。
  天气尾部不足会记录截断，内部缺测会保留失败记录。覆盖范围和具体缺口见
  [数据说明](docs/g2f-data.md)。
- 参数选择使用训练年观测，评估年用于独立验证。逐日播期曲线表示模型情景，
  田间观测对应实际处理；forecast 的 oracle 指源实验的模拟参照结果。
- AquaCrop 使用当前适配器支持的均质土层；APSIM/DSSAT 示例采用固定的
  参考土壤、水氮和品种设置。解释结果时应结合各[模型指南](#支持的模型)中的假设。
- 实验保存配置快照、来源指纹和运行状态。同配置可复用模型结果缓存并恢复扫描；
  更改设置时使用新实验 ID。历史实验的日期、结果和验证范围见
  [研究日志](docs/model-usage-log.md)与[验收记录](docs/reproducibility-validation.md)。

## 项目结构与开发

```text
src/snowwindow/
├── data/           # G2F 审计、标准化与模型输入准备
├── models/         # AquaCrop、APSIM、DSSAT 适配器
├── config.py       # YAML 解析与配置快照
├── domain.py       # 统一的输入输出数据结构
├── stages.py       # 实际播期模拟、校准与验证
├── scan.py         # 播期扫描
├── forecast.py     # 历史天气情景预测
└── reporting.py    # 图表与报告
configs/            # 实验 YAML 与配置清单
tests/              # 单元与集成测试
docs/               # 使用指南和研究记录
```

模型接入接口见 [`ModelAdapter`](src/snowwindow/adapters.py)；
`bin/` 保存引擎启动器，`patches/` 保存兼容补丁，`scripts/` 保存辅助脚本。
本地数据、原生引擎和实验输出分别存放在 `data/`、`.tools/`、`outputs/`，
由使用者准备和生成，Git 忽略这些目录。

日常开发检查：

```bash
make check
```

该命令检查依赖兼容性、代码风格和单元测试。
准备好本地数据与对应引擎后，运行 `make test-integration`。
更多测试命令见[快速上手](docs/getting-started.md#7-结果断点恢复与检查)。

## 文档

- [快速上手](docs/getting-started.md)：环境安装、引擎配置和常见问题。
- [数据下载](docs/data-download.md)与[G2F 数据映射](docs/g2f-data.md)：文件获取、字段与覆盖范围。
- [配置指南](docs/configuration.md)与[配置清单](configs/README.md)：修改字段、选择实验模板。
- [实验指南](docs/experiments.md)：分阶段运行、产物、恢复与历史结果。
- [ML 实验](docs/ml-experiments.md)：响应面、残差分析与特征解释。
- [全部文档](docs/README.md)：模型指南、开发参考和研究记录。
