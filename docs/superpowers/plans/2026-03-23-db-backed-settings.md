# DB-Backed Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the read-only `.env`-based settings API and localStorage-only OptionsContext with a DB-backed settings system that seeds from env vars on first run, persists changes with change-tracking, and surfaces real values in the Options modal.

**Architecture:** The `settings` table (key TEXT PK, value TEXT/JSONB, updated_at) already exists in both SQLite and PostgreSQL backends — no schema changes needed. The settings router is rewritten to read/write this table via `get_backend()`. The frontend `OptionsContext` gains an async server load on mount and persists server-owned keys via `POST /api/settings` on save. Display/UI preferences (theme, card dimensions, etc.) stay in `localStorage` only.

**Tech Stack:** FastAPI (sync route handlers), `mcp_server.tools.skills.storage.get_backend()`, React useState/useEffect, `gui/src/api.js` fetch wrappers.

---

## File Structure

| File | Change |
|------|--------|
| `api/routers/settings.py` | Complete rewrite — SETTINGS_KEYS registry, DB-backed GET/POST, seed function |
| `api/main.py` | Add two lines to lifespan: import seed fn + call after skill init |
| `gui/src/api.js` | Add `fetchSettings()` and `saveSettings(payload)` |
| `gui/src/context/OptionsContext.jsx` | Add server load on mount + async save to API for server keys |
| `gui/src/components/OptionsModal.jsx` | Await async save, surface save errors in footer |
| `tests/test_settings_router.py` | New — tests for GET, POST, seed, masking |

---

## Task 1: Rewrite `api/routers/settings.py`

**Files:**
- Modify: `api/routers/settings.py` (complete rewrite)
- Create: `tests/test_settings_router.py`

### Background

The current router reads `.env` on GET and does nothing on POST. The `settings` table exists in both DB backends with `get_setting(key)` / `set_setting(key, value)` already implemented. The project helper pattern for API routers uses sync `def` (see `api/routers/skills.py`).

`get_backend()` is imported from `mcp_server.tools.skills.storage`. It returns a singleton (SQLite or PostgreSQL, auto-detected).

### Step 1: Write the failing tests

- [ ] Create `tests/test_settings_router.py`:

```python
"""Tests for GET/POST /api/settings — DB-backed settings."""
import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)

SERVER_KEYS = [
    "lmStudioUrl", "lmStudioApiKey", "modelName",
    "kafkaBootstrapServers", "elasticsearchUrl", "kibanaUrl", "muninndbUrl",
    "dockerHost", "swarmManagerIPs", "swarmWorkerIPs",
    "externalProvider", "externalApiKey", "externalModel",
    "autoEscalate", "requireConfirmation", "dashboardRefreshInterval",
]


def auth_headers():
    r = client.post("/api/auth/login", json={"username": "admin", "password": "superduperadmin"})
    if r.status_code != 200:
        pytest.skip("Auth not available")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_get_settings_returns_all_server_keys():
    """GET /api/settings returns every key in SERVER_KEYS."""
    r = client.get("/api/settings", headers=auth_headers())
    assert r.status_code == 200
    body = r.json()
    assert "settings" in body
    for key in SERVER_KEYS:
        assert key in body["settings"], f"Missing key: {key}"


def test_get_settings_masks_sensitive_fields():
    """lmStudioApiKey and externalApiKey are masked in GET response."""
    # First write a non-empty value
    client.post("/api/settings",
        json={"lmStudioApiKey": "super-secret-key"},
        headers=auth_headers())
    r = client.get("/api/settings", headers=auth_headers())
    assert r.status_code == 200
    val = r.json()["settings"]["lmStudioApiKey"]
    assert "super-secret-key" not in val
    assert "***" in val


def test_post_settings_saves_to_db_and_returns_updated():
    """POST /api/settings saves values and returns them."""
    payload = {"lmStudioUrl": "http://test-host:1234/v1", "modelName": "test-model"}
    r = client.post("/api/settings", json=payload, headers=auth_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["updated"]["lmStudioUrl"] == "http://test-host:1234/v1"
    assert body["updated"]["modelName"] == "test-model"


def test_post_settings_persists_across_get():
    """Value saved via POST is returned in subsequent GET."""
    client.post("/api/settings",
        json={"muninndbUrl": "http://muninn-test:7700"},
        headers=auth_headers())
    r = client.get("/api/settings", headers=auth_headers())
    assert r.json()["settings"]["muninndbUrl"] == "http://muninn-test:7700"


def test_post_settings_ignores_unknown_keys():
    """POST /api/settings silently ignores keys not in SETTINGS_KEYS."""
    r = client.post("/api/settings",
        json={"unknownKey": "bad-value"},
        headers=auth_headers())
    assert r.status_code == 200
    assert "unknownKey" not in r.json().get("updated", {})


def test_post_settings_requires_auth():
    """POST /api/settings without token returns 401 or 403."""
    r = client.post("/api/settings", json={"modelName": "x"})
    assert r.status_code in (401, 403)
```

- [ ] Run tests to verify they all fail:

```bash
python -m pytest tests/test_settings_router.py -v 2>&1 | tail -30
```

Expected: FAIL (most likely `AssertionError` or `KeyError` — current GET doesn't return server keys, POST returns `readonly`)

### Step 2: Implement the rewritten router

- [ ] Replace the full contents of `api/routers/settings.py` with:

```python
"""GET/POST /api/settings — DB-backed settings with env-var seeding."""
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, Body
from api.auth import get_current_user
from mcp_server.tools.skills.storage import get_backend

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Registry: frontend key → {env_var, sensitive, default}
# "env_var" is used for seeding on first run only.
# "sensitive" = True means the GET response masks the value.
SETTINGS_KEYS: dict[str, dict] = {
    # Local AI
    "lmStudioUrl":           {"env": "LM_STUDIO_BASE_URL",      "sens": False, "default": ""},
    "lmStudioApiKey":        {"env": "LM_STUDIO_API_KEY",       "sens": True,  "default": ""},
    "modelName":             {"env": "LM_STUDIO_MODEL",         "sens": False, "default": ""},
    # External AI
    "externalProvider":      {"env": None,                      "sens": False, "default": "claude"},
    "externalApiKey":        {"env": "ANTHROPIC_API_KEY",       "sens": True,  "default": ""},
    "externalModel":         {"env": None,                      "sens": False, "default": "claude-sonnet-4-6"},
    # Escalation
    "autoEscalate":          {"env": None,                      "sens": False, "default": "both"},
    "requireConfirmation":   {"env": None,                      "sens": False, "default": True},
    # Infrastructure
    "kafkaBootstrapServers": {"env": "KAFKA_BOOTSTRAP_SERVERS", "sens": False, "default": ""},
    "elasticsearchUrl":      {"env": "ELASTIC_URL",             "sens": False, "default": ""},
    "kibanaUrl":             {"env": "KIBANA_URL",              "sens": False, "default": ""},
    "muninndbUrl":           {"env": "MUNINN_URL",              "sens": False, "default": ""},
    "dockerHost":            {"env": "DOCKER_HOST",             "sens": False, "default": ""},
    "swarmManagerIPs":       {"env": None,                      "sens": False, "default": ""},
    "swarmWorkerIPs":        {"env": None,                      "sens": False, "default": ""},
    # UI (stored server-side so they survive browser clears)
    "dashboardRefreshInterval": {"env": None,                   "sens": False, "default": 15000},
}


def _mask(value: Any) -> str:
    """Return a masked version of a sensitive value."""
    s = str(value)
    return (s[:4] + "***") if len(s) > 4 else "***"


def seed_defaults() -> int:
    """Populate settings table from env vars if the table is empty.

    Called once from api/main.py lifespan on startup.
    Returns number of keys seeded (0 if table already had data).
    """
    backend = get_backend()
    # Check if already seeded: if any key exists, skip.
    if backend.get_setting("lmStudioUrl") is not None:
        return 0

    seeded = 0
    for key, meta in SETTINGS_KEYS.items():
        env_var = meta["env"]
        value = os.environ.get(env_var, "") if env_var else meta["default"]
        if value is not None and value != "":  # Only seed non-empty values
            backend.set_setting(key, value)
            seeded += 1

    logger.info("Settings: seeded %d keys from environment", seeded)
    return seeded


@router.get("")
def get_settings(_: str = Depends(get_current_user)):
    """Return all server-managed settings. Sensitive values are masked."""
    backend = get_backend()
    result = {}
    for key, meta in SETTINGS_KEYS.items():
        val = backend.get_setting(key)
        if val is None:
            # Fall back to env var then hardcoded default
            env_var = meta["env"]
            val = os.environ.get(env_var, meta["default"]) if env_var else meta["default"]
        result[key] = _mask(val) if (meta["sens"] and val) else val
    return {"settings": result}


@router.post("")
def update_settings(
    body: dict = Body(...),
    _: str = Depends(get_current_user),
):
    """Persist settings to DB. Only recognised keys are saved. Returns updated values (masked)."""
    backend = get_backend()
    updated = {}
    for key, value in body.items():
        if key not in SETTINGS_KEYS:
            continue
        backend.set_setting(key, value)
        meta = SETTINGS_KEYS[key]
        updated[key] = _mask(value) if (meta["sens"] and value) else value
    return {"status": "ok", "updated": updated}


@router.post("/seed")
def reseed_settings(_: str = Depends(get_current_user)):
    """Force re-seed settings from env vars (overwrites existing DB values)."""
    backend = get_backend()
    seeded = 0
    for key, meta in SETTINGS_KEYS.items():
        env_var = meta["env"]
        value = os.environ.get(env_var, "") if env_var else ""
        if value:
            backend.set_setting(key, value)
            seeded += 1
    logger.info("Settings: force-reseeded %d keys", seeded)
    return {"status": "ok", "seeded": seeded}
```

### Step 3: Run tests

- [ ] Run tests:

```bash
python -m pytest tests/test_settings_router.py -v 2>&1 | tail -30
```

Expected: all 6 tests PASS

- [ ] Verify no syntax errors in the router:

```bash
python -m py_compile api/routers/settings.py && echo "OK"
```

### Step 4: Commit

```bash
git add api/routers/settings.py tests/test_settings_router.py
git commit -m "feat(settings): rewrite settings router with DB backing and env-var seeding"
git push
```

---

## Task 2: Auto-seed on startup in `api/main.py`

**Files:**
- Modify: `api/main.py` (2 lines in lifespan)

### Background

`api/main.py` has a `lifespan()` async context manager (lines 49–76) that runs on startup. We need to call `seed_defaults()` after `_skill_registry.init_db()` so the settings table is populated before any request comes in.

The import at line 20 already imports `settings as settings_router`. We need to also import `seed_defaults` from the router module.

### Step 1: Write the test

- [ ] Add to `tests/test_settings_router.py`:

```python
def test_settings_seeded_on_startup():
    """At least lmStudioUrl is present in GET response (seeded from env or default)."""
    r = client.get("/api/settings", headers=auth_headers())
    assert r.status_code == 200
    # The key must be present (may be empty string, but must exist)
    assert "lmStudioUrl" in r.json()["settings"]
```

- [ ] Run it and verify it already passes (it should, since Task 1's GET always returns all keys):

```bash
python -m pytest tests/test_settings_router.py::test_settings_seeded_on_startup -v
```

### Step 2: Add seed call to lifespan

- [ ] In `api/main.py`, add the import after the skills_router import line:

Find:
```python
from api.routers.skills import router as skills_router
```

Add after it:
```python
from api.routers.settings import seed_defaults as _seed_settings
```

- [ ] In the `lifespan()` function, insert the seed block **after** the skill-load try/except block and **before** the `ingest_runbooks` try block. Read `api/main.py` first to confirm the exact location — you are looking for this exact sequence:

```python
    except Exception as e:
        import logging as _logging
        _logging.getLogger(__name__).warning("Skill load skipped: %s", e)
    # Ingest runbooks into MuninnDB (non-blocking — failures are logged, not raised)
    try:
        await ingest_runbooks()
```

Replace that sequence with:
```python
    except Exception as e:
        import logging as _logging
        _logging.getLogger(__name__).warning("Skill load skipped: %s", e)
    # Seed settings from env vars on first run (no-op if already seeded)
    try:
        _seed_settings()
    except Exception as e:
        import logging as _logging
        _logging.getLogger(__name__).warning("Settings seed skipped: %s", e)
    # Ingest runbooks into MuninnDB (non-blocking — failures are logged, not raised)
    try:
        await ingest_runbooks()
```

### Step 3: Verify

- [ ] Syntax check:

```bash
python -m py_compile api/main.py && echo "OK"
```

- [ ] Run all settings tests:

```bash
python -m pytest tests/test_settings_router.py -v 2>&1 | tail -20
```

Expected: all tests PASS

### Step 4: Commit

```bash
git add api/main.py
git commit -m "feat(settings): auto-seed settings from env vars on first startup"
git push
```

---

## Task 3: Add `fetchSettings` and `saveSettings` to `gui/src/api.js`

**Files:**
- Modify: `gui/src/api.js`

### Background

`gui/src/api.js` exports all fetch functions. It already has `authHeaders()` and `BASE`. Settings endpoints require auth (Bearer token). The GET endpoint is now protected (requires auth), so we need `authHeaders()` in both calls.

### Step 1: Add the functions

- [ ] Open `gui/src/api.js`. Find the `// ── Skills ───` section (line 49) and add a new `// ── Settings ───` section directly before it:

Find:
```js
// ── Skills ────────────────────────────────────────────────────────────────────
```

Add before it:
```js
// ── Settings ─────────────────────────────────────────────────────────────────

export async function fetchSettings() {
  const r = await fetch(`${BASE}/api/settings`, { headers: { ...authHeaders() } })
  if (!r.ok) throw new Error(`Settings fetch failed: HTTP ${r.status}`)
  const d = await r.json()
  return d.settings ?? {}
}

export async function saveSettings(payload) {
  const r = await fetch(`${BASE}/api/settings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(payload),
  })
  if (!r.ok) { const d = await r.json(); throw new Error(d.detail || d.message || `HTTP ${r.status}`) }
  return r.json()
}

```

### Step 2: Verify build

- [ ] Run Vite build:

```bash
npm run build 2>&1 | grep -E "error|warn|✓"
```

Expected: `✓ built in ...` with no errors

### Step 3: Commit

```bash
git add gui/src/api.js
git commit -m "feat(settings): add fetchSettings and saveSettings API functions"
git push
```

---

## Task 4: Update `OptionsContext.jsx` — load from server, save to server

**Files:**
- Modify: `gui/src/context/OptionsContext.jsx`

### Background

Currently `OptionsContext` reads from `localStorage` on mount and writes to `localStorage` on save. We need it to:
1. Still load `localStorage` immediately (for instant render, no flash)
2. Then fetch server settings and merge them in (server values win for server-owned keys)
3. On save, POST server-owned keys to `/api/settings` AND update localStorage

**Server-owned keys** are the keys defined in `SETTINGS_KEYS` in the backend — everything except display/theme prefs. We define this list in the frontend too (must stay in sync manually):

```js
const SERVER_KEYS = new Set([
  'lmStudioUrl', 'lmStudioApiKey', 'modelName',
  'externalProvider', 'externalApiKey', 'externalModel',
  'autoEscalate', 'requireConfirmation',
  'kafkaBootstrapServers', 'elasticsearchUrl', 'kibanaUrl',
  'muninndbUrl', 'dockerHost', 'swarmManagerIPs', 'swarmWorkerIPs',
  'dashboardRefreshInterval',
])
```

UI-only keys (theme, cardMinHeight, etc.) remain localStorage-only.

**Masked values from server:** The server returns `sk-****` for sensitive keys. We must NOT overwrite a clean value in localStorage with a masked server value. Strategy: if the server value ends with `***`, keep the localStorage value instead.

### Step 1: Rewrite `OptionsContext.jsx`

- [ ] Replace the full contents of `gui/src/context/OptionsContext.jsx` with:

```jsx
import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { fetchSettings, saveSettings } from '../api'

const STORAGE_KEY = 'hp1_options'

const DEFAULTS = {
  // General
  theme:                    'dark',
  dashboardRefreshInterval: 15000,

  // Infrastructure
  swarmManagerIPs:        '',
  swarmWorkerIPs:         '',
  dockerHost:             '',
  kafkaBootstrapServers:  '',
  elasticsearchUrl:       '',
  kibanaUrl:              '',
  muninndbUrl:            '',

  // AI Services — Local
  lmStudioUrl:    '',
  lmStudioApiKey: '',
  modelName:      '',

  // AI Services — External
  externalProvider:    'claude',
  externalApiKey:      '',
  externalModel:       'claude-sonnet-4-6',

  // Escalation policy
  autoEscalate:        'both',
  requireConfirmation: true,

  // Display (localStorage only)
  cardMinHeight:        70,
  cardMaxHeight:        200,
  cardMinWidth:         300,
  cardMaxWidth:         null,
  nodeCardSize:         'medium',
  showVersionBadges:    true,
  showMemoryEngrams:    true,
  commandsPanelDefault: 'hidden',
}

// Keys managed by the server. Only these are sent to / fetched from the API.
const SERVER_KEYS = new Set([
  'lmStudioUrl', 'lmStudioApiKey', 'modelName',
  'externalProvider', 'externalApiKey', 'externalModel',
  'autoEscalate', 'requireConfirmation',
  'kafkaBootstrapServers', 'elasticsearchUrl', 'kibanaUrl',
  'muninndbUrl', 'dockerHost', 'swarmManagerIPs', 'swarmWorkerIPs',
  'dashboardRefreshInterval',
])

function isMasked(v) {
  return typeof v === 'string' && v.includes('***')
}

const OptionsContext = createContext(null)

export function OptionsProvider({ children }) {
  const [options, setOptions] = useState(() => {
    try {
      const saved  = localStorage.getItem(STORAGE_KEY)
      const parsed = saved ? JSON.parse(saved) : {}
      return { ...DEFAULTS, ...parsed }
    } catch {
      return { ...DEFAULTS }
    }
  })
  const [serverLoaded, setServerLoaded] = useState(false)

  // Load server settings once on mount (after auth token is available)
  const loadFromServer = useCallback(() => {
    fetchSettings()
      .then(serverData => {
        setOptions(prev => {
          const merged = { ...prev }
          for (const [key, val] of Object.entries(serverData)) {
            // Don't overwrite a real local value with a masked server value
            if (isMasked(val) && prev[key]) continue
            merged[key] = val
          }
          return merged
        })
        setServerLoaded(true)
      })
      .catch(() => {
        // Server unreachable — continue with localStorage values
        setServerLoaded(true)
      })
  }, [])

  useEffect(() => { loadFromServer() }, [loadFromServer])

  const setOption = (key, value) => {
    setOptions(prev => ({ ...prev, [key]: value }))
  }

  const saveOptions = async (newOptions) => {
    const dataOnly = Object.fromEntries(
      Object.entries(newOptions).filter(([, v]) => typeof v !== 'function')
    )
    const merged = { ...DEFAULTS, ...options, ...dataOnly }
    setOptions(merged)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(merged))

    // Persist server-owned keys to API
    const serverPayload = Object.fromEntries(
      Object.entries(merged).filter(([k]) => SERVER_KEYS.has(k))
    )
    await saveSettings(serverPayload)  // throws on failure — let caller handle
  }

  const resetOptions = () => {
    setOptions({ ...DEFAULTS })
    localStorage.removeItem(STORAGE_KEY)
  }

  return (
    <OptionsContext.Provider value={{
      ...options,
      serverLoaded,
      setOption,
      saveOptions,
      resetOptions,
      reloadFromServer: loadFromServer,
    }}>
      {children}
    </OptionsContext.Provider>
  )
}

export function useOptions() {
  const ctx = useContext(OptionsContext)
  if (!ctx) throw new Error('useOptions must be used inside OptionsProvider')
  return ctx
}
```

### Step 2: Verify build

- [ ] Run build:

```bash
npm run build 2>&1 | grep -E "error|warn|✓"
```

Expected: `✓ built in ...` with no errors

### Step 3: Commit

```bash
git add gui/src/context/OptionsContext.jsx
git commit -m "feat(settings): load server settings on mount, persist server keys via API"
git push
```

---

## Task 5: Update `OptionsModal.jsx` — async save, save errors, loading state

**Files:**
- Modify: `gui/src/components/OptionsModal.jsx`

### Background

`OptionsModal`'s `save()` function currently calls `options.saveOptions(draft)` synchronously. Now `saveOptions` is async and can throw. We need to:

1. `await` the save and catch errors
2. Show a red error message in the footer if save fails
3. Show a subtle loading indicator on the Infrastructure and AI Services tabs while `serverLoaded` is false (so the user knows the form hasn't been populated from the server yet)

### Step 1: Update the `save` function and footer

- [ ] In `OptionsModal.jsx`, find `const [saving, setSaving] = useState(false)` and add an error state below it:

Find:
```js
  const [saving,   setSaving]  = useState(false)
```

Replace with:
```js
  const [saving,   setSaving]   = useState(false)
  const [saveError, setSaveError] = useState(null)
```

- [ ] Find the `save` async function and replace it:

Find:
```js
  const save = async () => {
    setSaving(true)
    options.saveOptions(draft)

    // Non-critical POST to backend — ignore errors
    try {
      const infraKeys = ['dockerHost', 'kafkaBootstrapServers', 'elasticsearchUrl',
                         'kibanaUrl', 'muninndbUrl', 'swarmManagerIPs', 'swarmWorkerIPs']
      const infraSettings = Object.fromEntries(infraKeys.map(k => [k, draft[k]]))
      await fetch(`${BASE}/api/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(infraSettings),
      })
    } catch { /* ignore */ }

    setSaving(false)
    // Close directly — do NOT call closeModal() because it would revert LIVE_KEYS back to snapshot
    setOpen(false)
    setDraft(null)
    setSnapshot(null)
  }
```

Replace with:
```js
  const save = async () => {
    setSaving(true)
    setSaveError(null)
    try {
      await options.saveOptions(draft)
      // Close directly — do NOT call closeModal() which reverts LIVE_KEYS to snapshot
      setOpen(false)
      setDraft(null)
      setSnapshot(null)
    } catch (e) {
      setSaveError(e.message || 'Failed to save settings')
    } finally {
      setSaving(false)
    }
  }
```

- [ ] Find the footer section (the `<div className="flex items-center justify-end gap-3 ...">`) and add error display:

Find:
```jsx
          {/* Footer */}
          <div className="flex items-center justify-end gap-3 px-5 py-3 border-t border-slate-700 shrink-0">
            <button
              onClick={closeModal}
              className="px-4 py-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors"
            >
              Cancel
            </button>
```

Replace with:
```jsx
          {/* Footer */}
          <div className="flex items-center justify-end gap-3 px-5 py-3 border-t border-slate-700 shrink-0">
            {saveError && (
              <span className="text-xs text-red-400 mr-auto">{saveError}</span>
            )}
            <button
              onClick={closeModal}
              className="px-4 py-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors"
            >
              Cancel
            </button>
```

### Step 2: Add server-loading indicator to tab content

- [ ] Find the `const { ...options } = useOptions()` line at the top of the `OptionsModal` component and destructure `serverLoaded`:

Find the OptionsModal component function open (look for `const options = useOptions()`):
```js
  const options = useOptions()
```

Replace with:
```js
  const options  = useOptions()
  const { serverLoaded } = options
```

- [ ] Find the tab content section (inside `{draft && ...}`) and add the loading banner:

Find:
```jsx
          {/* Tab content */}
          <div className="flex-1 overflow-y-auto px-5 py-4">
            {draft && (
              <>
                {tab === 'General'        && <GeneralTab        draft={draft} update={update} />}
                {tab === 'Infrastructure' && <InfrastructureTab draft={draft} update={update} />}
                {tab === 'AI Services'    && <AIServicesTab     draft={draft} update={update} />}
                {tab === 'Display'        && <DisplayTab        draft={draft} update={update} />}
              </>
            )}
          </div>
```

Replace with:
```jsx
          {/* Tab content */}
          <div className="flex-1 overflow-y-auto px-5 py-4">
            {!serverLoaded && (tab === 'Infrastructure' || tab === 'AI Services') && (
              <p className="text-xs text-slate-500 animate-pulse mb-3">Loading from server…</p>
            )}
            {draft && (
              <>
                {tab === 'General'        && <GeneralTab        draft={draft} update={update} />}
                {tab === 'Infrastructure' && <InfrastructureTab draft={draft} update={update} />}
                {tab === 'AI Services'    && <AIServicesTab     draft={draft} update={update} />}
                {tab === 'Display'        && <DisplayTab        draft={draft} update={update} />}
              </>
            )}
          </div>
```

### Step 3: Verify `BASE` is still present

- [ ] Confirm `const BASE = import.meta.env.VITE_API_BASE ?? ''` is still in `OptionsModal.jsx`. **Do NOT remove it** — it is still used inside `AIServicesTab` (the test-connection fetch). The old `save()` function used it too, but `AIServicesTab` depends on it independently.

### Step 4: Verify build

- [ ] Run build:

```bash
npm run build 2>&1 | grep -E "error|warn|✓"
```

Expected: `✓ built in ...` with no errors

### Step 5: Commit

```bash
git add gui/src/components/OptionsModal.jsx
git commit -m "fix(settings): async save with error display, loading state for server tabs"
git push
```

---

## Task 6: Final smoke test and integration test

**Files:**
- Test: `tests/test_settings_router.py` (add one integration test)

### Step 1: Add round-trip test

- [ ] Add to `tests/test_settings_router.py`:

```python
def test_settings_round_trip_all_server_keys():
    """POST a value for every server key, then GET and confirm all are returned."""
    h = auth_headers()
    payload = {
        "lmStudioUrl":           "http://lm-test:1234/v1",
        "lmStudioApiKey":        "test-api-key",
        "modelName":             "test-model",
        "externalProvider":      "openai",
        "externalApiKey":        "sk-testkey",
        "externalModel":         "gpt-4o",
        "autoEscalate":          "failure",
        "requireConfirmation":   False,
        "kafkaBootstrapServers": "kafka1:9092",
        "elasticsearchUrl":      "http://es:9200",
        "kibanaUrl":             "http://kibana:5601",
        "muninndbUrl":           "http://muninn:7700",
        "dockerHost":            "unix:///var/run/docker.sock",
        "swarmManagerIPs":       "192.168.1.10",
        "swarmWorkerIPs":        "192.168.1.11,192.168.1.12",
        "dashboardRefreshInterval": 30000,
    }
    r = client.post("/api/settings", json=payload, headers=h)
    assert r.status_code == 200, r.text

    r2 = client.get("/api/settings", headers=h)
    data = r2.json()["settings"]

    # Non-sensitive keys must come back unchanged
    assert data["lmStudioUrl"]            == "http://lm-test:1234/v1"
    assert data["modelName"]              == "test-model"
    assert data["externalProvider"]       == "openai"
    assert data["externalModel"]          == "gpt-4o"
    assert data["autoEscalate"]           == "failure"
    assert data["kafkaBootstrapServers"]  == "kafka1:9092"
    assert data["elasticsearchUrl"]       == "http://es:9200"
    assert data["dashboardRefreshInterval"] == 30000

    # Sensitive keys must be masked
    assert "***" in data["lmStudioApiKey"]
    assert "***" in data["externalApiKey"]
```

- [ ] Run full test suite:

```bash
python -m pytest tests/test_settings_router.py -v 2>&1 | tail -30
```

Expected: all tests PASS

### Step 2: Run existing test suite to check for regressions

- [ ] Run all tests:

```bash
python -m pytest tests/ -x -q 2>&1 | tail -20
```

Expected: no regressions (same pass/fail count as before this feature branch)

### Step 3: Build GUI one final time

```bash
npm run build 2>&1 | grep -E "error|warn|✓"
```

Expected: `✓ built in ...`

### Step 4: Commit and push

```bash
git add tests/test_settings_router.py
git commit -m "test(settings): add round-trip integration test for all server keys"
git push
```

---

## Success Criteria

1. `GET /api/settings` returns all 16 server keys populated (from DB or env fallback).
2. `POST /api/settings` saves to DB — confirmed by a subsequent GET returning the saved value.
3. Sensitive keys (`lmStudioApiKey`, `externalApiKey`) are masked in GET responses.
4. Opening the Options modal while logged in shows values loaded from the server (not just hardcoded defaults).
5. Saving in Options modal successfully persists to DB and closes without error.
6. If the API is unreachable on modal open, the form still renders (falls back to localStorage).
7. All 7 tests in `test_settings_router.py` pass.
8. Existing test suite shows no regressions.
