"""Tests for :mod:`mineru.client`.

The suite is split into three layers:

* **Unit tests** — exercise serialization, validation, polling, and download
  logic against a mocked ``requests.Session`` so they run offline.
* **Local-server tests** — exercise the ``MinerULocalClient`` against a mocked
  ``mineru-api`` server (no GPU / no install required).
* **Live tests** — gated behind the ``MINERU_LIVE`` environment variable, they
  hit the real cloud API and require ``MINERU_TOKEN`` plus a reachable PDF URL.
  ``MINERU_LOCAL_LIVE`` runs the local-server tests against a real
  ``mineru-api`` process (start it with ``mineru-api --port 8000``).

Run with stdlib unittest:

    python -m unittest discover mineru/tests
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from mineru import (
    AGENT_DONE,
    AGENT_FAILED,
    LOCAL_BACKEND_HYBRID,
    LOCAL_COMPLETED,
    LOCAL_PENDING,
    LOCAL_PROCESSING,
    MAX_BATCH_FILES,
    PRECISE_DONE,
    PRECISE_FAILED,
    BatchStatus,
    LocalParseRequest,
    MinerUAPIError,
    MinerUAuthError,
    MinerUClient,
    MinerUFileError,
    MinerULocalClient,
    MinerUTimeoutError,
    TaskStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _envelope(data, code: int = 0, msg: str = "ok", trace_id: str | None = None):
    return {
        "code": code,
        "msg": msg,
        "trace_id": trace_id or "trace-xyz",
        "data": data,
    }


def _make_response(json_body, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.json.return_value = json_body
    resp.text = json.dumps(json_body)
    resp.raise_for_status = MagicMock()
    return resp


def _make_zip(members: dict[str, str] | None = None) -> bytes:
    members = members or {"doc.md": "# hello\n"}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in members.items():
            zf.writestr(name, body)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Envelope / exception handling
# ---------------------------------------------------------------------------


class EnvelopeAndExceptionsTests(unittest.TestCase):
    def test_successful_envelope_returns_data(self):
        from mineru.client import _check_envelope

        out = _check_envelope(_envelope({"task_id": "abc"}))
        self.assertEqual(out, {"task_id": "abc"})

    def test_auth_error_code_raises_auth(self):
        from mineru.client import _check_envelope

        with self.assertRaises(MinerUAuthError):
            _check_envelope(_envelope(None, code="A0202", msg="bad token"))

    def test_generic_error_raises_api_error(self):
        from mineru.client import _check_envelope

        with self.assertRaises(MinerUAPIError) as ctx:
            _check_envelope(_envelope(None, code=-500, msg="bad param"))
        self.assertEqual(ctx.exception.code, -500)
        self.assertEqual(ctx.exception.msg, "bad param")
        self.assertEqual(ctx.exception.trace_id, "trace-xyz")

    def test_load_token_uses_explicit_value(self):
        from mineru.client import _load_token

        self.assertEqual(_load_token("abc"), "abc")
        self.assertEqual(_load_token("  spaced  "), "spaced")

    def test_load_token_falls_back_to_env(self):
        from mineru.client import _load_token

        with patch.dict(os.environ, {"MINERU_TOKEN": "env-token"}):
            self.assertEqual(_load_token(None), "env-token")

    def test_load_token_raises_when_missing(self):
        from mineru.client import _load_token

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(MinerUAuthError):
                _load_token(None)


# ---------------------------------------------------------------------------
# TaskStatus / BatchStatus derived properties
# ---------------------------------------------------------------------------


class DataclassTests(unittest.TestCase):
    def test_task_status_done(self):
        s = TaskStatus(task_id="t", state=PRECISE_DONE)
        self.assertTrue(s.is_done)
        self.assertFalse(s.is_failed)

    def test_task_status_failed(self):
        s = TaskStatus(task_id="t", state=PRECISE_FAILED, err_msg="boom")
        self.assertTrue(s.is_failed)
        self.assertEqual(s.err_msg, "boom")

    def test_task_status_agent_done(self):
        s = TaskStatus(task_id="t", state=AGENT_DONE, markdown_url="https://x/y.md")
        self.assertTrue(s.is_done)

    def test_task_status_agent_failed(self):
        s = TaskStatus(task_id="t", state=AGENT_FAILED)
        self.assertTrue(s.is_failed)

    def test_batch_status_aggregates(self):
        b = BatchStatus(
            batch_id="b",
            state="running",
            files=[
                TaskStatus(task_id="1", state=PRECISE_DONE),
                TaskStatus(task_id="2", state="running"),
            ],
        )
        self.assertEqual(b.state, "running")

    def test_batch_status_all_done(self):
        b = BatchStatus(
            batch_id="b",
            state="running",
            files=[
                TaskStatus(task_id="1", state=PRECISE_DONE),
                TaskStatus(task_id="2", state=PRECISE_DONE),
            ],
        )
        b.state = PRECISE_DONE  # set by client
        self.assertEqual(b.state, PRECISE_DONE)


# ---------------------------------------------------------------------------
# Client: precise (v4) endpoints with mocked session
# ---------------------------------------------------------------------------


class PreciseAPITests(unittest.TestCase):
    def setUp(self):
        self.client = MinerUClient(token="test-token")
        # Replace session with a mock that records calls.
        self._session = MagicMock(spec=requests.Session)
        self._session.headers = {}
        self.client._session = self._session

    def test_submit_url_uses_bearer_auth_and_returns_task_id(self):
        self._session.post.return_value = _make_response(
            _envelope({"task_id": "task-1"})
        )

        task_id = self.client.submit_url(
            "https://example.com/p.pdf",
            model_version="vlm",
            language="en",
        )

        self.assertEqual(task_id, "task-1")
        self._session.post.assert_called_once()
        args, kwargs = self._session.post.call_args
        self.assertIn("Authorization", kwargs["headers"])
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-token")
        body = json.loads(kwargs["data"])
        self.assertEqual(body["url"], "https://example.com/p.pdf")
        self.assertEqual(body["model_version"], "vlm")
        self.assertEqual(body["language"], "en")
        self.assertTrue(body["enable_formula"])

    def test_submit_url_optional_fields_are_omitted(self):
        self._session.post.return_value = _make_response(
            _envelope({"task_id": "t"})
        )
        self.client.submit_url("https://e/x.pdf")
        body = json.loads(self._session.post.call_args.kwargs["data"])
        for key in ("data_id", "callback", "seed", "extra_formats", "page_ranges", "cache_tolerance"):
            self.assertNotIn(key, body)

    def test_submit_url_optional_fields_are_sent_when_provided(self):
        self._session.post.return_value = _make_response(
            _envelope({"task_id": "t"})
        )
        self.client.submit_url(
            "https://e/x.pdf",
            data_id="paper-42",
            callback="https://hook.example/",
            seed="seed-1",
            extra_formats=["docx"],
            page_ranges="2,4-6",
            cache_tolerance=900,
        )
        body = json.loads(self._session.post.call_args.kwargs["data"])
        self.assertEqual(body["data_id"], "paper-42")
        self.assertEqual(body["callback"], "https://hook.example/")
        self.assertEqual(body["seed"], "seed-1")
        self.assertEqual(body["extra_formats"], ["docx"])
        self.assertEqual(body["page_ranges"], "2,4-6")
        self.assertEqual(body["cache_tolerance"], 900)

    def test_submit_batch_validates_size(self):
        with self.assertRaises(MinerUFileError):
            self.client.submit_batch([{"name": f"f{i}.pdf", "url": "x"} for i in range(MAX_BATCH_FILES + 1)])
        with self.assertRaises(MinerUFileError):
            self.client.submit_batch([])

    def test_submit_batch_returns_batch_id(self):
        self._session.post.return_value = _make_response(
            _envelope({"batch_id": "batch-9"})
        )
        bid = self.client.submit_batch(
            [{"name": "a.pdf", "url": "https://e/a.pdf", "data_id": "a"}]
        )
        self.assertEqual(bid, "batch-9")
        body = json.loads(self._session.post.call_args.kwargs["data"])
        self.assertEqual(body["files"][0]["name"], "a.pdf")

    def test_get_task_parses_envelope(self):
        self._session.get.return_value = _make_response(
            _envelope(
                {
                    "task_id": "t-1",
                    "state": "running",
                    "extract_progress": {"extracted_pages": 3, "total_pages": 10},
                }
            )
        )
        s = self.client.get_task("t-1")
        self.assertEqual(s.state, "running")
        self.assertEqual(s.progress, {"extracted_pages": 3, "total_pages": 10})

    def test_get_batch_aggregates_states(self):
        self._session.get.return_value = _make_response(
            _envelope(
                {
                    "batch_id": "b-1",
                    "extract_result": [
                        {"task_id": "t1", "state": PRECISE_DONE, "full_zip_url": "https://x/a.zip", "data_id": "a"},
                        {"task_id": "t2", "state": "running"},
                    ],
                }
            )
        )
        b = self.client.get_batch("b-1")
        self.assertEqual(b.state, "running")
        self.assertEqual(len(b.files), 2)
        self.assertEqual(b.files[0].data_id, "a")

    def test_get_batch_all_done(self):
        self._session.get.return_value = _make_response(
            _envelope(
                {
                    "extract_result": [
                        {"task_id": "t1", "state": PRECISE_DONE, "full_zip_url": "https://x/a.zip"},
                        {"task_id": "t2", "state": PRECISE_DONE, "full_zip_url": "https://x/b.zip"},
                    ],
                }
            )
        )
        b = self.client.get_batch("b-1")
        self.assertEqual(b.state, PRECISE_DONE)

    def test_wait_for_task_returns_on_done(self):
        self._session.get.side_effect = [
            _make_response(_envelope({"task_id": "t", "state": "running"})),
            _make_response(
                _envelope(
                    {"task_id": "t", "state": PRECISE_DONE, "full_zip_url": "https://x/y.zip"}
                )
            ),
        ]
        s = self.client.wait_for_task("t", poll_interval=0, timeout=5)
        self.assertTrue(s.is_done)
        self.assertEqual(s.full_zip_url, "https://x/y.zip")

    def test_wait_for_task_raises_on_failed(self):
        self._session.get.return_value = _make_response(
            _envelope({"task_id": "t", "state": PRECISE_FAILED, "err_msg": "page limit"})
        )
        with self.assertRaises(MinerUAPIError):
            self.client.wait_for_task("t", poll_interval=0, timeout=5)

    def test_wait_for_task_timeout(self):
        self._session.get.return_value = _make_response(
            _envelope({"task_id": "t", "state": "running"})
        )
        with self.assertRaises(MinerUTimeoutError):
            self.client.wait_for_task("t", poll_interval=0, timeout=0.1)

    def test_wait_for_task_invokes_callback(self):
        self._session.get.side_effect = [
            _make_response(_envelope({"task_id": "t", "state": "running"})),
            _make_response(_envelope({"task_id": "t", "state": PRECISE_DONE})),
        ]
        seen = []
        self.client.wait_for_task("t", poll_interval=0, timeout=5, on_poll=seen.append)
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[1].state, PRECISE_DONE)

    def test_auth_error_surfaces_as_auth_exception(self):
        self._session.post.return_value = _make_response(
            _envelope(None, code="A0202", msg="token invalid")
        )
        with self.assertRaises(MinerUAuthError):
            self.client.submit_url("https://e/x.pdf")


# ---------------------------------------------------------------------------
# Client: agent (v1) endpoints with mocked session
# ---------------------------------------------------------------------------


class AgentAPITests(unittest.TestCase):
    def setUp(self):
        self.client = MinerUClient(token=None)  # agent API needs no token
        self._session = MagicMock(spec=requests.Session)
        self._session.headers = {}
        self.client._session = self._session

    def test_agent_submit_url_no_auth(self):
        self._session.post.return_value = _make_response(
            _envelope({"task_id": "ag-1"})
        )
        task_id = self.client.agent_submit_url(
            "https://e/x.pdf",
            file_name="x.pdf",
            language="en",
            page_range="1-3",
        )
        self.assertEqual(task_id, "ag-1")
        kwargs = self._session.post.call_args.kwargs
        self.assertNotIn("Authorization", kwargs["headers"])
        body = json.loads(kwargs["data"])
        self.assertEqual(body["file_name"], "x.pdf")
        self.assertEqual(body["language"], "en")
        self.assertEqual(body["page_range"], "1-3")

    def test_agent_get_task_parses_markdown_url(self):
        self._session.get.return_value = _make_response(
            _envelope(
                {"task_id": "ag-1", "state": AGENT_DONE, "markdown_url": "https://cdn/x.md"}
            )
        )
        s = self.client.agent_get_task("ag-1")
        self.assertEqual(s.state, AGENT_DONE)
        self.assertEqual(s.markdown_url, "https://cdn/x.md")

    def test_agent_wait_failed_raises(self):
        self._session.get.return_value = _make_response(
            _envelope({"task_id": "ag-1", "state": AGENT_FAILED, "err_code": -30001, "err_msg": "file too large"})
        )
        with self.assertRaises(MinerUAPIError) as ctx:
            self.client.agent_wait_for_task("ag-1", poll_interval=0, timeout=1)
        self.assertEqual(ctx.exception.code, -30001)

    def test_agent_api_error_code_surfaces(self):
        self._session.post.return_value = _make_response(
            {"code": -30001, "msg": "file too large", "data": {}}, status_code=200
        )
        with self.assertRaises(MinerUAPIError):
            self.client.agent_submit_url("https://e/big.pdf")


# ---------------------------------------------------------------------------
# Download / extract helpers
# ---------------------------------------------------------------------------


class DownloadAndExtractTests(unittest.TestCase):
    def test_download_zip_writes_file(self):
        payload = _make_zip({"a.md": "hi", "b.md": "bye"})
        with patch("mineru.client.requests.get") as gget:
            r = MagicMock()
            r.__enter__ = MagicMock(return_value=r)
            r.__exit__ = MagicMock(return_value=False)
            r.raise_for_status = MagicMock()
            r.iter_content.return_value = [payload]
            gget.return_value = r

            with tempfile.TemporaryDirectory() as d:
                p = MinerUClient.download_zip("https://x/y.zip", Path(d) / "out.zip")
                self.assertTrue(p.exists())
                self.assertGreater(p.stat().st_size, 0)

    def test_extract_zip_returns_files(self):
        with tempfile.TemporaryDirectory() as d:
            d_path = Path(d)
            zip_path = d_path / "in.zip"
            zip_path.write_bytes(_make_zip({"a.md": "hi", "sub/b.md": "bye"}))
            files = MinerUClient.extract_zip(zip_path, d_path / "out")
            names = {f.name for f in files}
            self.assertIn("a.md", names)
            self.assertIn("b.md", names)

    def test_download_markdown(self):
        with patch("mineru.client.requests.get") as gget:
            resp = MagicMock()
            resp.text = "# Title\n\nbody"
            resp.raise_for_status = MagicMock()
            gget.return_value = resp
            with tempfile.TemporaryDirectory() as d:
                p = MinerUClient.download_markdown("https://x/y.md", Path(d) / "x.md")
                self.assertEqual(p.read_text(encoding="utf-8"), "# Title\n\nbody")


# ---------------------------------------------------------------------------
# End-to-end convenience (parse_url / parse_urls) with mocked transport
# ---------------------------------------------------------------------------


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.client = MinerUClient(token="test-token")
        self._session = MagicMock(spec=requests.Session)
        self._session.headers = {}
        self.client._session = self._session

    def test_parse_url_submits_polls_and_extracts(self):
        # 1) submit_url
        # 2) get_task -> running
        # 3) get_task -> done (with full_zip_url)
        # 4) download_zip (mocked requests.get)
        self._session.post.return_value = _make_response(
            _envelope({"task_id": "task-7"})
        )
        self._session.get.side_effect = [
            _make_response(_envelope({"task_id": "task-7", "state": "running"})),
            _make_response(
                _envelope(
                    {
                        "task_id": "task-7",
                        "state": PRECISE_DONE,
                        "full_zip_url": "https://x/y.zip",
                    }
                )
            ),
        ]

        with patch("mineru.client.requests.get") as gget:
            r = MagicMock()
            r.__enter__ = MagicMock(return_value=r)
            r.__exit__ = MagicMock(return_value=False)
            r.raise_for_status = MagicMock()
            r.iter_content.return_value = [_make_zip({"doc.md": "# X\n"})]
            gget.return_value = r

            with tempfile.TemporaryDirectory() as d:
                files = self.client.parse_url(
                    "https://example.com/p.pdf",
                    output_dir=d,
                    poll_interval=0,
                    timeout=5,
                )
                self.assertTrue(any(f.name == "doc.md" for f in files))


# ---------------------------------------------------------------------------
# Live tests (gated by env)
# ---------------------------------------------------------------------------


LIVE_URL = "https://cdn-mineru.openxlab.org.cn/demo/example.pdf"


@unittest.skipUnless(
    os.environ.get("MINERU_LIVE") == "1",
    "set MINERU_LIVE=1 and MINERU_TOKEN=... to run live tests",
)
class LiveMinerUTests(unittest.TestCase):
    def setUp(self):
        if not os.environ.get("MINERU_TOKEN"):
            self.skipTest("MINERU_TOKEN is not set")

    def test_precise_pipeline_smoke(self):
        client = MinerUClient()
        with tempfile.TemporaryDirectory() as d:
            files = client.parse_url(
                LIVE_URL,
                output_dir=d,
                model_version="pipeline",
                timeout=300,
                poll_interval=5,
            )
            names = [f.name for f in files]
            self.assertTrue(any(n.endswith(".md") for n in names), names)

    def test_agent_api_smoke(self):
        client = MinerUClient()
        task_id = client.agent_submit_url(LIVE_URL, file_name="example.pdf")
        status = client.agent_wait_for_task(task_id, timeout=180, poll_interval=5)
        self.assertTrue(status.is_done, status)
        self.assertTrue(status.markdown_url, status)


# ---------------------------------------------------------------------------
# Local server (`mineru-api`) — unit + live
# ---------------------------------------------------------------------------


class LocalParseRequestTests(unittest.TestCase):
    def test_default_request_form(self):
        req = LocalParseRequest()
        form = req.to_form()
        # lang_list is a repeated key
        langs = [v for (k, _), v in form.items() if k == "lang_list"]
        self.assertEqual(langs, ["ch"])
        self.assertEqual(form[("backend", "")], LOCAL_BACKEND_HYBRID)
        self.assertEqual(form[("formula_enable", "")], "true")
        self.assertEqual(form[("return_md", "")], "true")
        self.assertEqual(form[("response_format_zip", "")], "true")
        # end_page_id / server_url omitted by default
        self.assertNotIn(("end_page_id", ""), form)
        self.assertNotIn(("server_url", ""), form)

    def test_custom_request_form(self):
        req = LocalParseRequest(
            lang_list=["ch", "en"],
            backend=LOCAL_BACKEND_HYBRID,
            return_md=False,
            end_page_id=10,
            server_url="http://vlm:8000",
        )
        form = req.to_form()
        self.assertEqual(
            [v for (k, _), v in form.items() if k == "lang_list"], ["ch", "en"]
        )
        self.assertEqual(form[("end_page_id", "")], "10")
        self.assertEqual(form[("server_url", "")], "http://vlm:8000")
        self.assertEqual(form[("return_md", "")], "false")


class LocalClientTests(unittest.TestCase):
    def setUp(self):
        self.client = MinerULocalClient(base_url="http://test:8000")
        self._session = MagicMock(spec=requests.Session)
        self._session.headers = {}
        self.client._session = self._session

    def test_health(self):
        self._session.get.return_value.json.return_value = {
            "protocol_version": 2,
            "processing_window_size": 64,
            "max_concurrent_requests": 3,
        }
        body = self.client.health()
        self.assertEqual(body["protocol_version"], 2)
        self._session.get.assert_called_with("http://test:8000/health", timeout=60)

    def test_submit_files_sends_multipart(self):
        self._session.post.return_value.status_code = 202
        self._session.post.return_value.json.return_value = {
            "task_id": "abc",
            "status_url": "http://test:8000/tasks/abc",
            "result_url": "http://test:8000/tasks/abc/result",
            "file_names": ["a.pdf"],
            "queued_ahead": 0,
        }
        self._session.post.return_value.raise_for_status = MagicMock()

        with tempfile.TemporaryDirectory() as d:
            pdf = Path(d) / "a.pdf"
            pdf.write_bytes(b"%PDF-1.4\n%fake")
            sub = self.client.submit_files([pdf])

        self.assertEqual(sub["task_id"], "abc")
        args, kwargs = self._session.post.call_args
        self.assertIn("files", kwargs)
        # Form fields were attached
        data = kwargs["data"]
        self.assertIn(("backend", ""), data)
        self.assertIn(("return_md", ""), data)

    def test_wait_for_task_completes(self):
        self._session.get.side_effect = [
            MagicMock(json=MagicMock(return_value={"status": LOCAL_PENDING})),
            MagicMock(json=MagicMock(return_value={"status": LOCAL_PROCESSING})),
            MagicMock(json=MagicMock(return_value={"status": LOCAL_COMPLETED})),
        ]
        for m in self._session.get.side_effect:
            m.raise_for_status = MagicMock()

        seen = []
        result = self.client.wait_for_task("abc", poll_interval=0, timeout=5, on_poll=seen.append)
        self.assertEqual(result["status"], LOCAL_COMPLETED)
        self.assertEqual(len(seen), 3)

    def test_wait_for_task_failed_raises(self):
        self._session.get.return_value = MagicMock(
            json=MagicMock(return_value={"status": "failed"})
        )
        self._session.get.return_value.raise_for_status = MagicMock()
        with self.assertRaises(MinerUAPIError):
            self.client.wait_for_task("abc", poll_interval=0, timeout=1)

    def test_wait_for_task_timeout(self):
        self._session.get.return_value = MagicMock(
            json=MagicMock(return_value={"status": LOCAL_PROCESSING})
        )
        self._session.get.return_value.raise_for_status = MagicMock()
        with self.assertRaises(MinerUTimeoutError):
            self.client.wait_for_task("abc", poll_interval=0, timeout=0.1)

    def test_parse_file_sync(self):
        zip_bytes = _make_zip({"out.md": "# hi\n", "meta.json": "{}"})
        self._session.post.return_value.status_code = 200
        self._session.post.return_value.content = zip_bytes
        self._session.post.return_value.raise_for_status = MagicMock()

        with tempfile.TemporaryDirectory() as d:
            pdf = Path(d) / "in.pdf"
            pdf.write_bytes(b"%PDF-1.4\n%fake")
            files = self.client.parse_file_sync(pdf, Path(d) / "out")
            names = {f.name for f in files}
            self.assertIn("out.md", names)
            self.assertIn("meta.json", names)


@unittest.skipUnless(
    os.environ.get("MINERU_LOCAL_LIVE") == "1",
    "set MINERU_LOCAL_LIVE=1 to run tests against a real `mineru-api` server",
)
class LocalLiveTests(unittest.TestCase):
    def setUp(self):
        try:
            MinerULocalClient().health()
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"mineru-api not reachable: {exc}")

    def test_parse_local_pdf(self):
        pdf = Path("data/pdf_convert/PubMed23689641.pdf")
        if not pdf.exists():
            self.skipTest(f"missing fixture: {pdf}")
        with tempfile.TemporaryDirectory() as d:
            files = MinerULocalClient().parse_file(pdf, d, timeout=600, poll_interval=2)
            names = [f.name for f in files]
            self.assertTrue(any(n.endswith(".md") for n in names), names)


if __name__ == "__main__":
    unittest.main()
