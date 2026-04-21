"""v2.36.8 — result_render_table MCP tool.

Reads a stored result_store ref server-side, renders selected rows as a
markdown table, and returns the rendered string in `data.render_markdown`.
The agent harness detects this field on successful calls and appends the
markdown to operations.final_answer — the LLM's context only sees a
short acknowledgement, NOT the table data.

This is the foundation of the render-and-caption grammar: instead of
the LLM fetching rows via result_fetch and enumerating them in prose
(token-expensive, thrash-prone), it calls this tool once with a column
choice, writes ONE caption line, done.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

_MAX_LIMIT = 200
_DEFAULT_LIMIT = 50
_MAX_CELL_CHARS = 80


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ok(data: dict, msg: str = "") -> dict:
    return {"status": "ok", "data": data, "message": msg, "timestamp": _ts()}


def _err(msg: str) -> dict:
    return {"status": "error", "data": None, "message": msg, "timestamp": _ts()}


# ── Column auto-pick heuristic ────────────────────────────────────────────────

# Preferred column-name fragments when the agent doesn't supply `columns`.
# Scored by first-fragment-match wins; higher in list = more preferred.
_PREFERRED_FRAGMENTS = (
    "name", "hostname", "label", "id",
    "ip", "address", "mac",
    "status", "state", "health",
    "signal", "rssi", "up", "uptime",
    "service", "container", "node", "host",
    "port", "type", "kind",
    "ap", "switch", "location",
    "version", "image",
)

# Columns to skip in auto-pick (too wide, too noisy, or structurally opaque).
_SKIP_FRAGMENTS = (
    "raw", "json", "metadata_json", "config", "description",
    "notes", "comments", "full", "body", "source",
)


def _score_column(col: str) -> int:
    """Higher score = more likely to be useful in a table."""
    lc = col.lower()
    for bad in _SKIP_FRAGMENTS:
        if bad in lc:
            return -1
    for i, frag in enumerate(_PREFERRED_FRAGMENTS):
        if frag in lc:
            return 1000 - i  # earlier fragments score higher
    return 0  # unknown columns get mid-priority


def _pick_columns(available: list[str], max_cols: int = 6) -> list[str]:
    """Pick up to max_cols columns using the preferred-fragments heuristic."""
    if not available:
        return []
    scored = [(c, _score_column(c)) for c in available]
    scored = [(c, s) for c, s in scored if s >= 0]
    scored.sort(key=lambda t: (-t[1], t[0]))  # score desc, then name asc for stability
    picked = [c for c, _ in scored[:max_cols]]
    if not picked:
        # Nothing matched preferences and nothing was skipped — fall back to
        # first N available columns preserving order.
        picked = available[:max_cols]
    return picked


# ── Markdown rendering ────────────────────────────────────────────────────────

def _format_cell(v: Any) -> str:
    """Render a cell value as a short pipe-safe string."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        # Compact structured types — operators rarely want raw JSON in a table.
        if isinstance(v, list):
            return f"[{len(v)} items]"
        return f"{{\u2026{len(v)} keys}}"
    s = str(v)
    # Pipe is the markdown table delimiter — must escape.
    s = s.replace("|", "\\|")
    # Strip line breaks that would corrupt the row.
    s = s.replace("\r", " ").replace("\n", " ")
    if len(s) > _MAX_CELL_CHARS:
        s = s[: _MAX_CELL_CHARS - 1] + "\u2026"
    return s


def _render_markdown_table(
    items: list[dict],
    columns: list[str],
    total_available: int,
    truncated: bool,
) -> str:
    """Render items + columns as a GitHub-flavoured markdown table string."""
    if not items:
        return f"_(no rows matched — {total_available} total in ref)_"
    if not columns:
        return "_(no columns to render)_"

    header = "| " + " | ".join(columns) + " |"
    divider = "|" + "|".join(["---"] * len(columns)) + "|"
    rows = []
    for item in items:
        cells = [_format_cell(item.get(c)) for c in columns]
        rows.append("| " + " | ".join(cells) + " |")

    table = "\n".join([header, divider, *rows])
    if truncated:
        table += (
            f"\n\n_(showing first {len(items)} of {total_available} — "
            f"add a `where` clause to narrow)_"
        )
    return table


# ── Public tool ───────────────────────────────────────────────────────────────

def result_render_table(
    ref: str,
    columns: str = "",
    where: str = "",
    order_by: str = "",
    caption: str = "",
    limit: int = _DEFAULT_LIMIT,
) -> dict:
    """Render a stored result as a markdown table written directly to the
    operation output. Your LLM context gets a short acknowledgement, NOT
    the table — so this is the right tool for showing operators a
    >20-row list without filling your context window with row data.

    Args:
        ref:      Reference token from a previous tool result (e.g. 'rs-abc123').
        columns:  Comma-separated columns to include, e.g. "hostname,ip,ap_name".
                  If empty, up to 6 columns are auto-picked via heuristic
                  (prefer name/id/ip/mac/status fields, skip wide/opaque ones).
        where:    Optional SQL-style filter, e.g. "status = 'up'".
                  Passed through to the same engine as result_query.
        order_by: Optional SQL-style sort, e.g. "ap_name, hostname".
        caption:  IGNORED at tool level — the agent writes its own caption
                  as its final_answer. Reserved for future use.
        limit:    Max rows to render (default 50, capped at 200).

    Returns:
        On success, ``{status, message, data: {render_markdown, row_count,
        columns_used, output_length, truncated}}``. The harness reads
        `render_markdown` and appends it to operations.final_answer —
        operators see the full table; the LLM only sees the tiny message.
    """
    try:
        from api.db.result_store import query_result, fetch_result

        safe_limit = max(1, min(int(limit), _MAX_LIMIT))

        # Pick data source: query_result if any filter/sort, else fetch_result.
        # Both return {items, total_count_ish, …}; we normalise below.
        chosen_cols: list[str] | None = None
        if columns:
            chosen_cols = [c.strip() for c in columns.split(",") if c.strip()]

        if where or order_by or chosen_cols:
            # Route via query_result — supports where/order_by/column projection.
            qr = query_result(
                ref,
                where=where,
                columns=chosen_cols,
                order_by=order_by,
                limit=safe_limit,
            )
            if qr is None:
                return _err(
                    f"No result found for ref={ref!r} — may have expired (2h TTL)"
                )
            if "error" in qr:
                return _err(f"Query error: {qr['error']}")
            items = qr.get("items") or []
            result_cols = qr.get("columns") or []
            # query_result's count is post-filter; we also want the full ref
            # total for the truncation footer.
            total_in_ref = fetch_result(ref, offset=0, limit=1)
            total_available = (
                total_in_ref.get("total") if total_in_ref else len(items)
            )
        else:
            # No filter, no column projection — just fetch the top N.
            fr = fetch_result(ref, offset=0, limit=safe_limit)
            if fr is None:
                return _err(
                    f"No result found for ref={ref!r} — may have expired (2h TTL)"
                )
            items = fr.get("items") or []
            total_available = fr.get("total") or len(items)
            # Column discovery from the first row if chosen_cols wasn't given.
            if items and isinstance(items[0], dict):
                result_cols = list(items[0].keys())
            else:
                result_cols = []

        # Column finalisation: explicit override wins, otherwise heuristic pick.
        if chosen_cols:
            render_cols = chosen_cols
        else:
            render_cols = _pick_columns(result_cols, max_cols=6)

        # Did we truncate relative to the ref's real total?
        truncated = len(items) >= safe_limit and total_available > len(items)

        markdown = _render_markdown_table(
            items=items,
            columns=render_cols,
            total_available=int(total_available),
            truncated=truncated,
        )

        return _ok(
            {
                "render_markdown": markdown,
                "row_count":       len(items),
                "columns_used":    render_cols,
                "output_length":   len(markdown),
                "truncated":       truncated,
                "total_in_ref":    int(total_available),
            },
            (
                f"Rendered {len(items)} rows to operation output "
                f"({len(markdown)} chars, {len(render_cols)} columns). "
                f"Write a one-line caption as your final_answer."
            ),
        )

    except Exception as e:
        log.debug("result_render_table failed: %s", e)
        return _err(f"result_render_table error: {e}")
