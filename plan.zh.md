# T3 详细计划：测试数据梳理与数据结构优化

> 日期：2026-06-21
> 状态：供算法同学评审的草案
> 本轮规则：只写文档，不改代码。

## 0. 目标

T3 的目标是把两个用户提供的测试集目录整理成一个可支撑 PM3 验收测试
和后续评测数据构建的稳定基础。仓库内现有数据只作为辅助。

这件事不只是统计文件数量。真正要确定的是：数据单元、schema、质量
门槛、拆分策略和标注路径。这样后续工程实现时，不需要反复改数据契约。

## 1. 当前数据基线

| 数据 / artifact | 当前路径 | 当前角色 | 备注 |
| --- | --- | --- | --- |
| 用户测试集：POMGNT1 | `/Users/roger/Downloads/NM_017739.4 (POMGNT1)  c.1319TG (p.Leu440Arg) 2` | primary acceptance/gold seed | 1 个 XLSX、2 篇 PDF、3 条整理记录 |
| 用户测试集：CFTR | `/Users/roger/Downloads/NM_000492.4 (CFTR)  c.220CT (p.Arg74Trp), exon3` | primary acceptance/gold seed | 1 个 XLSX、31 篇 PDF、5 条整理记录 |
| PM3-Bench | `benchmarks/PM3_Bench_data.json` | 辅助 benchmark 参考 | 1,027 条变异-文献记录 |
| PM3-Bench 文档 | `benchmarks/README.md`, `benchmarks/README.zh.md` | 辅助字段说明 | README 写 `ClinGen ID`，数据实际是 `CinGen ID` |
| PubMed BioC XML fixture | `tests/fixtures/23689641.xml`, `data/pdf_convert/23689641.xml` | 辅助 parser/query 回归数据 | 一篇完整论文 fixture |
| PubMed MinerU Markdown fixture | `tests/fixtures/PubMed23689641_markdown.md`, `data/pdf_convert/MinerU_markdown_PubMed23689641_2067159189227929600.md` | 辅助 chunking/evidence UI fixture | 46,041 字符、15 个 heading、2 个 HTML table |
| MinerU metadata | `data/pdf_convert/MinerU_PubMed23689641__20260617081534.json` | 辅助转换调试元数据 | 12 个 `pdf_info` block |
| Synthetic Markdown | `tests/test_synthetic_markdown.py`, `tests/benchmark_chunk_quality.py` | 辅助 chunker 边界测试 | 测试中生成，不是真实 PM3 标签 |

用户测试集观察到的统计：

| 指标 | POMGNT1 | CFTR |
| --- | ---: | ---: |
| XLSX 整理行数 | 3 | 5 |
| 本地 PDF 数 | 2 | 31 |
| XLSX sheet 数 | 1 | 2 |
| 提及目标位点的整理行 | 2 | 5 |
| 未提及 / 不适用整理行 | 1 | 0 |

辅助 PM3-Bench 观察到的统计：

| 指标 | 数值 |
| --- | ---: |
| 总行数 | 1,027 |
| 唯一 PMID | 467 |
| 唯一目标变异 | 752 |
| 唯一规范化 condition | 22 |
| `fine-tune` 行数 | 760 |
| `eval` 行数 | 195 |
| `others` 行数 | 72 |
| 对应多行记录的 PMID 数 | 155 |

## 2. 需要和算法同学确认的决策

这些问题应先确认，再进入实现。

| ID | 决策项 | 推荐默认值 |
| --- | --- | --- |
| D1 | T3 主数据集 | 两个 Downloads 目录，而不是 PM3-Bench |
| D2 | 验收/评测数据单元 | 每个 target variant-paper pair 一条记录 |
| D3 | Artifact 对齐边界 | XLSX 行和 PDF 按 PMID 对齐 |
| D4 | 用户目录的处理 | 先作为 gold/acceptance test seed，不进入训练集 |
| D5 | 仓库内现有数据的处理 | 仅作辅助；不能反向定义用户目录标签或 schema 优先级 |
| D6 | 模型输出形式 | 优先结构化 JSON；rationale 文本可选 |
| D7 | 第一版必需标签 | 目标变异、是否提及、患者数、疾病、表型、家系、合子状态、trans/cis 位点、source evidence、最终总结 |
| D8 | 无法解析患者数的处理 | 数值为 null，并提供明确 status |
| D9 | 无强度 `PM3` 的处理 | 暂时作为独立类别，等领域负责人确认后再映射 |
| D10 | evidence grounding 要求 | 用户目录 gold rows 必需；后续辅助 adapter 可选 |

## 3. 推荐数据单元

### 3.1 主记录

每条 JSONL 记录对应一个 target variant-paper pair。

该数据单元由用户提供 XLSX 的行结构定义。PM3-Bench 后续可以适配，
但不是第一版 T3 schema 的来源。

### 3.2 分层对象

每条主记录建议支持以下层级：

| 层级 | 作用 |
| --- | --- |
| `source` | 追溯原始数据集、行号、raw fields 和转换元数据 |
| `paper` | PMID、DOI、标题、可用格式、解析状态 |
| `condition` | 原始和规范化疾病/表型 |
| `target_variant` | 原始变异，以及 transcript/cDNA/protein/gene 解析字段 |
| `pm3_assertion` | Criterion、患者数、in-trans 摘要、assertion 来源 |
| `partner_variants` | 结构化 in-trans 或候选第二等位基因变异 |
| `cases` | 可选的病例/家系级证据 |
| `evidence` | comment、chunk、table、row 或 quote 级证据 |
| `review` | 人工审核状态和数据质量 flag |

### 3.3 用户测试集专属字段

用户提供的 XLSX 中有一些字段应完整保留，再做结构化规范化：

| 原始 XLSX 概念 | 规范化字段 |
| --- | --- |
| `是否提及此位点` | `target_variant.mention_status` |
| `患者年龄` | `cases[].age` 或 `patient_age_summary` |
| `患者临床疾病` | `condition.raw`, `condition.name` |
| `患者临床表型` | `phenotype_summary` |
| `家系情况` | `family_context` |
| `致病性...` | `pathogenicity_author_conclusion` |
| `关联合子状态` | `pm3_assertion.zygosity_or_allele_state` |
| `反式(trans)位点` | `partner_variants[]`，`phase_relation = in_trans` |
| `顺式(cis)位点` | `cis_variants[]` |
| `来源索引...` | `evidence[].source_index` |
| `表格原始行内容...` | `evidence[].raw_table_row_text` |
| `文献背景...` | `paper.background_summary` |
| `总结...` | `pm3_assertion.final_summary` |
| `AI提取过程` | `source.ai_extraction_trace` |

## 4. 推荐规范化 Schema

第一版 schema 示例：

详细标准化结构见：
`docs/t3_standardized_test_data_structure.zh.md`。

```json
{
  "record_id": "USERTEST:POMGNT1:23689641:NM_017739.4:c.1319T>G",
  "split": "acceptance_gold_candidate",
  "source": {
    "dataset": "user_test_set",
    "raw_row_index": 0,
    "artifact_dir": "/Users/roger/Downloads/...",
    "workbook": "POMGNT1_c.1319T_G_PM3汇总.xlsx",
    "raw_fields": {}
  },
  "paper": {
    "pmid": "23689641",
    "doi": null,
    "title": "Novel POMGnT1 mutations cause muscle-eye-brain disease in Chinese patients.",
    "formats_available": ["xlsx_summary", "pdf"],
    "pdf_available": true,
    "pdf_path": "/Users/roger/Downloads/.../PubMed23689641.pdf",
    "parse_status": "not_loaded"
  },
  "condition": {
    "raw": "肌 - 眼 - 脑病",
    "name": "muscle-eye-brain disease",
    "normalized_id": null
  },
  "target_variant": {
    "raw": "NM_017739.4:c.1319T>G (p.Leu440Arg)",
    "transcript": "NM_017739.4",
    "gene": "POMGNT1",
    "cdna": "c.1319T>G",
    "protein": "p.Leu440Arg",
    "mention_status": "mentioned"
  },
  "phenotype_summary": "...",
  "family_context": "...",
  "cis_variants": [],
  "pm3_assertion": {
    "criterion": "PM3-Strong",
    "patient_count": 1,
    "patient_count_raw": "1",
    "patient_count_status": "parsed",
    "in_trans_status": "reported"
  },
  "partner_variants": [
    {
      "raw": "c.1896+1G>C",
      "transcript": null,
      "gene": "POMGNT1",
      "cdna": "c.1896+1G>C",
      "protein": null,
      "phase_relation": "in_trans",
      "evidence_status": "from_xlsx_curated_summary"
    }
  ],
  "cases": [],
  "evidence": [
    {
      "evidence_id": "comment-0",
      "source_type": "expert_comment",
      "text": "位置：表1第一行（病例1），基因变异列明确记载c.1319T>G。",
      "pmid": "23689641",
      "source_index": null,
      "raw_table_row_text": null,
      "chunk_id": null,
      "table_id": null,
      "row_id": null,
      "span": null
    }
  ],
  "review": {
    "status": "unreviewed",
    "issues": []
  }
}
```

## 5. 字段规范化规则

| 源字段 | 规范化目标 | 规则 |
| --- | --- | --- |
| `CinGen ID` | `target_variant.clingen_id` | 在 `source.raw_fields` 保留原始拼写；规范化字段名使用 `clingen_id`。 |
| `Variant Name` | `target_variant.raw`, `transcript`, `cdna` | 尽量按第一个 `:` 拆分。 |
| `Condition` | `condition.raw`, `condition.name` | `name` 小写并 trim；原文保留到 `raw`。 |
| `Criterion` | `pm3_assertion.criterion` | 保留原始枚举；暂不合并 plain `PM3`。 |
| `PMID` | `paper.pmid` | 转成字符串。 |
| `Raw Comment` | `evidence[0].text` | 未来可补 cleaned text；原文保留到 `source.raw_fields`。 |
| `Number of Patients` | `patient_count`, `patient_count_raw`, `patient_count_status` | 整数为 `parsed`；`NA` 为 null + `not_reported`；`err` 为 null + `error`。 |
| `In trans Variants` | `partner_variants[]` | 解析为 raw、cDNA、protein、transcript、relation。 |
| `labels` | `split` | 保留原值，但 `others` 不进入正常 train/eval。 |

用户 XLSX mapping：

| 源字段 | 规范化目标 | 规则 |
| --- | --- | --- |
| 目录名 | `target_variant.raw`, `target_variant.gene`, `source.artifact_dir` | 从目录名解析目标位点；保留精确路径。 |
| `PMID` | `paper.pmid` | 转成字符串，并尝试对齐 `PubMed<PMID>.pdf`。 |
| `是否提及此位点` | `target_variant.mention_status` | `是` 映射为 `mentioned`，`否` 映射为 `not_mentioned`；保留原值。 |
| `患者数` | `pm3_assertion.patient_count`, `patient_count_raw`, `patient_count_status` | 能解析整数则解析；否则保留 raw summary text 和 status。 |
| `反式(trans)位点` | `partner_variants[]` | 先保留 raw text；结构化解析 best-effort。 |
| `顺式(cis)位点` | `cis_variants[]` | 先保留 raw text；结构化解析 best-effort。 |
| `来源索引...` | `evidence[].source_index` | 保留，用于 citation/evidence grounding。 |
| `表格原始行内容...` | `evidence[].raw_table_row_text` | 保留，用于审计和过滤假阳性。 |
| `AI提取过程` | `source.ai_extraction_trace` | 作为 provenance 保留，不直接视为 gold evidence。 |

## 6. 质量门槛

任何规范化数据用于评测或训练前，都应先通过这些检查。

| 检查项 | 要求 | 失败处理 |
| --- | --- | --- |
| 必需 ID | `record_id`、`paper.pmid`、`target_variant.raw`、`split` 存在 | 拒绝记录 |
| Split 枚举 | split 属于 `eval`、`fine-tune`、`others` 或未来批准值 | 拒绝记录 |
| Criterion 枚举 | criterion 属于已知 PM3 标签 | 标记待审核 |
| 患者数 | 数值为 int，或 null 且有明确 status | 拒绝记录 |
| PMID 泄漏 | 同一 PMID 不能跨正常 split 出现 | 拒绝 split 文件 |
| PDF 对齐 | 每条 XLSX PMID 记录是否存在本地 `PubMed<PMID>.pdf` | 缺 PDF 则标记 |
| 候选 PDF triage | XLSX 中未出现的 PDF 列为 uncurated candidates | 标记待 triage |
| Evidence text | 用户 XLSX 行应尽量保留 summary/source-index evidence 文本 | 缺失则标记 |
| Partner variants | 即使解析失败，也必须保留 raw string | 标记但不拒绝 |
| 编码问题 | 检测 comment 中的乱码标记 | 标记待清洗 |
| 来源追溯 | 能恢复原始行号和 raw fields | 拒绝记录 |

## 7. 拆分策略

### 7.1 第一版拆分

对用户提供目录：

- 将 XLSX 整理行视为 acceptance/gold candidates。
- 在领域同学确认前，不把这些行混入训练数据。
- 按目录级目标位点单独跟踪：一个 POMGNT1 target，一个 CFTR target。
- XLSX 中没有出现的 PDF 视为待 triage 的候选论文。
- XLSX 有记录但无本地 PDF 的 PMID，标记为需要补 artifact 或设为
  non-PDF evidence status。

对辅助 PM3-Bench，仅在后续使用时：

- `eval`：评测候选集
- `fine-tune`：训练/验证候选集
- `others`：parser/data-quality 诊断集

然后审计 PMID overlap。如果某个 PMID 跨正常 train/eval 边界出现，则
把整个 PMID cluster 分配到同一个 split。

### 7.2 后续辅助 PM3-Bench 拆分

如果后续把 PM3-Bench 作为辅助 benchmark/training reference，再从
`fine-tune` 中按 PMID 分组创建 validation：

1. 按 PMID group rows。
2. 尽量按 PM3 criterion 和 condition 分层。
3. 固定 hold out 一个 validation set。
4. 同一 PMID 的所有行必须留在同一 split。

### 7.3 Gold Regression Set

建立一个小规模、人工审核、带完整 evidence grounding 的集合：

| 候选 | 原因 |
| --- | --- |
| 用户 POMGNT1 整理行 | 小规模、适合人工检查的第一批 acceptance set |
| 用户 CFTR 整理行 | 富含 cis/trans complex-allele 场景 |
| PubMed 23689641 | 同时存在于用户目录和仓库 fixture 中，已有 XML、Markdown、PDF 和 MinerU metadata |
| 辅助 PM3-Bench 高行数 PMID | 后续可选，用于压测一篇论文对应多条 variant rows 的场景 |
| 辅助 PM3-Bench 低质量记录 | 后续可选，用于覆盖 `NA`、`err`、乱码或解析失败 |

## 8. 标注计划

### 8.1 最小标注

第一版可用数据集需要：

- 从目录/workbook 确认 target variant parse。
- 确认每行是否提及目标位点。
- 确认 PM3 conclusion/summary。用户 XLSX 不一定直接提供 ACMG criterion-strength enum。
- 确认 patient count status。
- 保留原始中文整理字段。
- 保留 raw in-trans 和 cis variant strings。

### 8.2 结构化标注

更强模型训练需要：

- 将 partner variants 解析为 cDNA/protein/transcript 字段。
- 标记每个 partner 是否确实与 target in trans。
- 当原文存在时，抽取 case/family ID。
- 当论文 artifact 存在时，把 evidence 链接到 chunk/table/row。

### 8.3 人工审核状态

建议使用以下 review status：

| 状态 | 含义 |
| --- | --- |
| `unreviewed` | 仅自动转换，未人工审核 |
| `needs_review` | converter 检测到质量问题 |
| `reviewed_pass` | 人工审核通过 |
| `reviewed_fixed` | 人工修正过一个或多个字段 |
| `excluded` | 不适合当前 train/eval 任务 |

## 9. 执行阶段

### Phase 0：Schema 对齐

交付物：

- 和算法同学确认本计划。
- 冻结第一版 normalized schema。
- 确认两个 Downloads 目录是 T3 primary acceptance/gold seed。
- 决定如何处理无强度 plain `PM3`。
- 决定第一版训练目标是 strict JSON，还是 JSON 加 rationale。

退出标准：

- Schema 字段和枚举已确认。
- Split policy 已确认。
- Required / optional labels 已标注。

### Phase 1：数据审计包

交付物：

- 两个用户 XLSX 的字段盘点表；PM3-Bench 仅在需要时作为辅助附录。
- 两个用户目录的 PDF/XLSX 对齐报告。
- 按 split 和 criterion 的标签分布。
- PMID 重复和泄漏报告。
- 患者数、乱码、空 partner variants 的质量问题报告。

退出标准：

- 每个已知质量问题都有处理状态：block、flag 或 ignore。

### Phase 2：规范化数据集设计

交付物：

- JSONL schema 文档。
- normal、missing patient count、parsing-error、`others` 等示例记录。
- validation rules。

退出标准：

- 算法和工程都确认该 schema 能支持评测和训练数据生成。

### Phase 3：Converter 和 Validator 实现

本阶段不属于当前 no-code pass。

schema 批准后的计划交付物：

- 用户 XLSX 到 normalized JSONL 的 converter。
- PDF/XLSX alignment report generator。
- 可选 PM3-Bench 到 normalized JSONL adapter，并明确标为 auxiliary。
- Validation report generator。
- PMID-level split checker。
- Quality issue summary output。

退出标准：

- 转换可复现。
- 无效记录能被拒绝或以明确原因标记。

### Phase 4：Gold Evidence Set

交付物：

- 用户 POMGNT1 和 CFTR 整理行作为可人工审核的 gold candidates。
- PubMed 23689641 人工审核 gold record。
- 尽可能提供 chunk/table/row evidence IDs。
- 用于回归测试的 expected extraction output。

退出标准：

- 至少一篇完整论文能同时评估最终 PM3 answer 和 evidence grounding。

### Phase 5：验收/评测打包

交付物：

- `acceptance_gold_candidates.jsonl`。
- `pdf_xlsx_alignment.md`。
- `quality_issues.md`。
- Dataset card，说明来源目录、schema、已知限制和 artifact 对齐策略。
- 版本化 manifest，包含行数、source checksum 和生成日期。

退出标准：

- 算法和工程评审可以直接消费用户测试集数据包，不需要临时猜字段含义。

## 10. 推荐文件布局

未来的数据产物可使用以下布局：

```text
data_prepared/
  user_test_set_v1/
    README.md
    manifest.json
    schema.json
    acceptance_gold_candidates.jsonl
    reports/
      field_inventory.md
      pdf_xlsx_alignment.md
      quality_issues.md
    gold/
      pubmed_23689641.json
  auxiliary_pm3_bench_v1_optional/
    README.md
    manifest.json
    schema.json
    train.jsonl
    valid.jsonl
    eval.jsonl
    diagnostic_others.jsonl
```

当前这轮是 documentation-only，因此不创建 `data_prepared/` 目录。

## 11. 算法同学评审 Checklist

- 确认两个 Downloads 目录是 primary user test set。
- 确认 variant-paper pair 是否是合适的主记录单元。
- 确认来自 18 列用户 XLSX schema 的第一版必需标签。
- 确认 criterion enum 的处理，尤其是 plain `PM3`。
- 确认 patient-count prediction 是训练目标、metadata，还是两者都是。
- 确认 partner-variant parsing 应该严格失败还是 best-effort。
- 确认用户 gold seed 不进入训练集。
- 确认 evidence grounding 是所有用户整理行必需，还是只对第一批审核子集必需。
- 确认期望的模型输出格式。

## 12. 立即下一步

1. 评审 `docs/t3_brief_report.zh.md`、`docs/data_inventory_t3.md` 和本文档。
2. 确认两个 Downloads 目录为 T3 primary data。
3. 和算法同学讨论 D1-D10。
4. 冻结 schema v0.1。
5. schema 批准后，再实现 user-XLSX converter、PDF alignment report 和 validator。
6. 将 PubMed 23689641 建成第一条人工审核的 gold evidence record。

## 13. 当前非目标

- 本轮不改代码。
- 本轮不生成训练文件。
- 本轮不做人工重标注。
- 本轮不下载外部数据。
- 本轮不把仓库内现有数据提升为 T3 主数据。
