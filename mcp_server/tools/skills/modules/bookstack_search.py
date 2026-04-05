"""BookStack — search pages, list books, and recent updates."""
import os
from datetime import datetime, timezone

import httpx


SKILL_META = {
    "name": "bookstack_search",
    "description": "Search BookStack pages and books, list all books, or show recently updated pages.",
    "category": "general",
    "version": "1.0.0",
    "annotations": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "'search', 'books' (default), or 'recent'"},
            "query": {"type": "string", "description": "Search keyword (for action=search)"},
        },
        "required": [],
    },
    "auth_type": "token",
    "config_keys": ["BOOKSTACK_HOST", "BOOKSTACK_TOKEN_ID", "BOOKSTACK_TOKEN_SECRET"],
    "compat": {
        "service": "bookstack",
        "api_version_built_for": "24.02",
        "min_version": "21.0",
        "max_version": "",
        "version_endpoint": "/api/docs.json",
        "version_field": "",
    },
}


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ok(data, message="OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}

def _err(message, data=None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


def _headers() -> dict:
    tid = os.environ.get("BOOKSTACK_TOKEN_ID", "")
    secret = os.environ.get("BOOKSTACK_TOKEN_SECRET", "")
    if not tid or not secret:
        return {}
    return {"Authorization": f"Token {tid}:{secret}"}


def execute(**kwargs) -> dict:
    host = os.environ.get("BOOKSTACK_HOST", "")
    action = kwargs.get("action", "books")
    if not host:
        return _err("BOOKSTACK_HOST not configured")
    headers = _headers()
    if not headers:
        return _err("BOOKSTACK_TOKEN_ID and BOOKSTACK_TOKEN_SECRET required")

    base = f"https://{host}/api"
    try:
        if action == "search":
            return _search(base, headers, kwargs.get("query", ""))
        elif action == "recent":
            return _get_recent(base, headers)
        return _get_books(base, headers)
    except httpx.HTTPStatusError as e:
        return _err(f"BookStack API error: HTTP {e.response.status_code}")
    except Exception as e:
        return _err(f"BookStack connection failed: {e}")


def _search(base: str, headers: dict, query: str) -> dict:
    if not query:
        return _err("query parameter required for action=search")
    r = httpx.get(f"{base}/search", headers=headers, verify=False, timeout=10,
                  params={"query": query, "count": 20})
    r.raise_for_status()
    data = r.json()
    results = []
    for item in data.get("data", []):
        results.append({
            "type": item.get("type", ""),
            "name": item.get("name", ""),
            "id": item.get("id", 0),
            "url": item.get("url", ""),
            "preview": item.get("preview_html", {}).get("content", "")[:200] if isinstance(item.get("preview_html"), dict) else "",
        })
    return _ok({"results": results, "count": data.get("total", len(results))},
               f"BookStack search '{query}': {data.get('total', len(results))} result(s)")


def _get_books(base: str, headers: dict) -> dict:
    r = httpx.get(f"{base}/books", headers=headers, verify=False, timeout=10,
                  params={"count": 50})
    r.raise_for_status()
    data = r.json()
    books = []
    for b in data.get("data", []):
        books.append({
            "id": b.get("id", 0),
            "name": b.get("name", ""),
            "description": b.get("description", "")[:100],
            "slug": b.get("slug", ""),
        })
    return _ok({"books": books, "count": data.get("total", len(books))},
               f"BookStack: {data.get('total', len(books))} book(s)")


def _get_recent(base: str, headers: dict) -> dict:
    r = httpx.get(f"{base}/pages", headers=headers, verify=False, timeout=10,
                  params={"count": 20, "sort": "-updated_at"})
    r.raise_for_status()
    data = r.json()
    pages = []
    for p in data.get("data", []):
        pages.append({
            "id": p.get("id", 0),
            "name": p.get("name", ""),
            "book_id": p.get("book_id", 0),
            "updated_at": p.get("updated_at", ""),
        })
    return _ok({"pages": pages, "count": len(pages)},
               f"BookStack: {len(pages)} recently updated page(s)")


def check_compat(**kwargs) -> dict:
    host = os.environ.get("BOOKSTACK_HOST", "")
    if not host:
        return _ok({"compatible": None, "detected_version": None, "reason": "Not configured"})
    headers = _headers()
    if not headers:
        return _ok({"compatible": None, "detected_version": None, "reason": "No token"})
    try:
        r = httpx.get(f"https://{host}/api/docs.json", headers=headers, verify=False, timeout=10)
        return _ok({"compatible": True, "detected_version": "API available", "reason": "BookStack API reachable"})
    except Exception as e:
        return _ok({"compatible": None, "detected_version": None, "reason": str(e)})
