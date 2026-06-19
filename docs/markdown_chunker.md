# Markdown Chunker

替换 [app/core/query.py](../app/core/query.py) 里旧的 `RecursiveCharacterTextSplitter`-only 切分逻辑。**保留 HTML 表格 / Pipe 表 / 围栏代码 / 图片引用为原子块**，确保 `VariantSpecificRetriever` 能一次拿到完整的变异证据。

## 问题

MinerU 把论文转成 markdown 时，**HTML 表格完整保留**（不是 pipe 表）：

```html
<table>
  <tr><td>1</td><td>c.1319T &gt; G, p.L440R; c.1896-1G &gt; C, p.V633EfxX53</td></tr>
  <tr><td>2</td><td>c.1814 G &gt; C, p.R605P; c.1513 G &gt; A, p.G505S</td></tr>
</table>
```

LangChain 默认 splitter 完全无视结构，可能把 `<table>` 拦腰切在某个 `<td>` 中间，导致：

* 变体字面量 (`c.1319T > G`) 被切成两半，分到两个 chunk
* LLM 收到半张表，做 PM3 推断时丢失上下文
* `extract_tables_from_markdown`（[query.py:511-544](../app/core/query.py#L511-L544)）**只识别 pipe 表**，HTML 表的变体数据完全没人能拿到

## 解法

新模块 [app/core/markdown_splitter.py](../app/core/markdown_splitter.py) 引入四种**原子块**：

| 块类型 | 检测 | 处理 |
|--------|------|------|
| `html_table` | `<table>...</table>` | 完整保留 ≤ chunk_size；超大则按 `</tr>` 切子块，前缀 `[rows N-M of K]` |
| `pipe_table` | 连续 `\|...\|` 行 | 同上，但按行（每行一个 `\|` cell）切 |
| `fence` | ` ``` ` 或 `~~~` | 完整保留 |
| `image` | `![...](...)` 单行 | 完整保留 |

Heading (`#`/`##`/...) **不被剥离**，而是作为 `source_heading` 元数据传播到后续 chunk —— 这样 `## Mutation analysis` 既保留在 chunk 里（round-trip 不丢），又能让下游按 heading 过滤。

### Public API

```python
from app.core.markdown_splitter import markdown_aware_split, split_docs

# 单一字符串接口（独立可用）
chunks = markdown_aware_split(text, chunk_size=1800, chunk_overlap=200)

# 兼容旧接口：content 含 HTML / # / | 行 → markdown 路径；否则 → LangChain fallback
chunks = split_docs([Document(page_content=text, metadata={"source": "local"})],
                   chunk_size=1800, chunk_overlap=200)
```

### Metadata 契约

每个输出 `Document`：

| 字段 | 类型 | 说明 |
|------|------|------|
| `chunk_index` | int | 1-based 跨输入 doc 连续编号 |
| `chunk_size` / `chunk_overlap` | int | 透传参数 |
| `source` | str | 从输入 `Document.metadata["source"]` 继承 |
| **`chunk_kind`** | str | `html_table` / `pipe_table` / `fence` / `paragraph` / `paragraph_split` / `image` |
| **`source_heading`** | str \| None | 该 chunk 所属最近 `#`/`##` 标题 |
| **`contains_table`** | bool | 是否包含 `<table>` 或 `\|` 表 |
| **`block_count`** | int | 实际打包进该 chunk 的内容 block 数（不含 overlap seed） |

## 接入点

[app/core/query.py:880-901](../app/core/query.py#L880-L901) 在 `query_variant_in_paper_xml` 里：

```python
if is_markdown_input:
    effective_chunk_size, effective_chunk_overlap = 1800, 200
else:
    effective_chunk_size, effective_chunk_overlap = 1500, 100
doc_chunks = split_docs(doc_wrapper,
                        chunk_size=effective_chunk_size,
                        chunk_overlap=effective_chunk_overlap)
```

Markdown 路径用更大的窗口（1800/200）以吸收 HTML 表；XML 路径走 dispatcher 里的 LangChain fallback，行为不变。

## 测试覆盖

27 个 pytest 用例（[tests/](../tests/)），按场景分文件：

| 文件 | 关注点 |
|------|--------|
| [tests/test_markdown_splitter.py](../tests/test_markdown_splitter.py) | HTML 表原子性、变体可检索性、chunk 上限、round-trip、元数据契约、XML fallback、空输入、参数校验 |
| [tests/test_split_docs_integration.py](../tests/test_split_docs_integration.py) | **baseline 对照**（证明旧 splitter 破坏 Case 表）、`VariantSpecificRetriever` 端到端、oversize 表 / 段落处理 |
| [tests/test_synthetic_markdown.py](../tests/test_synthetic_markdown.py) | 11 个合成 case：pipe 表、围栏、image、纯表、heading 传播、heading 切换、跨 baseline 对照、oversize 表无行丢失 |

## 对比结果

跑 `python -m tests.benchmark_chunk_quality` 看完整输出。核心结论：

### Fixture 3 — 80 行 oversize HTML 表（chunk_size=600）

| 指标 | OLD LangChain | NEW markdown |
|------|--------------:|-------------:|
| chunk 数 | 11 | 10 |
| HTML 表 atomic / partial | **0 / 2**（部分） | **9 / 0**（完整） |
| `<tr>` 被切片的 chunk | **5** | **0** |
| 携带 `source_heading` 元数据 | 0 | 10 |

### Fixture 1 — 真实 MinerU paper (PMID 23689641)

| 指标 | OLD | NEW |
|------|----:|----:|
| `c.1896-1 G [ C`（OCR 形式）命中数 | 3 chunk | 4 chunk |
| 携带 `chunk_kind` 等新元数据 | 无 | html_table×2、image×8、paragraph×23 |

## 运行验证

```bash
# 全量测试
python -m pytest tests/ -v

# 单跑 baseline 对照测试 —— 证明旧实现坏
python -m pytest tests/test_split_docs_integration.py::test_baseline_splitter_fails_atomic_table -v

# 看 OLD vs NEW 对比表
python -m tests.benchmark_chunk_quality
```