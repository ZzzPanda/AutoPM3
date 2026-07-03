#!/usr/bin/env python3
"""Extract PM3/PS4 ClinGen eRepo evidence into PMID-level JSONL rows."""

from __future__ import annotations

import argparse
import collections
import csv
import html
import json
import re
import shutil
import subprocess
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from http.client import IncompleteRead
from pathlib import Path
from urllib.error import URLError

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL.*")
import requests


TARGET_CODE_PREFIXES = ("PM3", "PS4")
PMID_PAREN_RE = re.compile(
    r"\(\s*PMIDs?:?\s*((?:\d+[\s,;]*)+)\)\.?",
    re.IGNORECASE,
)
PMID_RE = re.compile(r"\bPMIDs?:?\s*(\d+)\b", re.IGNORECASE)
PMID_LIST_RE = re.compile(r"\bPMIDs?:?\s*((?:\d+[\s,;]*)+)", re.IGNORECASE)
CRITERION_RE = re.compile(
    r"\b(?:PVS1|PS[1-4]|PM[1-6]|PP[1-5]|BA1|BS[1-4]|BP[1-7])"
    r"(?:[_-][A-Za-z]+(?:\s+[A-Za-z]+)*)?:"
)


@dataclass(frozen=True)
class EvidenceSummary:
    code: str
    summary: str
    ev_links: tuple[tuple[str, str, str], ...] = ()
    source: str = "detail"


@dataclass(frozen=True)
class ExtractedEvidence:
    variation: str
    pmid: str
    summary: str
    original: str
    method: str
    low_confidence: bool


def normalize_code(code: str) -> str:
    return re.sub(r"[- ]", "_", code.strip())


def is_target_code(code: str) -> bool:
    normalized = normalize_code(code)
    return normalized.startswith(TARGET_CODE_PREFIXES)


def row_has_target_met_code(row: dict[str, str]) -> bool:
    return any(
        is_target_code(code)
        for code in row.get("Applied Evidence Codes (Met)", "").split(",")
        if code.strip()
    )


def unique_in_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return unique_values


def extract_pmids(text: str) -> list[str]:
    pmids: list[str] = []
    for match in PMID_LIST_RE.finditer(text):
        pmids.extend(re.findall(r"\d+", match.group(1)))
    pmids.extend(PMID_RE.findall(text))
    return unique_in_order(pmids)


def extract_js_object(html_text: str, variable_name: str) -> dict:
    marker = f"var {variable_name} = "
    start = html_text.find(marker)
    if start == -1:
        return {}

    object_start = html_text.find("{", start + len(marker))
    if object_start == -1:
        return {}

    depth = 0
    in_string = False
    escaped = False
    for index in range(object_start, len(html_text)):
        char = html_text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(html_text[object_start : index + 1])

    return {}


def fetch_detail_evidence(
    url: str,
    *,
    timeout: float,
    retries: int,
    cache_dir: Path | None,
    refresh_cache: bool,
    browser_fallback: bool,
) -> tuple[list[EvidenceSummary], collections.Counter]:
    stats: collections.Counter = collections.Counter()
    if not url:
        return [], stats

    normalized_url = normalize_evidence_repo_url(url)
    cache_path = detail_cache_path(normalized_url, cache_dir)
    html_text = ""
    if cache_path and cache_path.exists() and not refresh_cache:
        html_text = cache_path.read_text(encoding="utf-8", errors="replace")
        stats["detail_cache_hits"] += 1
    else:
        stats["detail_cache_misses"] += 1
        try:
            html_text = fetch_detail_html(normalized_url, timeout=timeout, retries=retries)
        except Exception:
            if not browser_fallback:
                raise
            html_text = fetch_html_with_browser(normalized_url, timeout=timeout)
            stats["browser_fallback_fetches"] += 1
        if not extract_js_object(html_text, "tagLabels2Info"):
            raise ValueError("detail page did not contain tagLabels2Info")
        if cache_path and html_text:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(html_text, encoding="utf-8")

    tag_info = extract_js_object(html_text, "tagLabels2Info")
    evidence: list[EvidenceSummary] = []
    for raw_code, code_info in tag_info.items():
        if not is_target_code(raw_code):
            continue
        for agent_info in code_info.get("agents", {}).values():
            summary = html.unescape(agent_info.get("summary", "")).strip()
            ev_links = tuple(extract_ev_link(link) for link in agent_info.get("evLinks", []))
            ev_links = tuple(link for link in ev_links if link[0])
            if summary or ev_links:
                evidence.append(
                    EvidenceSummary(
                        code=normalize_code(raw_code),
                        summary=summary,
                        ev_links=ev_links,
                    )
                )
    return evidence, stats


def detail_cache_path(url: str, cache_dir: Path | None) -> Path | None:
    if cache_dir is None:
        return None
    match = re.search(r"/classification/([0-9a-fA-F-]+)", url)
    if not match:
        return None
    return cache_dir / f"{match.group(1)}.html"


def fetch_detail_html(url: str, *, timeout: float, retries: int) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 AutoPM3 ClinGen evidence extractor/0.1",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    attempts = max(1, retries)
    for attempt in range(attempts):
        try:
            html_text = fetch_html(url, headers=headers, timeout=timeout)
            break
        except (
            requests.RequestException,
            subprocess.SubprocessError,
            TimeoutError,
            URLError,
            IncompleteRead,
            OSError,
        ) as exc:
            if attempt == attempts - 1:
                raise
            time.sleep(0.5 * (attempt + 1))
    else:
        raise RuntimeError("unreachable fetch retry state")

    return html_text


def normalize_evidence_repo_url(url: str) -> str:
    return url.replace("https://erepo.genome.network/", "https://erepo.clinicalgenome.org/")


def fetch_html(url: str, *, headers: dict[str, str], timeout: float) -> str:
    curl = shutil.which("curl")
    if curl:
        command = [
            curl,
            "-fsSL",
            "--max-time",
            str(timeout),
            "-A",
            headers["User-Agent"],
            "-H",
            f"Accept: {headers['Accept']}",
            url,
        ]
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout + 2,
        )
        return completed.stdout

    response = requests.get(
        url,
        headers=headers,
        timeout=(min(3.0, timeout), timeout),
    )
    response.raise_for_status()
    return response.text


def fetch_html_with_browser(url: str, *, timeout: float) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "browser fallback requires the Python 'playwright' package. "
            "Install it and run `python -m playwright install chromium`."
        ) from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
        content = page.content()
        browser.close()
    return content


def extract_ev_link(link_info: dict) -> tuple[str, str, str]:
    link = link_info.get("link", "")
    original_comments = html.unescape(link_info.get("comments", "")).strip()
    pmids = extract_pmids(link)
    if not pmids:
        pmids = re.findall(r"(?:pubmed|pubmed\.ncbi\.nlm\.nih\.gov)/(\d+)", link)
    if not pmids:
        pmids = re.findall(r"/(\d+)(?:/?|[?#].*)$", link)
    if not pmids:
        pmids = extract_pmids(original_comments)
    return (
        pmids[0] if pmids else "",
        clean_evidence_text(original_comments),
        original_comments,
    )


def extract_summary_evidence(summary: str) -> list[EvidenceSummary]:
    matches = list(CRITERION_RE.finditer(summary))
    evidence: list[EvidenceSummary] = []
    for index, match in enumerate(matches):
        code = match.group(0).rstrip(":")
        if not is_target_code(code):
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(summary)
        snippet = summary[start:end].strip()
        if snippet:
            evidence.append(EvidenceSummary(code=normalize_code(code), summary=snippet, source="tsv"))
    return evidence


def extract_pmid_snippets(summary: str) -> list[tuple[str, str]]:
    """Return (pmid, evidence text) pairs from PMID-bearing evidence sentences."""
    summary = clean_evidence_text(summary)
    pairs: list[tuple[str, str]] = []
    pending_context = ""
    for sentence in split_evidence_sentences(summary):
        sentence = clean_evidence_text(sentence)
        if not sentence:
            continue

        pmids = extract_pmids(sentence)
        if not pmids:
            pending_context = f"{pending_context} {sentence}".strip()
            continue

        snippet = f"{pending_context} {sentence}".strip() if pending_context else sentence
        snippet = clean_evidence_text(snippet)
        pending_context = ""
        for pmid in pmids:
            pairs.append((pmid, snippet))
    return pairs


def split_evidence_sentences(text: str) -> list[str]:
    """Split on sentence boundaries without breaking HGVS fragments like c.643."""
    return re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])", text)


def clean_evidence_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^[.,;:\s]+", "", text)
    if not text:
        return ""

    text = re.sub(
        r"^Probands with total specificity score of [^.]+\.?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    text = re.sub(r"^Probands? are as follows:\s*", "", text, flags=re.IGNORECASE).strip()
    return text


def is_low_confidence_summary(summary: str, original: str) -> bool:
    normalized = clean_evidence_text(summary)
    if len(normalized) < 30:
        return True
    if re.fullmatch(r"\(?\s*PMID:?\s*\d+\s*\)?\.?", normalized, flags=re.IGNORECASE):
        return True
    original_pmids = extract_pmids(original)
    summary_pmids = extract_pmids(summary)
    if len(original_pmids) > 1 and len(summary_pmids) == 0:
        return True
    return False


def explode_erepo_pmids(
    input_path: Path,
    output_path: Path,
    *,
    fetch_details: bool,
    request_timeout: float,
    retries: int,
    cache_dir: Path | None,
    refresh_cache: bool,
    browser_fallback: bool,
    test_rows: int | None,
    workers: int,
) -> collections.Counter:
    stats: collections.Counter = collections.Counter()

    with input_path.open("r", encoding="utf-8", newline="") as input_file:
        reader = csv.DictReader(input_file, delimiter="\t")
        required_columns = {"Summary of interpretation"}
        missing_columns = required_columns.difference(reader.fieldnames or [])
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"Missing required column(s): {missing}")
        rows = list(reader)

    stats["input_rows"] = len(rows)
    candidate_rows = [row for row in rows if row_has_target_met_code(row)]
    stats["candidate_rows"] = len(candidate_rows)
    if test_rows is not None:
        candidate_rows = candidate_rows[:test_rows]
        stats["processed_candidate_rows"] = len(candidate_rows)
    else:
        stats["processed_candidate_rows"] = len(candidate_rows)

    with output_path.open("w", encoding="utf-8") as output_file:
        if workers > 1 and fetch_details:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [
                    executor.submit(
                        build_output_rows,
                        row,
                        fetch_details=fetch_details,
                        request_timeout=request_timeout,
                        retries=retries,
                        cache_dir=cache_dir,
                        refresh_cache=refresh_cache,
                        browser_fallback=browser_fallback,
                    )
                    for row in candidate_rows
                ]
                for future in as_completed(futures):
                    extracted_rows, row_stats = future.result()
                    write_extracted_rows(output_file, extracted_rows)
                    stats.update(row_stats)
        else:
            for row in candidate_rows:
                extracted_rows, row_stats = build_output_rows(
                    row,
                    fetch_details=fetch_details,
                    request_timeout=request_timeout,
                    retries=retries,
                    cache_dir=cache_dir,
                    refresh_cache=refresh_cache,
                    browser_fallback=browser_fallback,
                )
                write_extracted_rows(output_file, extracted_rows)
                stats.update(row_stats)

    return stats


def write_extracted_rows(output_file, extracted_rows: list[ExtractedEvidence]) -> None:
    for item in extracted_rows:
        json.dump(
            {
                "Variation": item.variation,
                "PMID": item.pmid,
                "Summary": item.summary,
                "Original": item.original,
            },
            output_file,
            ensure_ascii=False,
        )
        output_file.write("\n")


def build_output_rows(
    row: dict[str, str],
    *,
    fetch_details: bool,
    request_timeout: float,
    retries: int,
    cache_dir: Path | None,
    refresh_cache: bool,
    browser_fallback: bool,
) -> tuple[list[ExtractedEvidence], collections.Counter]:
    stats: collections.Counter = collections.Counter()
    evidence: list[EvidenceSummary] = []
    if fetch_details:
        try:
            evidence, fetch_stats = fetch_detail_evidence(
                row.get("Evidence Repo Link", ""),
                timeout=request_timeout,
                retries=retries,
                cache_dir=cache_dir,
                refresh_cache=refresh_cache,
                browser_fallback=browser_fallback,
            )
            stats.update(fetch_stats)
        except (
            requests.RequestException,
            subprocess.SubprocessError,
            TimeoutError,
            URLError,
            IncompleteRead,
            json.JSONDecodeError,
            OSError,
        ) as exc:
            stats["detail_fetch_errors"] += 1
            print(
                f"warning: failed to fetch detail evidence for "
                f"{row.get('Uuid', '<missing uuid>')}: {format_fetch_error(exc)}",
                file=sys.stderr,
            )

    if not evidence:
        evidence = extract_summary_evidence(row.get("Summary of interpretation", ""))
        if evidence:
            stats["tsv_fallback_records"] += 1

    output_rows: list[ExtractedEvidence] = []
    for item in evidence:
        if item.ev_links:
            for pmid, comment, original_comment in item.ev_links:
                original = original_comment or item.summary
                summary = comment or clean_evidence_text(item.summary)
                extracted = ExtractedEvidence(
                    variation=row.get("Variation", ""),
                    pmid=pmid,
                    summary=summary,
                    original=original,
                    method="evlinks",
                    low_confidence=is_low_confidence_summary(summary, original),
                )
                output_rows.append(extracted)
                stats["evlinks_rows"] += 1
                stats["output_rows"] += 1
                if extracted.low_confidence:
                    stats["low_confidence_rows"] += 1
            continue

        for pmid, summary in extract_pmid_snippets(item.summary):
            method = "tsv_summary_rule" if item.source == "tsv" else "detail_summary_rule"
            extracted = ExtractedEvidence(
                variation=row.get("Variation", ""),
                pmid=pmid,
                summary=summary,
                original=item.summary,
                method=method,
                low_confidence=is_low_confidence_summary(summary, item.summary),
            )
            output_rows.append(extracted)
            stats[f"{method}_rows"] += 1
            stats["output_rows"] += 1
            if extracted.low_confidence:
                stats["low_confidence_rows"] += 1
    if not output_rows and evidence:
        stats["no_pmid_evidence_blocks"] += len(evidence)
    return output_rows, stats


def format_fetch_error(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        return f"curl exit {exc.returncode}"
    if isinstance(exc, subprocess.TimeoutExpired):
        return "curl timeout"
    return str(exc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read a tab-delimited ClinGen eRepo export, keep rows with met "
            "PM3/PS4 codes, split PM3/PS4 evidence by PMID, and write JSONL "
            "with Variation, PMID, and Summary."
        )
    )
    parser.add_argument("input", type=Path, help="Input eRepo tab-delimited CSV/TSV file.")
    parser.add_argument("output", type=Path, help="Output JSONL path.")
    parser.add_argument(
        "--no-fetch-details",
        action="store_true",
        help="Do not fetch Evidence Repo detail pages; only parse Summary of interpretation.",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=20.0,
        help="Timeout in seconds for each Evidence Repo page request.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Number of attempts for each Evidence Repo detail page request.",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test mode: process only the first 30 rows that have met PM3/PS4 codes.",
    )
    parser.add_argument(
        "--test-rows",
        type=int,
        default=30,
        help="Number of PM3/PS4 candidate rows to process in test mode.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel Evidence Repo detail page requests.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/clinGen/cache/html"),
        help="Directory for cached Evidence Repo detail HTML pages.",
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Ignore cached detail pages and refetch them.",
    )
    parser.add_argument(
        "--browser-fallback",
        action="store_true",
        help="Use Playwright as a last-resort page fetcher if HTTP/curl fetches fail.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        stats = explode_erepo_pmids(
            args.input,
            args.output,
            fetch_details=not args.no_fetch_details,
            request_timeout=args.request_timeout,
            retries=max(1, args.retries),
            cache_dir=args.cache_dir,
            refresh_cache=args.refresh_cache,
            browser_fallback=args.browser_fallback,
            test_rows=args.test_rows if args.test else None,
            workers=max(1, args.workers),
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {stats['output_rows']} JSONL rows to {args.output}")
    print("Diagnostics:")
    for key in [
        "input_rows",
        "candidate_rows",
        "processed_candidate_rows",
        "output_rows",
        "detail_cache_hits",
        "detail_cache_misses",
        "browser_fallback_fetches",
        "evlinks_rows",
        "detail_summary_rule_rows",
        "tsv_summary_rule_rows",
        "tsv_fallback_records",
        "detail_fetch_errors",
        "low_confidence_rows",
        "no_pmid_evidence_blocks",
    ]:
        print(f"  {key}: {stats[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
