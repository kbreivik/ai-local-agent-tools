"""v2.38.5 — Logs sub-pages must expose DB UUIDs and full date+time.

Structural tests only; these are JSX source-file scans, not runtime
component tests (DEATHSTAR has no JSX test harness today).
"""
from __future__ import annotations

import pathlib

REPO_ROOT = pathlib.Path(__file__).parent.parent
GUI = REPO_ROOT / "gui" / "src"


def _read(rel: str) -> str:
    return (GUI / rel).read_text(encoding="utf-8")


def test_shared_fmtTs_util_exists():
    src = _read("utils/fmtTs.js")
    assert "export function fmtDateTime" in src
    assert "export function fmtDate" in src
    assert "export function fmtTime" in src
    # fmtDateTime must produce ISO-style output; loose but decisive
    # check: uses manual padStart to avoid locale dependence.
    assert "padStart(2, '0')" in src, (
        "fmtDateTime must build its own string — toLocaleTimeString "
        "is not locale-stable across browsers and breaks log "
        "correlation."
    )


def test_copyable_id_component_exists():
    src = _read("components/CopyableId.jsx")
    assert "export default function CopyableId" in src
    assert "navigator.clipboard.writeText" in src
    # execCommand fallback must be present (copied verbatim from
    # v2.38.1 — needed on non-HTTPS environments).
    assert "document.execCommand" in src, (
        "CopyableId must keep the execCommand fallback for non-HTTPS "
        "access (the GUI runs bare HTTP on 192.168.199.10)."
    )


def test_logtable_uses_shared_utils():
    src = _read("components/LogTable.jsx")
    assert "from '../utils/fmtTs'" in src
    assert "from './CopyableId'" in src
    # Old time-only formatter must be gone
    assert "toLocaleTimeString" not in src, (
        "LogTable.jsx should no longer call toLocaleTimeString — "
        "v2.38.5 routes every timestamp through fmtDateTime."
    )


def test_escview_shows_ids():
    """EscView must surface session_id, operation_id, and escalation id."""
    src = _read("components/LogTable.jsx")
    # Extract the EscView function body (from 'function EscView' or
    # 'export function EscView' to the next 'function' at column 0 or
    # 'export function').
    start = src.find("export function EscView")
    assert start >= 0, "EscView function not found"
    # End: either the next top-level 'export function' or EOF.
    end = src.find("export function", start + 1)
    if end < 0:
        end = len(src)
    body = src[start:end]

    # All three escalation ID surfaces must be rendered
    assert "e.session_id" in body, "EscView must render session_id"
    assert "e.operation_id" in body, "EscView must render operation_id"
    # Escalation row id IS referenced as key (`key={e.id}`); in
    # addition it must be in a CopyableId cell — check for the cell.
    assert "CopyableId value={e.id}" in body or \
           'CopyableId value={e.id}' in body, (
               "EscView must render the escalation id as a CopyableId "
               "pill, not just as the React key."
           )
    # Severity column must exist
    assert "e.severity" in body, "EscView must render severity"
    # Headers
    assert "'Escalation ID'" in body or '"Escalation ID"' in body
    assert "'Severity'" in body or '"Severity"' in body


def test_toolcall_row_shows_ids():
    """TcRow gained ID + Session columns in v2.38.5."""
    src = _read("components/LogTable.jsx")
    start = src.find("function TcRow")
    assert start >= 0
    end = src.find("function CorrelationView", start)
    assert end > start
    body = src[start:end]
    assert "CopyableId value={log.id}" in body
    assert "CopyableId value={log.session_id}" in body


def test_toolcalls_view_headers_updated():
    """Headers list must include the two new columns."""
    src = _read("components/LogTable.jsx")
    assert "'Time','ID','Session'" in src or \
           '"Time","ID","Session"' in src, (
               "ToolCallsView header row must list Time, ID, Session "
               "in the first three positions."
           )


def test_external_ai_calls_view_shows_ids():
    src = _read("components/ExternalAICallsView.jsx")
    assert "from '../utils/fmtTs'" in src
    assert "from './CopyableId'" in src
    assert "fmtDateTime(r.created_at)" in src
    assert "CopyableId value={r.id}" in src
    assert "CopyableId value={r.operation_id}" in src


def test_session_output_header_uses_copyable_id():
    """SessionOutputView header: truncated-with-ellipsis replaced by CopyableId."""
    src = _read("components/LogTable.jsx")
    # Old 'substring(0, 8)…' pattern must be gone
    assert "sessionId?.substring(0, 8)" not in src, (
        "SessionOutputView header must not show the truncated "
        "session_id with an ellipsis — use CopyableId instead so "
        "the full id can be copied."
    )
    assert "<CopyableId value={sessionId}" in src


def test_agent_actions_tab_uses_shared_fmtTs():
    src = _read("components/AgentActionsTab.jsx")
    # Must import the shared util
    assert "from '../utils/fmtTs'" in src
    # The local fmtTs definition must be gone (its body contained
    # the tell-tale `hour12: false` option).
    # After refactor, that literal appears ONLY in utils/fmtTs.js —
    # not in AgentActionsTab.
    assert "hour12: false" not in src, (
        "AgentActionsTab must not define its own fmtTs — it should "
        "import the shared utility instead."
    )
