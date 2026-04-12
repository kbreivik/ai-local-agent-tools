# CC PROMPT — v2.15.0 — Credential profiles

## What this does

Currently every vm_host connection stores its own username/password/key.
Adding 6 worker nodes means entering the same SSH key 6 times.
If the key rotates, you update 6 connections.

This introduces **credential profiles** — a separate encrypted store of
named auth sets. Connections reference a profile by ID instead of storing
credentials inline. One profile ("ubuntu-ssh-key") serves all workers.

Scope: vm_host and docker_host (SSH mode) to start. API-key platforms
(proxmox, fortigate etc.) are unaffected — they keep inline credentials.

Version bump: 2.14.0 → 2.15.0 (new subsystem, x.1.x)

---

## Change 1 — api/db/credential_profiles.py (NEW FILE)

```python
"""Credential profiles — named, encrypted auth sets shared across connections.

credential_profiles table:
  id          UUID PK
  name        TEXT UNIQUE NOT NULL        -- human label, e.g. "ubuntu-ssh-key"
  auth_type   TEXT NOT NULL               -- ssh_key | password | api_key | token
  credentials TEXT NOT NULL               -- Fernet-encrypted JSON
  created_at  TIMESTAMPTZ DEFAULT NOW()
  updated_at  TIMESTAMPTZ DEFAULT NOW()
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone

from api.crypto import encrypt_value, decrypt_value

log = logging.getLogger(__name__)

_DDL_PG = """
CREATE TABLE IF NOT EXISTS credential_profiles (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    auth_type   TEXT NOT NULL DEFAULT 'ssh_key',
    credentials TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(name)
);
"""

_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS credential_profiles (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    auth_type   TEXT NOT NULL DEFAULT 'ssh_key',
    credentials TEXT NOT NULL DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(name)
);
"""

_initialized = False


def _ts(): return datetime.now(timezone.utc).isoformat()
def _is_pg(): return bool(os.environ.get("DATABASE_URL", ""))


def _get_conn():
    if not _is_pg(): return None
    import psycopg2
    dsn = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    return psycopg2.connect(dsn)


def init_credential_profiles() -> bool:
    global _initialized
    if _initialized: return True
    conn = _get_conn()
    if conn:
        try:
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute(_DDL_PG)
            cur.close(); conn.close()
            _initialized = True
            log.info("credential_profiles table ready (PG)")
            return True
        except Exception as e:
            log.warning("credential_profiles init (PG) failed: %s", e)
            try: conn.close()
            except: pass
    try:
        from api.db.base import get_sync_engine
        from sqlalchemy import text as _t
        sa = get_sync_engine().connect()
        sa.execute(_t(_DDL_SQLITE)); sa.commit(); sa.close()
        _initialized = True
        log.info("credential_profiles table ready (SQLite)")
        return True
    except Exception as e:
        log.warning("credential_profiles init (SQLite) failed: %s", e)
        return False


def list_profiles() -> list[dict]:
    """List all profiles — credentials masked."""
    conn = _get_conn()
    rows = []
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, name, auth_type, created_at, updated_at FROM credential_profiles ORDER BY name")
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            cur.close(); conn.close()
        except Exception as e:
            log.warning("list_profiles failed: %s", e)
    else:
        try:
            from api.db.base import get_sync_engine
            from sqlalchemy import text as _t
            sa = get_sync_engine().connect()
            rows = [dict(r) for r in sa.execute(_t(
                "SELECT id, name, auth_type, created_at, updated_at FROM credential_profiles ORDER BY name"
            )).mappings().fetchall()]
            sa.close()
        except Exception:
            pass
    for r in rows:
        r['id'] = str(r['id'])
        if r.get('created_at'):
            try: r['created_at'] = r['created_at'].isoformat()
            except: pass
    return rows


def get_profile(profile_id: str) -> dict | None:
    """Get a profile with decrypted credentials."""
    conn = _get_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM credential_profiles WHERE id = %s", (profile_id,))
            cols = [d[0] for d in cur.description]
            row = cur.fetchone()
            cur.close(); conn.close()
            if not row: return None
            result = dict(zip(cols, row))
            result['id'] = str(result['id'])
            raw = result.get('credentials', '')
            if raw:
                dec = decrypt_value(raw)
                try: result['credentials'] = json.loads(dec)
                except: result['credentials'] = dec
            return result
        except Exception as e:
            log.warning("get_profile failed: %s", e)
            return None
    return None


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


def delete_profile(profile_id: str) -> dict:
    conn = _get_conn()
    if not conn:
        return {"status": "error", "message": "No database connection"}
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM credential_profiles WHERE id = %s", (profile_id,))
        deleted = cur.rowcount
        conn.commit(); cur.close(); conn.close()
        return {"status": "ok" if deleted else "error",
                "message": "Profile deleted" if deleted else "Not found"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def resolve_credentials_for_connection(connection: dict, all_connections: list[dict]) -> dict:
    """Return effective credentials for a connection.

    Priority:
    1. Connection's own inline credentials (if non-empty username or key)
    2. Linked credential profile (connection.config.credential_profile_id)
    3. Shared credential connection (existing shared_credentials fallback)
    """
    creds = connection.get('credentials') or {}
    if isinstance(creds, str):
        try: creds = json.loads(creds)
        except: creds = {}

    # Has its own credentials
    if creds.get('username') or creds.get('private_key') or creds.get('password'):
        return creds

    # Linked profile
    cfg = connection.get('config') or {}
    if isinstance(cfg, str):
        try: cfg = json.loads(cfg)
        except: cfg = {}
    profile_id = cfg.get('credential_profile_id')
    if profile_id:
        profile = get_profile(profile_id)
        if profile:
            return profile.get('credentials') or {}

    # Shared credential fallback (existing behaviour)
    for c in all_connections:
        if c['id'] == connection['id']: continue
        c_cfg = c.get('config') or {}
        if isinstance(c_cfg, str):
            try: c_cfg = json.loads(c_cfg)
            except: c_cfg = {}
        if c_cfg.get('shared_credentials'):
            c_creds = c.get('credentials') or {}
            if isinstance(c_creds, str):
                try: c_creds = json.loads(c_creds)
                except: c_creds = {}
            if c_creds.get('username') or c_creds.get('private_key'):
                return c_creds

    return creds
```

---

## Change 2 — api/routers/credential_profiles.py (NEW FILE)

```python
from fastapi import APIRouter, Depends
from api.auth import get_current_user

router = APIRouter(prefix="/api/credential-profiles", tags=["credential_profiles"])


@router.get("")
async def list_credential_profiles(_: str = Depends(get_current_user)):
    from api.db.credential_profiles import list_profiles
    return {"profiles": list_profiles()}


@router.post("")
async def create_credential_profile(req: dict, _: str = Depends(get_current_user)):
    from api.db.credential_profiles import create_profile
    name = req.get("name", "")
    auth_type = req.get("auth_type", "ssh_key")
    credentials = req.get("credentials", {})
    if not name:
        return {"status": "error", "message": "name required"}
    return create_profile(name, auth_type, credentials)


@router.put("/{profile_id}")
async def update_credential_profile(profile_id: str, req: dict, _: str = Depends(get_current_user)):
    from api.db.credential_profiles import update_profile
    return update_profile(profile_id, name=req.get("name"), credentials=req.get("credentials"))


@router.delete("/{profile_id}")
async def delete_credential_profile(profile_id: str, _: str = Depends(get_current_user)):
    from api.db.credential_profiles import delete_profile
    return delete_profile(profile_id)
```

---

## Change 3 — api/main.py — init + register router

In startup, add:
```python
from api.db.credential_profiles import init_credential_profiles
from api.routers.credential_profiles import router as cred_profiles_router

# In startup event:
init_credential_profiles()

# Register router:
app.include_router(cred_profiles_router)
```

---

## Change 4 — api/collectors/vm_hosts.py — use resolve_credentials_for_connection

Find `_resolve_credentials()` in `api/collectors/vm_hosts.py`. Update it to
also check the credential profile before falling back to shared credentials:

```python
def _resolve_credentials(connection: dict, all_connections: list[dict]):
    from api.db.credential_profiles import resolve_credentials_for_connection
    creds = resolve_credentials_for_connection(connection, all_connections)
    username = creds.get('username', 'ubuntu')
    password = creds.get('password')
    private_key = creds.get('private_key')
    return username, password, private_key
```

---

## Change 5 — gui/src/components/OptionsModal.jsx — Credential Profiles UI

### 5a — Add "Credential Profiles" section at the top of ConnectionsTab

Before the connection list, add a collapsible "Credential Profiles" section:

```jsx
// State additions in ConnectionsTab:
const [profiles, setProfiles] = useState([])
const [showProfileForm, setShowProfileForm] = useState(false)
const [profileForm, setProfileForm] = useState({ name: '', auth_type: 'ssh_key', credentials: {} })
const [profilesOpen, setProfilesOpen] = useState(false)

// Fetch profiles alongside connections:
const fetchProfiles = () => {
  fetch(`${BASE}/api/credential-profiles`, { headers: { ...authHeaders() } })
    .then(r => r.json())
    .then(d => setProfiles(d.profiles || []))
}
// Call fetchProfiles() in useEffect alongside fetchConns()

// Collapsible header:
<div className="mb-4 border rounded" style={{ borderColor: 'var(--border)' }}>
  <button
    onClick={() => setProfilesOpen(o => !o)}
    className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold"
    style={{ color: 'var(--text-1)' }}
  >
    <span>CREDENTIAL PROFILES ({profiles.length})</span>
    <span>{profilesOpen ? '▲' : '▼'}</span>
  </button>
  {profilesOpen && (
    <div className="px-3 pb-3">
      <p className="text-[10px] mb-2" style={{ color: 'var(--text-3)' }}>
        Named auth sets shared across multiple connections. Select a profile when adding vm_host or docker_host connections instead of re-entering credentials each time.
      </p>
      {profiles.map(p => (
        <div key={p.id} className="flex items-center justify-between py-1 border-b" style={{ borderColor: 'var(--border)' }}>
          <span className="text-xs" style={{ color: 'var(--text-1)' }}>{p.name}</span>
          <span className="text-[10px] px-2 py-0.5 rounded" style={{ background: 'var(--bg-3)', color: 'var(--text-3)' }}>{p.auth_type}</span>
        </div>
      ))}
      <button
        onClick={() => setShowProfileForm(true)}
        className="mt-2 text-xs px-3 py-1 rounded"
        style={{ background: 'var(--accent-dim)', color: 'var(--accent)' }}
      >+ New profile</button>
      {showProfileForm && <ProfileForm
        form={profileForm}
        setForm={setProfileForm}
        onSave={async () => {
          await fetch(`${BASE}/api/credential-profiles`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify(profileForm),
          })
          setShowProfileForm(false)
          setProfileForm({ name: '', auth_type: 'ssh_key', credentials: {} })
          fetchProfiles()
        }}
        onCancel={() => setShowProfileForm(false)}
      />}
    </div>
  )}
</div>
```

### 5b — ProfileForm component (add near bottom of file, before ConnectionsTab)

```jsx
function ProfileForm({ form, setForm, onSave, onCancel }) {
  const AUTH_TYPES = [
    ['ssh_key', 'SSH Key'],
    ['password', 'Password'],
    ['api_key', 'API Key'],
    ['token', 'Token'],
  ]
  const update = (k, v) => setForm(f => ({ ...f, [k]: v }))
  const updateCred = (k, v) => setForm(f => ({ ...f, credentials: { ...f.credentials, [k]: v } }))

  return (
    <div className="mt-3 p-3 border rounded" style={{ borderColor: 'var(--border)', background: 'var(--bg-2)' }}>
      <Field label="Profile name">
        <TextInput value={form.name} onChange={v => update('name', v)} placeholder="ubuntu-ssh-key" />
      </Field>
      <Field label="Auth type">
        <Select value={form.auth_type} onChange={v => update('auth_type', v)}
          options={AUTH_TYPES} />
      </Field>
      {(form.auth_type === 'ssh_key' || form.auth_type === 'password') && (
        <>
          <Field label="Username">
            <TextInput value={form.credentials.username || ''} onChange={v => updateCred('username', v)} placeholder="ubuntu" />
          </Field>
          {form.auth_type === 'ssh_key' && (
            <Field label="Private key (PEM)">
              <Textarea value={form.credentials.private_key || ''} onChange={v => updateCred('private_key', v)}
                placeholder="-----BEGIN OPENSSH PRIVATE KEY-----" rows={5} />
            </Field>
          )}
          {form.auth_type === 'password' && (
            <Field label="Password">
              <TextInput type="password" value={form.credentials.password || ''} onChange={v => updateCred('password', v)} />
            </Field>
          )}
        </>
      )}
      {form.auth_type === 'api_key' && (
        <Field label="API Key">
          <TextInput type="password" value={form.credentials.api_key || ''} onChange={v => updateCred('api_key', v)} />
        </Field>
      )}
      <div className="flex gap-2 mt-3">
        <button onClick={onSave} className="px-3 py-1 text-xs rounded bg-blue-600 text-white">Save</button>
        <button onClick={onCancel} className="px-3 py-1 text-xs rounded" style={{ background: 'var(--bg-3)', color: 'var(--text-2)' }}>Cancel</button>
      </div>
    </div>
  )
}
```

### 5c — Profile picker in vm_host connection form

In the vm_host credential fields section of `ConnectionsTab`, add a profile
picker dropdown ABOVE the manual credential fields:

```jsx
// When platform === 'vm_host', show this before the manual fields:
<Field label="Credential profile" hint="Pick a saved profile or enter credentials below">
  <select
    value={form.config?.credential_profile_id || ''}
    onChange={e => updateConfig('credential_profile_id', e.target.value || null)}
    className="w-full bg-[color:var(--bg-2)] border border-[color:var(--border)] rounded px-3 py-1.5 text-xs"
  >
    <option value="">— none (use credentials below) —</option>
    {profiles.map(p => (
      <option key={p.id} value={p.id}>{p.name} ({p.auth_type})</option>
    ))}
  </select>
</Field>
```

When a profile is selected, grey out / collapse the manual credential fields
with a note "Credentials from profile — leave blank to inherit".

---

## Version bump

Update VERSION: `2.14.0` → `2.15.0`

---

## Commit

```bash
git add -A
git commit -m "feat(connections): v2.15.0 credential profiles

- credential_profiles table: named encrypted auth sets (ssh_key/password/api_key/token)
- GET/POST/PUT/DELETE /api/credential-profiles
- resolve_credentials_for_connection(): own creds → profile → shared fallback
- vm_hosts.py: _resolve_credentials uses new resolver
- ConnectionsTab: Credential Profiles section + ProfileForm + profile picker on vm_host"
git push origin main
```
