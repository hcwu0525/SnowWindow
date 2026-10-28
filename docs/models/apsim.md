# APSIM 指南

返回 [README](../../README.md)。

## 安装与校验

自行取得适用许可/授权下的 APSIM NG 2026.9.8116.0 分发，以及对应 Linux
.NET 运行时；本仓库不自动下载、安装或代办商业/受限引擎授权。
将分发解包到以下约定位置，不要只复制一个模板：

```text
.tools/apsim/2026.9.8116.0/
  bin/Models.dll
  Examples/Maize.apsimx
  native-libs/
.tools/dotnet/8.0.31/dotnet
```

保留分发的依赖文件与目录结构，确保 `dotnet` 和 `bin/apsim` 可执行。
启动器固定设置 `DOTNET_ROOT` 与原生库路径；单独在 PATH 装另一个 dotnet
不能替代其约定目录。适配器从 Models.dll 读取内嵌 Maize 资源，
所以模板缺依赖时也不能运行。先核对启动器及版本：

```bash
./bin/apsim --version
```

如需官方示例冒烟，先把示例复制到新的输出目录，避免污染安装目录：

```bash
set -e
test ! -e outputs/experiments/apsim_runtime_check
test ! -L outputs/experiments/apsim_runtime_check
mkdir -p outputs/experiments/apsim_runtime_check
cp .tools/apsim/2026.9.8116.0/Examples/Maize.apsimx \
  outputs/experiments/apsim_runtime_check/
./bin/apsim outputs/experiments/apsim_runtime_check/Maize.apsimx \
  --single-threaded --csv
```

官方模板使用 `%root%/Examples/WeatherFiles/Dalby.met`，需保留同分发的天气文件；
其他引用也应恢复并核对路径。冒烟仅验证运行时，
不是 G2F 科学结果；该官方示例天气不用于 SnowWindow 的 G2F 实验。
`.tools/` 与 APSIM 包不入库。
当前适配器记录自身源码、模板、启动器的 SHA256 并检查运行时版本；
启动器指纹不等于完整引擎指纹，还需自行保存 Models.dll、原生库和 .NET
分发的版本/校验和，避免替换引擎后误用旧缓存。

## 输入映射

- 天气：最低/最高温度、降雨、辐射，写入 APSIM 可读气象输入。
- 土壤水氮：当前六环境流程使用固定探索假设。
- 品种：固定 Dekalb_XL82 假设，不等同于 G2F Hybrid。

天气策略更新（2026-10-27）：与 AquaCrop/DSSAT 统一，只使用本实验
`normalized/weather.parquet` 中的 G2F `full_year` 原始分表标准化记录；
不读取 legacy POWER CSV/provenance，也无需恢复外部天气缓存。先读当前
环境，只有 `simulation.scan_horizon: cross_year` 且
`continuation_weather_by_environment` 显式映射下一年同站点 G2F 环境时
才追加，无映射不自动替代。引擎工作目录的气象输入由这些记录生成；
模型结果缓存与断点恢复保留，不属于外部天气缓存。
forecast 仍用 G2F 历史同站点情景，不用目标年未来实测选参。

## 可校准参数

| 参数 | 含义 |
| --- | --- |
| `juvenile_tt` | 幼期积温相关物候参数 |
| `grain_number_scale` | 籽粒数缩放 |

当前版本不支持站点级校准。

## 输出解释

输出包含籽粒产量、开花事件和阶段信息。开花事件与 G2F `Pollen_DAP_days`
只作为代理比较，不是同一观测定义。

## 已知限制

- 固定土壤、水氮、施肥和品种情景仅用于流程验证。
- 示例默认输出不等于 APSIM 全部可输出能力。
- 全年扫描是反事实情景，冬季播种结果需单独田间可行性验证。
- 模拟受实际天气截止日限制并记录尾部截断，内部缺日期/核心值仍保留失败。
  2024 相关模拟与 scan/forecast 候选播期最晚为 2024-11-10（315 天，
  保留 2/29）；7/12–7/14 核心缺测不得补零、外部替代或改标成熟。
  该数据截止日不等于 forecast 信息截止日。详见[上手指南](../getting-started.md)。
- 没有 `MOH2_2024`，不得配置或伪造；显式映射也不等于跨年天气完整。
- 历史报告是本地产物，clone 不包含；保留原驱动说明、数值和日期，不追认
  当前策略通过。新策略必须用新 ID 和带 `weather_policy` 的新快照，不能混用旧产物。
