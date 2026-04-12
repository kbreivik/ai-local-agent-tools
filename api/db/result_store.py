"""Result store — persistent reference storage for large tool results.

When a tool returns more than _LARGE_RESULT_BYTES, the full data is stored
here and a compact reference token is passed to the LLM instead.
TTL is 2 hours — long enough for multi-step runs and follow-up questions.
"""
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

_DDL_PG = """
CREATE TABLE IF NOT EXISTS result_store (
    id              TEXT PRIMARY KEY,
    tool_name       TEXT NOT NULL,
    operation_id    TEXT,
    session_id      TEXT,
    data            JSONB NOT NULL,
    summary         JSONB NOT NULL DEFAULT '{}',
    row_count       INTEGER DEFAULT 0,
    columns         JSONB DEFAULT '[]',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    expires_at      TIMESTAMPTZ,
    accessed_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_result_store_session ON result_store(session_id);
CREATE INDEX IF NOT EXISTS idx_result_store_expires ON result_store(expires_at);
CREATE INDEX IF NOT EXISTS idx_result_store_tool    ON result_store(tool_name);
"""

_TTL_HOURS = 2
_initialized = False
_MEM_STORE = {}


def _ts(): return datetime.now(timezone.utc).isoformat()
def _is_pg(): return "postgres" in os.environ.get("DATABASE_URL", "")


def init_result_store():
    global _initialized
    if _initialized: return True
    if not _is_pg():
        _initialized = True; return True
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        for stmt in _DDL_PG.strip().split(";"):
            s = stmt.strip()
            if s: cur.execute(s)
        cur.close(); conn.close()
        _initialized = True
        log.info("result_store table ready")
        return True
    except Exception as e:
        log.warning("result_store init failed: %s", e)
        return False


def store_result(tool_name, data, *, operation_id="", session_id="", ttl_hours=_TTL_HOURS):
    """Store a large tool result. Returns a compact reference dict for the LLM."""
    ref = f"rs-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=ttl_hours)

    items = data if isinstance(data, list) else [data]
    row_count = len(items)
    columns = list(items[0].keys()) if items and isinstance(items[0], dict) else []
    preview = items[:5]

    summary = {
        "ref": ref, "count": row_count, "preview": preview, "columns": columns,
        "message": (f"{row_count} items stored under ref={ref!r}. "
                    f"Use result_fetch(ref={ref!r}) to retrieve all, "
                    f"or result_query(ref={ref!r}, where=...) to filter."),
    }

    if not _is_pg():
        _MEM_STORE[ref] = {"data": items, "summary": summary, "expires": expires.isoformat()}
        return summary

    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO result_store (id, tool_name, operation_id, session_id, data, summary,
                                      row_count, columns, created_at, expires_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (ref, tool_name, operation_id or None, session_id or None,
              json.dumps(items), json.dumps(summary), row_count, json.dumps(columns),
              now.isoformat(), expires.isoformat()))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        log.debug("result_store write failed: %s — using memory", e)
        _MEM_STORE[ref] = {"data": items, "summary": summary, "expires": expires.isoformat()}

    return summary


def fetch_result(ref, offset=0, limit=50):
    """Retrieve a page of items. Returns None if not found/expired."""
    if ref in _MEM_STORE:
        items = _MEM_STORE[ref]["data"]
        return {"ref": ref, "total": len(items), "offset": offset, "limit": limit,
                "items": items[offset:offset + limit], "has_more": (offset + limit) < len(items)}
    if not _is_pg(): return None
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT data, row_count FROM result_store WHERE id = %s AND expires_at > NOW()", (ref,))
        row = cur.fetchone()
        cur.execute("UPDATE result_store SET accessed_at = NOW() WHERE id = %s", (ref,))
        conn.commit(); cur.close(); conn.close()
        if not row: return None
        items = row[0] if isinstance(row[0], list) else json.loads(row[0])
        return {"ref": ref, "total": row[1], "offset": offset, "limit": limit,
                "items": items[offset:offset + limit], "has_more": (offset + limit) < row[1]}
    except Exception as e:
        log.debug("result_store fetch failed: %s", e)
        return None


def query_result(ref, where="", columns=None, order_by="", limit=50, session_id=""):
    """Filter/sort a stored result via Postgres temp table."""
    if ref in _MEM_STORE:
        items = _MEM_STORE[ref]["data"]
        return {"ref": ref, "items": items[:limit], "count": min(len(items), limit),
                "note": "SQL query not available (no Postgres)"}
    if not _is_pg(): return None
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT data, columns FROM result_store WHERE id = %s AND expires_at > NOW()", (ref,))
        row = cur.fetchone()
        if not row: cur.close(); conn.close(); return None
        items = row[0] if isinstance(row[0], list) else json.loads(row[0])
        stored_cols = row[1] if isinstance(row[1], list) else json.loads(row[1] or "[]")
        select_cols = columns or stored_cols or ["*"]

        tmp = f"_rs_{ref.replace('-', '_')}"
        if stored_cols:
            col_defs = ", ".join(f'"{c}" TEXT' for c in stored_cols)
            cur.execute(f"CREATE TEMP TABLE IF NOT EXISTS {tmp} ({col_defs})")
            for item in items:
                vals = [str(item.get(c, "")) for c in stored_cols]
                ph = ", ".join(["%s"] * len(stored_cols))
                cur.execute(f"INSERT INTO {tmp} VALUES ({ph})", vals)
        else:
            cur.execute(f"CREATE TEMP TABLE IF NOT EXISTS {tmp} (data jsonb)")
            for item in items:
                cur.execute(f"INSERT INTO {tmp} VALUES (%s)", (json.dumps(item),))

        sel = ", ".join(f'"{c}"' for c in select_cols) if select_cols != ["*"] else "*"
        sql = f"SELECT {sel} FROM {tmp}"
        if where:
            safe = where.replace(";", "").strip()

            # All temp table columns are TEXT. Coerce bare boolean literals to quoted strings
            # so the agent can write: WHERE dangling = true  (not: WHERE dangling = 'true')
            import re as _re
            safe = _re.sub(
                r'=\s*(true|false)\b',
                lambda m: f"= '{m.group(1)}'",
                safe,
                flags=_re.IGNORECASE,
            )
            # Also handle IS TRUE / IS FALSE
            safe = _re.sub(r'\bIS\s+TRUE\b',  "= 'true'",  safe, flags=_re.IGNORECASE)
            safe = _re.sub(r'\bIS\s+FALSE\b', "= 'false'", safe, flags=_re.IGNORECASE)

            for kw in ("DROP", "DELETE", "INSERT", "UPDATE", "CREATE", "ALTER"):
                if kw.upper() in safe.upper():
                    cur.close(); conn.close()
                    return {"error": f"Disallowed keyword: {kw}"}
            sql += f" WHERE {safe}"
        if order_by: sql += f" ORDER BY {order_by.replace(';', '').strip()}"
        sql += f" LIMIT {int(limit)}"

        cur.execute(sql)
        result_cols = [d[0] for d in cur.description]
        rows = [dict(zip(result_cols, r)) for r in cur.fetchall()]
        cur.execute(f"DROP TABLE IF EXISTS {tmp}")
        conn.commit(); cur.close(); conn.close()
        return {"ref": ref, "count": len(rows), "columns": result_cols, "items": rows,
                "query": {"where": where, "order_by": order_by, "limit": limit}}
    except Exception as e:
        log.debug("result_store query failed: %s", e)
        return {"error": str(e)}


def cleanup_expired():
    if not _is_pg(): return 0
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM result_store WHERE expires_at < NOW()")
        n = cur.rowcount
        conn.commit(); cur.close(); conn.close()
        return n
    except Exception as e:
        log.debug("result_store cleanup failed: %s", e)
        return 0
