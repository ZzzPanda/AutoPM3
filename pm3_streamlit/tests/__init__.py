"""Shared test configuration and constants for the AutoPM3 chunker test suite.

Importing from this module is supported because pytest auto-prepends the
project root (configured in ``pyproject.toml``'s ``pythonpath``) to
``sys.path``. We re-export ``ROOT`` and fixture paths from ``conftest`` so
test modules can reference them via plain ``from tests import ...``.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Default chunker parameters used across the suite. These mirror the values
# that ``query_variant_in_paper_xml`` passes for markdown inputs.
CHUNK_SIZE = 1800
CHUNK_OVERLAP = 200

# Variant substrings expected to be retrievable from the markdown fixture.
# These mirror the OCR / HTML-encoding artefacts produced by MinerU on
# PMID 23689641 — keep them exactly as they appear in the source markdown.
TARGET_VARIANT_SUBSTRINGS = (
    "c.1319T &gt; G",          # HTML-encoded ">" inside <td> on line 51
    "p.L440R",
    "p.V633EfxX53",
    "c.1896-1 G [ C",          # MinerU OCR'd form (line 71)
)

MARKDOWN_FIXTURE = ROOT / "tests" / "fixtures" / "PubMed23689641_markdown.md"
XML_FIXTURE = ROOT / "tests" / "fixtures" / "23689641.xml"

__all__ = [
    "ROOT",
    "CHUNK_SIZE",
    "CHUNK_OVERLAP",
    "TARGET_VARIANT_SUBSTRINGS",
    "MARKDOWN_FIXTURE",
    "XML_FIXTURE",
]