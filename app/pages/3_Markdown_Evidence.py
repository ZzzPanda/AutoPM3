# Make the project root importable when launched via `streamlit run app/main.py`.
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import os
import traceback

import streamlit as st

from app.core.query import format_mutalyzer_diagnostics, query_variant_in_paper_xml
from app.core.streamlit_helpers import (
    config_value,
    extract_paper_content,
    render_result,
    run_async_query,
)


TEST_MARKDOWN_PATH = (
    _PROJECT_ROOT
    / "data"
    / "pdf_convert"
    / "MinerU_markdown_PubMed23689641_2067159189227929600.md"
)


def run_query_markdown_evidence(variant_name, paper_path, api_url, model_name, api_key):
    """Run AutoPM3 with Markdown input and linked evidence chunks enabled."""
    return run_async_query(
        query_variant_in_paper_xml,
        variant_name,
        paper_path,
        model_name,
        model_name,
        api_key,
        api_url=api_url,
        include_evidence=True,
        allow_markdown=True,
    )


def _chunk_around(markdown_text: str, needle: str, radius: int = 650) -> str:
    idx = markdown_text.find(needle)
    if idx < 0:
        return markdown_text[: radius * 2].strip()

    table_start = markdown_text.rfind("<table", 0, idx)
    table_end = markdown_text.find("</table>", idx)
    if table_start >= 0 and table_end >= 0:
        nearest_table_close_before = markdown_text.rfind("</table>", 0, idx)
        if nearest_table_close_before < table_start:
            return markdown_text[table_start : table_end + len("</table>")].strip()

    para_start = markdown_text.rfind("\n\n", 0, idx)
    para_end = markdown_text.find("\n\n", idx + len(needle))
    if para_start >= 0 and para_end >= 0:
        return markdown_text[para_start + 2 : para_end].strip()

    start = max(0, idx - radius)
    end = min(len(markdown_text), idx + len(needle) + radius)
    return markdown_text[start:end].strip()


def _compact(text: str, limit: int = 1400) -> str:
    compacted = " ".join(text.split())
    if len(compacted) <= limit:
        return compacted
    return compacted[: limit - 1].rstrip() + "…"


def _build_fake_result():
    markdown_text = TEST_MARKDOWN_PATH.read_text(encoding="utf-8", errors="replace")
    chunk_1 = _chunk_around(markdown_text, "c.1319T &gt; G, p.L440R")
    chunk_2 = _chunk_around(markdown_text, "c.1896-1 G [ C")
    chunk_3 = _chunk_around(markdown_text, "The enzymatic activity was significantly lower")
    chunk_4 = _chunk_around(markdown_text, "mutant POMGnT1 also co-localized with an ER marker")
    chunk_5 = _chunk_around(markdown_text, "c.1814 mutation has previously been described")
    fake_diag = {
        "input_hgvs": "NM_017739.1:c.1319T>G",
        "var_dna": "1319T>G",
        "mutalyzer": {
            "endpoint": "https://mutalyzer.nl/api/normalize/NM_017739.1:c.1319T>G?only_variants=false",
            "raw_protein_description": "NP_060209.2:p.(Leu440Arg)",
            "protein_after_p_strip": "Leu440Arg",
            "trimmed_long": "Leu440Arg",
            "trimmed_short": "L440R",
            "c_protein_id_digits": ["440"],
            "status": "ok",
            "error": None,
        },
        "dna_search": {
            "regex_pattern": r"\s*1319\s*T\s*>\s*G",
            "matched": True,
            "chunk_count": 2,
        },
        "protein_search": {
            "long_form": "Leu440Arg",
            "short_form": "L440R",
            "long_matched": True,
            "short_matched": True,
            "chunk_count_long": 1,
            "chunk_count_short": 1,
        },
        "position_fallback": {
            "triggered": False,
            "dna_pattern": None,
            "protein_pattern": None,
            "matched": False,
            "chunk_count": 0,
        },
        "retriever_summary": {
            "ok": True,
            "total_chunks_returned": 2,
            "short_protein": "L24R",
        },
    }
    return {
        "title": "Output Summary",
        "sections": [
            {
                "title": "Query Variant and Relative Intrans-variant / Genotype Found in PaperTables",
                "body": "No table found\n\n",
                "evidence_ids": [],
            },
            {
                "title": "Query Variant Found in PaperText",
                "body": (
                    "- **[DNA match result]**: YES. The paper reports `c.1319T>G` "
                    "for Case 1 in the POMGnT1 gene.\n\n"
                    "- **[Protein match result]**: YES. The corresponding protein "
                    "change `p.L440R` is discussed and functionally evaluated."
                ),
                "evidence_ids": ["chunk-1", "chunk-3", "chunk-4"],
            },
            {
                "title": "Query Variant's Intrans-variant Found in PaperText",
                "body": "*c.1896-1G>C*",
                "evidence_ids": ["chunk-2"],
            },
            {
                "title": "Additional Cohort Variants Mentioned in PaperText",
                "body": (
                    "The discussion also mentions other compound heterozygous POMGnT1 "
                    "variants in Cases 2 and 3, including `c.1814G>C`, `c.1513G>A`, "
                    "`c.575T>C`, and `c.1325G>T`."
                ),
                "evidence_ids": ["chunk-5"],
            },
            {
                "title": "Mutalyzer & Search Diagnostics",
                "body": format_mutalyzer_diagnostics(fake_diag),
                "evidence_ids": ["chunk-1", "chunk-2", "chunk-3", "chunk-4", "chunk-5"],
            },
        ],
        "evidence": [
            {
                "id": "chunk-1",
                "kind": "text_chunk",
                "title": "Chunk 1",
                "reason": "Retriever matched variant alias: c.1319T>G / p.L440R",
                "query_variant": "NM_017739.1:c.1319T>G",
                "source": "local",
                "chunk_index": 1,
                "page": None,
                "text": _compact(chunk_1),
                "raw_text": chunk_1,
            },
            {
                "id": "chunk-2",
                "kind": "text_chunk",
                "title": "Chunk 2",
                "reason": "Retriever matched in-trans / compound heterozygous context",
                "query_variant": "NM_017739.1:c.1319T>G",
                "source": "local",
                "chunk_index": 2,
                "page": None,
                "text": _compact(chunk_2),
                "raw_text": chunk_2,
            },
            {
                "id": "chunk-3",
                "kind": "text_chunk",
                "title": "Chunk 3",
                "reason": "Functional assay evidence for p.L440R pathogenicity",
                "query_variant": "NM_017739.1:c.1319T>G",
                "source": "local",
                "chunk_index": 3,
                "page": None,
                "text": _compact(chunk_3),
                "raw_text": chunk_3,
            },
            {
                "id": "chunk-4",
                "kind": "text_chunk",
                "title": "Chunk 4",
                "reason": "Subcellular localization evidence for mutant POMGnT1",
                "query_variant": "NM_017739.1:c.1319T>G",
                "source": "local",
                "chunk_index": 4,
                "page": None,
                "text": _compact(chunk_4),
                "raw_text": chunk_4,
            },
            {
                "id": "chunk-5",
                "kind": "text_chunk",
                "title": "Chunk 5",
                "reason": "Additional cohort variant context",
                "query_variant": "NM_017739.1:c.1319T>G",
                "source": "local",
                "chunk_index": 5,
                "page": None,
                "text": _compact(chunk_5),
                "raw_text": chunk_5,
            },
        ],
        "document_markdown": markdown_text,
    }


st.set_page_config(page_title="AutoPM3 - Markdown Evidence", layout="wide")

st.title("AutoPM3 - Markdown Evidence")
st.markdown(
    "Upload MinerU-style Markdown to inspect AutoPM3 conclusions together "
    "with the source chunks that supported them."
)

col1, col2 = st.columns(2)
with col1:
    api_url = st.text_input(
        "API URL",
        placeholder="https://api.openai.com/v1",
        help="OpenAI-compatible API endpoint URL",
        value=config_value("OPENAI_API_URL", "openai_api_url", "https://api.openai.com/v1"),
    )
with col2:
    model_name = st.text_input(
        "Model Name",
        placeholder="gpt-4o-mini",
        help="Model name to use",
        value=config_value("OPENAI_MODEL", "openai_model", "gpt-4o-mini"),
    )

api_key = st.text_input(
    "API Key",
    type="password",
    key="api_key_markdown_evidence",
    value=config_value("OPENAI_API_KEY", "openai_api_key"),
)

st.header("Upload Paper")
if st.button("Example", type="primary"):
    st.session_state.variant_name_markdown_evidence = "NM_004004.5:c.71G>A"

variant_name = st.text_input(
    "Step 1. Enter the variant (HGVS notation)",
    key="variant_name_markdown_evidence",
)
paper_file = st.file_uploader(
    "Step 2. Upload Markdown paper",
    type=["md", "markdown", "txt"],
)

run_col, test_col = st.columns([1, 1])
with run_col:
    run_clicked = st.button("Run", type="primary", key="run_markdown_evidence")
with test_col:
    test_clicked = bool(os.environ.get("TEST_MODE") == "ON") and st.button(
        "Run Test",
        key="run_test_markdown_evidence",
        help="Render fake linked evidence data without making API calls.",
    )

if run_clicked:
    if paper_file and variant_name and api_url and model_name:
        try:
            paper_path = extract_paper_content(paper_file)
            summarized_results = run_query_markdown_evidence(
                variant_name,
                paper_path,
                api_url,
                model_name,
                api_key,
            )
            st.session_state["markdown_evidence_result"] = summarized_results
        except Exception:
            st.write("An error has occurred.")
            st.code(traceback.format_exc())
    else:
        st.write("Please enter API URL, model name, API key, variant and upload Markdown.")

if test_clicked:
    st.session_state["markdown_evidence_result"] = _build_fake_result()

if st.session_state.get("markdown_evidence_result"):
    render_result(st.session_state["markdown_evidence_result"])
