# 模型分析与使用日志

最后整理日期：2026-09-30。返回[文档目录](README.md)。

本日志初次整理已有文件和会话分析。以下日期是整理/核对日期；
未记录原始执行时间的实验不据此推断其执行日期。
2026-09-23 的历史章节为当时的只读核对；2026-09-27 与 09-30 章节记录了
实际执行。模型比较的当前说明见[比较文档](model-comparison.md)。

## 2026-10-27 · 仓库复现文档补充（未重跑实验）

状态：核对当前源码接口并补充执行文档；不是新的数值实验。
下方各日期、参数、统计和用户已有结论均保留原记录。
本日志所有 `outputs/` 证据链接都是本地产物，clone 不包含。

- 当前配置、年份、前置条件与执行命令见 [11 配置清单](../configs/README.md)
  及 [执行指南](experiments.md)，`run` 不含 forecast。
- 历史章节中的“无泄漏”指当时 forecast 天气情景的信息截止政策，
  不构成全部后续 ML 特征无泄漏的结论。oracle 派生残差及多尺度窗口
  只是诊断，不能部署；固定窗口包含播后实测天气时也不属于播前可用输入。
  现有函数示例见 [ML 指南](ml-experiments.md)。
- 当前 AquaCrop 使用 normalized weather，不暗中回退 legacy POWER；
  APSIM/DSSAT 的 baseline/校准/扫描依赖外部恢复的同布局天气四件套。
  新旧布局规则见 [上手指南](getting-started.md)。历史驱动/时限可能不同，
  不保证当前数值逐项复刻；refined/history 跨年缺口未因此解决。
- 研究材料维护路径：`docs/research/G2F_播期情景模拟技术调研.md`、
  `docs/research/计划书.md`。历史消融与离线汇报仍作为附加研究保留，
  不承诺由主 CLI 逐项重建，不修改历史脚本或 manifest。

## 2026-10-10 · 三模型 ±30 天扩展播期预测

状态：已完成；用于检验候选窗口从实际播期前后 14 天扩展到 30 天后，
推荐日期和 regret 是否发生实质变化。

- 配置：
  [`g2f_forecast_demo_radius30.yaml`](../configs/g2f_forecast_demo_radius30.yaml)、
  [`g2f_apsim_forecast_demo_radius30.yaml`](../configs/g2f_apsim_forecast_demo_radius30.yaml)、
  [`g2f_dssat_forecast_demo_radius30.yaml`](../configs/g2f_dssat_forecast_demo_radius30.yaml)。
- 候选窗口：实际播期前后各 30 天，共 61 个候选日期。
- 信息边界与 ±14 天实验一致：2023-03-01 前使用 2023 实测天气，
  之后使用同站点 2014–2022 历史天气情景。
- 三模型平均结果：
  - AquaCrop：窗口覆盖率 0.710，最优日 regret 0.773 Mg/ha，
    相对实际播期增益 -0.067 Mg/ha。
  - APSIM：窗口覆盖率 0.907，最优日 regret 0.222 Mg/ha，
    相对实际播期增益 +1.454 Mg/ha。
  - DSSAT：窗口覆盖率 0.475，最优日 regret 0.877 Mg/ha，
    相对实际播期增益 +2.322 Mg/ha。
- 关键变化：MOH2 在 APSIM 和 DSSAT 下的最优推荐日大幅后移，
  相对实际播期的增益显著增加；AquaCrop 在 INH1 的最优日明显前移。
  说明候选窗口宽度本身就是重要实验设定，不能把 ±14 天结果解释为全年最优播期。
- 结论：±30 天扩展揭示了更强的模型间差异和窗口敏感性，但仍属于
  仿真闭环内的回顾式诊断，不是田间增产证明。

证据：
[AquaCrop 报告](../outputs/experiments/g2f_forecast_demo_radius30/forecast/report.md)、
[APSIM 报告](../outputs/experiments/g2f_apsim_forecast_demo_radius30/forecast/report.md)、
[DSSAT 报告](../outputs/experiments/g2f_dssat_forecast_demo_radius30/forecast/report.md)。

## 2026-09-30 · APSIM 回顾式播期预测 Demo

状态：已完成；回顾式技术可行性演示，不是业务化预测或增产证明。

- 配置：[`g2f_apsim_forecast_demo.yaml`](../configs/g2f_apsim_forecast_demo.yaml)，
  oracle 与校准参数来自 [`g2f_apsim_demo`](../configs/g2f_apsim_demo.yaml)。
- 目标年份与信息截止：2023 年，2023-03-01。
- 天气政策：目标年截止日前使用 2023 实测天气；截止日后使用同站点
  2014–2022 年逐日历史天气情景，不使用目标年未来天气。
- 环境与候选：INH1、MOH2、NYH2 的 2023 年，实际播期前后各 14 天、步长 1 天。
- 记录：609 条情景仿真，键唯一；INH1 261 条成熟，MOH2 87 条成熟，
  NYH2 113 条成熟、148 条 `not_matured`。失败/未成熟状态完整保留，
  仅从汇总均值和分位数中排除。
- 95% 推荐窗口覆盖率：INH1 42.1%、MOH2 7.1%、NYH2 100%，均值 49.7%。
- 最优推荐日 oracle 遗憾：0.203、2.655、0.326 Mg/ha，均值 1.061 Mg/ha。
- 相对 G2F 实际播期的 oracle 增益：+0.708、-0.211、-0.106 Mg/ha，
  均值 +0.130 Mg/ha；环境间不稳定。
- 阶段结论：APSIM 能完成同一无泄漏回顾式预测闭环，但 MOH2 的窗口重叠
  与遗憾明显较差。土壤、水氮、品种和气象替代均为固定探索假设，三环境
  样本不足以证明普适增益。

证据：
[报告](../outputs/experiments/g2f_apsim_forecast_demo/forecast/report.md)、
[推荐结果](../outputs/experiments/g2f_apsim_forecast_demo/forecast/recommendations.csv)、
[情景曲线](../outputs/experiments/g2f_apsim_forecast_demo/forecast/forecast_curves.csv)、
[情景记录](../outputs/experiments/g2f_apsim_forecast_demo/forecast/scenario_results.csv)、
[manifest](../outputs/experiments/g2f_apsim_forecast_demo/forecast/manifest.json)、
[图表](../outputs/experiments/g2f_apsim_forecast_demo/forecast/figures/)。

```bash
.venv/bin/python -m snowwindow forecast --config configs/g2f_apsim_forecast_demo.yaml
```

## 2026-09-30 · DSSAT 回顾式播期预测 Demo

状态：已完成；回顾式技术可行性演示，不是业务化预测或增产证明。

- 配置：[`g2f_dssat_forecast_demo.yaml`](../configs/g2f_dssat_forecast_demo.yaml)，
  oracle 与校准参数来自 [`g2f_dssat_demo`](../configs/g2f_dssat_demo.yaml)。
- 目标年份与信息截止：2023 年，2023-03-01。
- 天气政策：目标年截止日前使用 2023 实测天气；截止日后使用同站点
  2014–2022 年逐日历史天气情景，不使用目标年未来天气。
- 环境与候选：INH1、MOH2、NYH2 的 2023 年，实际播期前后各 14 天、步长 1 天。
- 记录：609 条情景仿真，键唯一且全部报告成熟。记录仍保留状态字段以便审计。
- 95% 推荐窗口覆盖率：INH1 50.0%、MOH2 15.4%、NYH2 96.6%，均值 54.0%。
- 最优推荐日 oracle 遗憾：0.240、2.535、0.422 Mg/ha，均值 1.066 Mg/ha。
- 相对 G2F 实际播期的 oracle 增益：+0.532、+0.136、-0.014 Mg/ha，
  均值 +0.218 Mg/ha；环境间不稳定。
- 阶段结论：DSSAT 能完成同一无泄漏回顾式预测闭环，但 MOH2 仍是主要误差源。
  通用土壤/品种、雨养与氮肥情景、NASA POWER 气象替代以及三环境样本限制
  均使其不能替代业务预报或直接推出增产结论。

证据：
[报告](../outputs/experiments/g2f_dssat_forecast_demo/forecast/report.md)、
[推荐结果](../outputs/experiments/g2f_dssat_forecast_demo/forecast/recommendations.csv)、
[情景曲线](../outputs/experiments/g2f_dssat_forecast_demo/forecast/forecast_curves.csv)、
[情景记录](../outputs/experiments/g2f_dssat_forecast_demo/forecast/scenario_results.csv)、
[manifest](../outputs/experiments/g2f_dssat_forecast_demo/forecast/manifest.json)、
[图表](../outputs/experiments/g2f_dssat_forecast_demo/forecast/figures/)。

```bash
.venv/bin/python -m snowwindow forecast --config configs/g2f_dssat_forecast_demo.yaml
```

## 2026-09-27 · DSSAT 原生 CERES-Maize 六环境闭环

状态：已运行 prepare、baseline、calibrate、validate、scan、report；未使用
Py_DSSATTools。固定参考情景采用官方 IB0035 品种、通用深砂壤土
IB00000007、播期 120 kg N/ha 与雨养假设；它们并非 G2F 实测输入。
本地 DSSAT 4.8.6.2 的 ECO `CDAY` 读取错误修补保存在
[`patches/dssat-4.8.6.2-ecotype-cday.patch`](../patches/dssat-4.8.6.2-ecotype-cday.patch)。

- 配置：[`g2f_dssat_demo.yaml`](../configs/g2f_dssat_demo.yaml)。
- 环境：INH1、MOH2、NYH2 的 2022 和 2023 年；2022 用于校准，
  2023 用于留年验证。
- 校准所得：P1=170、G2=790。扫描 4,380 次（6 环境 ×
  365 播期 × default/calibrated），均报告成熟；扫描仍保存原生
  输出与状态，不对其他实验的失败状态作推断。
- G2F `.WTH` 使用 NASA POWER 逐日降雨、最高/最低温和辐射，
  扫描使用同坐标缓存的跨年延续天气，不是站点逐次观测；
  品种/土壤等固定假设见[DSSAT 指南](dssat.md)。
- 2023 验证，每项指标 n=3：花粉天数代理的 MAE 从默认 10.74 天
  降至校准 3.91 天；干产量 MAE 却从默认 1.04 Mg/ha 增至
  校准 2.36 Mg/ha。校准改善物候的同时没有改善留年产量，
  不能据此认定推荐播期或产量预测已具备田间应用精度。

证据：[报告](../outputs/experiments/g2f_dssat_demo/report/report.md)、
[留年指标](../outputs/experiments/g2f_dssat_demo/validation/metrics.csv)、
[扫描结果](../outputs/experiments/g2f_dssat_demo/scan/summary.csv)、
[适播窗口](../outputs/experiments/g2f_dssat_demo/scan/windows.csv)、
[模型缓存](../outputs/experiments/g2f_dssat_demo/model_cache/dssat/)、
[校准参数与引擎指纹](../outputs/experiments/g2f_dssat_demo/calibration/parameters.json)、
[输入指纹](../outputs/experiments/g2f_dssat_demo/manifests/prepare_manifest.json)。

从仓库根目录复现（需本地引擎、原始 G2F 文件和跨年天气缓存）：

```bash
.venv/bin/python -m snowwindow run --config configs/g2f_dssat_demo.yaml
```

## 2026-09-23 · AquaCrop 六环境演示

状态：已有运行结果；科学适用范围有限。

- 模型：AquaCrop-OSPy 3.1.0。
- 配置：[g2f_demo.yaml](../configs/g2f_demo.yaml)。
- 环境：INH1、MOH2、NYH2，各含 2022 和 2023。
- 校准：2022；独立留年评估：2023。
- 扫描：已有 4,380 行，即 6 环境 × 365 播期 × 2 参数组；
  含 default、calibrated，保留失败状态。
- 气象：扫描使用缓存的同坐标 NASA POWER 全年/续年数据，
  不等同于竞赛原始天气。

现有报告中的 2023 留年评估：

| 变量 | 参数组 | n | MAE | RMSE | bias |
| --- | --- | --- | --- | --- | --- |
| 干产量，Mg/ha | default | 3 | 2.7946 | 3.7061 | 2.7946 |
| 干产量，Mg/ha | calibrated | 3 | 1.9624 | 1.9699 | -0.8159 |
| 散粉天数代理比较，d | default | 3 | 3.3254 | 3.5261 | 1.7382 |
| 散粉天数代理比较，d | calibrated | 3 | 2.5806 | 3.0663 | -0.5951 |

这里 `n=3` 是每项指标的三个管理单元聚合观测数量，不是小区数；
在本次留年样本中对应 INH1、MOH2、NYH2 的 2023 年记录。
散粉比较使用 `HIstart` 代理。数值改善仅支持这三个留年样本上的比较，
不能证明跨区域或全年非实际播期预测已经可靠。

证据：
[报告](../outputs/experiments/g2f_demo/report/report.md)、
[指标](../outputs/experiments/g2f_demo/validation/metrics.csv)、
[扫描摘要](../outputs/experiments/g2f_demo/scan/summary.csv)、
[窗口](../outputs/experiments/g2f_demo/scan/windows.csv)、
[校准参数](../outputs/experiments/g2f_demo/calibration/parameters.json)。
输入与缓存来源应同时检查该实验下的 manifests、baseline 和 scan 记录。

下面是当前代码的重新运行入口。上述历史产物未在本日志中绑定完整的
原运行源码快照，当前工作树已有后续改动，因此不能保证重现完全相同的指标。
运行前确认原始数据与缓存可用；保留历史结果时另设实验 ID：

```bash
.venv/bin/python -m snowwindow run --config configs/g2f_demo.yaml
```

## 2026-09-23 · AquaCrop refined 扩展状态

状态：存在代码、配置与 audit/prepare 产物；尚未见完整校准至报告产物。

[当前配置](../configs/g2f_aquacrop_refined.yaml)的训练候选年份为
2014–2022，评估为 2023；允许未知灌溉状态按假定雨养处理，
默认土排除出校准，站点参数调整至少要求三个训练年份。
年份范围是候选范围，实际可用样本还要通过数据完整性筛选。

代码包含的扩展有颗粒比例土壤分类、株数/面积密度推导、确认灌溉环境的
土壤水分目标策略，以及站点物候和 HI 调整。这些不等于对应新实验
已经完成并证明有效；旧 demo 结果也不自动验证这些后续改动。

现有审计记录 155 个可校准管理单元，跨年扫描可用数为 0。
配置中的 `continuation_weather_by_environment` 为空；
缺少显式续年气象映射是后续扫描需要解决的问题。
这不与旧 demo 的缓存扫描相矛盾：它们使用的数据路径和实验条件不同。

证据：
[audit](../outputs/experiments/g2f_aquacrop_refined/audit/data_audit.json)、
[prepare manifest](../outputs/experiments/g2f_aquacrop_refined/manifests/prepare_manifest.json)、
[校准代码](../src/snowwindow/calibration.py)。
已有 prepare manifest 记录运行时 Python 3.9.18；仓库推荐环境为 3.10。
保留这一历史事实，未来复现实验需记录实际运行时。

## 2026-09-23 · APSIM 本地安装与官方示例

状态：本地命令行和官方玉米示例已验证；后续已完成 G2F 最小闭环接入。

| 项目 | 记录 |
| --- | --- |
| 系统 | Linux x86_64；已验证环境为 Rocky Linux 9.3 |
| 安装包 | 本地 `apsim-8116.deb` |
| APSIM | 2026.9.8116.0，`.tools/apsim/2026.9.8116.0/` |
| .NET | 8.0.31，`.tools/dotnet/8.0.31/` |
| 入口 | [bin/apsim](../bin/apsim)，按自身路径定位引擎和私有动态库 |
| 实验目录 | `outputs/experiments/apsim_smoke/` |
| 数据 | 官方 Maize 示例及 `AU_Dalby.met`，不是 G2F 数据 |
| 配置时段 | 1990-01-01 至 2000-12-31 |
| 输出 | `Maize.db`、`Maize.Report.csv`、`run.log` |

```bash
./bin/apsim --version
bash outputs/experiments/apsim_smoke/run-native.sh
```

原示例天气引用与安装包中的文件名不一致，实验副本改为相对引用
`AU_Dalby.met`，修改及来源记录在
[example_provenance.json](../outputs/experiments/apsim_smoke/example_provenance.json)。

已有[验证记录](../outputs/experiments/apsim_smoke/verification.json)：
退出码 0；数据库完整性检查为 `ok`；10 行收获事件记录，
日期从 1991-05-28 至 2000-04-05，阶段为 `HarvestRipe`。
保留了 11 条 “Initial area is more than max area for cohort 1.” 警告。
干净环境启动、从其他工作目录查看版本、迁移前后 CSV 一致性均已验证。
这不构成零警告运行或 G2F 科学验证。

示例使用条件播种：11 月 1 日至 1 月 10 日的窗口，
还检查可提取土壤水 100 mm 和前 7 天降雨 25 mm；品种为 Dekalb_XL82，
播深 30 mm、行距 750 mm、密度 6 株/m²，播种施 NO3N 160 kg/ha。
这些是示例参数，不能作为 G2F 默认事实。

固定播期管理、气象转换、单位转换、状态映射和参数校准接口已在后续
最小闭环中实现；分层土壤、水氮和真实品种参数仍需独立数据支持。
安装指纹见
[native_install_manifest.json](../outputs/experiments/apsim_smoke/native_install_manifest.json)。

## 2026-09-23 · APSIM G2F 六环境最小闭环

状态：已完成。

- 配置：[g2f_apsim_demo.yaml](../configs/g2f_apsim_demo.yaml)。
- 训练：INH1、MOH2、NYH2 的 2022 年代表管理单元，共 3 个。
- 评估：相同站点 2023 年代表管理单元，共 3 个；评估标签未参与参数选择。
- 校准参数：`juvenile_tt=100.0` °C·d，
  `grain_number_scale=1.5`。
- 扫描：六环境 × 默认/校准参数 × 365 天，共 4380 条唯一记录。
- 状态：默认参数 2170 条成熟、20 条未成熟；校准参数 2190 条成熟。
- 2023 干产量：默认 MAE 1.3479 Mg/ha，校准 MAE 1.1759 Mg/ha。
- 2023 花粉日期代理：默认 MAE 21.4049 天，校准 MAE 7.0715 天。

运行入口：

```bash
.venv/bin/python -m snowwindow run --config configs/g2f_apsim_demo.yaml
```

证据：
[报告](../outputs/experiments/g2f_apsim_demo/report/report.md)、
[指标](../outputs/experiments/g2f_apsim_demo/validation/metrics.csv)、
[扫描摘要](../outputs/experiments/g2f_apsim_demo/scan/summary.csv)、
[窗口](../outputs/experiments/g2f_apsim_demo/scan/windows.csv)、
[校准参数](../outputs/experiments/g2f_apsim_demo/calibration/parameters.json)。

该实验采用 APSIM 官方 Maize 示例的固定土壤、水氮和播种施氮情景，
品种使用 Dekalb_XL82；这些不是 G2F 站点或杂交种的实测参数。
因此当前结果证明流程、数据映射和批量扫描可运行，不构成参数已完成
科学校准的结论。

## 2026-09-23 · 理论比较结论与待核实事项

理论比较已整理至[模型文档](model-comparison.md)；
数据可用性见[G2F 映射](g2f-data.md)。以下是 2026-09-23 的
两模型分析判断；后续 DSSAT 完整流水线见本页顶部，
三模型在相同实测约束下的对照仍未完成。

1. AquaCrop 适合作为现有播期—水分—产量分析基准。
2. APSIM 是扩展水氮、器官生长与管理交互的候选，需要更多参数约束。
3. 优先完成同站点、同年份、同一实际播期的并列验证，再扩展全年扫描。
4. 基因型和 EC 数据的接入应单独设计，不能仅凭文件存在就直接用作生理参数或实测验证值。

| 待核实问题 | 需要的证据 / 完成条件 |
| --- | --- |
| 各年产量的 15.5% 标准含水率假设 | 发布说明或数据字典；核对转换是否重复 |
| EC 各列来源及信息泄漏 | 生成方法、模型/版本、输入、阶段定义和预测时可用性 |
| 2024 天气缺测及跨年续接 | 同站点连续驱动、缺测处理记录和来源指纹 |
| APSIM 初始水氮和土壤剖面 | 测量、可靠数据库或明确估计方法及敏感性分析 |
| 非常规播期仍成熟、跨年播期结果 | 核查出苗、低温/死亡、成熟、天气和管理；见下方具体记录，根因尚未确定 |
| 散粉/吐丝与模型阶段对应 | 独立物候观测及模型事件定义 |
| refined 扩展是否改善预测 | 固定训练样本，独立 2023 验证，保留失败与覆盖率 |
| G2F 与 APSIM 品种映射 | 生理参数拟合依据及独立验证，而非仅匹配名称 |

异常播期的具体核查入口：`g2f_demo/scan/summary.csv` 中
`INH1_2023 + calibrated` 的 2023-01-01 播种记录被标为 `matured`，
成熟日 2023-08-25、干产量约 9.1667 Mg/ha；
2023-09-18 播种记录的成熟日为 2024-07-18、干产量约 9.6917 Mg/ha。
这些是已有模拟输出，尚无对应非实际播期观测证明其合理性，
也尚未确定由哪项模型机制或输入假设导致。

## 记录模板

后续复制以下模板新增条目。建议以新实验 ID 保存新条件的结果，
然后更新[文档目录](README.md)中的当前状态及相应数据/模型说明。

```markdown
## YYYY-MM-DD · 模型 / 实验 / 分析主题

- 状态：已核对 / 已运行 / 已实现待验证 / 分析建议 / 待核实。
- 目的与可检验问题：
- 执行日期：如仅整理历史产物，分别记录整理日期和原始执行日期。
- 模型、版本、运行时：
- 代码版本：commit；若工作树有修改，记录补丁或源码指纹。
- 实验 ID、配置路径与配置指纹：
- 数据文件、版本、SHA256 / manifest 路径：
- 环境、年份、Hybrid / 聚合层级、有效样本数：
- 校准 / 评估划分：
- 气象与续年来源、土壤、品种、管理、初始状态：
- 估计值/默认值、单位转换与观测口径：
- 命令：
- 输出、日志、警告、失败记录路径：
- 验证：产量、物候、过程指标、覆盖率及样本数。
- 结论与适用范围：
- 对比/替代的旧记录：
- 未解决问题与下一步：
- 来源：文献 DOI / 官方文档版本 / 本地证据路径。
```
