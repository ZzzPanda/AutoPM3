# Make the project root importable when launched via `streamlit run app/main.py`.
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import os
import traceback

import streamlit as st

from app.core.query import query_pm3_evidence_workflow, query_pm3_paper_intake
from app.core.streamlit_helpers import (
    config_value,
    extract_paper_content,
    render_result,
    render_testmode_model_trace,
    run_async_query,
    set_testmode_fake_model_trace,
)


TEST_MARKDOWN_PATH = (
    _PROJECT_ROOT
    / "data"
    / "pdf_convert"
    / "MinerU_markdown_PubMed23689641_2067159189227929600.md"
)


def run_pm3_paper_intake(paper_path, api_url, model_name, api_key):
    return run_async_query(
        query_pm3_paper_intake,
        paper_path,
        model_name,
        api_key,
        api_url=api_url,
    )


def run_pm3_workflow_query(variant_name, paper_path, api_url, model_name, api_key):
    return run_async_query(
        query_pm3_evidence_workflow,
        variant_name,
        paper_path,
        model_name,
        model_name,
        api_key,
        api_url=api_url,
    )


def _candidate_variant_options(result):
    raw = result.get("intake_raw") if isinstance(result, dict) else None
    if not isinstance(raw, dict):
        return []
    candidates = []
    for item in raw.get("candidate_variants", []):
        if not isinstance(item, dict):
            continue
        variant = str(item.get("variant") or "").strip()
        if not variant or variant.lower() == "not stated":
            continue
        label_bits = [variant]
        protein = str(item.get("protein_change") or "").strip()
        case_ids = str(item.get("case_ids") or "").strip()
        if protein and protein.lower() != "not stated":
            label_bits.append(protein)
        if case_ids and case_ids.lower() != "not stated":
            label_bits.append(case_ids)
        candidates.append((" · ".join(label_bits), variant))
    return list(dict.fromkeys(candidates))


def _candidate_variant_rows(result):
    raw = result.get("intake_raw") if isinstance(result, dict) else None
    if not isinstance(raw, dict):
        return []
    rows = []
    for item in raw.get("candidate_variants", []):
        if not isinstance(item, dict):
            continue
        variant = str(item.get("variant") or "").strip()
        if not variant or variant.lower() == "not stated":
            continue
        rows.append(
            {
                "Variant": variant,
                "Protein": item.get("protein_change", "not stated"),
                "Gene": item.get("gene", "not stated"),
                "Cases": item.get("case_ids", "not stated"),
                "Context": item.get("zygosity_or_context", "not stated"),
                "Partner allele": item.get("second_allele_or_partner", "not stated"),
            }
        )
    return rows


def _build_fake_intake_result():
    markdown_text = TEST_MARKDOWN_PATH.read_text(encoding="utf-8", errors="replace")
    evidence = [
        {
            "id": "chunk-1",
            "kind": "text_chunk",
            "title": "Chunk 1",
            "reason": "PM3 intake candidate chunk: case table with genotype context",
            "query_variant": "paper-intake",
            "source": "local",
            "chunk_index": 1,
            "page": None,
            "text": (
                "Table and text report three Chinese MEB disease patients with "
                "compound heterozygous POMGnT1 variants, including Case 1 with "
                "c.1319T>G / p.L440R and c.1896-1G>C."
            ),
            "raw_text": markdown_text[:2500],
        },
        {
            "id": "chunk-2",
            "kind": "text_chunk",
            "title": "Chunk 2",
            "reason": "PM3 intake candidate chunk: family and phase context",
            "query_variant": "paper-intake",
            "source": "local",
            "chunk_index": 2,
            "page": None,
            "text": (
                "The paper describes parental segregation and reports Case 1 had "
                "a paternally inherited intronic c.1896-1G>C change."
            ),
            "raw_text": markdown_text[2500:5200],
        },
    ]
    intake_raw = {
        "paper_summary": {
            "conclusion": "This paper likely contains PM3-relevant patient evidence for POMGnT1 in MEB disease.",
            "disease_or_phenotype": "muscle-eye-brain disease / congenital muscular dystrophy phenotype",
            "gene_or_locus": "POMGnT1",
            "study_type": "cohort",
            "pm3_readiness": "ready for target variant review",
            "evidence_ids": ["chunk-1", "chunk-2"],
        },
        "candidate_variants": [
            {
                "variant": "NM_017739.1:c.1319T>G",
                "protein_change": "p.L440R",
                "gene": "POMGnT1",
                "transcript": "NM_017739.1",
                "case_ids": "Case 1",
                "zygosity_or_context": "compound heterozygous",
                "second_allele_or_partner": "c.1896-1G>C",
                "why_candidate": "Case 1 carries this variant with a second POMGnT1 allele in the disease context.",
                "needs_user_variant_input": "Use transcript-normalized HGVS, e.g. NM_017739.1:c.1319T>G.",
                "evidence_ids": ["chunk-1"],
            },
            {
                "variant": "c.1896-1G>C",
                "protein_change": "not stated",
                "gene": "POMGnT1",
                "transcript": "not stated",
                "case_ids": "Case 1",
                "zygosity_or_context": "compound heterozygous partner allele",
                "second_allele_or_partner": "c.1319T>G / p.L440R",
                "why_candidate": "This splice-site allele is reported as the other allele in Case 1.",
                "needs_user_variant_input": "Add transcript prefix before running PM3 if needed.",
                "evidence_ids": ["chunk-1", "chunk-2"],
            },
        ],
        "candidate_cases": [],
        "family_evidence": [],
        "deduplication_clues": [],
        "next_steps": {
            "conclusion": "Choose one candidate variant, normalize to transcript HGVS, then run PM3 Evidence Workflow.",
            "suggested_variant_inputs": ["NM_017739.1:c.1319T>G"],
            "evidence_ids": ["chunk-1"],
        },
    }
    return {
        "title": "PM3 Paper Intake",
        "sections": [
            {
                "title": "论文 PM3 信息概览",
                "body": (
                    "**Conclusion:** This paper likely contains PM3-relevant patient evidence for POMGnT1.\n\n"
                    "- **Disease/phenotype:** muscle-eye-brain disease\n"
                    "- **Gene/locus:** POMGnT1\n"
                    "- **Study type:** cohort\n"
                    "- **PM3 readiness:** ready for target variant review"
                ),
                "evidence_ids": ["chunk-1", "chunk-2"],
                "section_id": "paper-summary",
            },
            {
                "title": "候选变异 1: NM_017739.1:c.1319T>G",
                "body": (
                    "**Conclusion:** Case 1 carries this variant with a second POMGnT1 allele.\n\n"
                    "- **Variant:** NM_017739.1:c.1319T>G\n"
                    "- **Protein change:** p.L440R\n"
                    "- **Gene:** POMGnT1\n"
                    "- **Case IDs:** Case 1\n"
                    "- **Zygosity/context:** compound heterozygous\n"
                    "- **Second allele/partner:** c.1896-1G>C"
                ),
                "evidence_ids": ["chunk-1"],
                "section_id": "candidate-variant-1",
            },
            {
                "title": "下一步：补充 Variant 后运行 PM3",
                "body": (
                    "**Conclusion:** Choose one candidate variant, normalize to transcript HGVS, then run PM3 Evidence Workflow.\n\n"
                    "- **Suggested variant inputs:** NM_017739.1:c.1319T>G"
                ),
                "evidence_ids": ["chunk-1"],
                "section_id": "next-steps",
            },
        ],
        "evidence": evidence,
        "document_markdown": markdown_text,
        "intake_raw": intake_raw,
    }


def _build_fake_workflow_result_from_intake(variant_name):
    markdown_text = TEST_MARKDOWN_PATH.read_text(encoding="utf-8", errors="replace")
    selected_variant = variant_name or "NM_017739.1:c.1319T>G"
    evidence = [
        {
            "id": "chunk-1",
            "kind": "text_chunk",
            "title": "Chunk 1",
            "reason": f"Prepared PM3 test chunk for {selected_variant}",
            "query_variant": selected_variant,
            "source": "local",
            "chunk_index": 1,
            "page": None,
            "text": (
                "Case 1 is reported with POMGnT1 variants c.1319T>G / p.L440R "
                "and c.1896-1G>C in the muscle-eye-brain disease context."
            ),
            "raw_text": markdown_text[:2500],
        },
        {
            "id": "chunk-2",
            "kind": "text_chunk",
            "title": "Chunk 2",
            "reason": "Prepared PM3 test chunk for family/segregation review",
            "query_variant": selected_variant,
            "source": "local",
            "chunk_index": 2,
            "page": None,
            "text": (
                "The paper reports parental segregation context, including a "
                "paternally inherited c.1896-1G>C allele for Case 1."
            ),
            "raw_text": markdown_text[2500:5200],
        },
    ]
    return {
        "title": "PM3 Evidence Workflow",
        "sections": [
            {
                "title": "标准化结论",
                "body": (
                    "该变异已在至少1名患有muscle-eye-brain disease相关表型的个体中被检测到。\n"
                    "其中1名为该变异与一个致病性或可能致病性变异 c.1896-1G>C 的复合杂合，\n"
                    "其中[待确认]名通过父母/家庭检测/其他方法待确认确认处于反式位置。\n"
                    "0名个体为该变异纯合。[PMID:23689641]"
                ),
                "evidence_ids": [],
                "section_id": "standardized-conclusion",
                "style": "standardized",
                "linked_section_ids": ["case-1", "family-1", "scoring-summary"],
            },
            {
                "title": "病例证据 1",
                "body": (
                    f"**Conclusion:** Case 1 carries `{selected_variant}` in a compound heterozygous "
                    "POMGnT1 disease context.\n\n"
                    "- **Case ID:** Case 1\n"
                    "- **Disease/phenotype:** muscle-eye-brain disease\n"
                    f"- **Target variant:** {selected_variant}\n"
                    "- **Second allele:** c.1896-1G>C\n"
                    "- **Zygosity/phase:** compound heterozygous; phase needs manual review\n"
                    "- **PM3 relevance:** needs manual review"
                ),
                "evidence_ids": ["chunk-1", "chunk-2"],
                "section_id": "case-1",
            },
            {
                "title": "家系证据 1",
                "body": (
                    "**Conclusion:** Family evidence is present but requires manual review for exact trans confirmation.\n\n"
                    "- **Family ID:** Case 1 family\n"
                    "- **Parents tested:** yes / reported in paper context\n"
                    "- **Parental genotypes:** paternally inherited c.1896-1G>C is reported\n"
                    "- **Phase/trans support:** needs manual review"
                ),
                "evidence_ids": ["chunk-2"],
                "section_id": "family-1",
            },
            {
                "title": "人工算分依据",
                "body": (
                    "**Conclusion:** Prepared test data supports UI validation only; real scoring still needs model/manual review.\n\n"
                    "- **Included case count:** 1 needs review\n"
                    "- **PM3 level:** needs manual review"
                ),
                "evidence_ids": ["chunk-1", "chunk-2"],
                "section_id": "scoring-summary",
            },
        ],
        "evidence": evidence,
        "document_markdown": markdown_text,
    }


st.set_page_config(page_title="AutoPM3 - PM3 Paper Intake", layout="wide")

st.markdown(
    """
    <style>
    .stApp .block-container {
        max-width: 100%;
        padding-left: 1.25rem;
        padding-right: 1.25rem;
        padding-top: 1.5rem;
    }
    .stApp [data-testid="stHorizontalBlock"] {
        gap: 1rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("AutoPM3 - PM3 Paper Intake")
st.markdown(
    "Upload a Markdown paper first, extract PM3-ready candidate variants/cases/family evidence, "
    "then choose or enter a variant to run the full PM3 evidence workflow."
)

inputs_expanded = not bool(st.session_state.get("pm3_intake_result"))
with st.expander("输入与运行", expanded=inputs_expanded):
    col1, col2 = st.columns(2)
    with col1:
        api_url = st.text_input(
            "API URL",
            placeholder="https://api.openai.com/v1",
            help="OpenAI-compatible API endpoint URL",
            value=config_value("OPENAI_API_URL", "openai_api_url", "https://api.openai.com/v1"),
            key="api_url_pm3_intake",
        )
    with col2:
        model_name = st.text_input(
            "Model Name",
            placeholder="gpt-4o-mini",
            help="Model name to use",
            value=config_value("OPENAI_MODEL", "openai_model", "gpt-4o-mini"),
            key="model_name_pm3_intake",
        )

    api_key = st.text_input(
        "API Key",
        type="password",
        key="api_key_pm3_intake",
        value=config_value("OPENAI_API_KEY", "openai_api_key"),
    )

    paper_file = st.file_uploader(
        "Upload Markdown paper",
        type=["md", "markdown", "txt"],
        key="paper_file_pm3_intake",
    )

    run_col, test_col = st.columns([1, 1])
    with run_col:
        intake_clicked = st.button("Extract Paper Info", type="primary", key="run_pm3_intake")
    with test_col:
        test_mode_enabled = bool(os.environ.get("TEST_MODE") == "ON")
        test_clicked = test_mode_enabled and st.button(
            "Run Test",
            key="run_test_pm3_intake",
            help="Render prepared fake PM3 intake evidence without making API calls.",
        )

if intake_clicked:
    if paper_file and api_url and model_name:
        try:
            paper_path = extract_paper_content(paper_file)
            st.session_state["pm3_intake_paper_path"] = paper_path
            st.session_state["pm3_intake_result"] = run_pm3_paper_intake(
                paper_path,
                api_url,
                model_name,
                api_key,
            )
            st.session_state.pop("pm3_intake_workflow_result", None)
        except Exception:
            st.write("An error has occurred.")
            st.code(traceback.format_exc())
    else:
        st.write("Please enter API URL, model name and upload Markdown.")

if test_clicked:
    set_testmode_fake_model_trace()
    st.session_state["pm3_intake_paper_path"] = str(TEST_MARKDOWN_PATH)
    st.session_state["pm3_intake_result"] = _build_fake_intake_result()
    st.session_state.pop("pm3_intake_workflow_result", None)

if st.session_state.get("pm3_intake_result"):
    st.header("Next: Run PM3 With Selected Variant")
    options = _candidate_variant_options(st.session_state["pm3_intake_result"])
    candidate_rows = _candidate_variant_rows(st.session_state["pm3_intake_result"])
    if candidate_rows:
        st.table(candidate_rows)

    selected_variant = ""
    if options:
        labels = [label for label, _value in options]
        selected_label = st.selectbox(
            "Candidate variants extracted from the paper",
            labels,
            key="pm3_intake_candidate_variant_select",
        )
        selected_variant = dict(options).get(selected_label, "")
        if st.session_state.get("pm3_intake_previous_candidate_label") != selected_label:
            st.session_state["variant_name_pm3_intake_workflow"] = selected_variant
            st.session_state["pm3_intake_previous_candidate_label"] = selected_label
        st.caption("You can edit the final HGVS input below before running PM3.")
    else:
        st.info("No candidate variants were extracted. Enter a transcript-normalized variant manually.")

    if "variant_name_pm3_intake_workflow" not in st.session_state:
        st.session_state["variant_name_pm3_intake_workflow"] = selected_variant

    variant_name = st.text_input(
        "Variant for PM3 workflow",
        key="variant_name_pm3_intake_workflow",
        help="Use transcript-normalized HGVS when available, e.g. NM_017739.1:c.1319T>G.",
    )
    if st.button("Run PM3 Evidence Workflow", type="primary", key="run_pm3_from_intake"):
        paper_path = st.session_state.get("pm3_intake_paper_path")
        if paper_path and variant_name and api_url and model_name:
            try:
                if test_mode_enabled and paper_path == str(TEST_MARKDOWN_PATH):
                    st.session_state["pm3_intake_workflow_result"] = _build_fake_workflow_result_from_intake(
                        variant_name
                    )
                else:
                    st.session_state["pm3_intake_workflow_result"] = run_pm3_workflow_query(
                        variant_name,
                        paper_path,
                        api_url,
                        model_name,
                        api_key,
                    )
            except Exception:
                st.write("An error has occurred.")
                st.code(traceback.format_exc())
        else:
            st.write("Please provide a paper, API config and variant before running PM3.")

if st.session_state.get("pm3_intake_workflow_result"):
    st.header("PM3 Evidence Workflow Result")
    render_result(
        st.session_state["pm3_intake_workflow_result"],
        key_prefix="pm3_intake_workflow",
    )

if st.session_state.get("pm3_intake_result"):
    st.header("Extracted Paper Info")
    render_result(
        st.session_state["pm3_intake_result"],
        key_prefix="pm3_intake",
    )

render_testmode_model_trace()
