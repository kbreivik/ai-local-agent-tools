"""Storage backend factory. Call get_backend() to get the active backend.

Auto-detects PostgreSQL on first call; falls back to SQLite if unavailable.
Everything is a singleton — detection runs once at startup.
"""
import logging

log = logging.getLogger(__name__)

_backend = None
_cache = None


def get_backend():
    """Return the active StorageBackend (singleton). Auto-detects on first call."""
    global _backend
    if _backend is None:
        from mcp_server.tools.skills.storage.auto_detect import detect_backend
        _backend = detect_backend()
    return _backend


def get_cache():
    """Return the Redis CacheBackend (singleton), or None if unavailable."""
    global _cache
    if _cache is None:
        from mcp_server.tools.skills.storage.auto_detect import detect_cache
        _cache = detect_cache()  # May return None — that's fine
    return _cache


def shutdown():
    """Close all connections. Call on app shutdown."""
    global _backend, _cache
    if _backend:
        try:
            _backend.close()
        except Exception:
            pass
        _backend = None
    if _cache:
        try:
            _cache.close()
        except Exception:
            pass
        _cache = None
