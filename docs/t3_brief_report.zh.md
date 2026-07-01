# T3 简要报告

> 日期：2026-06-21
> 范围：围绕两个用户提供的 PM3 测试集目录做数据梳理与结构设计；仓库内现有数据只作为辅助参考。

## 摘要

修正：主数据不是仓库里的任何现有数据，而是
`/Users/roger/Downloads` 下两个按位点组织的目录。它们包含人工/AI
整理过的 PM3 汇总表和本地 PubMed PDF：POMGNT1 目录有 3 条整理记录
和 2 篇 PDF；CFTR 目录有 5 条整理记录和 31 篇 PDF。PM3-Bench 和仓库
内 fixture 只作为辅助参考/回归数据。

主要建议是：先把两个用户提供的 XLSX 规范化为“每个目标变异-论文配对
一条 JSONL 记录”，保留原始中文字段，并把每条记录和本地 PDF artifact
对齐。PM3-Bench 后续可以选择性转换到同一 schema，但不应反过来定义
第一版 T3 schema。

## 关键发现

| 领域 | 发现 |
| --- | --- |
| 真实用户测试集 | 两个 Downloads 目录：POMGNT1 c.1319T>G 和 CFTR c.220C>T。 |
| POMGNT1 目录 | 1 个 XLSX、2 篇 PDF、3 条整理记录。PMID 21983716 在表中有记录，但目录中未发现对应 PDF。 |
| CFTR 目录 | 1 个 XLSX、31 篇 PDF、5 条整理记录。`位点` sheet 记录 `chr7:117149143 C/T` 和 `rs115545701`。 |
| 共享 XLSX schema | 两个 workbook 都使用 18 列，覆盖 PMID、标题、是否提及位点、患者数、疾病、表型、家系、致病性、合子状态、trans/cis 位点、来源索引、表格原始行、文献背景、总结和 AI 提取过程。 |
| 辅助 benchmark | `benchmarks/PM3_Bench_data.json` 有 1,027 条记录，但不是 T3 主数据。 |
| 标签拆分 | `fine-tune`: 760，`eval`: 195，`others`: 72。 |
| PMID | 467 个唯一 PMID；155 个 PMID 对应多条记录。 |
| 变异 | 752 个唯一目标变异；观察到的 `Variant Name` 都以 `NM_` 开头。 |
| 疾病/条件 | 22 个唯一规范化 condition 字符串。 |
| PM3 等级 | PM3-Supporting 343，PM3 307，PM3-Strong 210，PM3-Very Strong 167。 |
| 患者数 | 47 个 `NA`，10 个 `err`，且存在 int/string 混合类型。 |
| 字段不一致 | 数据实际字段是 `CinGen ID`，README 写的是 `ClinGen ID`。 |
| 文本质量 | 31 条 raw comment 出现类似 `â` / `Â` 的乱码。 |
| 证据定位 | PM3-Bench comment 是 assertion 文本，不是论文原文 span。 |

## 主要风险

1. 真实用户测试集里的 XLSX 记录和本地 PDF 并不完全对齐：有整理过的
   PMID 缺 PDF，也有 PDF 尚未进入汇总表。
2. XLSX 中 trans/cis 字段信息很丰富，但仍是半结构化文本，需要规范化
   后才能自动评测。
3. `Number of Patients` 需要先清洗，才能作为可靠的数值标签使用。
4. 若要评估 citation grounding，需要 PDF/Markdown/XML 中的 evidence
   span；仅靠 XLSX summary 不够。
5. 如果后续使用辅助 PM3-Bench，按行做 train/eval 拆分会有 paper-level
   信息泄漏风险，因为同一个 PMID 可能对应多条变异记录。
6. PM3-Bench 中扁平的 `In trans Variants` 字段不足以评估等位基因配对、
   相位证据、转录本一致性或病例级支持。
7. PM3-Bench `others` 应作为 parser/data-quality 诊断集单独保留，不应混入正常
   训练或评测。

## 推荐方向

- 先规范化两个用户提供的 XLSX，以 target variant-paper pair 为 key。
- 为每个目录生成 PDF/XLSX 对齐报告：已整理 PMID、已有 PDF、缺失 PDF、
  尚未整理的候选 PDF。
- 将这两个用户目录作为第一批 gold/acceptance test set，不作为训练集。
- 保留 source/raw 字段用于追溯，同时引入干净的 typed fields。
- 当论文 artifact 可用时，尽快补充 evidence-span 记录。
- PM3-Bench 只作为后续可选的辅助 benchmark adapter。

## 立即下一步

以 `plan.zh.md` / `plan.md` 作为执行计划。第一个非代码里程碑是确认
这两个 Downloads 目录作为 primary acceptance/gold seed，然后冻结
XLSX-to-JSONL schema 和 PDF 对齐策略。

标准化测试数据结构详见：
`docs/t3_standardized_test_data_structure.zh.md`。
