# ClinGen eRepo PMID Evidence Extraction

This directory contains a small data-preparation script for ClinGen Evidence
Repository exports.

## Files

- `erepo-tabbed.csv`: source ClinGen eRepo export. Despite the `.csv` suffix,
  this file is tab-delimited.
- `explode_erepo_pmids.py`: keeps rows with met `PM3*` or `PS4*` evidence,
  extracts those evidence summaries, and explodes them by PMID.
- `erepo-pmid-summary.jsonl`: generated output. Re-run the command below to
  regenerate it from the current source export.

## What the Script Does

For each source row:

1. Keep only rows whose `Applied Evidence Codes (Met)` contains `PM3*` or
   `PS4*`.
2. Fetch the row's `Evidence Repo Link` detail page and read detailed
   `PM3*` / `PS4*` evidence from `tagLabels2Info`.
3. Prefer `evLinks` on the detail page when available. These links usually
   contain a PMID URL plus a curator comment, which is more reliable than
   splitting prose summaries.
4. If `evLinks` are unavailable, split the detailed evidence summary by
   parenthesized PMID markers such as `(PMID 10353779)`.
5. If the detail page cannot be fetched, fall back to parsing the source row's
   `Summary of interpretation`.
6. Remove boilerplate prefixes such as `Probands with total specificity score
   ...` and `Probands are as follows:`.
7. Emit JSONL rows with:
   - `Variation`
   - `PMID`
   - `Summary`
   - `Original`

`Summary` is the cleaned evidence text. `Original` keeps the raw source text
used for that row, which makes manual comparison easier during test-data
review.

The script does not modify empty source fields. If `Variation` is empty in the
original export, it remains empty in the output.

## Run

From the repository root:

```bash
python3 data/clinGen/explode_erepo_pmids.py \
  data/clinGen/erepo-tabbed.csv \
  data/clinGen/erepo-pmid-summary.jsonl
```

Test mode processes only the first N rows that have met `PM3*` or `PS4*`
codes. For a review batch of 100 candidates:

```bash
python3 data/clinGen/explode_erepo_pmids.py \
  data/clinGen/erepo-tabbed.csv \
  data/clinGen/erepo-pmid-summary.test.jsonl \
  --test \
  --test-rows 100 \
  --workers 3 \
  --request-timeout 20 \
  --retries 5
```

Detail pages are cached under `data/clinGen/cache/html` by default. Re-running
the same batch should use cache hits instead of making network requests. Use
`--refresh-cache` to force refetching.

To avoid network requests and only parse the local source summary field:

```bash
python3 data/clinGen/explode_erepo_pmids.py \
  data/clinGen/erepo-tabbed.csv \
  data/clinGen/erepo-pmid-summary.jsonl \
  --no-fetch-details
```

If direct HTTP fetching keeps failing and Playwright is installed, enable the
optional browser fallback:

```bash
python3 data/clinGen/explode_erepo_pmids.py \
  data/clinGen/erepo-tabbed.csv \
  data/clinGen/erepo-pmid-summary.test.jsonl \
  --test \
  --test-rows 100 \
  --browser-fallback
```

Browser fallback requires the Python `playwright` package and a Chromium
browser installation (`python -m playwright install chromium`). It is not used
by default because direct HTML parsing is faster and more reproducible.

## Example Output Row

```json
{"Variation":"NM_000314.8(PTEN):c.1003C>T (p.Arg335Ter)","PMID":"10353779","Summary":"Pediatric patient with macrocephaly, developmental delay, and penile freckling. Phenotype score +7, +1 proband point (PMID 10353779).","Original":"Probands with total specificity score of 5. Probands are as follows: Pediatric patient with macrocephaly, developmental delay, and penile freckling. Phenotype score +7, +1 proband point (PMID 10353779)."}
```

The script prints diagnostic counts after each run, including candidate rows,
output rows, cache hits/misses, browser fallback fetches, `evLinks` rows,
detail-summary rows, TSV fallback rows, fetch errors, and low-confidence rows.
