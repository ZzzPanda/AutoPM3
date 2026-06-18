"""Centralized prompt templates for AutoPM3.

Edit the ``.j2`` files in this directory to tune prompts without touching
application code. The two flavours of templates used here:

* **LangChain prompts** (``.j2`` files using ``{var}`` placeholders) — loaded
  eagerly into :class:`langchain.prompts.PromptTemplate` and exported as module
  constants. They integrate with ``LLMChain``, ``RetrievalQA``, etc.

* **Jinja2 prompts** (``.j2`` files using ``{{ var }}`` / ``{% ... %}`` syntax) —
  rendered on demand via :func:`render_table_extraction`. Use this flavour when
  the prompt is built from values that aren't a simple ``partial()`` of a
  fixed set of variables (e.g. loop variables, conditional rows).

When adding a new prompt:

1. Drop the ``.j2`` file here.
2. Add a loader line below — either a ``PromptTemplate.from_file(...)`` export
   or a new ``render_*`` function for Jinja2.
3. Import from the caller; do not inline template strings back in ``.py``.
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from langchain.prompts import PromptTemplate

_PROMPTS_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# LangChain prompts (use {var} placeholders)
# ---------------------------------------------------------------------------

# Main QA chain (biogenetics) — used in app.core.query for variant/compound-het
# fan-out. Llama 3 chat format with <|begin_of_text|> special tokens.
PM3_ANSWER = PromptTemplate.from_file(
    _PROMPTS_DIR / "pm3_answer.j2",
    input_variables=["question", "context", "c_variant", "proposedQuestion"],
)

# Benchmarking: turn one structured table row into plain text.
TABLE2TEXT = PromptTemplate.from_file(
    _PROMPTS_DIR / "table2text.j2",
    input_variables=["tableData", "question"],
)

# QA over (structured table row + its plain-text description).
TABLE_NTEXT_QA = PromptTemplate.from_file(
    _PROMPTS_DIR / "table_ntext_qa.j2",
    input_variables=["tableData", "pt", "question"],
)


# ---------------------------------------------------------------------------
# Jinja2 prompts (use {{ var }} syntax)
# ---------------------------------------------------------------------------

_JINJA_ENV = Environment(
    loader=FileSystemLoader(str(_PROMPTS_DIR)),
    keep_trailing_newline=True,
    trim_blocks=False,
    lstrip_blocks=False,
)


def render_table_extraction(*, idx: int, csv_content: str, query_text: str) -> str:
    """Render the per-table extraction prompt used by
    ``app.core.table_functions.table_extraction_with_deepseek``.

    This prompt is built per table inside a fan-out loop, so it stays as a
    Jinja2 template rather than a static ``PromptTemplate``.
    """
    return _JINJA_ENV.get_template("table_extraction.j2").render(
        idx=idx,
        csv_content=csv_content,
        query_text=query_text,
    )


__all__ = [
    "PM3_ANSWER",
    "TABLE2TEXT",
    "TABLE_NTEXT_QA",
    "render_table_extraction",
]
