"""WebSocket manager — broadcasts streamed agent output to all connected GUI clients."""
import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self._connections: list[WebSocket] = []
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        # Lazy init — must be created inside a running event loop (Python 3.10+)
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self._get_lock():
            self._connections.append(ws)

    async def disconnect(self, ws: WebSocket):
        async with self._get_lock():
            if ws in self._connections:
                self._connections.remove(ws)

    async def broadcast(self, message: dict[str, Any]):
        payload = json.dumps(message)
        async with self._get_lock():
            dead = []
            for ws in self._connections:
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._connections.remove(ws)

    async def send_line(self, line_type: str, content: str, tool: str = "", status: str = "",
                        session_id: str = ""):
        """Send a typed output line to all GUI clients."""
        msg: dict[str, Any] = {
            "type": line_type,       # "step" | "tool" | "reasoning" | "halt" | "done" | "error"
            "content": content,
            "tool": tool,
            "status": status,        # "ok" | "degraded" | "failed" | "escalated" | ""
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if session_id:
            msg["session_id"] = session_id
        await self.broadcast(msg)

    @property
    def active_count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()
