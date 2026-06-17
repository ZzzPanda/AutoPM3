# PM3-Bench

[English](./README.md) | **简体中文**

## 简介
[ClinGen 证据库](https://erepo.clinicalgenome.org/evrepo/) 提供了专家整理的判定条目，但条目以自然语言撰写，给基准评测的自动化带来了困难。为解决这一问题，我们基于 ClinGen 证据库构建了 PM3-Bench——一个面向 PM3 文献证据提取的综合数据集。

![](../docs/images/PM3-bench.png)

---

## 数据说明
本仓库提供 `PM3-Bench.json`，包含以下字段：

| 列名 | 说明 |
|---|---|
| ClinGen ID | ClinGen 证据库中的原始 ID |
| Variant Name | 变异的 HGVS 命名（DNA 层面变化） |
| Condition | ClinGen 中报告的疾病 |
| Criterion | 命中的 ACMG 判据 |
| Raw Comment | 专家提交的原始评注 |
| PMID | 文献证据对应的 PubMed ID |
| Number of Patients | 根据评注抽取的患者数量 |
| In trans Variants | 从评注中抽取的反式变异列表（以所有可能的格式扩充，空格分隔）；"NA" 表示原始评注中未提及反式变异 |
| labels | `eval`：用于评测的变异-文献配对；`others`：NCBI API 中文献 XML 被截断的样本，评测时已剔除；`fine-tune`：剩余样本，其中评注非空者用于微调 |


