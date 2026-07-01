# TODO / 待办

> Last updated: 2026-06-21

## Now / 当前

| ID | 任务 / Task | 状态 / Status | 下一步 / Next step |
| -- | ----------- | ------------- | ------------------ |
| T1 | 团队知识库 / Team knowledge base | Todo | 新建 `docs/knowledge_base/index.md`，列出核心概念。 / Create `docs/knowledge_base/index.md` with the core concepts list. |
| T2 | 论文总结算子 / Paper summary operator | Todo | 定义单篇论文总结 schema，不要求输入 variant。 / Define the one-paper summary schema without requiring a variant. |
| T3 | 测试数据梳理与数据结构优化 / Test data review and data-structure optimization | In progress | 基于 `docs/data_inventory_t3.md` 和算法同学确认训练/评测 schema。 / Confirm the training/evaluation schema with the algorithm team using `docs/data_inventory_t3.md`. |

## Details / 详情

### T1. 团队知识库 / Team knowledge base

目标 / Goal: 让团队成员不用先读完整代码，也能理解 AutoPM3 的核心概念。
Help teammates understand AutoPM3 core concepts without reading all code first.

第一版包含 / First version should cover:

- PM3 流程 / PM3 workflow
- variant、gene、phenotype 概念 / variant, gene, and phenotype concepts
- 家系与父母验证概念 / family and parental validation concepts
- PDF、PubMed、BioC、Markdown 预处理 / PDF, PubMed, BioC, and Markdown preprocessing
- 主要代码位置 / where the main code lives

完成标准 / Done when: 新成员能从一个 index 页面开始，找到关键文档。
A new teammate can start from one index page and find the key docs.

### T2. 论文总结算子 / Paper summary operator

目标 / Goal: 即使用户没有提供目标 variant，也能总结单篇论文。
Summarize a paper even when the user does not provide a target variant.

第一版抽取 / First version should extract:

- 论文标题、PMID、DOI / paper title, PMID, DOI
- 疾病与表型 / disease and phenotype
- 家系信息 / family information
- 文中提到的 variants 或 genes / variants or genes mentioned in the paper
- 缺失或未报道的信息 / what is missing or not reported

完成标准 / Done when: 可以跑一批已下载的 PubMed PDF，并保存可复用的单篇论文总结。
It can run on a folder of downloaded PubMed PDFs and save reusable per-paper summaries.

### T3. 测试数据梳理与数据结构优化 / Test data review and data-structure optimization

目标 / Goal: 先搞清楚用户提供的测试数据本身，再和算法同学沟通如何优化数据结构，用来构建测试集和训练数据。
Understand the user-provided test data first, then align with the algorithm team on data-structure improvements for test-set and training-data construction.

第一版包含 / First version should cover:

- 数据来源、格式、字段和样本量 / data sources, formats, fields, and sample counts
- 数据质量问题和缺失信息 / data quality issues and missing information
- 标注目标和可复用标签 / annotation targets and reusable labels
- 与算法沟通后的推荐数据结构 / recommended data structure after algorithm-team discussion
- 测试集和训练数据的拆分方案 / split plan for test sets and training data

完成标准 / Done when: 有一份清晰的数据盘点表和数据结构建议，可以开始构建测试集与训练数据。
There is a clear data inventory and data-structure proposal ready for building test sets and training data.

## Done / 已完成

- 2026-06-19: 创建简洁 TODO 清单。 / Created simple TODO list.
- 2026-06-21: 新增 T3 测试数据梳理任务。 / Added T3 test data review task.
- 2026-06-21: 完成 T3 第一版数据盘点与结构建议。 / Completed the first T3 data inventory and structure proposal.
