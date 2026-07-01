# T3 Detailed Plan: Test Data Review and Data-Structure Optimization

> Date: 2026-06-21
> Status: Draft for algorithm-team review
> Rule for this pass: documentation only; no code changes.

## 0. Objective

T3 should turn the two user-provided test folders into a clean foundation for
PM3 acceptance testing and later evaluation-data construction. Repository-local
data is auxiliary only.

The goal is not just to count files. The goal is to define the dataset unit,
schema, quality gates, split policy, and annotation path so later engineering
work can be implemented without changing the data contract repeatedly.

## 1. Current Data Baseline

| Dataset / artifact | Current path | Current role | Notes |
| --- | --- | --- | --- |
| User test set: POMGNT1 | `/Users/roger/Downloads/NM_017739.4 (POMGNT1)  c.1319TG (p.Leu440Arg) 2` | Primary acceptance/gold seed | 1 XLSX, 2 PDFs, 3 curated rows |
| User test set: CFTR | `/Users/roger/Downloads/NM_000492.4 (CFTR)  c.220CT (p.Arg74Trp), exon3` | Primary acceptance/gold seed | 1 XLSX, 31 PDFs, 5 curated rows |
| PM3-Bench | `benchmarks/PM3_Bench_data.json` | Auxiliary benchmark reference | 1,027 variant-literature rows |
| PM3-Bench docs | `benchmarks/README.md`, `benchmarks/README.zh.md` | Auxiliary field descriptions | README says `ClinGen ID`, data uses `CinGen ID` |
| PubMed BioC XML fixture | `tests/fixtures/23689641.xml`, `data/pdf_convert/23689641.xml` | Auxiliary parser/query regression data | One full paper fixture |
| PubMed MinerU Markdown fixture | `tests/fixtures/PubMed23689641_markdown.md`, `data/pdf_convert/MinerU_markdown_PubMed23689641_2067159189227929600.md` | Auxiliary chunking/evidence UI fixture | 46,041 chars, 15 headings, 2 HTML tables |
| MinerU metadata | `data/pdf_convert/MinerU_PubMed23689641__20260617081534.json` | Auxiliary conversion debug metadata | 12 `pdf_info` blocks |
| Synthetic Markdown | `tests/test_synthetic_markdown.py`, `tests/benchmark_chunk_quality.py` | Auxiliary chunker edge-case coverage | Generated fixtures, not real PM3 labels |

Observed user test-set counts:

| Metric | POMGNT1 | CFTR |
| --- | ---: | ---: |
| Curated XLSX rows | 3 | 5 |
| Local PDFs | 2 | 31 |
| XLSX sheets | 1 | 2 |
| Mention-positive curated rows | 2 | 5 |
| Mention-negative / not-applicable rows | 1 | 0 |

Auxiliary PM3-Bench counts:

| Metric | Value |
| --- | ---: |
| Rows | 1,027 |
| Unique PMIDs | 467 |
| Unique target variants | 752 |
| Unique normalized conditions | 22 |
| `fine-tune` rows | 760 |
| `eval` rows | 195 |
| `others` rows | 72 |
| PMIDs with multiple rows | 155 |

## 2. Decisions to Make With Algorithm Team

These should be settled before implementation.

| ID | Decision | Recommended default |
| --- | --- | --- |
| D1 | Primary T3 dataset | The two Downloads folders, not PM3-Bench |
| D2 | Acceptance/evaluation unit | One target variant-paper pair per record |
| D3 | Artifact alignment boundary | Align XLSX rows and PDFs by PMID |
| D4 | Treatment of user folders | Gold/acceptance test seed first, not training data |
| D5 | Treatment of repo-local data | Auxiliary only; do not let it redefine user-folder labels or schema priorities |
| D6 | Output style for models | Structured JSON first; rationale text optional |
| D7 | Required first-version labels | Target variant, mention status, patient count, disease, phenotype, family context, zygosity, trans/cis sites, source evidence, final summary |
| D8 | Handling of unresolved patient counts | Null numeric value plus explicit status |
| D9 | Handling of `PM3` without strength | Keep as separate class until domain owner confirms mapping |
| D10 | Evidence grounding requirement | Required for user-folder gold rows; optional for later auxiliary adapters |

## 3. Proposed Dataset Units

### 3.1 Primary Record

Use one JSONL record per target variant-paper pair.

This is defined from the user-provided XLSX row shape. PM3-Bench happens to be
adaptable later, but it is not the source of the first T3 schema.

### 3.2 Nested Objects

Each primary record should support these layers:

| Layer | Purpose |
| --- | --- |
| `source` | Trace original dataset, row index, raw fields, and conversion metadata |
| `paper` | PMID, DOI, title, available formats, parsing status |
| `condition` | Raw and normalized disease/phenotype |
| `target_variant` | Raw variant plus parsed transcript/cDNA/protein/gene fields |
| `pm3_assertion` | Criterion, patient count, in-trans summary, assertion source |
| `partner_variants` | Structured in-trans or candidate second-allele variants |
| `cases` | Optional case/family-level evidence |
| `evidence` | Comment, chunk, table, row, or quote-level support |
| `review` | Human-review status and data-quality flags |

### 3.3 User Test-Set Specific Fields

The user-provided XLSX files include fields that should be preserved even when
they are later normalized:

| Original XLSX concept | Normalized field |
| --- | --- |
| `是否提及此位点` | `target_variant.mention_status` |
| `患者年龄` | `cases[].age` or `patient_age_summary` |
| `患者临床疾病` | `condition.raw`, `condition.name` |
| `患者临床表型` | `phenotype_summary` |
| `家系情况` | `family_context` |
| `致病性...` | `pathogenicity_author_conclusion` |
| `关联合子状态` | `pm3_assertion.zygosity_or_allele_state` |
| `反式(trans)位点` | `partner_variants[]` with `phase_relation = in_trans` |
| `顺式(cis)位点` | `cis_variants[]` |
| `来源索引...` | `evidence[].source_index` |
| `表格原始行内容...` | `evidence[].raw_table_row_text` |
| `文献背景...` | `paper.background_summary` |
| `总结...` | `pm3_assertion.final_summary` |
| `AI提取过程` | `source.ai_extraction_trace` |

## 4. Proposed Normalized Schema

First version schema:

Detailed standardized structure:
`docs/t3_standardized_test_data_structure.zh.md`.

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

## 5. Field Normalization Rules

| Source field | Normalized target | Rule |
| --- | --- | --- |
| `CinGen ID` | `target_variant.clingen_id` | Preserve raw misspelled source key in `source.raw_fields`; normalize target name to `clingen_id`. |
| `Variant Name` | `target_variant.raw`, `transcript`, `cdna` | Split on first `:` when possible. |
| `Condition` | `condition.raw`, `condition.name` | Lowercase/trim for `name`; keep original in `raw`. |
| `Criterion` | `pm3_assertion.criterion` | Keep original enum; do not collapse `PM3` yet. |
| `PMID` | `paper.pmid` | Convert to string. |
| `Raw Comment` | `evidence[0].text` | Store cleaned text later; keep raw in `source.raw_fields`. |
| `Number of Patients` | `patient_count`, `patient_count_raw`, `patient_count_status` | Integers become `parsed`; `NA` becomes null + `not_reported`; `err` becomes null + `error`. |
| `In trans Variants` | `partner_variants[]` | Parse into raw, cDNA, protein, transcript, relation. |
| `labels` | `split` | Preserve values, but keep `others` out of normal train/eval. |

User XLSX mapping:

| Source field | Normalized target | Rule |
| --- | --- | --- |
| Folder name | `target_variant.raw`, `target_variant.gene`, `source.artifact_dir` | Parse target variant from folder name; preserve exact path. |
| `PMID` | `paper.pmid` | Convert to string and align with `PubMed<PMID>.pdf` if present. |
| `是否提及此位点` | `target_variant.mention_status` | Map `是` to `mentioned`, `否` to `not_mentioned`; preserve raw value. |
| `患者数` | `pm3_assertion.patient_count`, `patient_count_raw`, `patient_count_status` | Parse integers where possible; otherwise keep raw summary text and status. |
| `反式(trans)位点` | `partner_variants[]` | Preserve raw text first; structured parsing is best-effort. |
| `顺式(cis)位点` | `cis_variants[]` | Preserve raw text first; structured parsing is best-effort. |
| `来源索引...` | `evidence[].source_index` | Preserve for citation/evidence grounding. |
| `表格原始行内容...` | `evidence[].raw_table_row_text` | Preserve for audit and false-positive filtering. |
| `AI提取过程` | `source.ai_extraction_trace` | Preserve as provenance, not as gold evidence. |

## 6. Quality Gates

Before any normalized dataset is used for evaluation or training, run these
checks.

| Gate | Requirement | Failure action |
| --- | --- | --- |
| Required IDs | `record_id`, `paper.pmid`, `target_variant.raw`, `split` present | Reject record |
| Split enum | Split is one of `eval`, `fine-tune`, `others`, or future approved value | Reject record |
| Criterion enum | Criterion is one of known PM3 labels | Flag for review |
| Patient count | Numeric value is int or null with explicit status | Reject record |
| PMID leakage | No PMID appears in more than one normal split | Reject split file |
| PDF alignment | Each curated XLSX PMID records whether a local `PubMed<PMID>.pdf` exists | Flag missing PDF |
| Candidate PDF triage | PDFs not present in the XLSX are listed as uncurated candidates | Flag for triage |
| Evidence text | User XLSX rows must preserve summary/source-index evidence text where available | Flag missing evidence fields |
| Partner variants | Preserve raw string even if parsing fails | Flag, do not reject |
| Encoding | Detect mojibake markers in comments | Flag for cleanup |
| Source traceability | Original row index and raw fields are recoverable | Reject record |

## 7. Split Strategy

### 7.1 First-Version Split

For the user-provided folders:

- Treat curated XLSX rows as acceptance/gold candidates.
- Do not split them into training data until domain review confirms they can be
  used as labels.
- Track folder-level target variants separately: one POMGNT1 target and one
  CFTR target.
- Treat PDFs absent from the XLSX as candidate papers requiring triage.
- Treat XLSX rows with no matching PDF as label rows requiring artifact
  backfill or non-PDF evidence status.

For auxiliary PM3-Bench, only if used later:

- `eval`: evaluation candidate set
- `fine-tune`: training/validation candidate set
- `others`: parser/data-quality diagnostic set

Then audit PMID overlap. If any PMID appears across normal train/eval
boundaries, assign the full PMID cluster to one split.

### 7.2 Auxiliary PM3-Bench Split, If Used Later

If PM3-Bench is later adapted as an auxiliary benchmark/training reference,
create validation from `fine-tune` by PMID-level grouping:

1. Group rows by PMID.
2. Stratify approximately by PM3 criterion and condition.
3. Hold out a fixed validation set.
4. Keep all rows from the same PMID together.

### 7.3 Gold Regression Set

Build a small manually reviewed set with full evidence grounding:

| Candidate | Why |
| --- | --- |
| User POMGNT1 curated rows | Small, manually inspectable first acceptance set |
| User CFTR curated rows | Rich cis/trans complex-allele cases |
| PubMed 23689641 | Available in user folder and repo fixtures as XML, Markdown, PDF, and MinerU metadata |
| Auxiliary PM3-Bench high-row-count PMIDs | Optional later stress-test for multiple variant rows per paper |
| Auxiliary low-quality PM3-Bench rows | Optional later checks for `NA`, `err`, mojibake, or parsing failures |

## 8. Annotation Plan

### 8.1 Minimal Annotation

Required for first usable dataset:

- Confirm target variant parse from folder/workbook.
- Confirm whether each row mentions the target variant.
- Confirm PM3 conclusion/summary. User XLSX does not always provide an ACMG
  criterion-strength enum directly.
- Confirm patient count status.
- Preserve raw Chinese curated fields.
- Preserve raw in-trans and cis variant strings.

### 8.2 Structured Annotation

Required for stronger model training:

- Parse partner variants into cDNA/protein/transcript fields.
- Mark whether each partner is actually in trans with the target.
- Extract case/family IDs when present.
- Link evidence to paper chunk/table/row when paper artifact exists.

### 8.3 Human Review States

Use these review statuses:

| Status | Meaning |
| --- | --- |
| `unreviewed` | Automatically converted only |
| `needs_review` | Converter detected quality issue |
| `reviewed_pass` | Human reviewed and accepted |
| `reviewed_fixed` | Human corrected one or more fields |
| `excluded` | Not suitable for current train/eval task |

## 9. Execution Phases

### Phase 0: Schema Agreement

Deliverables:

- Confirm this plan with algorithm team.
- Freeze first-version normalized schema.
- Confirm the two Downloads folders are the primary T3 acceptance/gold seed.
- Decide how to handle `PM3` without strength.
- Decide whether first training target is strict JSON only or JSON plus rationale.

Exit criteria:

- Schema fields and enums are approved.
- Split policy is approved.
- Required vs optional labels are marked.

### Phase 1: Data Audit Package

Deliverables:

- A field inventory table for both user XLSX workbooks, with PM3-Bench only in
  an auxiliary appendix if needed.
- A PDF/XLSX alignment report for both user folders.
- Label distribution by split and criterion.
- PMID duplication and leakage report.
- Quality issue report for patient counts, mojibake, empty partner variants.

Exit criteria:

- Every known quality issue has a status: block, flag, or ignore.

### Phase 2: Normalized Dataset Design

Deliverables:

- JSONL schema documentation.
- Example records for normal, missing patient count, parsing-error, and `others`
  cases.
- Validation rules.

Exit criteria:

- Algorithm and engineering agree the schema can support evaluation and
  training-data generation.

### Phase 3: Converter and Validator Implementation

This phase is intentionally not part of the current no-code pass.

Planned deliverables after approval:

- User XLSX to normalized JSONL converter.
- PDF/XLSX alignment report generator.
- Optional PM3-Bench to normalized JSONL adapter, clearly marked auxiliary.
- Validation report generator.
- PMID-level split checker.
- Quality issue summary output.

Exit criteria:

- Conversion is reproducible.
- Invalid records are rejected or flagged with explicit reasons.

### Phase 4: Gold Evidence Set

Deliverables:

- User POMGNT1 and CFTR curated rows as manually reviewable gold candidates.
- PubMed 23689641 manually reviewed gold record.
- Chunk/table/row evidence IDs where possible.
- Expected extraction output for regression tests.

Exit criteria:

- At least one full paper can evaluate both final PM3 answer and evidence
  grounding.

### Phase 5: Acceptance/Evaluation Packaging

Deliverables:

- `acceptance_gold_candidates.jsonl`.
- `pdf_xlsx_alignment.md`.
- `quality_issues.md`.
- Dataset card describing source folders, schema, known limitations, and
  artifact alignment policy.
- Versioned manifest with row counts, source checksum, and generation date.

Exit criteria:

- The user test-set package can be consumed by algorithm and engineering review
  without ad hoc field interpretation.

## 10. Proposed File Layout

Future dataset artifacts can use this layout:

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

For now, because this pass is documentation-only, no `data_prepared/` directory
is created.

## 11. Algorithm-Team Review Checklist

- Confirm the two Downloads folders are the primary user test set.
- Confirm whether variant-paper pair is the right primary record unit.
- Confirm required first-version labels from the 18-column user XLSX schema.
- Confirm criterion enum handling, especially plain `PM3`.
- Confirm whether patient-count prediction is a target, metadata, or both.
- Confirm whether partner-variant parsing should be strict or best-effort.
- Confirm no-train treatment for the user gold seed.
- Confirm if evidence grounding is required for all user curated rows or only a
  first reviewed subset.
- Confirm expected model output format.

## 12. Immediate Next Actions

1. Review `docs/t3_brief_report.md` and `docs/data_inventory_t3.md`.
2. Confirm the two Downloads folders as primary T3 data.
3. Discuss decisions D1-D10 with algorithm team.
4. Freeze schema v0.1.
5. Only after schema approval, implement user-XLSX converter, PDF alignment
   report, and validator.
6. Build PubMed 23689641 as the first manually reviewed gold evidence record.

## 13. Current Non-Goals

- No code changes in this pass.
- No generated training files in this pass.
- No manual relabeling in this pass.
- No external data download in this pass.
- No promotion of repo-local data to primary T3 data in this pass.
