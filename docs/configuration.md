# 配置指南

返回 [README](../README.md)。

配置核对入口：[解析器](../src/snowwindow/config.py)、
[资格审计](../src/snowwindow/data/audit.py)、
[扫描](../src/snowwindow/scan.py)、[预测](../src/snowwindow/forecast.py)。
现有 11 个 YAML 的用途与命令见 [配置清单](../configs/README.md)；
本文说明已有字段，不新增 YAML schema 或 CLI 选项。

## 路径与最小结构

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

`data_dir`、`output_dir` 相对 **YAML 所在目录**解析（不是当前工作目录），
支持绝对路径与用户目录展开。上述 `../data`、`../outputs` 以
`configs/` 为基准。实验目录固定为
`<output_dir>/experiments/<experiment_id>/`；新实验请使用独立、安全的目录名。

## 模型与参数

`model.name` 通过 `AdapterRegistry` 解析：

- `aquacrop`：AquaCrop-OSPy 3.1.0。
- `apsim`：APSIM NG 2026.9.8116.0。
- `dssat`：DSSAT-CSM 4.8.6.2 / CERES-Maize。

模型特定翻译必须留在 `src/snowwindow/models/<model>/`，编排层只消费
`ModelCapabilities`。

`model.parameters` 必须存在且是映射，可以是 `{}`；不是任意模型参数都
已接入。当前配置中重要的参数包括：

| 模型 | 已有字段及用途 |
| --- | --- |
| 共用 | `model_version` 核对适配版本；`simulation_horizon_days` 为播后模拟天数（APSIM/DSSAT 示例为 365），仍受可用天气截止日限制 |
| AquaCrop | `crop: MaizeGDD`、`grain_standard_moisture_fraction: 0.155`（观测产量干重口径）、`default_soil_texture: Loam`、可选 `irrigation_smt`；模型物候/产量参数为 `phenology_scale`、`HI0` |
| APSIM | 固定参考 `cultivar: Dekalb_XL82`、`juvenile_tt`、`grain_number_scale` |
| DSSAT | 固定参考 `cultivar: IB0035`、`P1`、`G2` |

更改 `cultivar` 字符串不会自动建立新的品种映射。引擎安装路径由现有适配器
和启动器约定，当前 YAML 没有通用 `engine_path` 或自动下载选项。

## 校准与评估

- `selection.calibration_years`：允许用于参数选择的年份。
- `selection.evaluation_years`：独立评估年份，不能与校准年份相交。
- `selection.environments`：显式环境列表。
- `selection.all_eligible_environments`：全部合格环境的配置意图声明（见下文实际筛选边界）。
- `selection.allow_assumed_rainfed`：允许显式标记的假定雨养样本。
- `selection.exclude_default_soil_from_calibration`：现有配置保留的土壤排除声明，
  默认 `true`。当前资格审计仍把 `default_soil` 列为科学排除原因，
  不应将 `false` 理解为保证默认土样本进入校准。
- `selection.allow_default_soil_for_scan`：审计是否允许默认土用于扫描，
  默认 `true`，不代表该土壤已实测验证。
- `selection.site_offset_minimum_years`：AquaCrop 站点偏移所需最少年份，
  默认 3；只使用训练观测。APSIM/DSSAT 不支持站点校准。

`environments: []` 在现有阶段实现中表示不过滤环境；
`all_eligible_environments` 是配置意图声明，不是独立的自动选优算法。
实际选样应查看 `audit/eligibility.parquet` 与校准排除表，不要仅凭字段名
推断所有阶段均已按相同资格集合过滤。

推荐使用统一字段名。以下数值仅适用于 AquaCrop；APSIM/DSSAT 必须使用
后表对应的参数尺度，不能照抄这些数值覆盖模型专属网格：

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

每个 grid/fine_step 分别按如下顺序取首个存在的键：

1. `calibration` 中的统一键。
2. `calibration` 中的当前模型旧键。
3. `selection` 中的统一键（兼容旧配置）。
4. `selection` 中的当前模型旧键。
5. 解析器按模型设定的默认值。

也就是说，`calibration` 的旧键优先于 `selection` 的统一键，
不能简化为跨层级“统一键总是优先”。grid 为 `[start, stop, step]`，
要求 `stop > start`、`step > 0`；fine_step 必须为正数。
默认网格和细步长依次为：

| 模型 | 物候粗网格 / 细步长 | 产量粗网格 / 细步长 |
| --- | --- | --- |
| AquaCrop | `[0.8, 1.2, 0.02]` / `0.005` | `[0.35, 0.55, 0.01]` / `0.0025` |
| APSIM | `[100, 350, 25]` / `5` | `[0.5, 1.5, 0.1]` / `0.02` |
| DSSAT | `[150, 350, 50]` / `10` | `[700, 950, 50]` / `10` |

观测集合在搜索前固定；评估年份与校准年份必须不相交，不能使用评估观测
挑选参数。验证阶段按模型能力构造 default/calibrated，以及可支持的
site_calibrated 组；`simulation.parameter_sets` 主要控制扫描请求。

## 播期扫描

- `simulation.scan_fractions`：窗口产量阈值，必须在 `(0, 1]`。
- `simulation.scan_all_dates`：现有配置的全年扫描意图，默认 `false`。
  当前 `scan` 命令本身构造逐日日期，不提供由此切换的抽样扫描；
  2024 候选域限于 1/1–11/10（315 天，保留 2/29），不生成更晚候选。
- `simulation.workers`：正整数；只控制扫描 `run_many` 批组线程池，
  不保证所有步骤并行（按请求记录进度的预跑可能仍串行）。
  不支持批量的适配器仍串行；forecast 不因该值自动并行。
- `simulation.parameter_sets`：扫描参数映射。`default: {}` 直接用
  `model.parameters`；`calibrated: {source: calibration}` 加载 held_year
  参数；`site_calibrated: {source: site_calibration}` 加载全局参数与训练站点
  偏移，无该站点偏移时仍用全局参数。仅 AquaCrop 支持站点偏移。
  其他组按显式键值覆盖基础参数，不能把任意 `source` 当作插件机制。
- `simulation.scan_horizon`：支持 `same_year` 与 `cross_year`（默认）。
  `same_year` 只读当前环境，`cross_year` 仅在有下述显式映射时追加下一年。
- `simulation.continuation_weather_by_environment`：显式映射当前环境到下一年
  同站点 G2F 天气环境，例如 `{INH1_2022: INH1_2023}`；与
  `cross_year` 同时满足时，从 normalized 表追加对应记录。
  审计仍检查下一年年份、日历和核心变量，缺口可记为
  `crossyear_weather_missing`；有映射不代表跨年资格通过。

统一天气策略（2026-10-27）：三模型从本实验 `normalized/weather.parquet`
读取 G2F `full_year` 原始分表标准化记录；不读取 legacy POWER CSV 或其
provenance，不需要任何外部天气缓存，也没有新增 `weather_source` 选项。
无映射不自动找下一年、其他站点或其他来源；模拟受实际可用截止日限制并
记录尾部截断，内部缺日期/核心值继续保留失败。
2024 相关模拟结束日及 scan/forecast 候选播期不得晚于 2024-11-10；
2024-07-12 至 2024-07-14 的核心缺测不得补零、外部替代或改标成熟。

三个主 demo 显式映射 INH1/MOH2/NYH2 的 2022→2023，以及 INH1/NYH2 的
2023→2024；本地没有 `MOH2_2024`，不得映射或伪造。refined/history
保留空映射与跨年研究缺口。模型结果缓存及断点恢复继续保留，不属于天气缓存。

全年扫描是反事实模拟。只有实际 G2F 播期可以作为观测验证点。

## 回顾式 forecast

`selection.source_experiment_id` 指向同一 `output_dir` 下的源实验 ID，
默认本实验 ID。预测读取源实验的：

```text
normalized/{environments,management_units,soil_profiles,weather}.parquet
calibration/parameters.parquet
scan/summary.parquet
```

源实验须先完成 prepare、calibrate、scan，且有 held_year 参数与
`calibrated` oracle 扫描。forecast 不自动运行这些前置阶段。
目标年取 `selection.evaluation_years[0]`，不能用多个评估年暗示一次预测多年度。

| `simulation` 字段 | 默认值与含义 |
| --- | --- |
| `forecast_cutoff_year` | 第一个评估年；应与目标年一致 |
| `forecast_cutoff_month` / `forecast_cutoff_day` | `3` / `1`，共同构成合法截止日期 |
| `forecast_radius_days` | `14`，实际播期前后半径，非负 |
| `forecast_step_days` | `1`，正步长；实际播期始终加入候选 |
| `forecast_fraction` | `0.95`，推荐窗口阈值，范围 `(0, 1]` |

六个示例均截止 2023-03-01，半径为 ±14 或 ±30 天、步长 1、阈值 0.95。
截止日当日及以前使用目标年已实现天气，之后用同站点更早年份同月日天气，
不是数值天气预报。历史情景不只限于 calibration_years；有完整天气的更早年
可进入情景。2024 的候选播期和模拟硬截止为 2024-11-10，并保留闰日；
该日期不是 `forecast_cutoff_*` 所指定的信息截止日，不允许借此引入目标年
未来实测选参。六个示例仍评估 2023，不更改训练网格或科学参数。
oracle 为源实验模拟，不是田间标签。`run` 不包含 forecast，
必须单独执行原有 `forecast --config ...`。

## 配置快照与重跑

已存在产物而没有可信 `config.yaml` 的历史实验目录同样拒绝接管；
必须使用新实验 ID，不能补写新快照去追认旧数据的配置。快照先完整写入
同目录临时文件，再以不覆盖已有文件的原子方式发布，避免并发读取半份 YAML。

除 `audit`、`catalog` 外的 CLI 实验阶段，在写实验产物前保存解析后
`config.yaml`，包含解析后的绝对 data/output 路径、默认值与扩展选项，
可直接再次 `load_config`，不是只供阅读的 dataclass 转储。
首次创建后，同实验 ID 的不同解析配置拒绝覆盖，必须新建 ID；
同配置可继续运行。`audit_g2f` 只在内存中返回审计，CLI 打印计数，
不写审计文件、标准化产物或快照；这些审计文件由 `prepare` 保存。
`catalog` 使用配置的 `output_dir` 生成总索引，不创建实验快照。

新快照自动记录以下天气策略标识，无需在用户 YAML 增加字段：

```yaml
weather_policy:
  source: g2f_full_year
  end_date: 2024-11-10
  continuation: explicit_g2f_environment_mapping
```

旧快照未包含该标识、或历史产物由旧缓存链路产生时，不能与新策略混用；
必须新建 `experiment_id`，forecast 的 `source_experiment_id` 也须指向
同策略的新源实验。不能手工给旧快照补标识来追认旧结果。旧报告中的数值、
日期与来源记录保留，它们不构成当前 G2F 统一策略验证通过的证据。

快照不代替数据、软件和引擎指纹。换输入、引擎、代码版本或科学假设应建立
新实验并保存 provenance；不要删除历史快照或篡改失败缓存来绕过保护。
