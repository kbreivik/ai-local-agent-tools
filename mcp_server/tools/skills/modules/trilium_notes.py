"""Trilium — search notes, recent edits, and note tree structure."""
import os
from datetime import datetime, timezone

import httpx


SKILL_META = {
    "name": "trilium_notes",
    "description": "Search Trilium notes by keyword, list recently modified notes, or browse the note tree.",
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
            "action": {"type": "string", "description": "'search', 'recent' (default), or 'tree'"},
            "query": {"type": "string", "description": "Search keyword (for action=search)"},
        },
        "required": [],
    },
    "auth_type": "token",
    "config_keys": ["TRILIUM_HOST", "TRILIUM_ETAPI_TOKEN"],
    "compat": {
        "service": "trilium",
        "api_version_built_for": "0.63",
        "min_version": "0.50",
        "max_version": "",
        "version_endpoint": "/etapi/app-info",
        "version_field": "appVersion",
    },
}


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ok(data, message="OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}

def _err(message, data=None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


def _headers() -> dict:
    token = os.environ.get("TRILIUM_ETAPI_TOKEN", "")
    if not token:
        return {}
    return {"Authorization": token}


def execute(**kwargs) -> dict:
    host = os.environ.get("TRILIUM_HOST", "")
    action = kwargs.get("action", "recent")
    if not host:
        return _err("TRILIUM_HOST not configured")
    headers = _headers()
    if not headers:
        return _err("TRILIUM_ETAPI_TOKEN not configured")

    base = f"http://{host}:8080/etapi"
    try:
        if action == "search":
            return _search(base, headers, kwargs.get("query", ""))
        elif action == "tree":
            return _get_tree(base, headers)
        return _get_recent(base, headers)
    except httpx.HTTPStatusError as e:
        return _err(f"Trilium API error: HTTP {e.response.status_code}")
    except Exception as e:
        return _err(f"Trilium connection failed: {e}")


def _search(base: str, headers: dict, query: str) -> dict:
    if not query:
        return _err("query parameter required for action=search")
    r = httpx.get(f"{base}/notes", headers=headers, timeout=10,
                  params={"search": query})
    r.raise_for_status()
    notes = r.json().get("results", r.json()) if isinstance(r.json(), dict) else r.json()
    if not isinstance(notes, list):
        notes = []
    result = []
    for n in notes[:20]:
        result.append({
            "noteId": n.get("noteId", ""),
            "title": n.get("title", ""),
            "type": n.get("type", ""),
            "dateModified": n.get("dateModified", n.get("utcDateModified", "")),
        })
    return _ok({"notes": result, "count": len(result)},
               f"Trilium search '{query}': {len(result)} note(s)")


def _get_recent(base: str, headers: dict) -> dict:
    # ETAPI: get recent notes via search with orderBy
    r = httpx.get(f"{base}/notes", headers=headers, timeout=10,
                  params={"search": "#!archived", "orderBy": "dateModified", "orderDirection": "desc", "limit": 20})
    r.raise_for_status()
    notes = r.json().get("results", r.json()) if isinstance(r.json(), dict) else r.json()
    if not isinstance(notes, list):
        notes = []
    result = []
    for n in notes[:20]:
        result.append({
            "noteId": n.get("noteId", ""),
            "title": n.get("title", ""),
            "type": n.get("type", ""),
            "dateModified": n.get("dateModified", n.get("utcDateModified", "")),
        })
    return _ok({"notes": result, "count": len(result)},
               f"Trilium: {len(result)} recently modified note(s)")


def _get_tree(base: str, headers: dict) -> dict:
    # Get root note children (top-level structure)
    r = httpx.get(f"{base}/notes/root", headers=headers, timeout=10)
    r.raise_for_status()
    root = r.json()

    children = []
    # Get child branches of root
    try:
        br = httpx.get(f"{base}/notes/root/branches", headers=headers, timeout=10)
        if br.status_code == 200:
            branches = br.json() if isinstance(br.json(), list) else br.json().get("results", [])
            for b in branches[:20]:
                child_id = b.get("childNoteId", b.get("noteId", ""))
                if child_id:
                    try:
                        cr = httpx.get(f"{base}/notes/{child_id}", headers=headers, timeout=5)
                        if cr.status_code == 200:
                            cd = cr.json()
                            children.append({
                                "noteId": child_id,
                                "title": cd.get("title", ""),
                                "type": cd.get("type", ""),
                            })
                    except Exception:
                        children.append({"noteId": child_id, "title": "(load failed)", "type": ""})
    except Exception:
        pass

    return _ok({
        "root": {"noteId": "root", "title": root.get("title", "root")},
        "children": children,
        "count": len(children),
    }, f"Trilium tree: {len(children)} top-level note(s)")


def check_compat(**kwargs) -> dict:
    host = os.environ.get("TRILIUM_HOST", "")
    if not host:
        return _ok({"compatible": None, "detected_version": None, "reason": "Not configured"})
    headers = _headers()
    if not headers:
        return _ok({"compatible": None, "detected_version": None, "reason": "No ETAPI token"})
    try:
        r = httpx.get(f"http://{host}:8080/etapi/app-info", headers=headers, timeout=10)
        version = r.json().get("appVersion", "")
        return _ok({"compatible": True, "detected_version": version, "reason": f"Trilium {version}"})
    except Exception as e:
        return _ok({"compatible": None, "detected_version": None, "reason": str(e)})
