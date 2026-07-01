# Make the project root importable when launched via `streamlit run app/main.py`.
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import hashlib
import html as html_lib
import os
import traceback

import streamlit as st

from app.core.query import query_pm3_evidence_workflow, translate_markdown_block_to_chinese
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


def run_pm3_workflow_query(variant_name, paper_path, api_url, model_name, api_key):
    """Run the PM3 workflow page query with Markdown input and linked chunks."""
    return run_async_query(
        query_pm3_evidence_workflow,
        variant_name,
        paper_path,
        model_name,
        model_name,
        api_key,
        api_url=api_url,
    )


def translate_block(title, body, api_url, model_name, api_key):
    """Translate one rendered block body to Chinese."""
    return run_async_query(
        translate_markdown_block_to_chinese,
        title,
        body,
        model_name,
        api_key,
        api_url=api_url,
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
    return compacted[: limit - 1].rstrip() + "..."


def _translation_cache_key(title: str, body: str, model_name: str) -> str:
    payload = f"{model_name}\n{title}\n{body}".encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def _render_translatable_section_body(idx, section, result, api_url, model_name, api_key):
    """Render one section body with in-block translation controls."""
    st.session_state.setdefault("pm3_workflow_translation_cache", {})
    st.session_state.setdefault("pm3_workflow_translated_sections", {})
    cache = st.session_state["pm3_workflow_translation_cache"]
    translated_sections = st.session_state["pm3_workflow_translated_sections"]

    title = section.get("title", f"Section {idx + 1}")
    body = section.get("body", "")
    cache_key = _translation_cache_key(title, body, model_name)
    translated_key = f"{idx}:{cache_key}"
    showing_translation = bool(translated_sections.get(translated_key))
    prepared_translations = result.get("test_translations", {}) if isinstance(result, dict) else {}
    prepared_translation = prepared_translations.get(_translation_cache_key(title, body, "TEST"))
    if prepared_translation and cache_key not in cache:
        cache[cache_key] = prepared_translation

    if st.button(
        "显示原文" if showing_translation else "翻译此块",
        key=f"pm3_translate_button_{translated_key}",
        help="翻译会保留 HGVS、基因名、PMID、chunk id、Markdown 标记和特殊术语。",
    ):
        if showing_translation:
            translated_sections[translated_key] = False
        else:
            if cache_key not in cache:
                try:
                    with st.spinner("正在翻译当前块..."):
                        cache[cache_key] = translate_block(
                            title,
                            body,
                            api_url,
                            model_name,
                            api_key,
                        )
                except Exception:
                    st.warning(f"翻译失败：{title}")
                    st.code(traceback.format_exc())
            if cache_key in cache:
                translated_sections[translated_key] = True
        st.rerun()

    rendered_body = cache[cache_key] if showing_translation and cache_key in cache else body
    if section.get("style") == "standardized":
        escaped = html_lib.escape(str(rendered_body)).replace("\n", "<br>")
        st.markdown(
            f"""
            <div style="
                border-left: 5px solid #2563eb;
                background: #eff6ff;
                color: #111827;
                padding: 0.85rem 1rem;
                border-radius: 6px;
                line-height: 1.65;
                margin-bottom: 0.75rem;
            ">{escaped}</div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(rendered_body)


@st.cache_data(show_spinner=False)
def _build_fake_workflow_result():
    markdown_text = TEST_MARKDOWN_PATH.read_text(encoding="utf-8", errors="replace")
    chunk_1 = _chunk_around(markdown_text, "c.1319T &gt; G, p.L440R")
    chunk_2 = _chunk_around(markdown_text, "c.1896-1 G [ C")
    evidence = [
        {
            "id": "chunk-1",
            "kind": "text_chunk",
            "title": "Chunk 1",
            "reason": "Retriever matched target variant c.1319T>G / p.L440R",
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
            "reason": "Retriever matched compound heterozygous context",
            "query_variant": "NM_017739.1:c.1319T>G",
            "source": "local",
            "chunk_index": 2,
            "page": None,
            "text": _compact(chunk_2),
            "raw_text": chunk_2,
        },
    ]
    result = {
        "title": "PM3 Evidence Workflow",
        "sections": [
            {
                "title": "标准化结论",
                "body": (
                    "该变异已在至少1名患有肌眼脑病相关表型的个体中被检测到。\n"
                    "其中1名为该变异与一个致病性或可能致病性变异 c.1896-1G>C 的复合杂合，\n"
                    "其中0名通过父母/家庭检测/其他方法确认处于反式位置。\n"
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
                    "**Conclusion:** Case 1 carries the target variant and a second "
                    "POMGnT1 allele reported in the same disease context.\n\n"
                    "- **Case ID:** Case 1\n"
                    "- **Source:** mixed table/text evidence\n"
                    "- **Family/relationship:** not stated in linked chunks\n"
                    "- **Disease/phenotype:** muscle-eye-brain disease related phenotype\n"
                    "- **Target variant:** c.1319T>G / p.L440R\n"
                    "- **Second allele:** c.1896-1G>C\n"
                    "- **Zygosity/phase:** compound heterozygous; phase needs manual review\n"
                    "- **Phase confirmation:** not stated in linked chunks\n"
                    "- **Segregation/parental testing:** not stated in linked chunks\n"
                    "- **PM3 relevance:** needs manual review"
                ),
                "evidence_ids": ["chunk-1", "chunk-2"],
                "section_id": "case-1",
            },
            {
                "title": "家系证据 1",
                "body": (
                    "**Conclusion:** The linked chunks do not state parental testing or "
                    "segregation evidence for Case 1, so trans confirmation remains manual review.\n\n"
                    "- **Family ID:** not stated\n"
                    "- **Proband/case:** Case 1\n"
                    "- **Parents tested:** not stated\n"
                    "- **Parental genotypes:** not stated in linked chunks\n"
                    "- **Siblings/relatives:** not stated in linked chunks\n"
                    "- **Phase/trans support:** phase unknown\n"
                    "- **Segregation relevance:** needs manual review"
                ),
                "evidence_ids": ["chunk-1", "chunk-2"],
                "section_id": "family-1",
            },
            {
                "title": "人工算分依据",
                "body": (
                    "**Conclusion:** The case supports PM3 review, but confirmed trans "
                    "status is not available in the linked chunks.\n\n"
                    "- **Included case count:** 1 needs review\n"
                    "- **PM3 level:** needs manual review"
                ),
                "evidence_ids": ["chunk-1", "chunk-2"],
                "section_id": "scoring-summary",
            },
            {
                "title": "变异证据 / Variant Evidence",
                "body": (
                    "- **[DNA match result]**: YES. The paper reports `c.1319T>G` "
                    "for Case 1.\n\n"
                    "- **[Protein match result]**: YES. The corresponding protein "
                    "change `p.L440R` is discussed."
                ),
                "evidence_ids": ["chunk-1"],
            },
            {
                "title": "反式位点证据 / In-trans Evidence",
                "body": "*c.1896-1G>C*",
                "evidence_ids": ["chunk-2"],
            },
        ],
        "evidence": evidence,
        "document_markdown": markdown_text,
    }
    result["test_translations"] = _build_fake_translations(result["sections"])
    return result


def _build_fake_translations(sections):
    translations_by_title = {
        "标准化结论": (
            "该变异已在至少1名患有肌眼脑病相关表型的个体中被检测到。\n"
            "其中1名为该变异与一个致病性或可能致病性变异 c.1896-1G>C 的复合杂合，\n"
            "其中0名通过父母/家庭检测/其他方法确认处于反式位置。\n"
            "0名个体为该变异纯合。[PMID:23689641]"
        ),
        "病例证据 1": (
            "**Conclusion:** Case 1 携带目标变异，以及在相同疾病背景中报道的另一个 "
            "POMGnT1 等位基因。\n\n"
            "- **Case ID:** Case 1\n"
            "- **Source:** mixed table/text evidence\n"
            "- **Family/relationship:** linked chunks 中未说明\n"
            "- **Disease/phenotype:** muscle-eye-brain disease 相关表型\n"
            "- **Target variant:** c.1319T>G / p.L440R\n"
            "- **Second allele:** c.1896-1G>C\n"
            "- **Zygosity/phase:** compound heterozygous；phase needs manual review\n"
            "- **Phase confirmation:** linked chunks 中未说明\n"
            "- **Segregation/parental testing:** linked chunks 中未说明\n"
            "- **PM3 relevance:** needs manual review"
        ),
        "家系证据 1": (
            "**Conclusion:** linked chunks 中没有说明 Case 1 的 parental testing 或 segregation evidence，"
            "因此 trans confirmation 仍需人工复核。\n\n"
            "- **Family ID:** not stated\n"
            "- **Proband/case:** Case 1\n"
            "- **Parents tested:** not stated\n"
            "- **Parental genotypes:** linked chunks 中未说明\n"
            "- **Siblings/relatives:** linked chunks 中未说明\n"
            "- **Phase/trans support:** phase unknown\n"
            "- **Segregation relevance:** needs manual review"
        ),
        "人工算分依据": (
            "**Conclusion:** 该病例支持进入 PM3 复核，但 linked chunks 中没有 confirmed trans 状态。\n\n"
            "- **Included case count:** 1 needs review\n"
            "- **PM3 level:** needs manual review"
        ),
        "变异证据 / Variant Evidence": (
            "- **[DNA match result]**: YES。论文报道 Case 1 存在 `c.1319T>G`。\n\n"
            "- **[Protein match result]**: YES。文中讨论了对应蛋白改变 `p.L440R`。"
        ),
        "反式位点证据 / In-trans Evidence": "*c.1896-1G>C*",
    }
    return {
        _translation_cache_key(section.get("title", ""), section.get("body", ""), "TEST"): translations_by_title[section["title"]]
        for section in sections
        if section.get("title") in translations_by_title
    }


st.set_page_config(page_title="AutoPM3 - PM3 Evidence Workflow", layout="wide")

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
    @media (max-width: 768px) {
        .stApp .block-container {
            padding-left: 0.75rem;
            padding-right: 0.75rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("AutoPM3 - PM3 Evidence Workflow")
st.markdown(
    "Upload MinerU-style Markdown to extract PM3 evidence with case-level "
    "screening, deduplication notes, manual scoring support, and linked source chunks."
)

inputs_expanded = not bool(st.session_state.get("pm3_workflow_result"))
with st.expander("输入与运行", expanded=inputs_expanded):
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
        key="api_key_pm3_workflow",
        value=config_value("OPENAI_API_KEY", "openai_api_key"),
    )

    st.header("Upload Paper")
    if st.button("Example", type="primary"):
        st.session_state.variant_name_pm3_workflow = "NM_017739.1:c.1319T>G"

    variant_name = st.text_input(
        "Step 1. Enter the variant (HGVS notation)",
        key="variant_name_pm3_workflow",
    )
    paper_file = st.file_uploader(
        "Step 2. Upload Markdown paper",
        type=["md", "markdown", "txt"],
    )

    run_col, test_col = st.columns([1, 1])
    with run_col:
        run_clicked = st.button("Run", type="primary", key="run_pm3_workflow")
    with test_col:
        test_mode_enabled = bool(os.environ.get("TEST_MODE") == "ON")
        if test_mode_enabled:
            _build_fake_workflow_result()
        test_clicked = test_mode_enabled and st.button(
            "Run Test",
            key="run_test_pm3_workflow",
            help="Render prepared fake PM3 workflow evidence without making API calls.",
        )
if run_clicked:
    if paper_file and variant_name and api_url and model_name:
        try:
            paper_path = extract_paper_content(paper_file)
            summarized_results = run_pm3_workflow_query(
                variant_name,
                paper_path,
                api_url,
                model_name,
                api_key,
            )
            st.session_state["pm3_workflow_result"] = summarized_results
        except Exception:
            st.write("An error has occurred.")
            st.code(traceback.format_exc())
    else:
        st.write("Please enter API URL, model name, API key, variant and upload Markdown.")

if test_clicked:
    set_testmode_fake_model_trace()
    st.session_state["pm3_workflow_result"] = _build_fake_workflow_result()

if st.session_state.get("pm3_workflow_result"):
    render_result(
        st.session_state["pm3_workflow_result"],
        section_body_renderer=lambda idx, section: _render_translatable_section_body(
            idx,
            section,
            st.session_state["pm3_workflow_result"],
            api_url,
            model_name,
            api_key,
        ),
    )

render_testmode_model_trace()
