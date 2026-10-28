# AquaCrop 指南

返回 [README](../../README.md)。

## 安装与校验

AquaCrop-OSPy 3.1.0 由锁定依赖安装，不需要本地原生引擎：

```bash
uv venv --python 3.10 --seed .venv
.venv/bin/python -m pip install -r requirements-aquacrop.lock.txt -e '.[dev]'
.venv/bin/python -m pip check
```

推荐 Python 3.10，项目元信息支持 3.10–3.12。配置使用
`model.name: aquacrop`；[数据清单](../getting-started.md)中的 13 个文件必须
自备，库安装不代表已具备完整天气。适配器在模型结果缓存中记录模型与
自身源码指纹；该缓存及断点恢复保留，不是外部天气缓存。

## 输入映射

- 天气：`T2M_MIN`、`T2M_MAX`、`PRECTOTCORR`、`RH2M`、`WS2M`、`PS`、
  `ALLSKY_SFC_SW_DWN`；`ET0` 由适配器计算。
- 土壤：当前适配器支持单一均质土层和受限土壤纹理。
- 管理：实际播期、可用密度、灌溉假设；缺省灌溉按配置显式标记。

天气策略更新（2026-10-27）：与 APSIM/DSSAT 统一，只使用本实验
`normalized/weather.parquet` 中的 G2F `full_year` 原始分表标准化记录；
不读取 legacy POWER CSV/provenance，不需要外部天气缓存。先读当前环境，
只有 `simulation.scan_horizon: cross_year` 且
`continuation_weather_by_environment` 显式映射下一年同站点 G2F 环境时
才追加；无映射不自动替代。forecast 仍用 G2F 历史同站点情景，不用目标年
未来实测选参。完整规则见[共用天气说明](../getting-started.md#4-三模型共用-g2f-天气与时限)。

## 可校准参数

| 参数 | 含义 |
| --- | --- |
| `phenology_scale` | 物候时间尺度缩放 |
| `HI0` | 参考收获指数 |

AquaCrop 还支持站点级 `phenology_scale_site` 和 `HI0_site` 偏移。

## 输出解释

统一输出包含 `dry_yield_mg_ha`、物候代理和稳定状态。开花代理来自
`HIstart` 首次日末跨越，不是独立散粉事件。

## 已知限制

- 当前 Python 实现不是 FAO 官方实现。
- 不包含完整氮循环、盐分胁迫或肥力胁迫。
- 全年扫描是反事实情景，不代表全年实测产量。
- 模拟受实际天气截止日限制并记录尾部截断，内部缺日期/核心值仍保留失败。
  2024 相关模拟与 scan/forecast 候选播期不得晚于 2024-11-10（315 天，
  保留 2/29）；7/12–7/14 核心缺测不得补零、外部替代或改标成熟。
  该数据截止日不等于 forecast 信息截止日。
- refined/history 保留空延续映射；`MOH2_2024` 不存在，不配置或伪造。
  显式映射不证明 2024 已完整，跨年缺口不能称为已解决。
- 历史 demo 的驱动/时限与当前策略不同，保留原数值与日期，不追认新策略
  通过；必须用新 ID 和带 `weather_policy` 的新快照，不能混用旧产物。
