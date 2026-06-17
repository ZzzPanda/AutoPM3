"""
End-to-end smoke test against ``data/pdf_convert/PubMed23689641.pdf``.

Three modes are demonstrated:

1. **Inspect existing MinerU output** — the repo already has the markdown and
   middle.json from a prior run; we open them to confirm the structure we
   should be producing.

2. **Submit via the local `mineru-api` server** (recommended for local
   testing). Requires `mineru` installed and the server running::

       pip install "mineru[all]"
       mineru-api --host 0.0.0.0 --port 8000

3. **Submit via the cloud precise API** — requires ``MINERU_TOKEN`` and a
   public URL where MinerU can fetch the PDF (the local file path won't
   work; the precise API only accepts URLs). The helper
   ``serve_pdf_locally()`` spins up a one-shot ``http.server`` and prints an
   ngrok-style reminder.

Usage::

    # Default — just inspect the existing artifacts in data/pdf_convert/
    python mineru/examples/test_with_local_pdf.py

    # Local server (requires mineru-api on :8000)
    python mineru/examples/test_with_local_pdf.py --local-server

    # Cloud (requires MINERU_TOKEN)
    MINERU_TOKEN=... python mineru/examples/test_with_local_pdf.py --cloud

    # All three
    python mineru/examples/test_with_local_pdf.py --all
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
from contextlib import contextmanager
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]
PDF_PATH = REPO_ROOT / "data" / "pdf_convert" / "PubMed23689641.pdf"
EXPECTED_MD = REPO_ROOT / "data" / "pdf_convert" / "MinerU_markdown_PubMed23689641_2067159189227929600.md"
EXPECTED_JSON = REPO_ROOT / "data" / "pdf_convert" / "MinerU_PubMed23689641__20260617081534.json"
OUTPUT_ROOT = REPO_ROOT / "mineru" / "examples" / "output"


def step_inspect_existing() -> None:
    """Open the previously generated markdown and JSON."""
    print(f"\n[1/3] Inspecting existing MinerU output for {PDF_PATH.name}")
    if not PDF_PATH.exists():
        print(f"  ! missing fixture: {PDF_PATH}")
        return
    print(f"  PDF:    {PDF_PATH} ({PDF_PATH.stat().st_size / 1024:.1f} KB)")
    if EXPECTED_MD.exists():
        head = EXPECTED_MD.read_text(encoding="utf-8").splitlines()[:5]
        print(f"  MD:     {EXPECTED_MD}  ({len(head)}+ lines)")
        for line in head:
            print(f"    | {line}")
    if EXPECTED_JSON.exists():
        import json

        with EXPECTED_JSON.open() as f:
            data = json.load(f)
        print(
            f"  JSON:   {EXPECTED_JSON}  "
            f"(backend={data.get('_backend')}, version={data.get('_version_name')}, "
            f"pages={len(data.get('pdf_info', []))})"
        )


def step_local_server() -> None:
    """Submit the PDF to a locally running ``mineru-api`` server."""
    print(f"\n[2/3] Submitting to local mineru-api server")
    from mineru import LocalParseRequest, MinerULocalClient

    if not PDF_PATH.exists():
        print(f"  ! missing fixture: {PDF_PATH}")
        return

    client = MinerULocalClient()
    try:
        health = client.health()
        print(f"  server health: {health}")
    except Exception as exc:  # noqa: BLE001
        print(
            f"  ! cannot reach local server: {exc}\n"
            "  start one with:  mineru-api --host 0.0.0.0 --port 8000"
        )
        return

    request = LocalParseRequest(
        lang_list=["ch"],
        return_md=True,
        return_middle_json=True,
        return_images=True,
    )
    out_dir = OUTPUT_ROOT / "local"
    with TemporaryDirectory(dir=out_dir, prefix="run_") as tmp:
        try:
            files = client.parse_file(
                PDF_PATH, tmp, request, poll_interval=2, timeout=600
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ! parse failed: {exc}")
            return
    print(f"  extracted {len(files)} files into {out_dir}")
    for f in files[:8]:
        print(f"    - {f.name}  ({f.stat().st_size} bytes)")
    if len(files) > 8:
        print(f"    ... and {len(files) - 8} more")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def serve_pdf_locally(directory: Path):
    """Serve ``directory`` over HTTP on a random free port (background thread)."""
    directory = directory.resolve()
    port = _free_port()
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    httpd = HTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}/{PDF_PATH.name}", httpd
    finally:
        httpd.shutdown()
        httpd.server_close()


def step_cloud() -> None:
    """Submit via the cloud precise API by serving the PDF locally first."""
    print(f"\n[3/3] Submitting to the cloud precise API")
    from mineru import MinerUClient, MinerUAuthError

    token = os.environ.get("MINERU_TOKEN", "").strip()
    if not token:
        print("  ! MINERU_TOKEN is not set; skipping cloud test")
        return
    if not PDF_PATH.exists():
        print(f"  ! missing fixture: {PDF_PATH}")
        return

    with serve_pdf_locally(PDF_PATH.parent) as (url, _):
        print(f"  serving PDF at {url} (lifetime: this test only)")
        client = MinerUClient(token=token)
        with TemporaryDirectory(dir=OUTPUT_ROOT, prefix="cloud_") as tmp:
            try:
                files = client.parse_url(
                    url,
                    output_dir=tmp,
                    model_version="pipeline",
                    timeout=600,
                    poll_interval=5,
                )
            except MinerUAuthError as exc:
                print(f"  ! auth error: {exc}")
                return
            except Exception as exc:  # noqa: BLE001
                print(f"  ! parse failed: {exc}")
                return
        print(f"  extracted {len(files)} files into {OUTPUT_ROOT}/cloud_*/")
        for f in files[:8]:
            print(f"    - {f.name}  ({f.stat().st_size} bytes)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--all", action="store_true", help="run all three steps")
    g.add_argument(
        "--local-server", action="store_true", help="only run the local server step"
    )
    g.add_argument(
        "--cloud", action="store_true", help="only run the cloud step"
    )
    args = parser.parse_args(argv)

    print(f"Repo root: {REPO_ROOT}")
    print(f"Fixture:   {PDF_PATH}")

    step_inspect_existing()
    if args.all or args.local_server:
        step_local_server()
    if args.all or args.cloud:
        step_cloud()
    if not (args.all or args.local_server or args.cloud):
        # Default: inspect + local server (offline-friendly)
        step_local_server()
    return 0


if __name__ == "__main__":
    sys.exit(main())
