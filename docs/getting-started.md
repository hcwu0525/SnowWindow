# 快速上手

最后核对日期：2026-09-29。返回 [README](../README.md)。
安装与复现流程、G2F 统一天气策略补充：2026-10-27；原历史结果不因此更新。

## 1. Python 环境

SnowWindow 需要 Python 3.10–3.12，推荐 Python 3.10：

```bash
uv venv --python 3.10 --seed .venv
.venv/bin/python -m pip install -r requirements-aquacrop.lock.txt -e '.[dev]'
.venv/bin/python -m pip check
.venv/bin/python -c "import ctypes, snowwindow"
```

如果没有 `uv`，可用 `python3.10 -m venv .venv` 创建环境后执行同样的
`pip` 命令。锁定的关键版本为 AquaCrop 3.1.0、NumPy 1.26.4、
Ruff 0.16.8；开发测试依赖范围为 `pytest>=8,<10`。推荐环境不代表已经
逐一验证所有 Python 3.10–3.12 组合。

也可使用 `make venv`、`make install` 或一步 `make setup`。默认
`VENV_PYTHON=python3.10`、`PYTHON=.venv/bin/python`、
`CONFIG=configs/g2f_demo.yaml`；可在 Make 命令中显式覆盖。
`make venv` 优先使用 uv 的 `--seed` 创建环境；两条分支均使用
`VENV_PYTHON`（默认 `python3.10`）。没有 uv 时回退到该解释器执行
`-m venv .venv`。
`make setup` 再执行与上面相同的依赖安装与 `pip check`。

基础解释器应包含完整标准库。若导入出现 `No module named '_ctypes'`，
这是 Python 构建缺少扩展，不是再装一个 pip 包就能修复。用
`python3.10 -c "import ctypes"` 先核对解释器；另选完整安装后，在新环境中
使用 `make setup VENV_PYTHON=/path/to/python3.10`。若允许下载 Python，
也可在尚未创建 `.venv` 的新目录运行 `UV_MANAGED_PYTHON=1 make setup`；
该方式需要能访问 Python 分发站点，不保证受限网络可用。

## 2. 数据布局

使用 G2F 2024 Maize Genotype by Environment Prediction Competition 发布数据，
DOI 为 `10.25739/78mn-4394`。首次获取请按[数据下载指南](data-download.md)
打开官方入口、下载并核对文件；也可从来源明确且有权使用的副本恢复。
项目不自动下载，不读取现成的 merged 或 6D_features 表。
`data_dir` 相对 YAML 所在目录解析，随仓库配置使用时为根目录 `data/`。
按 [SOURCE_CATALOG](../src/snowwindow/data/sources.py)，以下 13 个文件
全部必须存在；`excluded_from_model_inputs` 仍参与完整性检查与来源指纹，
只是不会读入模型输入表：

```text
data/
  Training_data/
    1_Training_Trait_Data_2014_2023.csv
    2_Training_Meta_Data_2014_2023.csv
    3_Training_Soil_Data_2015_2023.csv
    4_Training_Weather_Data_2014_2023_full_year.csv
    4_Training_Weather_Data_2014_2023_seasons_only.csv
    6_Training_EC_Data_2014_2023.csv
  Testing_data/
    1_Submission_Template_2024.csv
    2_Testing_Meta_Data_2024.csv
    3_Testing_Soil_Data_2024.csv
    4_Testing_Weather_Data_2024_full_year.csv
    4_Testing_Weather_Data_2024_seasons_only.csv
    6_Testing_EC_Data_2024.csv
    7_Testing_Observed_Values.csv
```

其中两个 `seasons_only` 和两个 EC 文件的角色是
`excluded_from_model_inputs`，其余九个是 `model_input`。基因组 VCF、
数值基因型、亲本表、根目录 `merged_data` 和 `6D_features` 不在必需清单。
源数据始终只读，禁止把清洗结果写回此目录。
字段含义、发布覆盖不完整和各文件角色见 [G2F 数据映射](g2f-data.md)。

## 3. AquaCrop 快速示例

AquaCrop 随锁定依赖安装，不需要另装原生引擎。先检查数据：

```bash
.venv/bin/python -m snowwindow audit --config configs/g2f_demo.yaml
.venv/bin/python -m snowwindow prepare --config configs/g2f_demo.yaml
```

`audit` 在内存中规范化并返回审计，CLI 只向终端打印计数：
不写审计/标准化文件，也不创建配置快照。`prepare` 才写标准化表、
`audit/data_audit.json`、`audit/eligibility.parquet`、来源 manifest
和可重新加载的 `config.yaml`。所有生成物位于
`outputs/experiments/g2f_demo/`。已有同 ID 快照而配置不同时会拒绝覆盖；
保护历史结果时请复制 YAML 并设置新 `experiment_id` 后再执行。

需要全年/跨年模拟时，先阅读审计中的天气完整性和资格排除原因，再运行：

```bash
.venv/bin/python -m snowwindow run --config configs/g2f_demo.yaml
```

`run` 依次执行 prepare（若缺 manifest）、baseline、calibrate、validate、
scan、report，不含 forecast。报告位于
`outputs/experiments/g2f_demo/report/report.md`。
AquaCrop 与另两模型统一使用本实验 `normalized/weather.parquet` 中的
G2F `full_year` 天气，不读取 legacy POWER CSV 或其 provenance。
若 G2F 天气不足，运行可能失败或未成熟；refined/history 的跨年缺口并未
因此解决。新策略与旧快照/历史产物不能混用，即使 YAML 名称没变也须新建 ID。

## 4. 三模型共用 G2F 天气与时限

2026-10-27 起，baseline、校准、验证、scan 与 forecast 均只使用 G2F
`full_year` 原始分表标准化天气。新用户无需下载、恢复或生成任何外部天气
缓存；旧 `weather/*.csv` 与 `weather_raw/*.provenance.json` 不再参与装配。
天气字段及缺口见 [G2F 数据映射](g2f-data.md)。

- 普通模拟先读取 `normalized/weather.parquet` 中当前环境的记录；
  只有 `simulation.scan_horizon: cross_year` 且
  `continuation_weather_by_environment` 显式映射下一年同站点环境时，
  才追加该环境的 G2F 天气。`same_year` 不追加，无映射不自动寻找替代。
- 三个主 demo 配置提供五条映射：INH1/MOH2/NYH2 的 2022→2023，
  以及 INH1/NYH2 的 2023→2024。本地没有 `MOH2_2024`，不配置或伪造；
  refined/history 保留空映射，仍有跨年研究缺口。映射不等于日期与核心值完整。
- 模拟受实际可用天气截止日限制，尾部不足应记录截断；内部缺日期或核心值
  仍保留失败，不通过缩短到内部缺口前来掩盖问题。2024 天气仅到
  2024-11-10，全年 scan 为 1/1–11/10 的 315 个候选日，保留 2/29。
  2024 相关模拟与 forecast 候选播期同样不得晚于 11/10；
  2024-07-12 至 2024-07-14 的核心缺测不得补零、外部替代或改标成熟。
- forecast 仍从源实验 normalized 表构造 G2F 历史同站点情景，不用目标年
  信息截止日之后的实测天气选参。六个示例评估年仍为 2023，信息截止
  2023-03-01；2024-11-10 是数据/模拟硬截止日，不能充当预测信息截止日。

G2F 数据与模型引擎仍是独立前提；APSIM/.NET 与 DSSAT 的安装方式见下文。
`model_cache/<model>/` 是模型输入/结果缓存，扫描进度用于断点恢复，均继续
保留，不是外部天气缓存。原生引擎运行目录中的气象输入由 G2F 请求生成。

历史说明（2026-10-27）：旧六环境报告中基于 POWER 缓存的数值、日期和失败
记录按原样保留；它们不证明新策略已跑通。新建源实验 ID 后，forecast
也须新建 ID 并同步 `selection.source_experiment_id`，不能复用旧 oracle。
新快照自动记录 `weather_policy`，详见 [配置指南](configuration.md#配置快照与重跑)。

## 5. 可选 APSIM 引擎

APSIM NG 使用本地原生命令行和 `bin/apsim` 启动器；
自行取得适用授权并安装对应 APSIM/.NET 分发。安装后先验证：

```bash
./bin/apsim --version
```

本仓库不自动下载或安装 APSIM/.NET，更不代办商业或受限授权。
所需目录、指纹和独立输出的冒烟示例见
[APSIM 指南](models/apsim.md)。

## 6. 可选 DSSAT 引擎

DSSAT 使用 CERES-Maize 原生可执行文件，默认查找
`.tools/dssat/4.8.6.2/`。官方玉米数据分布需单独授权或下载。
安装前先阅读 [DSSAT 指南](models/dssat.md) 和
[DSSAT 详细运行说明](dssat.md)。

## 7. 结果、断点恢复与检查

所有生成物位于：

```text
outputs/experiments/<experiment_id>/
```

运行下面命令重建总索引：

```bash
.venv/bin/python -m snowwindow catalog --config configs/g2f_demo.yaml
```

catalog 扫描配置 `output_dir`，只重建总索引，不运行模型、不创建实验快照。
历史输出保留在 `outputs/experiments/legacy/`，新 clone 不包含这些本地产物。
分阶段依赖、三模型/六个预测命令和恢复说明见 [实验结果](experiments.md)。
全部配置的定位见 [配置清单](../configs/README.md)。

```bash
make check
make test
# 仅在本地数据/引擎具备时
make test-integration
```

Make 通过 `PYTEST_ADDOPTS` 选择标记；不要将 `-m` 直接传给 pytest 命令行，
因为 AquaCrop 的导入解析会与之冲突。直接运行的等价命令：

```bash
PYTEST_ADDOPTS='-m "not integration"' .venv/bin/python -m pytest -q
PYTEST_ADDOPTS='-m integration' .venv/bin/python -m pytest -q
```

常见故障：

| 现象 | 检查与处理 |
| --- | --- |
| `required G2F source files are missing` | 按[下载指南](data-download.md)核对 13 文件、目录嵌套和大小写，包括被排除的 EC/季节天气 |
| 下载后是 HTML、403 或超时 | 回到官方发布页核对资源，按站点要求访问；不要把错误页当 CSV |
| `prepared experiment artifacts are missing` | 对同一配置先执行 prepare；不能混用其他实验标准化表 |
| `calibration artifacts/parameters are missing` | 先 calibrate；forecast 还需要源实验 scan |
| 旧记录出现 `complete cached POWER forcing is missing` | 属于旧缓存链路；当前策略不再恢复该缓存，使用新 ID 按 G2F 链路准备 |
| `crossyear_weather_missing` / 天气日期不连续 | 核对 G2F 原始覆盖、同站下一年显式映射与审计；空映射或 2024 缺测不算已解决，不填零/换站 |
| 引擎/模板缺失、版本错误 | 按模型指南独立安装并核对版本、路径和指纹 |
| 配置快照冲突 | 使用新 experiment_id；不删除旧快照来强行覆盖 |
| 历史产物已有但无配置快照 | 拒绝自动接管；使用新 ID，保留原目录及原始证据 |
| `No module named '_ctypes'` | 基础 Python 不完整；先核对 `import ctypes`，使用完整解释器创建新环境 |
| 未成熟、失败或无正成熟产量 | 保留原状态与原因；检查驱动/时限，不能改标成熟 |
