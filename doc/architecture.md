# AutoPM3 架构流程图

## 整体架构

```
lit.py (Streamlit UI)
        │
        ├── Tab 1: Upload XML
        │         └── extract_xml_content() → 保存上传的 XML
        │
        └── Tab 2: Enter PMID
                  └── load_xml() → 从 NCBI API 获取 BioC XML
                            │
                            ▼
                  query_variant_in_paper_xml()
                            │
            ┌───────────────┴───────────────┐
            │                               │
            ▼                               ▼
     ┌─────────────┐               ┌─────────────┐
     │   表格链路   │               │   文本链路   │
     └─────────────┘               └─────────────┘
```

---

## 完整流程图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              lit.py (Streamlit UI)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────────┐         ┌─────────────────────┐                     │
│   │   Upload XML     │         │    Enter PMID        │                     │
│   │  (Tab 1)         │         │   (Tab 2)            │                     │
│   └────────┬────────┘         └──────────┬────────────┘                     │
│            │                             │                                  │
│            ▼                             ▼                                  │
│   ┌─────────────────┐         ┌─────────────────────┐                     │
│   │extract_xml_     │         │load_xml()            │                     │
│   │content(xml)     │         │从 NCBI API 获取 BioC XML                  │
│   └────────┬────────┘         └──────────┬────────────┘                     │
│            │                             │                                  │
│            └──────────┬───────────────────┘                                  │
│                       ▼                                                     │
│              ┌────────────────┐                                             │
│              │  run_query()   │                                             │
│              └────────┬───────┘                                              │
└──────────────────────┼─────────────────────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                     AutoPM3_main.py                                          │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              query_variant_in_paper_xml()                             │   │
│  │                                                                      │   │
│  │   1. 加载文本模型 (DeepSeek/Ollama)                                   │   │
│  │   2. 加载表格模型 (sqlcoder - Ollama 本地)                            │   │
│  │   3. load_protein_map() - 蛋白缩写映射                               │   │
│  │                                                                      │   │
│  │   ┌─────────────────────────────────────────────────────────────┐   │   │
│  │   │              并行执行 ↓                                      │   │   │
│  │   └─────────────────────────────────────────────────────────────┘   │   │
│  │                         │                                              │   │
│  │          ┌──────────────┴──────────────┐                             │   │
│  │          ▼                             ▼                             │   │
│  │   ┌──────────────────┐       ┌──────────────────────────┐           │   │
│  │   │   表格链路              │       │   文本链路                  │           │   │
│  │   ├──────────────────┤       ├──────────────────────────┤           │   │
│  │   │ extractTablesFrom│       │ load_xml_paper()         │           │   │
│  │   │ XML()            │       │ 提取文章文本内容          │           │   │
│  │   │ 提取表格          │       │                          │           │   │
│  │   │ (utils.py)       │       │ split_docs()             │           │   │
│  │   │                  │       │ 分块 1500 chars          │           │   │
│  │   │                  │       │                          │           │   │
│  │   │ table_extraction │       │ VariantSpecificRetriever │           │   │
│  │   │ _with_deepseek() │       │ (正则匹配 variant)        │           │   │
│  │   │ 直接用 DeepSeek   │       │                          │           │   │
│  │   │ 解析表格内容       │       │ load_qa_chain()          │           │   │
│  │   │                  │       │ + get_answers_PM3()       │           │   │
│  │   │ 返回:            │       │ LLM 问答                  │           │   │
│  │   │ table_results   │       │                          │           │   │
│  │   │ _plaintext      │       │ 返回:                     │           │   │
│  │   └──────────────────┘       │ text_variant_answer      │           │   │
│  │                              │ text_intrans_list       │           │   │
│  │                              └──────────────────────────┘           │   │
│  │                         │                                              │   │
│  │   ┌─────────────────────┴───────────────────────┐                   │   │
│  │   │                                               ▼                   │   │
│  │   │            ┌──────────────────────────────┐                   │   │
│  │   │            │     合并结果，返回 Markdown   │                   │   │
│  │   │            └──────────────────────────────┘                   │   │
│  └───┴───────────────┴───────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 关键函数说明

| 函数 | 文件 | 作用 |
|------|------|------|
| `load_xml()` | lit.py | 从 NCBI API 获取 BioC XML |
| `extract_xml_content()` | lit.py | 保存上传的 XML 到临时文件 |
| `query_variant_in_paper_xml()` | AutoPM3_main.py | **主入口**，协调文本和表格两条链路 |
| `load_xml_paper()` | AutoPM3_main.py | 从 XML 提取文本（支持 BioC 和自定义格式） |
| `extractTablesFromXML()` | utils.py | 从 XML 提取表格 DataFrame 列表 |
| `VariantSpecificRetriever` | AutoPM3_main.py | 自定义 retriever，用正则匹配 variant |
| `table_extraction_with_deepseek()` | table_functions.py | 用 DeepSeek 直接解析表格内容 |
| `Mutalyzer API` | external | HGVS variant → protein change 转换 |

---

## 两条链路对比

| | 表格链路 | 文本链路 |
|---|---|---|
| 数据源 | `extractTablesFromXML()` | `load_xml_paper()` |
| 处理方式 | DeepSeek 直接读 CSV | 正则匹配 + LLM 问答 |
| 模型 | `deepseek-v4-flash` | `deepseek-v4-flash` / `llama3` |
| 输出 | `table_results_plaintext` | `text_variant_answer` + `text_intrans_list` |

---

## 数据格式支持

```
XML 文件输入
    │
    ├─ BioC XML 格式 (NCBI API) ──→ load_xml_paper() / extractTablesFromXML()
    │
    └─ 自定义 XML 格式 (上传) ────→ load_xml_paper() / extractTablesFromXML()
                                      (有 fallback 逻辑)
```

---

## Variant 查询流程

```
输入: NM_004004.5:c.71G>A
          │
          ▼
    split(":") 取最后部分
          │
          ▼
    c.71G>A → 71G>A (去 c.)
          │
          ▼
    Mutalyzer API 转换
          │
          ▼
    获取 protein change (如 p.L24R)
          │
          ▼
    ┌─────────────────────────────────┐
    │         两条检索链路            │
    ├─────────────────────────────────┤
    │ DNA 正则: \s*71\s*G\s*>\s*A    │
    │ 蛋白匹配: L24R / L24           │
    │ 位置回退: 71 单独匹配           │
    └─────────────────────────────────┘
```

---

## 输出格式

```markdown
# Output Summary:

## Query Variant and Relative Intrans-variant/Genotype Found in PaperTables:
[表格查询结果]

## Query Variant Found in PaperText:
- [DNA match result]: ...
- [Protein match result]: ...

## Query Variant's Intrans-variant Found in PaperText:
[杂合变异列表] 或 "None!"
```