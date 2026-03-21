"""Skill registry — public API for all skill/service/compat DB operations.

Delegates to the auto-detected storage backend (SQLite or PostgreSQL).
Public function signatures are unchanged from v1 — all callers work as-is.
"""
import os
from datetime import datetime, timezone


_IMPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "data", "skill_imports"
)


def _db():
    """Return the active storage backend."""
    from mcp_server.tools.skills.storage import get_backend
    return get_backend()


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Initialization ────────────────────────────────────────────────────────────

def init_db() -> None:
    """Ensure the storage backend is initialized. Idempotent."""
    _db()  # get_backend() calls init() on first access


# ── Skills ────────────────────────────────────────────────────────────────────

def register_skill(
    meta: dict,
    file_path: str,
    auto_generated: bool = False,
    generation_mode: str = "manual",
) -> dict:
    return _db().register_skill(
        meta, file_path,
        auto_generated=auto_generated,
        generation_mode=generation_mode,
    )


def search_skills(query: str, category: str = "") -> list[dict]:
    return _db().search_skills(query, category)


def list_skills(category: str = "", enabled_only: bool = True) -> list[dict]:
    return _db().list_skills(category, enabled_only)


def get_skill(name: str) -> dict | None:
    return _db().get_skill(name)


def increment_call(name: str) -> None:
    _db().increment_call(name)


def record_error(name: str, error: str) -> None:
    _db().record_error(name, error)


def disable_skill(name: str) -> dict:
    _db().update_skill(name, enabled=False)
    return {"name": name, "enabled": False}


def enable_skill(name: str) -> dict:
    _db().update_skill(name, enabled=True)
    return {"name": name, "enabled": True}


def delete_skill(name: str) -> dict:
    return _db().delete_skill(name)


# ── Service Catalog ───────────────────────────────────────────────────────────

def upsert_service(service_id: str, display_name: str, service_type: str = "", **kwargs) -> dict:
    return _db().upsert_service(
        service_id,
        display_name=display_name,
        service_type=service_type,
        **kwargs,
    )


def get_service(service_id: str) -> dict | None:
    return _db().get_service(service_id)


def list_services() -> list[dict]:
    return _db().list_services()


def update_service_version(service_id: str, version: str, source: str = "skill_probe") -> dict:
    """Update detected version for a service. Creates entry if not present."""
    existing = get_service(service_id)
    if existing:
        return _db().upsert_service(
            service_id,
            display_name=existing.get("display_name", service_id),
            detected_version=version,
            version_source=source,
            last_checked=_ts(),
        )
    return upsert_service(
        service_id,
        service_id.replace("_", " ").title(),
        detected_version=version,
        version_source=source,
        last_checked=_ts(),
    )


# ── Breaking Changes ──────────────────────────────────────────────────────────

def add_breaking_change(service_id: str, to_version: str, description: str, **kwargs) -> dict:
    return _db().add_breaking_change(service_id, to_version, description, **kwargs)


def get_breaking_changes(service_id: str, from_version: str = "", to_version: str = "") -> list[dict]:
    return _db().get_breaking_changes(service_id, unresolved_only=True)


def get_unresolved_breaking_changes() -> list[dict]:
    db = _db()
    if hasattr(db, "get_all_unresolved_breaking_changes"):
        return db.get_all_unresolved_breaking_changes()
    return []


def resolve_breaking_change(change_id: int) -> dict:
    return _db().resolve_breaking_change(change_id)


def update_breaking_change_skills(change_id: int, affected_skills: list) -> None:
    _db().update_breaking_change_skills(change_id, affected_skills)


# ── Compat Log ────────────────────────────────────────────────────────────────

def log_compat_check(
    skill_name: str,
    service_id: str,
    detected_version: str,
    compatible,
    **kwargs,
) -> None:
    _db().log_compat_check(
        skill_name, service_id,
        detected_version=detected_version,
        compatible=compatible,
        **kwargs,
    )


def get_compat_history(skill_name: str, limit: int = 10) -> list[dict]:
    return _db().get_compat_history(skill_name, limit)


# ── Utility ───────────────────────────────────────────────────────────────────

def list_pending_imports() -> list[dict]:
    """Scan skill_imports dir for .py files. File-system only — not stored in DB."""
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
