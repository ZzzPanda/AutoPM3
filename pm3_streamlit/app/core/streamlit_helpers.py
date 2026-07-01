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
import html as html_lib
import os
import re
import shutil
import tempfile
import textwrap
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from app.core.model_trace import clear_model_trace, get_model_trace, is_model_trace_enabled

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


def render_result(
    result: Any,
    *,
    section_body_renderer: Callable[[int, dict[str, Any]], None] | None = None,
    key_prefix: str = "autopm3",
) -> None:
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
            section_body_renderer=section_body_renderer,
            key_prefix=key_prefix,
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
            if section_body_renderer is None:
                _render_section_body(section)
            else:
                section_body_renderer(i, section)


def _render_section_body(section: dict[str, Any]) -> None:
    if section.get("style") == "standardized":
        body = html_lib.escape(str(section.get("body", ""))).replace("\n", "<br>")
        st.markdown(
            f"""
            <div style="
                border-left: 5px solid #2563eb;
                background: #eff6ff;
                color: #111827;
                padding: 0.85rem 1rem;
                border-radius: 6px;
                line-height: 1.65;
                margin-bottom: 0.75rem;
            ">{body}</div>
            """,
            unsafe_allow_html=True,
        )
        return
    st.markdown(section.get("body", ""))


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

    _render_evidence_preview(selected_item)
    st.caption(
        "Selected chunk is shown above. It could not be matched back to an exact "
        "position in the full Markdown, so the full document is shown below."
    )
    st.divider()
    st.markdown(document_markdown, unsafe_allow_html=True)


def _render_result_with_evidence(
    sections: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    document_markdown: str = "",
    section_body_renderer: Callable[[int, dict[str, Any]], None] | None = None,
    key_prefix: str = "autopm3",
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

    safe_prefix = re.sub(r"[^A-Za-z0-9_-]+", "-", key_prefix).strip("-") or "autopm3"
    selected_key = f"{safe_prefix}_selected_evidence_id"
    focused_section_key = f"{safe_prefix}_focused_section_id"
    if st.session_state.get(selected_key) not in evidence_by_id:
        st.session_state[selected_key] = ordered_evidence[0]["id"]

    def _select_evidence(evidence_id: str) -> None:
        st.session_state[selected_key] = evidence_id

    def _select_linked_section(section_id: str, evidence_id: str) -> None:
        st.session_state[focused_section_key] = section_id
        st.session_state[selected_key] = evidence_id

    sections_by_id = {
        section["section_id"]: section
        for section in sections
        if isinstance(section, dict) and section.get("section_id")
    }
    standardized_sections = [
        section for section in sections if section.get("style") == "standardized"
    ]
    evidence_sections = [
        section for section in sections if section.get("style") != "standardized"
    ]
    section_index_by_id = {
        section["section_id"]: i
        for i, section in enumerate(sections)
        if isinstance(section, dict) and section.get("section_id")
    }
    section_index_by_object = {
        id(section): i
        for i, section in enumerate(sections)
        if isinstance(section, dict)
    }

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

    def _render_left_section(section: dict[str, Any], i: int) -> None:
        section_key = section.get("section_id") or f"section-{i}"
        is_focused_section = (
            section.get("section_id")
            and st.session_state.get(focused_section_key) == section.get("section_id")
        )
        evidence_ids = [
            evidence_id
            for evidence_id in section.get("evidence_ids", [])
            if evidence_id in evidence_by_id
        ]
        label = section["title"]
        if evidence_ids:
            label = f"{label} · {len(evidence_ids)} chunk(s)"
        if is_focused_section:
            label = f"当前关联证据 · {label}"
        with st.expander(label, expanded=True):
            if is_focused_section:
                st.markdown(
                    """
                    <div style="
                        border-left: 5px solid #16a34a;
                        background: #f0fdf4;
                        color: #14532d;
                        padding: 0.55rem 0.75rem;
                        border-radius: 6px;
                        margin-bottom: 0.75rem;
                        font-weight: 600;
                    ">当前从标准化结论跳转到此证据块；右侧已切换到对应 source chunk。</div>
                    """,
                    unsafe_allow_html=True,
                )
            st.markdown(f"### {section['title']}")
            if section_body_renderer is None:
                _render_section_body(section)
            else:
                section_body_renderer(i, section)
            linked_section_ids = [
                section_id
                for section_id in section.get("linked_section_ids", [])
                if section_id in sections_by_id
            ]
            if linked_section_ids:
                st.caption("关联证据块")
                linked_cols = st.columns(min(4, len(linked_section_ids)))
                for j, linked_section_id in enumerate(linked_section_ids):
                    linked_section = sections_by_id[linked_section_id]
                    linked_evidence_ids = [
                        evidence_id
                        for evidence_id in linked_section.get("evidence_ids", [])
                        if evidence_id in evidence_by_id
                    ]
                    with linked_cols[j % len(linked_cols)]:
                        button_kwargs = {
                            "key": f"{safe_prefix}-section-link-{section_key}-{j}-{linked_section_id}",
                            "type": "secondary",
                            "use_container_width": True,
                            "disabled": not linked_evidence_ids,
                        }
                        if linked_evidence_ids:
                            button_kwargs["on_click"] = _select_linked_section
                            button_kwargs["args"] = (linked_section_id, linked_evidence_ids[0])
                        st.button(linked_section.get("title", linked_section_id), **button_kwargs)
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
                            key=f"{safe_prefix}-evidence-link-{section_key}-{j}-{evidence_id}",
                            type="primary" if selected else "secondary",
                            use_container_width=True,
                            on_click=_select_evidence,
                            args=(evidence_id,),
                        ):
                            pass

    with left:
        if standardized_sections:
            st.subheader("Standardized Conclusion")
            for i, section in enumerate(standardized_sections):
                _render_left_section(section, i)

        st.subheader("Evidence")
        focused_section_id = st.session_state.get(focused_section_key)
        if focused_section_id:
            focused_sections = [
                section
                for section in evidence_sections
                if section.get("section_id") == focused_section_id
            ]
            other_sections = [
                section
                for section in evidence_sections
                if section.get("section_id") != focused_section_id
            ]
            ordered_evidence_sections = focused_sections + other_sections
            focused_section = sections_by_id.get(focused_section_id)
            if focused_section:
                st.caption(f"当前关联证据：{focused_section.get('title', focused_section_id)}")
        else:
            ordered_evidence_sections = evidence_sections
        conclusion_view = st.container(height=760, border=True)
        with conclusion_view:
            for section in ordered_evidence_sections:
                i = section_index_by_id.get(
                    section.get("section_id"),
                    section_index_by_object.get(id(section), 0),
                )
                _render_left_section(section, i)

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
        selected_id = st.session_state[selected_key]
        selected_item = evidence_by_id[selected_id]
        st.subheader("Full Markdown")
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

    clear_model_trace()
    trace_for_session: list[dict[str, Any]] | None = None
    try:
        if running is None:
            return asyncio.run(async_fn(*args, **kwargs))

        # Already in a loop — fall back to a worker thread with a fresh loop.
        def _runner() -> tuple[Any, list[dict[str, Any]], BaseException | None]:
            clear_model_trace()
            try:
                result = asyncio.run(async_fn(*args, **kwargs))
                return result, get_model_trace(), None
            except BaseException as exc:
                return None, get_model_trace(), exc

        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="autopm3-async") as ex:
            result, trace_for_session, exc = ex.submit(_runner).result()
            if exc is not None:
                raise exc
            return result
    finally:
        if st is not None:
            st.session_state["autopm3_model_trace"] = (
                trace_for_session if trace_for_session is not None else get_model_trace()
            )


def _clip_debug_text(text: Any, limit: int = 6000) -> str:
    value = "" if text is None else str(text)
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + f"\n... [showing first {limit} chars]"


def set_testmode_fake_model_trace() -> None:
    """Populate a deterministic fake trace for TEST_MODE layout checks."""
    if st is None or not is_model_trace_enabled():
        return

    now = time.time()
    st.session_state["autopm3_model_trace"] = [
        {
            "label": "paper intake candidate extraction",
            "model_name": "gpt-4o-mini",
            "input": "Extract PM3-ready candidate variants from linked Markdown chunks.",
            "started_at": now,
            "duration_ms": 840.0,
            "output": '{"candidate_variants": [{"variant": "NM_017739.1:c.1319T>G"}]}',
            "error": None,
        },
        {
            "label": "table extraction 1",
            "model_name": "gpt-4o-mini",
            "input": "CSV table with genotype rows for Case 1, Case 2, Case 3.",
            "started_at": now + 0.22,
            "duration_ms": 1280.0,
            "output": "Case 1 mentions c.1319T>G / p.L440R and c.1896-1G>C.",
            "error": None,
        },
        {
            "label": "pm3 evidence workflow",
            "model_name": "gpt-4o-mini",
            "input": "Synthesize standardized PM3 conclusion from evidence chunks.",
            "started_at": now + 1.7,
            "duration_ms": 960.0,
            "output": '{"standardized_conclusion": "needs manual review"}',
            "error": None,
        },
    ]


def render_testmode_model_trace() -> None:
    """Render the TEST_MODE model-call waterfall at the bottom of a page."""
    if st is None or not is_model_trace_enabled():
        return

    events = st.session_state.get("autopm3_model_trace", [])
    st.divider()
    st.markdown("### TESTMODE · Model Call Waterfall")
    if not events:
        st.caption("No model calls recorded in this run.")
        return

    starts = [float(event.get("started_at") or 0.0) for event in events]
    first_start = min(starts)
    last_end = max(
        float(event.get("started_at") or first_start)
        + (float(event.get("duration_ms") or 0.0) / 1000.0)
        for event in events
    )
    total_ms = max((last_end - first_start) * 1000.0, 1.0)
    sum_ms = sum(float(event.get("duration_ms") or 0.0) for event in events)
    st.caption(
        f"{len(events)} model calls · wall time {total_ms / 1000:.2f}s · summed model time {sum_ms / 1000:.2f}s"
    )

    rows = []
    for idx, event in enumerate(events, start=1):
        start_ms = (float(event.get("started_at") or first_start) - first_start) * 1000.0
        duration_ms = float(event.get("duration_ms") or 0.0)
        left_pct = max(0.0, min(96.0, start_ms / total_ms * 100.0))
        width_pct = max(2.0, min(100.0 - left_pct, duration_ms / total_ms * 100.0))
        label = html_lib.escape(str(event.get("label") or f"call {idx}"))
        model = html_lib.escape(str(event.get("model_name") or "unknown"))
        status_color = "#ef4444" if event.get("error") else "#2563eb"
        rows.append(
            f'<div class="autopm3-trace-row">'
            f'<div class="autopm3-trace-meta">#{idx} · {label}<br>'
            f'<span>{model} · +{start_ms:.0f}ms · {duration_ms:.0f}ms</span></div>'
            f'<div class="autopm3-trace-track">'
            f'<div class="autopm3-trace-bar" style="left:{left_pct:.2f}%; width:{width_pct:.2f}%; background:{status_color};"></div>'
            f'</div></div>'
        )
    trace_html = textwrap.dedent(
        f"""
        <style>
        .autopm3-trace-row {{
            display: grid;
            grid-template-columns: minmax(180px, 280px) 1fr;
            gap: 0.75rem;
            align-items: center;
            margin: 0.45rem 0;
        }}
        .autopm3-trace-meta {{
            font-size: 0.82rem;
            line-height: 1.25;
            color: #111827;
            overflow-wrap: anywhere;
        }}
        .autopm3-trace-meta span {{
            color: #6b7280;
        }}
        .autopm3-trace-track {{
            position: relative;
            height: 1.05rem;
            border-radius: 5px;
            background: #f3f4f6;
            overflow: hidden;
            border: 1px solid #e5e7eb;
        }}
        .autopm3-trace-bar {{
            position: absolute;
            top: 0;
            bottom: 0;
            border-radius: 4px;
        }}
        @media (max-width: 768px) {{
            .autopm3-trace-row {{
                grid-template-columns: 1fr;
            }}
        }}
        </style>
        {''.join(rows)}
        """
    ).strip()
    st.markdown(
        trace_html,
        unsafe_allow_html=True,
    )

    for idx, event in enumerate(events, start=1):
        label = event.get("label") or f"call {idx}"
        duration_ms = float(event.get("duration_ms") or 0.0)
        status = "error" if event.get("error") else "ok"
        with st.expander(f"#{idx} {label} · {duration_ms:.0f}ms · {status}", expanded=False):
            if event.get("error"):
                st.error(event["error"])
            st.markdown("**Input**")
            st.code(_clip_debug_text(event.get("input")), language="text")
            st.markdown("**Output**")
            st.code(_clip_debug_text(event.get("output")), language="text")


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
