"""
MinerU API client.

Wraps the MinerU cloud APIs for converting PDF / image / DOCX / PPTX / XLSX
files into structured Markdown and JSON.

Reference: https://mineru.net/apiManage/docs
Source:    https://github.com/opendatalab/MinerU

Two cloud APIs are exposed:

* 精准解析 API (``/api/v4/extract/*``) — token-authenticated, high-fidelity,
  supports ``pipeline`` / ``vlm`` / ``MinerU-HTML`` backends. 200 MB / 200
  pages / 200 files per batch.

* Agent 轻量解析 API (``/api/v1/agent/parse/*``) — no auth, IP rate-limited,
  single file only, ≤10 MB and ≤20 pages. Returns a markdown CDN link.

This module provides a single :class:`MinerUClient` that talks to both.
"""

from __future__ import annotations

import io
import json
import os
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import requests


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://mineru.net"
PRECISE_PATH = "/api/v4/extract/task"
PRECISE_BATCH_PATH = "/api/v4/extract/task/batch"
PRECISE_TASK_PATH = "/api/v4/extract/task/{task_id}"
PRECISE_BATCH_RESULT_PATH = "/api/v4/extract-results/batch/{batch_id}"

AGENT_URL_PATH = "/api/v1/agent/parse/url"
AGENT_FILE_PATH = "/api/v1/agent/parse/file"
AGENT_RESULT_PATH = "/api/v1/agent/parse/{task_id}"

# Limits published in the MinerU docs
MAX_FILE_SIZE_BYTES = 200 * 1024 * 1024  # 200 MB
MAX_PAGES = 200
MAX_BATCH_FILES = 200

# Agent (lightweight) limits
AGENT_MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
AGENT_MAX_PAGES = 20

# Polling defaults
DEFAULT_POLL_INTERVAL = 5.0
DEFAULT_TIMEOUT = 600.0

# Terminal states for the precise (v4) API
PRECISE_DONE = "done"
PRECISE_FAILED = "failed"
PRECISE_RUNNING_STATES = {"pending", "running", "converting"}

# Terminal states for the agent (v1) API
AGENT_DONE = "done"
AGENT_FAILED = "failed"
AGENT_RUNNING_STATES = {"waiting-file", "uploading", "pending", "running"}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class MinerUError(Exception):
    """Base exception for MinerU client errors."""


class MinerUAuthError(MinerUError):
    """Token missing, invalid, or expired (codes A0202 / A0211)."""


class MinerUAPIError(MinerUError):
    """A non-zero ``code`` was returned by the API."""

    def __init__(self, code: int, msg: str, trace_id: str | None = None):
        super().__init__(f"[{code}] {msg}")
        self.code = code
        self.msg = msg
        self.trace_id = trace_id


class MinerUTimeoutError(MinerUError):
    """Polling timed out before the task reached a terminal state."""


class MinerUFileError(MinerUError):
    """File-level constraint violated (size, page count, type)."""


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TaskStatus:
    """Subset of fields we care about from the precise / agent APIs."""

    task_id: str
    state: str
    full_zip_url: str | None = None
    markdown_url: str | None = None
    err_msg: str | None = None
    err_code: int | None = None
    data_id: str | None = None
    progress: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_done(self) -> bool:
        return self.state in (PRECISE_DONE, AGENT_DONE)

    @property
    def is_failed(self) -> bool:
        return self.state in (PRECISE_FAILED, AGENT_FAILED)


@dataclass
class BatchStatus:
    """Result of polling a batch (precise API)."""

    batch_id: str
    state: str  # aggregated: done | running | failed | unknown
    files: list[TaskStatus] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_envelope(data: dict[str, Any]) -> dict[str, Any]:
    """Inspect a MinerU response envelope. Raises on auth / api errors.

    Success envelope: ``{"code": 0, "data": {...}, "msg": "ok", "trace_id": "..."}``
    """
    code = data.get("code", 0)
    if code == 0:
        return data.get("data") or {}

    msg = data.get("msg", "unknown error")
    trace_id = data.get("trace_id")

    if code in (401, "A0202", "A0211"):
        raise MinerUAuthError(f"auth error {code}: {msg} (trace_id={trace_id})")
    raise MinerUAPIError(code, msg, trace_id)


def _load_token(token: str | None) -> str:
    if token:
        return token.strip()
    env = os.environ.get("MINERU_TOKEN", "").strip()
    if env:
        return env
    raise MinerUAuthError(
        "No API token provided. Pass `token=` or set MINERU_TOKEN in the env."
    )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class MinerUClient:
    """Synchronous client for the MinerU cloud APIs.

    Parameters
    ----------
    token:
        Bearer token from https://mineru.net/apiManage/token. Required for the
        precise (v4) API; ignored for the agent (v1) API.
    base_url:
        Override the base URL. Useful for staging / proxies.
    timeout:
        Per-request timeout in seconds for the HTTP session.
    session:
        Optional pre-configured ``requests.Session``.
    """

    def __init__(
        self,
        token: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 60.0,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._token: str | None = token.strip() if token else None
        self._session = session or requests.Session()
        self._session.headers.setdefault("User-Agent", "mineru-python-client/0.1")

    # -- HTTP plumbing --------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        if self._token is None:
            self._token = _load_token(None)
        return {"Authorization": f"Bearer {self._token}"}

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        resp = self._session.get(url, params=params or None, headers=self._auth_headers(), timeout=60)
        return self._parse(resp)

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        resp = self._session.post(
            url,
            headers={**self._auth_headers(), "Content-Type": "application/json"},
            data=json.dumps(body),
            timeout=60,
        )
        return self._parse(resp)

    @staticmethod
    def _parse(resp: requests.Response) -> dict[str, Any]:
        try:
            data = resp.json()
        except ValueError as exc:
            raise MinerUAPIError(
                resp.status_code, f"non-JSON response: {resp.text[:200]}"
            ) from exc

        if resp.status_code == 401:
            raise MinerUAuthError(f"HTTP 401: {data.get('msg', 'unauthorized')}")
        if resp.status_code == 429:
            raise MinerUAPIError(429, "rate limited")
        if not resp.ok and "code" not in data:
            raise MinerUAPIError(resp.status_code, data.get("msg") or resp.text[:200])
        return data

    # -- Precise API (v4) -----------------------------------------------

    def submit_url(
        self,
        url: str,
        *,
        is_ocr: bool = False,
        enable_formula: bool = True,
        enable_table: bool = True,
        language: str = "ch",
        data_id: str | None = None,
        callback: str | None = None,
        seed: str | None = None,
        extra_formats: list[str] | None = None,
        page_ranges: str | None = None,
        model_version: str = "pipeline",
        no_cache: bool = False,
        cache_tolerance: int | None = None,
    ) -> str:
        """Submit a single PDF by URL. Returns the ``task_id``."""
        body: dict[str, Any] = {
            "url": url,
            "is_ocr": is_ocr,
            "enable_formula": enable_formula,
            "enable_table": enable_table,
            "language": language,
            "model_version": model_version,
            "no_cache": no_cache,
        }
        if data_id is not None:
            body["data_id"] = data_id
        if callback is not None:
            body["callback"] = callback
        if seed is not None:
            body["seed"] = seed
        if extra_formats is not None:
            body["extra_formats"] = extra_formats
        if page_ranges is not None:
            body["page_ranges"] = page_ranges
        if cache_tolerance is not None:
            body["cache_tolerance"] = cache_tolerance

        data = _check_envelope(self._post(PRECISE_PATH, body))
        return data["task_id"]

    def submit_batch(self, files: list[dict[str, Any]]) -> str:
        """Submit a batch where each file is referenced by ``url``.

        Each item in ``files`` must contain at least ``name`` and ``url``.
        Returns the ``batch_id``.
        """
        if not files:
            raise MinerUFileError("files must not be empty")
        if len(files) > MAX_BATCH_FILES:
            raise MinerUFileError(f"batch exceeds {MAX_BATCH_FILES} files")
        body = {"files": files}
        data = _check_envelope(self._post(PRECISE_BATCH_PATH, body))
        return data["batch_id"]

    def get_task(self, task_id: str) -> TaskStatus:
        data = _check_envelope(self._get(PRECISE_TASK_PATH.format(task_id=task_id)))
        progress = data.get("extract_progress")
        return TaskStatus(
            task_id=data.get("task_id", task_id),
            state=data.get("state", "unknown"),
            full_zip_url=data.get("full_zip_url"),
            err_msg=data.get("err_msg"),
            data_id=data.get("data_id"),
            progress=progress,
            raw=data,
        )

    def get_batch(self, batch_id: str) -> BatchStatus:
        data = _check_envelope(
            self._get(PRECISE_BATCH_RESULT_PATH.format(batch_id=batch_id))
        )
        items = data.get("extract_result") or data.get("results") or []
        files = [
            TaskStatus(
                task_id=item.get("task_id", ""),
                state=item.get("state", "unknown"),
                full_zip_url=item.get("full_zip_url"),
                err_msg=item.get("err_msg"),
                data_id=item.get("data_id"),
                progress=item.get("extract_progress"),
                raw=item,
            )
            for item in items
        ]
        # Aggregate: done if every file done; failed if any failed and none
        # still running; running otherwise.
        if not files:
            agg = "unknown"
        elif all(f.is_done for f in files):
            agg = PRECISE_DONE
        elif any(f.is_failed for f in files) and not any(
            f.state in PRECISE_RUNNING_STATES for f in files
        ):
            agg = PRECISE_FAILED
        else:
            agg = "running"
        return BatchStatus(batch_id=batch_id, state=agg, files=files, raw=data)

    def wait_for_task(
        self,
        task_id: str,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_TIMEOUT,
        on_poll: callable | None = None,
    ) -> TaskStatus:
        """Poll a task until it reaches a terminal state."""
        deadline = time.monotonic() + timeout
        while True:
            status = self.get_task(task_id)
            if on_poll is not None:
                on_poll(status)
            if status.is_done:
                return status
            if status.is_failed:
                raise MinerUAPIError(
                    -1, status.err_msg or "task failed", trace_id=None
                )
            if time.monotonic() > deadline:
                raise MinerUTimeoutError(
                    f"task {task_id} did not finish within {timeout}s"
                )
            time.sleep(poll_interval)

    def wait_for_batch(
        self,
        batch_id: str,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_TIMEOUT,
        on_poll: callable | None = None,
    ) -> BatchStatus:
        deadline = time.monotonic() + timeout
        while True:
            status = self.get_batch(batch_id)
            if on_poll is not None:
                on_poll(status)
            if status.state in (PRECISE_DONE, PRECISE_FAILED):
                return status
            if time.monotonic() > deadline:
                raise MinerUTimeoutError(
                    f"batch {batch_id} did not finish within {timeout}s"
                )
            time.sleep(poll_interval)

    # -- Agent API (v1, lightweight) ------------------------------------

    def agent_submit_url(
        self,
        url: str,
        *,
        file_name: str | None = None,
        language: str = "ch",
        enable_table: bool = True,
        is_ocr: bool = False,
        enable_formula: bool = True,
        page_range: str | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "url": url,
            "language": language,
            "enable_table": enable_table,
            "is_ocr": is_ocr,
            "enable_formula": enable_formula,
        }
        if file_name is not None:
            body["file_name"] = file_name
        if page_range is not None:
            body["page_range"] = page_range

        # Agent API is unauthenticated.
        resp = self._session.post(
            f"{self.base_url}{AGENT_URL_PATH}",
            headers={"Content-Type": "application/json"},
            data=json.dumps(body),
            timeout=60,
        )
        data = self._parse(resp)
        if data.get("code", 0) != 0:
            raise MinerUAPIError(data.get("code", -1), data.get("msg", "agent error"))
        return data["data"]["task_id"]

    def agent_get_task(self, task_id: str) -> TaskStatus:
        resp = self._session.get(
            f"{self.base_url}{AGENT_RESULT_PATH.format(task_id=task_id)}", timeout=60
        )
        data = self._parse(resp)
        inner = data.get("data") or {}
        return TaskStatus(
            task_id=inner.get("task_id", task_id),
            state=inner.get("state", "unknown"),
            markdown_url=inner.get("markdown_url"),
            err_msg=inner.get("err_msg"),
            err_code=inner.get("err_code"),
            raw=inner,
        )

    def agent_wait_for_task(
        self,
        task_id: str,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_TIMEOUT,
        on_poll: callable | None = None,
    ) -> TaskStatus:
        deadline = time.monotonic() + timeout
        while True:
            status = self.agent_get_task(task_id)
            if on_poll is not None:
                on_poll(status)
            if status.is_done:
                return status
            if status.is_failed:
                raise MinerUAPIError(
                    status.err_code or -1, status.err_msg or "agent task failed"
                )
            if time.monotonic() > deadline:
                raise MinerUTimeoutError(
                    f"agent task {task_id} did not finish within {timeout}s"
                )
            time.sleep(poll_interval)

    # -- Download helpers ----------------------------------------------

    @staticmethod
    def download_zip(zip_url: str, save_path: str | os.PathLike) -> Path:
        """Download a result ZIP from a presigned URL."""
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(zip_url, stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(save_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
        return save_path

    @staticmethod
    def extract_zip(zip_path: str | os.PathLike, out_dir: str | os.PathLike) -> list[Path]:
        """Extract a result ZIP into ``out_dir`` and return the file paths."""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(out_dir)
            for name in zf.namelist():
                p = out_dir / name
                if p.is_file():
                    paths.append(p)
        return paths

    @staticmethod
    def download_markdown(markdown_url: str, save_path: str | os.PathLike) -> Path:
        """Download a markdown file (agent API) to ``save_path``."""
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        resp = requests.get(markdown_url, timeout=120)
        resp.raise_for_status()
        save_path.write_text(resp.text, encoding="utf-8")
        return save_path

    # -- Convenience: end-to-end pipeline ------------------------------

    def parse_url(
        self,
        url: str,
        output_dir: str | os.PathLike,
        *,
        model_version: str = "pipeline",
        language: str = "ch",
        enable_formula: bool = True,
        enable_table: bool = True,
        is_ocr: bool = False,
        data_id: str | None = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> list[Path]:
        """Submit, wait, download and extract a single file by URL.

        Returns the list of extracted file paths.
        """
        task_id = self.submit_url(
            url,
            model_version=model_version,
            language=language,
            enable_formula=enable_formula,
            enable_table=enable_table,
            is_ocr=is_ocr,
            data_id=data_id,
        )
        status = self.wait_for_task(
            task_id, poll_interval=poll_interval, timeout=timeout
        )
        if not status.full_zip_url:
            raise MinerUAPIError(-1, "task completed but full_zip_url missing")
        output_dir = Path(output_dir)
        zip_path = self.download_zip(status.full_zip_url, output_dir / f"{task_id}.zip")
        return self.extract_zip(zip_path, output_dir / task_id)

    def parse_urls(
        self,
        items: Iterable[dict[str, Any]],
        output_dir: str | os.PathLike,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> dict[str, list[Path]]:
        """Submit a batch, wait, download and extract each file.

        ``items`` is an iterable of dicts accepted by :meth:`submit_batch`
        (must include ``name`` and ``url``). Returns ``{data_id|name: [paths]}``.
        """
        files = list(items)
        batch_id = self.submit_batch(files)

        def _on_poll(s: BatchStatus) -> None:
            done = sum(1 for f in s.files if f.is_done)
            print(f"  batch {batch_id}: {done}/{len(s.files)} done")

        status = self.wait_for_batch(
            batch_id, poll_interval=poll_interval, timeout=timeout, on_poll=_on_poll
        )
        results: dict[str, list[Path]] = {}
        for f in status.files:
            if f.is_failed or not f.full_zip_url:
                results[f.data_id or f.task_id] = []
                continue
            out_dir = Path(output_dir) / (f.data_id or f.task_id)
            zip_path = self.download_zip(f.full_zip_url, out_dir / "result.zip")
            results[f.data_id or f.task_id] = self.extract_zip(zip_path, out_dir)
        return results


# ---------------------------------------------------------------------------
# Local API (`mineru-api` server)
# ---------------------------------------------------------------------------


LOCAL_DEFAULT_BASE_URL = "http://127.0.0.1:8000"
LOCAL_HEALTH_PATH = "/health"
LOCAL_TASKS_PATH = "/tasks"
LOCAL_TASK_PATH = "/tasks/{task_id}"
LOCAL_TASK_RESULT_PATH = "/tasks/{task_id}/result"
LOCAL_FILE_PARSE_PATH = "/file_parse"

LOCAL_BACKEND_PIPELINE = "pipeline"
LOCAL_BACKEND_VLM = "vlm-engine"
LOCAL_BACKEND_HYBRID = "hybrid-engine"

LOCAL_PENDING = "pending"
LOCAL_PROCESSING = "processing"
LOCAL_COMPLETED = "completed"
LOCAL_FAILED = "failed"
LOCAL_RUNNING_STATES = {LOCAL_PENDING, LOCAL_PROCESSING}


@dataclass
class LocalParseRequest:
    """Form fields for ``POST /tasks`` and ``POST /file_parse``.

    See https://opendatalab.github.io/MinerU/usage/api_server/ for the full
    field list.
    """

    lang_list: list[str] = field(default_factory=lambda: ["ch"])
    backend: str = LOCAL_BACKEND_PIPELINE
    parse_method: str = "auto"
    formula_enable: bool = True
    table_enable: bool = True
    return_md: bool = True
    return_middle_json: bool = True
    return_model_output: bool = False
    return_content_list: bool = False
    return_images: bool = True
    response_format_zip: bool = True
    return_original_file: bool = False
    start_page_id: int = 0
    end_page_id: int | None = None
    server_url: str | None = None  # required for `*-http-client` backends

    def to_form(self) -> dict[tuple[str, str], str]:
        """Serialize to ``requests``-style multipart form fields.

        ``lang_list`` is sent as repeated ``lang_list`` keys (one per element).
        """
        fields: dict[tuple[str, str], str] = {}
        for lang in self.lang_list:
            fields[("lang_list", "")] = lang
        for key, value in (
            ("backend", self.backend),
            ("parse_method", self.parse_method),
            ("formula_enable", str(self.formula_enable).lower()),
            ("table_enable", str(self.table_enable).lower()),
            ("return_md", str(self.return_md).lower()),
            ("return_middle_json", str(self.return_middle_json).lower()),
            ("return_model_output", str(self.return_model_output).lower()),
            ("return_content_list", str(self.return_content_list).lower()),
            ("return_images", str(self.return_images).lower()),
            ("response_format_zip", str(self.response_format_zip).lower()),
            ("return_original_file", str(self.return_original_file).lower()),
            ("start_page_id", str(self.start_page_id)),
        ):
            fields[(key, "")] = value
        if self.end_page_id is not None:
            fields[("end_page_id", "")] = str(self.end_page_id)
        if self.server_url is not None:
            fields[("server_url", "")] = self.server_url
        return fields


class MinerULocalClient:
    """Client for the self-hosted ``mineru-api`` FastAPI server.

    Start the server with::

        pip install "mineru[all]"
        mineru-api --host 0.0.0.0 --port 8000

    Swagger UI: ``http://127.0.0.1:8000/docs``
    OpenAPI:    ``http://127.0.0.1:8000/openapi.json``
    """

    def __init__(
        self,
        *,
        base_url: str = LOCAL_DEFAULT_BASE_URL,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._session = session or requests.Session()
        self._session.headers.setdefault("User-Agent", "mineru-python-client/0.1")

    # -- HTTP plumbing --------------------------------------------------

    def _post_multipart(
        self,
        path: str,
        files: list[tuple[str, tuple[str, io.BufferedReader, str]]],
        form: dict[tuple[str, str], str] | None = None,
    ) -> requests.Response:
        url = f"{self.base_url}{path}"
        return self._session.post(
            url,
            files=files,
            data=form or {},
            timeout=300,
        )

    def _get(self, path: str) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        resp = self._session.get(url, timeout=60)
        resp.raise_for_status()
        return resp.json()

    # -- Server introspection ------------------------------------------

    def health(self) -> dict[str, Any]:
        """Return ``/health`` body (protocol version, concurrency, task counts)."""
        return self._get(LOCAL_HEALTH_PATH)

    # -- File submission ------------------------------------------------

    @staticmethod
    def _open_files(paths: list[str | os.PathLike]) -> list[tuple[str, tuple[str, io.BufferedReader, str]]]:
        """Open files for multipart upload. Caller must close them."""
        out: list[tuple[str, tuple[str, io.BufferedReader, str]]] = []
        for p in paths:
            p = Path(p)
            out.append(
                ("files", (p.name, open(p, "rb"), "application/octet-stream"))
            )
        return out

    def submit_files(
        self,
        paths: list[str | os.PathLike],
        request: LocalParseRequest | None = None,
    ) -> dict[str, Any]:
        """Async submit. Returns the 202 body with ``task_id``, ``status_url``,
        ``result_url``, ``file_names``, ``queued_ahead``."""
        request = request or LocalParseRequest()
        files = self._open_files(paths)
        try:
            resp = self._post_multipart(
                LOCAL_TASKS_PATH, files=files, form=request.to_form()
            )
        finally:
            for _, handle in files:
                handle[1].close()
        resp.raise_for_status()
        return resp.json()

    def get_task(self, task_id: str) -> dict[str, Any]:
        return self._get(LOCAL_TASK_PATH.format(task_id=task_id))

    def wait_for_task(
        self,
        task_id: str,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_TIMEOUT,
        on_poll: callable | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            status = self.get_task(task_id)
            state = status.get("status")
            if on_poll is not None:
                on_poll(status)
            if state == LOCAL_COMPLETED:
                return status
            if state == LOCAL_FAILED:
                raise MinerUAPIError(-1, f"local task {task_id} failed")
            if time.monotonic() > deadline:
                raise MinerUTimeoutError(
                    f"local task {task_id} did not finish within {timeout}s"
                )
            time.sleep(poll_interval)

    def download_result(
        self,
        task_id: str,
        save_path: str | os.PathLike,
    ) -> Path:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"{self.base_url}{LOCAL_TASK_RESULT_PATH.format(task_id=task_id)}"
        with self._session.get(url, stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(save_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
        return save_path

    def parse_file_sync(
        self,
        path: str | os.PathLike,
        output_dir: str | os.PathLike,
        request: LocalParseRequest | None = None,
    ) -> list[Path]:
        """Convenience: POST to ``/file_parse`` (server blocks until done) and
        extract the returned ZIP."""
        request = request or LocalParseRequest()
        files = self._open_files([path])
        try:
            resp = self._post_multipart(
                LOCAL_FILE_PARSE_PATH, files=files, form=request.to_form()
            )
        finally:
            for _, handle in files:
                handle[1].close()
        resp.raise_for_status()
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        zip_path = output_dir / "result.zip"
        zip_path.write_bytes(resp.content)
        return self.extract_zip(zip_path, output_dir)

    def parse_file(
        self,
        path: str | os.PathLike,
        output_dir: str | os.PathLike,
        request: LocalParseRequest | None = None,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> list[Path]:
        """Async: submit, poll, download, extract. Returns the list of files."""
        request = request or LocalParseRequest()
        submit = self.submit_files([path], request)
        task_id = submit["task_id"]

        def _on_poll(s: dict[str, Any]) -> None:
            print(
                f"  task {task_id}: status={s.get('status')} "
                f"queued_ahead={s.get('queued_ahead')}"
            )

        self.wait_for_task(
            task_id, poll_interval=poll_interval, timeout=timeout, on_poll=_on_poll
        )
        output_dir = Path(output_dir)
        zip_path = self.download_result(task_id, output_dir / "result.zip")
        return self.extract_zip(zip_path, output_dir)

    # -- Shared helpers -------------------------------------------------

    @staticmethod
    def extract_zip(zip_path: str | os.PathLike, out_dir: str | os.PathLike) -> list[Path]:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(out_dir)
            for name in zf.namelist():
                p = out_dir / name
                if p.is_file():
                    paths.append(p)
        return paths
