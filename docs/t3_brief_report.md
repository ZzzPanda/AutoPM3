# T3 Brief Report

> Date: 2026-06-21
> Scope: Review the two user-provided PM3 test-set folders and define the data
> structure around them. Repository-local data is auxiliary only.

## Summary

Correction: the primary data is not any repo-local dataset. It is the two
variant-specific folders under `/Users/roger/Downloads`.
Together they contain curated PM3 summary spreadsheets plus local PubMed PDFs:
POMGNT1 has 3 curated rows and 2 PDFs; CFTR has 5 curated rows and 31 PDFs.
PM3-Bench and existing repo fixtures are auxiliary reference/regression data.

The main recommendation is to first normalize the two user-provided XLSX files
into one JSONL record per target variant-paper pair, preserving the original
Chinese columns and linking each row to the available PDFs. PM3-Bench can
optionally be converted into the same schema later, but it should not shape the
first T3 schema.

## Key Findings

| Area | Finding |
| --- | --- |
| Real user test set | Two Downloads folders: POMGNT1 c.1319T>G and CFTR c.220C>T. |
| POMGNT1 folder | 1 XLSX, 2 PDFs, 3 curated rows. PMID 21983716 is curated but no matching local PDF was found. |
| CFTR folder | 1 XLSX, 31 PDFs, 5 curated rows. The `位点` sheet records `chr7:117149143 C/T` and `rs115545701`. |
| Shared XLSX schema | Both workbooks use 18 columns covering PMID, title, mention status, patient count, disease, phenotype, family context, pathogenicity, zygosity, trans/cis sites, source index, raw table row, paper background, summary, and AI extraction trace. |
| Auxiliary benchmark | `benchmarks/PM3_Bench_data.json` has 1,027 rows, but is not the primary T3 data. |
| Split labels | `fine-tune`: 760, `eval`: 195, `others`: 72. |
| PMIDs | 467 unique PMIDs; 155 PMIDs appear in more than one row. |
| Variants | 752 unique target variants; all observed `Variant Name` values start with `NM_`. |
| Conditions | 22 unique normalized condition strings. |
| Criteria | PM3-Supporting 343, PM3 307, PM3-Strong 210, PM3-Very Strong 167. |
| Patient count | 47 `NA` values, 10 `err` values, mixed int/string types. |
| Field mismatch | Actual field is `CinGen ID`; README documents `ClinGen ID`. |
| Text quality | 31 raw comments show mojibake such as `â` / `Â`. |
| Evidence grounding | PM3-Bench comments are assertion text, not paper-grounded spans. |

## Main Risks

1. The true user test-set rows and local PDFs are not perfectly aligned:
   curated PMIDs can be missing PDFs, and extra PDFs can be uncurated candidates.
2. The current flat trans/cis fields in the XLSX are rich but semi-structured;
   they need normalization before automated evaluation.
3. Patient-count labels need cleanup before they are used as numeric targets.
4. Citation-grounded evaluation needs linked PDF/Markdown/XML evidence spans;
   XLSX summaries alone are not enough for source-grounded checks.
5. If auxiliary PM3-Bench is used later, row-level train/eval splitting can
   leak paper-level information because one PMID can map to many rows.
6. The current flat `In trans Variants` field in PM3-Bench is not enough to evaluate allele
   pairing, phase evidence, transcript consistency, or case-level support.
7. PM3-Bench `others` should stay separate as a parser/data-quality diagnostic
   set instead of being mixed into normal training or evaluation.

## Recommended Direction

- Normalize the two user-provided XLSX workbooks first, keyed by target
  variant-paper pair.
- Add a PDF/XLSX alignment report for each folder: curated PMIDs, available
  PDFs, missing PDFs, and uncurated candidate PDFs.
- Treat the user-provided folders as the first gold/acceptance test set, not
  training data.
- Keep source/raw fields for traceability while introducing clean typed fields.
- Add evidence-span records as soon as paper artifacts are available.
- Keep PM3-Bench as a later optional auxiliary benchmark adapter.

## Immediate Next Step

Use `plan.md` as the working execution plan. The first non-code milestone is to
confirm that the two Downloads folders are the primary acceptance/gold seed,
then freeze the XLSX-to-JSONL schema and PDF alignment policy.

Detailed standardized test-data structure:
`docs/t3_standardized_test_data_structure.zh.md`.
