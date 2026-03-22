# Skills Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated "Skills" tab to the GUI that lists all registered skills with category filters, parameter forms, and an execute button — so newly created skills immediately appear without page reload.

**Architecture:** A new `/api/skills` router on the backend exposes skill list + execute endpoints (thin wrappers over the existing `skill_list` / `skill_execute` MCP tools). The frontend adds `SkillsPanel.jsx` using the same layout patterns as `MemoryPanel.jsx` and `CommandPanel.jsx`. The tab is added to `MAIN_TABS` in `App.jsx`.

**Tech Stack:** Python/FastAPI (backend), React 18 + Tailwind CSS (frontend), existing `mcp_server.tools.skill_meta_tools` functions.

---

## File Map

| Action  | Path                                   | Responsibility                                      |
|---------|----------------------------------------|-----------------------------------------------------|
| Create  | `api/routers/skills.py`                | GET /api/skills, POST /api/skills/{name}/execute    |
| Modify  | `api/main.py`                          | Register new skills router                          |
| Modify  | `gui/src/api.js`                       | Add fetchSkills(), executeSkill() API helpers       |
| Create  | `gui/src/components/SkillsPanel.jsx`   | Skills tab: list, filter, param form, execute       |
| Modify  | `gui/src/App.jsx`                      | Add 'Skills' to MAIN_TABS, render SkillsPanel       |

---

## Task 1: Backend — /api/skills router

**Files:**
- Create: `api/routers/skills.py`
- Modify: `api/main.py`

### Background (read before coding)

`mcp_server/tools/skill_meta_tools.py` already has two key functions:
- `skill_list(category="", enabled_only=True)` — returns `_ok()` dict with `data.skills[]`
- `skill_execute(name, kwargs_json="")` — executes a skill by name, kwargs as JSON string

The existing `/api/tools/{tool_name}/invoke` endpoint in `api/routers/tools.py` calls `invoke_tool()` from `api/tool_registry.py`. We'll follow the same pattern here but with dedicated endpoints for better error messages.

Return format for all endpoints: `{"status": "ok"|"error", "data": ..., "message": ..., "timestamp": ...}`

- [ ] **Step 1: Write the test**

Create `tests/test_skills_router.py`:

```python
"""Tests for /api/skills endpoints."""
import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)

# Skills endpoints require auth — use the test token helper or skip auth
# The test client does NOT send auth headers by default; check if auth is
# required or if there's a test bypass. Look at api/auth.py and existing
# test files in tests/ to understand the pattern.

def auth_headers():
    """Get a valid JWT for test requests. See tests/conftest.py if it exists."""
    r = client.post("/api/auth/login", json={"username": "admin", "password": "changeme"})
    if r.status_code != 200:
        pytest.skip("Auth not available in test env")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

def test_list_skills_returns_list():
    h = auth_headers()
    r = client.get("/api/skills", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert "skills" in body
    assert isinstance(body["skills"], list)

def test_list_skills_category_filter():
    h = auth_headers()
    r = client.get("/api/skills?category=compute", headers=h)
    assert r.status_code == 200
    for skill in r.json()["skills"]:
        assert skill["category"] == "compute"

def test_execute_unknown_skill_returns_404():
    h = auth_headers()
    r = client.post("/api/skills/no_such_skill/execute", json={}, headers=h)
    assert r.status_code == 404

def test_execute_skill_http_health_check():
    """http_health_check is a starter skill that works without external services."""
    h = auth_headers()
    r = client.post(
        "/api/skills/http_health_check/execute",
        json={"url": "http://localhost:8000/api/health"},
        headers=h,
    )
    # May be ok or error depending on env — just check shape
    assert r.status_code == 200
    body = r.json()
    assert "status" in body
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_skills_router.py -v 2>&1 | head -30
```

Expected: ImportError or 404 — `/api/skills` doesn't exist yet.

- [ ] **Step 3: Implement `api/routers/skills.py`**

```python
"""GET /api/skills — skill registry endpoints for the GUI Skills tab."""
import json
from fastapi import APIRouter, HTTPException, Query
from api.tool_registry import invoke_tool

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("")
def list_skills(
    category: str = Query("", description="Filter by category"),
    include_disabled: bool = Query(False),
):
    """Return all registered skills, optionally filtered by category."""
    result = invoke_tool("skill_list", {
        "category": category,
        "enabled_only": not include_disabled,
    })
    skills = result.get("data", {}).get("skills", [])
    return {"skills": skills, "count": len(skills)}


@router.post("/{skill_name}/execute")
def execute_skill(skill_name: str, params: dict = {}):
    """Execute a skill by name. Params are passed as keyword arguments."""
    # Verify skill exists first for a clean 404
    listed = invoke_tool("skill_list", {"category": "", "enabled_only": False})
    names = {s["name"] for s in listed.get("data", {}).get("skills", [])}
    if skill_name not in names:
        raise HTTPException(404, f"Skill '{skill_name}' not found")

    kwargs_json = json.dumps(params) if params else ""
    result = invoke_tool("skill_execute", {"name": skill_name, "kwargs_json": kwargs_json})
    return result


@router.get("/{skill_name}")
def get_skill(skill_name: str):
    """Return metadata for a single skill."""
    listed = invoke_tool("skill_list", {"category": "", "enabled_only": False})
    skills = {s["name"]: s for s in listed.get("data", {}).get("skills", [])}
    if skill_name not in skills:
        raise HTTPException(404, f"Skill '{skill_name}' not found")
    return skills[skill_name]
```

- [ ] **Step 4: Register router in `api/main.py`**

Open `api/main.py`. Find the block where other routers are imported and included. It will look like:

```python
from api.routers import memory, tools, status, ...
app.include_router(memory.router)
app.include_router(tools.router)
```

Add after the existing router imports/includes:

```python
from api.routers import skills as skills_router
# ...
app.include_router(skills_router.router)
```

- [ ] **Step 5: Run tests — expect pass**

```bash
python -m pytest tests/test_skills_router.py -v
```

Expected: All tests pass (or `test_execute_skill_http_health_check` may show `status: error` if not in container — that's fine, just check shape).

- [ ] **Step 6: Validate syntax**

```bash
python -m py_compile api/routers/skills.py api/main.py
```

- [ ] **Step 7: Commit**

```bash
git add api/routers/skills.py api/main.py tests/test_skills_router.py
git commit -m "feat(api): add /api/skills router for GUI skills tab"
git push
```

---

## Task 2: Frontend API helpers

**Files:**
- Modify: `gui/src/api.js`

### Background

`gui/src/api.js` exports async functions used by all components. Each function calls `fetch(...)` with `authHeaders()` (JWT from localStorage). Look at the existing `fetchTools()` and `invokeTool()` functions for the exact pattern to follow.

`BASE` is `import.meta.env.VITE_API_BASE || ''` — always use `${BASE}/api/...` (never hardcode localhost).

- [ ] **Step 1: Add API functions to `gui/src/api.js`**

Find the end of the existing tool-related functions in `api.js` (around line 50). Add:

```javascript
// ── Skills ────────────────────────────────────────────────────────────────────

export async function fetchSkills(category = '') {
  const qs = category ? `?category=${encodeURIComponent(category)}` : ''
  const r = await fetch(`${BASE}/api/skills${qs}`, { headers: { ...authHeaders() } })
  const d = await r.json()
  return d.skills ?? []
}

export async function executeSkill(skillName, params = {}) {
  const r = await fetch(`${BASE}/api/skills/${encodeURIComponent(skillName)}/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(params),
  })
  return r.json()
}
```

- [ ] **Step 2: Verify no syntax errors**

```bash
cd gui && node --input-type=module < /dev/null || true
# Or just check for obvious errors:
grep -n "fetchSkills\|executeSkill" src/api.js
```

Expected: Both function names appear.

- [ ] **Step 3: Commit**

```bash
git add gui/src/api.js
git commit -m "feat(gui): add fetchSkills/executeSkill API helpers"
git push
```

---

## Task 3: SkillsPanel component

**Files:**
- Create: `gui/src/components/SkillsPanel.jsx`

### Background

Study `gui/src/components/MemoryPanel.jsx` and `gui/src/components/CommandPanel.jsx` for layout patterns.

Key UI conventions in this codebase:
- Dark theme: `bg-slate-950`, `bg-slate-900`, `bg-slate-800`, `text-slate-200/300/400`
- Border: `border-slate-700`
- Text sizes: `text-xs` for data, `text-sm` for labels
- Padding: `px-3 py-2` (compact) or `px-4 py-3` (tab view)
- Scrollable content area: `flex-1 overflow-y-auto`
- Loading state: `animate-pulse text-slate-500 text-xs`
- Status colors: green-400 = ok, red-400 = error, amber-400 = degraded, slate-400 = unknown

Skills come from `fetchSkills()` — each skill object has:
```js
{
  name: "proxmox_vm_status",
  description: "List all VMs...",
  category: "compute",
  enabled: true,
  auto_generated: true,
  call_count: 0,
  parameters: {
    type: "object",
    properties: { node: { type: "string", description: "Proxmox node name" } },
    required: ["node"]
  },
  compat: { service: "proxmox", api_version_built_for: "8.2", ... },
  created_at: "2026-03-22T18:00:39.381636+00:00",
  last_called_at: null,
  last_error: null
}
```

The panel needs:
1. **Header bar** — title + refresh button + skill count
2. **Category filter bar** — "All" + unique categories as buttons
3. **Skill cards** — one per skill, scrollable list
4. **Skill card content** — name, description, category badge, enabled indicator, call_count, execute button
5. **Execute flow** — click Execute → show param form inline → submit → show result

- [ ] **Step 1: Create `gui/src/components/SkillsPanel.jsx`**

```jsx
/**
 * SkillsPanel — browse and execute registered dynamic skills.
 */
import { useEffect, useState, useCallback } from 'react'
import { fetchSkills, executeSkill } from '../api'

const CATEGORY_COLOR = {
  compute:    'bg-blue-900 text-blue-300',
  networking: 'bg-green-900 text-green-300',
  storage:    'bg-purple-900 text-purple-300',
  monitoring: 'bg-teal-900 text-teal-300',
  general:    'bg-slate-700 text-slate-300',
}

function categoryBadge(cat) {
  return CATEGORY_COLOR[cat] ?? 'bg-slate-700 text-slate-400'
}

// ── Param form ────────────────────────────────────────────────────────────────

function ParamForm({ skill, onSubmit, onCancel, running }) {
  const props = skill.parameters?.properties ?? {}
  const required = skill.parameters?.required ?? []
  const [values, setValues] = useState(() =>
    Object.fromEntries(Object.keys(props).map(k => [k, '']))
  )

  const set = (k, v) => setValues(prev => ({ ...prev, [k]: v }))

  return (
    <div className="mt-2 border border-slate-600 rounded p-2 bg-slate-800 text-xs">
      {Object.entries(props).map(([k, schema]) => (
        <div key={k} className="mb-2">
          <label className="block text-slate-400 mb-0.5">
            {k}{required.includes(k) && <span className="text-red-400 ml-0.5">*</span>}
            {schema.description && (
              <span className="text-slate-600 ml-1">— {schema.description}</span>
            )}
          </label>
          <input
            value={values[k]}
            onChange={e => set(k, e.target.value)}
            placeholder={schema.type === 'integer' ? '0' : `${k}…`}
            className="w-full bg-slate-700 border border-slate-600 rounded px-2 py-1 text-slate-200 focus:outline-none focus:border-blue-500"
          />
        </div>
      ))}
      <div className="flex gap-2 mt-1">
        <button
          onClick={() => onSubmit(values)}
          disabled={running}
          className="px-3 py-1 rounded bg-green-600 hover:bg-green-700 text-white disabled:bg-slate-700 disabled:text-slate-500"
        >
          {running ? '…' : 'Run'}
        </button>
        <button
          onClick={onCancel}
          className="px-3 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-300"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

// ── Result display ────────────────────────────────────────────────────────────

function ResultBox({ result }) {
  const ok = result?.status === 'ok'
  const border = ok ? 'border-green-700' : 'border-red-700'
  const text   = ok ? 'text-green-300'  : 'text-red-300'
  return (
    <div className={`mt-2 border ${border} rounded p-2 bg-slate-800 text-xs`}>
      <span className={`font-bold ${text}`}>{result?.status?.toUpperCase()}</span>
      {result?.message && (
        <span className="text-slate-400 ml-2">{result.message}</span>
      )}
      {result?.data && (
        <pre className="mt-1 text-slate-300 whitespace-pre-wrap break-all max-h-40 overflow-y-auto">
          {JSON.stringify(result.data, null, 2)}
        </pre>
      )}
    </div>
  )
}

// ── Skill card ────────────────────────────────────────────────────────────────

function SkillCard({ skill }) {
  const [open,    setOpen]    = useState(false)   // param form open
  const [running, setRunning] = useState(false)
  const [result,  setResult]  = useState(null)

  const hasParams = Object.keys(skill.parameters?.properties ?? {}).length > 0

  const handleExecute = () => {
    setResult(null)
    if (hasParams) {
      setOpen(true)
    } else {
      run({})
    }
  }

  const run = async (params) => {
    setRunning(true)
    setOpen(false)
    try {
      // Cast integer params
      const props = skill.parameters?.properties ?? {}
      const cast = Object.fromEntries(
        Object.entries(params).map(([k, v]) => [
          k,
          props[k]?.type === 'integer' ? (parseInt(v, 10) || 0) : v,
        ])
      )
      const r = await executeSkill(skill.name, cast)
      setResult(r)
    } catch (e) {
      setResult({ status: 'error', message: e.message })
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="border border-slate-700 rounded p-2 mb-2 bg-slate-900">
      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="font-mono text-slate-200 text-xs">{skill.name}</span>
            <span className={`text-[10px] px-1.5 py-0.5 rounded ${categoryBadge(skill.category)}`}>
              {skill.category}
            </span>
            {skill.auto_generated && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-900 text-amber-300">
                generated
              </span>
            )}
            {!skill.enabled && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900 text-red-300">
                disabled
              </span>
            )}
          </div>
          <p className="text-slate-400 text-xs mt-0.5 leading-snug">{skill.description}</p>
        </div>
        <button
          onClick={handleExecute}
          disabled={running || !skill.enabled}
          className="shrink-0 px-2 py-1 text-xs rounded bg-blue-700 hover:bg-blue-600 text-white disabled:bg-slate-700 disabled:text-slate-500"
        >
          {running ? '…' : 'Execute'}
        </button>
      </div>

      {/* Call count */}
      {skill.call_count > 0 && (
        <p className="text-slate-600 text-[10px] mt-1">
          called {skill.call_count}×
          {skill.last_called_at && ` · ${new Date(skill.last_called_at).toLocaleString()}`}
        </p>
      )}

      {/* Param form (shown when Execute clicked and skill has params) */}
      {open && (
        <ParamForm
          skill={skill}
          onSubmit={run}
          onCancel={() => setOpen(false)}
          running={running}
        />
      )}

      {/* Result */}
      {result && <ResultBox result={result} />}
    </div>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function SkillsPanel() {
  const [skills,   setSkills]   = useState([])
  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState(null)
  const [category, setCategory] = useState('all')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchSkills()
      setSkills(data)
    } catch (e) {
      setError('Failed to load skills')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const categories = ['all', ...new Set(skills.map(s => s.category))]
  const visible    = category === 'all' ? skills : skills.filter(s => s.category === category)

  return (
    <div className="flex flex-col h-full w-full bg-slate-950">
      {/* Header */}
      <div className="px-4 py-2 border-b border-slate-700 bg-slate-900 shrink-0 flex items-center gap-3">
        <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Skills</span>
        <span className="text-slate-600 text-xs">
          {loading ? 'loading…' : `${skills.length} registered`}
        </span>
        <button
          onClick={load}
          className="ml-auto text-xs px-2 py-0.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-300"
        >
          ↻ Refresh
        </button>
      </div>

      {/* Category filter */}
      <div className="flex gap-1 px-4 py-2 border-b border-slate-700 flex-wrap shrink-0">
        {categories.map(c => (
          <button
            key={c}
            onClick={() => setCategory(c)}
            className={`text-xs px-2 py-0.5 rounded transition-colors ${
              category === c
                ? 'bg-blue-600 text-white'
                : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
            }`}
          >
            {c === 'all' ? `All (${skills.length})` : c}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {loading && (
          <p className="text-xs text-slate-500 animate-pulse">Loading skills…</p>
        )}
        {error && (
          <p className="text-xs text-red-400">{error}</p>
        )}
        {!loading && !error && visible.length === 0 && (
          <p className="text-xs text-slate-600">
            No skills found.{' '}
            {category !== 'all' && (
              <button onClick={() => setCategory('all')} className="text-blue-400 underline">
                Show all
              </button>
            )}
          </p>
        )}
        {visible.map(skill => (
          <SkillCard key={skill.name} skill={skill} />
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Check for obvious issues**

```bash
grep -n "import\|export" gui/src/components/SkillsPanel.jsx | head -10
```

Expected: imports `fetchSkills`, `executeSkill` from `../api`.

- [ ] **Step 3: Commit**

```bash
git add gui/src/components/SkillsPanel.jsx
git commit -m "feat(gui): add SkillsPanel component for dynamic skill browser"
git push
```

---

## Task 4: Wire SkillsPanel into App.jsx

**Files:**
- Modify: `gui/src/App.jsx`

### Background

`App.jsx` line 29: `const MAIN_TABS = ['Dashboard', 'Cluster', 'Commands', 'Logs', 'Memory', 'Ingest', 'Output', 'Tests']`

The tab rendering block (around line 363) uses `{activeTab === 'X' && <XPanel />}` conditionals.

Add 'Skills' between 'Commands' and 'Logs' (logical position — after executing tools, before logs).

- [ ] **Step 1: Add import for SkillsPanel**

Open `gui/src/App.jsx`. Find the import block for panels (lines 1-25 approx). Add:

```javascript
import SkillsPanel    from './components/SkillsPanel'
```

- [ ] **Step 2: Add 'Skills' to MAIN_TABS**

Find:
```javascript
const MAIN_TABS = ['Dashboard', 'Cluster', 'Commands', 'Logs', 'Memory', 'Ingest', 'Output', 'Tests']
```

Change to:
```javascript
const MAIN_TABS = ['Dashboard', 'Cluster', 'Commands', 'Skills', 'Logs', 'Memory', 'Ingest', 'Output', 'Tests']
```

- [ ] **Step 3: Add tab render block**

Find the block that renders tabs (around line 363). Look for the pattern:
```jsx
{activeTab === 'Logs' && (
```

Add immediately before it:
```jsx
{activeTab === 'Skills' && (
  <div className="flex-1 overflow-hidden">
    <SkillsPanel />
  </div>
)}
```

- [ ] **Step 4: Build GUI and verify**

```bash
cd gui && npm run build 2>&1 | tail -10
```

Expected: `✓ built in Xs` with no errors.

If there are JSX errors, fix them before proceeding.

- [ ] **Step 5: Commit**

```bash
git add gui/src/App.jsx
git commit -m "feat(gui): add Skills tab wired to SkillsPanel"
git push
```

---

## Task 5: Deploy and verify

- [ ] **Step 1: Build Docker image and deploy on agent-01**

From the dev machine or by triggering the Ansible cron on ansible2:

```bash
# On agent-01 (ssh auto-admin@192.168.199.10):
cd /opt/hp1-agent
git pull
docker build -t hp1-ai-agent:latest -f docker/Dockerfile .
docker compose -f docker/docker-compose.yml up -d --no-deps hp1_agent
```

Or trigger ansible2 cron run manually:
```bash
ssh ans2 'cd ~/hp1-infra && git pull && ansible-playbook deploy.yml -l hp1_agents 2>&1 | tail -20'
```

- [ ] **Step 2: Verify backend endpoint**

```bash
ssh ans2 'ssh auto-admin@192.168.199.10 "docker exec hp1_agent curl -sf http://localhost:8000/api/skills 2>&1 | python3 -c \"import json,sys; d=json.load(sys.stdin); print(d[\\\"count\\\"], \\\"skills\\\")\"" '
```

Expected: `5 skills` (or however many are registered).

- [ ] **Step 3: Verify new skill appears after skill_create**

In the GUI or via API, create a test skill:
```bash
ssh ans2 'ssh auto-admin@192.168.199.10 "docker exec hp1_agent curl -sf -X POST http://localhost:8000/api/tools/skill_create/invoke -H \"Content-Type: application/json\" -d \"{\\\"skill_description\\\": \\\"HTTP ping check that GETs a URL and returns status code\\\", \\\"service\\\": \\\"monitoring\\\"}\" 2>&1 | python3 -c \"import json,sys; d=json.load(sys.stdin); print(d.get(\\\"status\\\"), d.get(\\\"message\\\",\\\"\\\"))\""'
```

Then check the Skills tab (GUI → refresh, or GET /api/skills) — the new skill should appear without container restart.

- [ ] **Step 4: Final commit if any fixes were needed**

```bash
git add -A
git diff --cached --stat
# Only commit if there were actual fixes
git commit -m "fix(skills): post-deploy fixes"
git push
```

---

## Notes

- Auth: all `/api/skills` endpoints are protected by the same JWT middleware as other `/api/*` endpoints. The frontend sends `Authorization: Bearer <token>` via `authHeaders()` — this is already handled by `fetchSkills()` and `executeSkill()`.
- No async: `api/routers/skills.py` uses sync `def`, not `async def`, matching the project pattern. `invoke_tool()` from `tool_registry.py` is synchronous.
- The Skills tab refresh button calls `load()` which re-fetches from `/api/skills`. Since `skill_create` registers skills immediately in the DB, a refresh will show newly created skills without any server restart.
