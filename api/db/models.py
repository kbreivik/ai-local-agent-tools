"""
SQLAlchemy Core table definitions — shared between Postgres and SQLite backends.
JSONB is used for Postgres, JSON for SQLite (handled via type_coerce in queries).
"""
import os
from sqlalchemy import (
    Column, MetaData, Table, Text, Integer, Boolean,
    DateTime, ForeignKey, func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy import JSON

metadata = MetaData()

_IS_POSTGRES = bool(os.environ.get("DATABASE_URL"))


def _uuid_col(name: str, primary_key: bool = False, **kw):
    """UUID column — native UUID on Postgres, TEXT on SQLite."""
    if _IS_POSTGRES:
        return Column(name, PG_UUID(as_uuid=True), primary_key=primary_key,
                      server_default=func.gen_random_uuid() if primary_key else None, **kw)
    return Column(name, Text, primary_key=primary_key, **kw)


def _json_col(name: str, **kw):
    """JSONB on Postgres, JSON on SQLite."""
    return Column(name, JSONB if _IS_POSTGRES else JSON, **kw)


def _ts_col(name: str, **kw):
    return Column(name, DateTime(timezone=True), **kw)


# ── Tables ────────────────────────────────────────────────────────────────────

schema_versions = Table(
    "schema_versions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("version", Integer, nullable=False, unique=True),
    _ts_col("applied_at", nullable=False, server_default=func.now()),
    Column("description", Text),
)

operations = Table(
    "operations", metadata,
    _uuid_col("id", primary_key=True),
    Column("session_id", Text, nullable=False),
    Column("label", Text),
    _ts_col("started_at", nullable=False, server_default=func.now()),
    _ts_col("completed_at"),
    Column("status", Text, nullable=False, server_default="running"),
    Column("triggered_by", Text),
    Column("model_used", Text),
    Column("total_duration_ms", Integer),
    Column("feedback", Text),
    Column("feedback_at", Text),
    Column("final_answer", Text),
)

tool_calls = Table(
    "tool_calls", metadata,
    _uuid_col("id", primary_key=True),
    Column("operation_id", Text, ForeignKey("operations.id", ondelete="SET NULL"), nullable=True),
    Column("tool_name", Text, nullable=False),
    _json_col("params"),
    _json_col("result"),
    Column("status", Text, nullable=False, server_default="ok"),
    Column("model_used", Text),
    Column("duration_ms", Integer),
    _ts_col("timestamp", nullable=False, server_default=func.now()),
    Column("error_detail", Text),
)

status_snapshots = Table(
    "status_snapshots", metadata,
    _uuid_col("id", primary_key=True),
    Column("component", Text, nullable=False),
    _json_col("state"),
    Column("is_healthy", Boolean),
    _ts_col("timestamp", nullable=False, server_default=func.now()),
)

escalations = Table(
    "escalations", metadata,
    _uuid_col("id", primary_key=True),
    Column("operation_id", Text, ForeignKey("operations.id", ondelete="SET NULL"), nullable=True),
    Column("tool_call_id", Text, nullable=True),
    Column("reason", Text, nullable=False),
    _json_col("context"),
    Column("resolved", Boolean, nullable=False, server_default="false"),
    _ts_col("resolved_at"),
    _ts_col("timestamp", nullable=False, server_default=func.now()),
)

audit_log = Table(
    "audit_log", metadata,
    _uuid_col("id", primary_key=True),
    Column("event_type", Text, nullable=False),
    Column("entity_id", Text),
    Column("entity_type", Text),
    _json_col("detail"),
    _ts_col("timestamp", nullable=False, server_default=func.now()),
    Column("source", Text),
)
