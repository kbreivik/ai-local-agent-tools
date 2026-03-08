"""FastAPI application entry point — HP1 AI Agent backend."""
import os
import socket
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.db import init_db
from api.logger import ensure_started as _start_logger, flush_now as _flush_logger
from api.websocket import manager
from api.routers import tools, agent, status, logs, alerts, memory as memory_router, elastic as elastic_router, settings as settings_router
from api.routers import tests_api as tests_router
from api.routers import feedback as feedback_router
from api.collectors import manager as collector_manager
from api.memory.client import close_client as _close_memory
from api.memory.ingest import ingest_runbooks

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
    await _start_logger()
    collector_manager.start_all()
    # Ingest runbooks into MuninnDB (non-blocking — failures are logged, not raised)
    try:
        await ingest_runbooks()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Memory ingest skipped: %s", e)
    yield
    collector_manager.stop_all()
    await _close_memory()
    await _flush_logger()


app = FastAPI(
    title="HP1 AI Agent API",
    description="Local AI infrastructure orchestration — Docker Swarm + Kafka",
    version="1.6.5",
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
app.include_router(alerts.router)
app.include_router(memory_router.router)
app.include_router(elastic_router.router)
app.include_router(settings_router.router)
app.include_router(tests_router.router)
app.include_router(feedback_router.router)


def _get_host_ips() -> dict:
    try:
        hostname = socket.gethostname()
        try:
            all_ips = socket.gethostbyname_ex(hostname)[2]
        except Exception:
            all_ips = [socket.gethostbyname(hostname)]
        lan_ips = [
            ip for ip in all_ips
            if not ip.startswith('127.')
            and not ip.startswith('172.')
            and not ip.startswith('169.')
        ]
        return {
            "hostname": hostname,
            "lan_ips":  lan_ips,
            "all_ips":  all_ips,
            "api_url":  f"http://{lan_ips[0]}:8000" if lan_ips else None,
            "gui_url":  f"http://{lan_ips[0]}:5173" if lan_ips else None,
        }
    except Exception:
        return {"hostname": "unknown", "lan_ips": [], "all_ips": []}


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "service": "HP1-AI-Agent",
        "version": "1.6.5",
        "ws_clients": manager.active_count,
        "network": _get_host_ips(),
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
        reload_dirs=[str(Path(__file__).parent), str(Path(__file__).parent.parent / "mcp_server")],
    )
