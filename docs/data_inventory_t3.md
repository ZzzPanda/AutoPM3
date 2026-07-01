# T3 Test Data Inventory and Data Structure Proposal

> Created: 2026-06-21

This note inventories the two user-provided test-set folders as the primary T3
data. Repository-local datasets and fixtures are treated only as auxiliary
reference, regression, or later benchmark material.

## 1. Data Sources

| Source | Path | Format | Sample count | Current use |
| --- | --- | --- | --- | --- |
| User test set: POMGNT1 c.1319T>G | `/Users/roger/Downloads/NM_017739.4 (POMGNT1)  c.1319TG (p.Leu440Arg) 2` | 1 XLSX + 2 PDFs | 3 curated spreadsheet rows; 2 local PDFs | Primary user-provided PM3 test set |
| User test set: CFTR c.220C>T | `/Users/roger/Downloads/NM_000492.4 (CFTR)  c.220CT (p.Arg74Trp), exon3` | 1 XLSX + 31 PDFs | 5 curated spreadsheet rows; 31 local PDFs | Primary user-provided PM3 test set |
| PM3-Bench | `benchmarks/PM3_Bench_data.json` | JSON list | 1,027 variant-literature rows | Auxiliary benchmark reference only |
| PubMed 23689641 BioC XML | `tests/fixtures/23689641.xml`, `data/pdf_convert/23689641.xml` | XML | 1 paper | Auxiliary parser/query fixture |
| PubMed 23689641 MinerU Markdown | `tests/fixtures/PubMed23689641_markdown.md`, `data/pdf_convert/MinerU_markdown_PubMed23689641_2067159189227929600.md` | Markdown with HTML tables | 1 paper | Auxiliary chunking/evidence UI fixture |
| MinerU conversion metadata | `data/pdf_convert/MinerU_PubMed23689641__20260617081534.json` | JSON | 12 `pdf_info` blocks | Auxiliary PDF conversion debug metadata |
| Synthetic markdown fixtures | `tests/test_synthetic_markdown.py`, `tests/benchmark_chunk_quality.py` | Generated in tests | Several synthetic documents | Auxiliary chunker edge cases |
| Protein abbreviation map | `data/protein.txt` | Text mapping | 21 lines | Runtime normalization helper |

## 2. User-Provided Test Set Inventory

The two Downloads folders are the actual user-provided test set for T3. They
are the primary data source. Everything already in the repository is auxiliary:
useful for comparison, regression, and later expansion, but not the center of
this task.

### 2.1 Directory-Level Summary

| Variant folder | Target variant | Files | Curated rows | Local PDFs | Notes |
| --- | --- | ---: | ---: | ---: | --- |
| POMGNT1 | `NM_017739.4 (POMGNT1) c.1319T>G (p.Leu440Arg)` | 3 | 3 | 2 | XLSX includes PMID 21983716, but local PDFs include 23689641 and 33200426 only. |
| CFTR | `NM_000492.4 (CFTR) c.220C>T (p.Arg74Trp), exon3` | 32 | 5 | 31 | XLSX summarizes 5 PMIDs; folder contains many extra candidate PDFs. |

### 2.2 Shared XLSX Schema

Both summary workbooks use the same 18-column structure:

| Column | Meaning |
| --- | --- |
| `PMID` | Literature identifier |
| `标题` | Paper title |
| `作者` | Authors |
| `是否提及此位点` | Whether the paper mentions the target variant |
| `患者数` | Patient count or not-applicable status |
| `患者年龄` | Patient age |
| `患者临床疾病` | Disease / clinical diagnosis |
| `患者临床表型` | Phenotype details |
| `家系情况` | Family and segregation context |
| `致病性（作者结论是否致病/疑似致病/不致病可能有其它位点）` | Author-level pathogenicity conclusion |
| `关联合子状态` | Zygosity / allele state |
| `反式(trans)位点` | In-trans partner variant(s) |
| `顺式(cis)位点` | Cis-linked variant(s) |
| `来源索引（精准标注证据位置，格式为表编号+行号，用于回溯原始表格内容。）` | Source index for evidence tracing |
| `表格原始行内容（保留表格原始文本，用于人工复核、过滤解析错误或假阳性。）` | Raw table row text |
| `文献背景(是什么研究，最终什么结论)` | Paper background and conclusion |
| `总结（示例：...）` | Final PM3-style summary |
| `AI提取过程` | Model extraction trace / reasoning notes |

### 2.3 POMGNT1 Folder Details

Path:
`/Users/roger/Downloads/NM_017739.4 (POMGNT1)  c.1319TG (p.Leu440Arg) 2`

Files:

| File | Type | Notes |
| --- | --- | --- |
| `POMGNT1_c.1319T_G_PM3汇总.xlsx` | XLSX | 1 sheet, 18 columns, 3 curated rows |
| `PubMed23689641.pdf` | PDF | 12 pages; local PDF available |
| `PubMed33200426.pdf` | PDF | 30 pages; local PDF available |

Curated spreadsheet rows:

| PMID | Mentions target | Patient count | Disease | Allele state | Trans partner | Cis partner |
| --- | --- | --- | --- | --- | --- | --- |
| 21983716 | Yes | 1 | Muscle-eye-brain disease | Compound heterozygous | `c.1896+1G>C` | N/A |
| 23689641 | Yes | 1 | Muscle-eye-brain disease | Compound heterozygous | `c.1896+1G>C` | N/A |
| 33200426 | No | 0 | N/A | N/A | N/A | N/A |

Important issue: PMID 21983716 is curated in the XLSX but does not currently
have a matching local PDF in the folder. The folder also includes PMID 33200426
as a negative/non-mention example.

### 2.4 CFTR Folder Details

Path:
`/Users/roger/Downloads/NM_000492.4 (CFTR)  c.220CT (p.Arg74Trp), exon3`

Files:

| File type | Count | Notes |
| --- | ---: | --- |
| XLSX | 1 | `CFTR_c.220CT_PM3汇总.xlsx`; 2 sheets: `Sheet1` and `位点` |
| PDFs | 31 | Candidate literature folder, named by PMID |

The `位点` sheet records `chr7:117149143 C/T` and dbSNP `rs115545701`.

Curated `Sheet1` rows:

| PMID | Mentions target | Patient count | Disease / context | Main cis/trans signal |
| --- | --- | --- | --- | --- |
| 30600599 | Yes | 2 siblings | Cystic fibrosis | `p.[R74W;V201M;D1270N]` is in trans with `p.Phe508del`; R74W/V201M/D1270N are cis |
| 18703181 | Yes | 3 total | CBAVD / obstructive azoospermia / carrier children | Triple cis allele is in trans with `p.P841R` or `p.F508del` |
| 27738188 | Yes | 12 | CF, CFTR-RD, healthy/CFSPID-related | R74W appears in cis complex alleles; several trans CFTR variants reported |
| 37431359 | Yes | 1 | Mild CF with pancreatic insufficiency and bronchiectasis | R74W/V201M/D1270N cis; trans relation with F508del not experimentally resolved |
| 32172930 | Yes | N/A | CFTR-RD / NBS positives / asymptomatic compound heterozygotes | Classification/database review; cis complex alleles, no patient-level PM3 count |

Important issue: the CFTR folder contains 31 PDFs, but the curated spreadsheet
currently summarizes only 5 PMIDs. The remaining PDFs should be treated as
candidate papers requiring triage, not as already curated gold rows.

## 3. Auxiliary Repository Data: PM3-Bench Field Inventory

Actual fields in `benchmarks/PM3_Bench_data.json`:

| Field | Type / shape observed | Missing / quality notes |
| --- | --- | --- |
| `CinGen ID` | String | No missing values. Name appears misspelled; README says `ClinGen ID`. |
| `Variant Name` | HGVS cDNA string, all starting with `NM_` | No missing values. Needs transcript and cDNA components parsed into separate fields. |
| `Condition` | String | No missing values. 22 unique lowercase conditions. |
| `Criterion` | String enum | No missing values. Distribution: PM3-Supporting 343, PM3 307, PM3-Strong 210, PM3-Very Strong 167. |
| `PMID` | Integer | No missing values. 467 unique PMIDs; 155 PMIDs have multiple rows. |
| `Raw Comment` | Free text expert comment | No missing values, but 31 rows show mojibake such as `â` / `Â`. |
| `Number of Patients` | Mostly integer, sometimes string | 47 `NA` values and 10 `err` values; type is mixed: 955 int, 72 str. |
| `In trans Variants` | List of variant strings, sometimes empty/NA | 1 missing/empty row. Needs structured partner-variant records. |
| `labels` | String enum | No missing values. Distribution: fine-tune 760, eval 195, others 72. |

Key PM3-Bench counts:

- Rows: 1,027
- Unique variants: 752
- Unique PMIDs: 467
- Unique normalized conditions: 22
- Label split: `eval` 195, `fine-tune` 760, `others` 72

## 4. Auxiliary Repository Fixture Inventory

The PubMed 23689641 Markdown fixture has:

- 46,041 characters, 418 lines
- 15 Markdown headings
- 2 HTML tables
- 26 rough cDNA-like variant mentions
- 21 rough protein-like variant mentions

This fixture is useful for chunking and UI evidence-link regression tests, but
it is auxiliary. It should not define the T3 data structure.

## 5. Current Data Quality Issues

| Issue | Impact | Proposed cleanup |
| --- | --- | --- |
| User test-set folders are outside the repo | Repo-only inventory misses the true test set. | Treat the two Downloads folders as the primary T3 data inputs; repo data is auxiliary. |
| XLSX rows and local PDFs do not fully align | Gold labels may reference missing PDFs, and extra PDFs may be uncurated candidates. | Track `pdf_available`, `curation_status`, and `artifact_path` per PMID. |
| Chinese curated fields are rich but semi-structured | Direct model training needs typed fields. | Normalize each workbook row into structured variant-paper JSONL while preserving original Chinese columns. |
| `CinGen ID` typo | Downstream code may silently create both `CinGen ID` and `ClinGen ID`. | Normalize to `clingen_id`; keep source field in raw metadata. |
| Mixed type in `Number of Patients` | Numeric aggregation and stratified splits become fragile. | Parse to `patient_count`; preserve raw value in `patient_count_raw`; add `patient_count_status`. |
| `err` and `NA` patient values | Cannot use directly as labels. | Encode as null with status `error` or `not_reported`. |
| Mojibake in comments | Model prompts and exact-match evaluation can degrade. | Run encoding cleanup pass; store both raw and cleaned comments during transition. |
| `In trans Variants` is a flat list of strings | Hard to evaluate allele pairing, transcript, protein change, or evidence scope. | Convert to partner-variant objects with normalized HGVS components. |
| PMID duplicated across PM3-Bench rows | Relevant only if auxiliary PM3-Bench is later used for benchmark-scale experiments. | Split auxiliary PM3-Bench by PMID or paper cluster if used later. |
| Benchmark comments are assertion-level text, not paper-grounded spans | Evaluation can check final answers but not citation quality. | Add evidence span/chunk references when linking to XML/PDF/Markdown. |
| `others` means truncated XML in README | Mixing with eval can hide retrieval/parser failure modes. | Keep as a separate diagnostic split, not normal eval. |

## 6. Annotation Targets

For the user test-set workflow, reusable labels should be separated
into paper-level, variant-level, case-level, and evidence-level targets.

| Target layer | Labels to capture |
| --- | --- |
| Paper | PMID, DOI, title, source format, disease, gene/locus, available sections/tables |
| Variant query | Target variant, transcript, cDNA change, protein change, ClinGen ID, condition |
| PM3 assertion | Criterion strength, patient count, in-trans status, source comment, label split |
| Partner variant | Partner variant string, parsed transcript/cDNA/protein, relation to target, zygosity, phase evidence |
| Case/family | Case ID, family ID, genotype, phenotype, parental validation, segregation notes |
| Evidence span | Source document, chunk ID, table ID/row ID, quote/span text, confidence, extraction method |
| QA metadata | Human review status, reviewer, error type, notes |

## 7. Proposed Normalized Structure

Recommended first version: store one JSONL record per target variant-paper pair.
For T3, records should first be converted from the two user-provided XLSX
workbooks. PM3-Bench may be mapped to the same schema later, but only as an
auxiliary benchmark extension.

```json
{
  "record_id": "USERTEST:POMGNT1:23689641:NM_017739.4:c.1319T>G",
  "split": "acceptance_gold_candidate",
  "source": {
    "dataset": "user_test_set",
    "raw_row_index": 0,
    "artifact_dir": "/Users/roger/Downloads/...",
    "raw_fields": {}
  },
  "paper": {
    "pmid": "23689641",
    "doi": null,
    "title": "Novel POMGnT1 mutations cause muscle-eye-brain disease in Chinese patients.",
    "formats_available": ["xlsx_summary", "pdf"],
    "pdf_available": true
  },
  "condition": {
    "name": "muscle-eye-brain disease",
    "normalized_id": null
  },
  "target_variant": {
    "raw": "NM_017739.4:c.1319T>G (p.Leu440Arg)",
    "transcript": "NM_017739.4",
    "cdna": "c.1319T>G",
    "protein": "p.Leu440Arg",
    "gene": "POMGNT1",
    "mention_status": "mentioned"
  },
  "pm3_assertion": {
    "criterion": "PM3-Strong",
    "patient_count": 1,
    "patient_count_raw": "1",
    "patient_count_status": "parsed"
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
  "evidence": [
    {
      "evidence_id": "comment-0",
      "source_type": "xlsx_curated_summary",
      "text": "位置：表1第一行（病例1），基因变异列明确记载c.1319T>G。",
      "chunk_id": null,
      "table_id": null,
      "row_id": null
    }
  ],
  "review": {
    "status": "unreviewed",
    "issues": []
  }
}
```

## 8. Split Plan

Recommended split policy:

1. Treat the two user-provided folders as the initial gold/acceptance test set,
   not as training data.
2. Within the user test set, distinguish curated XLSX rows from uncurated
   candidate PDFs.
3. Do not use repository-local data to override or redefine the user test-set
   labels.
4. If PM3-Bench is used later, keep it as a separate auxiliary benchmark and
   split it by PMID to avoid leakage.
5. Keep repo fixtures as regression fixtures for parsing/chunking/evidence UI,
   not as primary labels.

## 9. Recommended Next Conversation With Algorithm Team

Open questions to confirm before implementing the data converter:

- Should the training unit be variant-paper pair, case-level evidence, or
  extracted evidence span?
- Which fields are mandatory for the first training set: partner variant only,
  patient count only, or full case/family structure?
- How should `PM3` without strength be mapped: separate class, or normalized
  strength?
- Should rows with `patient_count_status != "parsed"` be excluded, weakly
  labeled, or used only for retrieval training?
- What is the target output schema for model training: JSON object, natural
  language rationale plus JSON, or structured extraction only?
- Should the user-provided XLSX rows be treated as gold labels, silver labels,
  or labels requiring one more human review pass?
- For PDFs present in a folder but absent from the XLSX summary, should the
  first task be triage, full extraction, or negative-example confirmation?

## 10. Immediate Implementation Tasks

- Add a converter from the two user-provided XLSX workbooks to normalized JSONL.
- Add a PDF/XLSX alignment report: curated PMIDs, available PDFs, missing PDFs,
  and extra candidate PDFs.
- Later, optionally add a converter from `PM3_Bench_data.json` to the same
  normalized JSONL schema as an auxiliary benchmark adapter.
- Add validation checks for field names, enum values, patient-count parsing,
  partner-variant parsing, and PMID-level split leakage.
- Add a small manually reviewed gold file for PubMed 23689641 with chunk/table
  evidence IDs.
- Document clearly that repository-local PM3-Bench is auxiliary for T3.
