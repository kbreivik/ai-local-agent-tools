"""User + API token CRUD endpoints."""
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from api.auth import get_current_user

router = APIRouter(prefix="/api", tags=["users"])
log = logging.getLogger(__name__)


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "stormtrooper"

class UpdateUserRequest(BaseModel):
    role: str | None = None
    enabled: bool | None = None
    password: str | None = None

class CreateTokenRequest(BaseModel):
    name: str
    role: str = "droid"
    expires_at: str | None = None

class LayoutRequest(BaseModel):
    layout_json: str


# ── Users ────────────────────────────────────────────────────────────────────

@router.get("/users")
def get_users(_: str = Depends(get_current_user)):
    from api.users import list_users
    return {"status": "ok", "data": list_users()}


@router.get("/users/me")
def get_me(user: str = Depends(get_current_user)):
    return {"status": "ok", "data": {"username": user}}


@router.post("/users")
def create(req: CreateUserRequest, _: str = Depends(get_current_user)):
    from api.users import create_user
    result = create_user(req.username, req.password, req.role)
    if result["status"] != "ok":
        raise HTTPException(400, result["message"])
    return result


@router.put("/users/{user_id}")
def update(user_id: str, req: UpdateUserRequest, _: str = Depends(get_current_user)):
    from api.users import update_user
    result = update_user(user_id, role=req.role, enabled=req.enabled, password=req.password)
    if result["status"] != "ok":
        raise HTTPException(400, result["message"])
    return result


@router.delete("/users/{user_id}")
def delete(user_id: str, user: str = Depends(get_current_user)):
    from api.users import list_users, delete_user
    # Prevent deleting own account
    users = list_users()
    target = next((u for u in users if u["id"] == user_id), None)
    if target and target["username"] == user:
        raise HTTPException(400, "Cannot delete your own account")
    result = delete_user(user_id)
    if result["status"] != "ok":
        raise HTTPException(404, result["message"])
    return result


# ── API Tokens ───────────────────────────────────────────────────────────────

@router.get("/tokens")
def get_tokens(_: str = Depends(get_current_user)):
    from api.users import list_api_tokens
    return {"status": "ok", "data": list_api_tokens()}


@router.post("/tokens")
def create_token(req: CreateTokenRequest, user: str = Depends(get_current_user)):
    from api.users import create_api_token, list_users
    # Find user_id for the current user
    users = list_users()
    current = next((u for u in users if u["username"] == user), None)
    user_id = current["id"] if current else None
    result = create_api_token(req.name, req.role, user_id, req.expires_at)
    if result["status"] != "ok":
        raise HTTPException(400, result["message"])
    return result


@router.delete("/tokens/{token_id}")
def revoke(token_id: str, _: str = Depends(get_current_user)):
    from api.users import revoke_api_token
    result = revoke_api_token(token_id)
    if result["status"] != "ok":
        raise HTTPException(404, result["message"])
    return result


# ── User Layouts ────────────────────────────────────────────────────────────

DEFAULT_LAYOUT = {
    "template": "DEFAULT",
    "rows": [
        {"tiles": ["PLATFORM"]},
        {"tiles": ["COMPUTE", "CONTAINERS"], "flex": [3, 2]},
        {"tiles": ["NETWORK"]},
        {"tiles": ["STORAGE", "SECURITY"]},
    ],
    "collapsed": [],
    "prefs": {
        "drill_persist": True,
        "density": "compact",
        "compare_on_load": False,
    },
}

SYSTEM_TEMPLATES = [
    {
        "name": "DEFAULT",
        "description": "Standard layout — PLATFORM, COMPUTE+CONTAINERS split, NETWORK, STORAGE+SECURITY split",
        "system": True,
        "layout": DEFAULT_LAYOUT,
    },
    {
        "name": "OPS_FOCUS",
        "description": "All sections full-width, operations-first ordering",
        "system": True,
        "layout": {
            "template": "OPS_FOCUS",
            "rows": [
                {"tiles": ["PLATFORM"]},
                {"tiles": ["COMPUTE"]},
                {"tiles": ["CONTAINERS"]},
                {"tiles": ["NETWORK"]},
            ],
            "collapsed": [],
            "prefs": {"drill_persist": True, "density": "compact", "compare_on_load": False},
        },
    },
    {
        "name": "SOC_VIEW",
        "description": "Security-first — SECURITY, NETWORK, PLATFORM visible; COMPUTE collapsed",
        "system": True,
        "layout": {
            "template": "SOC_VIEW",
            "rows": [
                {"tiles": ["SECURITY"]},
                {"tiles": ["NETWORK"]},
                {"tiles": ["PLATFORM"]},
                {"tiles": ["COMPUTE"]},
            ],
            "collapsed": ["COMPUTE"],
            "prefs": {"drill_persist": True, "density": "compact", "compare_on_load": False},
        },
    },
    {
        "name": "NETWORK_ONLY",
        "description": "Network focus — NETWORK and PLATFORM visible, rest collapsed",
        "system": True,
        "layout": {
            "template": "NETWORK_ONLY",
            "rows": [
                {"tiles": ["NETWORK"]},
                {"tiles": ["PLATFORM"]},
                {"tiles": ["COMPUTE"]},
                {"tiles": ["STORAGE"]},
            ],
            "collapsed": ["COMPUTE", "STORAGE"],
            "prefs": {"drill_persist": True, "density": "compact", "compare_on_load": False},
        },
    },
    {
        "name": "COMPUTE_ONLY",
        "description": "Compute focus — COMPUTE, CONTAINERS, PLATFORM visible; rest collapsed",
        "system": True,
        "layout": {
            "template": "COMPUTE_ONLY",
            "rows": [
                {"tiles": ["COMPUTE"]},
                {"tiles": ["CONTAINERS"]},
                {"tiles": ["PLATFORM"]},
                {"tiles": ["NETWORK"]},
                {"tiles": ["STORAGE"]},
            ],
            "collapsed": ["NETWORK", "STORAGE"],
            "prefs": {"drill_persist": True, "density": "compact", "compare_on_load": False},
        },
    },
]


def _get_layout_db():
    """Get a sync DB connection for layout operations."""
    import os
    dsn = os.environ.get("DATABASE_URL", "")
    if dsn and "postgres" in dsn:
        import psycopg2
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
        return ("pg", psycopg2.connect(dsn))
    try:
        from api.db.base import get_sync_engine
        conn = get_sync_engine().connect()
        return ("sa", conn)
    except Exception:
        return (None, None)


@router.get("/users/me/layout")
def get_layout(user: str = Depends(get_current_user)):
    import json
    db_type, conn = _get_layout_db()
    if not conn:
        return {"status": "ok", "layout_json": json.dumps(DEFAULT_LAYOUT)}

    try:
        if db_type == "pg":
            cur = conn.cursor()
            cur.execute("SELECT layout_json FROM user_layouts WHERE user_id = %s", (user,))
            row = cur.fetchone()
            cur.close()
            conn.close()
            layout = row[0] if row else json.dumps(DEFAULT_LAYOUT)
        else:
            from sqlalchemy import text
            row = conn.execute(
                text("SELECT layout_json FROM user_layouts WHERE user_id = :u"),
                {"u": user},
            ).fetchone()
            conn.close()
            layout = row[0] if row else json.dumps(DEFAULT_LAYOUT)
        return {"status": "ok", "layout_json": layout}
    except Exception as e:
        log.warning("get_layout failed: %s", e)
        return {"status": "ok", "layout_json": json.dumps(DEFAULT_LAYOUT)}


@router.put("/users/me/layout")
def put_layout(req: LayoutRequest, user: str = Depends(get_current_user)):
    import json
    from datetime import datetime, timezone
    # Validate JSON
    try:
        json.loads(req.layout_json)
    except Exception:
        raise HTTPException(400, "Invalid JSON in layout_json")

    now = datetime.now(timezone.utc).isoformat()
    db_type, conn = _get_layout_db()
    if not conn:
        raise HTTPException(500, "No database available")

    try:
        if db_type == "pg":
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO user_layouts (user_id, layout_json, updated_at) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT (user_id) DO UPDATE SET layout_json = EXCLUDED.layout_json, updated_at = EXCLUDED.updated_at",
                (user, req.layout_json, now),
            )
            conn.commit()
            cur.close()
            conn.close()
        else:
            from sqlalchemy import text
            # SQLite upsert
            conn.execute(
                text("INSERT INTO user_layouts (user_id, layout_json, updated_at) "
                     "VALUES (:u, :l, :t) "
                     "ON CONFLICT (user_id) DO UPDATE SET layout_json = :l, updated_at = :t"),
                {"u": user, "l": req.layout_json, "t": now},
            )
            conn.commit()
            conn.close()
        return {"status": "ok"}
    except Exception as e:
        log.error("put_layout failed: %s", e)
        raise HTTPException(500, str(e))


@router.get("/layout/templates")
def get_templates(_: str = Depends(get_current_user)):
    import json
    templates = list(SYSTEM_TEMPLATES)

    # Also fetch shared user layouts
    db_type, conn = _get_layout_db()
    if conn:
        try:
            if db_type == "pg":
                cur = conn.cursor()
                cur.execute("SELECT user_id, layout_json FROM user_layouts")
                for row in cur.fetchall():
                    try:
                        layout = json.loads(row[1])
                        if layout.get("shared"):
                            templates.append({
                                "name": layout.get("template", f"User: {row[0]}"),
                                "description": f"Shared by {row[0]}",
                                "system": False,
                                "layout": layout,
                            })
                    except Exception:
                        pass
                cur.close()
                conn.close()
            else:
                from sqlalchemy import text
                rows = conn.execute(text("SELECT user_id, layout_json FROM user_layouts")).fetchall()
                conn.close()
                for row in rows:
                    try:
                        layout = json.loads(row[1])
                        if layout.get("shared"):
                            templates.append({
                                "name": layout.get("template", f"User: {row[0]}"),
                                "description": f"Shared by {row[0]}",
                                "system": False,
                                "layout": layout,
                            })
                    except Exception:
                        pass
        except Exception as e:
            log.debug("Failed to fetch shared layouts: %s", e)

    return {"status": "ok", "data": templates}
