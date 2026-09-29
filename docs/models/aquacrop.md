# AquaCrop 指南

返回 [README](../../README.md)。

## 安装与校验

AquaCrop-OSPy 3.1.0 由锁定依赖安装，不需要本地原生引擎：

```bash
.venv/bin/python -m pip install -r requirements-aquacrop.lock.txt
.venv/bin/python -m pip install -e .
```

配置使用 `model.name: aquacrop`。

## 输入映射

- 天气：`T2M_MIN`、`T2M_MAX`、`PRECTOTCORR`、`RH2M`、`WS2M`、`PS`、
  `ALLSKY_SFC_SW_DWN`；`ET0` 由适配器计算。
- 土壤：当前适配器支持单一均质土层和受限土壤纹理。
- 管理：实际播期、可用密度、灌溉假设；缺省灌溉按配置显式标记。

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
