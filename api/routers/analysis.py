"""Admin-only analysis — run registered SQL templates with bound params.

sith_lord only. Templates live in api/analysis_templates.py. This router
handles auth, param validation, query execution with timeout, and
response shaping (including CSV / Markdown dumps).
"""
import csv
import io
import json
import logging
import os
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import PlainTextResponse

from api.auth import get_current_user_and_role, role_meets
from api.analysis_templates import (
    TEMPLATES, get_template, list_templates, validate_params,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/analysis", tags=["admin-analysis"])

_STATEMENT_TIMEOUT_MS = 30_000  # 30s hard cap on every query


async def require_sith_lord(
    principal: tuple[str, str] = Depends(get_current_user_and_role),
) -> str:
    """Gate: sith_lord only."""
    username, role = principal
    if not role_meets(role, "sith_lord"):
        raise HTTPException(
            status_code=403,
            detail=f"sith_lord role required (you are {role})",
        )
    return username


def _run_template_sync(tpl: dict, bound_params: dict) -> dict:
    """Execute one template. Returns {columns, rows, row_count, truncated,
    latency_ms}. Raises HTTPException on DB error."""
    import time
    if "postgres" not in os.environ.get("DATABASE_URL", ""):
        raise HTTPException(503, "Postgres required")
    from api.connections import _get_conn
    try:
        conn = _get_conn()
        cur = conn.cursor()
        # Hard cap on statement duration — any single template > 30s aborts.
        cur.execute(f"SET LOCAL statement_timeout = {_STATEMENT_TIMEOUT_MS}")
        t0 = time.perf_counter()
        cur.execute(tpl["sql"], bound_params)
        rows = cur.fetchall()
        latency_ms = int((time.perf_counter() - t0) * 1000)
        columns = [d[0] for d in cur.description] if cur.description else []
        conn.commit()
        cur.close(); conn.close()
    except HTTPException:
        raise
    except Exception as e:
        log.exception("analysis template execution failed")
        raise HTTPException(500, f"Query failed: {type(e).__name__}: {str(e)[:300]}")
    # Normalise rows to list[dict] (psycopg returns tuples)
    result_rows = [dict(zip(columns, r)) for r in rows]
    row_cap = bound_params.get("row_cap", 500)
    truncated = len(result_rows) >= row_cap
    return {
        "columns": columns,
        "rows": result_rows,
        "row_count": len(result_rows),
        "truncated": truncated,
        "latency_ms": latency_ms,
    }


def _jsonify(obj):
    """Recursively convert non-JSON-native types (datetime, UUID, Decimal)
    to strings for safe JSON serialisation."""
    from datetime import date, datetime
    from decimal import Decimal
    import uuid as _uuid
    if isinstance(obj, dict):
        return {k: _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonify(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, _uuid.UUID):
        return str(obj)
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


@router.get("/templates")
async def get_templates(_: str = Depends(require_sith_lord)):
    """List all registered templates with param schemas (no raw SQL)."""
    return {"templates": list_templates()}


@router.post("/run")
async def run_template(
    body: dict,
    _: str = Depends(require_sith_lord),
):
    """Run a template by id with a dict of params. Returns JSON rows."""
    tid = (body or {}).get("template_id")
    raw_params = (body or {}).get("params") or {}
    tpl = get_template(tid)
    if not tpl:
        raise HTTPException(404, f"Unknown template: {tid}")
    try:
        bound = validate_params(tpl, raw_params)
    except ValueError as e:
        raise HTTPException(400, str(e))
    result = _run_template_sync(tpl, bound)
    return {"template_id": tid, "params": bound, **_jsonify(result)}


def _flatten_for_csv(rows: list[dict]) -> list[dict]:
    """CSV needs scalar columns — serialise nested JSON as compact strings."""
    out = []
    for r in rows:
        flat = {}
        for k, v in r.items():
            if isinstance(v, (dict, list)):
                flat[k] = json.dumps(v, default=str)
            elif v is None:
                flat[k] = ""
            else:
                flat[k] = str(v)
        out.append(flat)
    return out


def _render_markdown(columns: list[str], rows: list[dict]) -> str:
    """Render rows as GitHub-flavoured markdown table. Nested JSON cells are
    pipe-escaped and truncated to 120 chars with ellipsis."""
    if not columns:
        return "*(no columns)*\n"
    lines = ["| " + " | ".join(columns) + " |",
             "| " + " | ".join("---" for _ in columns) + " |"]
    for r in rows:
        cells = []
        for c in columns:
            v = r.get(c)
            if isinstance(v, (dict, list)):
                s = json.dumps(v, default=str)
            elif v is None:
                s = ""
            else:
                s = str(v)
            s = s.replace("|", "\\|").replace("\n", " ")
            if len(s) > 120:
                s = s[:117] + "..."
            cells.append(s)
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


@router.post("/dump")
async def dump_template(
    body: dict,
    format: str = Query("json", pattern="^(json|csv|md)$"),
    _: str = Depends(require_sith_lord),
):
    """Run a template and return the result as a downloadable attachment.

    format=json (default), csv, or md. Content-Disposition triggers
    browser download.
    """
    tid = (body or {}).get("template_id")
    raw_params = (body or {}).get("params") or {}
    tpl = get_template(tid)
    if not tpl:
        raise HTTPException(404, f"Unknown template: {tid}")
    try:
        bound = validate_params(tpl, raw_params)
    except ValueError as e:
        raise HTTPException(400, str(e))
    result = _run_template_sync(tpl, bound)
    safe_rows = _jsonify(result["rows"])
    from datetime import datetime, timezone
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    if format == "json":
        payload = json.dumps(
            {
                "template_id": tid,
                "params": bound,
                "columns": result["columns"],
                "row_count": result["row_count"],
                "truncated": result["truncated"],
                "latency_ms": result["latency_ms"],
                "rows": safe_rows,
                "exported_at": stamp,
            },
            indent=2, default=str,
        )
        return Response(
            content=payload, media_type="application/json",
            headers={"Content-Disposition":
                     f"attachment; filename=\"analysis_{tid}_{stamp}.json\""},
        )
    if format == "csv":
        flat = _flatten_for_csv(safe_rows)
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=result["columns"] or (list(flat[0].keys()) if flat else []))
        writer.writeheader()
        for r in flat:
            writer.writerow(r)
        return PlainTextResponse(
            content=buf.getvalue(), media_type="text/csv",
            headers={"Content-Disposition":
                     f"attachment; filename=\"analysis_{tid}_{stamp}.csv\""},
        )
    # markdown
    header = (
        f"# Analysis dump — {tpl['title']}\n\n"
        f"- Template: `{tid}`\n"
        f"- Params: `{json.dumps(bound)}`\n"
        f"- Rows: {result['row_count']}{' (truncated)' if result['truncated'] else ''}\n"
        f"- Latency: {result['latency_ms']}ms\n"
        f"- Exported: {stamp}\n\n"
    )
    body_md = _render_markdown(result["columns"], safe_rows)
    return PlainTextResponse(
        content=header + body_md, media_type="text/markdown",
        headers={"Content-Disposition":
                 f"attachment; filename=\"analysis_{tid}_{stamp}.md\""},
    )
