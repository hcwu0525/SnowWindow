# 快速上手

最后核对日期：2026-09-29。返回 [README](../README.md)。

## 1. Python 环境

SnowWindow 需要 Python 3.10–3.12，推荐 Python 3.10：

```bash
uv venv --python 3.10 --seed .venv
.venv/bin/python -m pip install -r requirements-aquacrop.lock.txt
.venv/bin/python -m pip install -e .
.venv/bin/python -m pip check
```

如果没有 `uv`，可用 `python3.10 -m venv .venv` 创建环境后执行同样的
`pip` 命令。

## 2. 数据布局

将 G2F 源文件放在 `data/` 下；源文件只读：

```text
data/
  Training_data/
    1_Training_Trait_Data_2014_2023.csv
    2_Training_Meta_Data_2014_2023.csv
    3_Training_Soil_Data_2015_2023.csv
  Testing_data/
    2_Testing_Meta_Data_2024.csv
    3_Testing_Soil_Data_2024.csv
```

字段含义与缺口见 [G2F 数据映射](g2f-data.md)。

## 3. AquaCrop 快速示例

AquaCrop 是默认开箱可用路径：

```bash
.venv/bin/python -m snowwindow run --config configs/g2f_demo.yaml
```

首次运行会自动准备数据并写入 `outputs/experiments/g2f_demo/`。若只需
验证数据链路：

```bash
.venv/bin/python -m snowwindow audit --config configs/g2f_demo.yaml
.venv/bin/python -m snowwindow prepare --config configs/g2f_demo.yaml
```

报告位于 `outputs/experiments/g2f_demo/report/report.md`。

## 4. 可选 APSIM 引擎

APSIM NG 使用本地原生命令行，默认查找 `.tools/apsim/` 与
`bin/apsim` 启动器。安装后先验证：

```bash
./bin/apsim --version
./bin/apsim /absolute/path/to/experiment.apsimx --single-threaded --csv
```

本仓库不自动下载 APSIM 或 .NET。安装、指纹和冒烟示例见
[APSIM 指南](models/apsim.md)。

## 5. 可选 DSSAT 引擎

DSSAT 使用 CERES-Maize 原生可执行文件，默认查找
`.tools/dssat/4.8.6.2/`。官方玉米数据分布需单独授权或下载。
安装前先阅读 [DSSAT 指南](models/dssat.md) 和
[DSSAT 详细运行说明](dssat.md)。

## 6. 结果目录

所有生成物位于：

```text
outputs/experiments/<experiment_id>/
```

运行下面命令重建总索引：

```bash
.venv/bin/python -m snowwindow catalog --config configs/g2f_demo.yaml
```

历史输出保留在 `outputs/experiments/legacy/`，索引见
[实验结果](experiments.md)。
