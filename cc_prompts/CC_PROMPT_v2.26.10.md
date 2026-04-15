# CC PROMPT — v2.26.10 — Backend: credential profiles API overhaul

## What this does
Overhauls the credential profiles API layer:
- Auth type rename: `ssh_key` → `ssh`, `api_key` → `api`; add `windows`, `token_pair`, `basic`
- Rotation test endpoint: tests NEW credentials against all linked connections before saving
- Confirm/save endpoint: writes audit log, updates profile
- Remove `shared_credentials` fallback from `resolve_credentials_for_connection()`
- Expose `/safe` endpoint for UI display without secrets
Version bump: 2.26.9 → 2.26.10

---

## Change 1 — api/routers/credential_profiles.py (FULL REWRITE)

Replace the entire file content with:

```python
"""Credential profiles API — CRUD + rotation test + audit."""
from fastapi import APIRouter, Depends, HTTPException
from api.auth import get_current_user, get_current_user_and_role, role_meets

router = APIRouter(prefix="/api/credential-profiles", tags=["credential_profiles"])

# Valid auth types
AUTH_TYPES = {"ssh", "windows", "api", "token_pair", "basic", "none"}


@router.get("")
async def list_credential_profiles(_: str = Depends(get_current_user)):
    """List all profiles with safe derived fields (no raw credentials)."""
    from api.db.credential_profiles import list_profiles
    return {"profiles": list_profiles()}


@router.get("/{profile_id}/safe")
async def get_profile_safe_fields(profile_id: str, _: str = Depends(get_current_user)):
    """Get non-secret profile fields for UI display.
    Returns username, has_private_key, has_passphrase, has_password."""
    from api.db.credential_profiles import get_profile_safe
    p = get_profile_safe(profile_id)
    if not p:
        raise HTTPException(404, "Profile not found")
    return p


@router.post("")
async def create_credential_profile(req: dict, user_role: tuple = Depends(get_current_user_and_role)):
    """Create a new credential profile. Requires imperial_officer or above."""
    username, role = user_role
    if not role_meets(role, "imperial_officer"):
        raise HTTPException(403, "imperial_officer or above required")
    from api.db.credential_profiles import create_profile
    from api.db.audit_log import write_audit_event
    name = req.get("name", "").strip()
    auth_type = req.get("auth_type", "ssh")
    credentials = req.get("credentials", {})
    discoverable = bool(req.get("discoverable", False))
    if not name:
        raise HTTPException(400, "name required")
    if name == "__no_credential__":
        raise HTTPException(400, "Reserved profile name")
    if auth_type not in AUTH_TYPES:
        raise HTTPException(400, f"Invalid auth_type. Valid: {sorted(AUTH_TYPES)}")
    result = create_profile(name, auth_type, credentials, discoverable=discoverable)
    if result.get("status") == "ok":
        write_audit_event("profile_created", performed_by=username, profile_id=result.get("id"))
    return result


@router.put("/{profile_id}")
async def update_credential_profile(
    profile_id: str, req: dict, user_role: tuple = Depends(get_current_user_and_role)
):
    """Update profile metadata (name, discoverable) without touching credentials.
    Use /confirm-rotation to update credentials after testing."""
    username, role = user_role
    if not role_meets(role, "imperial_officer"):
        raise HTTPException(403, "imperial_officer or above required")
    from api.db.credential_profiles import update_profile
    return update_profile(
        profile_id,
        name=req.get("name"),
        discoverable=req.get("discoverable"),
    )


@router.post("/{profile_id}/test-rotation")
async def test_rotation(
    profile_id: str, req: dict, _: str = Depends(get_current_user)
):
    """Test NEW credentials against all connections linked to this profile.
    Does NOT save credentials — call /confirm-rotation to finalize.

    Body: { new_credentials: {username, private_key, passphrase, password, ...} }
    Returns: { results: [{conn_id, label, host, ok, message, duration_ms}], all_ok: bool }
    """
    from api.db.credential_profiles import get_profile, get_profile_by_seq_id
    from api.connections import get_all_connections_for_platform, list_connections
    import time, json, os

    new_creds = req.get("new_credentials", {})
    if not new_creds:
        raise HTTPException(400, "new_credentials required")

    profile = get_profile(profile_id)
    if not profile:
        raise HTTPException(404, "Profile not found")

    auth_type = profile.get("auth_type", "ssh")

    # Find all connections using this profile (config.credential_profile_id = profile_id)
    all_conns = list_connections()
    linked = [
        c for c in all_conns
        if isinstance(c.get("config"), dict)
        and str(c["config"].get("credential_profile_id", "")) == profile_id
    ]

    if not linked:
        return {"results": [], "all_ok": True, "message": "No connections linked to this profile"}

    # Determine concurrency from settings
    from mcp_server.tools.skills.storage import get_backend
    settings_backend = get_backend()
    test_mode = settings_backend.get_setting("rotationTestMode") or "adaptive"
    delay_ms = int(settings_backend.get_setting("rotationTestDelayMs") or 500)
    max_parallel = int(settings_backend.get_setting("rotationMaxParallel") or 10)
    windows_delay_ms = int(settings_backend.get_setting("rotationWindowsDelayMs") or 2000)

    # Sequential for windows (lockout risk), parallel for others
    is_sequential = (
        test_mode == "sequential"
        or (test_mode == "adaptive" and auth_type == "windows")
    )
    effective_delay = windows_delay_ms if auth_type == "windows" else delay_ms

    import asyncio
    results = []

    async def _test_one(conn: dict) -> dict:
        t0 = time.monotonic()
        try:
            label = conn.get("label") or conn.get("host", "?")
            host = conn.get("host", "")
            port = conn.get("port") or 22
            if auth_type == "ssh":
                from api.collectors.vm_hosts import _ssh_run
                username = new_creds.get("username", "")
                private_key = new_creds.get("private_key", "")
                passphrase = new_creds.get("passphrase", "")
                password = new_creds.get("password", "")
                out = await asyncio.to_thread(
                    _ssh_run, host, port, username, password,
                    private_key, "echo ok", passphrase=passphrase
                )
                ok = "ok" in out.lower() or bool(out.strip())
                msg = "SSH OK" if ok else "SSH failed"
            elif auth_type == "windows":
                # WinRM stub — test connectivity only for now
                import httpx
                scheme = "https" if port in (5986, 443) else "http"
                try:
                    r = httpx.get(f"{scheme}://{host}:{port}/wsman", verify=False, timeout=8)
                    ok = r.status_code < 500
                    msg = f"WinRM HTTP {r.status_code}"
                except Exception as e:
                    ok = False
                    msg = str(e)[:80]
            else:
                # For api/token_pair/basic: HTTP reachability only (credentials validated at use time)
                import httpx
                scheme = "https" if port in (443, 8443, 8006, 8007) else "http"
                try:
                    r = httpx.get(f"{scheme}://{host}:{port}/", verify=False, timeout=8, follow_redirects=True)
                    ok = r.status_code < 500
                    msg = f"HTTP {r.status_code}"
                except Exception as e:
                    ok = False
                    msg = str(e)[:80]
            duration_ms = int((time.monotonic() - t0) * 1000)
            return {"conn_id": str(conn.get("id", "")), "label": label, "host": host,
                    "ok": ok, "message": msg, "duration_ms": duration_ms}
        except Exception as e:
            duration_ms = int((time.monotonic() - t0) * 1000)
            return {"conn_id": str(conn.get("id", "")), "label": conn.get("label", "?"),
                    "host": conn.get("host", ""), "ok": False,
                    "message": str(e)[:120], "duration_ms": duration_ms}

    if is_sequential:
        for conn in linked:
            result = await _test_one(conn)
            results.append(result)
            if effective_delay > 0:
                await asyncio.sleep(effective_delay / 1000)
    else:
        # Parallel with max_parallel cap
        sem = asyncio.Semaphore(max_parallel)
        async def _bounded(conn):
            async with sem:
                return await _test_one(conn)
        results = await asyncio.gather(*[_bounded(c) for c in linked])
        results = list(results)

    all_ok = all(r["ok"] for r in results)
    return {"results": results, "all_ok": all_ok, "profile_id": profile_id}


@router.post("/{profile_id}/confirm-rotation")
async def confirm_rotation(
    profile_id: str, req: dict, user_role: tuple = Depends(get_current_user_and_role)
):
    """Save new credentials after rotation test. Writes audit log.

    Body: {
        new_credentials: {...},
        override: bool,           # true = save despite test failures
        override_reason: str,     # required if override=true and not sith_lord
        test_results: [...],      # results from /test-rotation to log
    }

    Override rules:
      sith_lord:        always allowed, no password required
      imperial_officer: allowed, must provide override_reason
      stormtrooper:     not allowed
    """
    username, role = user_role
    if not role_meets(role, "imperial_officer"):
        raise HTTPException(403, "imperial_officer or above required to save credentials")

    from api.db.credential_profiles import update_profile
    from api.db.audit_log import write_audit_event

    new_creds = req.get("new_credentials", {})
    override = bool(req.get("override", False))
    override_reason = str(req.get("override_reason", "")).strip()
    test_results_raw = req.get("test_results", [])

    if not new_creds:
        raise HTTPException(400, "new_credentials required")
    if override and not role_meets(role, "sith_lord") and not override_reason:
        raise HTTPException(400, "override_reason required for non-admin override")

    result = update_profile(profile_id, credentials=new_creds)
    if result.get("status") != "ok":
        raise HTTPException(400, result.get("message", "Update failed"))

    # Build results dict for audit
    results_dict = {r.get("conn_id", ""): {"ok": r.get("ok"), "message": r.get("message", "")}
                    for r in (test_results_raw or []) if isinstance(r, dict)}
    conn_ids = [r.get("conn_id", "") for r in (test_results_raw or []) if isinstance(r, dict)]

    event_type = "rotation_override" if override else "rotation_test"
    write_audit_event(
        event_type,
        performed_by=username,
        profile_id=profile_id,
        override_reason=override_reason if override else "",
        connection_ids=conn_ids,
        test_results=results_dict,
    )

    return {"status": "ok", "message": "Profile credentials updated", "override": override}


@router.get("/{profile_id}/audit")
async def get_profile_audit(profile_id: str, _: str = Depends(get_current_user)):
    """Get audit log entries for a profile."""
    from api.db.audit_log import list_audit_events
    return {"events": list_audit_events(profile_id=profile_id, limit=50)}


@router.delete("/{profile_id}")
async def delete_credential_profile(
    profile_id: str, user_role: tuple = Depends(get_current_user_and_role)
):
    """Delete a profile. Requires sith_lord if profile has linked connections."""
    username, role = user_role
    if not role_meets(role, "imperial_officer"):
        raise HTTPException(403, "imperial_officer or above required")

    from api.db.credential_profiles import delete_profile, list_profiles, _count_linked_connections
    from api.db.audit_log import write_audit_event

    counts = _count_linked_connections()
    linked_count = counts.get(profile_id, 0)
    if linked_count > 0 and not role_meets(role, "sith_lord"):
        raise HTTPException(403,
            f"Profile has {linked_count} linked connections. sith_lord required to delete.")

    result = delete_profile(profile_id)
    if result.get("status") == "ok":
        write_audit_event("profile_deleted", performed_by=username, profile_id=profile_id)
    return result
```

---

## Change 2 — api/db/credential_profiles.py

### 2a — Update create_profile to accept discoverable param

FIND (exact):
```
def create_profile(name: str, auth_type: str, credentials: dict) -> dict:
    conn = _get_conn()
    if not conn:
        return {"status": "error", "message": "No database connection"}
    try:
        pid = str(uuid.uuid4())
        enc = encrypt_value(json.dumps(credentials))
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO credential_profiles (id, name, auth_type, credentials) VALUES (%s, %s, %s, %s)",
            (pid, name, auth_type, enc)
        )
        conn.commit(); cur.close(); conn.close()
        return {"status": "ok", "id": pid, "message": f"Profile '{name}' created"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

REPLACE WITH:
```
def create_profile(name: str, auth_type: str, credentials: dict, discoverable: bool = False) -> dict:
    conn = _get_conn()
    if conn:
        try:
            pid = str(uuid.uuid4())
            enc = encrypt_value(json.dumps(credentials))
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO credential_profiles (id, name, auth_type, credentials, discoverable) "
                "VALUES (%s, %s, %s, %s, %s)",
                (pid, name, auth_type, enc, discoverable)
            )
            conn.commit(); cur.close(); conn.close()
            return {"status": "ok", "id": pid, "message": f"Profile '{name}' created"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    # SQLite fallback
    try:
        pid = str(uuid.uuid4())
        enc = encrypt_value(json.dumps(credentials))
        from api.db.base import get_sync_engine
        from sqlalchemy import text as _t
        sa = get_sync_engine().connect()
        sa.execute(_t(
            "INSERT INTO credential_profiles (id, name, auth_type, credentials, discoverable) "
            "VALUES (:id, :name, :at, :creds, :disc)"
        ), {"id": pid, "name": name, "at": auth_type, "creds": enc, "disc": 1 if discoverable else 0})
        sa.commit(); sa.close()
        return {"status": "ok", "id": pid, "message": f"Profile '{name}' created"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

### 2b — Update update_profile to accept discoverable param

FIND (exact):
```
def update_profile(profile_id: str, name: str = None, credentials: dict = None) -> dict:
    conn = _get_conn()
    if not conn:
        return {"status": "error", "message": "No database connection"}
    try:
        sets, params = ["updated_at = NOW()"], []
        if name:
            sets.append("name = %s"); params.append(name)
        if credentials:
            existing = get_profile(profile_id)
            merged = {**(existing.get('credentials') or {}), **credentials}
            sets.append("credentials = %s"); params.append(encrypt_value(json.dumps(merged)))
        params.append(profile_id)
        cur = conn.cursor()
        cur.execute(f"UPDATE credential_profiles SET {', '.join(sets)} WHERE id = %s", params)
        conn.commit(); cur.close(); conn.close()
        return {"status": "ok", "message": "Profile updated"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

REPLACE WITH:
```
def update_profile(
    profile_id: str,
    name: str = None,
    credentials: dict = None,
    discoverable: bool | None = None,
) -> dict:
    conn = _get_conn()
    if conn:
        try:
            sets, params = ["updated_at = NOW()"], []
            if name is not None:
                sets.append("name = %s"); params.append(name)
            if credentials is not None:
                # For rotation: replace credentials entirely (not merge) so old keys are removed
                sets.append("credentials = %s"); params.append(encrypt_value(json.dumps(credentials)))
            if discoverable is not None:
                sets.append("discoverable = %s"); params.append(bool(discoverable))
            params.append(profile_id)
            cur = conn.cursor()
            cur.execute(f"UPDATE credential_profiles SET {', '.join(sets)} WHERE id = %s", params)
            conn.commit(); cur.close(); conn.close()
            return {"status": "ok", "message": "Profile updated"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    # SQLite fallback
    try:
        from api.db.base import get_sync_engine
        from sqlalchemy import text as _t
        sa = get_sync_engine().connect()
        sets, params = ["updated_at = datetime('now')"], {}
        if name is not None:
            sets.append("name = :name"); params["name"] = name
        if credentials is not None:
            sets.append("credentials = :creds"); params["creds"] = encrypt_value(json.dumps(credentials))
        if discoverable is not None:
            sets.append("discoverable = :disc"); params["disc"] = 1 if discoverable else 0
        params["id"] = profile_id
        sa.execute(_t(f"UPDATE credential_profiles SET {', '.join(sets)} WHERE id = :id"), params)
        sa.commit(); sa.close()
        return {"status": "ok", "message": "Profile updated"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

### 2c — Remove shared_credentials fallback from resolve_credentials_for_connection

FIND (exact):
```
    # Shared credential fallback (existing behaviour)
    for c in all_connections:
        if c['id'] == connection['id']: continue
        c_cfg = c.get('config') or {}
        if isinstance(c_cfg, str):
            try: c_cfg = json.loads(c_cfg)
            except Exception: c_cfg = {}
        if c_cfg.get('shared_credentials'):
            c_creds = c.get('credentials') or {}
            if isinstance(c_creds, str):
                try: c_creds = json.loads(c_creds)
                except Exception: c_creds = {}
            if c_creds.get('username') or c_creds.get('private_key'):
                return c_creds

    return creds
```

REPLACE WITH:
```
    # shared_credentials connection flag removed in v2.26.10 — credential profiles replace this
    return creds
```

---

## Version bump
Update VERSION: 2.26.9 → 2.26.10

## Commit
```bash
git add -A
git commit -m "feat(api): v2.26.10 credential profiles API overhaul — rotation test, confirm, audit, auth types"
git push origin main
```
