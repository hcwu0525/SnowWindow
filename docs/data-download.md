# 数据集下载与首次校验

来源与流程核对日期：2026-10-27。返回 [README](../README.md) 或
[文档目录](README.md)。

本页说明如何取得当前流水线需要的 G2F 原始文件，不下载或修改你已有的
`data/`。先按[快速上手](getting-started.md#1-python-环境)安装 Python 环境，
再依次完成下载、目录检查、audit 和 prepare。

## 1. 下载哪个数据集

使用 **Genomes to Fields 2024 Maize Genotype by Environment Prediction
Competition** 数据，而不是任意年份的 G2F 原始发布包：

- 数据 DOI：[10.25739/78mn-4394](https://doi.org/10.25739/78mn-4394)。
- [CyVerse 官方发布页](https://dc.cyverse.org/dataset/genomes_to_fields_2024_maize_genotype_by_environment_prediction_competition)：
  下载入口及数据许可。
- [官方 readme 资源页](https://dc.cyverse.org/dataset/genomes_to_fields_2024_maize_genotype_by_environment_prediction_competition/resource/a3de9669-88dc-4cdf-9ec6-c17933fa3a77)：
  文件说明与当前资源 URL。
- [配套数据论文](https://doi.org/10.1186/s13104-026-07629-5)：
  2026-02-09 发表，说明训练/测试划分，表 1 列出发布文件。

该竞赛数据的训练部分覆盖 2014–2023 年，测试部分为 2024 年；
训练土壤表从 2015 年开始。本仓库的文件名与该发布清单对应，但尚未与
官方原件逐文件核验校验和，不能仅凭同名断言本地副本字节完全相同。
当前 demo 配置另行使用 2022 年校准、2023 年评估；加载 2024 年标签
不等于已完成 2024 年独立测试，更不能用这些标签调参。

核对时官方资源 URL 的公共路径为：

```text
/iplant/home/shared/commons_repo/curated/
  GenomesToFields_GenotypeByEnvironment_PredictionCompetition_2025/
```

路径中的 `_2025` 是资源目录名，不能据此把本次测试年份理解为 2025。
若资源迁移，以 DOI 发布页的当前链接为准，不自行猜测新路径或替换数据版本。

官方资源页标注 **Open Data Commons Public Domain Dedication and License
（PDDL）**。下载前重新确认页面许可，研究引用同时记录数据 DOI 和数据论文。
数据许可不等于 SnowWindow 源码或 APSIM/DSSAT 的许可；本仓库不代办引擎授权，
也不因本页而指定源码许可证。

## 2. 从官方页面下载

推荐浏览器流程，避免将网页、登录页或站点验证页误存为 CSV：

1. 打开上面的 DOI 或 CyVerse 发布页，核对完整标题及年份。
2. 在 **Data and Resources** 中找到 `readme.txt`，通过 **Go to resource**
   阅读或保存原说明；页面也列有可选的 `COMPETITION_DATA_README.docx`。
   README 供理解来源，不属于流水线必须读取的 13 个输入。
3. 分别打开 `Training_data`、`Testing_data` 的 **Browse folder**，
   下载下一节列出的 6 个训练 CSV 和 7 个测试 CSV，保留原始文件名与内容。
   特别检查测试目录中是否包含 `7_Testing_Observed_Values.csv`。
4. 先保存到仓库外新建的暂存目录。若通过浏览器或官方工具取得压缩包，
   先解压到暂存目录并核对内部层级；不假定官方提供固定名称的 ZIP 包，
   也不要把 `.zip` 文件直接改名为 `.csv`。
5. 确认文件齐全后，把两个目录中的所需 CSV 放入仓库根目录 `data/`，
   得到下一节布局。去掉解压产生的多余外层目录，保留 `Training_data/`
   和 `Testing_data/` 这一级。已有同名文件时停止并比较来源/指纹，
   不要覆盖原始副本；需要另一版本时使用独立数据目录和新实验 ID。

若官方目录或已有副本缺少 `7_Testing_Observed_Values.csv`，先核对是否取到了
当前完整公开发布，而不是竞赛进行时的无标签测试包；仍缺少时联系发布方取得
对应文件。当前输入契约不能跳过它，即使 demo 只评估 2023 年也一样。
取得前停止准备与实验流程，不造空表、不用提交模板顶替，也不用预测值充当观测。

官方发布页公开提供资源链接；核对到的 `readme.txt` 文件端点使用
`https://data.cyverse.org/dav-anon/` 前缀。若跳转到需要认证的工具，
先回到发布页核对是否选择了正确的公开资源，再按官方要求登录。
不要为了下载而关闭 TLS 校验、使用来历不明的镜像或绕过访问控制。

本次核对了发布页、资源页的公开元数据及论文中的来源/文件清单；当前运行环境
访问文件端点时出现 TLS 连接被重置（curl error 35），没有重新下载整套数据，
也没有完成官方文件的端到端传输和校验和比对。因此这里提供浏览器操作步骤，
不承诺批量下载命令在所有网络中可用。遇到 403、超时或返回 HTML 时，
保留失败记录，换用能正常访问官方站点的浏览器/网络，或联系发布方；
不要把错误响应当作数据继续实验。

## 3. 需要哪些文件、放在哪里

默认配置中的 `data_dir: ../data` 相对 `configs/` 中 YAML 的位置解析，
因此对应仓库根目录 `data/`。以下路径大小写与文件名须保持一致：

```text
data/
  Training_data/
    1_Training_Trait_Data_2014_2023.csv
    2_Training_Meta_Data_2014_2023.csv
    3_Training_Soil_Data_2015_2023.csv
    4_Training_Weather_Data_2014_2023_full_year.csv
    4_Training_Weather_Data_2014_2023_seasons_only.csv
    6_Training_EC_Data_2014_2023.csv
  Testing_data/
    1_Submission_Template_2024.csv
    2_Testing_Meta_Data_2024.csv
    3_Testing_Soil_Data_2024.csv
    4_Testing_Weather_Data_2024_full_year.csv
    4_Testing_Weather_Data_2024_seasons_only.csv
    6_Testing_EC_Data_2024.csv
    7_Testing_Observed_Values.csv
```

两个 `seasons_only` 和两个 EC 文件仅参与完整性检查与来源指纹，不进入模型
输入表，但仍是必需文件。其余九个文件用于模型数据准备。完整契约由
[SOURCE_CATALOG](../src/snowwindow/data/sources.py) 定义，角色说明见
[G2F 数据映射](g2f-data.md#必需的-13-个源文件)。

不需要下载基因组 VCF、数值基因型或亲本表来运行当前流程；
`train_merged_data.csv`、`test_merged_data.csv` 和
`train_6D_features.csv`、`test_6D_features.csv` 也不被读取。
项目从原始分表自行关联、标准化，不能用 merged 表顶替缺失输入，
也不能省略仅用于审计的四个文件。

不要用 Excel 重新另存 CSV，不改列名、日期、缺失值或编码来“修复”输入。
如需处理新版本，应保留原副本并单独评估输入契约；源文件始终只读。

## 4. 先检查目录与基本文件内容

在仓库根目录运行。以下代码使用已安装的 SnowWindow 环境，只读检查文件
存在、非空、CSV 的 `Env` 表头和至少一行数据，并打印文件大小及 SHA256。
它不联网、不生成实验产物，也不保证所有数据行完整或科学上可用；
后续仍须运行 audit：

```bash
.venv/bin/python - <<'PY'
import csv
from pathlib import Path

from snowwindow.data.sources import SOURCE_CATALOG, sha256_file

data_root = Path("data")  # 使用其他数据目录时，仅修改这里
problems = []
for spec in SOURCE_CATALOG.values():
    path = data_root / spec.relative_path
    if not path.is_file() or path.stat().st_size == 0:
        problems.append(f"缺失或空文件：{path}")
        continue
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream)
            header = next(reader, [])
            first_row = next(reader, [])
        if "Env" not in header or not first_row:
            problems.append(f"不是预期的 G2F CSV，检查是否误下载网页：{path}")
            continue
        print(f"{sha256_file(path)}  {path.stat().st_size} bytes  {path}")
    except (OSError, UnicodeError, csv.Error) as exc:
        problems.append(f"无法读取：{path}：{exc}")

if problems:
    raise SystemExit("\n".join(problems))
print(f"基本检查通过：{len(SOURCE_CATALOG)} 个文件；下一步运行 audit。")
PY
```

此命令示例使用 Bash；Windows 可在 Git Bash/WSL 中执行。若使用原生
Windows 虚拟环境，把解释器改为 `.venv/Scripts/python.exe`。
SHA256 是本次副本的指纹，不是从官方取得的预期值；它不能独自证明下载来源。
若官方提供校验文件，应另行比对，不能用上面刚计算的值自证下载正确。

## 5. 数据审计、首次准备与来源记录

新检出环境、默认演示 ID 尚无历史产物时执行：

```bash
.venv/bin/python -m snowwindow audit --config configs/g2f_demo.yaml
.venv/bin/python -m snowwindow prepare --config configs/g2f_demo.yaml
```

若已有同 ID 实验、配置或数据来源发生变化，先用编辑器复制 YAML 为
`configs/g2f_download_check.local.yaml`，设置新的 `experiment_id`
（例如 `g2f_download_check_20261027`），保留其他参数或按实际位置设置
`data_dir`，再将两条命令的 `--config` 替换为这个文件。
不要删除旧快照或覆盖历史产物来强行恢复运行；数据版本改变也使用新 ID，
不能仅因 YAML 文本未变而混用原有产物。

`audit` 在内存中检查输入并向终端打印计数，不创建输出文件。
`prepare` 成功后，默认演示实验的重点检查项是：

- `outputs/experiments/g2f_demo/audit/data_audit.json`：
  缺失、覆盖情况和假设。命令退出成功不代表所有环境都合格。
- `outputs/experiments/g2f_demo/audit/eligibility.parquet`：
  校准/扫描资格及排除原因。
- `outputs/experiments/g2f_demo/manifests/prepare_manifest.json`：
  `sources` 记录全部 13 个文件的路径、字节数、SHA256 和角色。
- `outputs/experiments/g2f_demo/config.yaml`：可重新加载的配置快照。

使用新 ID 时，上述路径中的 `g2f_demo` 随之替换。`prepare` 会创建标准化表，
不是下载命令；只有检查天气连续性、资格排除原因和模型前提后才继续 baseline。
完整顺序见[实验指南](experiments.md)。

`prepare_manifest.json` 自动记录本地输入指纹，但不会自动补全官方 DOI、
下载日期或许可信息。请在 prepare 成功后，将以下来源记录另存为本实验
`audit/download_record.md`，不提交原数据或下载凭据。不要在 prepare 前
往一个尚无配置快照的实验目录预写记录，以免触发历史目录保护。

```text
数据标题：Genomes to Fields 2024 Maize Genotype by Environment Prediction Competition
数据 DOI：10.25739/78mn-4394
下载/取得日期与时区：<实际日期，不用本页核对日期代替>
官方资源页及实际文件 URL：<逐项记录或附下载清单>
数据目录/版本标识：<实际资源路径与取得方式；备份需注明原始来源>
页面许可：<下载时所示许可及页面链接>
本地文件指纹：见同实验 manifests/prepare_manifest.json 的 sources
与官方校验值的比对：<结果；没有可比对的官方值则明确写未核验>
```

## 6. 下载后的天气与引擎边界

统一天气策略更新（2026-10-27）：三模型均只用 G2F `full_year` 原始分表
标准化天气，不读取 legacy POWER CSV/provenance。新用户无需恢复或生成
任何外部天气缓存；数据完整性与模型引擎仍是独立前提：

- 名称带 `full_year` 不代表日期连续或全年完整。普通模拟从当前环境
  `normalized/weather.parquet` 记录开始，只有 `simulation.scan_horizon:
  cross_year` 且 `continuation_weather_by_environment` 显式映射下一年
  同站点 G2F 环境时才追加记录；无映射不自动替代。
- 模拟受实际天气截止日限制，尾部不足记录截断，内部缺日期或核心值继续
  保留失败。2024 覆盖为 2024-01-01 至 2024-11-10（315 天，保留 2/29），
  scan/forecast 的 2024 候选播期与相关模拟结束日也不晚于 11/10。
  2024-07-12 至 2024-07-14 的核心缺测不得补零、外部替代或改标成熟。
  该数据截止日不等于 forecast 信息截止日；forecast 仍用 G2F 历史同站点
  情景，不用目标年未来实测选参，六个示例的评估年仍是 2023。
- 三个主 demo 仅配置实际存在的五条下一年映射，没有 `MOH2_2024`；
  refined/history 仍为空映射，跨年缺口未解决，见[天气说明](getting-started.md#4-三模型共用-g2f-天气与时限)。
- APSIM/.NET 与 DSSAT 本地引擎另按[上手指南](getting-started.md#5-可选-apsim-引擎)
  安装并核对指纹；不随 G2F 数据包或 Git 仓库分发。

模型结果缓存和扫描断点恢复继续保留，不是外部天气缓存。历史 POWER
驱动产物的来源、数值和日期保留，不追认为新策略通过；新策略必须新建实验
ID，自动记录 `weather_policy` 的新快照不能与旧快照/产物混用。
forecast 另须使用新 ID 并指向同策略的新源实验，不能沿用旧 oracle。

`data/`、`outputs/` 及本地引擎均不入 Git。提交文档前可用
`git status --short --untracked-files=all` 检查待提交范围，不使用 `git add -f`
把数据、缓存或来源不明的第三方文件纳入仓库。
