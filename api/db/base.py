"""
Connection factory — picks Postgres (asyncpg) or SQLite (aiosqlite) based on
DATABASE_URL. Setting DATABASE_URL automatically switches the backend; all other
code is unchanged.

Postgres:  DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
SQLite:    (unset — uses SQLITE_PATH or default data/hp1_agent.db)
"""
import os
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

# ── Configuration ─────────────────────────────────────────────────────────────

_DATABASE_URL: str | None = os.environ.get("DATABASE_URL")
_PROJECT_ROOT = Path(__file__).parent.parent.parent  # api/db/base.py → api/db/ → api/ → project root
_SQLITE_PATH = Path(os.environ.get(
    "SQLITE_PATH",
    os.environ.get("DB_PATH", str(_PROJECT_ROOT / "data" / "hp1_agent.db"))
))

DB_BACKEND: str = "postgres" if _DATABASE_URL else "sqlite"

# ── Engine ─────────────────────────────────────────────────────────────────────

_engine: AsyncEngine | None = None


def _build_url() -> str:
    if _DATABASE_URL:
        return _DATABASE_URL
    _SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{_SQLITE_PATH}"


def _build_engine() -> AsyncEngine:
    url = _build_url()
    if DB_BACKEND == "postgres":
        return create_async_engine(
            url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            echo=False,
        )
    else:
        return create_async_engine(
            url,
            connect_args={"check_same_thread": False},
            echo=False,
        )


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


_sync_engine = None


def get_sync_engine():
    """Return a plain synchronous SQLAlchemy engine for use in sync collectors/workers.

    Uses sqlite (not aiosqlite) or psycopg2 (not asyncpg) so callers can use
    engine.begin() from any thread without triggering SQLAlchemy's greenlet machinery.
    """
    global _sync_engine
    if _sync_engine is None:
        from sqlalchemy import create_engine
        url = _build_url()
        sync_url = url.replace("sqlite+aiosqlite", "sqlite").replace(
            "postgresql+asyncpg", "postgresql+psycopg2"
        )
        _sync_engine = create_engine(sync_url, connect_args={"check_same_thread": False}
                                     if DB_BACKEND == "sqlite" else {})
    return _sync_engine


async def get_connection() -> AsyncGenerator[AsyncConnection, None]:
    """Yield an open AsyncConnection (context-manager usage recommended)."""
    async with get_engine().connect() as conn:
        yield conn


async def init_db():
    """Create schema and run migrations on startup."""
    from api.db.migrations import run_migrations
    await run_migrations(get_engine())
