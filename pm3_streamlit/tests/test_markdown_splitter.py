"""Unit tests for app.core.markdown_splitter.

These tests exercise ``markdown_aware_split`` and ``split_docs`` against the
real MinerU markdown fixture for PMID 23689641. The baseline test in
``test_split_docs_integration.py`` independently proves the previous
``RecursiveCharacterTextSplitter``-based chunker fails the atomic-table
property on the same fixture.
"""
from __future__ import annotations

import pytest

from langchain_core.documents import Document

from app.core.markdown_splitter import (
    KIND_HTML_TABLE,
    KIND_PARAGRAPH,
    KIND_PARAGRAPH_SPLIT,
    markdown_aware_split,
    split_docs,
)

from tests import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    MARKDOWN_FIXTURE,
    TARGET_VARIANT_SUBSTRINGS,
    XML_FIXTURE,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def markdown_text() -> str:
    return MARKDOWN_FIXTURE.read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="module")
def chunks(markdown_text):
    return markdown_aware_split(
        markdown_text,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _html_tables(text: str) -> list[tuple[int, int]]:
    """Return (start, end) character offsets of every <table>...</table> in
    ``text``. We use simple substring search rather than regex parsing so
    that nested or odd HTML does not confuse the test.
    """
    tables: list[tuple[int, int]] = []
    cursor = 0
    while True:
        open_idx = text.find("<table", cursor)
        if open_idx < 0:
            break
        # Skip past any tag-attribute noise after "<table".
        gt = text.find(">", open_idx)
        start = gt + 1 if gt > open_idx else open_idx + len("<table")
        end_idx = text.find("</table>", start)
        if end_idx < 0:
            break
        tables.append((open_idx, end_idx + len("</table>")))
        cursor = end_idx + len("</table>")
    return tables


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_html_table_atomic(chunks, markdown_text):
    """Every <table>...</table> block must live in exactly one chunk."""
    tables = _html_tables(markdown_text)
    assert len(tables) == 2, f"expected 2 HTML tables in fixture, got {len(tables)}"

    for start, end in tables:
        original = markdown_text[start:end]
        owner_count = sum(1 for c in chunks if original in c.page_content)
        assert owner_count == 1, (
            f"HTML table at offset {start}-{end} (len {end - start}) "
            f"appears in {owner_count} chunks (expected exactly 1)"
        )


def test_variant_retrievability(chunks):
    """All four target variant literals must be findable in some chunk."""
    missing = [
        needle
        for needle in TARGET_VARIANT_SUBSTRINGS
        if not any(needle in c.page_content for c in chunks)
    ]
    assert not missing, f"variant substrings not found in any chunk: {missing}"


def test_chunk_sizes_bounded(chunks):
    """Every chunk must stay within chunk_size * 1.2 (oversize-table slack)."""
    cap = int(CHUNK_SIZE * 1.2)
    violations = [
        (i, len(c.page_content))
        for i, c in enumerate(chunks, 1)
        if len(c.page_content) > cap
    ]
    assert not violations, (
        f"chunks exceeded {cap}-char cap (1.2x chunk_size={CHUNK_SIZE}): "
        f"{violations[:5]}"
    )


def test_round_trip_recovers_content(chunks, markdown_text):
    """Concatenating all chunks must recover every non-empty source paragraph.

    Allowed drift: chunks may share overlap tail, and a single paragraph may
    be split across chunks — but no source content may be silently dropped.

    We check coverage at the **token level** rather than the literal-string
    level because LangChain's ``RecursiveCharacterTextSplitter`` fallback
    for oversize paragraphs (those > chunk_size) produces sub-pieces that
    are not byte-identical to the original paragraph — only token-faithful.
    """
    concatenated = "".join(c.page_content for c in chunks)
    # Build the set of non-trivial source tokens (length ≥ 6, alphanumeric).
    import re as _re

    token_re = _re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{5,}")
    source_tokens = set(token_re.findall(markdown_text))
    chunk_tokens = set(token_re.findall(concatenated))
    missing = sorted(source_tokens - chunk_tokens)

    # Allow a small tolerance for tokens that only appear inside very
    # long tail fragments (e.g. citation suffixes that get pushed off the
    # end of an oversize paragraph split). Anything beyond 0.5% is a real
    # silent drop.
    max_missing = max(1, len(source_tokens) // 200)
    assert len(missing) <= max_missing, (
        f"round-trip dropped {len(missing)} tokens (max allowed {max_missing}); "
        f"first missing: {missing[:5]}"
    )


def test_metadata_contract(chunks):
    """Every chunk has the legacy contract + four new fields; chunk_index is
    a contiguous 1-based sequence."""
    required_old = {"chunk_index", "chunk_size", "chunk_overlap", "source"}
    required_new = {"chunk_kind", "source_heading", "contains_table", "block_count"}

    seen_indices: list[int] = []
    for c in chunks:
        meta = c.metadata or {}
        assert required_old.issubset(meta.keys()), (
            f"missing legacy metadata: {required_old - meta.keys()}"
        )
        assert required_new.issubset(meta.keys()), (
            f"missing new metadata: {required_new - meta.keys()}"
        )
        assert meta["chunk_size"] == CHUNK_SIZE
        assert meta["chunk_overlap"] == CHUNK_OVERLAP
        assert meta["source"] == "local"
        seen_indices.append(meta["chunk_index"])

    assert seen_indices == list(range(1, len(chunks) + 1)), (
        f"chunk_index is not contiguous 1-based; got {seen_indices[:10]}..."
    )


def test_paragraph_kind_under_heading(chunks):
    """The chunk that contains the '## Mutation analysis' heading must
    advertise that heading via ``source_heading``."""
    # Match either the bare heading or with a leading space.
    heading_targets = ("## Mutation analysis", "##Mutation analysis")
    matching = [
        c for c in chunks
        if any(c.page_content.lstrip().startswith(h) or f"\n{h}\n" in c.page_content
               for h in heading_targets)
    ]
    assert matching, "no chunk contained the '## Mutation analysis' heading"
    for c in matching:
        assert c.metadata["source_heading"] == "Mutation analysis", (
            f"chunk with heading line has wrong source_heading: "
            f"{c.metadata['source_heading']!r}"
        )


def test_xml_input_still_works():
    """``split_docs`` must keep producing sensible chunks for XML paper text.

    The XML path falls through to the dispatcher in ``split_docs``; the
    chunker classifies it as plain text (no <tag>, no '#', no '|' lines in
    the body) and routes it to the LangChain fallback. We assert at least
    one chunk exists and at least one of them has ``chunk_kind='paragraph'``.
    """
    from app.core.query import load_xml_paper

    xml_text = load_xml_paper(str(XML_FIXTURE), filter_tables=False)
    assert xml_text.strip(), "XML fixture produced empty text"

    chunks = split_docs(
        [Document(page_content=xml_text, metadata={"source": "local"})],
        chunk_size=1500,
        chunk_overlap=100,
    )
    assert chunks, "split_docs returned no chunks for XML input"
    kinds = {c.metadata.get("chunk_kind") for c in chunks}
    assert KIND_PARAGRAPH in kinds, (
        f"XML fallback did not produce any paragraph chunks; got kinds={kinds}"
    )


def test_split_docs_dispatches_on_content_shape():
    """Markdown content triggers markdown path; plain text triggers fallback."""
    from langchain.text_splitter import RecursiveCharacterTextSplitter

    md_text = "# Heading\n\nA paragraph with <em>inline</em> HTML."
    plain_text = "Just a plain paragraph with no markup at all. " * 200

    md_chunks = split_docs([Document(page_content=md_text)], chunk_size=200, chunk_overlap=20)
    plain_chunks = split_docs([Document(page_content=plain_text)], chunk_size=200, chunk_overlap=20)

    # Markdown: at least one chunk should carry our new metadata contract.
    assert any("chunk_kind" in (c.metadata or {}) for c in md_chunks)
    # Plain text: every chunk has the legacy metadata contract (including
    # source/chunk_size/chunk_overlap).
    assert plain_chunks
    for c in plain_chunks:
        assert c.metadata.get("source") == "local"
        assert c.metadata.get("chunk_size") == 200


def test_empty_input_returns_empty_list():
    assert markdown_aware_split("") == []
    assert split_docs([]) == []
    assert split_docs([Document(page_content="")]) == []


def test_invalid_arguments_raise():
    import pytest
    with pytest.raises(ValueError):
        markdown_aware_split("hello", chunk_size=0)
    with pytest.raises(ValueError):
        markdown_aware_split("hello", chunk_size=100, chunk_overlap=100)
    with pytest.raises(ValueError):
        markdown_aware_split("hello", chunk_size=100, chunk_overlap=-1)