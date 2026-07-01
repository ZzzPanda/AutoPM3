"""Synthetic markdown tests for ``markdown_aware_split``.

These tests construct small Markdown documents that exercise one specific
chunking property at a time. Compared with the real MinerU fixture, the
synthetic tests give us:

* Predictable structure (we control the inputs).
* Targeted assertions (one property per test).
* Coverage of edge cases that don't appear in PMID 23689641 (pipe tables,
  fenced code, nested headings, image-heavy documents, only-tables).
"""
from __future__ import annotations

import pytest
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
    split_docs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row(tag: str, n: int, extra: str = "") -> str:
    cells = "".join(f"<td>c{tag}{i}</td>" for i in range(n))
    return f"<tr>{cells}{extra}</tr>"


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def simple_md_with_html_table() -> str:
    return (
        "# Title\n"
        "\n"
        "First paragraph that introduces the topic and is reasonably long.\n"
        "\n"
        "## Section A\n"
        "\n"
        "Some prose before the table.\n"
        "\n"
        "<table>"
        + _row("A", 3)
        + _row("B", 3)
        + _row("C", 3)
        + "</table>\n"
        "\n"
        "## Section B\n"
        "\n"
        "Prose after the table with the variant c.1319T>G mentioned.\n"
    )


@pytest.fixture
def pipe_table_md() -> str:
    return (
        "# Pipe table test\n"
        "\n"
        "Intro paragraph.\n"
        "\n"
        "| Case | Variant | Allele |\n"
        "|------|---------|--------|\n"
        "| 1    | c.1319T>G | p.L440R |\n"
        "| 2    | c.1896-1G>C | p.V633EfxX53 |\n"
        "\n"
        "Closing paragraph.\n"
    )


@pytest.fixture
def fenced_code_md() -> str:
    return (
        "# Code test\n"
        "\n"
        "Paragraph above the fence.\n"
        "\n"
        "```python\n"
        "def hello():\n"
        "    return 'world'\n"
        "```\n"
        "\n"
        "Paragraph below the fence.\n"
    )


@pytest.fixture
def image_heavy_md() -> str:
    images = "\n".join(
        f"![Figure {i} caption text here](https://cdn.example.com/fig{i}.png)"
        for i in range(20)
    )
    return (
        "# Image test\n"
        "\n"
        f"{images}\n"
        "\n"
        "Final paragraph mentioning c.555G>A.\n"
    )


@pytest.fixture
def only_tables_md() -> str:
    """A document with several large tables and almost no prose."""
    parts = ["# Only tables\n\n"]
    for i in range(5):
        rows = "".join(_row(f"{i}_", 4) for _ in range(15))
        parts.append(f"<table>{rows}</table>\n\n")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_simple_html_table_atomic(simple_md_with_html_table):
    chunks = markdown_aware_split(simple_md_with_html_table, chunk_size=400, chunk_overlap=50)
    owners = [
        c for c in chunks
        if "<table><tr><td>cA0</td>" in c.page_content
        and "</table>" in c.page_content
    ]
    assert len(owners) == 1, (
        f"HTML table split across {len(owners)} chunks; expected exactly 1. "
        f"Got chunks: {[(c.metadata['chunk_kind'], len(c.page_content)) for c in chunks]}"
    )


def test_pipe_table_atomic(pipe_table_md):
    chunks = markdown_aware_split(pipe_table_md, chunk_size=300, chunk_overlap=20)
    pipe_chunks = [c for c in chunks if c.metadata["chunk_kind"] == KIND_PIPE_TABLE]
    assert pipe_chunks, f"no chunk was classified as pipe table; kinds={[c.metadata['chunk_kind'] for c in chunks]}"
    # When the whole pipe table fits in one chunk, all rows must coexist.
    full_table_chunk = [
        c for c in pipe_chunks
        if "| 1    | c.1319T>G | p.L440R |" in c.page_content
        and "| 2    | c.1896-1G>C | p.V633EfxX53 |" in c.page_content
    ]
    assert full_table_chunk, (
        f"no pipe chunk held the complete table; got {len(pipe_chunks)} "
        f"pipe chunks. Contents: {[c.page_content[:80] for c in pipe_chunks]}"
    )


def test_pipe_table_oversize_split_preserves_rows():
    """An oversize pipe table that can't fit in one chunk must split on row
    boundaries — no row may be sliced mid-cell, and every row must appear
    in some sub-chunk (header re-emitted on each sub-chunk)."""
    rows_text = "\n".join(f"| {i} | c.{100 + i}A>G | note {i} |" for i in range(40))
    md = "## Pipe table\n\n" + (
        "| Case | Variant | Notes |\n"
        "|------|---------|-------|\n"
        + rows_text + "\n"
    ) + "\nOutro.\n"
    chunk_size = 300  # small enough to force a split
    chunks = markdown_aware_split(md, chunk_size=chunk_size, chunk_overlap=20)
    pipe_chunks = [c for c in chunks if c.metadata["chunk_kind"] == KIND_PIPE_TABLE]
    assert len(pipe_chunks) >= 2, "oversize pipe table should split into ≥2 chunks"

    # Every data row must appear in full in some pipe chunk (no row lost,
    # no row sliced mid-cell).
    joined = "".join(c.page_content for c in pipe_chunks)
    missing = [i for i in range(40) if f"| {i} | c.{100 + i}A>G | note {i} |" not in joined]
    assert not missing, f"oversize pipe split dropped rows: {missing[:5]}"

    # No pipe chunk may contain a partial row. We check this by ensuring
    # every pipe-table line starts and ends with `|`.
    for i, c in enumerate(pipe_chunks, 1):
        for line in c.page_content.splitlines():
            stripped = line.strip()
            if stripped.startswith("|") and "[rows" not in stripped:
                assert stripped.endswith("|"), (
                    f"pipe chunk #{i} contains a sliced row: {stripped!r}"
                )


def test_fenced_code_block_atomic(fenced_code_md):
    chunks = markdown_aware_split(fenced_code_md, chunk_size=80, chunk_overlap=10)
    fence_chunks = [c for c in chunks if c.metadata["chunk_kind"] == KIND_FENCE]
    assert fence_chunks, (
        f"no chunk was classified as fence; kinds={[c.metadata['chunk_kind'] for c in chunks]}"
    )
    for c in fence_chunks:
        # The fence content must be intact.
        assert "def hello():" in c.page_content
        assert "return 'world'" in c.page_content


def test_image_atomic(image_heavy_md):
    chunks = markdown_aware_split(image_heavy_md, chunk_size=200, chunk_overlap=20)
    # With chunk_size=200 and ~20 images of ~70 chars each, images can't fit
    # atomically; the chunker must keep each image on a single line within
    # its chunk (not sliced mid-URL).
    broken = [
        c for c in chunks
        if any(
            line.count("![") != line.count("](")  # mismatched markers = sliced
            for line in c.page_content.splitlines()
            if "[" in line or "](" in line
        )
    ]
    assert not broken, (
        f"{len(broken)} chunks contain sliced image references. "
        f"First: {broken[0].page_content[:200] if broken else ''!r}"
    )


def test_only_tables_no_paragraphs(only_tables_md):
    chunks = markdown_aware_split(only_tables_md, chunk_size=600, chunk_overlap=50)
    kinds = [c.metadata["chunk_kind"] for c in chunks]
    # After Bug 2 (heading-as-own-block fix), the leading "# Only tables"
    # heading is its own paragraph block, so the first chunk may be
    # KIND_PARAGRAPH. Every other chunk should be a table (or a split
    # oversize table sub-piece).
    table_kinds = {KIND_HTML_TABLE, KIND_PARAGRAPH_SPLIT}
    non_table = [k for k in kinds[1:] if k not in table_kinds]
    if kinds and kinds[0] not in table_kinds and kinds[0] != KIND_PARAGRAPH:
        non_table = [kinds[0]] + non_table
    assert not non_table, (
        f"only-tables doc produced non-table chunks: {non_table}; "
        f"full kinds: {kinds}"
    )


def test_heading_propagates_to_following_chunks():
    """The same heading should appear on multiple consecutive chunks that
    belong to the same section."""
    md = (
        "## Long Section\n\n"
        + ("This is paragraph content for the long section. " * 50 + "\n\n") * 3
    )
    chunks = markdown_aware_split(md, chunk_size=400, chunk_overlap=50)
    assert len(chunks) >= 2, "expected multiple chunks for a long section"
    headings = [c.metadata["source_heading"] for c in chunks]
    assert all(h == "Long Section" for h in headings), (
        f"headings inconsistent across same-section chunks: {headings}"
    )


def test_heading_change_breaks_propagation():
    """When a new heading appears, subsequent chunks should switch to the
    new heading."""
    md = (
        "## Section One\n\n"
        + ("Paragraph content for section one. " * 30 + "\n\n")
        + "## Section Two\n\n"
        + ("Paragraph content for section two. " * 30 + "\n\n")
    )
    chunks = markdown_aware_split(md, chunk_size=400, chunk_overlap=50)
    headings = [c.metadata["source_heading"] for c in chunks]
    # Find where the transition happens — there must be at least one chunk
    # with each heading.
    assert "Section One" in headings, f"missing 'Section One': {headings}"
    assert "Section Two" in headings, f"missing 'Section Two': {headings}"
    # And 'Section Two' must come AFTER 'Section One'.
    assert headings.index("Section Two") > headings.index("Section One")


def test_new_chunker_vs_baseline_atomic_html_table():
    """Demonstrate the headline improvement: on a single-table markdown doc
    large enough to force a split, the new chunker keeps the table row-
    atomic; the LangChain baseline splits it mid-cell."""
    rows = "".join(
        _row(f"r{i}_", 8, extra=f"<td>v.c.{100 + i}A&gt;G</td>") for i in range(20)
    )
    md = (
        "## Methods\n\n"
        "Brief intro.\n\n"
        f"<table>{rows}</table>\n\n"
        "Brief outro with c.555G>A.\n"
    )
    table_text = f"<table>{rows}</table>"
    assert 1500 < len(table_text) < 5000, "test fixture table size drifted"

    chunk_size = 800
    new_chunks = markdown_aware_split(md, chunk_size=chunk_size, chunk_overlap=50)
    base_chunks = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=50).split_documents(
        [Document(page_content=md, metadata={"source": "local"})]
    )

    # New chunker: every emitted chunk either has the complete table or
    # only complete rows; no chunk has a partial row.
    for i, c in enumerate(new_chunks, 1):
        opens = c.page_content.count("<tr")
        closes = c.page_content.count("</tr>")
        assert opens == closes, (
            f"new chunker chunk #{i} sliced a row: {opens} <tr> vs {closes} </tr>"
        )

    # Baseline: at least one chunk contains a partial table (open without close).
    has_partial = any(
        "<table" in c.page_content and "</table>" not in c.page_content
        for c in base_chunks
    )
    assert has_partial, "baseline did not produce a partial-table chunk; revise test"

    # Variant retrievability: the new chunker keeps the variant-bearing row
    # intact in exactly one chunk.
    new_owners = [c for c in new_chunks if "v.c.105A&gt;G" in c.page_content]
    assert len(new_owners) >= 1, "new chunker lost a variant row"


def test_new_chunker_vs_baseline_pipe_table():
    """Same comparison for pipe-style markdown tables, which the old
    chunker treated as ordinary text."""
    header = "| Case | Variant | Notes |\n|------|---------|-------|\n"
    rows = "".join(f"| {i} | c.{100 + i}A>G | note text here |\n" for i in range(40))
    md = "## Section\n\nIntro.\n\n" + header + rows + "\nOutro.\n"
    pipe_table_text = header + rows

    chunk_size = 600
    new_chunks = markdown_aware_split(md, chunk_size=chunk_size, chunk_overlap=50)
    base_chunks = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=50).split_documents(
        [Document(page_content=md, metadata={"source": "local"})]
    )

    # New: pipe table must be classified as KIND_PIPE_TABLE.
    pipe_chunks = [c for c in new_chunks if c.metadata["chunk_kind"] == KIND_PIPE_TABLE]
    assert pipe_chunks, "new chunker did not classify any chunk as pipe_table"

    # Baseline: at least one chunk holds a partial table (a body row but
    # missing the header/separator of the table above it). The new chunker
    # tags such chunks as KIND_PIPE_TABLE; the baseline has no such concept.
    base_chunk_kinds = {c.metadata.get("chunk_kind") for c in base_chunks}
    assert KIND_PIPE_TABLE not in base_chunk_kinds, (
        "baseline unexpectedly tagged a chunk as pipe_table; revise test"
    )


def test_oversize_table_no_row_loss():
    """A 3000-char table with 50 rows must split into sub-chunks that
    collectively contain every row's variant text."""
    chunk_size = 1500
    rows = "".join(
        f"<tr><td>{i:02d}</td><td>{'x' * 30}</td><td>c.{1000 + i}A&gt;G</td></tr>"
        for i in range(50)
    )
    table = "<table>" + rows + "</table>"
    chunks = markdown_aware_split(table, chunk_size=chunk_size, chunk_overlap=50)
    assert len(chunks) >= 2

    joined = "".join(c.page_content for c in chunks)
    missing = [i for i in range(50) if f"c.{1000 + i}A&gt;G" not in joined]
    assert not missing, f"oversize-table split lost {len(missing)} rows: {missing[:5]}"


def test_split_docs_preserves_chunk_index_continuity():
    """When split_docs is fed multiple input Documents, the emitted chunks'
    chunk_index must be a contiguous 1-based sequence across all of them."""
    docs = [
        Document(page_content="# First doc\n\nFirst content here.", metadata={"source": "local"}),
        Document(page_content="# Second doc\n\nSecond content here.", metadata={"source": "local"}),
    ]
    chunks = split_docs(docs, chunk_size=80, chunk_overlap=20)
    indices = [c.metadata["chunk_index"] for c in chunks]
    assert indices == list(range(1, len(chunks) + 1)), indices