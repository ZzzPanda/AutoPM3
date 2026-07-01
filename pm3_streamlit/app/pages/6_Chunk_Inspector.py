# Make the project root importable when launched via `streamlit run app/main.py`.
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

from app.core.markdown_splitter import (
    KIND_FENCE,
    KIND_HTML_TABLE,
    KIND_IMAGE,
    KIND_PARAGRAPH,
    KIND_PARAGRAPH_SPLIT,
    KIND_PIPE_TABLE,
    markdown_aware_split,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


TEST_MARKDOWN_PATH = (
    _PROJECT_ROOT
    / "data"
    / "pdf_convert"
    / "MinerU_markdown_PubMed23689641_2067159189227929600.md"
)


# Color legend. Background tints that don't fight with Streamlit's light
# theme; kept readable on both light and dark backgrounds.
KIND_STYLE = {
    KIND_HTML_TABLE:      {"bg": "#ffe3e3", "border": "#c92a2a", "label": "HTML table"},
    KIND_PIPE_TABLE:      {"bg": "#fff3bf", "border": "#e67700", "label": "Pipe table"},
    KIND_FENCE:           {"bg": "#fff9db", "border": "#b08900", "label": "Fenced code"},
    KIND_PARAGRAPH:       {"bg": "#d0ebff", "border": "#1864ab", "label": "Paragraph"},
    KIND_PARAGRAPH_SPLIT: {"bg": "#e7f5ff", "border": "#339af0", "label": "Paragraph (split)"},
    KIND_IMAGE:           {"bg": "#e5dbff", "border": "#5f3dc4", "label": "Image"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@st.cache_data(show_spinner=False)
def _load_example() -> str:
    return TEST_MARKDOWN_PATH.read_text(encoding="utf-8", errors="replace")


def _run_new(text: str, chunk_size: int, chunk_overlap: int) -> list[Document]:
    return markdown_aware_split(
        text,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )


def _run_baseline(text: str, chunk_size: int, chunk_overlap: int) -> list[Document]:
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    ).split_documents([Document(page_content=text, metadata={"source": "local"})])


def _kind_distribution(chunks: list[Document]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in chunks:
        k = c.metadata.get("chunk_kind", "(none)")
        out[k] = out.get(k, 0) + 1
    return out


def _table_integrity(chunks: list[Document]) -> tuple[int, int]:
    """Return (atomic_html_tables, partial_html_tables).

    atomic = a chunk with a complete ``<table>...</table>`` block.
    partial = a chunk with an opening ``<table>`` but no matching
    ``</table>``, OR a ``</table>`` without an opening ``<table>``.
    """
    atomic = 0
    partial = 0
    for c in chunks:
        opens = c.page_content.count("<table")
        closes = c.page_content.count("</table>")
        if opens == 0 and closes == 0:
            continue
        if opens == closes and opens > 0:
            atomic += opens
        else:
            partial += max(opens, closes)
    return atomic, partial


def _row_sliced_chunks(chunks: list[Document]) -> int:
    return sum(
        1 for c in chunks
        if c.page_content.count("<tr") != c.page_content.count("</tr>")
    )


def _variant_hits(chunks: list[Document], needles: list[str]) -> dict[str, int]:
    return {n: sum(1 for c in chunks if n in c.page_content) for n in needles}


def _style_for_kind(kind: str) -> dict[str, str]:
    return KIND_STYLE.get(kind, {"bg": "#f1f3f5", "border": "#868e96", "label": kind})


def _render_chunk_card(chunk: Document, idx: int) -> None:
    style = _style_for_kind(chunk.metadata.get("chunk_kind", ""))
    bg = style["bg"]
    border = style["border"]
    label = style["label"]
    length = len(chunk.page_content)
    heading = chunk.metadata.get("source_heading") or ""
    heading_html = (
        f'<span style="background:#e9ecef;padding:1px 6px;border-radius:3px;'
        f'font-family:monospace;">{heading}</span>'
        if heading
        else '<span style="color:#adb5bd;">no heading</span>'
    )

    st.markdown(
        f"""
        <div style="
            background:{bg};
            border-left:5px solid {border};
            border-radius:4px;
            padding:10px 14px;
            margin-bottom:6px;
            font-family:monospace;
        ">
          <div style="display:flex; gap:16px; align-items:center; font-family:sans-serif;
                      font-size:13px; margin-bottom:6px;">
            <b>#{idx}</b>
            <span style="background:{border};color:white;padding:2px 8px;border-radius:3px;">
              {label}
            </span>
            <span>{length} chars</span>
            <span style="color:#495057;">{heading_html}</span>
          </div>
          <pre style="white-space:pre-wrap; word-break:break-word; margin:0;
                      color:#212529; max-height:280px; overflow-y:auto;">{chunk.page_content[:6000].replace("<", "&lt;")}</pre>
          {f'<div style="font-size:11px;color:#868e96;margin-top:4px;">…{length - 6000} more chars hidden</div>' if length > 6000 else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_legend() -> None:
    pills = []
    for kind, s in KIND_STYLE.items():
        pills.append(
            f'<span style="display:inline-block;background:{s["bg"]};'
            f'border:1px solid {s["border"]};border-radius:12px;padding:2px 10px;'
            f'margin-right:6px;font-size:12px;color:#212529;">'
            f'{s["label"]}</span>'
        )
    st.markdown(
        '<div style="margin-bottom:8px;"><b>Legend:</b> '
        + "".join(pills)
        + "</div>",
        unsafe_allow_html=True,
    )


def _render_stats(label: str, chunks: list[Document], needles: list[str] | None = None) -> None:
    if not chunks:
        st.warning(f"{label}: produced 0 chunks")
        return
    kinds = _kind_distribution(chunks)
    lengths = [len(c.page_content) for c in chunks]
    atomic, partial = _table_integrity(chunks)
    row_sliced = _row_sliced_chunks(chunks)
    heading_chunks = sum(
        1 for c in chunks if c.metadata.get("source_heading") is not None
    )

    cols = st.columns(6)
    cols[0].metric("Chunks", len(chunks))
    cols[1].metric("Min / Max / Avg len",
                   f"{min(lengths)} / {max(lengths)} / {sum(lengths)//len(lengths)}")
    cols[2].metric("Distinct kinds", len(kinds))
    cols[3].metric("HTML tables atomic / partial", f"{atomic} / {partial}")
    cols[4].metric("Chunks w/ sliced `<tr>`", row_sliced)
    cols[5].metric("With source_heading", f"{heading_chunks}/{len(chunks)}")

    kind_str = ", ".join(f"{k}={v}" for k, v in sorted(kinds.items(), key=lambda kv: -kv[1]))
    st.caption(f"Kind distribution: {kind_str}")

    if needles:
        hits = _variant_hits(chunks, needles)
        miss = [n for n, c in hits.items() if c == 0]
        if miss:
            st.error(f"❌ Missing in chunks: {', '.join(repr(m) for m in miss)}")
        else:
            ok_chunks = {n: c for n, c in hits.items()}
            st.success(f"✅ All {len(needles)} variants retrievable — hits: {ok_chunks}")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


st.set_page_config(page_title="AutoPM3 - Chunk Inspector", layout="wide")
st.title("AutoPM3 — Chunk Inspector")
st.markdown(
    "Visually inspect how the markdown-aware chunker splits a document. "
    "Each chunk is shown as a colored card (color = block kind) so you can "
    "spot mid-row table slicing, oversized paragraphs, or wrong source_heading "
    "propagation at a glance."
)

with st.sidebar:
    st.header("1. Source")
    source_choice = st.radio("Pick source", ["Example", "Upload", "Paste"], label_visibility="collapsed")

    if source_choice == "Example":
        markdown_text = _load_example()
        st.success(f"Loaded {len(markdown_text):,} chars from {TEST_MARKDOWN_PATH.name}")
    elif source_choice == "Upload":
        uploaded = st.file_uploader("Markdown file", type=["md", "markdown", "txt"])
        if uploaded is None:
            markdown_text = ""
            st.info("Awaiting upload…")
        else:
            markdown_text = uploaded.read().decode("utf-8", errors="replace")
            st.success(f"Uploaded {len(markdown_text):,} chars")
    else:
        markdown_text = st.text_area(
            "Paste markdown",
            value=(
                "# Sample\n\n"
                "Intro paragraph.\n\n"
                "<table><tr><td>1</td><td>c.1319T&gt;G</td></tr></table>\n\n"
                "Outro.\n"
            ),
            height=240,
        )

    st.divider()
    st.header("2. Chunker parameters")
    chunk_size = st.slider("chunk_size", 200, 4000, 1800, step=100)
    chunk_overlap = st.slider("chunk_overlap", 0, min(500, chunk_size - 100), 200, step=50)

    st.divider()
    st.header("3. Variant needles (optional)")
    default_needles = (
        "c.1319T &gt; G, p.L440R",
        "p.V633EfxX53",
        "c.1896-1 G [ C",
    )
    needles_text = st.text_area(
        "Substrings to search for in chunks (one per line)",
        value="\n".join(default_needles),
        height=80,
    )
    needles = [n.strip() for n in needles_text.splitlines() if n.strip()]

    show_baseline = st.checkbox("Also show LangChain baseline", value=True)

    st.divider()
    st.header("4. Display options")
    render_as_markdown = st.checkbox(
        "Render chunk content as markdown (instead of preformatted text)",
        value=False,
        help="When ON, code fences, tables and image refs inside chunks render "
             "as markdown. When OFF, chunks show as raw text — better for "
             "spotting slicing issues.",
    )


if not markdown_text.strip():
    st.info("Pick or paste a markdown source from the sidebar to start.")
    st.stop()


_render_legend()


new_chunks = _run_new(markdown_text, chunk_size, chunk_overlap)


tab_titles = ["🟢 NEW (markdown-aware)"]
if show_baseline:
    tab_titles += ["🔴 OLD (LangChain)", "⚖️ Side-by-side"]
tabs = st.tabs(tab_titles)


# --- Tab 1: NEW ----------------------------------------------------------
with tabs[0]:
    st.subheader("Markdown-aware chunker")
    _render_stats("NEW chunker", new_chunks, needles=needles or None)

    sort_options = ["Document order", "By length", "By chunk_kind"]
    sort_choice = st.radio(
        "Sort chunks by", sort_options, horizontal=True, key="new_sort"
    )
    indexed = list(enumerate(new_chunks, start=1))
    if sort_choice == "By length":
        indexed.sort(key=lambda kv: -len(kv[1].page_content))
    elif sort_choice == "By chunk_kind":
        indexed.sort(key=lambda kv: kv[1].metadata.get("chunk_kind", ""))

    for idx, c in indexed:
        with st.expander(
            f"#{idx} · {c.metadata.get('chunk_kind', '?')} · "
            f"{len(c.page_content)} chars · {c.metadata.get('source_heading') or 'no heading'}",
            expanded=False,
        ):
            _render_chunk_card(c, idx)
            if render_as_markdown:
                st.markdown("**Rendered markdown preview:**")
                try:
                    st.markdown(c.page_content)
                except Exception:
                    st.warning("Markdown rendering failed for this chunk.")


# --- Tab 2: OLD ----------------------------------------------------------
if show_baseline:
    with tabs[1]:
        st.subheader("LangChain baseline (RecursiveCharacterTextSplitter)")
        baseline_chunks = _run_baseline(markdown_text, chunk_size, chunk_overlap)
        _render_stats("LangChain baseline", baseline_chunks, needles=needles or None)

        for idx, c in enumerate(baseline_chunks, start=1):
            kind = "(langchain-baseline)"
            border = "#495057"
            bg = "#f8f9fa"
            with st.expander(
                f"#{idx} · {kind} · {len(c.page_content)} chars",
                expanded=False,
            ):
                st.markdown(
                    f"""
                    <div style="background:{bg};border-left:5px solid {border};
                                border-radius:4px;padding:10px 14px;
                                font-family:monospace;">
                      <pre style="white-space:pre-wrap;word-break:break-word;margin:0;
                                  max-height:280px;overflow-y:auto;">
                        {c.page_content[:6000].replace("<", "&lt;")}
                      </pre>
                      {f'<div style="font-size:11px;color:#868e96;margin-top:4px;">…{len(c.page_content) - 6000} more chars hidden</div>' if len(c.page_content) > 6000 else ''}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if render_as_markdown:
                    try:
                        st.markdown(c.page_content)
                    except Exception:
                        pass


# --- Tab 3: Compare ------------------------------------------------------
if show_baseline:
    with tabs[2]:
        st.subheader("Side-by-side comparison")
        baseline_chunks = _run_baseline(markdown_text, chunk_size, chunk_overlap)

        col_l, col_r = st.columns(2)
        with col_l:
            st.markdown("##### 🟢 NEW (markdown-aware)")
            _render_stats("NEW", new_chunks, needles=needles or None)
            for idx, c in enumerate(new_chunks, start=1):
                _render_chunk_card(c, idx)
        with col_r:
            st.markdown("##### 🔴 OLD (LangChain baseline)")
            _render_stats("OLD", baseline_chunks, needles=needles or None)
            for idx, c in enumerate(baseline_chunks, start=1):
                st.markdown(
                    f"""
                    <div style="background:#f8f9fa;border-left:5px solid #495057;
                                border-radius:4px;padding:8px 12px;margin-bottom:6px;
                                font-family:monospace;font-size:12px;">
                      <b>#{idx}</b> · {len(c.page_content)} chars
                      <pre style="white-space:pre-wrap;word-break:break-word;margin:6px 0 0 0;
                                  max-height:200px;overflow-y:auto;">
                        {c.page_content[:2000].replace("<", "&lt;")}
                      </pre>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )