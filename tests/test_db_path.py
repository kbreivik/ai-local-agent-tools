"""
TDD: verify SQLite path falls back to a __file__-relative path, not an absolute
Windows path, when neither SQLITE_PATH nor DB_PATH env vars are set.
"""
import os
import importlib
from pathlib import Path
import pytest


def _reload_base():
    """Reload api.db.base with clean env (no SQLITE_PATH / DB_PATH)."""
    import api.db.base as mod
    return importlib.reload(mod)


def test_db_path_no_env_vars(monkeypatch):
    """Without env vars, _SQLITE_PATH must be relative to the project root."""
    monkeypatch.delenv("SQLITE_PATH", raising=False)
    monkeypatch.delenv("DB_PATH", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    mod = _reload_base()
    path = mod._SQLITE_PATH

    # Must end with data/hp1_agent.db (using posix-style comparison)
    assert path.parts[-1] == "hp1_agent.db", f"Wrong filename: {path}"
    assert path.parts[-2] == "data", f"Wrong parent dir: {path}"

    # Must NOT contain any Windows drive letter or absolute Windows path component
    path_str = str(path)
    assert "D:/claude_code" not in path_str, (
        f"DB path still contains hard-coded Windows path: {path_str}"
    )
    assert "C:/claude_code" not in path_str, (
        f"DB path contains hard-coded Windows path: {path_str}"
    )

    # Path must be resolvable — parent directory exists (project root / data)
    project_root = Path(__file__).parent.parent
    expected = project_root / "data" / "hp1_agent.db"
    assert path == expected, (
        f"Expected {expected}, got {path}"
    )


def test_db_path_env_sqlite_path_override(monkeypatch, tmp_path):
    """SQLITE_PATH env var must override the default."""
    custom = tmp_path / "custom.db"
    monkeypatch.setenv("SQLITE_PATH", str(custom))
    monkeypatch.delenv("DB_PATH", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    mod = _reload_base()
    assert mod._SQLITE_PATH == custom, (
        f"SQLITE_PATH override not respected: {mod._SQLITE_PATH}"
    )


def test_db_path_env_db_path_fallback(monkeypatch, tmp_path):
    """DB_PATH env var must be used when SQLITE_PATH is unset."""
    custom = tmp_path / "fallback.db"
    monkeypatch.delenv("SQLITE_PATH", raising=False)
    monkeypatch.setenv("DB_PATH", str(custom))
    monkeypatch.delenv("DATABASE_URL", raising=False)

    mod = _reload_base()
    assert mod._SQLITE_PATH == custom, (
        f"DB_PATH fallback not respected: {mod._SQLITE_PATH}"
    )
