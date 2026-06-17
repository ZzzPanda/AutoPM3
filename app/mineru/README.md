# MinerU Integration

[English](./README.md) | [简体中文](./README.zh.md)

A small client that wraps the [MinerU](https://mineru.net/apiManage/docs) cloud
APIs for converting PDF / image / DOCX / PPTX / XLSX files into structured
**Markdown** and **JSON** outputs. Designed to slot into AutoPM3's literature
processing pipeline.

## Layout

```
mineru/
├── __init__.py        # public re-exports
├── client.py          # MinerUClient + MinerULocalClient + exceptions + dataclasses
├── README.md          # this file (research notes + usage)
├── examples/
│   └── test_with_local_pdf.py   # end-to-end smoke script (uses data/pdf_convert/)
└── tests/
    └── test_client.py # unit + live tests
```

## API at a glance

MinerU exposes two parallel cloud APIs and one self-hosted local API.

| API | Path prefix | Auth | Limits | Use when |
| --- | --- | --- | --- | --- |
| 精准解析 (precise) | `/api/v4/extract/*` | Bearer token | 200 MB / 200 pages / 200 files per batch | High-fidelity extraction, batch jobs |
| Agent 轻量解析 (lightweight) | `/api/v1/agent/parse/*` | None (IP rate-limited) | 10 MB / 20 pages / single file | Quick one-offs, demos |
| Local (`mineru-api`) | `/tasks`, `/file_parse` | None | Configurable | Self-hosted with GPU |

### Precise API (v4) — main flow

1. `POST /api/v4/extract/task` with a JSON body containing the PDF URL and
   extraction options → returns `task_id`.
2. `GET /api/v4/extract/task/{task_id}` repeatedly until `state == "done"`.
3. Download the result ZIP from the returned `full_zip_url`.

For batches, use `POST /api/v4/extract/task/batch` (URLs) and poll
`GET /api/v4/extract-results/batch/{batch_id}`.

#### Task / batch status states

`pending` → `running` (`converting` for HTML backend) → `done` / `failed`.
The `extract_progress` object reports `extracted_pages`, `total_pages`, and
`start_time`.

#### Notable request fields

| field | values | notes |
| --- | --- | --- |
| `model_version` | `pipeline` (default) / `vlm` / `MinerU-HTML` | VLM uses vision-language model; HTML is the new layout backend |
| `language` | `ch` (default) / `en` / `japan` / `korean` / `chinese_cht` / `ta` / `te` / `ka` / `el` / `th` / `latin` / `arabic` / `cyrillic` / `east_slavic` / `devanagari` | `ch_server` is the server-side OCR model |
| `enable_formula` / `enable_table` | bool | both default `true` |
| `is_ocr` | bool | force OCR even on text-layer PDFs |
| `page_ranges` | `"2,4-6"` | select specific pages |
| `extra_formats` | list | only with `MinerU-HTML`: `docx`, `html`, `latex` |
| `callback` + `seed` | string | webhook for completion; `seed` required when callback is set |
| `no_cache` / `cache_tolerance` (sec) | bool / int | cache control |

#### Error codes

| code | meaning |
| --- | --- |
| `A0202` | token invalid / user auth failed |
| `A0211` | token expired |
| `-500` | parameter error |
| `-60001` … `-60022` | service errors (URL gen, format, file read, size, pages, conversion, retry limits) |

### Agent API (v1) — quick flow

1. `POST /api/v1/agent/parse/url` (or `/file` to upload) → returns `task_id`.
2. `GET /api/v1/agent/parse/{task_id}` until `state == "done"`.
3. Read `markdown_url` from the response — it points to a CDN-hosted `.md` file.

States: `waiting-file` → `uploading` → `pending` → `running` → `done` / `failed`.
Error codes: `-30001` (file too big), `-30002` (bad type), `-30003` (too many
pages), `-30004` (bad parameter).

### Result ZIP contents

The precise API returns a ZIP with the following (file names depend on the
backend and `extra_formats`):

- `{file}.md` — clean Markdown
- `{file}_layout.pdf` — layout visualization overlay
- `{file}_span.pdf` — extracted text spans (pipeline only)
- `{file}_middle.json` — intermediate processing (`pdf_info[]`, `_backend`,
  `_version_name`)
- `{file}_content_list.json` — content list (types: `image`, `table`, `chart`,
  `text`, `equation`, `code`, `list`, `header`, `footer`, `page_number`,
  `aside_text`, `page_footnote`)
- `{file}_content_list_v2.json` — new page-grouped structure (MinerU 3.0+)
- `images/` — extracted figures

## Authentication

1. Log in at <https://mineru.net/apiManage/token>.
2. Copy the Bearer token.
3. Pass it to `MinerUClient(token=...)` **or** set `MINERU_TOKEN` in the
   environment / `.env` file.

The Agent API does **not** require a token.

## Usage

### Single file (precise API)

```python
from mineru import MinerUClient

client = MinerUClient()  # uses MINERU_TOKEN env var
paths = client.parse_url(
    "https://example.com/paper.pdf",
    output_dir="output/paper",
    model_version="pipeline",  # or "vlm"
    language="en",
    enable_formula=True,
    enable_table=True,
    timeout=600,
)
# paths: [Path("output/paper/<task_id>/paper.md"), ...]
```

### Batch (precise API)

```python
files = [
    {"name": "a.pdf", "url": "https://example.com/a.pdf", "data_id": "a"},
    {"name": "b.pdf", "url": "https://example.com/b.pdf", "data_id": "b"},
]
results = client.parse_urls(files, output_dir="output/batch")
# results: {"a": [paths...], "b": [paths...]}
```

### Quick one-off (Agent API, no token)

```python
task_id = client.agent_submit_url("https://example.com/short.pdf")
status = client.agent_wait_for_task(task_id)
markdown_text = requests.get(status.markdown_url).text
```

## Configuration

`mineru/.env.example`:

```bash
# Required for the precise (v4) API. Get one at
# https://mineru.net/apiManage/token
MINERU_TOKEN=your-token-here

# Optional: override the base URL (e.g. for staging / proxies)
# MINERU_BASE_URL=https://mineru.net

# Optional: set to 1 to enable the live integration tests
# MINERU_LIVE=0
```

The client does **not** auto-load `.env`; if you want it, call
`load_dotenv()` from `python-dotenv` at the entry point of your script
(both `python-dotenv` and the loader pattern are already used elsewhere in
this project).

## Testing

```bash
# Offline unit tests
python -m unittest discover mineru/tests -v

# Live smoke tests (requires MINERU_TOKEN and network access)
MINERU_LIVE=1 MINERU_TOKEN=... python -m unittest discover mineru/tests -v

# Live tests against a running local mineru-api server
mineru-api --host 0.0.0.0 --port 8000 &
MINERU_LOCAL_LIVE=1 python -m unittest mineru.tests.test_client.LocalLiveTests -v
```

The offline tests mock `requests.Session` so they run anywhere. The live tests
hit the real `/api/v4/extract/task` endpoint with a small demo PDF served by
MinerU's CDN.

## End-to-end smoke test against `data/pdf_convert/`

A runnable script is included that exercises the local PDF fixture
(`PubMed23689641.pdf`, 22 pages, 835 KB) end-to-end:

```bash
# 1. Inspect the existing MinerU artifacts that came with the repo
python mineru/examples/test_with_local_pdf.py

# 2. Submit the same PDF to a locally running mineru-api server
pip install "mineru[all]"
mineru-api --host 0.0.0.0 --port 8000 &
python mineru/examples/test_with_local_pdf.py --local-server

# 3. Submit via the cloud API (requires MINERU_TOKEN; serves the PDF locally
#    on a random port so MinerU can fetch it back)
MINERU_TOKEN=... python mineru/examples/test_with_local_pdf.py --cloud

# All three
python mineru/examples/test_with_local_pdf.py --all
```

The cloud step uses a temporary `http.server` on `127.0.0.1` — MinerU's
precise API only accepts URLs, not multipart uploads, so the file has to be
reachable. The script starts a one-shot server for the lifetime of the
request, so this is safe to run on a laptop without exposing the file
externally (assuming the MinerU backend can reach your `127.0.0.1`; for
fully-isolated runs, prefer the local server).

## Caveats discovered during research

1. **`/api/v4/file-urls/batch` presigned URL** — there is an open
   [issue #4145](https://github.com/opendatalab/MinerU) reporting that the
   returned Alibaba-OSS URL returns HTTP 403 on `PUT`. Until that's resolved,
   prefer `submit_url` or `submit_batch` with already-hosted URLs, or run the
   local `mineru-api` server and upload via multipart.
2. **Token errors on new tokens** — issue #5133 reports `A0202` from tokens
   that were just generated; the cause is still being tracked. Retry once
   before reporting a hard failure.
3. **Doc site is a SPA** — `mineru.net/apiManage/docs` is a client-rendered
   Next.js page, so plain `curl` returns an HTML shell. The endpoint details
   in this README were corroborated against the
   [opendatalab/MinerU GitHub repo](https://github.com/opendatalab/MinerU),
   the [PyPI package](https://pypi.org/project/mineru/), and the
   [project docs site](https://opendatalab.github.io/MinerU/).
4. **Result retention** — local `mineru-api` retains tasks for 24 h by
   default (`MINERU_API_TASK_RETENTION_SECONDS`). Cloud retention is
   undocumented in the public docs.

## References

- Cloud API docs: <https://mineru.net/apiManage/docs>
- Token page: <https://mineru.net/apiManage/token>
- PyPI: <https://pypi.org/project/mineru/>
- Project docs: <https://opendatalab.github.io/MinerU/>
- Source: <https://github.com/opendatalab/MinerU>
