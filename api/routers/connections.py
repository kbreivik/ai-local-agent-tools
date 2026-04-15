"""CRUD endpoints for infrastructure connections."""
import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import get_current_user, get_current_user_and_role, role_meets

router = APIRouter(prefix="/api/connections", tags=["connections"])
log = logging.getLogger(__name__)


def _trigger_collector_repoll(platform: str = "") -> None:
    """Trigger immediate repoll for all collectors that declare this platform.
    Derived from each collector's `platforms` class attribute — no hardcoded lists."""
    try:
        from api.collectors.manager import manager
        loop = asyncio.get_event_loop()
        targets: set[str] = set()
        for component, collector in manager._collectors.items():
            collector_platforms = getattr(collector, "platforms", [])
            if not platform or platform in collector_platforms:
                targets.add(component)
        for component in sorted(targets):
            if manager.get(component):
                loop.create_task(manager.trigger_poll(component))
        if targets:
            log.debug("_trigger_collector_repoll(%r) → %s", platform, sorted(targets))
    except Exception as e:
        log.warning("_trigger_collector_repoll failed: %s", e)


class CreateConnectionRequest(BaseModel):
    platform: str
    label: str
    host: str
    port: int = 443
    auth_type: str = "token"
    credentials: dict = Field(default_factory=dict)
    config: dict = Field(default_factory=dict)
    enabled: bool = True


class UpdateConnectionRequest(BaseModel):
    label: str | None = None
    host: str | None = None
    port: int | None = None
    auth_type: str | None = None
    credentials: dict | None = None
    config: dict | None = None
    enabled: bool | None = None


@router.get("")
def list_all(platform: str = "", _: str = Depends(get_current_user)):
    """List all connections (credentials masked)."""
    from api.connections import list_connections
    return {"status": "ok", "data": list_connections(platform)}


@router.get("/export")
def export_connections(_: str = Depends(get_current_user)):
    """Export all connections as CSV. No secrets included.
    Profile referenced by seq_id (human-readable stable ID).

    Columns: seq_id, platform, label, host, port, role, os_type, jump_via_label
    """
    import csv, io
    from api.connections import list_connections

    all_conns = list_connections()
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=[
        "profile_seq_id", "platform", "label", "host", "port",
        "role", "os_type", "jump_via_label",
    ], extrasaction="ignore")
    writer.writeheader()
    for c in all_conns:
        cfg = c.get("config") or {}
        if isinstance(cfg, str):
            import json
            try: cfg = json.loads(cfg)
            except Exception: cfg = {}
        cred_state = c.get("credential_state") or {}
        row = {
            "profile_seq_id":  cred_state.get("profile_seq_id", ""),
            "platform":        c.get("platform", ""),
            "label":           c.get("label", ""),
            "host":            c.get("host", ""),
            "port":            c.get("port", ""),
            "role":            cfg.get("role", ""),
            "os_type":         cfg.get("os_type", ""),
            "jump_via_label":  cfg.get("jump_via_label", ""),
        }
        writer.writerow(row)

    from fastapi.responses import Response
    return Response(
        content=out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=connections_export.csv"},
    )


@router.get("/{connection_id}")
def get_one(connection_id: str, _: str = Depends(get_current_user)):
    """Get connection detail (credentials masked in response)."""
    from api.connections import get_connection
    conn = get_connection(connection_id)
    if not conn:
        raise HTTPException(404, "Connection not found")
    # Mask credentials in API response
    if conn.get("credentials"):
        conn["credentials"] = "***"
    return {"status": "ok", "data": conn}


@router.post("")
def create(req: CreateConnectionRequest, _: str = Depends(get_current_user)):
    """Create a new platform connection."""
    from api.connections import create_connection
    result = create_connection(
        platform=req.platform, label=req.label, host=req.host,
        port=req.port, auth_type=req.auth_type,
        credentials=req.credentials, config=req.config, enabled=req.enabled,
    )
    if result["status"] != "ok":
        raise HTTPException(400, result["message"])
    _trigger_collector_repoll(req.platform)
    return result


@router.put("/{connection_id}")
def update(connection_id: str, req: UpdateConnectionRequest, _: str = Depends(get_current_user)):
    """Partial update of a connection."""
    from api.connections import update_connection, get_connection
    kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
    result = update_connection(connection_id, **kwargs)
    if result["status"] != "ok":
        raise HTTPException(400, result["message"])
    # Get platform for targeted repoll
    conn = get_connection(connection_id)
    _trigger_collector_repoll(conn.get("platform", "") if conn else "")
    return result


@router.delete("/{connection_id}")
def delete(connection_id: str, _: str = Depends(get_current_user)):
    """Delete a connection."""
    from api.connections import delete_connection, get_connection
    # Get platform before delete for targeted repoll
    conn = get_connection(connection_id)
    platform = conn.get("platform", "") if conn else ""
    result = delete_connection(connection_id)
    if result["status"] != "ok":
        raise HTTPException(404, result["message"])
    _trigger_collector_repoll(platform)
    return result


@router.post("/{connection_id}/test")
def test(connection_id: str, _: str = Depends(get_current_user)):
    """Test connectivity for a connection."""
    from api.connections import test_connection
    return test_connection(connection_id)


@router.post("/{connection_id}/pause")
def pause(connection_id: str, user_role: tuple = Depends(get_current_user_and_role)):
    """Pause a connection — stops collectors from polling it.
    Requires imperial_officer role or above."""
    username, role = user_role
    if not role_meets(role, "imperial_officer"):
        raise HTTPException(403, "Insufficient permissions — imperial_officer or above required")
    from api.connections import pause_connection, get_connection
    result = pause_connection(connection_id, paused_by=username)
    if result["status"] != "ok":
        raise HTTPException(400, result["message"])
    conn = get_connection(connection_id)
    _trigger_collector_repoll(conn.get("platform", "") if conn else "")
    return result


@router.post("/{connection_id}/resume")
def resume(connection_id: str, user_role: tuple = Depends(get_current_user_and_role)):
    """Resume a paused connection — collectors will poll it again.
    Requires imperial_officer role or above."""
    username, role = user_role
    if not role_meets(role, "imperial_officer"):
        raise HTTPException(403, "Insufficient permissions — imperial_officer or above required")
    from api.connections import resume_connection, get_connection
    result = resume_connection(connection_id)
    if result["status"] != "ok":
        raise HTTPException(400, result["message"])
    conn = get_connection(connection_id)
    _trigger_collector_repoll(conn.get("platform", "") if conn else "")
    return result


@router.post("/import")
def import_connections(req: dict, user_role: tuple = Depends(get_current_user_and_role)):
    """Import connections from CSV data (base64-encoded or raw string).

    Body: { csv_data: "<base64 or raw CSV string>" }

    Profile matched by profile_seq_id column. If seq_id not found:
      - Creates connection with config.profile_not_found = true
      - Reports as warning in results

    Security: all values are validated; no SQL injection possible (parameterised queries).
    Existing connections (same platform+label) are skipped with a 'exists' result.
    """
    import csv, io, base64, re, json
    from api.connections import create_connection
    from api.db.credential_profiles import get_profile_by_seq_id

    username, role = user_role
    if not role_meets(role, "imperial_officer"):
        raise HTTPException(403, "imperial_officer or above required")

    raw = req.get("csv_data", "")
    if not raw:
        raise HTTPException(400, "csv_data required")

    # Attempt base64 decode; fall back to raw string
    try:
        csv_text = base64.b64decode(raw).decode("utf-8")
    except Exception:
        csv_text = raw

    # Validate input length
    if len(csv_text) > 500_000:
        raise HTTPException(400, "CSV too large (max 500KB)")

    reader = csv.DictReader(io.StringIO(csv_text))
    required_cols = {"platform", "label", "host"}
    if not reader.fieldnames or not required_cols.issubset(set(reader.fieldnames)):
        raise HTTPException(400, f"CSV must contain columns: {required_cols}")

    # Value sanitisation helper — strips control chars, limits length
    _SAFE = re.compile(r'[\x00-\x1f\x7f]')
    def _clean(v: str, max_len: int = 255) -> str:
        return _SAFE.sub("", str(v or ""))[:max_len]

    # Valid platforms (whitelist)
    VALID_PLATFORMS = {
        "proxmox","fortigate","fortiswitch","truenas","pbs","unifi",
        "wazuh","grafana","portainer","kibana","netbox","synology",
        "security_onion","syncthing","caddy","traefik","opnsense",
        "adguard","bookstack","trilium","nginx","pihole","technitium",
        "cisco","juniper","aruba","docker_host","vm_host","elasticsearch",
        "logstash","windows",
    }

    results = []
    for row in reader:
        platform = _clean(row.get("platform", ""))
        label    = _clean(row.get("label", ""))
        host     = _clean(row.get("host", ""))

        if not platform or not label or not host:
            results.append({"label": label or "?", "status": "skip", "reason": "missing required fields"})
            continue
        if platform not in VALID_PLATFORMS:
            results.append({"label": label, "status": "skip", "reason": f"unknown platform: {platform}"})
            continue

        # Parse port safely
        try:
            port = int(_clean(row.get("port", "443"))) if row.get("port") else 443
            if port < 1 or port > 65535:
                port = 443
        except ValueError:
            port = 443

        # Resolve profile by seq_id
        profile_not_found = False
        profile_id = None
        seq_id_raw = _clean(row.get("profile_seq_id", ""))
        if seq_id_raw and seq_id_raw != "0" and seq_id_raw != "":
            try:
                seq_id = int(seq_id_raw)
                if seq_id > 0:
                    prof = get_profile_by_seq_id(seq_id)
                    if prof:
                        profile_id = str(prof["id"])
                    else:
                        profile_not_found = True
            except ValueError:
                profile_not_found = True

        config = {
            "role":    _clean(row.get("role", ""), 50),
            "os_type": _clean(row.get("os_type", ""), 50),
        }
        if profile_id:
            config["credential_profile_id"] = profile_id
        if profile_not_found:
            config["profile_not_found"] = True
        jump_label = _clean(row.get("jump_via_label", ""), 100)
        if jump_label:
            config["_import_jump_label"] = jump_label  # resolved post-import

        result = create_connection(
            platform=platform, label=label, host=host, port=port,
            auth_type="ssh" if platform in ("vm_host", "windows") else "api",
            credentials={}, config=config,
        )
        if result.get("status") == "ok":
            status = "created"
            if profile_not_found:
                status = "created_no_profile"
        elif "UNIQUE constraint" in str(result.get("message", "")) or \
             "duplicate key" in str(result.get("message", "")):
            status = "exists"
        else:
            status = "error"

        results.append({
            "label":             label,
            "status":            status,
            "profile_not_found": profile_not_found,
            "message":           result.get("message", ""),
        })

    ok = sum(1 for r in results if r["status"] in ("created", "created_no_profile"))
    skipped = sum(1 for r in results if r["status"] in ("exists", "skip"))
    errors = sum(1 for r in results if r["status"] == "error")

    return {
        "status": "ok",
        "summary": {"created": ok, "skipped": skipped, "errors": errors},
        "results": results,
    }
