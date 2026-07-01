# `app/prompts/` — Centralized prompt templates

[English](./README.md) | [简体中文](./README.zh.md)

All LLM prompts live here as `.j2` files. Edit a file in this directory to
tune a prompt — no Python change required, and diffs are clean.

## Two flavours

| Syntax | Loaded by | Use when |
| --- | --- | --- |
| `{var}` placeholders | `langchain.prompts.PromptTemplate.from_file()` | Static prompt with a fixed set of variables, used inside `LLMChain` / `RetrievalQA` / `partial()`. |
| `{{ var }}` / `{% ... %}` | `jinja2.Environment` + `render_*()` helper | Prompt is built per-call (loop variables, conditionals, dynamic content). |

## Files

| File | Variables | Used by |
| --- | --- | --- |
| `pm3_answer.j2` | `question`, `context`, `c_variant`, `proposedQuestion` | `app.core.query` — main biogenetics QA chain (Llama 3 chat format). |
| `table2text.j2` | `tableData`, `question` | `app.core.table_functions.table2text` — benchmarking, table row → plain text. |
| `table_ntext_qa.j2` | `tableData`, `pt`, `question` | `app.core.table_functions.tableNtext_qa` — QA over (table row + plain text). |
| `table_extraction.j2` | `idx`, `csv_content`, `query_text` (Jinja2) | `app.core.table_functions.table_extraction_with_deepseek` — per-table extraction prompt. |

## Adding a new prompt

1. Drop the `.j2` file in this directory.
2. In `__init__.py`:
   - For a LangChain prompt: add a `PromptTemplate.from_file(...)` constant.
   - For a Jinja2 prompt: add a `render_*` helper using `_JINJA_ENV`.
3. Import from the caller (`from app.prompts import ...`); never inline
   template strings in `.py` files.

## Notes

- Llama 3 special tokens (`<|begin_of_text|>`, `<|start_header_id|>`, etc.)
  are literal text inside `pm3_answer.j2` — escape only if you switch to the
  Jinja2 flavour.
- `keep_trailing_newline=True` is set on the Jinja2 env so prompts ending in
  a newline keep that newline (matches the original f-string behaviour).
