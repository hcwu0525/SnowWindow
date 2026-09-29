# SnowWindow

SnowWindow 是一个可复现的 G2F 玉米播期模拟流水线。它将源数据标准化，
审计模型可用性，通过统一适配器运行 AquaCrop、APSIM 和 DSSAT，
完成校准、独立年份验证与全年播期窗口报告。

## 快速开始

```bash
uv venv --python 3.10 --seed .venv
.venv/bin/python -m pip install -r requirements-aquacrop.lock.txt
.venv/bin/python -m pip install -e .
.venv/bin/python -m snowwindow run --config configs/g2f_demo.yaml
```

完整安装、数据布局和可选引擎说明见
[快速上手](docs/getting-started.md)。

## 三类模型能力概览

| 能力 | AquaCrop 3.1.0 | APSIM NG 2026.9.8 | DSSAT 4.8.6.2 |
| --- | --- | --- | --- |
| 分发方式 | Python 依赖，开箱可用 | 本地原生引擎，需安装 | 本地原生引擎，需安装 |
| 校准参数 | `phenology_scale`、`HI0` | `juvenile_tt`、`grain_number_scale` | `P1`、`G2` |
| 站点校准 | 支持 | 暂不支持 | 暂不支持 |
| 当前验证 | 六环境闭环 | 固定探索情景六环境闭环 | 固定参考情景六环境闭环 |
| 主要限制 | 单层土壤、无完整氮循环 | 土壤水氮与品种为固定假设 | 土壤、品种、施氮为固定参考输入 |

详细边界见各模型指南：
[AquaCrop](docs/models/aquacrop.md)、
[APSIM](docs/models/apsim.md)、
[DSSAT](docs/models/dssat.md)。

## 文档索引

- [快速上手](docs/getting-started.md)：环境、数据、AquaCrop 示例和可选引擎。
- [配置指南](docs/configuration.md)：配置结构、统一校准键和兼容策略。
- [实验结果索引](docs/experiments.md)：目录规范、catalog 和复现入口。
- [G2F 数据映射](docs/g2f-data.md)：字段、单位、覆盖范围和缺口。
- [模型比较](docs/model-comparison.md)：机制、输入输出和适用范围。
- [研究日志](docs/model-usage-log.md)：历史实验证据和结论边界。
- [文档目录](docs/README.md)：持续维护约定。

## 常用命令

```bash
# 完整流水线
.venv/bin/python -m snowwindow run --config configs/g2f_demo.yaml

# 分阶段执行
.venv/bin/python -m snowwindow audit --config configs/g2f_demo.yaml
.venv/bin/python -m snowwindow prepare --config configs/g2f_demo.yaml
.venv/bin/python -m snowwindow calibrate --config configs/g2f_demo.yaml
.venv/bin/python -m snowwindow validate --config configs/g2f_demo.yaml
.venv/bin/python -m snowwindow scan --config configs/g2f_demo.yaml
.venv/bin/python -m snowwindow report --config configs/g2f_demo.yaml

# 重建结果目录索引
.venv/bin/python -m snowwindow catalog --config configs/g2f_demo.yaml
```

结果入口：

- `outputs/experiments/INDEX.md`
- `outputs/experiments/catalog.json`
- `outputs/experiments/g2f_demo/report/report.md`

## 验证

提交前运行：

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests/snowwindow
```

## 科学使用边界

`data/` 保持只读；所有生成物写入 `outputs/experiments/<experiment_id>/`。
校准与评估年份必须不相交；不得用评估年份观测选择参数。失败和未成熟
运行必须保留原始状态。全年播期扫描是反事实情景，不能当作全年实测验证。
