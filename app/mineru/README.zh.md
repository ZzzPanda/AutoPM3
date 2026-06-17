# MinerU 集成

[English](./README.md) | **简体中文**

一个轻量的客户端，对 [MinerU](https://mineru.net/apiManage/docs) 云端 API 做了封装，用于把 PDF / 图片 / DOCX / PPTX / XLSX 文件转换为结构化的 **Markdown** 和 **JSON** 输出。设计上能直接嵌入 AutoPM3 的文献处理流水线。

## 目录结构

```
mineru/
├── __init__.py        # 公开符号 re-export
├── client.py          # MinerUClient + MinerULocalClient + 异常 + dataclass
├── README.md          # 本文件（调研笔记 + 使用说明）
├── examples/
│   └── test_with_local_pdf.py   # 端到端冒烟脚本（使用 data/pdf_convert/）
└── tests/
    └── test_client.py # 单元测试 + live 测试
```

## API 一览

MinerU 提供了两套并行的云端 API 和一个本地自托管 API。

| API | 路径前缀 | 鉴权 | 限制 | 适用场景 |
| --- | --- | --- | --- | --- |
| 精准解析（precise） | `/api/v4/extract/*` | Bearer token | 单批 200 MB / 200 页 / 200 个文件 | 高保真提取、批处理 |
| Agent 轻量解析 | `/api/v1/agent/parse/*` | 无（按 IP 限流） | 10 MB / 20 页 / 单文件 | 临时单文件、演示 |
| 本地（`mineru-api`） | `/tasks`、`/file_parse` | 无 | 可配置 | 自带 GPU 自托管 |

### 精准解析 API（v4）—— 主流程

1. `POST /api/v4/extract/task`，body 为 JSON，包含 PDF URL 和抽取选项 → 返回 `task_id`。
2. 反复 `GET /api/v4/extract/task/{task_id}` 轮询，直到 `state == "done"`。
3. 从返回的 `full_zip_url` 下载结果 ZIP。

批量请用 `POST /api/v4/extract/task/batch`（传 URL），然后轮询 `GET /api/v4/extract-results/batch/{batch_id}`。

#### 任务 / 批处理状态

`pending` → `running`（HTML 后端对应 `converting`）→ `done` / `failed`。
`extract_progress` 对象会回报 `extracted_pages`、`total_pages`、`start_time`。

#### 关键请求字段

| 字段 | 取值 | 说明 |
| --- | --- | --- |
| `model_version` | `pipeline`（默认） / `vlm` / `MinerU-HTML` | VLM 走视觉语言模型；HTML 是新的版面后端 |
| `language` | `ch`（默认） / `en` / `japan` / `korean` / `chinese_cht` / `ta` / `te` / `ka` / `el` / `th` / `latin` / `arabic` / `cyrillic` / `east_slavic` / `devanagari` | `ch_server` 是服务端 OCR 模型 |
| `enable_formula` / `enable_table` | bool | 默认都是 `true` |
| `is_ocr` | bool | 即使是带文字层的 PDF 也强制走 OCR |
| `page_ranges` | `"2,4-6"` | 选特定页 |
| `extra_formats` | list | 仅 `MinerU-HTML` 支持：`docx`、`html`、`latex` |
| `callback` + `seed` | string | 完成时回调 webhook；设置 callback 时必须同时给 `seed` |
| `no_cache` / `cache_tolerance`（秒） | bool / int | 缓存控制 |

#### 错误码

| 错误码 | 含义 |
| --- | --- |
| `A0202` | token 无效 / 用户鉴权失败 |
| `A0211` | token 已过期 |
| `-500` | 参数错误 |
| `-60001` … `-60022` | 服务端错误（URL 生成、格式、文件读取、大小、页数、转换、重试上限等） |

### Agent API（v1）—— 快速流程

1. `POST /api/v1/agent/parse/url`（或 `/file` 上传文件）→ 返回 `task_id`。
2. `GET /api/v1/agent/parse/{task_id}` 直到 `state == "done"`。
3. 从响应里读 `markdown_url`——指向 CDN 上的 `.md` 文件。

状态：`waiting-file` → `uploading` → `pending` → `running` → `done` / `failed`。
错误码：`-30001`（文件太大）、`-30002`（文件类型错）、`-30003`（页数超限）、`-30004`（参数错）。

### 结果 ZIP 内容

精准解析 API 返回的 ZIP 包含以下内容（文件名取决于后端和 `extra_formats`）：

- `{file}.md` —— 干净的 Markdown
- `{file}_layout.pdf` —— 版面可视化叠层
- `{file}_span.pdf` —— 抽取的文本 span（仅 pipeline）
- `{file}_middle.json` —— 中间产物（`pdf_info[]`、`_backend`、`_version_name`）
- `{file}_content_list.json` —— 内容列表（类型：`image`、`table`、`chart`、`text`、`equation`、`code`、`list`、`header`、`footer`、`page_number`、`aside_text`、`page_footnote`）
- `{file}_content_list_v2.json` —— 新的按页分组结构（MinerU 3.0+）
- `images/` —— 抽取出的图片

## 鉴权

1. 登录 <https://mineru.net/apiManage/token>。
2. 复制 Bearer token。
3. 把 token 传给 `MinerUClient(token=...)` **或** 在环境变量 / `.env` 文件里设 `MINERU_TOKEN`。

Agent API **不**需要 token。

## 使用

### 单文件（精准解析 API）

```python
from mineru import MinerUClient

client = MinerUClient()  # 读 MINERU_TOKEN 环境变量
paths = client.parse_url(
    "https://example.com/paper.pdf",
    output_dir="output/paper",
    model_version="pipeline",  # 或 "vlm"
    language="en",
    enable_formula=True,
    enable_table=True,
    timeout=600,
)
# paths: [Path("output/paper/<task_id>/paper.md"), ...]
```

### 批量（精准解析 API）

```python
files = [
    {"name": "a.pdf", "url": "https://example.com/a.pdf", "data_id": "a"},
    {"name": "b.pdf", "url": "https://example.com/b.pdf", "data_id": "b"},
]
results = client.parse_urls(files, output_dir="output/batch")
# results: {"a": [paths...], "b": [paths...]}
```

### 临时单文件（Agent API，无需 token）

```python
task_id = client.agent_submit_url("https://example.com/short.pdf")
status = client.agent_wait_for_task(task_id)
markdown_text = requests.get(status.markdown_url).text
```

## 配置

`mineru/.env.example`：

```bash
# 精准解析（v4）API 必填。Token 在这里取：
# https://mineru.net/apiManage/token
MINERU_TOKEN=your-token-here

# 可选：覆盖 base URL（如 staging / 代理环境）
# MINERU_BASE_URL=https://mineru.net

# 可选：设为 1 开启 live 集成测试
# MINERU_LIVE=0
```

客户端 **不会** 自动加载 `.env`；如果需要，在脚本入口处调用 `python-dotenv` 的 `load_dotenv()`（本项目其它地方已经在用 `python-dotenv` 和这套加载模式）。

## 测试

```bash
# 离线单元测试
python -m unittest discover mineru/tests -v

# Live 冒烟测试（需要 MINERU_TOKEN 和外网）
MINERU_LIVE=1 MINERU_TOKEN=... python -m unittest discover mineru/tests -v

# 针对本地的 mineru-api 服务器跑 live 测试
mineru-api --host 0.0.0.0 --port 8000 &
MINERU_LOCAL_LIVE=1 python -m unittest mineru.tests.test_client.LocalLiveTests -v
```

离线测试用 `mock` 替换 `requests.Session`，在任何环境都能跑。Live 测试会真的命中 `/api/v4/extract/task` 端点，传入 MinerU CDN 提供的一份小型 demo PDF。

## 用 `data/pdf_convert/` 做端到端冒烟

仓库里带了一个可运行的脚本，能用本地 PDF 夹具（`PubMed23689641.pdf`，22 页，835 KB）跑通端到端：

```bash
# 1. 查看仓库里已有的 MinerU 产物
python mineru/examples/test_with_local_pdf.py

# 2. 把同一份 PDF 提交到本地 mineru-api 服务器
pip install "mineru[all]"
mineru-api --host 0.0.0.0 --port 8000 &
python mineru/examples/test_with_local_pdf.py --local-server

# 3. 走云端 API（需要 MINERU_TOKEN；脚本会在本地随机端口开一个 http.server，
#    让 MinerU 能从公网拉回 PDF）
MINERU_TOKEN=... python mineru/examples/test_with_local_pdf.py --cloud

# 三种全跑
python mineru/examples/test_with_local_pdf.py --all
```

第 3 步用了一个临时的 `http.server` 监听 `127.0.0.1`——MinerU 的精准解析 API 只接受 URL，不接受 multipart 上传，所以文件必须可达。脚本会为本次请求的整个生命周期启一个一次性服务器，在笔记本上跑是安全的，不会把文件对外暴露（前提是 MinerU 后端能到达你的 `127.0.0.1`；要完全隔离的话优先用本地 server）。

## 调研中发现的坑

1. **`/api/v4/file-urls/batch` 预签名 URL** —— 有一个[公开 issue #4145](https://github.com/opendatalab/MinerU) 报告说返回的 Alibaba-OSS URL 在 `PUT` 时返回 HTTP 403。在解决前，建议优先用 `submit_url` 或 `submit_batch`（传入已托管的 URL），或者跑本地的 `mineru-api` 服务器走 multipart 上传。
2. **新 token 报错** —— issue #5133 报告刚生成的 token 也会触发 `A0202`；原因还在跟进，遇到硬失败前先重试一次。
3. **文档站是 SPA** —— `mineru.net/apiManage/docs` 是客户端渲染的 Next.js 页面，裸 `curl` 只会拿到 HTML 外壳。本 README 中的端点细节已经与 [opendatalab/MinerU GitHub 仓库](https://github.com/opendatalab/MinerU)、[PyPI 包](https://pypi.org/project/mineru/) 和 [项目文档站](https://opendatalab.github.io/MinerU/) 交叉核对过。
4. **结果保留期** —— 本地 `mineru-api` 默认保留任务 24 小时（`MINERU_API_TASK_RETENTION_SECONDS`）。云端的保留期公开文档里没写。

## 参考

- 云端 API 文档：<https://mineru.net/apiManage/docs>
- Token 申请页：<https://mineru.net/apiManage/token>
- PyPI：<https://pypi.org/project/mineru/>
- 项目文档：<https://opendatalab.github.io/MinerU/>
- 源码：<https://github.com/opendatalab/MinerU>
