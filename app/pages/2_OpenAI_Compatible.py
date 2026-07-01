# Make the project root importable when launched via `streamlit run app/main.py`.
# Streamlit inserts the script's directory (app/pages/) into sys.path[0], which
# hides the `app` package from absolute imports. Inserting the project root up
# front lets `from app.core...` resolve correctly without requiring PYTHONPATH.
import sys
from pathlib import Path
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st
import os
import traceback

from app.core.query import query_variant_in_paper_xml, format_mutalyzer_diagnostics
from app.core.streamlit_helpers import (
    config_value,
    extract_paper_content,
    render_result,
    render_testmode_model_trace,
    run_async_query,
    set_testmode_fake_model_trace,
)


def run_query_openai(variant_name, xml_path, api_url, model_name, api_key):
    """Run the query using OpenAI-compatible API and return results."""
    summarized_results = run_async_query(
        query_variant_in_paper_xml,
        variant_name, xml_path,
        model_name,  # model_name_table
        model_name,  # model_name_text
        api_key,
        api_url=api_url,
    )
    return summarized_results


def _build_fake_result():
    """Build a realistic-looking result dict using the canonical example
    NM_004004.5:c.71G>A → p.(Leu24Arg). Exercises every formatting path
    (tables, code blocks, emoji, lists, the full Mutalyzer diagnostics block)
    so style changes can be eyeballed without running a real query.
    """
    fake_diag = {
        "input_hgvs": "NM_004004.5:c.71G>A",
        "var_dna": "71G>A",
        "mutalyzer": {
            "endpoint": "https://mutalyzer.nl/api/normalize/NM_004004.5:c.71G>A?only_variants=false",
            "raw_protein_description": "NP_003995.2:p.(Leu24Arg)",
            "protein_after_p_strip": "Leu24Arg",
            "trimmed_long": "Leu24Arg",
            "trimmed_short": "L24R",
            "c_protein_id_digits": ["24"],
            "status": "ok",
            "error": None,
        },
        "dna_search": {
            "regex_pattern": r"\s*71\s*G\s*>\s*A",
            "matched": True,
            "chunk_count": 3,
        },
        "protein_search": {
            "long_form": "Leu24Arg",
            "short_form": "L24R",
            "long_matched": True,
            "short_matched": True,
            "chunk_count_long": 2,
            "chunk_count_short": 2,
        },
        "position_fallback": {
            "triggered": False,
            "dna_pattern": r"\D71\D",
            "protein_pattern": r"\D24\D",
            "matched": False,
            "chunk_count": 0,
        },
        "retriever_summary": {
            "ok": True,
            "total_chunks_returned": 5,
            "short_protein": "L24R",
        },
    }
    return {
        "title": "Output Summary",
        "sections": [
            {
                "title": "Query Variant and Relative Intrans-variant / Genotype Found in PaperTables",
                "body": (
                    "**Table 1.** Patient cohort and genotype-phenotype correlation.\n\n"
                    "| Patient ID | Variant (DNA) | Variant (protein) | Genotype | Phenotype |\n"
                    "|---|---|---|---|---|\n"
                    "| P001 | c.71G>A | p.Leu24Arg | Heterozygous | Non-syndromic hearing loss |\n"
                    "| P002 | c.71G>A + c.269T>C | p.Leu24Arg + p.Phe90Ser | Compound het | Non-syndromic hearing loss |\n"
                    "| P003 | c.71G>A | p.Leu24Arg | Homozygous | Severe hearing loss |\n"
                ),
            },
            {
                "title": "Query Variant Found in PaperText",
                "body": (
                    "- **[DNA match result]**: Yes, the variant `c.71G>A` was identified in 3 unrelated "
                    "families. The substitution affects a highly conserved residue in the transmembrane domain.\n\n"
                    "- **[Protein match result]**: Confirmed at the protein level — Leu24Arg destabilises "
                    "the channel pore."
                ),
            },
            {
                "title": "Query Variant's Intrans-variant Found in PaperText",
                "body": "*c.269T>C*, *c.512T>A*",
            },
            {
                "title": "Mutalyzer & Search Diagnostics",
                "body": format_mutalyzer_diagnostics(fake_diag),
            },
        ],
    }


# Page config
st.set_page_config(page_title="AutoPM3 - OpenAI Compatible", page_icon="🤖")

# Inject CSS for fixed-pixel centering of the result region.
# The .result-region-marker div is emitted right before render_result() —
# everything that follows it in the same Streamlit vertical block gets
# constrained to a fixed `max-width` and centered. Uses the modern `:has()`
# + sibling `~` selector to scope the rule to widgets that appear *after*
# the marker (inputs/buttons above the marker stay full-width).
RESULT_REGION_CSS = """
<style>
div:has(> .result-region-marker) ~ div {
    max-width: 1200px !important;
    margin-left: auto !important;
    margin-right: auto !important;
}
</style>
"""
st.markdown(RESULT_REGION_CSS, unsafe_allow_html=True)

st.title("AutoPM3 - OpenAI Compatible 🤖")

st.markdown("""
Use this page if you want to use your own **OpenAI-compatible API endpoint**
(e.g., local models, proxy servers, or other LLM providers).
""")

col1, col2 = st.columns(2)
with col1:
    api_url = st.text_input('API URL', placeholder='https://api.openai.com/v1', help='OpenAI-compatible API endpoint URL',
                            value=config_value("OPENAI_API_URL", "openai_api_url", "https://api.openai.com/v1"))
with col2:
    model_name = st.text_input('Model Name', placeholder='gpt-4o-mini', help='Model name to use',
                               value=config_value("OPENAI_MODEL", "openai_model", "gpt-4o-mini"))

api_key = st.text_input('API Key', type='password', key='api_key_openai',
                         value=config_value("OPENAI_API_KEY", "openai_api_key"))

st.header("Upload Paper")
if st.button('Example', type='primary'):
    st.session_state.variant_name_xml_openai = 'NM_004004.5:c.71G>A'

variant_name = st.text_input('Step 1. Enter the variant (HGVS notation)', key='variant_name_xml_openai')
paper_file = st.file_uploader('Step 2. Upload XML paper', type=['xml'])

run_col, test_col = st.columns([1, 1])
with run_col:
    run_clicked = st.button('Run', type='primary', key='run_xml_openai')
# Run Test is a developer-only affordance for previewing the result layout
# without making real API calls. Hidden by default; opt in at launch time with:
#     TEST_MODE=ON streamlit run app/main.py
# (or set TEST_MODE in your shell / .env). Comparing to the literal "ON" keeps
# accidental `TEST_MODE=1` or `TEST_MODE=true` from enabling it silently.
with test_col:
    if os.environ.get("TEST_MODE") == "ON":
        test_clicked = st.button(
            'Run Test',
            key='run_test_openai',
            help='Render with fake example data (NM_004004.5:c.71G>A) — no API call, no XML needed. Useful for previewing styles.',
        )
    else:
        test_clicked = False

# ── Output region ──
# Both buttons render their output into the SAME region below, so the
# horizontal position is identical regardless of which button triggered
# it. Width is controlled by CSS (max-width: 1200px) injected at the top
# of the page — we just emit a marker div here to anchor the rule.
st.markdown('<div class="result-region-marker"></div>', unsafe_allow_html=True)
if run_clicked:
    if paper_file and variant_name and api_url and model_name:
        try:
            paper_path = extract_paper_content(paper_file)
            summarized_results = run_query_openai(variant_name, paper_path, api_url, model_name, api_key)
            render_result(summarized_results)
        except Exception as e:
            st.write('An error has occurred.')
            st.code(traceback.format_exc())
    else:
        st.write('Please enter API URL, model name, API key, variant and upload XML.')
if test_clicked:
    set_testmode_fake_model_trace()
    render_result(_build_fake_result())

render_testmode_model_trace()
