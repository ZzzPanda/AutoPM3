"""Shared helpers for the AutoPM3 Streamlit pages.

The two pages (``app/main.py`` and ``app/pages/2_OpenAI_Compatible.py``) used to ship
byte-for-byte identical copies of ``extract_paper_content`` and
``render_result``. They also wrote user uploads to the process-wide
``tempfile`` directory with ``delete=False``, leaking files forever and
allowing other users on the host to read them if they guessed the path.

This module centralises that logic and gives each Streamlit session its own
scratch directory under ``$TMP/autopm3_sessions/<session_id>/``. The directory
is cleaned up at module load time based on a TTL (default 24h, overridable
via ``AUTOPM3_SESSION_TTL_HOURS``) — Streamlit 1.39 has no native session-end
hook, so TTL-at-startup is the smallest mechanism that keeps the host clean
across restarts.

Helpers exposed:
    get_session_id()             - current Streamlit session id (or "default"
                                   when called outside a Streamlit run, e.g.
                                   from the CLI).
    session_paper_dir(session_id) - absolute path to the session's scratch dir.
    extract_paper_content(file)  - write an upload into the session dir and
                                   return its path; also remembers the path in
                                   ``st.session_state["paper_path"]`` so the
                                   next call from the same session can wipe
                                   the previous upload.
    render_result(result)        - structured-dict → Streamlit expanders.
    run_async_query(async_fn)    - safe ``asyncio.run`` boundary for button
                                   handlers.
    cleanup_old_sessions(...)    - TTL sweep; called once at import.
"""

from __future__ import annotations

import asyncio
import atexit
import os
import shutil
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

# Streamlit is intentionally an optional import so the helpers module can be
# imported (and the cleanup sweep can run) during CLI / tests where Streamlit
# isn't installed or hasn't initialised a script-run context.
try:
    import streamlit as st
    from streamlit.runtime.scriptrunner import get_script_run_ctx
except Exception:  # pragma: no cover - exercised only outside Streamlit
    st = None  # type: ignore[assignment]
    get_script_run_ctx = None  # type: ignore[assignment]


# Root of all per-session scratch directories. Allocated on import so the
# cleanup sweep at the bottom of this file has somewhere to scan.
SESSIONS_ROOT = os.path.join(tempfile.gettempdir(), "autopm3_sessions")


def config_value(env_name: str, secret_name: str, default: str = "") -> str:
    """Read config from env first, then Streamlit secrets if available."""
    env_value = os.getenv(env_name)
    if env_value:
        return env_value
    if st is None:
        return default
    try:
        value = st.secrets.get(secret_name, default)
    except (FileNotFoundError, KeyError):
        return default
    return value if value is not None else default


def get_session_id() -> str:
    """Return the current Streamlit session id, or ``"default"`` otherwise.

    The CLI / tests / non-Streamlit imports all fall through to ``"default"``,
    which means they all share one scratch directory. That's acceptable for
    the CLI because only one process runs at a time, and Streamlit sessions
    each get their own UUID-style id and therefore their own directory.
    """
    if get_script_run_ctx is None:
        return "default"
    try:
        ctx = get_script_run_ctx()
    except Exception:
        return "default"
    if ctx is None:
        return "default"
    return ctx.session_id


def session_paper_dir(session_id: str) -> str:
    """Return (and create) the session-scoped scratch directory.

    ``os.makedirs(..., exist_ok=True)`` is technically racy across processes,
    but the only writer is the user's own session, so the race is harmless —
    the inner ``NamedTemporaryFile`` call uses a unique name anyway.
    """
    path = os.path.join(SESSIONS_ROOT, session_id)
    os.makedirs(path, exist_ok=True)
    return path


def extract_paper_content(paper_file: Any) -> str:
    """Write an uploaded paper into the session's scratch dir and return its path.

    The previous upload from the same session (if any) is deleted first so the
    directory stays lean. The new path is stashed in ``st.session_state`` so
    the next call from this session knows what to clean up.

    When called outside Streamlit, the session_id falls back to ``"default"``
    and the path is not stored in session_state (which doesn't exist).
    """
    session_id = get_session_id()
    paper_dir = session_paper_dir(session_id)

    # Click-time cleanup: delete the previous upload from this session if it
    # lives in the same session dir. We deliberately don't touch files
    # outside the session dir — that's the responsibility of the TTL sweep.
    if st is not None:
        prev = st.session_state.get("paper_path")
        if prev and os.path.exists(prev) and os.path.dirname(prev) == paper_dir:
            try:
                os.unlink(prev)
            except OSError:
                pass

    suffix = os.path.splitext(paper_file.name)[1].lower() or ".xml"
    # Random suffix avoids name collisions when the same session uploads
    # twice in a row (the click-time cleanup above usually handles this, but
    # belt-and-braces in case cleanup fails).
    paper_basename = f"paper_{uuid.uuid4().hex[:8]}{suffix}"
    paper_path = os.path.join(paper_dir, paper_basename)

    with open(paper_path, "wb") as fp:
        fp.write(paper_file.read())

    if st is not None:
        st.session_state["paper_path"] = paper_path

    return paper_path


def render_result(result: Any) -> None:
    """Render a structured result dict as a stack of expandable sections.

    Matches the contract used by the existing pages: result is ``{"title":
    str, "sections": [{"title": str, "body": str}, ...]}``. Anything that
    doesn't match the contract is dumped verbatim as a safety net (matches
    the historical fallback in the page-level copies).
    """
    if st is None:
        return
    if not isinstance(result, dict) or "sections" not in result:
        st.write(result)
        return
    if result.get("title"):
        st.header(result["title"])
    sections = result["sections"]
    evidence = result.get("evidence") if isinstance(result, dict) else None
    if evidence:
        _render_result_with_evidence(
            sections,
            evidence,
            document_markdown=result.get("document_markdown", ""),
        )
        return
    for i, section in enumerate(sections):
        if i > 0:
            st.divider()
        # The expander label is small by default, so we render the title
        # twice: once as the expander label (visible when collapsed, acts
        # as collapse toggle) and once as a big `##` heading inside the
        # expander (visible when expanded). Gives a clear visual
        # hierarchy either way.
        with st.expander(section["title"], expanded=True):
            st.markdown(f"## {section['title']}")
            st.markdown(section["body"])


def _render_evidence_preview(evidence_item: dict[str, Any]) -> None:
    label_bits = [evidence_item.get("title") or evidence_item.get("id", "Evidence")]
    if evidence_item.get("page"):
        label_bits.append(f"page {evidence_item['page']}")
    if evidence_item.get("reason"):
        label_bits.append(evidence_item["reason"])
    st.caption(" · ".join(str(bit) for bit in label_bits if bit))
    st.markdown(
        f"""
        <div style="
            border-left: 4px solid #f97316;
            background: #fff7ed;
            padding: 0.75rem 0.9rem;
            border-radius: 6px;
            margin: 0.5rem 0 1rem 0;
            color: #111827;
            line-height: 1.55;
            overflow-x: auto;
        ">{evidence_item.get("text", "")}</div>
        """,
        unsafe_allow_html=True,
    )


def _render_markdown_document_with_highlight(
    document_markdown: str,
    selected_item: dict[str, Any],
) -> None:
    raw_chunk = selected_item.get("raw_text") or selected_item.get("text") or ""
    anchor_id = "autopm3-selected-chunk"
    if raw_chunk and raw_chunk in document_markdown:
        before, rest = document_markdown.split(raw_chunk, 1)
        _, after = rest[: len(raw_chunk)], rest[len(raw_chunk):]
        if before.strip():
            with st.expander("Content before selected chunk", expanded=False):
                st.markdown(before, unsafe_allow_html=True)
        st.markdown(f'<div id="{anchor_id}"></div>', unsafe_allow_html=True)
        _render_evidence_preview({**selected_item, "text": raw_chunk})
        if after.strip():
            st.markdown(after, unsafe_allow_html=True)
        return

    st.markdown(document_markdown, unsafe_allow_html=True)


def _render_result_with_evidence(
    sections: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    document_markdown: str = "",
) -> None:
    ordered_evidence = [
        item
        for item in evidence
        if isinstance(item, dict) and item.get("id")
    ]
    evidence_by_id = {item["id"]: item for item in ordered_evidence}
    if not evidence_by_id:
        st.info("No linked chunks were returned for this result.")
        return

    selected_key = "autopm3_selected_evidence_id"
    if st.session_state.get(selected_key) not in evidence_by_id:
        st.session_state[selected_key] = ordered_evidence[0]["id"]

    st.markdown(
        """
        <style>
        .autopm3-workbench-note {
            color: #6b7280;
            font-size: 0.9rem;
            margin-top: -0.5rem;
            margin-bottom: 0.75rem;
        }
        [data-testid="stVerticalBlockBorderWrapper"] table {
            border-collapse: collapse;
            display: block;
            overflow-x: auto;
            white-space: nowrap;
            width: 100%;
        }
        [data-testid="stVerticalBlockBorderWrapper"] th,
        [data-testid="stVerticalBlockBorderWrapper"] td {
            border: 1px solid #d1d5db;
            padding: 0.35rem 0.5rem;
            vertical-align: top;
        }
        [data-testid="stVerticalBlockBorderWrapper"] tr:nth-child(even) {
            background: #f9fafb;
        }
        </style>
        <div class="autopm3-workbench-note">
        Conclusions on the left are linked to source chunks on the right.
        </div>
        """,
        unsafe_allow_html=True,
    )

    left, gutter, right = st.columns([0.95, 0.035, 1.05], gap="large")

    with left:
        st.subheader("Conclusions")
        for i, section in enumerate(sections):
            evidence_ids = [
                evidence_id
                for evidence_id in section.get("evidence_ids", [])
                if evidence_id in evidence_by_id
            ]
            label = section["title"]
            if evidence_ids:
                label = f"{label} · {len(evidence_ids)} chunk(s)"
            with st.expander(label, expanded=True):
                st.markdown(f"### {section['title']}")
                st.markdown(section["body"])
                if evidence_ids:
                    st.caption("Linked source chunks")
                    button_cols = st.columns(min(4, len(evidence_ids)))
                    for j, evidence_id in enumerate(evidence_ids):
                        item = evidence_by_id[evidence_id]
                        chunk_label = item.get("title") or evidence_id
                        if item.get("page"):
                            chunk_label = f"{chunk_label} p.{item['page']}"
                        with button_cols[j % len(button_cols)]:
                            selected = st.session_state[selected_key] == evidence_id
                            if st.button(
                                f"{'Selected: ' if selected else ''}{chunk_label}",
                                key=f"evidence-link-{i}-{j}-{evidence_id}",
                                type="primary" if selected else "secondary",
                                use_container_width=True,
                                on_click=lambda value=evidence_id: st.session_state.__setitem__(
                                    selected_key,
                                    value,
                                ),
                            ):
                                pass

    with gutter:
        st.markdown(
            """
            <div style="
                min-height: 720px;
                border-left: 1px solid #d1d5db;
                margin: 0.25rem auto;
            "></div>
            """,
            unsafe_allow_html=True,
        )

    with right:
        st.subheader("Markdown Source")
        option_ids = [item["id"] for item in ordered_evidence]
        selected_index = option_ids.index(st.session_state[selected_key])
        selected_id = st.selectbox(
            "Current chunk",
            option_ids,
            index=selected_index,
            format_func=lambda evidence_id: evidence_by_id[evidence_id].get("title") or evidence_id,
        )
        st.session_state[selected_key] = selected_id
        selected_item = evidence_by_id[selected_id]
        related_sections = [
            section["title"]
            for section in sections
            if selected_id in section.get("evidence_ids", [])
        ]
        if related_sections:
            st.caption("Linked conclusions: " + " / ".join(related_sections))
        st.markdown("#### Full Markdown")
        document_view = st.container(height=760, border=True)
        with document_view:
            if document_markdown:
                _render_markdown_document_with_highlight(document_markdown, selected_item)
            else:
                st.info("The full Markdown document is not available for this result.")

        with st.expander("All chunks", expanded=False):
            for item in ordered_evidence:
                title = item.get("title") or item["id"]
                if item.get("page"):
                    title = f"{title} · page {item['page']}"
                st.markdown(f"**{title}**")
                st.caption(item.get("reason", ""))
                st.write((item.get("text") or "")[:420])


def run_async_query(async_fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run an async coroutine factory from a synchronous Streamlit handler.

    ``asyncio.run`` creates a fresh event loop, runs the coroutine to
    completion, then closes the loop. That's the right thing for a button
    click — we want a clean loop per request, no leftover tasks.

    Defensive fallback: if we're somehow already inside a running event
    loop (Streamlit 1.39 doesn't do this, but a future version might),
    ``asyncio.run`` would raise. In that case we run the coroutine in a
    fresh thread with its own loop, which adds ~100ms but is correct.
    """
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    if running is None:
        return asyncio.run(async_fn(*args, **kwargs))

    # Already in a loop — fall back to a worker thread with a fresh loop.
    def _runner() -> Any:
        return asyncio.run(async_fn(*args, **kwargs))

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="autopm3-async") as ex:
        return ex.submit(_runner).result()


# ---------------------------------------------------------------------------
# TTL cleanup
# ---------------------------------------------------------------------------

# Default: anything older than 24h is reaped at module load. Long enough that
# active sessions are safe across short-lived server restarts, short enough
# that a forgotten tab doesn't pin a paper forever.
_SESSION_TTL_SECONDS = int(os.getenv("AUTOPM3_SESSION_TTL_HOURS", "24")) * 3600


def cleanup_old_sessions(max_age_seconds: int = _SESSION_TTL_SECONDS) -> int:
    """Delete session dirs in ``SESSIONS_ROOT`` older than ``max_age_seconds``.

    Called once at module import. Returns the number of dirs deleted (useful
    for tests, otherwise ignored). Errors during scan are swallowed so a
    half-dead tmpfs can't crash the import.
    """
    if not os.path.isdir(SESSIONS_ROOT):
        return 0
    cutoff = time.time() - max_age_seconds
    deleted = 0
    try:
        with os.scandir(SESSIONS_ROOT) as it:
            for entry in it:
                if not entry.is_dir():
                    continue
                try:
                    mtime = entry.stat(follow_symlinks=False).st_mtime
                except OSError:
                    continue
                if mtime < cutoff:
                    try:
                        shutil.rmtree(entry.path, ignore_errors=True)
                        deleted += 1
                    except OSError:
                        continue
    except OSError:
        return deleted
    return deleted


# Best-effort cleanup on interpreter exit too — catches the case where
# Streamlit hot-reloads the module without re-running this top-level code.
# ``atexit`` is a no-op if the module is being garbage-collected normally.
@atexit.register
def _atexit_cleanup() -> None:
    try:
        cleanup_old_sessions()
    except Exception:
        pass
