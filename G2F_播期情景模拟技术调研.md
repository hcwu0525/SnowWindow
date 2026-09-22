# G2F 在不同播种日期情景模拟与产量预测中的应用：技术调研与实验蓝图

调研日期：2026-09-15。交付范围：文献技术报告、字段映射、公开资源核验与实施蓝图；未安装或运行作物模型，未完整统计本地数据，未编写实验实现代码。

## 决策摘要

**建议采用 G2F + 作物生长模型开展这一实验，但将第一版定位为有明确初始化和管理假设的历史播期情景研究。** G2F 提供了环境、播期、开花、产量及遗传材料的连接基础；完整分层土壤、灌溉/施肥事件和初始土壤状态仍需补充。已有 EC 不能随着 `Date_Planted` 改名后继续使用：作物物候、阶段天气暴露、水氮状态和产量都应重新模拟或聚合。

| 决策问题 | 建议 | 主要条件 |
|---|---|---|
| 主线模型 | APSIM Next Generation | 冻结模型与玉米模板版本，补充分层土壤和管理假设 |
| 第二过程模型 | DSSAT CERES-Maize | 有六个主要品种系数和成熟的播期实验范式；需要转换输入格式 |
| 1–2 周快速曲线 | AquaCrop-OSPy；若已有 APSIM 经验则直接 APSIM NG | OSPy 适合水分与温度驱动的原型；不能承担完整氮素机制验证 |
| 纯 Python 且需要 LAI/器官生物量 | WOFOST/PCSE | 必须选择具体生产水平；传统水分限制配置不含动态氮限制 |
| 老师近期检查 | 5 个地点 × 3 年 × 9 播期，单一通用品种 | 135 个成功或有明确失败解释的情景、过程图、原播期对照和局限说明 |
| 5200+ 杂交种 | 不逐个自由率定全部参数 | 通用品种 → 熟期组 → 有充分跨环境观测的杂交种 → 分层/SNP 参数预测 |

以上是基于输入负担、公开工作和接口成熟度的**技术判断**，不是实测性能排名。后文分别讨论各模型的机制和限制。

最重要的证据层级是：①软件能跑；②原播期物候和产量能在独立环境验证；③播期响应在独立多播期对照中成立。第三层不能由第二层自动推出。历史地点/年份之间的播期差异也不等同于随机播期试验。

## 1. 调研方法、数据版本与证据边界

### 1.1 检索与核验方法

检索主题覆盖 G2F + APSIM、G2F + DSSAT、crop model、environmental covariates、envirotyping、sowing/planting date、crop model assisted genomic prediction，以及模型官方输入、玉米模块、许可证和命令行资料。优先核对官方资源、原论文方法和作者代码；近五年工作优先，播期验证与基因组—过程模型耦合的必要基础研究保留。本报告是围绕任务的系统技术检索，未声称进行数据库穷尽检索或 PRISMA 文献计量综述。

证据标记含义：**已核实**表示原文或公开代码支持；**推导/建议**表示本报告的技术判断与实验设计；**未确认**表示不能从已访问材料确认。未找到某资源不能解释为该资源绝不存在。

### 1.2 必须分开的三个数据层

| 数据层 | 范围与用途 | 本报告的处理 |
|---|---|---|
| G2F 年度原始发布 | 按年度发布表型、站点、田间管理、天气、土壤等；字段和完整性可随年度变化 | 从年度 DOI 与说明逐年追溯；不能假设竞赛文件包含全部原始管理记录 |
| Lopez-Cruz 等研究整理版 / MAIZE-HUB | 2014–2021；质量控制后 78,686 条记录、4,372 杂交种、38 个美国地点 | 用于追踪 APSIM EC 工作流；这些数量不是 2014–2023 本地版的覆盖率 |
| 2024 G2F 预测竞赛公开版 | 2014–2023 为训练、2024 为测试；约 18 万小区、5,205 杂交种、272 训练环境、2,425 SNP | 与本地文件命名相符，但未做逐文件哈希匹配，不能认定本地数据与公开发布逐字一致 |

研究整理版数量来自 [Lopez-Cruz 等，Nature Communications，2023](https://pmc.ncbi.nlm.nih.gov/articles/PMC10616096/)；2024 竞赛数量来自 [Chen 等，BMC Research Notes，2026](https://link.springer.com/article/10.1186/s13104-026-07629-5)。后者报告 2024 测试涉及 1,063 杂交种、23 个地点，且部分坐标是近似位置。数据规模与品种参数可率定性是不同问题。

年度发布入口为 [G2F Resources](https://www.genomes2fields.org/resources/)。2022 竞赛 DOI 是 [10.25739/tq5e-ak26](https://doi.org/10.25739/tq5e-ak26)，2024 竞赛 DOI 是 [10.25739/78mn-4394](https://doi.org/10.25739/78mn-4394)。2024 数据目录的许可证标为 Open Data Commons PDDL；不要将数据许可证、论文 CC BY 与模型软件许可证混用。[CyVerse 2024 数据目录](https://dc.cyverse.org/dataset/genomes_to_fields_2024_maize_genotype_by_environment_prediction_competition)

### 1.3 本地文件表头提供的有限事实

前期只读表头检查确认本地有以下文件类别，不包含完整分布/缺失率核验：

| 文件（位于 `data/Training_data`） | 与本任务有关的字段 |
|---|---|
| `1_Training_Trait_Data_2014_2023.csv` | Env、Year、Field_Location、Experiment、Replicate、Block、Plot、Hybrid、双亲、Plot_Area_ha、Date_Planted、Date_Harvested、Stand_Count_plants、Pollen_DAP_days、Silk_DAP_days、Yield_Mg_ha、Grain_Moisture 等 |
| `2_Training_Meta_Data_2014_2023.csv` | Env、Year、Treatment、场地与田块、田块角点坐标、天气站坐标、Previous_Crop、耕作、Irrigated、问题备注 |
| `3_Training_Soil_Data_2015_2023.csv` | Env、Year、采样深度描述、pH、盐分、质地、LOI 有机质、Nitrate-N、砂粉黏比例、养分检测等 |
| `4_Training_Weather_Data_2014_2023_full_year.csv` | Env、Date、T2M_MAX、T2M_MIN、ALLSKY_SFC_SW_DWN、PRECTOTCORR、RH2M、WS2M 等 POWER 风格字段 |
| `4_Training_Weather_Data_2014_2023_seasons_only.csv` | 季节裁剪天气；对更早/更晚播期和播前模拟可能不足 |
| `6_Training_EC_Data_2014_2023.csv` | Env、HI30/CumHI30、TT、biomass、yield、Eo、Eos、Es、ESW、FlowNO3 等按阶段命名字段 |
| VCF、数值 SNP 和双亲 key 文件 | 遗传标记与杂交种/双亲映射；数值编码的等位基因方向须按说明核对 |

本地表型表头**没有独立的 `Realized_Density_plants_ha` 列**；可考虑从 Stand_Count 与面积推导，但先确认 stand count 的测量面积、时间和定义。元数据有 `Irrigated`，未见独立施肥/灌溉事件列；备注或年度原始发布仍可能包含信息。土壤文件名从 2015 开始，不等于已核实所有 2015–2023 环境都有土样，也不等于 2014 完全没有外部土壤资料。

## 2. G2F 是否足以作为模型输入

### 2.1 字段用途矩阵

I = 直接/经格式转换输入；D = 推导或参数映射；C = 率定观测；V = 独立验证观测；E = 外部补充。C/V 的同一条观测不能同时用于拟合和独立验证。

| 字段/文件 | 类别 | 可做什么 | 必须避免的误用 |
|---|---|---|---|
| Env / Location / Year | I | 连接天气、土壤、管理、试验和情景 | 不能直接把 Env 当作唯一管理单元；一个 Env 可能含多个试验/处理 |
| 田块/天气站经纬度 | I | 日长、天气和土壤空间匹配 | 站点坐标不必等于田块坐标；近似坐标要做土壤成分敏感性 |
| Hybrid / 双亲 | I、D | 索引 cultivar 参数，识别重复材料 | Hybrid 字符串不能直接驱动生长机制 |
| SNP / VCF | D | 关系矩阵或学习 SNP → 生理参数 | 不能把 SNP 数值直接填入 DSSAT/APSIM 品种系数 |
| Date_Planted | I | 原播期和九个候选播期 | 不用原播期物候日期固定候选播期阶段边界 |
| Date_Harvested | I、V（有限） | 原试验管理重建与观察终点 | 收获日不是生理成熟日；不据此直接率定成熟热时间 |
| Pollen_DAP_days | C 或 V | Date_Planted + DAP 形成约 50% 散粉日期观测 | 模型 Flowering/Anthesis 定义需对齐，不假设与吐丝完全相同 |
| Silk_DAP_days | C 或 V | 吐丝日期与 ASI，物候参数约束 | 单一开花阶段不能同时完美表达散粉和吐丝两套机制 |
| Yield_Mg_ha | C 或 V | 产量参数与留出验证 | 校正水分基准后与模型籽粒干物质比较；不能直接监督“新播期真实产量” |
| Grain_Moisture | D、V | 判断含水率口径、收获状态 | 先核对 Yield 是否已标准化，不能二次重复校正 |
| Realized_Density / Stand_Count | I、D；敏感性 | 有效株数/面积；plants/ha ÷ 10000 得 plants/m² | 最终成苗是播后结果，可能包含死亡；反事实固定它是实验假设，不是真实播种量 |
| Irrigated / Irrigation | I（标记）、E（事件） | 分类雨养/灌溉，构造情景 | yes/no 不能还原日期、用量、水质和触发规则 |
| Fertilizer / Management | I（有记录时）、E | 施肥种类、N 量、日期、位置、耕作、残茬 | 默认充足 N 不等于原试验真实 N 管理 |
| Daily weather | I | 温度、降水、辐射与 ET 驱动 | POWER 的 GWET* 不等于田块分层实测含水量 |
| Soil chemistry/texture | I、D | 化学状态、质地，部分水力参数估计 | LOI 有机质不能不经转换等同有机碳；化验单不是全剖面 |
| 分层 LL/DUL/SAT/BD/Ksat/根系参数 | E、D | 水分平衡、根区供水、排水与吸收 | 土壤数据库代表成分不等于该试验田的真值 |
| 初始 SW、NO3、NH4、残茬 | E、D | 模拟起点状态与水氮动态 | 表层 N 浓度不能代替整个剖面矿质氮 |
| EC / APSIM-derived variables | 模拟产物；诊断/ML | 原播期参考、阶段聚合范式 | 不作为改变播期后的固定输入，不作为独立过程观测验证模型自身 |

G2F 表型与气象可建立关系，但 DSSAT 官方最小数据还要求土壤剖面、播深/行距、初始状态与管理；模型能运行所需的默认值与模型能被验证所需的观测要分开。[DSSAT Minimum Data](https://dssat.net/data/minimum-data/)

### 2.2 关键转换与外部补充

**天气。** 主用全年天气；模拟区间可能跨前后年，须补足共同起点至所有候选播期成熟后的区间。转换关系是：T2M_MAX → Tmax；T2M_MIN → Tmin；PRECTOTCORR → rain；ALLSKY_SFC_SW_DWN → radn；RH2M/露点与 WS2M 用于湿度、VPD 和 ET。辐射必须按源文件元数据确认单位：若为 kWh/m²/day 则乘 3.6 转 MJ/m²/day；若已为 MJ，则不转换。PCSE 内部天气单位另有要求，不能直接复用 APSIM 数值。POWER 产品和接口可提供不同单位/社区格式，不能凭列名决定。[NASA POWER 官方入口](https://power.larc.nasa.gov/)、[API 文档](https://power.larc.nasa.gov/api/pages/)、[DSSAT Weather module](https://dssat.net/weather-module/)

**土壤。** 美国地点优先 SSURGO/gSSURGO，记录 map unit、component、horizon 和数据库日期。最低应有层厚、砂粉黏、容重、LL/DUL/SAT 或其模型对应物、有机碳、根区深度、排水/导水参数。实测表层化验与数据库深层可以融合，但不能把一年表层 N 检测复制成所有年份和土层的状态。加拿大地点需要另选对应国家/全球土壤资料，不能假设 SSURGO 覆盖。[NRCS SSURGO](https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo)、[SSURGO 元数据](https://www.nrcs.usda.gov/resources/data-and-reports/ssurgo/stats2go-metadata)

**管理和状态。** 优先追溯 G2F 年度原始管理资料；仍缺失时将补充方式显式分成“雨养已确认”“灌溉事件已知”“灌溉标记但事件未知”和“N 事件已知/假设”。初始化需要共同日期的土壤水、矿质氮和残茬/碳库；有机质、前茬只能帮助约束，不能唯一反推。AquaCrop 还需要 ET0；可按 FAO Penman–Monteith 用温湿风辐射计算，须记录算法、海拔和单位。[FAO AquaCrop 输入要求](https://www.fao.org/aquacrop/overview/input-requirements/)

若 N 浓度为 mg N/kg soil，则一层 N 库近似为：

`N_kg_ha = concentration_mg_kg × bulk_density_Mg_m3 × thickness_m × 10`。

该转换需要明确浓度是 NO3-N 还是 NO3 离子、有无砾石修正、采样层厚与容重。它不补回未采样深层和铵态氮。以上公式与融合规则为本报告的工程建议。

## 3. 已有 APSIM EC：生成条件、可复用性与隐患

### 3.1 研究版已核实配置

Lopez-Cruz 等（2023）方法报告使用 APSIM NG `2021.11.3.6921` 和 R `apsimx 2.3.1`；通用玉米模板，按年—地点平均株密度和原播期设置；用环境平均吐丝日期调幼年期热时间；初始可利用水为 50%，标准化硝态氮设置为 200 kg/ha；天气来自 POWER、土壤来自 SSURGO。[原论文 Methods](https://pmc.ncbi.nlm.nih.gov/articles/PMC10616096/)

本次还直接读取作者 [MAIZE-HUB 流程压缩包](https://github.com/QuantGen/MAIZE-HUB/blob/main/data_curation_and_ecov.zip)，核对所得细节如下。论文概述和代码实现应同时保留：

| 配置/过程 | 代码核验结果 | 对当前任务的影响 |
|---|---|---|
| 模板 | 从安装目录复制 `Maize.apsimx`；ZIP 内没有 `.apsimx` 模板 | 只下载 ZIP 不能保证复现；新版安装的模板会改变结果 |
| 播种规则 | `StartDate=d0`，`EndDate=d0+1`；`MinESW=0`、`MinRain=0` | 原配置有两日播种窗口；严格固定播期时要记录实际播种事件 |
| 品种 | 创建并种植 `Custom` | 不是 4372 杂交种分别率定的品种库 |
| 热时间默认值 | Juvenile=210；GrainFilling=510 °C·day | 仅是该函数起始值，不是所有北美玉米通用真值 |
| 物候调整 | 以模拟 Flowering 对齐环境平均吐丝；步进迭代，未达到目标也可能在迭代上限停止 | 要检查误差和收敛状态，不能假设每个环境精确对齐 |
| 两参数联动 | `gdd_gf = gdd_juv + (gdd_gf0-gdd_juv0)` | 调 Juvenile 时还联动 GrainFilling；不能解释为仅改一个开花参数 |
| 初始水 | 修改 `InitialWater.FractionFull=0.50`，之后替换土壤 profile | 应检查最终保存的 `.apsimx` 是否仍符合预期，不靠调用顺序推定 |
| 200 kg/ha N | driver 传入 200；函数写入 `SowingFertiliser.Amount` | 这是播种管理器 N 设置；不能直接称为实测剖面初始 NO3，也要核对模板施肥类型 |
| 模拟起止 | 函数起点 `d0−90`；终点 `d0+210`，天气尾部不足时可能截短 | 与论文天气描述不同；新实验需独立检查是否成熟和是否截断 |
| 土壤匹配 | `get_ssurgo_soil_profile`；失败时随机扰动坐标重试，取返回剖面 | 不宜原样复用无上限随机搜索；固定匹配规则和失败记录 |
| 灌溉 | 读取的 driver 未显式传入事件表；模板具体默认未核实 | 不能声称还原了 G2F 各地点真实灌溉 |

代码位置：`5_APSIM/code/1_apsim_sim.R`、`tools/APSIM_functions.R`、`6_ecov/code/1_get_env_cov.R`，均在上述 ZIP 中。读取的是公开 main 分支 ZIP；该文件最近一次提交 SHA 为 `55fd3cbcc1ce0bbc19b4291f6f9556ce10df0c07`，下载内容 SHA256 为 `edea15e5ed181b928440e6107933fed83499dece2c0b5331e92ff910c583fcf8`。这提供来源追踪，**不表示本次已重运行复现**。[工作流与依赖说明](https://github.com/QuantGen/MAIZE-HUB)

### 3.2 EC 名称到底表示什么

作者代码明确映射：Ger=Germination；Eme=Emergence；EnJ=EndJuvenile；Flo=FloralInitiation；Fla=FlagLeaf；Flw=Flowering；StG=StartGrainFill；EnG=EndGrainFill；Mat=Maturity；Har=HarvestRipe。**Flo 是花器官分化，不是开花；Flw 才是开花。** Har 也不是实测 Date_Harvested。

在该研究代码中：`HI30` 是日最高温与相对湿度计算的 heat index 大于 30°C 的天数；`CumHI30` 对阶段计数再累加；其他 W0 变量按阶段 `sum/length` 求均值，yield 在聚合前做单位转换。阶段边界使用首个匹配阶段，且区间两端都包含，因此相邻阶段可能共享边界日。不能把所有 `TT` 列都当作阶段累计积温，不能把 `HI30` 当作 CERES/APSIM 自带花粉热伤害因子。[EC 作者代码资源](https://github.com/QuantGen/MAIZE-HUB/blob/main/data_curation_and_ecov.zip)

这也意味着 biomass/yield 是特定阶段的模拟状态摘要，FlowNO3 等流量列还需要确认分层展开和聚合口径。新 EC 可以采用更清晰的半开区间和均值/总量/末值分开命名，但必须声明与旧 EC 不再逐列等价。

### 3.3 竞赛版能否认定采用相同配置

2022 竞赛结果论文明确列出 APSIM 计算的 EC。[Washburn 等，Genetics，iyae195](https://doi.org/10.1093/genetics/iyae195)。2024 数据说明确认提供 EC、使用 POWER 天气且继承 2022 数据，但本次访问的正文**没有明确写出 EC 的 APSIM 版本、品种参数或 2022–2024 新环境的率定方式**。[2024 竞赛说明](https://link.springer.com/article/10.1186/s13104-026-07629-5)

本地字段与 MAIZE-HUB 命名高度一致，支持“继承相关工作流”的判断；它不足以证明逐项采用相同参数。本次从2024公共目录API定位到 `readme.txt` 和 `COMPETITION_DATA_README.docx`，但文件端点返回CyVerse人工验证页面，未取得README正文。因此不把研究版200 kg N、Custom热时间或模板版本当作竞赛版已确认事实。这里是来源访问受限，不是已证明README没有说明。

后续 Phase 0 应取得发布 README、EC 原始流程与最终配置。若无法取得，建立自己的冻结版本重模拟 EC，称作“本实验重新生成 EC”，不用“官方 EC 精确复现”。

### 3.4 改播期后什么能复用

| 内容 | 可否复用 | 原因 |
|---|---|---|
| 地点坐标、年份、土壤物理剖面、SNP | 可，若地点/田块确实相同 | 不随本次日期干预改变 |
| 同一日历日期天气与日长 | 可 | 历史天气序列固定；补充早播/晚播和跨年区间 |
| 已率定品种系数、目标株密度 | 可，作为固定实验条件 | 不在每个候选播期重新拟合，否则改变的不止播期 |
| 共同起点的初始 SW/N/残茬 | 可 | 同一实验分支的共同前史 |
| 候选播种当天 SW/N | 不固定，通常应重算 | 播前蒸发、降水、矿化和排水持续发生 |
| 物候、LAI、根系、器官生物量、产量 | 必须重模拟 | 温度累积和资源供需轨迹已改变 |
| 阶段温湿风辐射、HI30 等 | 必须重新聚合 | 即使原始天气相同，阶段日期已变化 |
| 水/N 胁迫、ET、吸收、淋失 | 必须重模拟 | 是动态状态和生长的反馈结果 |
| 原 EC 的缺失处理、标准化/PCA | 方法可参考，统计参数在训练折拟合 | 防止测试分布或表型泄漏 |

严格的干预表示为 `Y(d | G, soil, weather, initial_state, management_policy, model_version)`。天气相同不意味着环境暴露相同；初始化规则和管理日期规则属于该条件的一部分。

## 4. 候选模型的机制、输入、输出与率定

### 4.1 共同输入匹配矩阵

A=已有类别但需核实质量；D=可推导；E=外部补充/显式假设；H=大规模难获得；—=所列实现不直接表达。任何 A 都不代表已核实无缺失。

| 输入 | APSIM NG | CERES-Maize | AquaCrop-OSPy | PCSE/WOFOST | STICS | CropSyst |
|---|---|---|---|---|---|---|
| 日温、雨、辐射 | A | A | A（辐射可用于 ET0） | A | A | A |
| 湿度、风、ET0 | A/D | A（ET 选项） | D（ET0 必需） | A/D | A/D | A/D |
| 层厚、容重、质地 | A+E | A+E | A+E | A+E | A+E | A+E |
| 水力/排水/根区土壤参数 | D/E | D/E | D/E | D/E | D/E | D/E |
| 品种生理系数 | H；可从表型约束 | H；可从表型约束 | H；默认玉米可起步 | H；公共玉米参数可起步 | H；配套品种可起步 | H；配套参数需检查 |
| 原播期 | A | A | A | A | A | A |
| 株密度 | D/E | D/E | D/E | 依模型表达，非标准直接 G×density | D/E | D/E |
| 播深、行距 | E/原始管理 | E/原始管理 | 表达粒度有限 | 表达粒度有限 | E/原始管理 | E/原始管理 |
| 施肥日期/形式/N量 | E | E | —（当前 OSPy 肥力模块缺失） | E（NWLP 时） | E | E |
| 灌溉日期/量/规则 | E | E | E | E | E | E |
| 初始水 | E/D | E/D | E/D | E/D | E/D | E/D |
| 初始矿质氮/碳库/残茬 | E/H | E/H | — | E/H（有 N 时） | E/H | E/H |
| CO2、海拔、前茬等 | A/D/E | A/D/E | A/D/E | A/D/E | A/D/E | A/D/E |

上述矩阵是官方需求与 G2F 字段类别的**映射判断**，不是每个模型均需所有字段的绝对最小清单。具体需求取决于 ET、土壤、水氮和管理模块。

### 4.2 APSIM Classic 与 Next Generation

**机制。** 按热时间和阶段控制叶片/器官发育；辐射截获及 RUE 驱动干物质生产，叶面积和衰老影响光截获；根系吸收水氮，土壤水与碳氮模块模拟蒸发、排水、矿化、供给和损失；器官分配与籽粒汇决定产量。播期改变会重新排列温度、日长、辐射、蒸散需求和根区供给。选择 SWIM/SoilWater 以及玉米模板版本会改变具体方程和能力。[APSIM NG 文档](https://docs.apsim.info/docs/)、[Maize 模块](https://jenkins.apsim.info/validation/Maize)

**输出。** 可报告阶段/日期、LAI、根深、器官干物质、Grain.Wt、土壤分层 SW、NO3/NH4、ET 及水氮供需/限制指标；具体路径须检查冻结模板。Flowering 与 silking 要作观测定义映射，不假设各版本都独立模拟两者。日高温暴露可以派生；**不能承诺每个 APSIM 玉米版本都有独立的花粉热伤害/粒数热胁迫机制**。当前 Maize 官方文档仍将部分粒数热胁迫列为发展需求；2026 新增渍水机制亦不应倒推为 2021 模板已有能力。[Maize 版本与发展说明](https://jenkins.apsim.info/validation/Maize)

**品种参数。** NG 采用 cultivar override 的模型路径，重点是 Juvenile/GrainFilling 的 Target、叶片出现/扩展、RUE、籽粒汇与氮浓度/吸收等，不能用 Classic 参数名机械替换。MAIZE-HUB 可参考 `[Phenology].Juvenile.Target.FixedValue` 和 `[Phenology].GrainFilling.Target.FixedValue`；正式率定应只开放可识别参数。[作者代码](https://github.com/QuantGen/MAIZE-HUB)

**Classic 的具体率定证据。** Winn 等用 APSIM 7.10、SWIM 和 SOILN，针对 15 个公开 ex-PVP 杂交种开展两年、三个环境的多性状人工迭代率定：先物候，再生物量/叶面积，再分配与 N。Table 2 提供 17 类参数；例如 B73×Mo17 的出苗至花分化热时间为 310、吐丝至成熟为 700 °C·day、RUE 为 1.85 g/MJ。其参数包括 `tt_emerg_to_endjuv`、`tt_endjuv_init`、`tt_flower_to_maturity`、`tt_flower_to_start_grain`、`potKernelWt`、`GNmaxCoef`、`rue`、叶出现率和根前沿速率。它们是特定旧模型/材料的结果，**不能直接输入 NG**。[Winn 等，2023，正文 Table 2 与 Methods](https://www.genomes2fields.org/docs/publications/csc2.20857.pdf)

**适用判断。** 充分利用 G2F 的主线首选 NG；Classic 用于旧参数/论文复现。NG 从头重写且跨平台运行，不保证 Classic/NG 数值等价。[APSIM NG 架构说明](https://docs.apsim.info/docs/)

### 4.3 DSSAT CERES-Maize

**机制。** 热时间、幼年期与光周期控制发育，叶片出现和面积控制冠层，辐射转化产生生物量；水氮供给限制生长，模拟器官分配、籽粒数量/增长和产量。天气、土壤、初始状态和管理共同驱动土壤—植物—大气动态。温度响应或高温暴露指标不应自动解释为完整花粉热伤害机制，须查指定 CERES 版本。[DSSAT Models Overview](https://dssat.net/models-overview/)、[CSM 官方源码](https://github.com/DSSAT/dssat-csm-os)

**输入/输出。** `.WTH` 天气、`.SOL` 分层土壤、FileX 试验/处理、`.CUL/.ECO/.SPE` 作物参数以及初始水氮和管理事件。可获得 FLO/MAT、TOPWT、HARWT 和 PlantGro 等日过程输出；LAI、根区、土壤水氮、ET/限制变量取决于开启输出。散粉/吐丝的观测映射需核对，不凭 FLO 名称推定两者均独立输出。[DSSAT 最小输入](https://dssat.net/data/minimum-data/)、[DSSATTools 3.0 输出接口](https://github.com/daquinterop/Py_DSSATTools)

| 品种系数 | 意义 | 用 G2F 率定的现实性 |
|---|---|---|
| P1 | 出苗至幼年期结束的积温，基温 8°C | 可由开花观测间接约束；与叶出现等存在补偿 |
| P2 | 长日条件下发育延迟/光周期敏感系数 | 北美材料可有弱敏感，但不能从单环境唯一识别 |
| P5 | 吐丝至生理成熟积温 | G2F 收获日不能替代成熟日；需外部先验/观测 |
| G2 | 潜在籽粒数/株 | 仅最终产量难与 G3、资源限制分离 |
| G3 | 潜在单粒增长速率 | 需要籽粒或生物量过程观测增强识别 |
| PHINT | 相邻叶尖出现的积温间隔 | 开花观测可约束但最好有叶龄/叶数 |

六系数定义和玉米播期验证实例见 [Li 等，Agronomy，2021](https://www.mdpi.com/2073-4395/11/4/674)。不为全体杂交种同时开放六系数；先固定 P2/PHINT 等先验，拟合少量物候参数，再用独立信息约束产量形成。GLUE/自动优化能找可行参数集，不解决观测信息不足的问题。

**适用判断。** 作为 APSIM 的第二模型，可比较播期响应与水氮限制解释；公开 CSM 引擎和六系数文件清晰，工程转换负担高于原生 Python。检索到播期优化实例不等于检索到可直接复用的 G2F 专用品种库。

### 4.4 AquaCrop：官方 Fortran 与 AquaCrop-OSPy 要分开

**机制。** 用冠层覆盖 CC 而非 LAI 主导冠层；分开计算蒸发和蒸腾，累积归一化蒸腾与水分生产率得到生物量，再以胁迫修正收获指数形成产量。水分限制影响冠层扩展、气孔、衰老和 HI；温度控制热时间并可影响授粉。播期会改变热量积累、ET0、供水与开花温度暴露。[FAO 计算框架](https://www.fao.org/aquacrop/overview/calculation-scheme/)、[FAO Crop Yield Response to Water](https://www.fao.org/4/i2800e/i2800e.pdf)

**输入。** Tmax/Tmin、rain、ET0、CO2、土层 FC/PWP/SAT/Ksat、初始水、玉米参数、密度、播期和灌溉。官方模型的肥力胁迫是简化表达，不是 CERES/APSIM 式动态土壤氮循环；**当前 OSPy README 明确肥力和盐分胁迫等尚未实现**。因此不能声称 OSPy 可充分利用 G2F 氮管理。[FAO 输入](https://www.fao.org/aquacrop/overview/input-requirements/)、[OSPy 功能边界](https://github.com/aquacropos/aquacrop)

**参数/输出。** 重点是 Tbase/Tupp、Emergence、HIstart、Flowering、Senescence、Maturity、CGC/CDC、CCx、根深、WP、HI0 和水分胁迫阈值。注意 `Flowering` 在参数库中是**开花持续时长**，不应直接赋成 `Pollen_DAP`。当前公开 `MaizeGDD` 参数库示例含 CalendarType=2、Tbase=8、Tupp=30、Emergence=80、HIstart=880、Maturity=1700 °C·day、PlantPop=75000、HI0=0.48；这些仅是库示例，不是 G2F 校准结果。[OSPy 玉米参数源码](https://github.com/aquacropos/aquacrop/blob/master/aquacrop/entities/crops/crop_params.py)

可得到冠层、biomass、根深、水储量、水分限制/蒸散和最终 dry yield 等；物候日期需从状态/事件提取。没有直接 LAI、粒数和动态 N 的承诺；散粉/吐丝不可当作两个独立生殖阶段观测。OSPy API 核心对象为 AquaCropModel、Soil、Crop、InitialWaterContent，以及管理对象；正式实验冻结版本，不直接复用旧教程私有 `_outputs` 路径。[OSPy API/示例](https://github.com/aquacropos/aquacrop)

**适用判断。** 最快水分/温度型原型，低接口成本；品种未知和水力参数未知仍会影响最优播期。若要展示 N stress、LAI 和粒数机制，它不是本任务全功能替代。

### 4.5 WOFOST / PCSE

**机制。** 温度/日长驱动物候，叶片光合能力、辐射、温度和 LAI 决定冠层同化；扣除呼吸、按发育阶段分配给根茎叶和储藏器官。土壤水供给与蒸腾反馈生长；氮限制只在相应配置中出现。播期影响同化与发育所经历的天气序列，不只是移动固定生育天数。[PCSE 官方框架](https://github.com/ajwdewit/pcse)、[WOFOST 生产水平类](https://pcse.readthedocs.io/en/stable/_modules/pcse/models.html)

**配置必须具体。** 可先用 `Wofost81_WLP_CWB` 或同版本的水分限制类；需要 N 时使用 `Wofost81_NWLP_MLWB_SNOMIN` 等指定配置。PP 是潜在生产、WLP 是水分限制、NWLP 含养分限制；不能将 WOFOST 7.2 水分配置与 8.1 SNOMIN 的能力合并描述。[模型类源码](https://pcse.readthedocs.io/en/stable/_modules/pcse/models.html)

**参数/输出。** TSUMEM、TSUM1、TSUM2、DTSMTB、IDSL/DLO/DLC 控物候；AMAXTB、EFFTB、KDIFTB、SLATB、SPAN、分配表和根系参数控同化/器官。可输出 DVS、LAI、TAGP、TWSO、RD、SM、TRA 等；DVS≈1 为 anthesis，成熟按目标 DVS/事件确定。不能假设标准 WOFOST 给出独立 silking、籽粒数和高温授粉失败。株密度也不是可在所有标准配置中直接输入后产生玉米密度效应的统一参数。[物候源码与参数定义](https://pcse.readthedocs.io/en/stable/_modules/pcse/crop/phenology.html)、[公共作物参数](https://github.com/ajwdewit/WOFOST_crop_parameters)

**播期注意。** AgroManagement 可指定 `crop_start_type: sowing`；很多示例采用 emergence，直接换日期会绕过播种—出苗过程。保持共同土壤模拟起点，以指定 crop_start_date 种植；用 maturity end type 并设置最长历期/日历截止。[PCSE 管理文档](https://pcse.readthedocs.io/en/develop/user_guide.html)

**适用判断。** Python 环境最顺畅，适合 LAI/生物量曲线和 ML 数据生成；成熟玉米播期＋N 管理＋杂交种机制主线的 G2F 可复用证据弱于 APSIM。

### 4.6 STICS

**机制与输入。** 通用日尺度土壤—作物模型，模拟温度驱动物候、LAI、生物量与器官/产量形成，土壤水氮及限制，允许轮作和裸土期。输入包括日天气、分层土壤、初始状态、品种、密度、播期、施肥/灌溉/耕作。官方配套多种作物和品种参数，包括玉米。[STICS 官方模型说明](https://stics.inrae.fr/eng/general-presentation-of-the-model)

**参数与输出。** 物候关注 stlevamf、stamflax、stlevdrp、stdrpmat；LAI/叶寿命参数与粒数/粒重参数再约束生长和产量。参数含义与阶段定义须按选定版本检查。常见过程输出包含 LAI、生物量、产量、根前沿、土壤水、植物 N 和胁迫；散粉/吐丝和粒数热伤害能力不能仅由“支持玉米”推定。CroptimizR 提供分步物候率定的可运行文档，示例边界不是 G2F 玉米已验证边界。[官方率定协议示例](https://sticsrpacks.github.io/CroptimizR/articles/AgMIP_Calibration_Phenology_protocol.html)

**情景/率定。** 改技术管理文件的播期，保持 USM 的土壤/品种/初始与管理政策一致，完整重跑再提取过程。SticsOnR 控运行，SticsRFiles 编辑输入，CroptimizR/CroPlotR 支持率定和分析，Python 可经文件/subprocess 或调用 R 集成。[SticsRPacks](https://github.com/SticsRPacks)

**适用判断。** 适合有 STICS 经验团队的水氮/管理科研；从 G2F 零起步并在一两周复用现成 EC 的优势较弱。

### 4.7 CropSyst

**机制/数据。** 多年多作物系统模型，热时间发育、冠层与生物量形成、根区水分/ET、氮循环和管理相互作用；改变播期后需重跑水氮与生长。PSU 开发团队说明其数据库与批运行结构适合大项目/HPC，学习成本较高。[开发团队说明](https://plantscience.psu.edu/research/labs/kemanian/models-and-tools/cropsyst)

具体输入仍需分层土壤、天气、热时间/冠层/生产率/收获参数、管理及初始水氮；可用于生物量、产量和水氮诊断。但本次未取得可冻结的完整官方当前代码、许可证、玉米品种文件和输出变量手册，因此**粒数、独立 heat stress、散粉/吐丝输出及 Linux 部署细节标为未确认**。不能用近似第三方移植填补这些证据缺口。

尤其 [pruettm/cropsyst](https://github.com/pruettm/cropsyst) 是 R 作物蒸散框架，仓库 MIT 许可不能证明完整 CropSyst 引擎具有相同许可或功能。理论上适合水氮管理，当前快速落地推荐度低。

### 4.8 补充模型与近期路线

**DSSAT CSM-IXIM。** 这是与CERES不同的玉米模块，不应把其机制混写成CERES能力。官方说明IXIM具有逐叶扩展/衰老与叶尺度同化、呼吸、穗生长、粒数、N分配，并加入ASI及花粉/花丝的不同热响应。若研究重点是 `Pollen/Silk → ASI → heat exposure → kernel set`，它比只添加HI30暴露指标更切题。输入仍基于DSSAT天气/土壤/管理体系，品种与生殖参数需按IXIM文件核对，CERES六系数不是其完整参数描述。本次未核实G2F专用IXIM参数库，故列为科研扩展候选，而非最小demo首选。[DSSAT官方IXIM说明](https://dssat.net/csm-ixim/)、[官方编译文件中的IXIM模块](https://github.com/DSSAT/dssat-csm-os/blob/develop/CMakeLists.txt)

**SIMPLE。** Zhao 等 2019 的通用模型用较少参数描述发育、辐射驱动生物量、温度/干旱限制和产量；原论文报告 13 个作物参数、其中 4 个品种参数。适合低成本基线，不提供本任务要求的完整玉米生殖、水氮及粒数链。公开 Python 移植存在，仍须确认其与原论文版本一致。[原论文](https://www.sciencedirect.com/science/article/pii/S1161030118304234)、[Python 移植](https://github.com/ataraxno/SIMPLE_crop_model)

**Cycles。** 开发团队提供水碳氮、分层土壤、多年管理和作物产量框架，可用于播期/轮作管理；当前 PSUmodeling/Cycles 仓库主要发布执行文件与文档，不能把 utils 仓库的 MIT 许可直接当引擎许可。未核实 G2F 专门率定/EC 复现路线。[团队介绍](https://plantscience.psu.edu/research/labs/kemanian/models-and-tools/cycles)、[发布仓库](https://github.com/PSUmodeling/Cycles)

**近期 emulator/可微模型。** 2026 预印本 “From Simulation to Discovery: AI Enabled Probabilistic Emulation of Mechanistic Crop Systems” 报告 APSIM 玉米多输出近似和百万级训练模拟，是 Phase 4 的相关线索；不是本次已复现的可直接替代品。可微生物物理模型也可研究 SNP → 参数，但替换机制模型之前仍需确认作物、管理、训练域和公开配置。[2026 APSIM emulator 预印本](https://arxiv.org/abs/2605.22848)、[2026 动态参数耦合预印本](https://arxiv.org/abs/2603.15411)

**2023数据驱动作物模型。** “A data-driven crop model for maize yield prediction” 用知识约束的少量生物参数与历史数据优化耦合，研究的是1981–2020美国县尺度玉米，公开代码归档于Zenodo。它是参数学习路线的可复现参考，不是G2F小区/杂交种参数库，也不能直接替代完整土壤水氮和播期生殖过程验证。[Communications Biology原论文](https://www.nature.com/articles/s42003-023-04833-y)、[代码归档](https://doi.org/10.5281/zenodo.7792271)

## 5. 工程实现、许可证与十万级可行性

### 5.1 工程核验表

| 实现 | 代码/许可证 | Python 与无 GUI / Linux | 批量、并行与容器 | 当前落地判断 |
|---|---|---|---|---|
| APSIM NG | GitHub 可见源码；自定义 General Use，教育/个人学习/公益研究免费，商业活动另有 Special Use | 官方 Models CLI；跨平台；Python subprocess + `.apsimx`/SQLite 稳妥，非原生官方 Python 模型 API | 官方 CLI 批运行和 Docker 镜像；情景可外部并行 | 主线可落地；须注册与冻结模板 |
| APSIM Classic | 官方旧源码/下载；核对所用版本 APSIM 条款 | CLI 可用；旧构建依赖较复杂 | 可外部分批并行；当前官方容器支持未核实 | 旧文献复现适用 |
| DSSAT CSM | 官方 Fortran 引擎 BSD-3-Clause；数据/GUI另核许可 | CMake 编译、headless；Python DSSATTools 是第三方 | 多 FileX treatment/batch；独立工作目录并行；本次未确认官方维护通用 Docker | 第二过程模型可落地 |
| AquaCrop 官方 Fortran | KU Leuven/FAO 支持，当前源码 LICENSE 写 v7.3 BSD-3 | Linux/macOS/Windows standalone；共享库也可构建 | 文件批运行，可进程并行；官方通用 Docker 未确认 | 官方核心可复现，接口需适配 |
| AquaCrop-OSPy | Apache-2.0；不是 FAO 官方实现 | Python API，Linux/headless；编译/Numba 首次初始化成本单列 | Python 情景循环/进程；官方通用 Docker 未确认 | 最快水分型 demo |
| PCSE | 当前仓库 EUPL 1.1 或后续批准版本；作物参数库另查许可证 | 原生 Python，ParameterProvider + weather + AgroManagement | 独立实例/进程；官网通用 Docker 未确认 | Python 数据管线优先 |
| STICS | 核心 CeCILL-C；JavaStics CeCILL-B；R 包 LGPL | 核心 CLI 与 R 接口；Linux可用；Python非主要官方接口 | R 控制批运行；外部并行目录隔离；Docker 未确认 | 团队熟悉时可落地 |
| CropSyst | 完整当前源码/引擎许可本次未确认 | 原生 Python API/当前 Linux部署未确认 | 团队说明支持批/HPC；冻结工程资源仍缺 | 不列为近期主线 |
| SIMPLE Python 移植 | 移植仓库 Apache-2.0 | Python/headless；非复杂玉米专用 | 外部情景并行；容器未确认 | 低参数基线 |

来源：[APSIM 许可与注册](https://registration.apsim.info/)、[源码 LICENSE](https://github.com/APSIMInitiative/ApsimX/blob/master/LICENSE.md)、[命令行](https://docs.apsim.info/docs/usage/commandline)、[官方 Docker](https://hub.docker.com/r/apsiminitiative/apsimng)、[DSSAT 引擎](https://github.com/DSSAT/dssat-csm-os)、[AquaCrop LICENSE](https://github.com/KUL-RSDA/AquaCrop/blob/main/LICENSE)、[官方构建与运行](https://github.com/KUL-RSDA/AquaCrop)、[OSPy](https://github.com/aquacropos/aquacrop)、[PCSE LICENSE](https://github.com/ajwdewit/pcse/blob/master/LICENSE)、[STICS 许可](https://stics.inrae.fr/eng/download)。许可证是版本相关的事实，不把公开源码全部称为无条件开放源码。

DSSATTools 当前仓库标 GPL-3.0，但部分 PyPI 旧/预发布元数据仍显示 MIT，存在版本/元数据差异；正式使用以冻结版本 LICENSE 为准。3.0 API 与旧版本不兼容，当前 `DSSAT.run_treatment(...)` 接收 FileX section 对象，返回标准摘要，日输出通过 output_tables 访问，不抄用旧 2.x 示例。[当前仓库](https://github.com/daquinterop/Py_DSSATTools)、[PyPI 预发布元数据](https://pypi.org/project/DSSATTools/3.0.0a0/)

### 5.2 单次计算成本：本次不报未经测量的秒数

没有取得在同一硬件、模型版本、模拟长度和输出设置下比较上述模型的可靠公开 benchmark，因此不能严谨给出“APSIM 每次 X 秒，十万次 Y 小时”。日尺度单田块模型的十万级**工程上现实**，但率定迭代、动态 N、启动开销和逐日分层输出可能比基础情景更昂贵。这个结论是工作量结构推导，不是运行承诺。

后续用 100 个代表情景测冷启动/稳态时间、内存、P50/P95、失败率和输出体积，再按：

`T_wall ≈ N × mean_time / (workers × efficiency) + I/O + setup`。

仅作算术例子：若实测 1 秒/情景，10 万次约 27.8 CPU 小时；若 10 秒则约 278 CPU 小时；这两个秒数**不是任一模型实测值**。初始化下载、首次编译、天气服务请求都应移出内层循环，保存成可复用资产。

### 5.3 规模不要误算

按公开 272 环境 × 9 播期 × 1 通用品种，只有 **2448** 个基础情景。极端全笛卡尔积 272 × 5205 × 9 是 **12,741,840** 个，约 1274 万，而不是十万；正式任务应只使用有效 Env×Hybrid 组合，不能把未试验材料全部默认具有参数。通用品种模式中把同一条结果复制到所有 Hybrid，不会产生杂交种特异响应。

扩展规模为 `有效Env×cultivar组合 × 9 × 参数样本 × 初始化样本 × 管理政策 × 模型数`。不要按小区重复次数重复同一过程模拟；同质条件的重复用于估计观测噪声。

Python/Pandas 负责输入清洗和情景表，过程引擎独立工作目录运行，结果转为 summary/daily/stage 表。每个任务记录模型/模板 hash、参数来源、实际播种日、终止原因、输入 hash；避免共写 SQLite 或 DSSAT 固定输出文件。PyTorch 的加入不会自动使这些模型可微，黑箱率定与 surrogate 训练是不同工作。

## 6. 已有研究：哪些可以直接借鉴

### 6.1 相关研究复现表

| 研究 | 数据、模型、输入与率定 | 输出/是否改变播期 | 代码、参数与复现判断 | 本任务借鉴 |
|---|---|---|---|---|
| **Lopez-Cruz 等，2023，Nature Communications 14:6904**；Leveraging data from the Genomes-to-Fields Initiative to investigate genotype-by-environment interactions in maize in North America | G2F 2014–2021；APSIM NG + POWER + SSURGO；环境均值密度、吐丝约束物候、标准化水/N | 阶段 EC、遗传/环境结构与基因组预测；未建立独立候选播期优化实验 | MAIZE-HUB 数据与流程 ZIP 公开；依赖安装模板，代码/论文细节有差异；本次只读核验，未重跑 | 最直接 EC 和土壤/天气管线；冻结原参数再扩展日期 |
| **Winn 等，2023，Crop Science 63:511–534**；Calibration of a crop growth model in APSIM for 15 publicly available corn hybrids in North America | 15 公开 ex-PVP 杂交种；2017–2018 专门多性状试验；APSIM Classic 7.10/SWIM/SOILN；人工分步率定 | 物候、LAI、器官/籽粒/N 与多年 G×E；不是完整 G2F 5205 品种率定，也不是多播期实测验证 | 正文 Table 2 和补充参数/敏感性资料公开；独立执行项目/优化代码本次未确认，不能直接声称一键复现 | 物候优先、有限参数、多过程约束；旧参数转 NG 需重新验证 |
| **Washburn 等，在线2024/卷期2025，Genetics，iyae195**；Global genotype by environment prediction competition reveals that diverse modeling strategies can deliver satisfactory maize yield estimates | 2022 竞赛：2014–2021训练、2022测试；提供 APSIM EC；不同参赛团队预测路线 | 原测试环境产量预测；不是统一过程模型重跑播期实验 | 论文给17团队方法/代码，资源按团队核查；不是统一全杂交种作物参数库 | 留年预测基准、现有EC定位与多方法对照 |
| **Chen 等，2026，BMC Research Notes 19:113**；Genomes to fields 2024 maize genotype by environment prediction competition | 2014–2023训练、2024测试；表型/SNP/土壤/POWER天气/EC/元数据 | 数据发布与已解封2024产量；未给播期干预验证 | CyVerse DOI公开；正文未明确全部EC配置/率定规则 | 当前数据规模和外部验证年份；需另追EC配置 |
| **Hu、Rincent、Runcie，在线2024/卷期2025，Genetics 229(1)，iyae171**；MegaLMM improves genomic predictions in new environments using environmental covariates | 2022竞赛 G2F；4402材料、195试验的稀疏MET；用类别与天气EC的统计模型，不是APSIM专门率定 | 新环境遗传值/表型预测；未证实重模拟候选播期 | 作者分析仓库、MegaLMM包和Zenodo归档公开 | 环境留出、稀疏材料信息共享；不能把预测成绩等同播期曲线可信 |
| **Rogers、Holland，2022，G3 12(2):jkab440**；Environment-specific genomic prediction ability in maize using environmental covariates depends on environmental similarity to training data | 1918 G2F杂交种、59环境；天气时间窗口与遗传交互；非完整过程模型率定 | 跨年份/地点/材料预测，未调整播期 | 数据/代码可用性以原文availability核对；本次不声称已复现 | LO-year、LO-location、LO-hybrid 与外推域检验 |
| **Li 等，2021，Agronomy 11:674**；Application of DSSAT CERES-Maize to Identify the Optimum Irrigation Management and Sowing Dates on Improving Maize Yield in Northern China | 非G2F；2017–2019观测用于CERES品种与模型验证，长天气序列与灌溉情景 | 明确播期＋灌溉优化 | 参数与实验方法在论文；可执行项目/代码本次未确认 | 多过程观测、成熟验证与管理日期规则；参数不可直接搬到G2F |
| **Tofa 等，2020，Agronomy 10:871**；Modeling Planting-Date Effects on Intermediate-Maturing Maize in Contrasting Environments in the Nigerian Savanna: An Application of DSSAT Model | 非G2F；两玉米品种、多播期试验，CERES率定评价 | 明确不同播期响应 | 原论文实验与参数资料；一键执行代码未确认 | 播期反事实可信度需要真实多播期验证 |
| **Technow 等，2015，PLOS ONE 10:e0130855**；Integrating Crop Growth Models with Whole Genome Prediction through Approximate Bayesian Computation | 非G2F；证明性玉米CGM-WGP/ABC框架 | 遗传参数与过程模型联合预测；不是官方G2F EC重建 | 以原论文支持信息为准；不是可直接覆盖本任务的现成完整模型库 | SNP→生理参数和层级先验的理论基础 |
| **Shahhosseini 等，2021，Scientific Reports 11:1606**；Coupling Machine Learning and Crop Modeling Improves Crop Yield Prediction in the US Corn Belt | 非G2F县尺度数据；APSIM模拟变量＋ML | 作物模型变量改善产量预测；不是G2F播期验证 | 公开预印本与期刊版；专用工程配置/冻结代码需另核对 | 用过程变量辅助ML的基线；全年实况天气与预测天气的差别 |

来源按行对应：[Lopez-Cruz](https://pmc.ncbi.nlm.nih.gov/articles/PMC10616096/)、[Winn](https://doi.org/10.1002/csc2.20857)、[Washburn](https://doi.org/10.1093/genetics/iyae195)、[Chen](https://link.springer.com/article/10.1186/s13104-026-07629-5)、[Hu](https://escholarship.org/uc/item/1225h1m6)、[Rogers/Holland](https://academic.oup.com/g3journal/article/12/2/jkab440/6486423)、[Li](https://www.mdpi.com/2073-4395/11/4/674)、[Tofa](https://www.mdpi.com/2073-4395/10/6/871)、[Technow](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0130855)、[APSIM＋ML公开预印本](https://arxiv.org/abs/2008.04060)。

### 6.2 三类研究不能混为一种能力

G2F＋EC＋ML 可以提高某些跨环境预测，却不自动得到完整生育过程；环境平均物候率定可以改善阶段定位，却不等于材料特异参数；专门 15 杂交种多性状率定展示可行性，却不证明仅用散粉、吐丝和最终产量即可率定 5205 材料。

Winn 研究首次率定后在 2018 渍水环境发生明显偏差，并加入短期辐射降低的经验修正再率定。最终报告的良好拟合不能不加区分地当作完全独立跨环境验证；该经验修正也不应在本任务中按 observed yield 自动触发。[原论文 Calibration 与 Discussion](https://www.genomes2fields.org/docs/publications/csc2.20857.pdf)

本次检索**没有核实可直接拿来对 G2F 2014–2023 全部杂交种运行候选播期的 DSSAT 参数库/完整项目**；也未核实官方公开 EC 已覆盖用户设想的九个新播期。相关路线存在，但这两个具体交付物不能假定已经完成。

另外，原生天气统计EC与过程模型EC是不同对象。Rogers/Holland的五日窗口和遗传交互路线可作统计基线；MegaLMM论文还使用类别EC和278个整理天气EC，并不等于采用APSIM阶段EC。不是所有G2F“EC”都由APSIM生育阶段模拟得到。[Rogers/Holland原论文](https://academic.oup.com/g3journal/article/12/2/jkab440/6486423)、[MegaLMM原论文Methods](https://academic.oup.com/genetics/article/229/1/iyae171/7848891)

APSIM＋ML的县尺度研究明确说明模拟使用了测试年的全年天气，真实提前预测需换成预报模式并引入额外不确定性；其成绩不能直接作为小区播期决策精度。[Scientific Reports期刊版](https://www.nature.com/articles/s41598-020-80820-1)

## 7. 5205 杂交种的参数率定策略

### 7.1 为什么逐个全部自由率定不现实

每个小区两个开花性状和一个最终产量并非三个完全独立的过程约束；Pollen/Silk 相关，产量可由叶面积、RUE、籽粒汇、根区供水、N供给和成熟时长相互补偿产生。同一 Hybrid 跨环境观测数量和熟期跨度决定可识别信息，不能用总数据量替代材料级有效样本量。

“高RUE＋强缺水”和“低RUE＋充足水”可能拟合相同原播期产量，但改变播期后响应不同。因此先改善管理/土壤输入，再增加品种参数，避免让遗传系数吸收环境错误。

### 7.2 分层推进方案（本报告建议）

| 层级 | 参数策略 | 可以回答 | 不能声称 |
|---|---|---|---|
| generic maize | 所有环境单一冻结参数 | 不同环境下通用品种播期响应 | Hybrid特异最优播期 |
| 熟期组 | 用训练环境开花与已知熟期定义3–5组，组内共享主要参数 | 熟期×环境×播期的机制差异 | 已鉴定每个Hybrid全部生理机制 |
| 环境级率定 | 原播期用环境平均吐丝调整，冻结后跑候选日期 | 特定历史环境的条件曲线、旧EC重建 | 新环境部署时可使用未观测吐丝，或完全独立的环境特征 |
| Hybrid级少量参数 | 有足够跨环境观测时开放1–2物候参数，再有限产量参数 | 部分材料跨环境响应 | 仅产量即可自由辨识全部水氮/生殖参数 |
| hierarchical calibration | 材料参数围绕熟期组/遗传先验部分池化，环境管理不确定性另建层 | 稀疏数据迁移与参数不确定性 | 层级模型可凭空补出未测生理信息 |
| SNP→coefficients | 训练有可靠率定/多性状观测的材料，用SNP/双亲预测系数及区间 | 新材料生理参数迁移研究 | marker数量多就保证机制映射有效 |

对于未来预测，熟期组划分、参数优化、SNP映射必须在训练折内部完成。对于纯历史重建，可用同环境吐丝，但应标记为“观测辅助重建”，且不用其拟合效果作为留环境准确率。

### 7.3 率定顺序与损失

1. **输入固定与审计**：天气/土壤/管理、密度与含水率口径先统一。
2. **物候优先**：用散粉/吐丝日期约束发育参数；按模型定义选择主要目标，另一个作为独立诊断。未表达ASI的模型不同时自由拟合两个不同日期。
3. **成熟约束**：加入真实成熟/黑层或可信熟期先验；Date_Harvested只能作观察终点或不等式约束，不能作为成熟真值。
4. **生长与产量**：先用LAI/biomass等可得过程约束，再调整少量RUE/籽粒汇或HI类参数；只有Yield时报告参数多解和较宽区间。
5. **敏感性筛选与留出验证**：避免开放低敏感或不能辨识参数；保留可行参数集合，不仅最优单点。

概念损失可用 `L = wP×phenology_error + wY×yield_error + prior_penalty`，各观测按误差尺度归一化。不能用增加产量权重掩盖时间轴偏移。已有 CroptimizR/AgMIP 分步协议可参考，而非从零设计无约束优化。[分步率定示例](https://sticsrpacks.github.io/CroptimizR/articles/AgMIP_Calibration_Phenology_protocol.html)

## 8. 模型横向评分与选型

### 8.1 统一评分表

1–5，5分更有利。率定负担、数据缺口、计算负担和Demo难度均已反向处理。成本为模型/工程复杂度的定性判断，不是benchmark；不对总分机械排名。G×E评分指通过品种生理参数表达差异的潜力，不意味着直接支持SNP。

| 模型/实现 | G2F匹配 | 玉米成熟 | 播期模拟 | G×E | 率定易度 | 缺口小 | Python/批量 | 开放程度 | 计算轻量 | Demo易度 | 科研潜力 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| APSIM NG | 5 | 4 | 5 | 5 | 2 | 2 | 4 | 2 | 3 | 3 | 5 |
| APSIM Classic | 4 | 5 | 5 | 5 | 2 | 2 | 2 | 2 | 3 | 2 | 4 |
| DSSAT CERES-Maize | 4 | 5 | 5 | 4 | 3 | 2 | 4 | 5 | 4 | 3 | 5 |
| AquaCrop-OSPy | 3 | 4 | 4 | 2 | 4 | 3 | 5 | 5 | 4 | 5 | 3 |
| WOFOST/PCSE 8.1 | 3 | 4 | 4 | 3 | 3 | 3 | 5 | 4 | 3 | 4 | 4 |
| STICS | 3 | 4 | 5 | 4 | 2 | 2 | 3 | 4 | 3 | 2 | 4 |
| CropSyst | 2 | 4 | 4 | 3 | 2 | 2 | 2 | 2* | 3* | 1 | 4 |
| SIMPLE Python | 2 | 2 | 3 | 2 | 5 | 4 | 4 | 5 | 5 | 4 | 2 |

`*` CropSyst开放与计算评分为保守可获取性判断，证据置信度低，不代表判定其闭源或测出性能差。PCSE行按8.1能力评价；若使用简单WLP，数据负担较小但N能力减少。OSPy播期4分反映温水曲线可得、独立玉米生殖/氮链不完整。

### 8.2 每行分数的理由

- **APSIM NG**：G2F直接EC工作流提高匹配度；参数化器官、水氮和管理提高G×E/科研分；土壤/管理缺口及参数路径复杂降低率定与Demo分；CLI/容器提高批量分，自定义用途许可降低开放分；NG具体玉米机制仍随版本发展，成熟度不直接等同Classic。
- **Classic**：长期玉米和15材料率定证据提高成熟/G×E分；输入缺口与NG相近；旧构建和参数迁移降低Python/快速Demo分，新增科研主线优先NG。
- **CERES**：成熟玉米、多播期验证、六系数提高玉米/播期/率定分；完整水氮与遗传参数支持科研；缺少G2F专用可复用库和FileX转换降低匹配/Demo分；BSD引擎和Linux/Python第三方接口提高开放/批量分。
- **OSPy**：直接Python与默认玉米让Demo/接口分高；水力/ET0仍需补；CC、水分生产率与HI比完整器官/N机制少，率定负担较低，但G×E和充分利用G2F分下降；首次编译成本未实测。
- **PCSE**：原生Python、公共参数、生产水平明确提高接口/Demo分；生理同化与器官/N可拓展，但G2F专用参数和玉米密度/生殖表达需要适配；纯Python/复杂N没有可比计时，计算分只作中性估计。
- **STICS**：多年水氮/管理与玉米提高播期/科研分；参数和管理资料负担高，主要R生态与缺少G2F现成管线降低Demo；官方分离软件许可证支持开放评分。
- **CropSyst**：开发团队对系统模型与HPC能力有证据，理论科研潜力高；当前冻结源码/许可/接口未核实使落地分低，不能凭第三方同名包提高分数。
- **SIMPLE**：少参数提高率定、缺口和计算评分；冠层/生殖/N细节有限使玉米完整过程、G2F充分利用和科研扩展分低；适合基线，不能取代主线。

这些评分的来源是第4–5节逐模型链接及第6节可复用工作；分数本身为本报告判断。

### 8.3 分目标选择

| 目标 | 首选 | 次选 | 判断依据与条件 |
|---|---|---|---|
| 1–2周跑播期—产量曲线 | AquaCrop-OSPy | PCSE；已有模板经验时APSIM NG | 明确只解释温水作用；需要完整N/粒数时跳过简化原型 |
| 尽量利用G2F | APSIM NG | CERES-Maize | 现有EC路线、物候/水氮与管理；不把SNP直接当系数 |
| G×E×M论文 | APSIM NG | CERES-Maize | 分层品种参数、真实多播期验证、管理不确定性；最好双模型核查 |
| ML/surrogate | APSIM NG（标签与过程生成） | PCSE（纯Python实验） | 完整机制教师和可复用EC；surrogate先忠实近似模拟器，再验证真实产量 |
| 参数与工程最低成本 | OSPy；更粗基线可SIMPLE | PCSE简单WLP | 低成本伴随机制和输出减少，不能只看最终曲线好看 |

## 9. 可执行实施蓝图：Phase 0–5

以下是后续实施规格，不是本次已执行结果。

### Phase 0：数据核验与资产冻结

交付 `data_audit`、`field_mapping`、`assumption_register` 和版本清单。具体应检查：

| 检查 | 统计/核验方式 | 对实验的处理 |
|---|---|---|
| Date_Planted | 按Env/Experiment/Treatment列唯一日期、最早最晚、分布与异常 | 同Env多播期保留子管理单元，不先平均 |
| 同Location跨年 | 以稳定地点/田块ID统计DOY变化 | 分开田块迁移与年际天气，不直接作播期因果证据 |
| 同Hybrid跨环境 | 有效环境数、年份数、熟期观测数和连通性 | 决定是否能Hybrid率定；稀疏材料部分池化 |
| Pollen/Silk | 非缺失率、成对率、绝对日期、ASI和异常 | 对齐50%观测与模型阶段；记录异常过滤规则 |
| 土壤 | 有样环境、深度/多样本、剖面水力参数是否存在 | 不能只报“有soil列”；按模型需求核查 |
| 天气 | Env×Date唯一性、闰日、逐日连续、单位、缺测、负降水、Tmin>Tmax | 使用全年的扩展区间；填补来源/比例记录 |
| Management | 灌溉、施肥、播深、行距、前茬、残茬的事件完整性 | 雨养优先；未知管理另列假设，不混作已知处理 |
| EC | 来源版本、实际播种日、参数、聚合代码与表头 | 尝试小样本原配置复建；配置不可得则新建EC |
| Yield/Density | 水分基准、stand测量面积与时间、单位 | 统一产量干物质和有效密度；留成苗敏感性 |

本报告不提供这些本地缺失率的虚构数字。公开发布规模只能作数据版本参考。

### Phase 1：最小可运行过程模型

**默认主线选 APSIM NG。** 最小5地点×3年，数据允许再扩10地点×5年。选美国地点、已确认雨养、天气连续且土壤与开花观测较好的子集；兼顾纬度/干湿差异，不仅挑最高产环境。通用品种、一个有效株密度、九个偏移 `[-20,-15,-10,-5,0,5,10,15,20]`。

**固定实验条件。** 同一Env内天气、土壤、品种、目标密度、播深、行距、起点状态一致。共同模拟起点设为最早候选播期前90天，即 `t_start=d0−110`；同日起始水/N/残茬后，每个分支完整跑到其播期并继续生长。不要每个播期都在 `d−90` 用相同FractionFull重置，否则前史不同。

**管理政策默认。** 雨养不灌溉；有实际施肥记录则固定原日历日期、剂量和形式，并检查早播是否在施肥前。缺失施肥时单列一个明确的合成“播种时固定N量”处理，命名为播期＋播种施肥时间联动的政策，不宣称纯播期干预；若要纯日期干预，补充固定日历N处理作对照。阶段触发灌溉/追肥允许作后续独立政策，规则和总量/触发记录不能省略。

**初始化与敏感性。** 初始可利用水50%只作起始假设；初始矿质N与播种施肥分别配置。最小可增加可利用水25/50/75%的三水平敏感性；N水平依当地可信资料或范围设定，不能不经核对把MAIZE-HUB的200直接当初始NO3。对完全未知管理只报条件模拟。

**模拟终点。** 同Env各分支采用相同日历截止，优先覆盖最晚播期后240天；如发生跨年须补天气。原播期重建另报告原Date_Harvested时的状态；候选优化以生理成熟产量为主要指标，另加共同可收获截止、霜冻/未成熟等可行性标签。未成熟不输出正常终产量；记截尾或失败，保留截止时生物量，不把最后一天Grain.Wt误当成熟产量。

**输出接口（建议而非官方路径）。**

| 表 | 最小字段 |
|---|---|
| scenario | Env、Year、Location、management_unit、cultivar_id、planned/actual_sowing_date、offset、policy、init_id、model/template/parameter hash |
| daily | date、stage、LAI、aboveground_biomass、grain_biomass、root_depth、soil_water、ET、water/N限制指标 |
| summary | emergence/flowering/maturity日期、原收获日状态、成熟biomass、dry_yield、status、termination_reason |
| stage_ec | 阶段起止、阶段天数、weather_mean/sum、biomass_end、soil_water_mean、stress_days/integral |

最小必须交付 flowering、maturity、biomass、水分限制、yield 和曲线；未被所选模型表达的输出标“不可用”，不由字段名伪造。grain g/m²转Mg/ha乘0.01；模型g/plant等其他单位另换算，不统一套用。

**配置蓝图（声明式说明，不是可执行 `.apsimx` 文件）。**

```text
Engine: APSIM Next Generation <冻结版本>
Template: Maize.apsimx <冻结内容hash>
Clock: d0-110 到共同截止日期
Weather: 全区间逐日 Tmax/Tmin/rain/radn + 选定ET所需变量
Soil: 冻结层厚、LL/DUL/SAT/BD/根区/水氮与有机碳参数
Initial state: 在共同起点设SW/NO3/NH4/残茬
Cultivar: 单一generic；不按新播期重新率定
Sowing: d0+offset，记录实际事件；固定population/depth/row spacing
Management: 已知固定日历事件；合成管理另设policy标签
Report: end-of-day状态 + 物候/播种/成熟/终止事件
Harvest: 原记录日对照 + 成熟产量/共同截止可行性
```

如果采用CERES，则对应WTH、SOL、CUL/ECO/SPE、FileX的初始条件/播种/事件和Simulation Controls；PCSE对应ParameterProvider、WeatherDataProvider、AgroManagement，并使用sowing起始类型；OSPy对应Soil/Crop/InitialWaterContent/IrrigationManagement和天气ET0。九个播期都需新实例与完整重运行，不能在同一实例上改日期后延续旧状态。

**一期验收。** 曲线之外，至少画原播期与两个极端播期的LAI/biomass/SW和阶段对照；实际播期符合设定、阶段顺序合理、无天气截断、产量单位正确。峰值可在边界、曲线可不平滑，不强迫拟合钟形曲线。物候或产量误差大时解释缺口而非立即扩大规模。

### Phase 2：物候和产量率定

先用训练环境的散粉/吐丝拟合少量物候参数，冻结后留年份/地点验证；成熟热时间用外部约束与区间。通用品种模型可与环境均值比较，但不能与所有小区遗传差异逐点比较后声称解释Hybrid。

接着增加熟期组、有限生长/产量参数，采用小区观测误差或环境BLUE/均值的不确定性权重。物候报告MAE/RMSE/偏差（天），产量报告RMSE/MAE/偏差与相对误差；相关系数不能替代尺度准确性。

冻结测试划分后再率定，测试环境Pollen/Silk/Yield不能参与构造其预测用参数或选择模型。材料足够时再做Hybrid部分池化和SNP映射。验收不预设缺乏依据的统一精度阈值；是否达到农学用途由观测误差和独立实验预先约定。

### Phase 3：批量情景与重新生成EC

先跑环境×9播期×通用品种；增加熟期组/可靠Hybrid参数后才扩有效组合。缓存天气/土壤/模板，不在每个情景联网下载。分批并行，隔离目录，能断点重试并生成失败表。

新EC由新阶段边界生成：温雨辐射/VPD的mean/sum、超阈值日数、开花前后暴露、土壤可利用水、水/N限制积分及器官生长；mean、sum、end明确分开。选择“参考通用品种环境EC”和“材料特异过程EC”两套名称，后一套是G×E×M过程特征，不称纯环境特征。

最终数据集接近 `[Env,Year,Location,cultivar/Hybrid,SowingDate,Phenology,EC,Stress,Yield]`，并加管理政策、初始化、参数样本、模型版本、成熟状态。只有通用品种时Hybrid为空/不适用，而非把通用曲线伪装成每个材料响应。

### Phase 4：ML 与 surrogate

明确两个任务：

- **模拟器surrogate**：天气/土壤/参数/播期/政策 → 模拟产量及物候/胁迫。标签是 `Y_sim`，成功标准是对未见环境、播期和参数的模拟器保真度。
- **真实产量融合/偏差订正**：SNP/土壤/播期/可用天气/模拟EC → `Y_obs` 或 `Y_obs−Y_sim`。需要独立实测验证；原播期拟合残差不能证明候选播期偏差也相同。

先RF/LightGBM/XGBoost基线，再考虑TabularModel或多输出网络。若surrogate输入完整阶段EC，这些EC仍需过程模拟，不能宣传节省整个模拟成本；想完全替代引擎，输入应是外生驱动与品种系数，输出联合近似阶段/EC/产量。

随机行划分会让同Env相邻播期/重复小区同时进训练和测试。默认做留年份、留地点、留Hybrid、联合留出；新增候选日期还测离训练日期的外推，并报告预测最优日期偏差、窗口一致性和regret `max_d Y_sim(d)−Y_sim(d_hat)`。用于物候率定/EC生成的测试表型也属于泄漏。

历史最优播期依赖全年实际天气，是事后分析；未来播期推荐只能用当时可得预报或历史天气分布，不能把未来实况天气/后期实测表型当可用输入。

### Phase 5：最优播期与窗口

在成功且农学可行的候选日期集合D内：`d*=argmax Y(d)`；`W_q={d∈D : Y(d)≥q×max_D Y(d)}`，q=0.90/0.95。若D无成功情景或最大产量不正，不报正常窗口。多个峰值默认报告全部并列日期及对应区间；不把无依据插值解释为日精度最优。

九个日期是5天网格，90/95%窗口先报告离散集合；非连续则分别报告，边界峰值标记“搜索范围内最优，真实最优可能在范围外”。需要日精度时再对峰值附近1天网格重模拟。

输出 early/late loss `Y(d*)−Y(d)` 和相对损失，并同时报告相对原播期 `Y(d)−Y(d0)`。参数、土壤、管理/初始化、天气集合与模型结构不确定性分别呈现；窗口阈值90/95%不是统计置信度。

限制因子依据水/N限制日数、阶段辐射/温度暴露与资源供需诊断，辅以合理对照情景（补水/改变N/不同熟期参数）验证；特征重要性不能独自证明因果。对于长期地点播期推荐，比较跨年平均、低分位、未成熟概率与最坏损失，不只挑单一年最高产日。

## 10. 从“能跑”到“农学可信”的检查路线

| 层级 | 必须完成 | 可对外表述 |
|---|---|---|
| 1：程序可运行 | 官方示例可重现；九情景实际播种、日期/单位/截尾正确；过程输出一致 | “已建立条件模拟与播期响应原型” |
| 2：原播期独立验证 | 土壤/管理核验；训练折率定；留年/地点/材料物候与产量验证；敏感性/多解报告 | “对所验证材料与环境，原管理条件下预测有证据支持” |
| 3：播期响应可信 | 同环境多播期对照或独立外部多播期数据；开花/成熟/生长过程和响应方向/幅度验证；模型结构与可行性检查 | “在验证范围内播期响应及适宜窗口具有农学支持” |
| 4：未来决策 | 预报/历史天气分布、田块状态与实施限制、跨年风险和外推域评估 | “条件与风险已说明的播期建议” |

具体测试情景包括：零偏移重复运行一致；单一日期干预时固定输入hash一致；早播未出苗/晚播未成熟正确记录；原收获早于模拟成熟不混作正常成熟产量；雨养不隐含自动灌溉；初始N与播种N不重复计入；同Env多Treatment不误合并；天气缺日/闰日/跨年正确；有多峰/边界峰时窗口定义正确；测试表型不进入率定或EC构建。

以上不是本次运行测试结果，而是后续验收清单。本次文献核验不能消除田块实测状态和多播期验证的缺口。

## 11. 最后八个结论

1. **当前G2F足以直接开展吗？** 足以搭建并筛选有假设的子集实验；不足以仅靠现有整理表、无需外部输入就为全部Hybrid给出农学可信播期最优解。优先补土壤剖面、管理和初始状态。
2. **最推荐模型？** APSIM NG，用冻结玉米模板和明确水氮/管理配置；充分利用现有G2F EC路线但重新生成候选播期过程。
3. **第二推荐？** DSSAT CERES-Maize，用作第二过程模型与响应鲁棒性核查。仅追求近期水分型Python曲线时OSPy更省工程成本。
4. **最大数据缺口？** 动态初始水/N、分层土壤水力/根区和施肥/灌溉事件；另一个决定反事实可信度的缺口是同环境多播期及成熟/生物量观测。
5. **最大率定风险？** 开花和最终产量不足以唯一识别大量参数；环境输入误差被品种参数吸收，或测试吐丝参与EC生成造成泄漏，原播期拟合很好但新播期曲线错误。
6. **老师近期检查最小范围？** 5地点×3年×9播期×单通用品种；完整输出开花/成熟/生物量/水分限制/产量与过程图，原播期观测对照，明确失败和假设。不要为了展示“5205品种”复制通用产量。
7. **可复用与必须重实现？** 可复用原始连接关系、全年天气、土壤获取思路、MAIZE-HUB流程与EC命名、公开Classic参数作为先验线索；必须冻结/适配NG参数、建立共同初始化与管理政策、每个播期重跑、重聚合EC、加失败/不确定性和无泄漏验证。旧EC与旧品种参数都不能无条件直接搬用。
8. **能跑到可信差在哪？** 能跑是输入齐全且过程/单位自洽；原播期可信要独立物候与产量验证；播期最优可信还要独立多播期响应与成熟/胁迫机制证据。G2F＋过程模型是合理研究路线，这三个目标应分别验收。

## 附录：优先资源清单与未解决事项

### A. 首先访问的资源

| 资源 | 用途 |
|---|---|
| [G2F Resources](https://www.genomes2fields.org/resources/) / [Publications](https://www.genomes2fields.org/publications/) | 年度DOI、竞赛版本与原始文献 |
| [2024竞赛发布说明](https://link.springer.com/article/10.1186/s13104-026-07629-5) / [数据DOI](https://doi.org/10.25739/78mn-4394) | 当前2014–2023数据出处与测试数据 |
| [MAIZE-HUB](https://github.com/QuantGen/MAIZE-HUB) / [EC流程ZIP](https://github.com/QuantGen/MAIZE-HUB/blob/main/data_curation_and_ecov.zip) | R天气/土壤/APSIM与EC工作流 |
| [Winn正文](https://www.genomes2fields.org/docs/publications/csc2.20857.pdf) / [补充材料入口](https://acsess.onlinelibrary.wiley.com/doi/abs/10.1002/csc2.20857) | Classic参数Table2、土壤表、敏感性与率定限制 |
| [APSIM NG文档](https://docs.apsim.info/docs/) / [源码](https://github.com/APSIMInitiative/ApsimX) / [Maize](https://jenkins.apsim.info/validation/Maize) | 版本、模板、器官过程与输出路径 |
| [DSSAT源码](https://github.com/DSSAT/dssat-csm-os) / [输入数据与参数](https://github.com/DSSAT/dssat-csm-data) | Linux引擎与作物/天气/土壤示例资产 |
| [DSSAT IXIM](https://dssat.net/csm-ixim/) | ASI、授粉热胁迫与粒数机制扩展；不要混写为CERES能力 |
| [DSSATTools](https://github.com/daquinterop/Py_DSSATTools) | 当前Python FileX/run_treatment集成；先查版本与许可 |
| [AquaCrop官方核心](https://github.com/KUL-RSDA/AquaCrop) / [OSPy](https://github.com/aquacropos/aquacrop) | 分别核对官方Fortran和Python移植能力 |
| [PCSE](https://github.com/ajwdewit/pcse) / [WOFOST参数](https://github.com/ajwdewit/WOFOST_crop_parameters) | Python生产水平、玉米参数和管理 |
| [STICS下载](https://stics.inrae.fr/eng/download) / [SticsRPacks](https://github.com/SticsRPacks) | 核心、R文件/运行/率定接口与许可证 |
| [MegaLMM分析代码](https://github.com/hh622/MegaLMM_New_Environments_Prediction_GenomesToFields) / [归档](https://zenodo.org/records/13787618) | 稀疏MET与新环境预测对照 |
| [NRCS SSURGO](https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo) / [NASA POWER](https://power.larc.nasa.gov/) | 外部驱动资产，保存版本和空间匹配信息 |
| [IITA播期模拟数据](https://data.iita.org/dataset/dssat-maize-simulated-sowing-dates-for-nigeriafor-the-period-1981-2019) | 非G2F播期情景数据范式；模拟数据不能替代实测验证 |

### B. 本次未确认且不应被省略的事项

- 本地文件与CyVerse公开版本的内容一致性、各字段真实缺失率和同Env多播期比例。
- 2024竞赛全部EC的生成版本、冻结模板、参数、实际播期、管理、初始化及新环境物候参数来源。
- Winn全套可执行Classic项目/人工优化代码与向NG迁移后的等价性；论文公开参数不等于一键复现。
- CropSyst当前完整官方引擎源码/许可与Linux/Python接口；不由第三方同名包推定。
- 相同硬件设置下各模型单次成本、十万级实测吞吐量和官方维护容器的完整清单。
- G2F全材料可直接复用的DSSAT参数库，以及独立多播期实测验证资源。

这些未确认项不会阻止通用品种子集原型，但决定哪些结果只能作条件模拟，哪些可以升级为可信的材料播期推荐。
