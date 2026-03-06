"""Database layer — auto-selects Postgres or SQLite from DATABASE_URL env var."""
from api.db.base import get_engine, get_connection, init_db, DB_BACKEND

__all__ = ["get_engine", "get_connection", "init_db", "DB_BACKEND"]
