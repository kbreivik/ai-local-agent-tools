"""SQLite storage backend — zero-config, always available.

Uses WAL journal mode for concurrent reads + single-writer safety.
Ported from the original registry.py with audit_log, checkpoints, and settings added.
"""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp_server.tools.skills.storage.interface import StorageBackend


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


class SqliteBackend(StorageBackend):

    def __init__(self, db_path: str = ""):
        if not db_path:
            project_root = Path(__file__).parent.parent.parent.parent.parent
            db_path = str(project_root / "data" / "skills.db")
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def init(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS skills (
                name            TEXT PRIMARY KEY,
                description     TEXT NOT NULL,
                category        TEXT DEFAULT 'general',
                version         TEXT DEFAULT '1.0.0',
                file_path       TEXT NOT NULL,
                auth_type       TEXT DEFAULT 'none',
                config_keys     TEXT DEFAULT '[]',
                parameters      TEXT DEFAULT '{}',
                annotations     TEXT DEFAULT '{}',
                compat          TEXT DEFAULT '{}',
                enabled         INTEGER DEFAULT 1,
                auto_generated  INTEGER DEFAULT 0,
                generation_mode TEXT DEFAULT 'manual',
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL,
                call_count      INTEGER DEFAULT 0,
                last_error      TEXT,
                last_called_at  TEXT
            );

            CREATE TABLE IF NOT EXISTS service_catalog (
                service_id          TEXT PRIMARY KEY,
                display_name        TEXT NOT NULL,
                service_type        TEXT DEFAULT '',
                detected_version    TEXT DEFAULT '',
                known_latest        TEXT DEFAULT '',
                version_source      TEXT DEFAULT '',
                api_docs_ingested   INTEGER DEFAULT 0,
                api_docs_version    TEXT DEFAULT '',
                changelog_ingested  INTEGER DEFAULT 0,
                last_checked        TEXT,
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL,
                notes               TEXT DEFAULT '',
                api_base            TEXT DEFAULT ''
            );

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
            );

            CREATE TABLE IF NOT EXISTS skill_compat_log (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_name          TEXT NOT NULL,
                service_id          TEXT NOT NULL,
                detected_version    TEXT,
                built_for_version   TEXT,
                compatible          INTEGER,
                check_method        TEXT DEFAULT '',
                details             TEXT DEFAULT '',
                checked_at          TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT NOT NULL,
                action      TEXT NOT NULL,
                result      TEXT DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
            CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(timestamp);

            CREATE TABLE IF NOT EXISTS checkpoints (
                label       TEXT NOT NULL,
                timestamp   TEXT NOT NULL,
                data        TEXT NOT NULL,
                PRIMARY KEY (label, timestamp)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key         TEXT PRIMARY KEY,
                value       TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
        """)
        conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def health_check(self) -> dict:
        try:
            self._get_conn().execute("SELECT 1")
            return {"ok": True, "backend": "sqlite", "details": self.db_path}
        except Exception as e:
            return {"ok": False, "backend": "sqlite", "details": str(e)}

    # ── Skills Registry ──────────────────────────────────────────────────────

    def register_skill(self, meta: dict, file_path: str, **kwargs) -> dict:
        now = _ts()
        name = meta["name"]
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO skills
                (name, description, category, version, file_path, auth_type,
                 config_keys, parameters, annotations, compat, enabled, auto_generated,
                 generation_mode, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
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
            json.dumps(meta.get("compat", {})),
            int(kwargs.get("auto_generated", False)),
            kwargs.get("generation_mode", "manual"),
            now, now,
        ))
        conn.commit()
        return self.get_skill(name) or {"name": name}

    def get_skill(self, name: str) -> dict | None:
        row = self._get_conn().execute(
            "SELECT * FROM skills WHERE name = ?", (name,)
        ).fetchone()
        return self._skill_row(row) if row else None

    def search_skills(self, query: str, category: str = "") -> list[dict]:
        like = f"%{query}%"
        if category:
            rows = self._get_conn().execute(
                "SELECT * FROM skills WHERE (name LIKE ? OR description LIKE ?) AND category = ?",
                (like, like, category),
            ).fetchall()
        else:
            rows = self._get_conn().execute(
                "SELECT * FROM skills WHERE name LIKE ? OR description LIKE ?",
                (like, like),
            ).fetchall()
        return [self._skill_row(r) for r in rows]

    def list_skills(self, category: str = "", enabled_only: bool = True) -> list[dict]:
        clauses, params = [], []
        if enabled_only:
            clauses.append("enabled = 1")
        if category:
            clauses.append("category = ?")
            params.append(category)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._get_conn().execute(f"SELECT * FROM skills{where}", params).fetchall()
        return [self._skill_row(r) for r in rows]

    def update_skill(self, name: str, **fields) -> dict:
        now = _ts()
        fields["updated_at"] = now
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        self._get_conn().execute(
            f"UPDATE skills SET {set_clause} WHERE name = ?",
            list(fields.values()) + [name],
        )
        self._get_conn().commit()
        return self.get_skill(name) or {"name": name}

    def delete_skill(self, name: str) -> dict:
        self._get_conn().execute("DELETE FROM skills WHERE name = ?", (name,))
        self._get_conn().commit()
        return {"name": name, "deleted": True}

    def increment_call(self, name: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE skills SET call_count = call_count + 1, last_called_at = ? WHERE name = ?",
            (_ts(), name),
        )
        conn.commit()

    def record_error(self, name: str, error: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE skills SET last_error = ?, updated_at = ? WHERE name = ?",
            (error, _ts(), name),
        )
        conn.commit()

    def _skill_row(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        for key in ("config_keys", "parameters", "annotations", "compat"):
            if key in d and isinstance(d[key], str):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        d["enabled"] = bool(d.get("enabled", 1))
        d["auto_generated"] = bool(d.get("auto_generated", 0))
        return d

    # ── Service Catalog ──────────────────────────────────────────────────────

    def upsert_service(self, service_id: str, **fields) -> dict:
        now = _ts()
        conn = self._get_conn()
        existing = conn.execute(
            "SELECT * FROM service_catalog WHERE service_id = ?", (service_id,)
        ).fetchone()

        if existing:
            updatable = {
                "display_name", "service_type", "detected_version", "known_latest",
                "version_source", "api_docs_ingested", "api_docs_version",
                "changelog_ingested", "last_checked", "notes", "api_base",
            }
            updates = {"updated_at": now}
            for k in updatable:
                if k in fields and fields[k] is not None:
                    updates[k] = fields[k]
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(
                f"UPDATE service_catalog SET {set_clause} WHERE service_id = ?",
                list(updates.values()) + [service_id],
            )
        else:
            conn.execute("""
                INSERT INTO service_catalog
                    (service_id, display_name, service_type, detected_version,
                     known_latest, version_source, api_docs_ingested, api_docs_version,
                     changelog_ingested, last_checked, created_at, updated_at, notes, api_base)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                service_id,
                fields.get("display_name", service_id.replace("_", " ").title()),
                fields.get("service_type", ""),
                fields.get("detected_version", ""),
                fields.get("known_latest", ""),
                fields.get("version_source", ""),
                int(fields.get("api_docs_ingested", 0)),
                fields.get("api_docs_version", ""),
                int(fields.get("changelog_ingested", 0)),
                fields.get("last_checked"),
                now, now,
                fields.get("notes", ""),
                fields.get("api_base", ""),
            ))
        conn.commit()
        return self.get_service(service_id) or {"service_id": service_id}

    def get_service(self, service_id: str) -> dict | None:
        row = self._get_conn().execute(
            "SELECT * FROM service_catalog WHERE service_id = ?", (service_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_services(self) -> list[dict]:
        rows = self._get_conn().execute(
            "SELECT * FROM service_catalog ORDER BY service_id"
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Breaking Changes ─────────────────────────────────────────────────────

    def add_breaking_change(self, service_id: str, to_version: str, description: str, **kwargs) -> dict:
        now = _ts()
        conn = self._get_conn()
        cursor = conn.execute("""
            INSERT INTO breaking_changes
                (service_id, from_version, to_version, severity, description,
                 affected_endpoints, affected_skills, remediation, source, muninndb_ref,
                 created_at, resolved)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (
            service_id,
            kwargs.get("from_version", ""),
            to_version,
            kwargs.get("severity", "warning"),
            description,
            json.dumps(kwargs.get("affected_endpoints", [])),
            json.dumps(kwargs.get("affected_skills", [])),
            kwargs.get("remediation", ""),
            kwargs.get("source", "manual"),
            kwargs.get("muninndb_ref", ""),
            now,
        ))
        conn.commit()
        change_id = cursor.lastrowid
        row = conn.execute(
            "SELECT * FROM breaking_changes WHERE id = ?", (change_id,)
        ).fetchone()
        return self._bc_row(row) if row else {"id": change_id}

    def get_breaking_changes(self, service_id: str, unresolved_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM breaking_changes WHERE service_id = ?"
        params: list = [service_id]
        if unresolved_only:
            sql += " AND resolved = 0"
        sql += " ORDER BY created_at DESC"
        rows = self._get_conn().execute(sql, params).fetchall()
        return [self._bc_row(r) for r in rows]

    def get_all_unresolved_breaking_changes(self) -> list[dict]:
        rows = self._get_conn().execute(
            "SELECT * FROM breaking_changes WHERE resolved = 0 ORDER BY created_at DESC"
        ).fetchall()
        return [self._bc_row(r) for r in rows]

    def resolve_breaking_change(self, change_id: int) -> dict:
        conn = self._get_conn()
        conn.execute("UPDATE breaking_changes SET resolved = 1 WHERE id = ?", (change_id,))
        conn.commit()
        return {"id": change_id, "resolved": True}

    def update_breaking_change_skills(self, change_id: int, affected_skills: list) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE breaking_changes SET affected_skills = ? WHERE id = ?",
            (json.dumps(affected_skills), change_id),
        )
        conn.commit()

    def _bc_row(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        for k in ("affected_endpoints", "affected_skills"):
            try:
                d[k] = json.loads(d[k])
            except Exception:
                pass
        d["resolved"] = bool(d.get("resolved", 0))
        return d

    # ── Compat Log ───────────────────────────────────────────────────────────

    def log_compat_check(self, skill_name: str, service_id: str, **kwargs) -> None:
        compatible = kwargs.get("compatible")
        compat_int = None if compatible is None else (1 if compatible else 0)
        conn = self._get_conn()
        conn.execute("""
            INSERT INTO skill_compat_log
                (skill_name, service_id, detected_version, built_for_version,
                 compatible, check_method, details, checked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            skill_name, service_id,
            kwargs.get("detected_version", ""),
            kwargs.get("built_for_version", ""),
            compat_int,
            kwargs.get("check_method", ""),
            kwargs.get("details", ""),
            _ts(),
        ))
        conn.commit()

    def get_compat_history(self, skill_name: str, limit: int = 10) -> list[dict]:
        rows = self._get_conn().execute(
            "SELECT * FROM skill_compat_log WHERE skill_name = ? ORDER BY checked_at DESC LIMIT ?",
            (skill_name, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Audit Log ────────────────────────────────────────────────────────────

    def append_audit(self, action: str, result: Any) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO audit_log (timestamp, action, result) VALUES (?, ?, ?)",
            (_ts(), action, json.dumps(result, default=str)),
        )
        conn.commit()

    def query_audit(self, action_prefix: str = "", limit: int = 50, offset: int = 0) -> list[dict]:
        if action_prefix:
            rows = self._get_conn().execute(
                "SELECT * FROM audit_log WHERE action LIKE ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (f"{action_prefix}%", limit, offset),
            ).fetchall()
        else:
            rows = self._get_conn().execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["result"] = json.loads(d["result"])
            except Exception:
                pass
            result.append(d)
        return result

    # ── Checkpoints ──────────────────────────────────────────────────────────

    def save_checkpoint(self, label: str, data: dict) -> dict:
        now = _ts()
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO checkpoints (label, timestamp, data) VALUES (?, ?, ?)",
            (label, now, json.dumps(data, default=str)),
        )
        conn.commit()
        return {"label": label, "timestamp": now}

    def load_checkpoint(self, label: str) -> dict | None:
        row = self._get_conn().execute(
            "SELECT * FROM checkpoints WHERE label = ? ORDER BY timestamp DESC LIMIT 1",
            (label,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["data"] = json.loads(d["data"])
        except Exception:
            pass
        return d

    def list_checkpoints(self, limit: int = 20) -> list[dict]:
        rows = self._get_conn().execute(
            "SELECT label, timestamp FROM checkpoints ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Settings ─────────────────────────────────────────────────────────────

    def get_setting(self, key: str) -> Any:
        row = self._get_conn().execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["value"])
        except Exception:
            return row["value"]

    def set_setting(self, key: str, value: Any) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, json.dumps(value, default=str), _ts()),
        )
        conn.commit()
