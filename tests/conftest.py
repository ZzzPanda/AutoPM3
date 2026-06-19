"""Pytest configuration: expose project root and fixture paths."""
from __future__ import annotations

import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURE_DIR = ROOT / "tests" / "fixtures"
MARKDOWN_FIXTURE = FIXTURE_DIR / "PubMed23689641_markdown.md"
XML_FIXTURE = FIXTURE_DIR / "23689641.xml"

# Shared constants for the markdown-aware chunker suite.
CHUNK_SIZE = 1800
CHUNK_OVERLAP = 200

# Variant substrings expected to be retrievable from the markdown fixture.
# These mirror the OCR / HTML-encoding artefacts produced by MinerU on
# PMID 23689641 — we must keep the literal text exactly as it appears in
# the source markdown.
TARGET_VARIANT_SUBSTRINGS = (
    "c.1319T &gt; G",          # HTML-encoded ">" inside <td> on line 51
    "p.L440R",
    "p.V633EfxX53",
    "c.1896-1 G [ C",          # MinerU OCR'd form (line 71)
)