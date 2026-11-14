# PHG29/PHG47 玉米播期扫描分析数据

中文分析数据包，面向已有 G2F 原始数据的研究者。

- 品种：PHG29/PHG47。
- 34 个环境、20 个站点；播种年份为 2016、2017、2020、2021、2022。
- APSIM、AquaCrop、DSSAT 共 37,266 条播期扫描记录，完整表 174 个字段。
- 包含核心字段 CSV、完整 Parquet、中文字段字典、校准与独立验证证据、G2F 来源映射及 Python 读取示例。
- 保留死亡、未成熟和技术失败记录；有效干产量记录为 33,125 条。
- 不包含天气事件验证、逐日模型输出、模型缓存或完整原始 G2F 数据集。

解压后从 `dataset/README.md` 开始，运行 `dataset/examples/verify_package.py` 校验文件。
各模型物候代理的含义不同；土壤与部分管理输入为先验或参考假设。校准运行脚本的历史版本差异已在包内注明。

ZIP SHA-256：

```text
b796370a886337ef36a57331630becd0106e14329c79e4f13198b3565b47683b
```

本附件是分析数据发布，不是软件版本更新。G2F 原始数据与模型软件的使用、许可和引用遵循其原有说明。

## 下载与使用

下载同目录的 [g2f_phg29_scan_analysis_v1.zip](g2f_phg29_scan_analysis_v1.zip)，解压后阅读 dataset/README.md。
verification.json 记录本地分发检查；SHA256SUMS 用于核对 ZIP。
