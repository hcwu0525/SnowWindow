# DSSAT 原生 CERES-Maize：Linux 与 G2F 六环境

核对日期：2026-09-27。返回[文档目录](README.md)或
[DSSAT 使用摘要](models/dssat.md)。

本页描述 SnowWindow **已经运行的** DSSAT-CSM 4.8.6.2
（`MZCER048`）参考情景。调用的是本地 `dscsm048` 可执行文件，
不依赖 Py_DSSATTools。官方示例可运行与 G2F 校准具有不同含义：
前者验证运行时，后者只在文末列出的六个环境与固定假设下成立。

## 运行时与安装

适配器默认查找仓库根目录下的 `.tools/dssat/4.8.6.2/`，至少需要：

| 路径（相对安装目录） | 用途 |
| --- | --- |
| `dscsm048`、`DSSATPRO.L48` | 原生引擎与 Linux 路径配置 |
| `Maize/UFGA8201.MZX` | 官方玉米试验文件模板 |
| `Genotype/MZCER048.CUL`、`.ECO`、`.SPE` | 品种、生态型、物种参数 |
| `Soil/SOIL.SOL` | 通用参考土壤剖面 |

代码及官方数据需另行安装；`.tools/`、`data/` 与 `outputs/`
不随本仓库提交。此工作区的 `DSSATPRO.L48` 使用
`/home/users/haochen.wu/.dssat` 短路径别名指向安装目录，
以避开 DSSAT 旧式固定宽度路径读取限制。更换机器时，必须同步
配置该别名或将 profile 改为本机可读取的短路径。无需 root。

本地 4.8.6.2 源码将 `MZCER048.ECO` 的 `CDAY` 小数形式误读为
整数，导致官方示例在 `MZPHEN` 报错；补丁见
[ecotype-cday.patch](../patches/dssat-4.8.6.2-ecotype-cday.patch)。
补丁只应应用于**未修改的对应版本源码**，本地 `dssat-csm-os/`
工作树已应用，使用当前工作树重编译时应跳过下面的两个
`git ... apply` 命令。新环境从未修改源码构建的示例
（从仓库根目录执行；`cmake` 可在用户目录安装）：

```bash
git -C dssat-csm-os apply --check ../patches/dssat-4.8.6.2-ecotype-cday.patch
git -C dssat-csm-os apply ../patches/dssat-4.8.6.2-ecotype-cday.patch
cmake -S dssat-csm-os -B .tools/dssat/build-local \
  -DCMAKE_Fortran_COMPILER=gfortran -DCMAKE_BUILD_TYPE=RELEASE \
  -DDYNAMIC_LINK=ON
cmake --build .tools/dssat/build-local -j 8
cp .tools/dssat/build-local/bin/dscsm048 .tools/dssat/4.8.6.2/dscsm048
```

先用官方 `UFGA8201.MZX` 做运行时检查（不属于 G2F 结果）：

```bash
mkdir -p outputs/experiments/dssat_runtime/smoke
cp .tools/dssat/4.8.6.2/Maize/UFGA8201.MZX \
  outputs/experiments/dssat_runtime/smoke/
( cd outputs/experiments/dssat_runtime/smoke &&
  "$OLDPWD/.tools/dssat/4.8.6.2/dscsm048" C UFGA8201.MZX 1 )
```

本机该示例的 `Summary.OUT` 记录 FLO=76 DAP、MAT=128 DAP、
HARWT=2293 kg/ha；它只检查原生引擎与官方数据是否能配合运行。

## SnowWindow 如何构造请求

[原生适配器](../src/snowwindow/models/dssat/adapter.py)将每个请求
写入独立的 `model_cache/dssat/<cache_key>/` 工作目录：

| 输入 / 输出 | 已实现的映射或边界 |
| --- | --- |
| 天气 `G2F.WTH` | 逐日 `ALLSKY_SFC_SW_DWN`→`SRAD`（MJ/m²/d）、`T2M_MAX`→`TMAX`、`T2M_MIN`→`TMIN`（℃）、`PRECTOTCORR`→`RAIN`（mm/d）；日期用 DSSAT 年份/年积日格式 |
| 试验 `G2F.MZX` | 沿用官方试验文件结构，替换站点、播期、密度、土壤、初始条件与管理；已标注雨养，不沿用官方示例灌溉事件 |
| 品种 `MZCER048.CUL` | 固定参考品种 `IB0035`（McCurdy 84aa），只调整其 P1（物候）和 G2（潜在籽粒数）；G2F `Hybrid` 未转换为该品种 |
| 土壤与肥料 | 固定通用深砂壤土 `IB00000007`；播期 120 kg N/ha；初始水分与矿质氮设置为参考输入，**不是** G2F 田间观测 |
| 原生输出 | 从 `Summary.OUT` 读取 `ADAT`（开花日期）、`MDAT`（生理成熟日期）、`HWAM`（kg/ha 干籽粒）、`CWAM`（kg/ha 地上干物质）；产量和生物量除以 1000 得 Mg/ha |

用 `ADAT` 减播期所得 `flowering_proxy_dap` 与 G2F
`Pollen_DAP_days` 比较，二者不能视为相同的实测物候事件。
只有存在有效成熟日期的结果才标记 `matured`；未成熟和执行错误
分别保留状态与原因。输入、原生输出及 `result.json` 留在哈希目录，
缓存键包含请求、适配器、可执行文件及参考输入文件指纹。
准备阶段另在 manifest 中记录原始输入指纹。

## 六环境复现与解释

从仓库根目录执行；需要本地 G2F 源文件及跨年延续天气缓存：

```bash
.venv/bin/python -m snowwindow run --config configs/g2f_dssat_demo.yaml
```

[配置文件](../configs/g2f_dssat_demo.yaml)指定 INH1、MOH2、
NYH2 在 2022/2023 年的六个环境。2022 用于 P1/G2 校准，
2023 仅用于留年验证。扫描的两组参数为 `default` 和
`calibrated`，每组覆盖六环境各 365 个播期；跨年气象来自
已缓存的同坐标 NASA POWER 驱动，并非 G2F 2024 年完整天气观测。

本次校准选择 P1=170、G2=790，4,380 个扫描请求均报告成熟。
2023 留年各指标只有三个管理单元：花粉天数代理的 MAE 从
10.74 天降到 3.91 天，干产量 MAE 则从 1.04 升至
2.36 Mg/ha。全年播期是**反事实模拟**，没有全年实际播期标签；
全部成熟不证明冬季播种在田间可行。参考土壤、基因型、水氮状态
和施肥日程尚需站点证据及独立验证。

结果见[报告](../outputs/experiments/g2f_dssat_demo/report/report.md)、
[留年指标](../outputs/experiments/g2f_dssat_demo/validation/metrics.csv)、
[扫描摘要](../outputs/experiments/g2f_dssat_demo/scan/summary.csv)
与[实验日志](model-usage-log.md)。
