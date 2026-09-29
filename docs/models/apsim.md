# APSIM 指南

返回 [README](../../README.md)。

## 安装与校验

适配器默认使用仓库根目录 `bin/apsim` 和
`.tools/apsim/2026.9.8116.0/Examples/Maize.apsimx`。安装 APSIM NG
和 .NET 后执行：

```bash
./bin/apsim --version
./bin/apsim /absolute/path/to/experiment.apsimx --single-threaded --csv
```

`.tools/` 与 APSIM Debian 包不入库；新环境需自行安装并保留引擎指纹。

## 输入映射

- 天气：最低/最高温度、降雨、辐射，写入 APSIM 可读气象输入。
- 土壤水氮：当前六环境流程使用固定探索假设。
- 品种：固定 Dekalb_XL82 假设，不等同于 G2F Hybrid。

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
