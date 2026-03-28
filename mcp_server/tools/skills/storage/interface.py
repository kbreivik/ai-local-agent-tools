"""Storage backend interface — every backend implements this contract.

All methods are synchronous (matching project convention).
All methods return dicts or lists of dicts — never ORM objects or DB cursors.
"""
from abc import ABC, abstractmethod
from typing import Any


class StorageBackend(ABC):

    # ── Lifecycle ────────────────────────────────────────────────────────────

    @abstractmethod
    def init(self) -> None:
        """Create tables/schema if they don't exist. Idempotent."""

    @abstractmethod
    def close(self) -> None:
        """Close connections. Called on shutdown."""

    @abstractmethod
    def health_check(self) -> dict:
        """Return {"ok": bool, "backend": str, "details": str}."""

    # ── Skills Registry ──────────────────────────────────────────────────────

    @abstractmethod
    def register_skill(self, meta: dict, file_path: str, **kwargs) -> dict: ...

    @abstractmethod
    def get_skill(self, name: str) -> dict | None: ...

    @abstractmethod
    def search_skills(self, query: str, category: str = "") -> list[dict]: ...

    @abstractmethod
    def list_skills(self, category: str = "", enabled_only: bool = True) -> list[dict]: ...

    @abstractmethod
    def update_skill(self, name: str, **fields) -> dict: ...

    @abstractmethod
    def delete_skill(self, name: str) -> dict: ...

    @abstractmethod
    def increment_call(self, name: str) -> None: ...

    @abstractmethod
    def record_error(self, name: str, error: str) -> None: ...

    # ── Service Catalog ──────────────────────────────────────────────────────

    @abstractmethod
    def upsert_service(self, service_id: str, **fields) -> dict: ...

    @abstractmethod
    def get_service(self, service_id: str) -> dict | None: ...

    @abstractmethod
    def list_services(self) -> list[dict]: ...

    # ── Breaking Changes ─────────────────────────────────────────────────────

    @abstractmethod
    def add_breaking_change(self, service_id: str, to_version: str, description: str, **kwargs) -> dict: ...

    @abstractmethod
    def get_breaking_changes(self, service_id: str, unresolved_only: bool = False) -> list[dict]: ...

    @abstractmethod
    def resolve_breaking_change(self, change_id: int) -> dict: ...

    @abstractmethod
    def update_breaking_change_skills(self, change_id: int, affected_skills: list) -> None: ...

    # ── Compat Log ───────────────────────────────────────────────────────────

    @abstractmethod
    def log_compat_check(self, skill_name: str, service_id: str, **kwargs) -> None: ...

    @abstractmethod
    def get_compat_history(self, skill_name: str, limit: int = 10) -> list[dict]: ...

    # ── Audit Log ────────────────────────────────────────────────────────────

    @abstractmethod
    def append_audit(self, action: str, result: Any) -> None: ...

    @abstractmethod
    def query_audit(self, action_prefix: str = "", limit: int = 50, offset: int = 0) -> list[dict]: ...

    # ── Checkpoints ──────────────────────────────────────────────────────────

    @abstractmethod
    def save_checkpoint(self, label: str, data: dict) -> dict: ...

    @abstractmethod
    def load_checkpoint(self, label: str) -> dict | None: ...

    @abstractmethod
    def list_checkpoints(self, limit: int = 20) -> list[dict]: ...

    # ── Settings ─────────────────────────────────────────────────────────────

    @abstractmethod
    def get_setting(self, key: str) -> Any: ...

    @abstractmethod
    def set_setting(self, key: str, value: Any) -> None: ...

    # ── Generation Log ───────────────────────────────────────────────────────

    @abstractmethod
    def write_generation_log(self, row: dict) -> None:
        """Write one generation trace row. row must have all skill_generation_log columns.

        Raises sqlite3.IntegrityError (SQLite) or psycopg2.IntegrityError (PostgreSQL) on
        duplicate id. Callers should generate a fresh UUID per row to avoid this.
        """

    @abstractmethod
    def get_generation_log(self, skill_name: str = "", outcome: str = "", limit: int = 50) -> list[dict]:
        """Return log rows, JSON fields pre-parsed to dicts/lists. Ordered by created_at DESC."""
