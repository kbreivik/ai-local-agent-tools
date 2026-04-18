"""
Schema versioning — runs on startup, applies missing migrations in order.
Never drops data. Each migration is idempotent.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from api.db.models import metadata

log = logging.getLogger(__name__)

# ── Migration definitions ─────────────────────────────────────────────────────
# Each entry: (version: int, description: str, sql: list[str])
# SQL must be backend-agnostic or use the dialect check below.

MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (1, "Initial schema", []),  # schema created by metadata.create_all
    (2, "Add indexes to tool_calls and operations", [
        "CREATE INDEX IF NOT EXISTS idx_tc_status   ON tool_calls(status)",
        "CREATE INDEX IF NOT EXISTS idx_tc_tool     ON tool_calls(tool_name)",
        "CREATE INDEX IF NOT EXISTS idx_tc_op       ON tool_calls(operation_id)",
        "CREATE INDEX IF NOT EXISTS idx_tc_ts       ON tool_calls(timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_ops_session ON operations(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_esc_resolved ON escalations(resolved)",
        "CREATE INDEX IF NOT EXISTS idx_snap_comp   ON status_snapshots(component)",
        "CREATE INDEX IF NOT EXISTS idx_audit_type  ON audit_log(event_type)",
    ]),
    (3, "Add new columns to operations (Phase 3 schema upgrade)", [
        # SQLite ALTER TABLE only supports ADD COLUMN — safe to re-run (IF NOT EXISTS not supported,
        # so each statement is wrapped individually in the try/except in run_migrations)
        "ALTER TABLE operations ADD COLUMN triggered_by TEXT",
        "ALTER TABLE operations ADD COLUMN model_used TEXT",
        "ALTER TABLE operations ADD COLUMN total_duration_ms INTEGER",
        "ALTER TABLE tool_calls ADD COLUMN error_detail TEXT",
    ]),
    (4, "Add memory_context to tool_calls (Phase 5 — MuninnDB engram IDs)", [
        "ALTER TABLE tool_calls ADD COLUMN memory_context TEXT",
    ]),
    (5, "Add feedback columns to operations (Phase 7 — thumbs feedback)", [
        "ALTER TABLE operations ADD COLUMN feedback TEXT",
        "ALTER TABLE operations ADD COLUMN feedback_at TEXT",
        "ALTER TABLE operations ADD COLUMN final_answer TEXT",
    ]),
    (6, "Add operation_log table and owner_user to operations (Phase 8 — auth)", [
        "ALTER TABLE operations ADD COLUMN owner_user TEXT",
        """CREATE TABLE IF NOT EXISTS operation_log (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            type TEXT NOT NULL,
            content TEXT,
            metadata TEXT,
            timestamp TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_oplog_session ON operation_log(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_oplog_ts ON operation_log(timestamp)",
    ]),
    (7, "Add user_layouts table for per-user dashboard layout storage", [
        """CREATE TABLE IF NOT EXISTS user_layouts (
            user_id     TEXT PRIMARY KEY,
            layout_json TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )""",
    ]),
    (8, "v2.34.2 — skill_executions + auto_promoter_scans (observability)", [
        """CREATE TABLE IF NOT EXISTS skill_executions (
            id                 TEXT PRIMARY KEY,
            skill_id           TEXT NOT NULL,
            task_id            TEXT NOT NULL,
            agent_type         TEXT NOT NULL,
            invoked_by         TEXT,
            args               TEXT,
            started_at         TEXT NOT NULL,
            completed_at       TEXT,
            duration_ms        INTEGER,
            outcome            TEXT,
            error              TEXT,
            result_summary     TEXT,
            replaced_tool_chain TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS idx_skill_exec_skill ON skill_executions (skill_id, started_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_skill_exec_task  ON skill_executions (task_id)",
        """CREATE TABLE IF NOT EXISTS auto_promoter_scans (
            id                TEXT PRIMARY KEY,
            scanned_at        TEXT NOT NULL,
            window_days       INTEGER NOT NULL,
            actions_scanned   INTEGER NOT NULL,
            candidates_found  INTEGER NOT NULL,
            candidates_new    INTEGER NOT NULL,
            duration_ms       INTEGER,
            triggered_by      TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_promoter_scans_ts ON auto_promoter_scans (scanned_at DESC)",
    ]),
    (9, "v2.34.8 — subagent_runs.substantive_tool_calls for hallucination audit", [
        # Column may already exist via init_subagent_runs() — the
        # ADD COLUMN IF NOT EXISTS form keeps this idempotent on Postgres.
        # The subagent_runs table itself is not part of SQLAlchemy metadata
        # (it's created by init_subagent_runs()), so this is a Postgres-only
        # migration — on SQLite the statement is a no-op fallback.
        "ALTER TABLE subagent_runs ADD COLUMN IF NOT EXISTS substantive_tool_calls INTEGER DEFAULT 0",
    ]),
    (10, "v2.34.14 — agent_llm_traces + agent_llm_system_prompts for LLM trace persistence", [
        """CREATE TABLE IF NOT EXISTS agent_llm_traces (
            operation_id    TEXT NOT NULL,
            step_index      INTEGER NOT NULL,
            timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            agent_type      TEXT,
            is_subagent     BOOLEAN NOT NULL DEFAULT FALSE,
            parent_op_id    TEXT,
            messages_delta  JSONB NOT NULL,
            response_raw    JSONB NOT NULL,
            tokens_prompt     INTEGER,
            tokens_completion INTEGER,
            tokens_total      INTEGER,
            temperature       REAL,
            model             TEXT,
            finish_reason     TEXT,
            tool_calls_count  INTEGER DEFAULT 0,
            PRIMARY KEY (operation_id, step_index)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_llm_traces_parent ON agent_llm_traces (parent_op_id) WHERE parent_op_id IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS idx_llm_traces_ts ON agent_llm_traces (timestamp DESC)",
        """CREATE TABLE IF NOT EXISTS agent_llm_system_prompts (
            operation_id    TEXT PRIMARY KEY,
            system_prompt   TEXT NOT NULL,
            tools_manifest  JSONB NOT NULL,
            prompt_chars    INTEGER,
            tools_count     INTEGER,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
    ]),
]


async def _ensure_versions_table(conn) -> None:
    """Create schema_versions table if it doesn't exist."""
    from api.db.base import DB_BACKEND
    if DB_BACKEND == "postgres":
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_versions (
                id          SERIAL PRIMARY KEY,
                version     INTEGER NOT NULL UNIQUE,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                description TEXT
            )
        """))
    else:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_versions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                version     INTEGER NOT NULL UNIQUE,
                applied_at  TEXT NOT NULL,
                description TEXT
            )
        """))


async def _current_version(conn) -> int:
    row = await conn.execute(text("SELECT MAX(version) as v FROM schema_versions"))
    result = row.fetchone()
    return result[0] if result and result[0] is not None else 0


async def _record_version(conn, version: int, description: str) -> None:
    from api.db.base import DB_BACKEND
    now = datetime.now(timezone.utc).isoformat()
    if DB_BACKEND == "postgres":
        await conn.execute(
            text("INSERT INTO schema_versions (version, description) VALUES (:v, :d)"),
            {"v": version, "d": description},
        )
    else:
        await conn.execute(
            text("INSERT INTO schema_versions (version, applied_at, description) VALUES (:v, :ts, :d)"),
            {"v": version, "ts": now, "d": description},
        )


async def run_migrations(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        # Create all tables (CREATE IF NOT EXISTS — safe to re-run)
        await conn.run_sync(metadata.create_all)
        await _ensure_versions_table(conn)
        current = await _current_version(conn)
        log.info(f"DB schema at version {current}")

        for version, description, sql_stmts in MIGRATIONS:
            if version <= current:
                continue
            log.info(f"Applying migration v{version}: {description}")
            for stmt in sql_stmts:
                try:
                    await conn.execute(text(stmt))
                except Exception as e:
                    # Index may already exist — log and continue
                    log.warning(f"Migration v{version} stmt skipped: {e}")
            await _record_version(conn, version, description)
            log.info(f"Migration v{version} applied")
