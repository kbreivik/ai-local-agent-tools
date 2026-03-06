"""SQLite setup via aiosqlite. Tables: operations, tool_calls, status_snapshots."""
import os
from pathlib import Path
import aiosqlite

DB_PATH = Path(os.environ.get("DB_PATH", "D:/claude_code/FAJK/HP1-AI-Agent-v1/data/hp1_agent.db"))

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS operations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    label       TEXT,
    started_at  TEXT NOT NULL,
    completed_at TEXT,
    status      TEXT NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id INTEGER REFERENCES operations(id),
    tool_name    TEXT NOT NULL,
    params       TEXT,
    result       TEXT,
    status       TEXT NOT NULL DEFAULT 'running',
    model_used   TEXT,
    duration_ms  INTEGER,
    timestamp    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS status_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    component   TEXT NOT NULL,
    state_json  TEXT NOT NULL,
    timestamp   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_op   ON tool_calls(operation_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_ts   ON tool_calls(timestamp);
CREATE INDEX IF NOT EXISTS idx_snapshots_comp  ON status_snapshots(component);
"""


async def get_db() -> aiosqlite.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(CREATE_TABLES)
        await db.commit()
