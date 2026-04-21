"""v2.36.8 — result_render_table regression tests.

Pure unit tests where possible (render helpers, column heuristic),
plus DB-backed tests for the full tool call using monkeypatched
result_store access.
"""
from __future__ import annotations

import pytest

from mcp_server.tools.render_tools import (
    result_render_table,
    _pick_columns,
    _render_markdown_table,
    _format_cell,
    _score_column,
)


# ── Unit: column auto-pick ────────────────────────────────────────────────────

def test_pick_columns_prefers_named_fields():
    available = ["id", "hostname", "ip", "mac", "raw_json", "notes", "rssi", "vendor"]
    picked = _pick_columns(available, max_cols=4)
    # hostname/ip/mac/rssi should win over raw_json/notes (skipped) and vendor (unknown)
    assert "hostname" in picked
    assert "ip" in picked
    assert "mac" in picked
    assert "raw_json" not in picked, "raw_* columns must be skipped"
    assert "notes" not in picked, "notes columns must be skipped"


def test_pick_columns_falls_back_to_order_when_all_skipped():
    # Everything looks skippable — should degrade to first-N.
    available = ["raw_foo", "raw_bar", "raw_baz", "config_dump"]
    picked = _pick_columns(available, max_cols=2)
    assert len(picked) == 2
    assert picked[0] == "raw_foo"  # preserves input order


def test_pick_columns_empty_input():
    assert _pick_columns([], max_cols=6) == []


def test_score_column_skips_opaque():
    assert _score_column("raw_json") < 0
    assert _score_column("notes") < 0


def test_score_column_prefers_name():
    # Any of the _PREFERRED_FRAGMENTS should score above 0
    assert _score_column("hostname") > 0
    assert _score_column("ip_address") > 0


# ── Unit: cell formatting ─────────────────────────────────────────────────────

def test_format_cell_escapes_pipes():
    assert _format_cell("a|b|c") == "a\\|b\\|c"


def test_format_cell_truncates_long():
    long_str = "x" * 200
    out = _format_cell(long_str)
    assert len(out) <= 80
    assert out.endswith("\u2026")


def test_format_cell_compacts_structured_values():
    assert _format_cell([1, 2, 3]) == "[3 items]"
    assert _format_cell({"a": 1, "b": 2}) == "{\u20262 keys}"


def test_format_cell_none_becomes_empty():
    assert _format_cell(None) == ""


def test_format_cell_strips_newlines():
    assert _format_cell("line1\nline2\nline3") == "line1 line2 line3"


def test_format_cell_booleans():
    assert _format_cell(True) == "true"
    assert _format_cell(False) == "false"


# ── Unit: markdown rendering ──────────────────────────────────────────────────

def test_render_markdown_basic():
    items = [
        {"hostname": "h1", "ip": "10.0.0.1"},
        {"hostname": "h2", "ip": "10.0.0.2"},
    ]
    md = _render_markdown_table(
        items, ["hostname", "ip"],
        post_filter_total=2, pre_filter_total=2, truncated=False,
    )
    assert "| hostname | ip |" in md
    assert "|---|---|" in md
    assert "| h1 | 10.0.0.1 |" in md
    assert "showing first" not in md  # no truncation footer when truncated=False


def test_render_markdown_truncation_footer_shows_totals():
    items = [{"x": i} for i in range(50)]
    md = _render_markdown_table(
        items, ["x"],
        post_filter_total=200, pre_filter_total=200, truncated=True,
    )
    assert "showing first 50 of 200" in md
    assert "where" in md  # hints at the fix


def test_render_markdown_no_rows():
    md = _render_markdown_table(
        [], ["a", "b"],
        post_filter_total=0, pre_filter_total=0, truncated=False,
    )
    assert "no rows" in md.lower()


def test_render_markdown_no_columns():
    md = _render_markdown_table(
        [{"a": 1}], [],
        post_filter_total=1, pre_filter_total=1, truncated=False,
    )
    assert "no columns" in md.lower()


# ── Integration: full tool call via monkeypatched result_store ────────────────

@pytest.fixture
def fake_result_store(monkeypatch):
    """Monkey-patch fetch_result and query_result to return canned data."""
    from api.db import result_store as rs

    _store = {
        "rs-unifi42": {
            "items": [
                {
                    "hostname": f"client-{i:02d}",
                    "ip":       f"10.0.0.{i}",
                    "mac":      f"aa:bb:cc:dd:ee:{i:02x}",
                    "ap_name":  f"ap-{(i % 3) + 1}",
                    "signal":   -40 - (i % 40),
                }
                for i in range(42)
            ],
        },
        "rs-empty": {"items": []},
    }

    def fake_fetch(ref, offset=0, limit=50):
        if ref not in _store:
            return None
        items = _store[ref]["items"]
        return {
            "ref": ref,
            "total": len(items),
            "offset": offset,
            "limit": limit,
            "items": items[offset : offset + limit],
            "has_more": (offset + limit) < len(items),
        }

    def fake_query(ref, where="", columns=None, order_by="", limit=50, session_id=""):
        if ref not in _store:
            return None
        items = _store[ref]["items"]
        # Minimal filter support for test — signal < -50 → drop ~half
        if "signal < -50" in where:
            items = [i for i in items if i.get("signal", 0) < -50]
        # Contract: `count` is post-filter, PRE-limit (v2.36.9 footer depends
        # on this to distinguish truncation from "filter matched everything").
        post_filter_count = len(items)
        return {
            "ref":     ref,
            "items":   items[:limit],
            "count":   post_filter_count,
            "columns": columns or (list(items[0].keys()) if items else []),
        }

    monkeypatch.setattr(rs, "fetch_result", fake_fetch)
    monkeypatch.setattr(rs, "query_result", fake_query)


def test_render_table_full_path_explicit_columns(fake_result_store):
    out = result_render_table(
        ref="rs-unifi42",
        columns="hostname,ip,ap_name,signal",
        limit=100,
    )
    assert out["status"] == "ok"
    data = out["data"]
    assert data["row_count"] == 42
    assert data["columns_used"] == ["hostname", "ip", "ap_name", "signal"]
    md = data["render_markdown"]
    assert "| hostname | ip | ap_name | signal |" in md
    assert "client-00" in md
    assert "ap-1" in md
    assert data["truncated"] is False


def test_render_table_auto_picks_columns(fake_result_store):
    out = result_render_table(ref="rs-unifi42", limit=10)
    assert out["status"] == "ok"
    cols = out["data"]["columns_used"]
    assert "hostname" in cols  # named field preferred
    assert "ip" in cols
    assert len(cols) <= 6


def test_render_table_truncates_and_flags(fake_result_store):
    out = result_render_table(ref="rs-unifi42", columns="hostname", limit=10)
    data = out["data"]
    assert data["row_count"] == 10
    assert data["truncated"] is True
    assert data["total_in_ref"] == 42
    assert "showing first 10 of 42" in data["render_markdown"]


def test_render_table_with_where_clause(fake_result_store):
    out = result_render_table(
        ref="rs-unifi42",
        columns="hostname,signal",
        where="signal < -50",
    )
    assert out["status"] == "ok"
    # The fake_query filter reduces set to clients with signal<-50
    assert out["data"]["row_count"] < 42


def test_render_table_respects_max_limit(fake_result_store):
    out = result_render_table(ref="rs-unifi42", limit=500)
    # _MAX_LIMIT = 200 but fake store only has 42 rows
    assert out["status"] == "ok"
    assert out["data"]["row_count"] == 42


def test_render_table_ref_not_found(fake_result_store):
    out = result_render_table(ref="rs-does-not-exist")
    assert out["status"] == "error"
    assert "expired" in out["message"].lower() or "not found" in out["message"].lower()


def test_render_table_empty_ref(fake_result_store):
    out = result_render_table(ref="rs-empty")
    assert out["status"] == "ok"
    assert out["data"]["row_count"] == 0
    assert "no rows" in out["data"]["render_markdown"].lower()


# ── Integration: allowlist ────────────────────────────────────────────────────
# v2.36.8 scope (spec Q4): observe + investigate only — NOT execute or build.

def test_result_render_table_in_observe_allowlist():
    from api.agents.router import OBSERVE_AGENT_TOOLS
    assert "result_render_table" in OBSERVE_AGENT_TOOLS, (
        "result_render_table must be in observe allowlist (v2.36.8)"
    )


def test_result_render_table_in_investigate_allowlist():
    from api.agents.router import INVESTIGATE_AGENT_TOOLS
    assert "result_render_table" in INVESTIGATE_AGENT_TOOLS


def test_result_render_table_NOT_in_execute_allowlists():
    """Spec Q4 decision — render tool is scoped to observe + investigate."""
    from api.agents.router import (
        EXECUTE_KAFKA_TOOLS,
        EXECUTE_SWARM_TOOLS,
        EXECUTE_PROXMOX_TOOLS,
        EXECUTE_GENERAL_TOOLS,
        BUILD_AGENT_TOOLS,
    )
    for name, allowlist in (
        ("kafka",   EXECUTE_KAFKA_TOOLS),
        ("swarm",   EXECUTE_SWARM_TOOLS),
        ("proxmox", EXECUTE_PROXMOX_TOOLS),
        ("general", EXECUTE_GENERAL_TOOLS),
        ("build",   BUILD_AGENT_TOOLS),
    ):
        assert "result_render_table" not in allowlist, (
            f"render tool must NOT be in {name} allowlist (spec Q4)"
        )


# ── v2.36.9 — filtered-footer behaviour and dispatch regression guard ────────

def test_render_table_where_clause_footer_cites_both_totals(fake_result_store):
    """v2.36.9 — footer must cite BOTH the filtered match count AND
    the pre-filter ref total so operators can see the filter worked."""
    # fake_query filters signal < -50 → subset of the 42-row ref
    out = result_render_table(
        ref="rs-unifi42",
        columns="hostname,signal",
        where="signal < -50",
        limit=5,   # force truncation
    )
    data = out["data"]
    assert out["status"] == "ok"
    assert data["pre_filter_total"] == 42
    assert data["post_filter_total"] <= 42
    md = data["render_markdown"]
    if data["truncated"]:
        # Footer must name both numbers when filtering and truncating
        assert "of 42" in md or "out of 42" in md
        assert "matching filter" in md


def test_dispatch_wired_in_agent_loop():
    """v2.36.9 — regression guard: the render tool dispatch must be
    wired in api/routers/agent.py. If this test fails, the feature
    is shipping as a no-op for operators (tool runs, markdown lost)."""
    import pathlib
    agent_py = pathlib.Path(__file__).parent.parent / "api" / "routers" / "agent.py"
    src = agent_py.read_text(encoding="utf-8")
    assert "result_render_table" in src, (
        "dispatch check: 'result_render_table' missing from agent.py — "
        "v2.36.8 feature is unwired"
    )
    assert "set_operation_final_answer_append" in src, (
        "dispatch check: 'set_operation_final_answer_append' missing from "
        "agent.py — render tool output cannot reach DB"
    )
    assert "render_markdown" in src, (
        "dispatch check: 'render_markdown' field extraction missing from "
        "agent.py — dispatch is shaped wrong"
    )
