"""Optional Redis cache layer.

Read-through cache for hot read paths: skill metadata, service catalog.
NOT used for audit_log or checkpoints (write-heavy, no benefit).
Everything works fine without Redis — callers get None from get_cache().
"""
import json
import logging
from typing import Any

log = logging.getLogger(__name__)

_SKILL_TTL = 300      # 5 minutes — skills change infrequently
_SERVICE_TTL = 60     # 1 minute — version info can change after upgrades
_DEFAULT_TTL = 300


class RedisCache:
    """Read-through cache backed by Redis. Optional — never required for correctness."""

    def __init__(self, url: str):
        import redis
        self.client = redis.from_url(url, decode_responses=True)
        self._url = url

    def health_check(self) -> dict:
        try:
            self.client.ping()
            return {"ok": True, "backend": "redis", "details": self._url.split("@")[-1]}
        except Exception as e:
            return {"ok": False, "backend": "redis", "details": str(e)}

    def get(self, key: str) -> Any:
        try:
            val = self.client.get(key)
            return json.loads(val) if val else None
        except Exception:
            return None

    def set(self, key: str, value: Any, ttl: int = _DEFAULT_TTL) -> None:
        try:
            self.client.setex(key, ttl, json.dumps(value, default=str))
        except Exception:
            pass  # Cache failures are non-fatal

    def delete(self, key: str) -> None:
        try:
            self.client.delete(key)
        except Exception:
            pass

    def invalidate_prefix(self, prefix: str) -> None:
        """Delete all keys with a given prefix. Call after writes."""
        try:
            keys = list(self.client.scan_iter(f"{prefix}*"))
            if keys:
                self.client.delete(*keys)
        except Exception:
            pass

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass
