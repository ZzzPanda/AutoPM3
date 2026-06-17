# AutoPM3 架构流程图

> 范围：主查询链路（用户上传 XML → variant 检索 → 结构化输出）。
> PDF 解析走 MinerU（见 [app/mineru/](app/mineru/)）和 PM3-Bench 离线数据下载（[app/data_io/](app/data_io/)），本文档不展开。

---

## 整体架构

```
                          ┌─────────────────────────────────────┐
                          │           Streamlit Pages           │
                          │                                     │
                          │  app/main.py            (DeepSeek)  │
                          │  app/pages/2_OpenAI_               │
                          │     Compatible.py      (任意端点)   │
                          │                                     │
                          └────────────────┬────────────────────┘
                                           │
                                           ▼
                          ┌─────────────────────────────────────┐
                          │   app/core/streamlit_helpers.py     │
                          │   ─ extract_paper_content()         │
                          │   ─ run_async_query()               │
                          │   ─ render_result()                 │
                          │   ─ session scratch dir + TTL       │
                          └────────────────┬────────────────────┘
                                           │  async
                                           ▼
                          ┌─────────────────────────────────────┐
                          │      app/core/query.py              │
                          │  query_variant_in_paper_xml()       │
                          │                                     │
                          │   ┌──────────────┐ ┌────────────┐   │
                          │   │  表格链路     │ │  文本链路  │   │
                          │   └──────────────┘ └────────────┘   │
                          └─────────────────────────────────────┘
```

两层职责清晰：

- **Pages** 只负责 UI（输入收集、按钮、错误展示）。
- **streamlit_helpers** 是 pages 之间的复用层，托管会话级文件、异步桥接、结果渲染。
- **core/query** 是纯业务逻辑，不依赖 Streamlit（CLI `python -m app.core.query` 也走它）。

---

## 完整流程图

```
┌──────────────────────────────────────────────────────────────────────────┐
│                       Streamlit UI  (浏览器)                              │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────────────┐    ┌─────────────────────────────────┐     │
│  │   app/main.py            │    │  app/pages/2_OpenAI_Compatible  │     │
│  │   ─ DeepSeek 固定        │    │  ─ 自定义 api_url / model_name  │     │
│  │   ─ DEEPSEEK_API_KEY     │    │  ─ OPENAI_API_KEY               │     │
│  │                          │    │  ─ TEST_MODE=ON 调试按钮        │     │
│  └────────────┬─────────────┘    └─────────────────┬───────────────┘     │
│               │                                    │                     │
│               │  st.file_uploader  →  paper_file   │                     │
│               │  st.text_input     →  variant_name │                     │
│               │  st.button("Run")  →  click        │                     │
│               └────────────────┬───────────────────┘                     │
└───────────────────────────────┼──────────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│             app/core/streamlit_helpers.py                                │
│                                                                          │
│  extract_paper_content(paper_file)                                       │
│    ├─ get_session_id()  →  当前 Streamlit 会话 id                         │
│    ├─ session_paper_dir(session_id)  →  $TMP/autopm3_sessions/<sid>/     │
│    ├─ 删除上一次上传 (st.session_state["paper_path"])                      │
│    └─ 写入 paper_<uuid>.xml，返回绝对路径                                  │
│                                                                          │
│  run_async_query(query_variant_in_paper_xml, *args)                      │
│    ├─ 同步 context → asyncio.run(coro)                                   │
│    └─ 已在 loop → ThreadPoolExecutor(1) 跑独立 loop（防御）               │
│                                                                          │
│  render_result(result)                                                   │
│    └─ 把 {"title", "sections": [...]} 渲染为 st.expander 堆叠             │
│                                                                          │
│  (模块 import 时 cleanup_old_sessions()，TTL = 24h)                       │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │  paper_path
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                app/core/query.py                                         │
│                                                                          │
│  query_variant_in_paper_xml(                                             │
│      query_variant, xml_path,                                            │
│      model_name_table, model_name_text,                                  │
│      api_key=None, api_url=None                                          │
│  )  →  async dict {"title", "sections": [...]}                           │
│                                                                          │
│  1.  _init_async_runtime()       # semaphore + thread pool               │
│  2.  _reset_mutalyzer_diagnostics()                                      │
│  3.  _build_llm(...)              # ChatDeepSeek 或 ChatOpenAI            │
│  4.  load_protein_map(data/protein.txt)                                  │
│  5.  httpx → Mutalyzer normalize  →  protein change                      │
│                                                                          │
│  ┌──────────────────────┐         ┌──────────────────────────────────┐    │
│  │  表格链路             │         │  文本链路                          │    │
│  │  (并行 gather)        │         │  (2×2 fan-out)                    │    │
│  ├──────────────────────┤         ├──────────────────────────────────┤    │
│  │ extractTablesFromXML  │         │ load_xml_paper(filter_tables=    │    │
│  │   (run on thread pool)│         │   True)                          │    │
│  │         │             │         │   │                              │    │
│  │         ▼             │         │   ▼                              │    │
│  │ table_extraction_     │         │ split_docs(chunk=1500)           │    │
│  │   with_deepseek       │         │   │                              │    │
│  │   (asyncio.gather)    │         │   ▼                              │    │
│  │   每个 table 一个 LLM  │         │ VariantSpecificRetriever         │    │
│  │   调用，走同一信号量    │         │   (regex: DNA / protein / 位置)  │    │
│  │         │             │         │   │ 预计算 (per variant)         │    │
│  │         ▼             │         │   ▼                              │    │
│  │ table_results_        │         │ StaticRetriever 包裹预计算 chunks │    │
│  │   plaintext           │         │   │                              │    │
│  └──────────┬────────────┘         │   ▼                              │    │
│             │                      │ RetrievalQA × {VARIANT_QUERY,    │    │
│             │                      │                INTRANS_QUERY}     │    │
│             │                      │   for c_index ∈ variant_alias    │    │
│             │                      │   每个 LLM 走同一信号量            │    │
│             │                      │   单次 TimeoutError 自动重试 1 次 │    │
│             │                      │         │                        │    │
│             │                      │         ▼                        │    │
│             │                      │ text_variant_answer              │    │
│             │                      │ text_intrans_list                │    │
│             └──────────┬───────────┴──────────────┬─────────────────┘    │
│                        ▼                          ▼                      │
│            ┌──────────────────────────────────────────────────┐          │
│            │  合并 + 渲染为结构化 dict                          │          │
│            │  sections[0]  表格查询结果                          │          │
│            │  sections[1]  文本：variant 上下文 (DNA / protein)│          │
│            │  sections[2]  文本：intrans-variant 列表 (去重)   │          │
│            │  sections[3]  Mutalyzer & 检索诊断 (新增)         │          │
│            └──────────────────────────────────────────────────┘          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 关键函数说明

| 函数 | 文件 | 作用 |
|------|------|------|
| `extract_paper_content(paper_file)` | [app/core/streamlit_helpers.py:105](app/core/streamlit_helpers.py#L105) | 写入会话级 scratch dir，返回绝对路径 |
| `run_async_query(async_fn, *args)` | [app/core/streamlit_helpers.py:174](app/core/streamlit_helpers.py#L174) | 同步 Streamlit handler → 异步 coroutine 的桥接 |
| `render_result(result)` | [app/core/streamlit_helpers.py:145](app/core/streamlit_helpers.py#L145) | 结构化 dict → `st.expander` 堆叠 |
| `query_variant_in_paper_xml(...)` | [app/core/query.py:610](app/core/query.py#L610) | **主入口**，async，并行调度表格 / 文本两条链路 |
| `query_variant_in_paper_xml_sync(...)` | [app/core/query.py:580](app/core/query.py#L580) | 同步包装，给 CLI (`python -m app.core.query`) 用 |
| `load_xml_paper(filename, filter_tables)` | [app/core/query.py:431](app/core/query.py#L431) | BioC / 自定义 XML → 纯文本；filter_tables=True 过滤掉 TABLE / REF 等段落 |
| `extractTablesFromXML(XML_path)` | [app/core/utils.py:136](app/core/utils.py#L136) | XML → `pd.DataFrame` 列表，BioC 优先，自定义格式 fallback |
| `VariantSpecificRetriever` | [app/core/query.py:186](app/core/query.py#L186) | 自定义 retriever，正则匹配 DNA → protein → 位置回退；把诊断信息写入模块级 `mutalyzer_diagnostics` |
| `StaticRetriever` | [app/core/query.py:405](app/core/query.py#L405) | 包裹预计算 chunks，避免 4 路并行 LLM 协程踩 retriever 的 per-instance state |
| `table_extraction_with_deepseek(...)` | [app/core/table_functions.py:156](app/core/table_functions.py#L156) | async，DeepSeek 直接读 CSV；`asyncio.gather` 每个 table 一个 LLM 调用 |
| `format_mutalyzer_diagnostics(diag)` | [app/core/query.py:980](app/core/query.py#L980) | 把 `mutalyzer_diagnostics` dict 渲染成 Markdown |
| `Mutalyzer / normalize` API | external | HGVS → protein change；调用方在 query.py（async httpx）和 VariantSpecificRetriever（sync requests）里都查了一次 |
| `data_io/download_papers.py` | [app/data_io/download_papers.py](app/data_io/download_papers.py) | **离线脚本**（非 UI 入口）：从 NCBI BioNLP 批量下 XML 到 `data/xml_papers/{pmid}.xml` |
| `MinerUClient / MinerULocalClient` | app/mineru/ | 独立子系统，PDF/PPT/DOCX → Markdown。本文档不展开。 |

---

## 两条链路对比

| | 表格链路 | 文本链路 |
|---|---|---|
| 数据源 | `extractTablesFromXML()` | `load_xml_paper(filter_tables=True)` |
| 处理 | DeepSeek 直接读 CSV prompt | 正则匹配 (DNA / protein) → LLM 问答 |
| 并发 | `asyncio.gather`：每张表一个 LLM 调用 | 2×2 fan-out：(c_variant / protein) × (VARIANT_QUERY / INTRANS_QUERY) |
| 信号量 | 全局 LLM semaphore (默认 4) | 同上 |
| 重试 | 无 | 单次 TimeoutError 自动 rebuild LLM 重试 1 次 |
| 输出 | `table_results_plaintext: List[str]` | `text_variant_answer: str` + `text_intrans_list: List[str]` |
| 顺序保证 | `gather` 输入顺序 | retrieval 预先算一次后用 `StaticRetriever` 避免 race |

---

## 异步运行时的全局约束

`query_variant_in_paper_xml` 是 async 入口。同一进程内多个 Streamlit 会话共享：

- **LLM semaphore** `AUTOPM3_LLM_CONCURRENCY`（默认 4）— 全局 in-flight LLM 调用上限。
- **LLM thread pool** — 让 HTTP I/O 释放 GIL。
- **session 隔离** — 上传文件落在 `$TMP/autopm3_sessions/<session_id>/`，TTL 24h（`AUTOPM3_SESSION_TTL_HOURS`）。每个会话读自己的 paper，互不污染。
- **per-coroutine state** — 每个 LLM 协程的 result 写到局部 dict，`asyncio.gather` 完成后才合并到最终 output。`text_intrans_list` 在合并后做 normalized 字符串去重（`_format_deduped_lines`）。

---

## 数据格式支持

```
XML 文件输入
    │
    ├─ BioC XML (NCBI API)         ──→ load_xml_paper() / extractTablesFromXML()
    │                                  （主路径）
    │
    └─ 自定义 XML (用户上传)         ──→ load_xml_paper() / extractTablesFromXML()
                                       （lxml 解析 <content>/<main_content>/<section>，
                                        表格路径解析 <table><thead><tbody>）
```

不直接支持 PDF：UI 会拒绝并提示重新上传 XML。PDF 用户应先经 [MinerU](app/mineru/) 转 Markdown/JSON。

---

## Variant 查询流程

```
输入: NM_004004.5:c.71G>A
          │
          ▼
    split(":") → 取最后一段
          │
          ▼
    c.71G>A → 71G>A   (去 c. 和括号)
          │
          ├────────────────────────────┐
          ▼                            ▼
   Mutalyzer normalize          protein change 计算
   (query.py: async httpx)      (retriever: sync requests)
          │                            │
          ▼                            ▼
   protein = "Leu24Arg"         long = "Leu24Arg"
                                short = "L24R"   (蛋白缩写映射)
                                        │
                                        ▼
                       ┌────────────────────────────────────┐
                       │  VariantSpecificRetriever           │
                       ├────────────────────────────────────┤
                       │ 1. DNA 正则:                        │
                       │    \s*71\s*G\s*>\s*A              │
                       │ 2. 蛋白长形式:  Leu24Arg            │
                       │ 3. 蛋白短形式:  L24R               │
                       │ 4. 位置回退 (前 3 步都没命中时触发):  │
                       │    \D71\D  /  \D24\D               │
                       └────────────────────────────────────┘
                                        │
                                        ▼
                            retrieved_chunks (top-k = 5)
                                        │
                                        ▼
                            StaticRetriever 包裹
                                        │
                                        ▼
                       2×2 LLM 问答 (VARIANT_QUERY / INTRANS_QUERY)
```

诊断面板 (sections[3]) 实时展示每一步的实际输入：

- Mutalyzer 端点 / 返回状态 / 错误
- 实际使用的 DNA regex
- long/short 形式各自的命中 chunk 数
- 位置回退是否触发、是否命中
- 最终 retriever 返回的 chunk 总数

---

## 输出格式

`query_variant_in_paper_xml` 返回结构化 dict，由 `render_result` 渲染：

```python
{
  "title": "Output Summary",
  "sections": [
    {
      "title": "Query Variant and Relative Intrans-variant / Genotype Found in PaperTables",
      "body": "<table_results_plaintext joined>",
    },
    {
      "title": "Query Variant Found in PaperText",
      "body": "- **[DNA match result]**: ...\n- **[Protein match result]**: ...",
    },
    {
      "title": "Query Variant's Intrans-variant Found in PaperText",
      "body": "- c.269T>C\n- c.512T>A   # 规范化去重，保留模型首次出现顺序",
    },
    {
      "title": "Mutalyzer & Search Diagnostics",
      "body": "<format_mutalyzer_diagnostics() 的 markdown>",
    },
  ],
}
```

`render_result` 把 4 段分别包成 `st.expander(..., expanded=True)`，内部用 `##` 标题 + `st.markdown` 渲染 body。

---

## CLI 入口

```bash
python -m app.core.query \
    --query_variant "NM_004004.5:c.71G>A" \
    --paper_path ./data/xml_papers/36546626.xml \
    --deepseek_api_key $DEEPSEEK_API_KEY
```

走 `query_variant_in_paper_xml_sync` → `asyncio.run(async_query(...))`。打印原始 dict。
