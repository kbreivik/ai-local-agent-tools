"""Agent tools for accessing stored results: result_fetch, result_query."""
from datetime import datetime, timezone

def _ts(): return datetime.now(timezone.utc).isoformat()
def _ok(data, msg=""): return {"status": "ok", "data": data, "message": msg, "timestamp": _ts()}
def _err(msg): return {"status": "error", "data": None, "message": msg, "timestamp": _ts()}


def result_fetch(ref: str, offset: int = 0, limit: int = 100) -> dict:
    """Retrieve items from a stored result by reference token.

    Use when a previous tool returned a ref token instead of full data.

    Args:
        ref:    Reference token (e.g. 'rs-abc123') from a previous tool result
        offset: Start index for pagination (default 0)
        limit:  Max items to return (default 100, max 500)
    """
    try:
        from api.db.result_store import fetch_result
        limit = min(int(limit), 500)
        data = fetch_result(ref, offset=int(offset), limit=limit)
        if not data:
            return _err(f"No result found for ref={ref!r} — may have expired (2h TTL)")
        return _ok(data, f"Fetched {len(data['items'])} of {data['total']} items from {ref}")
    except Exception as e:
        return _err(f"result_fetch error: {e}")


def result_query(ref: str, where: str = "", columns: str = "",
                 order_by: str = "", limit: int = 50) -> dict:
    """Filter and sort a stored result using SQL-like syntax.

    Materialises the stored data into a temporary Postgres table and
    runs your filter against it.

    Args:
        ref:      Reference token from a previous tool result
        where:    Filter, e.g. "type = 'wireless'" or "signal < -70"
        columns:  Comma-separated columns to return, e.g. "hostname,ip,signal"
        order_by: Sort expression, e.g. "signal DESC"
        limit:    Max rows (default 50)
    """
    try:
        from api.db.result_store import query_result
        cols = [c.strip() for c in columns.split(",") if c.strip()] if columns else None
        data = query_result(ref, where=where, columns=cols, order_by=order_by, limit=int(limit))
        if not data:
            return _err(f"No result found for ref={ref!r} — may have expired")
        if "error" in data:
            return _err(f"Query error: {data['error']}")
        return _ok(data, f"{data['count']} rows from {ref}" + (f" where {where}" if where else ""))
    except Exception as e:
        return _err(f"result_query error: {e}")
