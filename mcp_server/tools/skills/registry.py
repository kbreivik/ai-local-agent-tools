"""SQLite registry for dynamic skills."""
import json
import os
import sqlite3
from datetime import datetime, timezone


_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "data", "skills.db"
)
_IMPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "data", "skill_imports"
)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create skills table if it does not exist."""
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS skills (
                name           TEXT PRIMARY KEY,
                description    TEXT NOT NULL,
                category       TEXT DEFAULT 'general',
                version        TEXT DEFAULT '1.0.0',
                file_path      TEXT NOT NULL,
                auth_type      TEXT DEFAULT 'none',
                config_keys    TEXT DEFAULT '[]',
                parameters     TEXT DEFAULT '{}',
                annotations    TEXT DEFAULT '{}',
                enabled        INTEGER DEFAULT 1,
                auto_generated INTEGER DEFAULT 0,
                generation_mode TEXT DEFAULT 'manual',
                created_at     TEXT NOT NULL,
                updated_at     TEXT NOT NULL,
                call_count     INTEGER DEFAULT 0,
                last_error     TEXT,
                last_called_at TEXT
            )
        """)


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    # Deserialise JSON fields
    for key in ("config_keys", "parameters", "annotations"):
        if key in d and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    d["enabled"] = bool(d.get("enabled", 1))
    d["auto_generated"] = bool(d.get("auto_generated", 0))
    return d


def register_skill(
    meta: dict,
    file_path: str,
    auto_generated: bool = False,
    generation_mode: str = "manual",
) -> dict:
    """Insert or replace a skill record. Returns the row as dict."""
    now = _ts()
    name = meta["name"]
    with _conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO skills
                (name, description, category, version, file_path, auth_type,
                 config_keys, parameters, annotations, enabled, auto_generated,
                 generation_mode, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
        """, (
            name,
            meta.get("description", ""),
            meta.get("category", "general"),
            meta.get("version", "1.0.0"),
            file_path,
            meta.get("auth_type", "none"),
            json.dumps(meta.get("config_keys", [])),
            json.dumps(meta.get("parameters", {})),
            json.dumps(meta.get("annotations", {})),
            int(auto_generated),
            generation_mode,
            now,
            now,
        ))
    return get_skill(name) or {"name": name}


def search_skills(query: str, category: str = "") -> list[dict]:
    """LIKE search on name + description, optionally filtered by category."""
    like = f"%{query}%"
    with _conn() as conn:
        if category:
            rows = conn.execute(
                "SELECT * FROM skills WHERE (name LIKE ? OR description LIKE ?) AND category = ?",
                (like, like, category),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM skills WHERE name LIKE ? OR description LIKE ?",
                (like, like),
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_skills(category: str = "", enabled_only: bool = True) -> list[dict]:
    """List all skills, optionally filtered."""
    clauses = []
    params: list = []
    if enabled_only:
        clauses.append("enabled = 1")
    if category:
        clauses.append("category = ?")
        params.append(category)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with _conn() as conn:
        rows = conn.execute(f"SELECT * FROM skills{where}", params).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_skill(name: str) -> dict | None:
    """Get a single skill by name."""
    with _conn() as conn:
        row = conn.execute("SELECT * FROM skills WHERE name = ?", (name,)).fetchone()
    return _row_to_dict(row) if row else None


def increment_call(name: str) -> None:
    """Increment call_count and update last_called_at."""
    now = _ts()
    with _conn() as conn:
        conn.execute(
            "UPDATE skills SET call_count = call_count + 1, last_called_at = ? WHERE name = ?",
            (now, name),
        )


def record_error(name: str, error: str) -> None:
    """Record last error and update timestamp."""
    now = _ts()
    with _conn() as conn:
        conn.execute(
            "UPDATE skills SET last_error = ?, updated_at = ? WHERE name = ?",
            (error, now, name),
        )


def disable_skill(name: str) -> dict:
    """Disable a skill."""
    now = _ts()
    with _conn() as conn:
        conn.execute("UPDATE skills SET enabled = 0, updated_at = ? WHERE name = ?", (now, name))
    return {"name": name, "enabled": False}


def enable_skill(name: str) -> dict:
    """Enable a skill."""
    now = _ts()
    with _conn() as conn:
        conn.execute("UPDATE skills SET enabled = 1, updated_at = ? WHERE name = ?", (now, name))
    return {"name": name, "enabled": True}


def delete_skill(name: str) -> dict:
    """Delete a skill from the registry."""
    with _conn() as conn:
        conn.execute("DELETE FROM skills WHERE name = ?", (name,))
    return {"name": name, "deleted": True}


def list_pending_imports() -> list[dict]:
    """Scan _IMPORTS_DIR for .py files, return list of {filename, path, size}."""
    os.makedirs(_IMPORTS_DIR, exist_ok=True)
    results = []
    for fname in os.listdir(_IMPORTS_DIR):
        if fname.endswith(".py"):
            fpath = os.path.join(_IMPORTS_DIR, fname)
            if os.path.isfile(fpath):
                results.append({
                    "filename": fname,
                    "path": fpath,
                    "size": os.path.getsize(fpath),
                })
    return results
