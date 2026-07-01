# `app/prompts/` — 集中管理的 prompt 模板

[English](./README.md) | [简体中文](./README.zh.md)

所有 LLM prompt 都集中放在本目录的 `.j2` 文件中。调 prompt 时直接编辑这里的文件即可，
**不需要改 Python 代码**，git diff 也更干净。

## 两种语法风格

| 语法 | 加载方式 | 适用场景 |
| --- | --- | --- |
| `{var}` 占位符 | `langchain.prompts.PromptTemplate.from_file()` | 静态 prompt，变量集合固定，配合 `LLMChain` / `RetrievalQA` / `partial()` 使用。 |
| `{{ var }}` / `{% ... %}` | `jinja2.Environment` + `render_*()` 辅助函数 | 每次调用动态生成（循环变量、条件分支、动态内容）。 |

## 文件清单

| 文件 | 变量 | 调用方 |
| --- | --- | --- |
| `pm3_answer.j2` | `question`, `context`, `c_variant`, `proposedQuestion` | `app.core.query` —— 主 biogenetics QA 链（Llama 3 chat 格式）。 |
| `table2text.j2` | `tableData`, `question` | `app.core.table_functions.table2text` —— benchmark 用，表格行 → 纯文本。 |
| `table_ntext_qa.j2` | `tableData`, `pt`, `question` | `app.core.table_functions.tableNtext_qa` —— 表格行 + 纯文本 联合 QA。 |
| `table_extraction.j2` | `idx`, `csv_content`, `query_text`（Jinja2） | `app.core.table_functions.table_extraction_with_deepseek` —— 按表格动态生成的抽取 prompt。 |

## 新增一个 prompt

1. 把 `.j2` 文件丢进本目录。
2. 在 `__init__.py` 里加一行 loader：
   - LangChain 风格 → 加一个 `PromptTemplate.from_file(...)` 常量。
   - Jinja2 风格 → 用 `_JINJA_ENV` 加一个 `render_*` 函数。
3. 调用方用 `from app.prompts import ...` 导入；**不要**再把 prompt 字符串写回 `.py` 文件。

## 注意事项

- Llama 3 特殊 token（`<|begin_of_text|>`、`<|start_header_id|>` 等）在
  `pm3_answer.j2` 里是字面量文本 —— 只有切到 Jinja2 风格时才需要转义。
- Jinja2 环境设置了 `keep_trailing_newline=True`，以保留 prompt 末尾的换行
  （与原先 f-string 的行为一致）。
