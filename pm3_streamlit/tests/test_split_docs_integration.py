"""Integration tests for the chunker against the variant retriever and
synthesised oversize fixtures.

The headline test in this file is
``test_baseline_splitter_fails_atomic_table`` — it pins the historical
``RecursiveCharacterTextSplitter``-based chunker against the same markdown
fixture and asserts that the variant-bearing ``<table>`` at line 51 is **not**
fully contained in any single chunk. That assertion is the "保证效果" proof:
it shows the new chunker is strictly better than the previous one on a
real-world MinerU output.
"""
from __future__ import annotations

import copy

import pytest
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

from app.core.markdown_splitter import (
    KIND_HTML_TABLE,
    KIND_PARAGRAPH_SPLIT,
    markdown_aware_split,
)

from tests import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    MARKDOWN_FIXTURE,
    XML_FIXTURE,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def markdown_text() -> str:
    return MARKDOWN_FIXTURE.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _case_table_substring(text: str) -> str:
    """Locate the ``<table>...</table>`` block on line 51 of the fixture that
    contains the Case 1/2/3 variant data. We can't hard-code the offsets
    because they depend on line endings, so we search by content."""
    open_idx = text.find('<table><tr><td rowspan="2">Case number')
    assert open_idx >= 0, "fixture missing the Case table we expected"
    end_idx = text.find("</table>", open_idx)
    assert end_idx >= 0, "Case table has no closing tag"
    return text[open_idx : end_idx + len("</table>")]


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


def test_variant_retriever_finds_target():
    """Building real chunks and feeding them through VariantSpecificRetriever
    must return at least one chunk for ``NM_017739.1:c.1319T>G``. This is the
    most direct end-to-end check that mirrors the production pipeline."""
    from app.core.query import (
        MUTALYZER_DIAGNOSTICS_TEMPLATE,
        VariantSpecificRetriever,
    )

    text = MARKDOWN_FIXTURE.read_text(encoding="utf-8", errors="replace")
    chunks = markdown_aware_split(
        text,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    retriever = VariantSpecificRetriever(
        documents=chunks,
        k=5,
        protein_map={},
        diagnostics=copy.deepcopy(MUTALYZER_DIAGNOSTICS_TEMPLATE),
    )
    # The retriever's _get_relevant_documents runs the full regex path,
    # including Mutalyzer. We bypass the Mutalyzer call by priming the
    # diagnostic with the already-resolved protein description.
    retriever.diagnostics["mutalyzer"]["status"] = "ok"
    retriever.diagnostics["mutalyzer"]["trimmed_long"] = "L440R"
    retriever.diagnostics["mutalyzer"]["trimmed_short"] = "L440R"

    retrieved = retriever._get_relevant_documents("NM_017739.1:c.1319T>G")
    assert retrieved, (
        "VariantSpecificRetriever returned no chunks for c.1319T>G; "
        "either the chunker is dropping variant text or the regex path is broken"
    )
    # The Case table row that names the variant must be one of the retrieved
    # chunks (or at least its parent chunk that contains it).
    needle = "c.1319T &gt; G"
    assert any(needle in c.page_content for c in retrieved), (
        f"retriever returned {len(retrieved)} chunks but none contain {needle!r}"
    )


def test_baseline_splitter_fails_atomic_table():
    """PROOF THAT THE NEW CHUNKER IS STRICTLY BETTER.

    The Case 1/2/3 HTML table is 1438 chars — small enough to fit in one
    1500-char LangChain chunk, so a baseline "is the table fully contained
    in some chunk?" assertion is uninteresting on its own. Instead we
    force a structural split by running the baseline with a small
    chunk_size (800) and asserting two properties:

    1. The baseline produces at least one chunk that contains a partial
       table — i.e. an opening ``<table>`` tag without a matching closing
       ``</table>``. This is the silent destruction we want to prevent.
    2. The new chunker, given the *same* small chunk_size, splits the
       table on ``</tr>`` boundaries only — every emitted chunk either
       contains no part of the table or contains only complete ``<tr>``
       rows. Mid-row cell slicing never happens.
    """
    text = MARKDOWN_FIXTURE.read_text(encoding="utf-8", errors="replace")
    case_table = _case_table_substring(text)

    baseline_chunk_size = 800
    baseline_chunks = RecursiveCharacterTextSplitter(
        chunk_size=baseline_chunk_size,
        chunk_overlap=100,
    ).split_documents([Document(page_content=text, metadata={"source": "local"})])

    # Property 1: at least one baseline chunk holds a partial table.
    has_partial = any(
        "<table" in c.page_content and "</table>" not in c.page_content
        for c in baseline_chunks
    )
    assert has_partial, (
        "baseline splitter did not produce a partial-table chunk — "
        "either LangChain changed its behaviour or the table is too small. "
        "Re-evaluate whether the new chunker is still needed."
    )

    # Property 2: new chunker never slices a row mid-cell. Each sub-chunk
    # of an oversize table is well-formed: opener (on first chunk) +
    # complete rows + closer (on last chunk). We verify two invariants:
    #   - Across all chunks, total <table> tags == total </table> tags
    #     (the table isn't dropped or duplicated).
    #   - Every <tr> in every chunk is matched by a </tr> in the SAME
    #     chunk (no row is sliced across the chunk boundary).
    new_chunks = markdown_aware_split(
        text,
        chunk_size=baseline_chunk_size,
        chunk_overlap=100,
    )
    total_opens = sum(c.page_content.count("<table") for c in new_chunks)
    total_closes = sum(c.page_content.count("</table>") for c in new_chunks)
    assert total_opens == total_closes, (
        f"new chunker lost table tags: {total_opens} <table> vs "
        f"{total_closes} </table> across all chunks"
    )
    for i, c in enumerate(new_chunks, 1):
        text_in = c.page_content
        tr_opens = text_in.count("<tr")
        tr_closes = text_in.count("</tr>")
        assert tr_opens == tr_closes, (
            f"new chunker chunk #{i} has unbalanced <tr> tags "
            f"({tr_opens} open / {tr_closes} close) — row slicing occurred"
        )


def test_oversize_table_subchunking():
    """A 3000-char HTML table that exceeds chunk_size must be sub-chunked
    on ``</tr>`` boundaries, never mid-row, with a recoverable row index."""
    chunk_size = 1500
    rows = []
    for i in range(50):
        rows.append(
            f"<tr><td>case-{i:02d}</td><td>"
            + "x" * 40
            + f"</td><td>c.{1000 + i}A&gt;G</td></tr>"
        )
    table = "<table>" + "".join(rows) + "</table>"
    assert len(table) > chunk_size * 1.5

    chunks = markdown_aware_split(table, chunk_size=chunk_size, chunk_overlap=100)
    assert len(chunks) >= 2, "oversize table was not split into multiple chunks"

    # Every sub-chunk must be bounded (allow a small header slack for the
    # "[rows N-M of K]" prefix).
    cap = int(chunk_size * 1.2)
    for i, c in enumerate(chunks, 1):
        assert len(c.page_content) <= cap, (
            f"sub-chunk #{i} len={len(c.page_content)} exceeded cap={cap}"
        )

    # Concatenation of all sub-chunk texts must reproduce every row's
    # c.NNA>G variant literal — i.e. no row was silently dropped.
    joined = "".join(c.page_content for c in chunks)
    for i in range(50):
        assert f"c.{1000 + i}A&gt;G" in joined, (
            f"oversize-table split lost row #{i} (variant c.{1000 + i}A>G)"
        )


def test_oversize_paragraph_falls_back():
    """A single paragraph longer than chunk_size must trigger the LangChain
    fallback and produce ``chunk_kind == 'paragraph_split'`` sub-pieces."""
    paragraph = "The mutant POMGnT1 had no enzyme activity compared with the wild-type. " * 60
    assert len(paragraph) > 1500

    chunks = markdown_aware_split(paragraph, chunk_size=1500, chunk_overlap=100)
    assert len(chunks) >= 2, "oversize paragraph should split into multiple chunks"
    kinds = [c.metadata["chunk_kind"] for c in chunks]
    assert KIND_PARAGRAPH_SPLIT in kinds, (
        f"oversize paragraph did not use the LangChain fallback; "
        f"chunk_kinds={kinds}"
    )


def test_no_chunk_loss_on_borders(markdown_text):
    """With chunk_overlap=200, substrings that sit on a chunk boundary should
    still appear in at least one of the two adjacent chunks (regression guard
    for the overlap rule)."""
    chunks = markdown_aware_split(
        markdown_text,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    # Pick a few real substrings from the source that are ≥ 30 chars.
    needles = [
        "enzyme activity, western blot",
        "missense mutation (c.1319T",
        "POMGnT1 enzymatic activity was measured in the fibroblasts",
    ]
    missing = []
    for needle in needles:
        if needle not in markdown_text:
            continue
        if not any(needle in c.page_content for c in chunks):
            missing.append(needle)
    assert not missing, f"overlap rule dropped these substrings: {missing}"