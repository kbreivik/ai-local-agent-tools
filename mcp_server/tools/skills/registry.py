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
    """Create skills table and supporting tables if they do not exist."""
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS service_catalog (
                service_id         TEXT PRIMARY KEY,
                display_name       TEXT NOT NULL,
                service_type       TEXT DEFAULT '',
                detected_version   TEXT DEFAULT '',
                known_latest       TEXT DEFAULT '',
                version_source     TEXT DEFAULT '',
                api_docs_ingested  INTEGER DEFAULT 0,
                api_docs_version   TEXT DEFAULT '',
                changelog_ingested INTEGER DEFAULT 0,
                last_checked       TEXT,
                created_at         TEXT NOT NULL,
                updated_at         TEXT NOT NULL,
                notes              TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS breaking_changes (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id          TEXT NOT NULL,
                from_version        TEXT DEFAULT '',
                to_version          TEXT NOT NULL,
                severity            TEXT DEFAULT 'warning',
                description         TEXT NOT NULL,
                affected_endpoints  TEXT DEFAULT '[]',
                affected_skills     TEXT DEFAULT '[]',
                remediation         TEXT DEFAULT '',
                source              TEXT DEFAULT '',
                muninndb_ref        TEXT DEFAULT '',
                created_at          TEXT NOT NULL,
                resolved            INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS skill_compat_log (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_name       TEXT NOT NULL,
                service_id       TEXT NOT NULL,
                detected_version TEXT,
                built_for_version TEXT,
                compatible       INTEGER,
                check_method     TEXT DEFAULT '',
                details          TEXT DEFAULT '',
                checked_at       TEXT NOT NULL
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


# ── Service catalog ────────────────────────────────────────────────────────────

def upsert_service(service_id: str, display_name: str, service_type: str = "", **kwargs) -> dict:
    """Insert or update a service catalog entry."""
    now = _ts()
    with _conn() as conn:
        existing = conn.execute(
            "SELECT * FROM service_catalog WHERE service_id = ?", (service_id,)
        ).fetchone()
        if existing:
            # Update non-empty kwargs
            updates = {"updated_at": now}
            for k in ("detected_version", "known_latest", "version_source",
                      "api_docs_ingested", "api_docs_version", "changelog_ingested",
                      "last_checked", "notes"):
                if k in kwargs and kwargs[k] is not None:
                    updates[k] = kwargs[k]
            if display_name:
                updates["display_name"] = display_name
            if service_type:
                updates["service_type"] = service_type
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(
                f"UPDATE service_catalog SET {set_clause} WHERE service_id = ?",
                list(updates.values()) + [service_id]
            )
        else:
            conn.execute("""
                INSERT INTO service_catalog
                    (service_id, display_name, service_type, detected_version,
                     known_latest, version_source, api_docs_ingested, api_docs_version,
                     changelog_ingested, last_checked, created_at, updated_at, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                service_id,
                display_name,
                service_type,
                kwargs.get("detected_version", ""),
                kwargs.get("known_latest", ""),
                kwargs.get("version_source", ""),
                int(kwargs.get("api_docs_ingested", 0)),
                kwargs.get("api_docs_version", ""),
                int(kwargs.get("changelog_ingested", 0)),
                kwargs.get("last_checked"),
                now, now,
                kwargs.get("notes", ""),
            ))
    return get_service(service_id) or {"service_id": service_id}


def get_service(service_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM service_catalog WHERE service_id = ?", (service_id,)
        ).fetchone()
    return dict(row) if row else None


def list_services() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM service_catalog ORDER BY service_id").fetchall()
    return [dict(r) for r in rows]


def update_service_version(service_id: str, version: str, source: str = "skill_probe") -> dict:
    """Update the detected version for a service. Creates entry if not exists."""
    existing = get_service(service_id)
    if existing:
        now = _ts()
        with _conn() as conn:
            conn.execute(
                "UPDATE service_catalog SET detected_version = ?, version_source = ?, last_checked = ?, updated_at = ? WHERE service_id = ?",
                (version, source, now, now, service_id)
            )
        return get_service(service_id) or {}
    else:
        return upsert_service(service_id, service_id.replace("_", " ").title(),
                              detected_version=version, version_source=source,
                              last_checked=_ts())


# ── Breaking changes ───────────────────────────────────────────────────────────

def add_breaking_change(service_id: str, to_version: str, description: str, **kwargs) -> dict:
    now = _ts()
    # Determine which skills are affected based on service_id
    affected_skills = kwargs.get("affected_skills", [])
    if not affected_skills:
        # Auto-detect: find skills for this service
        with _conn() as conn:
            rows = conn.execute(
                "SELECT name FROM skills WHERE enabled = 1"
            ).fetchall()
        # We don't have service_id in skills table, so just return empty — caller can pass it
        affected_skills = []

    with _conn() as conn:
        cursor = conn.execute("""
            INSERT INTO breaking_changes
                (service_id, from_version, to_version, severity, description,
                 affected_endpoints, affected_skills, remediation, source, muninndb_ref, created_at, resolved)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (
            service_id,
            kwargs.get("from_version", ""),
            to_version,
            kwargs.get("severity", "warning"),
            description,
            json.dumps(kwargs.get("affected_endpoints", [])),
            json.dumps(affected_skills),
            kwargs.get("remediation", ""),
            kwargs.get("source", "manual"),
            kwargs.get("muninndb_ref", ""),
            now,
        ))
        change_id = cursor.lastrowid

    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM breaking_changes WHERE id = ?", (change_id,)
        ).fetchone()
    if row:
        d = dict(row)
        for k in ("affected_endpoints", "affected_skills"):
            try:
                d[k] = json.loads(d[k])
            except Exception:
                pass
        return d
    return {"id": change_id}


def get_breaking_changes(service_id: str, from_version: str = "", to_version: str = "") -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM breaking_changes WHERE service_id = ? AND resolved = 0 ORDER BY created_at DESC",
            (service_id,)
        ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        for k in ("affected_endpoints", "affected_skills"):
            try:
                d[k] = json.loads(d[k])
            except Exception:
                pass
        result.append(d)
    return result


def get_unresolved_breaking_changes() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM breaking_changes WHERE resolved = 0 ORDER BY created_at DESC"
        ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        for k in ("affected_endpoints", "affected_skills"):
            try:
                d[k] = json.loads(d[k])
            except Exception:
                pass
        result.append(d)
    return result


def resolve_breaking_change(change_id: int) -> dict:
    with _conn() as conn:
        conn.execute(
            "UPDATE breaking_changes SET resolved = 1 WHERE id = ?", (change_id,)
        )
    return {"id": change_id, "resolved": True}


# ── Compat log ─────────────────────────────────────────────────────────────────

def log_compat_check(
    skill_name: str,
    service_id: str,
    detected_version: str,
    compatible,
    **kwargs
) -> None:
    now = _ts()
    compat_int = None if compatible is None else (1 if compatible else 0)
    with _conn() as conn:
        conn.execute("""
            INSERT INTO skill_compat_log
                (skill_name, service_id, detected_version, built_for_version,
                 compatible, check_method, details, checked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            skill_name,
            service_id,
            detected_version or "",
            kwargs.get("built_for_version", ""),
            compat_int,
            kwargs.get("check_method", ""),
            kwargs.get("details", ""),
            now,
        ))


def get_compat_history(skill_name: str, limit: int = 10) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM skill_compat_log WHERE skill_name = ? ORDER BY checked_at DESC LIMIT ?",
            (skill_name, limit)
        ).fetchall()
    return [dict(r) for r in rows]
