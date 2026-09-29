# G2F 数据与模型输入映射

原始数据覆盖审计：2026-09-23；DSSAT 项目映射核对：2026-09-27。
范围：本仓库 `data/` 下的实际文件。
返回[文档目录](README.md)。

## 1. 文件与覆盖范围

下面的行数为本次只读解析 CSV 的数据行数，不含表头；
环境数为 `Env` 唯一值数，不等于有效校准样本数。
训练文件位于 `data/Training_data/`，测试文件位于 `data/Testing_data/`。

| 类别 | 训练文件 | 训练行数 / 环境数 | 测试文件 | 测试行数 / 环境数 |
| --- | --- | --- | --- | --- |
| 性状 | `1_Training_Trait_Data_2014_2023.csv` | 173,960 / 272 | 无对应完整性状表 | — |
| 元数据 | `2_Training_Meta_Data_2014_2023.csv` | 272 / 272 | `2_Testing_Meta_Data_2024.csv` | 23 / 23 |
| 土壤化验 | `3_Training_Soil_Data_2015_2023.csv` | 186 / 186 | `3_Testing_Soil_Data_2024.csv` | 21 / 16 |
| 全年天气 | `4_Training_Weather_Data_2014_2023_full_year.csv` | 98,236 / 269 | `4_Testing_Weather_Data_2024_full_year.csv` | 7,245 / 23 |
| 生长季天气 | `4_Training_Weather_Data_2014_2023_seasons_only.csv` | 51,098 / 269 | `4_Testing_Weather_Data_2024_seasons_only.csv` | 4,591 / 23 |
| EC 特征 | `6_Training_EC_Data_2014_2023.csv` | 241 / 241 | `6_Testing_EC_Data_2024.csv` | 22 / 22 |
| 提交模板 | — | — | `1_Submission_Template_2024.csv` | 10,057 / 23 |
| 观测产量 | 已在训练性状表内 | — | `7_Testing_Observed_Values.csv` | 9,486 / 22 |

注意：测试提交模板覆盖 23 个环境，而产量观测只覆盖 22 个环境。
模板有一行，不代表对应标签存在；缺失值不能当作零产量。

2024 产量标签已由标准化代码按 `(Env, Hybrid)` 与提交模板外连接，
进入标准化观测表；缺失标签仍保留为缺失。当前记录的 demo/refined
评估年份是 2023，不因加载了 2024 标签就表示已完成 2024 评估。
今后若将 2024 用作独立测试集，应在选参前冻结其用途。

其他本地文件：

| 文件 | 已核对内容 | 当前使用状态 |
| --- | --- | --- |
| `Training_data/5_Genotype_Data_All_2014_2025_Hybrids.vcf` | 文件存在，文件名标称 2014–2025 基因型 | 未接入；本次未审计位点、样本或缺失率 |
| `Training_data/5_Genotype_Data_All_2014_2025_Hybrids_numerical.txt` | 文件存在 | 未接入；需核实编码和样本对应关系 |
| `Training_data/key_inbreds_G2F_2014-2025.txt` | 文件存在 | 未接入；需核实亲本映射 |
| `train_merged_data.csv`、`test_merged_data.csv` | 各 887 列的合并表 | 不在当前 `SOURCE_CATALOG`；生成来源待核实 |
| `train_6D_features.csv`、`test_6D_features.csv` | 各 24 列，含 `Prec/Tmax/Tmin/Radn/GDD/SOM` 等 | 不在当前源目录；聚合时段和生成方式待核实 |

基因型文件名中的 2025 不代表本地同时具备 2025 年气象或性状观测。
上面四个合并/特征文件也不因位于 `data/` 就自动成为独立原始观测。

## 2. 性状、管理与观测

| 原始字段 | 含义 / 单位 | 当前 SnowWindow 用法 | APSIM / DSSAT 接入意义或限制 |
| --- | --- | --- | --- |
| `Env`、`Year`、`Field_Location` | 环境、年份、站点标识 | 关联环境和划分年份 | 复用环境标识 |
| `Experiment/Replicate/Block/Plot` | 试验及小区结构 | 连同 `Env` 组成训练小区自然键 | 避免合并不同处理或重复计数 |
| `Hybrid`、`Hybrid_orig_name`、`Hybrid_Parent1/2` | 杂交种及亲本标识 | 保留原始信息；按 Hybrid 聚合代表玉米观测 | 不能直接转换成模型品种参数 |
| `Date_Planted` | 播种日期 | 建立管理单元和实际播期模拟 | 需配置实际播种动作，并记录实际触发日期 |
| `Date_Harvested` | 收获日期 | 保存、聚合为观测信息 | 收获不等于生理成熟，不宜直接校准成熟积温 |
| `Pollen_DAP_days` | 播种至散粉天数，d | 校准观测 `pollen_dap` | 应匹配对应物候事件，不能混同吐丝 |
| `Silk_DAP_days` | 播种至吐丝天数，d | 标准化保存 | 可用于物候验证；需核实模型事件定义 |
| `Yield_Mg_ha` | 给定含水率口径的产量，Mg/ha | 派生 `dry_yield_mg_ha` | 比较三种模型前统一干重口径 |
| `Grain_Moisture` | 原始籽粒含水率字段 | 保留；当前干重转换不逐行使用此列 | 先查清产量是否已标准化，避免重复校正 |
| `Stand_Count_plants`、`Plot_Area_ha` | 小区株数和面积 | 推导实现密度；管理单元内过滤后取中位数 | 株数观测未必等于播种密度，可能受出苗和死亡影响 |
| `Plant_Height_cm`、`Ear_Height_cm` | 株高、穗位高，cm | 尚未作为当前校准目标 | 可作附加验证，但先确认模型可比变量 |
| `Root_Lodging_plants`、`Stalk_Lodging_plants` | 根倒伏、茎倒伏株数 | 尚未显式模拟倒伏过程 | 可标注异常环境；不能据此声称模型已模拟倒伏 |
| `Twt_kg_m3` | 容重，kg/m³ | 尚未用于校准 | 不等于籽粒干物质量或单粒重 |

本次训练表非空计数：产量 164,921；散粉 134,339；吐丝 131,866；
株数 156,765；籽粒含水率 164,608。这里仅剔除空白、NA、NaN、null；
尚未叠加数值有效性、管理、土壤、气象和年份筛选。

当前代表玉米观测的聚合方式是：管理单元内先求各 Hybrid 的有效小区均值，
再对 Hybrid 均值等权平均。结果代表管理单元内的杂交种集合，
不是单一品种响应，也不是直接对全部小区等权平均。
依据：[标准化代码](../src/snowwindow/data/normalization.py)。

训练管理单元键为 `Env__Experiment__planting_date`，测试侧使用
`Env__Experiment_Code__planting_date`。同一环境可有多个试验或播期，
所以管理单元数不等于环境数。当前键未额外纳入元数据中的自由文本
`Treatment`；若后续识别出同键下的不同水肥处理，需要扩展键并重新审计，
不能默认现有聚合已经分离所有处理。

当前干重转换：

```text
dry_yield_mg_ha =
    yield_at_supplied_moisture_mg_ha × (1 - grain_standard_moisture_fraction)
```

当前配置采用 `grain_standard_moisture_fraction = 0.155`。
这是项目的产量口径假设；需持续核对数据发布说明是否支持全部年份。
不要把它改写为“每条记录均已证实为 15.5% 含水率”。

元数据另有坐标、`Irrigated`、前茬、耕作方式、处理名称和问题备注。
当前代码使用坐标、灌溉状态与严重问题标记等信息；前茬和耕作文字
尚未转换为 APSIM 或 DSSAT 的实际管理事件。`Irrigated` 不是逐次
灌溉日期与水量，
当前文件也没有统一的结构化施肥日程。

## 3. 逐日天气

三种模型均应使用逐日驱动，不应把生长季汇总特征直接当成日值。

| G2F 字段 | 当前项目单位 | AquaCrop-OSPy | APSIM 常见映射 |
| --- | --- | --- | --- |
| `Date` | `YYYYMMDD` | `Date` | 日期或 `year/day` |
| `T2M_MIN`、`T2M_MAX` | ℃ | `MinTemp/MaxTemp` | `mint/maxt` |
| `PRECTOTCORR` | mm/d | `Precipitation` | `rain` |
| `ALLSKY_SFC_SW_DWN` | MJ/m²/d | 用于计算 ET₀ | `radn` |
| `RH2M` | % | 用于计算 ET₀ | 如需水汽压，按所选模块转换 |
| `WS2M` | m/s | 用于计算 ET₀ | 如启用相应输入，映射风速 |
| `PS` | kPa | 用于计算 ET₀ | 按目标变量要求转换，不能混用 kPa/hPa |
| `T2M/T2MDEW/T2MWET/QV2M` | 见数据字典 | 原始附加气象信息 | 按具体研究目的核对 |
| `GWETTOP/GWETPROF/GWETROOT` | 当前字典记为 fraction | 未作为实测分层初始含水量 | 定义、土层和单位须核实，不能直接替代 θ |
| `ALLSKY_SFC_PAR_TOT` | 当前字典记为 W/m² | 非当前核心驱动 | 不等于 `radn`，时间积分和光谱口径不同 |
| `ALLSKY_SFC_SW_DNI` | MJ/m²/d | 非当前核心驱动 | 不直接替代总短波辐射 |

单位依据：[源目录与单位定义](../src/snowwindow/data/sources.py)；
ET₀ 与实际输入转换依据：[AquaCrop 适配器](../src/snowwindow/models/aquacrop/adapter.py)。
APSIM 和 DSSAT 已有本地适配器；上表的 APSIM 列描述常见变量语义，
不是当前六环境模拟对每个变量都已完成接入。

本次 [DSSAT 适配器](../src/snowwindow/models/dssat/adapter.py)实际读取
四个逐日字段，数值单位不需再转换：

| G2F 标准化字段 | DSSAT `.WTH` 字段 | 单位 |
| --- | --- | --- |
| `Date` | `@DATE`，两位年份加三位年积日 | 日期代码 |
| `ALLSKY_SFC_SW_DWN` | `SRAD` | MJ/m²/d |
| `T2M_MAX` / `T2M_MIN` | `TMAX` / `TMIN` | ℃ |
| `PRECTOTCORR` | `RAIN` | mm/d |

`RH2M`、`WS2M`、`PS` 等保留在标准化天气记录中，但**没有**被
这版 DSSAT `.WTH` 生成器传入。适配器检查每个模拟日都有唯一一条
天气记录、数值有限、最低温不高于最高温、降雨与辐射非负。

已核对的覆盖限制：

- 训练全年天气缺少 `TXH2_2015`、`TXH2_2016`、`TXH2_2017`。
- 测试全年天气只有 2024-01-01 至 2024-11-10，共 315 天/环境；
  2024-07-12 至 2024-07-14 另有核心变量缺测。文件名不能证明全年完整。
- 跨年播期模拟还需要下一年的连续驱动；不能拼接其他站点、
  重复当年天气或把缺测填零而不说明。
- 当前源目录显式排除 `seasons_only` 文件作为模型输入。
- 六环境演示扫描使用缓存的同坐标 NASA POWER 补充驱动；
  这与竞赛文件的覆盖审计是两条不同的数据路径。
- DSSAT 六环境扫描同样使用上述跨年补充驱动；4,380 条模拟均成熟，
  不证明 2024 测试文件已补全，也不代表非实际播期已有观测。

证据：[refined 数据审计](../outputs/experiments/g2f_aquacrop_refined/audit/data_audit.json)
及[演示报告](../outputs/experiments/g2f_demo/report/report.md)。

## 4. 土壤能够提供什么

化验表包含 `E Depth`、pH、盐分、有机质灼失量
`Organic Matter LOI %`、`Nitrate-N ppm N`、P/K/Ca/Mg 等化学指标，
以及 `% Sand/% Silt/% Clay` 和 `Texture`。
训练表 186 行中，有机质 178 行非空、硝态氮 169 行、
砂/粉/黏粒各 162 行；测试表 21 行中，有机质与硝态氮各 21 行、
砂/粉/黏粒各 20 行。存在化验值不代表具有完整分层剖面。

当前标准化显式提取深度原值、质地、pH 和颗粒比例，其余化验信息保留于
`raw_values`。土壤剖面由颗粒比例分类或质地查表得到，缺失时使用默认土；
AquaCrop 适配器当前只支持一个均质土层，默认深度 2 m、
内部计算分区 0.1 m。这是模型假设，不是 G2F 测得的 2 m 剖面。

APSIM 水氮模拟通常还需补齐或有依据地估计：

| 缺口 | 为什么不能直接从当前化验表得到 |
| --- | --- |
| 分层厚度、容重、AirDry/LL15/DUL/SAT | `E Depth` 是采样字段，不能直接充当模型各层边界 |
| 水分输运、LL/KL/XF 等根系取水参数 | 质地名称不能唯一确定这些参数 |
| 模拟起始日分层含水量 | 化验表未提供完整初始水分状态 |
| 分层有机碳及碳库参数 | LOI 有机质不等于有机碳，更不等于碳库分配 |
| 起始 NO₃⁻、NH₄⁺ | 单次硝态氮样品不等于播前完整矿质氮剖面；本表无统一 NH₄⁺ 列 |
| 氮素总量转换 | ppm 转 kg/ha 需要容重、层厚及明确采样口径 |
| 施肥、残茬、前茬状态 | 元数据中的文字尚不足以自动构成连续水氮管理日程 |

因此，对 APSIM 而言，当前更明显的增量工作是土壤水氮和管理参数化。
“字段存在”“已标准化”“已进入模型”“已验证”需分别记录。
对 DSSAT 亦然：当前固定使用官方通用深砂壤土 `IB00000007`，
没有根据 G2F `% Sand/% Silt/% Clay` 或硝态氮化验逐站拟合
`SOIL.SOL` 剖面；参考初始土壤水氮和播期 120 kg N/ha 施肥
不应误称为实测条件。详情见[DSSAT 运行指南](dssat.md)。

## 5. EC 与基因型的使用边界

EC 训练/测试表均有 655 列，含阶段特征以及
`biomass_p…`、`yield_p…`、`LAI_p…`、`FlowNO3_p…`、`LL__1` 等字段。
目前只确认这些列存在，未确认每列的生成模型、参数、单位、时段、
是否用到了目标观测，以及预测时能否获得。

当前 [SOURCE_CATALOG](../src/snowwindow/data/sources.py) 将 EC 表标记为
`excluded_from_model_inputs`。在核实来源前，不把这些列当作独立实测
生物量、LAI 或可直接复用的 APSIM/DSSAT 土壤参数，也不用于验证
生成它们的模型。
后续若用于统计模型，另做预测时信息可用性与目标泄漏审计。

基因型可以作为后续“遗传信息 → 生理参数”研究的数据候选，但当前
三种过程模型都没有从本地 SNP 文件自动推导品种参数的项目实现。
这需要独立映射方法、训练集和外部验证。

## 6. 数据快照与更新方式

现有 refined 审计覆盖 295 个训练/测试环境：269 个使用天气站坐标，
10 个使用田块角点中心，16 个缺坐标；灌溉状态为确认灌溉 26、
确认雨养 45、未知 224。默认土 117 个、颗粒比例分类 177 个、
质地查表 1 个。这些是已有审计产物的统计，不代表模型运行成功数量。

源文件 SHA256 和标准化产物指纹保存在
[prepare manifest](../outputs/experiments/g2f_aquacrop_refined/manifests/prepare_manifest.json)。
上述 refined 文件覆盖统计取自早期审计，更新 DSSAT 映射时未重审
全部原始文件；DSSAT 六环境校准及扫描已单独运行。数据更换后，
应重新生成审计并更新本页；
命令会写入对应实验目录，保留历史结果时请先使用新的 `experiment_id`：

```bash
.venv/bin/python -m snowwindow audit --config configs/g2f_aquacrop_refined.yaml
.venv/bin/python -m snowwindow prepare --config configs/g2f_aquacrop_refined.yaml
```

后续每增加一类数据，补充：文件/版本、字段与单位、空间和时间尺度、
覆盖与缺失、是否实测、转换规则、模型用途、来源指纹以及仍待核实的内容。
