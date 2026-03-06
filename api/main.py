"""FastAPI application entry point — HP1 AI Agent backend."""
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.db import init_db
from api.websocket import manager
from api.routers import tools, agent, status, logs

HOST = os.environ.get("API_HOST", "0.0.0.0")
PORT = int(os.environ.get("API_PORT", "8000"))

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://0.0.0.0:5173",
    # Allow any LAN IP on common ports
    "http://192.168.0.0/16",
]
# Allow all origins in dev — tighten in production
CORS_ORIGINS_ALL = os.environ.get("CORS_ALLOW_ALL", "true").lower() == "true"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="HP1 AI Agent API",
    description="Local AI infrastructure orchestration — Docker Swarm + Kafka",
    version="1.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if CORS_ORIGINS_ALL else CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(tools.router)
app.include_router(agent.router)
app.include_router(status.router)
app.include_router(logs.router)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "service": "HP1-AI-Agent",
        "version": "1.2.0",
        "ws_clients": manager.active_count,
    }


@app.websocket("/ws/output")
async def websocket_output(ws: WebSocket):
    """WebSocket endpoint — streams agent output to GUI in real time."""
    await manager.connect(ws)
    try:
        # Keep alive — client can send pings
        while True:
            try:
                data = await ws.receive_text()
                if data == "ping":
                    await ws.send_text('{"type":"pong"}')
            except WebSocketDisconnect:
                break
    finally:
        await manager.disconnect(ws)


# Serve built React GUI if present
_gui_dist = Path(__file__).parent.parent / "gui" / "dist"
if _gui_dist.exists():
    app.mount("/", StaticFiles(directory=str(_gui_dist), html=True), name="gui")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host=HOST,
        port=PORT,
        reload=True,
        reload_dirs=[str(Path(__file__).parent)],
    )
