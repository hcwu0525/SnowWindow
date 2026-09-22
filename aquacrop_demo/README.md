# G2F AquaCrop-OSPy 快速实验

所有命令在 SnowWindow 项目根目录执行。原始 `data/` 只读；新输入、输出和日志写入 `outputs/aquacrop_demo/`。

## 环境

本次已经创建 `.venv`（Python 3.10.20）并安装 AquaCrop-OSPy 3.1.0。激活与验证：

```bash
source .venv/bin/activate
python --version
python -m pip check
```

在另一个 macOS ARM64 环境重建时，可用已有 uv 创建 Python3.10虚拟环境，然后安装冻结依赖：

```bash
uv venv --python 3.10 --seed .venv
.venv/bin/python -m pip install -r requirements-aquacrop.lock.txt
```

依赖版本锁文件来自本次成功安装，不是跨平台二进制镜像或带包哈希的供应链锁。Linux 需重新检查对应版本能否安装，通过示例和测试后使用，不能直接声称已验证。

## 运行

```bash
.venv/bin/python -m aquacrop_demo all
.venv/bin/python -m pytest -q
```

`all` 顺序运行 `smoke → prepare → baseline → calibrate → validate → scenarios → report`。首次 prepare 需要访问 NASA POWER；已缓存完整原始天气后可离线重跑。配置入口 `aquacrop_demo/config.yaml`，可用 `--config` 指定副本。

也可分阶段运行，例如：

```bash
.venv/bin/python -m aquacrop_demo scenarios
.venv/bin/python -m aquacrop_demo report
```

进程数默认3。设 `workers: 1` 可串行调试；不会改变模型机制，但因配置进入缓存哈希，会产生新的任务记录。适配器、模型源码、天气、参数、管理单元和配置变化均会生成新缓存键。失败任务保留错误与状态，不能手工改成正常成熟。

## 结果和默认假设

- 第一条曲线：`milestone_a.csv`，INH1_2023，默认通用玉米。
- 主结果：`结果报告.md` 与 `figures/`。
- 机器可读：`scenario_summary.csv`、`planting_windows.json`、`validation_metrics.csv`。
- 逐日过程：`runs/<run_id>.parquet`；参数/土壤对应 `.crop.json`、`.soil.csv`。校准与敏感性仅保存汇总以控制体量；基础九播期保存逐日输出。
- 输入来源：`selection_manifest.json`、`weather_raw/*.json`、`weather_manifest.json`、`original_vs_refreshed_weather.csv`。

固定密度75,000 plants/ha；2 m均质质地土壤；1.9 m最大根深及0.1 m底部缓冲；1月1日50%总可利用水量初始化；雨养；无地下水/覆盖物/前茬。年度观测先按材料平均重复，再对材料等权平均。选定三个有至少两年明确雨养记录的地点，以最大主试验原始小区数选择代表性管理单元。主率定2022、主测试2023；留地点验证各折独立率定。

OSPy3.1.0天气数组必须为 `MinTemp, MaxTemp, Precipitation, ReferenceET, Date`。模型ET0下限0.1 mm/day；保存FAO-56计算值供追溯。产量观测15.5%含水率，干物质转换系数0.845；不能把库内Fresh yield直接当竞赛口径。

`insufficient_thermal_time` 表示模型在初始化前因年内热时间不足拒绝运行，产量缺失；`crop_died` 表示模型死亡终止，可能已有产量，但不属于正常成熟候选。90/95%窗口只用正的正常成熟情景；不连续日期集合分别报告，边界峰不外推。

仅用于快速机制流程验证。缺少实测多播期对照时，不把窗口当作生产推荐；开花时间是HIstart热时间代理，不是独立散粉/吐丝过程。更多定义与实际限制见结果报告。

## 第二版：细化率定与全年每日播期

运行：

```bash
.venv/bin/python -m aquacrop_demo.optimize
```

输出位于 `outputs/aquacrop_annual/`，第一版结果保留。六个环境固定，不自动新增地点或年份。复用第一版核验过的全年天气；不下载新天气。每套参数扫描全年365个候选日，晚于成熟可行日期的候选可能在引擎初始化时被拒绝，保留原因与空产量。12月31日播种明确标记日历不支持，不跨年。

第二版增加局部细网格、2022年内留地点稳定性检查及HI0敏感性带。主参数只用2022年训练数据选择，2023年评估不得影响选择。敏感性带不是统计置信区间。达到参数边界时不自动扩大范围。所有情景均雨养且使用1月1日共同初始水分，播种日不重置水分。

可重复执行同一命令，单次模拟复用内容指纹缓存。若进程中断，重跑会恢复已完成模拟。恢复生成报告可使用：

```bash
.venv/bin/python -c "import yaml; from aquacrop_demo.annual_report import build; build(yaml.safe_load(open('outputs/aquacrop_annual/config.yaml')))"
```

新增接口：`Experiment.run(..., planting_date='2023-04-20')`；提供显式日期时该日期决定情景，`offset_days`从原播期重新计算。日期必须属于环境年份。`planting_windows(..., step_days=1)`按逐日邻接形成窗口，原接口默认5天保持兼容。

输入核查记录在`input_audit.csv`。三个地点两年Field和田块坐标存在差异，图表称“同地点跨年”，不称同地块多年。Stand_Count/Plot_Area只是实现株数密度诊断，不自动当成播种密度使用。

## 第三版：允许播种后跨年生长

```bash
.venv/bin/python -m aquacrop_demo.crossyear
```

输出位于`outputs/aquacrop_crossyear/`，不覆盖前两版。复用第一年天气，对六个原环境分别从NASA POWER获取同一坐标的下一年完整天气；联网仅在首次获取时需要。三套主参数（默认、第一版率定、优化）不重新率定，每套在六个环境对全年365天逐日扫描。模拟从播种当年1月1日开始，每个候选的截止日为下一周年前一天；作物提前成熟或死亡则提前结束。OSPy 3.1.0自身还要求单季成熟少于365天。因内部使用非闰年1990解析月/日，2023年3月1日播期的2024年2月29日截止改为2月28日并记录。冬播可能产生数值上可成熟但农学上不可信的高产；图中模拟不构成田间播期推荐。
