"""Markdown-aware text splitter for AutoPM3.

This module replaces the previous ``split_docs`` wrapper that called
LangChain's ``RecursiveCharacterTextSplitter`` with no structure awareness.
The default LangChain splitter would happily slice an HTML ``<table>`` block
mid-row, which silently destroys the variant evidence that lives inside
MinerU-style tables.

The chunker here understands four atomic block kinds and keeps them intact:

* HTML tables (``<table>...</table>``)
* Pipe-style markdown tables
* Fenced code blocks (``` or ~~~)
* Markdown image references (``![alt](url)`` on a single line)

Headings (``#``, ``##``, ...) are recorded as ``source_heading`` metadata on
the next paragraph block instead of being stripped, so the round-trip
property (no content silently lost) holds.

For blocks that exceed ``chunk_size`` we degrade gracefully:
oversized tables are split on ``</tr>`` boundaries and prefixed with a
``[rows N-M of K]`` marker; oversized paragraphs fall back to
``RecursiveCharacterTextSplitter`` and are tagged ``chunk_kind="paragraph_split"``.

The public surface is intentionally small:

* :func:`markdown_aware_split` — block-aware splitter, single text input.
* :func:`split_docs` — drop-in replacement for the previous ``split_docs``,
  dispatches to :func:`markdown_aware_split` for content that looks like
  markdown and to ``RecursiveCharacterTextSplitter`` otherwise (plain text,
  XML-converted paragraphs).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document


# Block kinds — used both for the in-memory block model and for the
# ``chunk_kind`` metadata emitted on each Document.
KIND_HTML_TABLE = "html_table"
KIND_PIPE_TABLE = "pipe_table"
KIND_FENCE = "fence"
KIND_PARAGRAPH = "paragraph"
KIND_PARAGRAPH_SPLIT = "paragraph_split"
KIND_IMAGE = "image"


@dataclass
class Block:
    """One atomic block parsed out of the input text."""

    kind: str
    text: str
    source_heading: Optional[str] = None
    start: int = 0
    end: int = 0


@dataclass
class _HeadingHit:
    text: str
    line: int


_HTML_TABLE_OPEN_RE = re.compile(r"^\s*<table[\s>]", re.IGNORECASE)
_HTML_TABLE_CLOSE_TAG_RE = re.compile(r"</table\s*>", re.IGNORECASE)
_HTML_ROW_CLOSE_RE = re.compile(r"</tr\s*>", re.IGNORECASE)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_IMAGE_RE = re.compile(r"^!\[.*\]\(.*\)\s*$")
_FENCE_OPEN_RE = re.compile(r"^\s*(```|~~~)")


def _looks_like_markdown(text: str) -> bool:
    """Heuristic dispatch: True iff the content has any of HTML, headings, or
    pipe tables. False means the content is plain text — we fall back to the
    LangChain character splitter to keep behaviour identical for XML dumps.
    """
    if not text:
        return False
    for line in text.splitlines()[:4000]:  # bounded scan is enough for the dispatch
        stripped = line.lstrip()
        if not stripped:
            continue
        if stripped.startswith("<") or _HEADING_RE.match(stripped) or stripped.startswith("|"):
            return True
    return False


def _parse_blocks(text: str) -> List[Block]:
    """Walk the text line by line and emit atomic blocks.

    The state machine has four modes:
    TEXT (default), TABLE_HTML, TABLE_PIPE, FENCE. Inside TEXT mode the
    collector switches between paragraph accumulation, heading capture, and
    image-only lines.
    """
    lines = text.splitlines(keepends=True)
    blocks: List[Block] = []
    current_heading: Optional[str] = None

    i = 0
    n = len(lines)

    # HTML table — atomic, multi-line. The opening tag is on the first line;
    # the closing tag may appear on any subsequent line OR on the same line
    # (for single-line tables common in MinerU output).
    def _collect_html_table(start: int) -> Block:
        body = [lines[start]]
        j = start + 1
        # If the open line itself already contains </table>, close on this line.
        if _HTML_TABLE_CLOSE_TAG_RE.search(lines[start]):
            return Block(
                kind=KIND_HTML_TABLE,
                text=lines[start],
                source_heading=current_heading,
                start=start,
                end=start + 1,
            )
        while j < n:
            body.append(lines[j])
            if _HTML_TABLE_CLOSE_TAG_RE.search(lines[j]):
                j += 1
                break
            j += 1
        text_block = "".join(body)
        return Block(
            kind=KIND_HTML_TABLE,
            text=text_block,
            source_heading=current_heading,
            start=start,
            end=j,
        )

    # Pipe-style table — atomic run of `|` lines.
    def _collect_pipe_table(start: int) -> Block:
        body = [lines[start]]
        j = start + 1
        while j < n:
            stripped = lines[j].strip()
            if stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2:
                body.append(lines[j])
                j += 1
                continue
            break
        return Block(
            kind=KIND_PIPE_TABLE,
            text="".join(body),
            source_heading=current_heading,
            start=start,
            end=j,
        )

    # Fenced code block — ``` or ~~~.
    def _collect_fence(start: int, fence: str) -> Block:
        body = [lines[start]]
        j = start + 1
        while j < n:
            body.append(lines[j])
            stripped = lines[j].lstrip()
            if stripped.startswith(fence) and re.match(rf"^\s*{re.escape(fence)}\s*$", lines[j]):
                j += 1
                break
            j += 1
        return Block(
            kind=KIND_FENCE,
            text="".join(body),
            source_heading=current_heading,
            start=start,
            end=j,
        )

    # Paragraph run — blank line terminates. A leading heading is captured
    # but still included in the block text so round-trip recovery succeeds.
    def _collect_paragraph(start: int) -> Block:
        nonlocal current_heading
        body: List[str] = []
        leading_heading_line: Optional[str] = None
        j = start
        while j < n:
            line = lines[j]
            if line.strip() == "":
                j += 1
                break
            m = _HEADING_RE.match(line)
            if m and not body and leading_heading_line is None:
                # Heading at the very start of a paragraph slot — record
                # it (so the line is not silently dropped) and update
                # current_heading; then continue collecting the paragraph
                # body that follows.
                leading_heading_line = line
                current_heading = m.group(2).strip()
                j += 1
                while j < n and lines[j].strip() == "":
                    j += 1
                continue
            body.append(line)
            j += 1
        if leading_heading_line is not None:
            body.insert(0, leading_heading_line)
        return Block(
            kind=KIND_PARAGRAPH,
            text="".join(body),
            source_heading=current_heading,
            start=start,
            end=j,
        )

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if stripped == "":
            i += 1
            continue

        if _HTML_TABLE_OPEN_RE.match(line):
            blk = _collect_html_table(i)
            blocks.append(blk)
            i = blk.end
            continue

        if _FENCE_OPEN_RE.match(line):
            fence = line.lstrip()[:3]
            blk = _collect_fence(i, fence)
            blocks.append(blk)
            i = blk.end
            continue

        if stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2:
            blk = _collect_pipe_table(i)
            blocks.append(blk)
            i = blk.end
            continue

        if _IMAGE_RE.match(line):
            blocks.append(
                Block(
                    kind=KIND_IMAGE,
                    text=line,
                    source_heading=current_heading,
                    start=i,
                    end=i + 1,
                )
            )
            i += 1
            continue

        # Heading-only line: register but defer to the next paragraph (or
        # emit as its own paragraph chunk if it's the tail).
        m = _HEADING_RE.match(line)
        if m:
            heading_text = m.group(2).strip()
            # Look ahead — if the next non-blank line is a regular paragraph,
            # let the paragraph collector pick this heading up (which updates
            # current_heading). Otherwise emit a 1-line paragraph chunk so
            # the heading is not silently lost.
            k = i + 1
            while k < n and lines[k].strip() == "":
                k += 1
            if k >= n:
                blocks.append(
                    Block(
                        kind=KIND_PARAGRAPH,
                        text=line,
                        source_heading=current_heading,
                        start=i,
                        end=i + 1,
                    )
                )
                current_heading = heading_text
                i += 1
                continue
            next_stripped = lines[k].strip()
            next_is_structural = (
                _HTML_TABLE_OPEN_RE.match(lines[k])
                or _FENCE_OPEN_RE.match(lines[k])
                or (next_stripped.startswith("|") and next_stripped.endswith("|") and next_stripped.count("|") >= 2)
                or _IMAGE_RE.match(lines[k])
            )
            if next_is_structural:
                # Heading is followed by a structural block — emit the
                # heading as a tiny paragraph so it isn't lost, and let the
                # structural block reattach to current_heading.
                blocks.append(
                    Block(
                        kind=KIND_PARAGRAPH,
                        text=line,
                        source_heading=current_heading,
                        start=i,
                        end=i + 1,
                    )
                )
                current_heading = heading_text
                i += 1
                continue
            current_heading = heading_text
            blk = _collect_paragraph(i)
            blocks.append(blk)
            i = blk.end
            continue

        # Plain paragraph.
        blk = _collect_paragraph(i)
        blocks.append(blk)
        i = blk.end

    return blocks


def _split_oversize_html_table(text: str, chunk_size: int) -> List[str]:
    """Split an HTML table that doesn't fit into a single chunk.

    Splitting on ``</tr>`` keeps each row's cells together. The opening
    ``<table>`` tag is prepended to the first sub-chunk and the closing
    ``</table>`` is appended to the last sub-chunk so each sub-chunk is
    independently well-formed HTML. Each piece is also prefixed with a
    ``[rows N-M of K]`` marker so the original row range can be recovered.
    """
    # Extract rows. Each row is the slice from one <tr> to the next <tr>
    # (exclusive). The text BEFORE the first <tr> is the table opener; the
    # text AFTER the last </tr> is the table closer.
    tr_starts = [m.start() for m in re.finditer(r"<tr[\s>]", text, re.IGNORECASE)]
    if not tr_starts:
        return _hard_split(text, chunk_size)

    opener = text[:tr_starts[0]]                  # "<table ...>"
    # Find the </table> position (if any) to use as the closer.
    closer_match = re.search(r"</table\s*>", text, re.IGNORECASE)
    closer = text[closer_match.start():] if closer_match else "</table>"

    # Build per-row pieces. Each piece is "<tr>...</tr>".
    pieces: List[str] = []
    for idx in range(len(tr_starts)):
        start = tr_starts[idx]
        end = tr_starts[idx + 1] if idx + 1 < len(tr_starts) else (closer_match.start() if closer_match else len(text))
        pieces.append(text[start:end])
    total = len(pieces)

    # Greedy pack rows into independently well-formed table chunks. Account
    # for the wrapper/header length while packing so the caller never falls
    # through to _hard_split and slices a row mid-cell.
    out: List[str] = []
    cur: List[str] = []
    cur_len = 0
    start_idx = 0

    def emit(end_idx: int) -> None:
        header = f"[rows {start_idx + 1}-{end_idx} of {total}]\n"
        out.append(opener + header + "".join(cur) + closer)

    for idx, row in enumerate(pieces):
        next_header = f"[rows {start_idx + 1}-{idx + 1} of {total}]\n"
        next_len = len(opener) + len(next_header) + cur_len + len(row) + len(closer)
        if cur and next_len > chunk_size:
            emit(idx)
            cur = [row]
            cur_len = len(row)
            start_idx = idx
        else:
            cur.append(row)
            cur_len += len(row)
    if cur:
        emit(total)
    return out


def _hard_split(text: str, chunk_size: int) -> List[str]:
    """Last-resort split that just slices on the size limit."""
    if len(text) <= chunk_size:
        return [text]
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


def _pack_blocks(
    blocks: List[Block],
    chunk_size: int,
    chunk_overlap: int,
) -> List[Tuple[str, List[Block]]]:
    """Greedy-pack parsed blocks into chunks.

    Returns a list of ``(text, blocks_list)`` tuples — one per emitted
    chunk. Carrying the block list alongside the text lets the caller
    derive chunk metadata (``chunk_kind``, ``source_heading``,
    ``contains_table``, ``block_count``) without re-parsing.
    """
    packed: List[Tuple[str, List[Block]]] = []
    buffer: List[Block] = []
    buffer_len = 0
    prev_paragraph_tail: str = ""  # overlap seed for the next paragraph chunk

    def flush() -> None:
        nonlocal buffer, buffer_len, prev_paragraph_tail
        if not buffer:
            return
        text = "".join(b.text for b in buffer)
        # Compute overlap seed BEFORE constructing the doc, using only the
        # trailing paragraph block of the just-flushed buffer.
        trailing_paragraph = ""
        for b in reversed(buffer):
            if b.kind in (KIND_PARAGRAPH, KIND_PARAGRAPH_SPLIT, KIND_IMAGE):
                trailing_paragraph = b.text
                break
        if trailing_paragraph and chunk_overlap > 0:
            prev_paragraph_tail = trailing_paragraph[-chunk_overlap:]
        else:
            prev_paragraph_tail = ""
        packed.append((text, list(buffer)))
        buffer = []
        buffer_len = 0

    def oversize_split_block(block: Block) -> List[Block]:
        if block.kind == KIND_HTML_TABLE:
            sub_texts = _split_oversize_html_table(block.text, chunk_size)
            return [
                Block(
                    kind=KIND_HTML_TABLE,
                    text=t,
                    source_heading=block.source_heading,
                )
                for t in sub_texts
            ]
        if block.kind == KIND_PIPE_TABLE:
            sub_texts = _split_oversize_html_table(block.text, chunk_size)
            return [
                Block(
                    kind=KIND_PIPE_TABLE,
                    text=t,
                    source_heading=block.source_heading,
                )
                for t in sub_texts
            ]
        # paragraph / fence / image — defer to LangChain.
        sub_texts = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        ).split_text(block.text)
        kind = KIND_PARAGRAPH_SPLIT if block.kind == KIND_PARAGRAPH else block.kind
        return [
            Block(kind=kind, text=t, source_heading=block.source_heading) for t in sub_texts
        ]

    for block in blocks:
        if len(block.text) > chunk_size:
            # Oversized block — flush whatever we have, then decompose.
            flush()
            for sub in oversize_split_block(block):
                if len(sub.text) > chunk_size:
                    # Belt-and-braces — if a sub-block is still too big, hard split.
                    for piece in _hard_split(sub.text, chunk_size):
                        buffer.append(
                            Block(
                                kind=sub.kind,
                                text=piece,
                                source_heading=sub.source_heading,
                            )
                        )
                        flush()
                else:
                    # Check overflow BEFORE appending — otherwise a flush
                    # after the append would drag the just-added sub into
                    # the same chunk as the previous buffer (overshoot).
                    if buffer and buffer_len + len(sub.text) > chunk_size:
                        flush()
                    buffer.append(sub)
                    buffer_len += len(sub.text)
            continue

        # Atomic block — never slice it. If it doesn't fit in the current
        # buffer, flush and start a new chunk with this block.
        if block.kind in (KIND_HTML_TABLE, KIND_PIPE_TABLE, KIND_FENCE):
            if buffer and buffer_len + len(block.text) > chunk_size:
                flush()
            buffer.append(block)
            buffer_len += len(block.text)
            continue

        # Paragraph / image block.
        if buffer and buffer_len + len(block.text) > chunk_size:
            flush()
        # Seed the new chunk with overlap tail if any.
        if prev_paragraph_tail and not buffer and block.kind in (
            KIND_PARAGRAPH,
            KIND_PARAGRAPH_SPLIT,
            KIND_IMAGE,
        ):
            buffer.append(
                Block(
                    kind=KIND_PARAGRAPH,
                    text=prev_paragraph_tail,
                    source_heading=block.source_heading,
                )
            )
            buffer_len = len(prev_paragraph_tail)
        buffer.append(block)
        buffer_len += len(block.text)

    flush()
    return packed


def markdown_aware_split(
    text: str,
    chunk_size: int = 1500,
    chunk_overlap: int = 100,
    source: str = "local",
) -> List[Document]:
    """Split a markdown document into chunks that respect tables, fences, and headings.

    Parameters
    ----------
    text : str
        The full markdown source.
    chunk_size : int
        Maximum chunk length in characters. Atomic blocks (tables, fences,
        images) are kept whole up to this limit; anything larger is
        sub-divided (tables by ``</tr>``, paragraphs via
        ``RecursiveCharacterTextSplitter``).
    chunk_overlap : int
        Trailing paragraph text carried into the next chunk to soften
        boundary effects. Never slices inside atomic blocks.
    source : str
        Value for the ``source`` metadata field on every output Document.

    Returns
    -------
    list[Document]
        Each Document carries the legacy metadata contract
        (``chunk_index``, ``chunk_size``, ``chunk_overlap``, ``source``)
        plus the new fields ``chunk_kind``, ``source_heading``,
        ``contains_table``, ``block_count``.
    """
    if not text:
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be in [0, chunk_size)")

    blocks = _parse_blocks(text)
    packed = _pack_blocks(blocks, chunk_size, chunk_overlap)

    docs: List[Document] = []
    for idx, (chunk_text, packed_blocks) in enumerate(packed, start=1):
        # chunk_kind is the dominant kind of the packed blocks. For atomic
        # blocks (tables, fences, images) the chunk is that kind. For
        # paragraph chunks that include a LangChain-split oversize block,
        # the split's kind ("paragraph_split") wins. Mixed paragraphs collapse
        # to KIND_PARAGRAPH.
        if not packed_blocks:
            chunk_kind = KIND_PARAGRAPH
        elif len(packed_blocks) == 1:
            chunk_kind = packed_blocks[0].kind
        else:
            # Multiple blocks — prefer an atomic kind if present, else the
            # last block's kind (preserves paragraph_split when an oversize
            # paragraph was packed together with overlap seed).
            atomic_kinds = {
                b.kind for b in packed_blocks
                if b.kind in (KIND_HTML_TABLE, KIND_PIPE_TABLE, KIND_FENCE, KIND_IMAGE)
            }
            if len(atomic_kinds) == 1:
                chunk_kind = next(iter(atomic_kinds))
            elif atomic_kinds:
                chunk_kind = sorted(atomic_kinds)[0]
            else:
                chunk_kind = packed_blocks[-1].kind

        contains_table = any(
            b.kind in (KIND_HTML_TABLE, KIND_PIPE_TABLE) for b in packed_blocks
        )
        # source_heading: prefer the source_heading of the first non-seed
        # block in the buffer. The first block is often the overlap-seed
        # paragraph (a synthetic KIND_PARAGRAPH carrying prev_tail), so we
        # skip those when looking for a meaningful heading.
        source_heading = None
        for b in packed_blocks:
            if b.source_heading is not None:
                source_heading = b.source_heading
                break
        if source_heading is None and packed_blocks:
            source_heading = packed_blocks[0].source_heading

        # block_count: number of real (non-overlap-seed) blocks in the chunk.
        # The overlap seed is always a single synthetic paragraph block
        # whose source_heading was already set by the previous chunk, so we
        # exclude blocks whose source_heading matches the chunk's heading
        # AND whose text is short (the seed is exactly chunk_overlap chars).
        # In practice the seed is rare and a simple length filter works.
        chunk_overlap_text = packed_blocks[0].text if packed_blocks else ""
        # The overlap seed is a block with empty source_heading and length
        # <= chunk_overlap. Filter those out so block_count reflects the
        # number of *content* blocks packed.
        real_blocks = [
            b for b in packed_blocks
            if not (
                b.source_heading is None
                and len(b.text) <= chunk_overlap
                and b is not packed_blocks[-1]
            )
        ]
        if not real_blocks:
            real_blocks = packed_blocks

        metadata = {
            "source": source,
            "chunk_index": idx,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "chunk_kind": chunk_kind,
            "source_heading": source_heading,
            "contains_table": contains_table,
            "block_count": len(real_blocks),
        }
        docs.append(Document(page_content=chunk_text, metadata=metadata))
    return docs


def split_docs(
    documents: List[Document],
    chunk_size: int = 1500,
    chunk_overlap: int = 100,
) -> List[Document]:
    """Drop-in replacement for the previous ``app.core.query.split_docs``.

    Dispatches each input document by content shape:

    * If the document looks like markdown (any HTML tag, ``#`` heading, or
      pipe-table line), it goes through :func:`markdown_aware_split`.
    * Otherwise (plain text from XML papers, etc.) it goes through
      ``RecursiveCharacterTextSplitter`` to preserve the historical
      behaviour for that path.

    The output is a flat list of ``Document`` with the metadata contract
    documented on :func:`markdown_aware_split`.
    """
    if not documents:
        return []

    recursive = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    out: List[Document] = []
    for doc in documents:
        text = doc.page_content or ""
        source = (doc.metadata or {}).get("source", "local")
        if _looks_like_markdown(text):
            sub_docs = markdown_aware_split(
                text,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                source=source,
            )
            # Re-index across all input docs so chunk_index is contiguous.
            offset = len(out)
            for i, sub in enumerate(sub_docs, start=1):
                meta = dict(sub.metadata or {})
                meta["chunk_index"] = offset + i
                out.append(Document(page_content=sub.page_content, metadata=meta))
        else:
            sub_docs = recursive.split_documents([doc])
            offset = len(out)
            for i, sub in enumerate(sub_docs, start=1):
                meta = dict(sub.metadata or {})
                meta.setdefault("source", source)
                meta.setdefault("chunk_size", chunk_size)
                meta.setdefault("chunk_overlap", chunk_overlap)
                meta.setdefault("chunk_kind", KIND_PARAGRAPH)
                meta.setdefault("source_heading", None)
                meta.setdefault("contains_table", False)
                meta.setdefault("block_count", 1)
                meta["chunk_index"] = offset + i
                out.append(Document(page_content=sub.page_content, metadata=meta))
    return out


__all__ = ["markdown_aware_split", "split_docs"]
