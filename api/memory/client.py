"""
MuninnDB REST client — async, graceful fallback when server unavailable.

MuninnDB exposes REST on localhost:9475 (proxied via socat sidecar).
All methods return empty/None on failure — callers should not depend on
memory being available for correctness.
"""
import logging
import os
from typing import Optional

import httpx

log = logging.getLogger(__name__)

MUNINNDB_URL = (
    os.environ.get("MUNINN_URL")
    or os.environ.get("MUNINNDB_URL")
    or "http://localhost:9475"
)
log.info("[MuninnDB] using URL: %s", MUNINNDB_URL)
_TIMEOUT = 3.0


class MuninnClient:
    """Thin async wrapper around MuninnDB REST API. Thread-safe singleton."""

    def __init__(self, base_url: str = MUNINNDB_URL):
        self._base = base_url.rstrip("/")
        self._http: Optional[httpx.AsyncClient] = None

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                base_url=self._base,
                timeout=_TIMEOUT,
                headers={"Content-Type": "application/json"},
            )
        return self._http

    async def close(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()
        self._http = None

    # ── Core API ──────────────────────────────────────────────────────────────

    async def store(
        self,
        concept: str,
        content: str,
        tags: list[str] | None = None,
    ) -> str | None:
        """Store an engram. Returns engram ID or None on failure."""
        try:
            http = await self._get_http()
            resp = await http.post("/api/engrams", json={
                "concept": concept,
                "content": content,
                "tags": tags or [],
            })
            resp.raise_for_status()
            return resp.json().get("id")
        except Exception as e:
            log.debug("MuninnDB store failed: %s", e)
            return None

    async def activate(
        self,
        context: list[str],
        max_results: int = 5,
    ) -> list[dict]:
        """Retrieve engrams relevant to context via Hebbian activation."""
        try:
            http = await self._get_http()
            resp = await http.post("/api/activate", json={
                "context": context,
                "max_results": max_results,
            })
            resp.raise_for_status()
            return resp.json().get("activations", [])
        except Exception as e:
            log.debug("MuninnDB activate failed: %s", e)
            return []

    async def search(self, query: str, limit: int = 20) -> list[dict]:
        """Full-text search over engrams."""
        try:
            http = await self._get_http()
            resp = await http.get("/api/engrams", params={"q": query, "limit": limit})
            resp.raise_for_status()
            return resp.json().get("engrams", [])
        except Exception as e:
            log.debug("MuninnDB search failed: %s", e)
            return []

    async def recent(self, limit: int = 20) -> list[dict]:
        """Return most recently stored engrams."""
        try:
            http = await self._get_http()
            resp = await http.get("/api/engrams", params={"limit": limit})
            resp.raise_for_status()
            return resp.json().get("engrams", [])
        except Exception as e:
            log.debug("MuninnDB recent failed: %s", e)
            return []

    async def delete(self, engram_id: str) -> bool:
        """Delete an engram by ID."""
        try:
            http = await self._get_http()
            resp = await http.delete(f"/api/engrams/{engram_id}")
            return resp.status_code in (200, 204)
        except Exception as e:
            log.debug("MuninnDB delete failed: %s", e)
            return False

    async def health(self) -> bool:
        """Return True if MuninnDB REST API is reachable."""
        try:
            http = await self._get_http()
            resp = await http.get("/api/engrams", params={"limit": 1})
            return resp.status_code == 200
        except Exception:
            return False


# ── Module-level singleton ─────────────────────────────────────────────────────

_client: MuninnClient | None = None


def get_client() -> MuninnClient:
    global _client
    if _client is None:
        _client = MuninnClient()
    return _client


async def close_client() -> None:
    global _client
    if _client:
        await _client.close()
        _client = None
