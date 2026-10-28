# AquaCrop、APSIM 与 DSSAT：机制、输入输出及 G2F 适用性

项目实现与实验状态核对日期：2026-09-27。返回[文档目录](README.md)。

本文保留原核对日期与历史结论；`outputs/` 链接都是 clone 不包含的本地证据。
2026-10-27 补充的当前安装、G2F 统一天气策略和复现边界见
[快速上手](getting-started.md) 与 [配置清单](../configs/README.md)。
三模型现统一只用 G2F `full_year` 原始分表标准化天气，不读取 legacy
POWER CSV/provenance，不需要外部天气缓存；APSIM/DSSAT 引擎仍独立安装。
仅 `scan_horizon: cross_year` 加显式下一年同站点 G2F 环境映射才追加记录；
无映射不自动替代，实际天气截止导致尾部截断须记录，内部缺测仍失败。
2024 相关模拟与 scan/forecast 候选播期不晚于 2024-11-10（315 天，
保留 2/29）；7/12–7/14 核心缺测不得补零、外部替代或改标成熟。
这不是 forecast 信息截止日，预测仍按既有信息边界使用历史同站点情景。
模型结果缓存与断点恢复保留；历史成功不追认为新策略通过，
必须新 ID、新快照，不能混用旧产物。以下历史数值与核对日期不变。

本文将 FAO AquaCrop 理论框架、AquaCrop-OSPy 3.1.0 实现、
APSIM Next Generation 玉米模型、DSSAT CERES-Maize，以及
SnowWindow 当前适配范围分开描述。
APSIM Classic 或其他作物的机制不能直接视为当前 NG 玉米实现。

## 1. 模型如何形成产量

### AquaCrop

主线为：温度与土壤水分 → 绿色冠层覆盖度 CC → 实际蒸腾 Tr
→ 地上干生物量 B → 经收获指数 HI 转换的产量 Y。[S1]

省略温度、CO₂ 等修正的概念式：

```text
B ≈ WP* × Σ(Tr_day / ET0_day)
Y = B × HI
```

`WP*` 是标准化水分生产力；`ET0` 是参考蒸散。作物蒸腾和土壤蒸发
分开计算，生物量主要与前者关联。缺水可影响冠层扩展、气孔关闭、
提前衰老和收获指数，因此缺水时段会改变减产程度。
HI 是生育过程中受胁迫调整的量，不应理解成所有情况下固定不变。[S1]

### APSIM NG 玉米

主线为：温度与物候 → 叶片/冠层发育 → 辐射截获与干物质生产
→ 叶、茎、根、籽粒等器官间分配 → 籽粒生长与灌浆。[S2][S3]

辐射利用效率方法的概念式：

```text
potential_daily_biomass ≈ intercepted_radiation × RUE
```

实际生长取决于水、氮、温度及器官供需约束；土壤、残茬和作物模块
交换状态。该式不代表所有 APSIM 作物模块只有同一套计算机制，
也不表示所有胁迫都通过一个系数处理。[S2][S3]

### DSSAT CERES-Maize

本项目运行的是 DSSAT-CSM 4.8.6.2 中的 `MZCER048`，它以逐日
气象、品种系数、土壤剖面和管理事件为输入，计算玉米发育、干物质
与籽粒产量。品种文件的 P1 为出苗至幼年期结束的积温参数，
G2 为每株潜在籽粒数；改动二者不能代替实测土壤水氮、品种
和完整管理资料。具体定义见安装副本
`Genotype/MZCER048.CUL` 与[本项目适配器](../src/snowwindow/models/dssat/adapter.py)。

| 维度 | AquaCrop 理论框架 | APSIM NG 玉米 | DSSAT CERES-Maize |
| --- | --- | --- | --- |
| 研究重点 | 作物产量对水分的响应 | 作物、土壤与管理相互作用 | 品种、天气、土壤、管理共同驱动的逐日作物生长 |
| 冠层 | 主要使用覆盖度 CC | 叶片发育、LAI、截光 | 玉米冠层发育与截光；不是 AquaCrop 的 CC |
| 生物量 | 标准化蒸腾与水分生产力 | 辐射利用、资源约束与器官分配 | 玉米生长与干物质形成，受温度、水氮状态等约束 |
| 产量 | 地上生物量 × 调整后的 HI | 籽粒器官干物质积累 | `HWAM` 干籽粒产量；与 `CWAM` 地上生物量分别输出 |
| 物候 | 日历日或积温描述生育进程 | 分阶段发育 | 品种系数（如 P1）调节发育，输出 `ADAT`、`MDAT` |
| 土壤氮 | 当前 OSPy 不具备完整氮循环 | 可连接土壤氮模块 | 原生模型可处理氮过程；当前固定参考施氮与初始状态 |
| 连续系统 | 可模拟连续季节，重点仍为作物水分响应 | 可连接轮作、残茬、土壤碳氮等过程 | DSSAT-CSM 有系统过程；本项目仅验证单次玉米试验 |

依据：[S1]–[S3]、[S5]、[S9]。过程更多意味着可以检验更多机制，
也增加了需要数据约束的状态和参数；不据此判定精度高低。

## 2. 软件实现和项目支持范围

| 层次 | 已核对事实 |
| --- | --- |
| FAO AquaCrop | 是理论与官方实现的来源；不要把其他实现等同于所有官方版本 |
| AquaCrop-OSPy 3.1.0 | 本地安装包 METADATA 声明：非 FAO 官方实现，主要对应 FAO 7.1；尚不包含盐分/肥力胁迫、杂草管理、多年生草本相关例程 |
| SnowWindow AquaCrop | 已接入 Python 适配器；支持范围比底层模型小，例如当前仅支持单一均质土层 |
| APSIM NG 2026.9.8116.0 | 已通过本地命令行及官方玉米示例验证 |
| SnowWindow APSIM | 已有原生适配器，完成六环境校准、验证及全年扫描；采用固定探索情景 |
| DSSAT-CSM 4.8.6.2 / `MZCER048` | 本地原生可执行文件与官方玉米示例已运行；需应用本地 ECO `CDAY` 读取补丁 |
| SnowWindow DSSAT | 已有原生适配器，完成六环境的准备、校准、留年验证和 4,380 次播期扫描；固定土壤、品种和施氮并非 G2F 实测 |

OSPy 版本说明依据 [S8] 及本地
`.venv/lib/python3.10/site-packages/aquacrop-3.1.0.dist-info/METADATA`；
项目依据见[适配器](../src/snowwindow/models/aquacrop/adapter.py)
、[APSIM 验证记录](../outputs/experiments/apsim_smoke/verification.json)
与[DSSAT 实验记录](dssat.md)。
升级模型后应重新核对，不能沿用此版本能力表。

## 3. 输入比较

| 输入 | AquaCrop / 当前 OSPy | APSIM NG 玉米 | 当前 DSSAT 参考情景 | G2F 可用程度 |
| --- | --- | --- | --- | --- |
| 逐日气象 | Tmin/Tmax、降雨、ET₀ | Tmin/Tmax、降雨、辐射 | `SRAD/TMAX/TMIN/RAIN` | 基本字段存在；跨年天气需另找连续驱动 |
| 站点 | 计算 ET₀ 所需坐标、气象信息 | 纬度及相关站点信息 | 站点坐标写入气象/试验文件 | 部分环境缺坐标 |
| 土壤水力 | 分层含水阈值和导水参数 | 分层容重、含水阈值及输运/取水参数 | 固定 `SOIL.SOL` 的 `IB00000007` 剖面 | 化验与质地不等于完整水力剖面 |
| 初始水分 | 起始含水量或有效水比例 | 分层起始含水量 | 使用参考初始设置 | 无实际播前分层含水量 |
| 土壤碳氮 | 当前 OSPy 不具备显式氮循环 | 起始矿质氮、有机质及相应参数 | 固定初始土壤氮输入 | 硝态氮化验不能直接代表完整初始状态 |
| 品种 | 冠层、根深、物候、WP*、HI 等 | 物候、叶片、RUE、器官与籽粒过程 | `IB0035`，仅校准 P1/G2 | G2F Hybrid 不能直接等同于任何参考品种 |
| 管理 | 播期、密度、灌溉、田间措施 | 播期、密度、行距、深度、水肥、收获等 | 播期、可用密度；雨养、播期 120 kg N/ha | 水肥实际日程不足 |
| CO₂ | 标准化水分生产力等计算条件 | 相应作物过程条件 | 沿用参考试验的控制设置 | 未独立约束当年站点条件 |

机制和输入依据：[S1][S2][S4][S5][S7][S8][S9]；
G2F 字段、单位及处理见[数据映射](g2f-data.md)。
“可用程度”不表示所有行都已满足输入条件。

## 4. 输出与可比性

| 输出 | AquaCrop / OSPy | APSIM NG | 当前 DSSAT 适配器 | 比较时需统一 |
| --- | --- | --- | --- | --- |
| 产量 | 收获产量、地上生物量、HI | 籽粒干物质 | `HWAM` 除以 1000 得 Mg/ha | 干重与 G2F 标准含水率转换口径 |
| 冠层 | CC 及其时间变化 | LAI、覆盖和叶片相关量 | 目前不解析冠层输出 | CC 与 LAI 不直接相减 |
| 生物量 | 主要为地上生物量 | 可分器官 | `CWAM` 除以 1000 得 Mg/ha | 地上/全株，活体/总量 |
| 物候 | 生育进程和成熟信息 | 阶段名、阶段时间等 | `ADAT`、`MDAT` | `ADAT` 与散粉/吐丝不完全等同；收获与生理成熟不同 |
| 水分 | 蒸发、蒸腾、径流、排水等 | 依水分模块输出 | 本次不从原生输出汇总水量 | 需明确土层、单位、统计起止日 |
| 胁迫 | 冠层、气孔、衰老等过程 | 水氮供需及器官约束 | 本次不导出胁迫指标 | 不把不同模型的指数当作同一变量 |
| 土壤碳氮 | 当前 OSPy 不提供完整过程体系 | 启用相应模块后可报告 | 本次未将土壤氮输出用于验证 | 需独立化验和过程证据 |

输出能力依据：[S1][S2][S5][S8][S9]。APSIM 需要配置 Report 的变量和事件；
示例默认输出不等于模型全部可输出内容。[S6]

项目中的具体注意点：

- AquaCrop 当前 `flowering_proxy_dap` 来自 `HIstart` 的首次日末跨越，
  并非独立散粉事件。用 `pollen_dap` 验证时必须保留这一代理定义。
- APSIM 示例表达式 `[Maize].Grain.Total.Wt*10 as Yield` 将 g/m² 转为
  kg/ha；进入 `dry_yield_mg_ha` 时还需除以 1000。
- 当前 APSIM 示例按收获事件记录；需要逐日曲线时须增加逐日 Report。
- DSSAT 本次 `flowering_proxy_dap` 由 `ADAT` 减播期得到，`MDAT`
  缺失时不把产量记为成熟产量；保留未成熟和执行失败记录。
- 进程退出成功、有产量、已收获、生理成熟是不同状态，须分别核对。

证据：[AquaCrop 输出实现](../src/snowwindow/models/aquacrop/adapter.py)、
[APSIM 示例配置](../outputs/experiments/apsim_smoke/Maize.apsimx)、
[DSSAT 原生输出映射](../src/snowwindow/models/dssat/adapter.py)、
[统一状态定义](../src/snowwindow/domain.py)。

## 5. 如何用于播期窗口研究

以下为分析建议。三个模型的不同固定情景不能直接视为同条件精度排名；
本项目只有小样本的实际播期留年验证，没有全年播期实测验证。

| 研究问题 | 建议与所需证据 |
| --- | --- |
| 播期改变引起的水分供需与产量变化 | 先用 AquaCrop 建立基准，核实气象、初始水分、物候和产量口径 |
| 播期 × 品种 × 密度 × 施氮 | APSIM 是扩展候选；先补土壤水氮、管理和品种约束 |
| 基因型/SNP 到生理参数 | 三者都需额外映射方法；现有 Hybrid 或 VCF 不自动完成参数化 |
| 非常规季节、冬季或跨年播种 | 三者均须单独验证出苗、低温/霜冻、死亡与成熟判定；DSSAT 本次全年扫描全部成熟不等于田间可行 |
| 长期轮作、残茬及氮供应 | APSIM 的相关模块更匹配，但需连续管理与初始状态证据 |

APSIM NG 玉米官方文档列有需进一步完善或验证的物候胁迫、
热胁迫、幼苗死亡等过程；不能把其他作物或 Classic 版本的能力直接套用，
也不能承诺替换模型就能修复异常冬季播种结果。[S2]

建议先比较同一环境、同一年、同一实际播期的输出，再扩展扫描。
固定共同的天气、管理事实和产量口径；分别校准模型自己的参数，
保存土壤映射差异。只使用训练年份选参，以独立年份评估，
先比物候和产量，再在有独立观测时比较生长、水分和氮素过程。
本地 DSSAT 2023 留年结果中，校准后物候 MAE 下降、干产量 MAE 上升，
见[实际结果](model-usage-log.md)；
不能把物候改善延伸为产量预测改善。

## 6. 来源

S1–S8 为 2026-09-23 的理论核对来源；S9 为 2026-09-27 的
本地 DSSAT 引擎与实验产物。动态网页不保证与安装版本完全一致，
具体运行仍以引擎指纹和配置为准。

| 编号 | 来源 | 定位 |
| --- | --- | --- |
| S1 | FAO，AquaCrop Calculation scheme 与参考手册 | `https://www.fao.org/aquacrop/overview/calculation-scheme`；`https://www.fao.org/aquacrop/knowledge-resources/training-materials/en` |
| S2 | APSIM NG，Maize 官方模型文档 | `http://docs.apsim.info/validation/Maize` |
| S3 | Morel 等，2020，Challenges for Simulating Growth and Phenology of Silage Maize in a Nordic Climate with APSIM | DOI `10.3390/agronomy10050645`；历史应用证据，不替代当前版本说明 |
| S4 | APSIM 官方，Creating an APSIM met file using Excel；NG CSV weather | `https://www.apsim.info?p=775/`；`https://docs.apsim.info/docs/usage/met/csvweather` |
| S5 | Dalgliesh 等，CSIRO，2016，A Protocol for the Development of APSoil Parameter Values for Use in APSIM | `https://www.apsim.info/wp-content/uploads/2019/10/Parameters-for-soil-water-Ver24.pdf` |
| S6 | APSIM 官方，Reporting and graphing model output | `https://www.apsim.info/clem/Content/UsingCLEM/GraphsReports.htm` |
| S7 | FAO Irrigation and Drainage Paper 56 | `https://www.fao.org/4/x0490e/x0490e00.htm` |
| S8 | AquaCrop-OSPy 开发者 README 与本地 3.1.0 包元数据 | `https://github.com/aquacropos/aquacrop`；本地路径见第 2 节 |
| S9 | 本地 DSSAT-CSM 4.8.6.2 / CERES-Maize 源码、品种文件、适配器与实跑产物 | [DSSAT 运行指南](dssat.md)、[源码修补](../patches/dssat-4.8.6.2-ecotype-cday.patch)、[六环境报告](../outputs/experiments/g2f_dssat_demo/report/report.md) |
