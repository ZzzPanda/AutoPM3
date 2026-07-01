"""
Smoke test for the MinerU Agent (轻量解析) cloud API.

The Agent API is **public** — no token, no signup. It is IP-rate-limited
(429 if you hammer it) and capped at ≤10 MB / ≤20 pages per file. Output
is a single ``markdown_url`` pointing at a CDN-hosted ``.md`` file.

Usage::

    # Use the public demo PDF that MinerU ships for this exact purpose
    python -m app.mineru.examples.test_agent_api

    # Or point at any other public PDF URL
    python -m app.mineru.examples.test_agent_api --url https://example.com/paper.pdf

    # Save the markdown somewhere specific
    python -m app.mineru.examples.test_agent_api --output /tmp/paper.md
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Make the repo root importable so `import app.mineru` works.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.mineru import MinerUClient  # noqa: E402

DEFAULT_URL = "https://cdn-mineru.openxlab.org.cn/demo/example.pdf"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="public PDF URL (default: MinerU's demo PDF)",
    )
    parser.add_argument(
        "--file-name",
        default="example.pdf",
        help="file name sent to the API (cosmetic)",
    )
    parser.add_argument(
        "--language",
        default="ch",
        choices=["ch", "en", "ch_server", "japan", "korean"],
    )
    parser.add_argument(
        "--page-range",
        default=None,
        help='e.g. "1-5" or "2,4-6"',
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="where to save the markdown (default: print first 500 chars)",
    )
    parser.add_argument("--poll-interval", type=float, default=3.0)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args(argv)

    # token=None explicitly: Agent API requires no auth.
    client = MinerUClient(token=None)

    print(f"[1/3] Submitting URL to Agent API (no auth)")
    print(f"  url:        {args.url}")
    print(f"  file_name:  {args.file_name}")
    print(f"  language:   {args.language}")
    if args.page_range:
        print(f"  page_range: {args.page_range}")

    t0 = time.monotonic()
    task_id = client.agent_submit_url(
        args.url,
        file_name=args.file_name,
        language=args.language,
        page_range=args.page_range,
    )
    print(f"  task_id:    {task_id}")

    print(f"\n[2/3] Polling for completion (interval={args.poll_interval}s)")
    status = client.agent_wait_for_task(
        task_id,
        poll_interval=args.poll_interval,
        timeout=args.timeout,
        on_poll=lambda s: print(
            f"  ... state={s.state} (elapsed {time.monotonic()-t0:.1f}s)"
        ),
    )
    print(f"  state:      {status.state}  ({time.monotonic()-t0:.1f}s)")
    print(f"  markdown:   {status.markdown_url}")

    print(f"\n[3/3] Downloading markdown")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        path = MinerUClient.download_markdown(status.markdown_url, args.output)
        body = path.read_text(encoding="utf-8")
        print(f"  saved:      {path}  ({len(body)} chars)")
        print(f"  head:       {body.splitlines()[0] if body else '(empty)'}")
    else:
        import requests

        body = requests.get(status.markdown_url, timeout=120).text
        print(f"  length:     {len(body)} chars")
        print("  --- first 500 chars ---")
        print(body[:500])
        if len(body) > 500:
            print("  ... (truncated)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
