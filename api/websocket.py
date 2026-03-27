"""WebSocket manager — broadcasts streamed agent output to all connected GUI clients."""
import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Optional

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

    async def connect(self, ws: WebSocket, token: Optional[str] = None):
        """Accept the WebSocket connection. If token is provided, validate it.
        Invalid token closes the connection with code 1008 (policy violation).
        """
        if token:
            try:
                from api.auth import decode_token
                decode_token(token)
            except Exception:
                # Accept first so the browser receives a proper 1008 close code
                # (without accept, the upgrade returns HTTP 403 and the browser
                # gets code=1006/abnormal, making auth errors indistinguishable
                # from network errors)
                await ws.accept()
                await ws.close(code=1008)
                return
        await ws.accept()
        async with self._get_lock():
            self._connections.append(ws)

    async def disconnect(self, ws: WebSocket):
        async with self._get_lock():
            if ws in self._connections:
                self._connections.remove(ws)

    async def broadcast(self, message: dict[str, Any]):
        payload = json.dumps(message)
        # Store line for session replay
        session_id = message.get("session_id", "")
        msg_type = message.get("type", "")
        content = message.get("content", "")
        if session_id:
            try:
                from api.session_store import store_line
                metadata = {k: v for k, v in message.items()
                            if k not in ("session_id", "type", "content", "timestamp")}
                store_line(session_id, msg_type, content, metadata)
            except Exception:
                pass

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

    async def get_replay(self, session_id: str) -> list[dict]:
        """Return stored lines for a session from DB."""
        try:
            from api.session_store import get_replay_lines
            return await get_replay_lines(session_id)
        except Exception:
            return []

    @property
    def active_count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()
