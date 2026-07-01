# T3 标准化测试数据结构建议

> 日期：2026-06-21
> 适用范围：两个用户提供的 PM3 测试集目录。
> 核心原则：用户目录是主数据；仓库内现有数据只作为辅助参考/回归数据。

## 1. 调研依据

参考主流训练/评测数据组织方式，可以归纳出几个稳定做法：

| 来源 | 对 T3 的启发 |
| --- | --- |
| OpenAI supervised fine-tuning 文档 | 训练文件通常用 JSONL，每行是一个完整样本；chat fine-tuning 使用 `messages` 格式。 |
| OpenAI Evals 文档 | 评测数据可以是 JSONL，并且需要和 eval schema 对齐；也就是“样本结构”和“评分器/评测逻辑”要分开。 |
| Hugging Face Datasets 文档 | 数据集通常有明确 features/schema、split、可处理/导出；数据文件和 dataset card 分开管理。 |
| Hugging Face Dataset Cards | 数据集应配 README/dataset card，说明用途、字段、限制、偏差和使用方式。 |
| Google Data Cards | 数据卡强调跨生命周期记录数据来源、用途、风险、采集/标注过程和限制。 |
| MLCommons Croissant | ML-ready dataset 需要标准化 metadata，以便可发现、可治理、可复用。 |

结论：T3 不应该只有一个“训练 JSONL”。更稳的结构是：

1. **源数据层**：记录用户目录、xlsx、PDF、原始字段。
2. **规范化标签层**：把每个 xlsx 行转成 target variant-paper pair。
3. **artifact 对齐层**：记录 PMID 是否有 PDF、PDF 路径、是否已解析。
4. **评测样本层**：给模型的输入、期望输出、评分规则。
5. **训练样本层**：可选，等 gold 数据确认后再从评测/标签层派生。
6. **数据卡/manifest 层**：记录版本、来源、限制、checksum、统计。

## 2. 推荐文件布局

第一版只围绕两个用户目录，不把 PM3-Bench 放进主路径。

```text
data_prepared/
  user_pm3_testset_v0_1/
    README.md
    manifest.json
    schema/
      record.schema.json
      eval_sample.schema.json
      alignment.schema.json
    source_inventory/
      folders.json
      xlsx_columns.json
      pdf_inventory.jsonl
      pdf_xlsx_alignment.jsonl
    records/
      acceptance_gold_candidates.jsonl
      review_queue.jsonl
      excluded_or_unresolved.jsonl
    eval/
      pm3_extraction_eval.jsonl
      evidence_grounding_eval.jsonl
      negative_mention_eval.jsonl
    training_optional/
      README.md
      supervised_chat_train.jsonl
      supervised_chat_valid.jsonl
    reports/
      field_inventory.md
      pdf_xlsx_alignment.md
      quality_issues.md
      dataset_card.md
```

说明：

- `records/acceptance_gold_candidates.jsonl` 是第一核心产物。
- `eval/*.jsonl` 是给评测 runner 用的样本，不直接等同于标签源。
- `training_optional/` 只有在人工确认 gold/silver 边界后再生成。
- PM3-Bench 若后续适配，应放在 `data_prepared/auxiliary_pm3_bench_*`，不要混入主目录。

## 3. 核心数据单元

推荐主记录单位：

```text
target_variant + PMID = 一条标准记录
```

理由：

- 和用户 xlsx 的自然行结构一致。
- 能承载“是否提及此位点”“患者数”“trans/cis 位点”“总结”等标签。
- 能对齐 `PubMed<PMID>.pdf`。
- 后续可以派生出训练样本、评测样本、证据定位样本。

## 4. 标准记录 Schema

建议文件：`records/acceptance_gold_candidates.jsonl`

每行一个 JSON object：

```json
{
  "record_id": "USERTEST:POMGNT1:23689641:NM_017739.4:c.1319T>G",
  "dataset_role": "acceptance_gold_candidate",
  "curation_status": "xlsx_curated_needs_review",
  "target": {
    "folder_id": "POMGNT1_c1319T_G",
    "gene": "POMGNT1",
    "transcript": "NM_017739.4",
    "variant_cdna": "c.1319T>G",
    "variant_protein": "p.Leu440Arg",
    "variant_aliases": ["p.L440R"],
    "raw_folder_name": "NM_017739.4 (POMGNT1)  c.1319TG (p.Leu440Arg) 2"
  },
  "paper": {
    "pmid": "23689641",
    "title": "Novel POMGnT1 mutations cause muscle-eye-brain disease in Chinese patients.",
    "authors_raw": "Hui Jiao ...",
    "pdf_available": true,
    "pdf_path": "/Users/roger/Downloads/.../PubMed23689641.pdf",
    "pdf_pages": 12,
    "derived_artifacts": {
      "markdown_path": null,
      "xml_path": null,
      "tables_path": null
    }
  },
  "labels": {
    "mentions_target_variant": true,
    "patient_count": 1,
    "patient_count_raw": "1",
    "patient_count_status": "parsed",
    "disease_raw": "肌 - 眼 - 脑病",
    "phenotype_summary": "...",
    "family_context": "...",
    "author_pathogenicity_conclusion": "致病变异",
    "zygosity_or_allele_state": "复合杂合",
    "in_trans_variants": [
      {
        "raw": "c.1896+1G>C",
        "gene": "POMGNT1",
        "cdna": "c.1896+1G>C",
        "protein": null,
        "phase_relation": "in_trans",
        "phase_evidence": "parental testing reported"
      }
    ],
    "cis_variants": [],
    "pm3_summary": "该变异已在至少1名患有肌-眼-脑病的个体中被检测到..."
  },
  "evidence": {
    "source_index_raw": "位置：表1第一行（病例1）...",
    "raw_table_row_text": "Case number|Sex/age|...",
    "paper_background_summary": "本研究针对国内少见的肌-眼-脑病...",
    "evidence_spans": [],
    "grounding_status": "xlsx_source_index_only"
  },
  "provenance": {
    "source_type": "user_xlsx",
    "xlsx_path": "/Users/roger/Downloads/.../POMGNT1_c.1319T_G_PM3汇总.xlsx",
    "sheet_name": "Sheet1",
    "row_number_1based": 3,
    "raw_xlsx_row": {},
    "ai_extraction_trace_raw": "豆包：..."
  },
  "review": {
    "review_status": "unreviewed",
    "reviewer": null,
    "review_notes": [],
    "quality_flags": []
  }
}
```

## 5. PDF/XLSX 对齐 Schema

建议文件：`source_inventory/pdf_xlsx_alignment.jsonl`

每行一个 PMID 在某个用户目录下的对齐状态：

```json
{
  "folder_id": "POMGNT1_c1319T_G",
  "pmid": "21983716",
  "in_xlsx": true,
  "xlsx_row_numbers": [2],
  "pdf_available": false,
  "pdf_path": null,
  "alignment_status": "xlsx_label_without_local_pdf",
  "action_needed": "backfill_pdf_or_mark_non_pdf_evidence",
  "notes": "Curated in POMGNT1 summary workbook but no PubMed21983716.pdf found in folder."
}
```

建议枚举：

| `alignment_status` | 含义 |
| --- | --- |
| `aligned_xlsx_and_pdf` | xlsx 有整理行，本地也有对应 PDF |
| `xlsx_label_without_local_pdf` | xlsx 有整理行，但缺 PDF |
| `pdf_without_xlsx_label` | 有 PDF，但尚未进入 xlsx 汇总 |
| `negative_or_not_mentioned` | xlsx 明确标注未提及目标位点 |
| `needs_manual_triage` | 需要人工判断是否纳入 |

## 6. 评测样本 Schema

标签记录和评测样本要分开。标签记录是“事实库”，评测样本是“怎么问模型、怎么打分”。

建议文件：`eval/pm3_extraction_eval.jsonl`

```json
{
  "eval_id": "EVAL:PM3:POMGNT1:23689641:summary",
  "record_id": "USERTEST:POMGNT1:23689641:NM_017739.4:c.1319T>G",
  "task_type": "pm3_structured_extraction",
  "input": {
    "target_variant": "NM_017739.4:c.1319T>G (p.Leu440Arg)",
    "paper_artifact": {
      "pmid": "23689641",
      "pdf_path": "/Users/roger/Downloads/.../PubMed23689641.pdf",
      "markdown_path": null
    },
    "prompt_context_policy": "model_may_use_pdf_or_converted_markdown"
  },
  "expected": {
    "mentions_target_variant": true,
    "patient_count": 1,
    "in_trans_variants_raw_any": ["c.1896+1G>C", "c.1896-1G>C"],
    "cis_variants_raw_any": [],
    "required_summary_facts": [
      "muscle-eye-brain disease",
      "compound heterozygous",
      "parental testing or family segregation supports trans phase"
    ]
  },
  "scoring": {
    "grader_type": "hybrid_rule_and_human_review",
    "must_match_fields": [
      "mentions_target_variant",
      "patient_count"
    ],
    "semantic_fields": [
      "in_trans_variants_raw_any",
      "required_summary_facts"
    ],
    "evidence_required": true
  }
}
```

## 7. 训练样本 Schema

训练样本应从已审核的标准记录派生，不要直接从原始 xlsx 盲目生成。

适配 OpenAI chat fine-tuning 时，可以生成：

```json
{
  "messages": [
    {
      "role": "system",
      "content": "You extract PM3 evidence from biomedical papers and return strict JSON."
    },
    {
      "role": "user",
      "content": "Target variant: NM_017739.4:c.1319T>G (p.Leu440Arg)\nPaper PMID: 23689641\nExtract PM3 evidence..."
    },
    {
      "role": "assistant",
      "content": "{\"mentions_target_variant\":true,\"patient_count\":1,\"in_trans_variants\":[{\"raw\":\"c.1896+1G>C\"}],\"summary\":\"...\"}"
    }
  ],
  "metadata": {
    "record_id": "USERTEST:POMGNT1:23689641:NM_017739.4:c.1319T>G",
    "source_quality": "reviewed_pass",
    "do_not_train_if": ["unreviewed", "missing_pdf_without_review"]
  }
}
```

注意：

- 训练 JSONL 是模型平台格式，不应替代主标签 JSONL。
- 小样本阶段，建议先做 eval/acceptance，不急着训练。
- 如果训练，至少拆出 `train` / `valid`，且同一 PMID 不要跨 split。

## 8. Manifest / Dataset Card

建议文件：`manifest.json`

```json
{
  "dataset_id": "user_pm3_testset_v0_1",
  "version": "0.1.0",
  "created_at": "2026-06-21",
  "primary_sources": [
    "/Users/roger/Downloads/NM_017739.4 (POMGNT1)  c.1319TG (p.Leu440Arg) 2",
    "/Users/roger/Downloads/NM_000492.4 (CFTR)  c.220CT (p.Arg74Trp), exon3"
  ],
  "auxiliary_sources": [
    "benchmarks/PM3_Bench_data.json",
    "tests/fixtures/PubMed23689641_markdown.md",
    "tests/fixtures/23689641.xml"
  ],
  "counts": {
    "folders": 2,
    "curated_xlsx_rows": 8,
    "local_pdfs": 33
  },
  "policy": {
    "primary_data_rule": "Only the two user folders define the first T3 schema.",
    "repo_data_rule": "Repository-local data is auxiliary and must not override user labels.",
    "training_rule": "Training samples can only be derived from reviewed records."
  }
}
```

建议文件：`reports/dataset_card.md`

必须写清楚：

- 数据来源：两个用户目录。
- 数据用途：PM3 抽取验收测试、后续评测集构建。
- 非用途：第一版不直接训练、不把 PM3-Bench 作为主数据。
- 标注来源：xlsx 人工/AI 整理字段。
- 已知限制：PDF/XLSX 不完全对齐、部分字段半结构化、部分证据未定位到精确 span。
- 审核状态：哪些记录 reviewed，哪些只是 candidate。

## 9. 推荐第一版产物

优先做这 4 个文件：

1. `source_inventory/pdf_xlsx_alignment.jsonl`
2. `records/acceptance_gold_candidates.jsonl`
3. `reports/quality_issues.md`
4. `eval/pm3_extraction_eval.jsonl`

暂缓：

- `training_optional/supervised_chat_train.jsonl`
- PM3-Bench adapter
- 大规模 split

原因：当前最重要的是把用户真实测试集变成稳定、可验收、可回溯的数据结构，而不是先训练。

## 10. 一句话标准

第一版 T3 标准化测试数据结构应该满足：

> 每个样本都能回答：这是哪个目标位点、哪篇文献、来自哪个用户目录和 xlsx 行、有没有对应 PDF、标准标签是什么、证据在哪里、审核状态是什么、能否进入评测或训练。
