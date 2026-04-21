"""v2.37.2 — TraceView picker must display session_id, not operation.id.

Structural guard so a future refactor can't silently re-break the
correlation between the Trace picker and the rest of the UI.
"""
import pathlib

REPO_ROOT = pathlib.Path(__file__).parent.parent


def test_trace_view_picker_renders_session_id_not_operation_id():
    p = REPO_ROOT / "gui" / "src" / "components" / "TraceView.jsx"
    src = p.read_text(encoding="utf-8")
    assert "o.session_id" in src, (
        "OperationPicker must read o.session_id for display (v2.37.2)"
    )
    import re
    assert not re.search(
        r"\(o\.id\s*\|\|\s*''\)\.slice\(0,\s*8\)\s*}\s*·",
        src,
    ), "o.id.slice(0, 8) as primary display was replaced by o.session_id in v2.37.2"


def test_trace_view_filter_matches_both_ids():
    """Filter must accept both session_id and operation.id as input."""
    p = REPO_ROOT / "gui" / "src" / "components" / "TraceView.jsx"
    src = p.read_text(encoding="utf-8")
    assert "o.session_id" in src
    assert "o.id" in src


def test_trace_view_option_value_is_operation_id():
    """<option value={o.id}> must stay — the trace API endpoint uses
    operation.id, not session_id."""
    p = REPO_ROOT / "gui" / "src" / "components" / "TraceView.jsx"
    src = p.read_text(encoding="utf-8")
    assert "value={o.id}" in src, (
        "<option value=o.id> must remain — trace endpoint is keyed on operation.id"
    )


def test_operations_list_queries_joins_agent_llm_traces():
    """Regression: api/db/queries.py::get_operations must source
    agent_type from agent_llm_traces (matches /recent endpoint)."""
    p = REPO_ROOT / "api" / "db" / "queries.py"
    src = p.read_text(encoding="utf-8")
    assert "FROM agent_llm_traces" in src, (
        "get_operations must join/subquery agent_llm_traces for agent_type"
    )
    assert "ORDER BY t.step_index ASC" in src, (
        "get_operations must pick step 0 (earliest step_index) for agent_type"
    )
