"""PostgreSQL storage backend — concurrent writes, Swarm-ready.

Uses psycopg2 (sync, matching project convention) with SimpleConnectionPool.
PostgreSQL advantages over SQLite:
  - Native concurrent writes — multiple replicas safe
  - JSONB columns for flexible schema
  - Full-text search via to_tsvector/plainto_tsquery
  - TIMESTAMPTZ for proper timezone handling
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any

from mcp_server.tools.skills.storage.interface import StorageBackend

log = logging.getLogger(__name__)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostgresBackend(StorageBackend):

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._pool = None

    def _get_pool(self):
        if self._pool is None:
            import psycopg2
            import psycopg2.pool
            import psycopg2.extras
            self._pool = psycopg2.pool.SimpleConnectionPool(
                minconn=1,
                maxconn=5,
                dsn=self.dsn,
                cursor_factory=psycopg2.extras.RealDictCursor,
            )
        return self._pool

    def _execute(self, sql: str, params: tuple = (), fetch: str = "none"):
        """Execute SQL. fetch: 'none', 'one', 'all'. Returns rows or None."""
        pool = self._get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                if fetch == "one":
                    result = cur.fetchone()
                elif fetch == "all":
                    result = cur.fetchall()
                else:
                    result = None
                conn.commit()
                return result
        except Exception:
            conn.rollback()
            raise
        finally:
            pool.putconn(conn)

    def _row(self, row) -> dict | None:
        if row is None:
            return None
        return dict(row)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def init(self) -> None:
        self._execute("""
            CREATE TABLE IF NOT EXISTS skills (
                name            TEXT PRIMARY KEY,
                description     TEXT NOT NULL,
                category        TEXT DEFAULT 'general',
                version         TEXT DEFAULT '1.0.0',
                file_path       TEXT NOT NULL,
                auth_type       TEXT DEFAULT 'none',
                config_keys     JSONB DEFAULT '[]',
                parameters      JSONB DEFAULT '{}',
                annotations     JSONB DEFAULT '{}',
                compat          JSONB DEFAULT '{}',
                enabled         BOOLEAN DEFAULT TRUE,
                auto_generated  BOOLEAN DEFAULT FALSE,
                generation_mode TEXT DEFAULT 'manual',
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                call_count      INTEGER DEFAULT 0,
                last_error      TEXT,
                last_called_at  TIMESTAMPTZ
            );

            CREATE TABLE IF NOT EXISTS service_catalog (
                service_id          TEXT PRIMARY KEY,
                display_name        TEXT NOT NULL,
                service_type        TEXT DEFAULT '',
                detected_version    TEXT DEFAULT '',
                known_latest        TEXT DEFAULT '',
                version_source      TEXT DEFAULT '',
                api_docs_ingested   BOOLEAN DEFAULT FALSE,
                api_docs_version    TEXT DEFAULT '',
                changelog_ingested  BOOLEAN DEFAULT FALSE,
                last_checked        TIMESTAMPTZ,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                notes               TEXT DEFAULT '',
                api_base            TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS breaking_changes (
                id                  SERIAL PRIMARY KEY,
                service_id          TEXT NOT NULL,
                from_version        TEXT DEFAULT '',
                to_version          TEXT NOT NULL,
                severity            TEXT DEFAULT 'warning',
                description         TEXT NOT NULL,
                affected_endpoints  JSONB DEFAULT '[]',
                affected_skills     JSONB DEFAULT '[]',
                remediation         TEXT DEFAULT '',
                source              TEXT DEFAULT '',
                muninndb_ref        TEXT DEFAULT '',
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                resolved            BOOLEAN DEFAULT FALSE
            );

            CREATE TABLE IF NOT EXISTS skill_compat_log (
                id                  SERIAL PRIMARY KEY,
                skill_name          TEXT NOT NULL,
                service_id          TEXT NOT NULL,
                detected_version    TEXT,
                built_for_version   TEXT,
                compatible          BOOLEAN,
                check_method        TEXT DEFAULT '',
                details             TEXT DEFAULT '',
                checked_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id          SERIAL PRIMARY KEY,
                timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                action      TEXT NOT NULL,
                result      JSONB DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
            CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(timestamp);

            CREATE TABLE IF NOT EXISTS checkpoints (
                label       TEXT NOT NULL,
                timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                data        JSONB NOT NULL,
                PRIMARY KEY (label, timestamp)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key         TEXT PRIMARY KEY,
                value       JSONB NOT NULL,
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_skills_fts
            ON skills USING gin(to_tsvector('english', description));
        """)

    def close(self) -> None:
        if self._pool:
            self._pool.closeall()
            self._pool = None

    def health_check(self) -> dict:
        try:
            row = self._execute(
                "SELECT version(), current_database() AS db", fetch="one"
            )
            ver = str(row.get("version", ""))[:40] if row else ""
            db = row.get("db", "") if row else ""
            return {"ok": True, "backend": "postgresql", "details": f"{db} ({ver})"}
        except Exception as e:
            return {"ok": False, "backend": "postgresql", "details": str(e)}

    # ── Skills Registry ──────────────────────────────────────────────────────

    def register_skill(self, meta: dict, file_path: str, **kwargs) -> dict:
        name = meta["name"]
        self._execute("""
            INSERT INTO skills
                (name, description, category, version, file_path, auth_type,
                 config_keys, parameters, annotations, compat, enabled, auto_generated,
                 generation_mode, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s, NOW(), NOW())
            ON CONFLICT (name) DO UPDATE SET
                description     = EXCLUDED.description,
                category        = EXCLUDED.category,
                version         = EXCLUDED.version,
                file_path       = EXCLUDED.file_path,
                auth_type       = EXCLUDED.auth_type,
                config_keys     = EXCLUDED.config_keys,
                parameters      = EXCLUDED.parameters,
                annotations     = EXCLUDED.annotations,
                compat          = EXCLUDED.compat,
                generation_mode = EXCLUDED.generation_mode,
                updated_at      = NOW()
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
            kwargs.get("auto_generated", False),
            kwargs.get("generation_mode", "manual"),
        ))
        return self.get_skill(name) or {"name": name}

    def get_skill(self, name: str) -> dict | None:
        row = self._execute(
            "SELECT * FROM skills WHERE name = %s", (name,), fetch="one"
        )
        return self._row(row)

    def search_skills(self, query: str, category: str = "") -> list[dict]:
        """Full-text search using PostgreSQL tsvector — better than LIKE."""
        sql = """
            SELECT *, ts_rank(to_tsvector('english', description),
                              plainto_tsquery('english', %s)) AS _rank
            FROM skills
            WHERE enabled = TRUE
              AND (
                to_tsvector('english', description) @@ plainto_tsquery('english', %s)
                OR name ILIKE %s
              )
        """
        params: list = [query, query, f"%{query}%"]
        if category:
            sql += " AND category = %s"
            params.append(category)
        sql += " ORDER BY _rank DESC LIMIT 20"
        rows = self._execute(sql, tuple(params), fetch="all") or []
        return [dict(r) for r in rows]

    def list_skills(self, category: str = "", enabled_only: bool = True) -> list[dict]:
        clauses, params = [], []
        if enabled_only:
            clauses.append("enabled = TRUE")
        if category:
            clauses.append("category = %s")
            params.append(category)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._execute(f"SELECT * FROM skills{where}", tuple(params), fetch="all") or []
        return [dict(r) for r in rows]

    def update_skill(self, name: str, **fields) -> dict:
        fields["updated_at"] = "NOW()"
        # Build SET clause — special-case NOW() literal
        parts = []
        params = []
        for k, v in fields.items():
            if v == "NOW()":
                parts.append(f"{k} = NOW()")
            else:
                parts.append(f"{k} = %s")
                params.append(v)
        set_clause = ", ".join(parts)
        params.append(name)
        self._execute(f"UPDATE skills SET {set_clause} WHERE name = %s", tuple(params))
        return self.get_skill(name) or {"name": name}

    def delete_skill(self, name: str) -> dict:
        self._execute("DELETE FROM skills WHERE name = %s", (name,))
        return {"name": name, "deleted": True}

    def increment_call(self, name: str) -> None:
        self._execute(
            "UPDATE skills SET call_count = call_count + 1, last_called_at = NOW() WHERE name = %s",
            (name,),
        )

    def record_error(self, name: str, error: str) -> None:
        self._execute(
            "UPDATE skills SET last_error = %s, updated_at = NOW() WHERE name = %s",
            (error, name),
        )

    # ── Service Catalog ──────────────────────────────────────────────────────

    def upsert_service(self, service_id: str, **fields) -> dict:
        display_name = fields.get("display_name", service_id.replace("_", " ").title())
        self._execute("""
            INSERT INTO service_catalog
                (service_id, display_name, service_type, detected_version, known_latest,
                 version_source, api_docs_ingested, api_docs_version, changelog_ingested,
                 last_checked, notes, api_base, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (service_id) DO UPDATE SET
                display_name        = COALESCE(NULLIF(EXCLUDED.display_name, ''), service_catalog.display_name),
                service_type        = COALESCE(NULLIF(EXCLUDED.service_type, ''), service_catalog.service_type),
                detected_version    = COALESCE(NULLIF(EXCLUDED.detected_version, ''), service_catalog.detected_version),
                known_latest        = COALESCE(NULLIF(EXCLUDED.known_latest, ''), service_catalog.known_latest),
                version_source      = COALESCE(NULLIF(EXCLUDED.version_source, ''), service_catalog.version_source),
                notes               = COALESCE(NULLIF(EXCLUDED.notes, ''), service_catalog.notes),
                api_base            = COALESCE(NULLIF(EXCLUDED.api_base, ''), service_catalog.api_base),
                updated_at          = NOW()
        """, (
            service_id, display_name,
            fields.get("service_type", ""),
            fields.get("detected_version", ""),
            fields.get("known_latest", ""),
            fields.get("version_source", ""),
            fields.get("api_docs_ingested", False),
            fields.get("api_docs_version", ""),
            fields.get("changelog_ingested", False),
            fields.get("last_checked"),
            fields.get("notes", ""),
            fields.get("api_base", ""),
        ))
        return self.get_service(service_id) or {"service_id": service_id}

    def get_service(self, service_id: str) -> dict | None:
        row = self._execute(
            "SELECT * FROM service_catalog WHERE service_id = %s", (service_id,), fetch="one"
        )
        return self._row(row)

    def list_services(self) -> list[dict]:
        rows = self._execute(
            "SELECT * FROM service_catalog ORDER BY service_id", fetch="all"
        ) or []
        return [dict(r) for r in rows]

    # ── Breaking Changes ─────────────────────────────────────────────────────

    def add_breaking_change(self, service_id: str, to_version: str, description: str, **kwargs) -> dict:
        row = self._execute("""
            INSERT INTO breaking_changes
                (service_id, from_version, to_version, severity, description,
                 affected_endpoints, affected_skills, remediation, source, muninndb_ref)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
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
        ), fetch="one")
        return self._row(row) or {}

    def get_breaking_changes(self, service_id: str, unresolved_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM breaking_changes WHERE service_id = %s"
        params: list = [service_id]
        if unresolved_only:
            sql += " AND resolved = FALSE"
        sql += " ORDER BY created_at DESC"
        rows = self._execute(sql, tuple(params), fetch="all") or []
        return [dict(r) for r in rows]

    def get_all_unresolved_breaking_changes(self) -> list[dict]:
        rows = self._execute(
            "SELECT * FROM breaking_changes WHERE resolved = FALSE ORDER BY created_at DESC",
            fetch="all",
        ) or []
        return [dict(r) for r in rows]

    def resolve_breaking_change(self, change_id: int) -> dict:
        self._execute(
            "UPDATE breaking_changes SET resolved = TRUE WHERE id = %s", (change_id,)
        )
        return {"id": change_id, "resolved": True}

    def update_breaking_change_skills(self, change_id: int, affected_skills: list) -> None:
        import json as _json
        self._execute(
            "UPDATE breaking_changes SET affected_skills = %s WHERE id = %s",
            (_json.dumps(affected_skills), change_id),
        )

    # ── Compat Log ───────────────────────────────────────────────────────────

    def log_compat_check(self, skill_name: str, service_id: str, **kwargs) -> None:
        self._execute("""
            INSERT INTO skill_compat_log
                (skill_name, service_id, detected_version, built_for_version,
                 compatible, check_method, details)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            skill_name, service_id,
            kwargs.get("detected_version", ""),
            kwargs.get("built_for_version", ""),
            kwargs.get("compatible"),
            kwargs.get("check_method", ""),
            kwargs.get("details", ""),
        ))

    def get_compat_history(self, skill_name: str, limit: int = 10) -> list[dict]:
        rows = self._execute("""
            SELECT * FROM skill_compat_log
            WHERE skill_name = %s ORDER BY checked_at DESC LIMIT %s
        """, (skill_name, limit), fetch="all") or []
        return [dict(r) for r in rows]

    # ── Audit Log ────────────────────────────────────────────────────────────

    def append_audit(self, action: str, result: Any) -> None:
        self._execute(
            "INSERT INTO audit_log (action, result) VALUES (%s, %s)",
            (action, json.dumps(result, default=str)),
        )

    def query_audit(self, action_prefix: str = "", limit: int = 50, offset: int = 0) -> list[dict]:
        if action_prefix:
            rows = self._execute("""
                SELECT * FROM audit_log WHERE action LIKE %s
                ORDER BY id DESC LIMIT %s OFFSET %s
            """, (f"{action_prefix}%", limit, offset), fetch="all") or []
        else:
            rows = self._execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT %s OFFSET %s",
                (limit, offset), fetch="all",
            ) or []
        return [dict(r) for r in rows]

    # ── Checkpoints ──────────────────────────────────────────────────────────

    def save_checkpoint(self, label: str, data: dict) -> dict:
        now = _ts()
        self._execute(
            "INSERT INTO checkpoints (label, data) VALUES (%s, %s) "
            "ON CONFLICT (label, timestamp) DO UPDATE SET data = EXCLUDED.data",
            (label, json.dumps(data, default=str)),
        )
        return {"label": label, "timestamp": now}

    def load_checkpoint(self, label: str) -> dict | None:
        row = self._execute("""
            SELECT * FROM checkpoints WHERE label = %s
            ORDER BY timestamp DESC LIMIT 1
        """, (label,), fetch="one")
        return self._row(row)

    def list_checkpoints(self, limit: int = 20) -> list[dict]:
        rows = self._execute("""
            SELECT label, timestamp FROM checkpoints
            ORDER BY timestamp DESC LIMIT %s
        """, (limit,), fetch="all") or []
        return [dict(r) for r in rows]

    # ── Settings ─────────────────────────────────────────────────────────────

    def get_setting(self, key: str) -> Any:
        row = self._execute(
            "SELECT value FROM settings WHERE key = %s", (key,), fetch="one"
        )
        if not row:
            return None
        val = row.get("value")
        # JSONB comes back as Python object already via psycopg2
        return val

    def set_setting(self, key: str, value: Any) -> None:
        self._execute("""
            INSERT INTO settings (key, value, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
        """, (key, json.dumps(value, default=str)))
