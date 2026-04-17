"""FastAPI application entry point — HP1 AI Agent backend."""
import os
import socket
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from typing import Optional

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.db import init_db
from api.logger import ensure_started as _start_logger, flush_now as _flush_logger
from api.websocket import manager
from api.auth import get_current_user, check_secrets
from api.routers import tools, agent, status, logs, alerts, memory as memory_router, elastic as elastic_router, settings as settings_router
from api.routers import tests_api as tests_router
from api.routers import feedback as feedback_router
from api.routers.auth import router as auth_router
from api.routers.lock import router as lock_router
from api.routers.ansible import router as ansible_router
from api.routers.ingest import router as ingest_router
from api.routers.skills import router as skills_router
from api.routers.dashboard import router as dashboard_router
from api.routers.connections import router as connections_router
from api.routers.notifications import router as notifications_router
from api.routers.credential_profiles import router as cred_profiles_router
from api.routers.layout import router as layout_router
from api.routers.escalations import router as escalations_router, init_escalations
from api.routers.agent_actions_api import router as agent_actions_router
from api.routers.agent_blackouts_api import router as agent_blackouts_router
from api.routers.errors import router as errors_router
from api.routers.users import router as users_router
from api.routers.entities import router as entities_router
from api.routers.vm_exec_allowlist import router as vm_exec_allowlist_router
from api.routers.runbooks import router as runbooks_router
from api.routers.maintenance import router as maintenance_router
from api.routers.discovery import router as discovery_router
from api.routers.card_templates import router as card_templates_router
from api.routers.display_aliases import router as display_aliases_router
from api.routers.docs import router as docs_router
from api.routers.kafka_overview import router as kafka_overview_router
from api.db.entity_maintenance import init_maintenance
from api.routers.settings import seed_defaults as _seed_settings, sync_env_from_db as _sync_env
from api.constants import APP_NAME, APP_VERSION, DEFAULT_API_PORT, DEFAULT_GUI_PORT
from api.session_store import ensure_started as _start_session_store
from api.collectors import manager as collector_manager
from api.memory.client import close_client as _close_memory
from api.memory.ingest import ingest_runbooks
from mcp_server.tools.skills import loader as _skill_loader
from mcp_server.tools.skills import registry as _skill_registry
from api.metrics import render_metrics, BUILD
import json as _json

def _load_build_info() -> dict | None:
    """Load api/build_info.json if present. Returns None if absent.

    In the container: main.py is at /app/api/main.py and build_info.json
    is at /app/api/build_info.json — so Path(__file__).parent is correct.
    Locally: same relative layout (api/main.py → api/build_info.json).
    """
    path = Path(__file__).parent / "build_info.json"
    try:
        return _json.loads(path.read_text())
    except (OSError, _json.JSONDecodeError):
        return None

_BUILD_INFO = _load_build_info()

HOST = os.environ.get("API_HOST", "0.0.0.0")
PORT = int(os.environ.get("API_PORT", str(DEFAULT_API_PORT)))

_DEFAULT_CORS = [
    f"http://localhost:{DEFAULT_GUI_PORT}",
    f"http://127.0.0.1:{DEFAULT_GUI_PORT}",
]
# CORS_ORIGINS env var: comma-separated list of additional allowed origins.
# Example: CORS_ORIGINS=http://192.168.1.10:8000,http://myhost:8000
_extra = os.environ.get("CORS_ORIGINS", "")
CORS_ORIGINS = _DEFAULT_CORS + [o.strip() for o in _extra.split(",") if o.strip()]
# CORS_ALLOW_ALL=true enables wildcard origins (dev convenience). Default is false (restrictive).
CORS_ORIGINS_ALL = os.environ.get("CORS_ALLOW_ALL", "false").lower() == "true"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Populate Prometheus build info once per process
    try:
        _version_path = Path(__file__).parent.parent / "VERSION"
        BUILD.info({"version": _version_path.read_text().strip()})
    except Exception:
        pass
    # Crypto boot-safety: refuse to start if env key is missing but encrypted data exists
    from api.crypto import check_encryption_key_safe
    check_encryption_key_safe()
    check_secrets()
    await _start_logger()
    await _start_session_store()
    import logging as _logging
    _log = _logging.getLogger(__name__)
    if _BUILD_INFO:
        _log.info("Build info: v%s commit=%s branch=%s build=#%s",
                  _BUILD_INFO.get("version"), _BUILD_INFO.get("commit"),
                  _BUILD_INFO.get("branch"), _BUILD_INFO.get("build_number"))
    else:
        _log.warning("build_info.json not found — run scripts/gen_build_info.py before docker build")
    # Seed settings from env vars on first run (no-op if already seeded), then
    # mirror DB → os.environ so collectors pick up user-saved values on restart.
    try:
        _seed_settings()
        _sync_env()
    except Exception as e:
        _log.warning("Settings seed/sync skipped: %s", e)
    # Encrypt any plaintext secrets in settings table (one-time migration)
    try:
        from api.settings_manager import migrate_plaintext_secrets
        from api.routers.settings import SETTINGS_KEYS
        migrate_plaintext_secrets(SETTINGS_KEYS)
    except Exception as e:
        _log.debug("Secret encryption migration skipped: %s", e)
    # Seed crypto canary row for future key-drift detection
    try:
        from api.crypto import ensure_crypto_canary
        ensure_crypto_canary()
    except Exception as e:
        _log.debug("Crypto canary seed skipped: %s", e)
    # Initialize pgvector RAG schema (no-op if pgvector unavailable)
    try:
        from api.rag.schema import init_doc_chunks
        init_doc_chunks()
    except Exception as e:
        _log.debug("RAG schema init skipped: %s", e)
    # Initialize connections table
    try:
        from api.connections import init_connections
        init_connections()
    except Exception as e:
        _log.debug("Connections table init skipped: %s", e)
    # Initialize entity maintenance table
    try:
        init_maintenance()
    except Exception as e:
        _log.debug("entity_maintenance init skipped: %s", e)
    # Initialize infra inventory table
    try:
        from api.db.infra_inventory import init_inventory
        init_inventory()
    except Exception as e:
        _log.debug("Infra inventory init skipped: %s", e)
    # Initialize SSH connection log table
    try:
        from api.db.ssh_log import init_ssh_log
        init_ssh_log()
    except Exception as e:
        _log.debug("SSH log init skipped: %s", e)
    try:
        from api.db.ssh_capabilities import init_capabilities
        init_capabilities()
    except Exception as e:
        _log.debug("SSH capabilities init skipped: %s", e)
    try:
        from api.db.result_store import init_result_store
        init_result_store()
    except Exception as e:
        _log.debug("Result store init skipped: %s", e)
    try:
        from api.db.entity_history import init_entity_history
        init_entity_history()
    except Exception as e:
        _log.debug("Entity history init skipped: %s", e)
    try:
        from api.db.notifications import init_notifications
        init_notifications()
    except Exception as e:
        _log.debug("Notifications init skipped: %s", e)
    try:
        from api.db.credential_profiles import init_credential_profiles
        init_credential_profiles()
    except Exception as e:
        _log.debug("Credential profiles init skipped: %s", e)
    # Initialize agent_escalations table
    try:
        init_escalations()
    except Exception as e:
        _log.debug("Escalations table init skipped: %s", e)
    # Initialize agent_actions audit table
    try:
        from api.db.agent_actions import init_agent_actions
        init_agent_actions()
    except Exception as e:
        _log.debug("agent_actions init skipped: %s", e)
    # Initialize agent_attempts history table (v2.32.3)
    try:
        from api.db.agent_attempts import init_agent_attempts
        init_agent_attempts()
    except Exception as e:
        _log.debug("agent_attempts init skipped: %s", e)
    try:
        from api.db.agent_blackouts import init_agent_blackouts
        init_agent_blackouts()
    except Exception as e:
        _log.debug("agent_blackouts init skipped: %s", e)
    # Initialize VM action audit log table
    try:
        from api.db.vm_action_log import init_vm_action_log
        init_vm_action_log()
    except Exception as e:
        _log.debug("VM action log init skipped: %s", e)
    # Initialize vm_exec allowlist table
    try:
        from api.db.vm_exec_allowlist import init_allowlist
        init_allowlist()
    except Exception as e:
        _log.debug("vm_exec_allowlist init skipped: %s", e)
    try:
        from api.db.subtask_proposals import init_subtask_proposals
        init_subtask_proposals()
    except Exception as e:
        _log.debug("subtask_proposals init skipped: %s", e)
    try:
        from api.db.runbooks import init_runbooks
        init_runbooks()
    except Exception as e:
        _log.debug("runbooks init skipped: %s", e)
    # Initialize card_templates table
    try:
        from api.db.card_templates import init_card_templates
        init_card_templates()
    except Exception as e:
        _log.debug("card_templates init skipped: %s", e)
    # Initialize display_aliases table
    try:
        from api.db.display_aliases import init_display_aliases
        init_display_aliases()
    except Exception as e:
        _log.debug("display_aliases init skipped: %s", e)
    # Migrate operations table: add parent_session_id if not present
    try:
        from api.db.base import get_engine as _ge
        from sqlalchemy import text as _sqlt
        async with _ge().begin() as _mc:
            await _mc.execute(_sqlt(
                "ALTER TABLE operations ADD COLUMN IF NOT EXISTS "
                "parent_session_id TEXT NOT NULL DEFAULT ''"
            ))
    except Exception as _mige:
        pass
    # Initialize metric_samples time-series table
    try:
        from api.db.metric_samples import init_metric_samples
        init_metric_samples()
    except Exception as e:
        _log.debug("Metric samples init skipped: %s", e)
    # Auto-register local Docker socket as docker_host connection (idempotent)
    try:
        from api.connections import list_connections, create_connection
        existing = list_connections("docker_host")
        labels = [c.get("label", "") for c in existing]
        if "agent-01" not in labels:
            create_connection(
                platform="docker_host", label="agent-01",
                host="unix:///var/run/docker.sock", port=0,
                auth_type="tcp", credentials={},
                config={"role": "standalone"}, enabled=True,
            )
            _log.info("Auto-created agent-01 docker_host connection")
    except Exception as e:
        _log.debug("agent-01 auto-register skipped: %s", e)
    # Initialize users + API tokens tables
    try:
        from api.users import init_users_tables
        init_users_tables()
    except Exception as e:
        _log.debug("Users table init skipped: %s", e)
    # Scan and load plugins (Tier 2 tools)
    try:
        from api.plugin_loader import scan_plugins
        from api.agents.router import _load_plugins_into_allowlists
        scan_plugins()
        _load_plugins_into_allowlists()
    except Exception as e:
        _log.debug("Plugin load skipped: %s", e)
    collector_manager.start_all()
    # Load dynamic skills from modules/ into memory so skill_execute works after restart
    try:
        _skill_registry.init_db()
        result = _skill_loader.load_all_skills(None)
        _skill_loader.scan_imports(None)
        _log.info(
            "Skills loaded: %d ok, %d failed", len(result["loaded"]), len(result["failed"])
        )
    except Exception as e:
        _log.warning("Skill load skipped: %s", e)
    # Ingest runbooks into MuninnDB (non-blocking — failures are logged, not raised)
    try:
        await ingest_runbooks()
    except Exception as e:
        _log.warning("Memory ingest skipped: %s", e)
    # Start auto-update background check
    try:
        from api.routers.dashboard import start_auto_update, stop_auto_update
        start_auto_update()
    except Exception as e:
        _log.warning("Auto-update start skipped: %s", e)
    # start Bookstack sync scheduler
    try:
        from api.rag.bookstack_sync import start_bookstack_scheduler
        start_bookstack_scheduler()
    except Exception as _bs_err:
        _log.warning("Bookstack scheduler start failed: %s", _bs_err)
    # Result store cleanup every 30 minutes
    import asyncio as _aio
    async def _result_store_cleanup_loop():
        while True:
            await _aio.sleep(1800)
            try:
                from api.db.result_store import cleanup_expired
                n = cleanup_expired()
                if n: _log.info("result_store: purged %d expired rows", n)
            except Exception: pass
    _aio.create_task(_result_store_cleanup_loop())
    # status_snapshots retention cleanup: once on startup, then daily
    try:
        from api.db.base import get_engine as _get_eng
        from sqlalchemy import text as _sqlt
        async with _get_eng().begin() as _conn:
            await _conn.execute(_sqlt(
                "DELETE FROM status_snapshots WHERE timestamp < NOW() - INTERVAL '30 days'"
            ))
    except Exception:
        pass
    async def _snapshot_cleanup_loop():
        while True:
            await _aio.sleep(86400)
            try:
                from api.db.base import get_engine as _get_eng2
                from sqlalchemy import text as _sqlt2
                async with _get_eng2().begin() as _conn2:
                    result = await _conn2.execute(_sqlt2(
                        "DELETE FROM status_snapshots WHERE timestamp < NOW() - INTERVAL '30 days'"
                    ))
                    deleted = result.rowcount
                    if deleted:
                        _log.info("status_snapshots cleanup: deleted %d rows older than 30 days", deleted)
            except Exception as _e:
                _log.debug("status_snapshots cleanup error: %s", _e)
    _aio.create_task(_snapshot_cleanup_loop())
    # Schedule daily metric_samples cleanup (30-day retention)
    async def _daily_metric_cleanup():
        while True:
            await _aio.sleep(86400)
            try:
                from api.db.metric_samples import cleanup_old_samples
                n = cleanup_old_samples(days=30)
                if n:
                    _log.info("metric_samples cleanup: deleted %d rows older than 30d", n)
            except Exception as _e:
                _log.debug("metric_samples cleanup failed: %s", _e)
    _aio.create_task(_daily_metric_cleanup())
    # Schedule hourly operation_log cleanup (retention + per-session trim)
    async def _operation_log_cleanup_loop():
        while True:
            await _aio.sleep(3600)
            try:
                from mcp_server.tools.skills.storage import get_backend as _gb
                retention_days = int(_gb().get_setting("opLogRetentionDays") or 30)
                from api.session_store import cleanup_old_logs
                n = await cleanup_old_logs(retention_days)
                if n:
                    _log.info("operation_log: purged %d rows older than %d days", n, retention_days)
            except Exception as _ole:
                _log.debug("operation_log cleanup failed: %s", _ole)
    _aio.create_task(_operation_log_cleanup_loop())
    # Auto-promoter: weekly scan of agent_actions for repeated tool patterns
    try:
        from api.skills.auto_promoter import schedule_weekly
        pool = getattr(app.state, "pool", None)
        app.state.auto_promoter_task = _aio.create_task(schedule_weekly(pool))
    except Exception as _ape:
        _log.warning("auto_promoter start skipped: %s", _ape)
    yield
    try:
        t = getattr(app.state, "auto_promoter_task", None)
        if t:
            t.cancel()
    except Exception:
        pass
    try:
        stop_auto_update()
    except Exception:
        pass
    try:
        from api.rag.bookstack_sync import stop_bookstack_scheduler
        stop_bookstack_scheduler()
    except Exception:
        pass
    collector_manager.stop_all()
    await _close_memory()
    await _flush_logger()


app = FastAPI(
    title=f"{APP_NAME} API",
    description="Local AI infrastructure orchestration — Docker Swarm + Kafka",
    version=APP_VERSION,
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
app.include_router(auth_router)
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
app.include_router(lock_router)
app.include_router(ansible_router)
app.include_router(ingest_router)
app.include_router(skills_router)
app.include_router(dashboard_router)
app.include_router(connections_router)
app.include_router(notifications_router)
app.include_router(users_router)
app.include_router(entities_router)
app.include_router(cred_profiles_router)
app.include_router(layout_router)
app.include_router(escalations_router)
app.include_router(agent_actions_router)
app.include_router(agent_blackouts_router)
app.include_router(errors_router)
app.include_router(vm_exec_allowlist_router)
app.include_router(runbooks_router)
app.include_router(maintenance_router)
app.include_router(discovery_router)
app.include_router(card_templates_router)
app.include_router(display_aliases_router)
app.include_router(docs_router)
app.include_router(kafka_overview_router)


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
        # Fallback: inside Docker the container only has a 172.x bridge IP.
        # AGENT_HOST lets the operator advertise the real host LAN address.
        if not lan_ips:
            agent_host = os.environ.get("AGENT_HOST", "")
            if agent_host:
                lan_ips = [agent_host]
        return {
            "hostname": hostname,
            "lan_ips":  lan_ips,
            "all_ips":  all_ips,
            "api_url":  f"http://{lan_ips[0]}:{DEFAULT_API_PORT}" if lan_ips else None,
            "gui_url":  f"http://{lan_ips[0]}:{DEFAULT_API_PORT}" if lan_ips else None,
        }
    except Exception:
        return {"hostname": "unknown", "lan_ips": [], "all_ips": []}


@app.get("/api/agent/session/{session_id}/replay")
async def session_replay(session_id: str, user: str = Depends(get_current_user)):
    from api.session_store import get_replay_lines
    lines = await get_replay_lines(session_id)
    return {"session_id": session_id, "lines": lines}


@app.get("/api/agent/sessions/active")
async def active_sessions(user: str = Depends(get_current_user)):
    from api.session_store import get_active_sessions
    return {"sessions": await get_active_sessions()}


@app.get("/metrics")
async def metrics():
    body, ctype = render_metrics()
    return Response(content=body, media_type=ctype)


@app.get("/api/health")
async def health():
    response = {
        "status": "ok",
        "service": APP_NAME,
        "version": APP_VERSION,
        "deploy_mode": os.environ.get("HP1_DEPLOY_MODE", "bare-metal"),
        "ws_clients": manager.active_count,
        "network": _get_host_ips(),
    }
    if _BUILD_INFO:
        response["build_info"] = {k: v for k, v in _BUILD_INFO.items() if k != "version"}
    return response


@app.websocket("/ws/output")
async def websocket_output(ws: WebSocket, token: Optional[str] = Query(default=None)):
    """WebSocket endpoint — streams agent output to GUI in real time.

    Auth priority:
      1. ?token=<jwt> query param (legacy)
      2. httpOnly auth cookie (preferred since v2.30.1 / v2.31.3)

    Invalid or missing token closes with code 1008.
    """
    if not token:
        # Browsers send same-origin cookies on the WS handshake. Read the
        # same cookie name used by the HTTP auth path so both flows validate
        # via the exact same manager.connect(token=...) path.
        token = ws.cookies.get("hp1_auth") or ""
    await manager.connect(ws, token=token)
    # If connect rejected the ws (invalid token), it's closed; the ws won't be in connections.
    # We still need to guard the receive loop.
    if ws not in manager._connections:
        return
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
