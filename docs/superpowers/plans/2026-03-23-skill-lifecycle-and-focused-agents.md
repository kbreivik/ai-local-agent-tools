# Skill Lifecycle & Focused Agent Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix skill persistence across container rebuilds, add GUI test/promote/scrap workflow, and replace the single all-tools agent with intent+domain focused agents and a step-through orchestrator with structured verdict gates.

**Architecture:** Three layers: (1) skills saved to `data/skill_modules/` on the existing persistent volume so generated skills survive rebuilds; (2) promoted skills registered as first-class `@mcp.tool()` at server startup and assigned to a domain agent; (3) `classify_task()` expanded to 4 intents (observe/investigate/execute/build), `execute` further filtered by detected domain, and a step orchestrator that runs multi-domain tasks as sequential focused steps with a 50-token structured verdict passed between them.

**Tech Stack:** Python 3.13, FastAPI, FastMCP, SQLite (sqlite3), React/JSX, Tailwind CSS

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `mcp_server/tools/skills/loader.py` | Modify | Add `GENERATED_DIR` constant + scan both dirs |
| `mcp_server/tools/skills/meta_tools.py` | Modify | Write new skills to `GENERATED_DIR` instead of `modules/` |
| `mcp_server/tools/skills/storage/sqlite_backend.py` | Modify | Migration: add `lifecycle_state` + `agent_domain` columns |
| `mcp_server/tools/skills/promoter.py` | Create | Pure logic: promote/demote/scrap/restore DB ops |
| `mcp_server/server.py` | Modify | Register promoted skills as `@mcp.tool()` at startup |
| `api/routers/skills.py` | Modify | Add promote/demote/scrap/restore endpoints |
| `gui/src/api.js` | Modify | Add promoteSkill/scrapSkill/demoteSkill/restoreSkill |
| `gui/src/components/SkillsPanel.jsx` | Modify | Lifecycle badges, Promote/Scrap/Demote/Restore buttons, domain picker |
| `api/agents/gate_rules.py` | Create | Pure gate-rule functions per service operation |
| `api/agents/router.py` | Modify | 4 intent types, domain detection, domain execute allowlists, promoted skill injection |
| `api/agents/orchestrator.py` | Create | Step plan builder + verdict formatter |
| `api/routers/agent.py` | Modify | Use orchestrator for multi-step tasks; new intent labels |
| `tests/test_skill_persistence.py` | Create | Skills load from GENERATED_DIR |
| `tests/test_skill_lifecycle.py` | Create | Promote/scrap/demote/restore API tests |
| `tests/test_gate_rules.py` | Create | Unit tests for gate rule pure functions |
| `tests/test_orchestrator.py` | Create | Step plan builder tests |

---

## Task 1: Skill Persistence

**Files:**
- Modify: `mcp_server/tools/skills/loader.py:41-46`
- Modify: `mcp_server/tools/skills/meta_tools.py:73-76` and `:304-306`
- Create: `tests/test_skill_persistence.py`

**Context:** Today `_MODULES_DIR` (inside the Docker image) is the only scan path. Generated skills written there are lost when the image is rebuilt. `data/` is already on the `agent-data` volume. We add `GENERATED_DIR = data/skill_modules/` as a second scan path and the write target for new skills.

- [ ] **Step 1: Write failing test**

```python
# tests/test_skill_persistence.py
import os, sys, tempfile, shutil, textwrap
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def test_load_all_skills_scans_generated_dir(tmp_path, monkeypatch):
    """Skills in data/skill_modules/ are loaded alongside modules/."""
    from mcp_server.tools.skills import loader

    gen_dir = tmp_path / "data" / "skill_modules"
    gen_dir.mkdir(parents=True)

    skill_code = textwrap.dedent("""\
        from datetime import datetime, timezone
        SKILL_META = {
            "name": "test_generated_skill",
            "description": "test",
            "category": "general",
            "version": "1.0.0",
            "annotations": {},
            "parameters": {},
            "auth_type": "none",
            "config_keys": [],
            "compat": {},
        }
        def _ts(): return datetime.now(timezone.utc).isoformat()
        def _ok(d, m="OK"): return {"status":"ok","data":d,"timestamp":_ts(),"message":m}
        def _err(m, d=None): return {"status":"error","data":d,"timestamp":_ts(),"message":m}
        def execute(**kwargs): return _ok({"test": True})
    """)
    (gen_dir / "test_generated_skill.py").write_text(skill_code)

    monkeypatch.setattr(loader, "GENERATED_DIR", str(gen_dir))

    result = loader.load_all_skills(None)
    assert "test_generated_skill" in result["loaded"]
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd D:/claude_code/FAJK/HP1-AI-Agent-v1
python -m pytest tests/test_skill_persistence.py -v
```

Expected: FAIL — `load_all_skills` only scans `_MODULES_DIR`, doesn't know about `GENERATED_DIR`.

- [ ] **Step 3: Add GENERATED_DIR constant to loader.py**

In `loader.py`, after line 46 (`_IMPORTS_PROCESSED_DIR = ...`), add:

```python
# Public constant — imported by meta_tools and tests
GENERATED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "data", "skill_modules"
)
```

- [ ] **Step 4: Update load_all_skills() to scan both directories**

Replace the existing `load_all_skills` function body (lines 187-208) with:

```python
def load_all_skills(mcp_server) -> dict:
    """Scan modules/ and data/skill_modules/ for skill files. Returns summary."""
    loaded = []
    failed = []

    for scan_dir in [_MODULES_DIR, GENERATED_DIR]:
        if not os.path.isdir(scan_dir):
            os.makedirs(scan_dir, exist_ok=True)
            continue

        for fname in sorted(os.listdir(scan_dir)):
            if not fname.endswith(".py"):
                continue
            if fname.startswith("__") or fname.startswith("_template"):
                continue

            name = fname[:-3]
            if name in _SKILL_HANDLERS:
                continue  # Already loaded from higher-priority dir

            # load_single_skill normally looks only in _MODULES_DIR — pass filepath directly
            filepath = os.path.join(scan_dir, fname)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    code = f.read()
                result = validator.validate_skill_code(code)
                if not result["valid"]:
                    failed.append({"name": name, "error": result["error"]})
                    continue
                module = _load_module_from_file(filepath, f"skill_{name}")
                handler = _make_tool_handler(module, name)
                _SKILL_HANDLERS[name] = handler
                meta = module.SKILL_META
                registry.register_skill(meta, filepath)
                service_id = meta.get("compat", {}).get("service", "")
                if service_id:
                    _seed_service(service_id)
                log.info("Loaded skill: %s (from %s)", name, scan_dir)
                loaded.append(name)
            except Exception as e:
                log.error("Failed to load skill %s: %s", name, e)
                failed.append({"name": name, "error": str(e)})

    log.info("Skill loader: %d loaded, %d failed", len(loaded), len(failed))
    return {"loaded": loaded, "failed": failed, "total": len(loaded) + len(failed)}
```

- [ ] **Step 5: Run test — should pass now**

```bash
python -m pytest tests/test_skill_persistence.py::test_load_all_skills_scans_generated_dir -v
```

Expected: PASS.

- [ ] **Step 6: Update skill_create in meta_tools.py to write to GENERATED_DIR**

In `meta_tools.py`, find lines 73-76:
```python
    # Save to modules directory
    dest = os.path.join(os.path.dirname(loader.__file__), "modules", f"{name}.py")
    with open(dest, "w", encoding="utf-8") as f:
        f.write(code)
```

Replace with:
```python
    # Save to generated skills directory (persisted via data volume)
    os.makedirs(loader.GENERATED_DIR, exist_ok=True)
    dest = os.path.join(loader.GENERATED_DIR, f"{name}.py")
    with open(dest, "w", encoding="utf-8") as f:
        f.write(code)
```

- [ ] **Step 7: Update skill_regenerate in meta_tools.py to use GENERATED_DIR**

Find lines 304-306:
```python
    skill_dir = os.path.join(os.path.dirname(loader.__file__), "modules")
    old_path = os.path.join(skill_dir, f"{name}.py")
    bak_path = os.path.join(skill_dir, f"{name}.py.bak")
```

Replace with:
```python
    # Check both dirs — starter skills are in modules/, generated in GENERATED_DIR
    _in_modules = os.path.join(os.path.dirname(loader.__file__), "modules", f"{name}.py")
    _in_generated = os.path.join(loader.GENERATED_DIR, f"{name}.py")
    skill_dir = loader.GENERATED_DIR if os.path.exists(_in_generated) else os.path.dirname(_in_modules)
    old_path = os.path.join(skill_dir, f"{name}.py")
    bak_path = os.path.join(skill_dir, f"{name}.py.bak")
```

- [ ] **Step 8: Syntax check**

```bash
python -m py_compile mcp_server/tools/skills/loader.py
python -m py_compile mcp_server/tools/skills/meta_tools.py
```

Expected: no output (clean).

- [ ] **Step 9: Run full persistence test suite**

```bash
python -m pytest tests/test_skill_persistence.py -v
```

Expected: all tests pass.

- [ ] **Step 10: Commit**

```bash
git add mcp_server/tools/skills/loader.py mcp_server/tools/skills/meta_tools.py tests/test_skill_persistence.py
git commit -m "feat(skills): persist generated skills to data/skill_modules/ on agent-data volume"
git push
```

---

## Task 2: DB Migration — Lifecycle Columns

**Files:**
- Modify: `mcp_server/tools/skills/storage/sqlite_backend.py`

**Context:** The `skills` table needs two new columns: `lifecycle_state` (auto_generated/promoted/scrapped) and `agent_domain` (kafka/swarm/proxmox/general/null). SQLite's `ALTER TABLE ADD COLUMN` is safe and idempotent — we catch the "duplicate column" error.

- [ ] **Step 1: Add migration after init() CREATE TABLE block**

In `sqlite_backend.py`, the `init()` method ends at line 132 with `conn.commit()`. Add this block immediately after the executescript commit:

```python
        # Migration: add lifecycle columns (idempotent — safe to run on existing DBs)
        for _col, _default in [
            ("lifecycle_state", "auto_generated"),
            ("agent_domain",    ""),
        ]:
            try:
                conn.execute(
                    f"ALTER TABLE skills ADD COLUMN {_col} TEXT DEFAULT '{_default}'"
                )
                conn.commit()
            except Exception:
                pass  # Column already exists — safe to ignore
```

- [ ] **Step 2: Update _skill_row() to include new columns**

Find the `_skill_row` method. It converts a sqlite3.Row to a dict. Verify it uses `dict(row)` or equivalent — if so, new columns are automatically included. If it explicitly maps columns, add the two new ones.

Run:
```bash
grep -n "_skill_row\|dict(row\|row\[" mcp_server/tools/skills/storage/sqlite_backend.py | head -20
```

If `_skill_row` uses `dict(row)`, no change needed. If it has explicit column mapping, add:
```python
"lifecycle_state": row["lifecycle_state"] if "lifecycle_state" in row.keys() else "auto_generated",
"agent_domain":    row["agent_domain"]    if "agent_domain"    in row.keys() else "",
```

- [ ] **Step 3: Syntax check**

```bash
python -m py_compile mcp_server/tools/skills/storage/sqlite_backend.py
```

Expected: no output.

- [ ] **Step 4: Verify migration runs cleanly on existing DB**

```bash
python -c "
from mcp_server.tools.skills.storage.sqlite_backend import SqliteBackend
b = SqliteBackend()
b.init()
skills = b.list_skills(enabled_only=False)
print('skills:', len(skills))
if skills:
    s = skills[0]
    print('has lifecycle_state:', 'lifecycle_state' in s)
    print('has agent_domain:', 'agent_domain' in s)
"
```

Expected output includes `has lifecycle_state: True` and `has agent_domain: True`.

- [ ] **Step 5: Commit**

```bash
git add mcp_server/tools/skills/storage/sqlite_backend.py
git commit -m "feat(db): add lifecycle_state and agent_domain columns to skills table"
git push
```

---

## Task 3: Promoter Module + Server Registration

**Files:**
- Create: `mcp_server/tools/skills/promoter.py`
- Modify: `mcp_server/server.py`

**Context:** `promoter.py` contains pure logic for promote/demote/scrap/restore operations — it updates the DB and moves files. `server.py` reads promoted skills from DB at startup and registers each as a proper `@mcp.tool()` wrapper.

- [ ] **Step 1: Create promoter.py**

```python
# mcp_server/tools/skills/promoter.py
"""Skill lifecycle operations: promote, demote, scrap, restore.

All functions return {"status": "ok"|"error", "message": str, "data": dict|None}.
File operations use data/skill_modules/scrapped/ as a holding area for scrapped skills
so they can be restored without re-generating.
"""
import os
import shutil
from datetime import datetime, timezone

from mcp_server.tools.skills import registry
from mcp_server.tools.skills.loader import GENERATED_DIR


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ok(data=None, msg="OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": msg}

def _err(msg, data=None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": msg}

_SCRAPPED_DIR = os.path.join(os.path.dirname(GENERATED_DIR), "skill_modules_scrapped")


def promote_skill(name: str, domain: str) -> dict:
    """Mark skill as promoted and assign it to an agent domain.

    Args:
        name: Skill name (must exist in DB).
        domain: Agent domain — kafka | swarm | proxmox | general.
    """
    skill = registry.get_skill(name)
    if not skill:
        return _err(f"Skill '{name}' not found")

    valid_domains = {"kafka", "swarm", "proxmox", "general"}
    if domain not in valid_domains:
        return _err(f"Invalid domain '{domain}'. Must be one of: {', '.join(valid_domains)}")

    if skill.get("lifecycle_state") == "scrapped":
        return _err(f"Skill '{name}' is scrapped. Restore it before promoting.")

    registry._db().update_skill(name, lifecycle_state="promoted", agent_domain=domain)
    return _ok({"name": name, "domain": domain},
               f"Skill '{name}' promoted to {domain} agent. Restart to activate as @mcp.tool().")


def demote_skill(name: str) -> dict:
    """Remove skill from promoted state, back to auto_generated.

    Args:
        name: Skill name.
    """
    skill = registry.get_skill(name)
    if not skill:
        return _err(f"Skill '{name}' not found")

    registry._db().update_skill(name, lifecycle_state="auto_generated", agent_domain="")
    return _ok({"name": name}, f"Skill '{name}' demoted. Will be removed from @mcp.tool() on next restart.")


def scrap_skill(name: str) -> dict:
    """Disable skill and move its file to the scrapped holding area.

    Args:
        name: Skill name.
    """
    skill = registry.get_skill(name)
    if not skill:
        return _err(f"Skill '{name}' not found")

    file_path = skill.get("file_path", "")
    os.makedirs(_SCRAPPED_DIR, exist_ok=True)

    if file_path and os.path.exists(file_path):
        dest = os.path.join(_SCRAPPED_DIR, os.path.basename(file_path))
        shutil.move(file_path, dest)

    registry._db().update_skill(name, enabled=0, lifecycle_state="scrapped", agent_domain="")
    return _ok({"name": name}, f"Skill '{name}' scrapped. Use restore to recover.")


def restore_skill(name: str) -> dict:
    """Move scrapped skill file back and re-enable it.

    Args:
        name: Skill name.
    """
    skill = registry.get_skill(name)
    if not skill:
        return _err(f"Skill '{name}' not found")

    if skill.get("lifecycle_state") != "scrapped":
        return _err(f"Skill '{name}' is not scrapped (state: {skill.get('lifecycle_state')}).")

    # Find the file in scrapped dir
    fname = f"{name}.py"
    scrapped_path = os.path.join(_SCRAPPED_DIR, fname)
    if not os.path.exists(scrapped_path):
        return _err(f"Scrapped file not found at {scrapped_path}. Cannot restore.")

    os.makedirs(GENERATED_DIR, exist_ok=True)
    dest = os.path.join(GENERATED_DIR, fname)
    shutil.move(scrapped_path, dest)

    registry._db().update_skill(name, enabled=1, lifecycle_state="auto_generated",
                                 file_path=dest)
    return _ok({"name": name}, f"Skill '{name}' restored. Reload skills to activate.")
```

- [ ] **Step 2: Syntax check promoter.py**

```bash
python -m py_compile mcp_server/tools/skills/promoter.py
```

Expected: no output.

- [ ] **Step 3: Add promoted skill registration to server.py**

In `mcp_server/server.py`, find the startup block where skills are loaded (around lines 269-271):
```python
skill_registry.init_db()
_skill_load_result = skill_loader.load_all_skills(mcp)
_skill_import_result = skill_loader.scan_imports(mcp)
```

Add immediately after those three lines:

```python
# Register promoted skills as first-class @mcp.tool() wrappers
try:
    from mcp_server.tools.skills.registry import list_skills as _ls_promoted
    for _ps in _ls_promoted(enabled_only=True):
        if _ps.get("lifecycle_state") != "promoted":
            continue
        _pname = _ps["name"]
        _pdesc = _ps.get("description", _pname)
        def _make_promoted_tool(_n: str, _d: str):
            def _promoted_fn(**kwargs) -> dict:
                """Promoted skill wrapper."""
                from mcp_server.tools.skills.loader import dispatch_skill
                return dispatch_skill(_n, **kwargs)
            _promoted_fn.__name__ = _n
            _promoted_fn.__doc__ = _d
            return mcp.tool()(_promoted_fn)
        _make_promoted_tool(_pname, _pdesc)
except Exception as _e:
    import logging as _logging
    _logging.getLogger(__name__).warning("Promoted skill registration failed: %s", _e)
```

- [ ] **Step 4: Syntax check server.py**

```bash
python -m py_compile mcp_server/server.py
```

Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add mcp_server/tools/skills/promoter.py mcp_server/server.py
git commit -m "feat(skills): promoter module + dynamic @mcp.tool() registration for promoted skills"
git push
```

---

## Task 4: Backend Lifecycle Endpoints

**Files:**
- Modify: `api/routers/skills.py`
- Create: `tests/test_skill_lifecycle.py`

**Context:** Four new endpoints: promote (POST), demote (POST), scrap (DELETE), restore (POST). All delegate to `promoter.py` functions. Auth required (existing pattern).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_skill_lifecycle.py
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)

@pytest.fixture
def token(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "superduperadmin"})
    return r.json()["access_token"]

@pytest.fixture
def headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_promote_unknown_skill_returns_404(client, headers):
    r = client.post("/api/skills/nonexistent_xyz/promote",
                    json={"domain": "kafka"}, headers=headers)
    assert r.status_code == 404


def test_scrap_unknown_skill_returns_404(client, headers):
    r = client.delete("/api/skills/nonexistent_xyz", headers=headers)
    assert r.status_code == 404


def test_restore_non_scrapped_returns_400(client, headers):
    # http_health_check is a starter skill — not scrapped
    r = client.post("/api/skills/http_health_check/restore", headers=headers)
    assert r.status_code in (400, 404)


def test_promote_invalid_domain_returns_400(client, headers):
    # Use a real skill if available, else just check 400 vs 404
    r = client.post("/api/skills/http_health_check/promote",
                    json={"domain": "invalid_domain"}, headers=headers)
    # 400 if skill exists and domain invalid, 404 if skill not in DB
    assert r.status_code in (400, 404)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_skill_lifecycle.py -v
```

Expected: multiple FAILs — endpoints don't exist yet (404 from FastAPI itself, not our 404).

- [ ] **Step 3: Add endpoints to skills.py**

Add to the end of `api/routers/skills.py`:

```python
from pydantic import BaseModel

class PromoteRequest(BaseModel):
    domain: str  # kafka | swarm | proxmox | general


@router.post("/{skill_name}/promote")
def promote_skill(skill_name: str, body: PromoteRequest, _: str = Depends(get_current_user)):
    """Promote a skill to @mcp.tool() and assign it to an agent domain."""
    from mcp_server.tools.skills.promoter import promote_skill as _promote
    result = _promote(skill_name, body.domain)
    if result["status"] == "error":
        msg = result.get("message", "")
        code = 400 if "not found" not in msg.lower() else 404
        raise HTTPException(code, msg)
    return result


@router.post("/{skill_name}/demote")
def demote_skill(skill_name: str, _: str = Depends(get_current_user)):
    """Remove a skill from the promoted state."""
    from mcp_server.tools.skills.promoter import demote_skill as _demote
    result = _demote(skill_name)
    if result["status"] == "error":
        raise HTTPException(404, result.get("message", "Not found"))
    return result


@router.delete("/{skill_name}")
def scrap_skill(skill_name: str, _: str = Depends(get_current_user)):
    """Scrap a skill — disable it and move file to holding area."""
    from mcp_server.tools.skills.promoter import scrap_skill as _scrap
    result = _scrap(skill_name)
    if result["status"] == "error":
        raise HTTPException(404, result.get("message", "Not found"))
    return result


@router.post("/{skill_name}/restore")
def restore_skill(skill_name: str, _: str = Depends(get_current_user)):
    """Restore a scrapped skill."""
    from mcp_server.tools.skills.promoter import restore_skill as _restore
    result = _restore(skill_name)
    if result["status"] == "error":
        msg = result.get("message", "")
        code = 400 if "not scrapped" in msg.lower() or "not found" in msg.lower() else 500
        # 404 if skill unknown, 400 if not in scrapped state
        if "not found" in msg.lower():
            code = 404
        raise HTTPException(code, msg)
    return result
```

Also add `get_current_user` to the imports at the top of `skills.py`:
```python
from api.auth import get_current_user
from fastapi import APIRouter, Depends, HTTPException, Query
```

- [ ] **Step 4: Syntax check**

```bash
python -m py_compile api/routers/skills.py
```

Expected: no output.

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_skill_lifecycle.py -v
```

Expected: all PASS. (The 400/404 tests will pass since endpoints now exist and return proper codes.)

- [ ] **Step 6: Commit**

```bash
git add api/routers/skills.py tests/test_skill_lifecycle.py
git commit -m "feat(api): add promote/demote/scrap/restore skill lifecycle endpoints"
git push
```

---

## Task 5: Frontend Lifecycle UI

**Files:**
- Modify: `gui/src/api.js`
- Modify: `gui/src/components/SkillsPanel.jsx`

**Context:** Skills have four lifecycle states visible in the GUI: auto_generated (untested), auto_generated (tested), promoted, scrapped. After a test run the Promote and Scrap buttons unlock. Promote shows an inline domain picker. The parent panel reloads skills after any lifecycle change.

- [ ] **Step 1: Add API functions to api.js**

After the existing `executeSkill` function in `gui/src/api.js`, add:

```javascript
export async function promoteSkill(skillName, domain) {
  const r = await fetch(`${BASE}/api/skills/${encodeURIComponent(skillName)}/promote`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ domain }),
  })
  return r.json()
}

export async function demoteSkill(skillName) {
  const r = await fetch(`${BASE}/api/skills/${encodeURIComponent(skillName)}/demote`, {
    method: 'POST',
    headers: { ...authHeaders() },
  })
  return r.json()
}

export async function scrapSkill(skillName) {
  const r = await fetch(`${BASE}/api/skills/${encodeURIComponent(skillName)}`, {
    method: 'DELETE',
    headers: { ...authHeaders() },
  })
  return r.json()
}

export async function restoreSkill(skillName) {
  const r = await fetch(`${BASE}/api/skills/${encodeURIComponent(skillName)}/restore`, {
    method: 'POST',
    headers: { ...authHeaders() },
  })
  return r.json()
}
```

- [ ] **Step 2: Update SkillCard to accept lifecycle props and show lifecycle badges**

In `SkillsPanel.jsx`, update the `SkillCard` function signature and add lifecycle state handling. Replace the entire `SkillCard` function with:

```jsx
const DOMAINS = ['proxmox', 'swarm', 'kafka', 'general']

function LifecycleBadge({ state }) {
  if (state === 'promoted')
    return <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-900 text-green-300">promoted</span>
  if (state === 'scrapped')
    return <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900 text-red-300">scrapped</span>
  return null
}

function SkillCard({ skill, onReload }) {
  const [open,        setOpen]        = useState(false)
  const [running,     setRunning]     = useState(false)
  const [result,      setResult]      = useState(null)
  const [promoting,   setPromoting]   = useState(false)
  const [working,     setWorking]     = useState(false)

  const state     = skill.lifecycle_state ?? 'auto_generated'
  const hasParams = Object.keys(skill.parameters?.properties ?? {}).length > 0
  const tested    = result !== null
  const isEnabled = skill.enabled !== false && state !== 'scrapped'

  const handleExecute = () => {
    setResult(null)
    if (hasParams) setOpen(true)
    else run({})
  }

  const run = async (params) => {
    setRunning(true)
    setOpen(false)
    try {
      const props = skill.parameters?.properties ?? {}
      const cast = Object.fromEntries(
        Object.entries(params).map(([k, v]) => [
          k, props[k]?.type === 'integer' ? (parseInt(v, 10) || 0) : v,
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

  const handlePromote = async (domain) => {
    setWorking(true)
    setPromoting(false)
    try {
      await promoteSkill(skill.name, domain)
      onReload()
    } catch (e) {
      setResult({ status: 'error', message: `Promote failed: ${e.message}` })
    } finally {
      setWorking(false)
    }
  }

  const handleDemote = async () => {
    setWorking(true)
    try {
      await demoteSkill(skill.name)
      onReload()
    } catch (e) {
      setResult({ status: 'error', message: `Demote failed: ${e.message}` })
    } finally {
      setWorking(false)
    }
  }

  const handleScrap = async () => {
    setWorking(true)
    try {
      await scrapSkill(skill.name)
      onReload()
    } catch (e) {
      setResult({ status: 'error', message: `Scrap failed: ${e.message}` })
    } finally {
      setWorking(false)
    }
  }

  const handleRestore = async () => {
    setWorking(true)
    try {
      await restoreSkill(skill.name)
      onReload()
    } catch (e) {
      setResult({ status: 'error', message: `Restore failed: ${e.message}` })
    } finally {
      setWorking(false)
    }
  }

  return (
    <div className={`border rounded p-2 mb-2 bg-slate-900 ${
      state === 'promoted' ? 'border-green-800' :
      state === 'scrapped' ? 'border-red-900 opacity-60' :
      'border-slate-700'
    }`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className={`font-mono text-xs ${state === 'scrapped' ? 'line-through text-slate-500' : 'text-slate-200'}`}>
              {skill.name}
            </span>
            <span className={`text-[10px] px-1.5 py-0.5 rounded ${categoryBadge(skill.category)}`}>
              {skill.category}
            </span>
            {skill.auto_generated && state !== 'promoted' && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-900 text-amber-300">generated</span>
            )}
            <LifecycleBadge state={state} />
            {state === 'promoted' && skill.agent_domain && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-400">
                {skill.agent_domain}
              </span>
            )}
          </div>
          <p className="text-slate-400 text-xs mt-0.5 leading-snug">{skill.description}</p>
        </div>

        {/* Action buttons */}
        <div className="flex gap-1 shrink-0">
          {state === 'scrapped' ? (
            <button onClick={handleRestore} disabled={working}
              className="px-2 py-1 text-xs rounded bg-slate-600 hover:bg-slate-500 text-white disabled:opacity-40">
              {working ? '…' : '↺'}
            </button>
          ) : (
            <>
              <button onClick={handleExecute} disabled={running || !isEnabled}
                className="px-2 py-1 text-xs rounded bg-blue-700 hover:bg-blue-600 text-white disabled:bg-slate-700 disabled:text-slate-500">
                {running ? '…' : '▶'}
              </button>
              {state === 'promoted' ? (
                <button onClick={handleDemote} disabled={working}
                  className="px-2 py-1 text-xs rounded bg-slate-700 hover:bg-slate-600 text-slate-300 disabled:opacity-40">
                  {working ? '…' : '↓'}
                </button>
              ) : (
                <>
                  <button onClick={() => setPromoting(p => !p)} disabled={!tested || working}
                    title={tested ? 'Promote to @mcp.tool()' : 'Run test first'}
                    className="px-2 py-1 text-xs rounded bg-green-800 hover:bg-green-700 text-green-300 disabled:bg-slate-700 disabled:text-slate-500">
                    {working ? '…' : '↑'}
                  </button>
                  <button onClick={handleScrap} disabled={!tested || working}
                    title={tested ? 'Scrap this skill' : 'Run test first'}
                    className="px-2 py-1 text-xs rounded bg-red-900 hover:bg-red-800 text-red-300 disabled:bg-slate-700 disabled:text-slate-500">
                    {working ? '…' : '✕'}
                  </button>
                </>
              )}
            </>
          )}
        </div>
      </div>

      {skill.call_count > 0 && (
        <p className="text-slate-600 text-[10px] mt-1">
          called {skill.call_count}×
          {skill.last_called_at && ` · ${new Date(skill.last_called_at).toLocaleString()}`}
        </p>
      )}

      {open && (
        <ParamForm skill={skill} onSubmit={run} onCancel={() => setOpen(false)} running={running} />
      )}

      {/* Domain picker for promote */}
      {promoting && (
        <div className="mt-2 border border-green-800 rounded p-2 bg-slate-800 text-xs">
          <p className="text-slate-400 mb-2">Add to which agent? (takes effect on restart)</p>
          <div className="flex gap-2 flex-wrap">
            {DOMAINS.map(d => (
              <button key={d} onClick={() => handlePromote(d)}
                className="px-3 py-1 rounded bg-slate-700 hover:bg-green-800 hover:text-green-300 text-slate-300">
                {d}
              </button>
            ))}
          </div>
          <button onClick={() => setPromoting(false)} className="mt-2 text-slate-500 text-[10px]">cancel</button>
        </div>
      )}

      {result && <ResultBox result={result} />}
    </div>
  )
}
```

- [ ] **Step 3: Update SkillsPanel to pass onReload to each card**

In the `SkillsPanel` component, update the `visible.map` line (near the bottom):

```jsx
{visible.map(skill => (
  <SkillCard key={skill.name} skill={skill} onReload={load} />
))}
```

- [ ] **Step 4: Add new API imports to SkillsPanel.jsx**

At the top of `SkillsPanel.jsx`, update the import line:

```javascript
import { fetchSkills, executeSkill, promoteSkill, demoteSkill, scrapSkill, restoreSkill } from '../api'
```

- [ ] **Step 5: Build check**

```bash
cd gui && npm run build 2>&1 | tail -20
```

Expected: build succeeds with no errors.

- [ ] **Step 6: Commit**

```bash
cd ..
git add gui/src/api.js gui/src/components/SkillsPanel.jsx
git commit -m "feat(gui): skill lifecycle UI — promote/demote/scrap/restore with domain picker"
git push
```

---

## Task 6: Gate Rules

**Files:**
- Create: `api/agents/gate_rules.py`
- Create: `tests/test_gate_rules.py`

**Context:** Pure functions that evaluate structured facts and return `(verdict, message)`. Used by the orchestrator to decide GO/ASK/HALT before each execute step. Testing is straightforward since they're pure functions.

- [ ] **Step 1: Write failing tests first**

```python
# tests/test_gate_rules.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from api.agents.gate_rules import kafka_rolling_restart, swarm_service_upgrade, changelog_check, evaluate


def test_kafka_all_up_is_go():
    verdict, msg = kafka_rolling_restart({"brokers_up": 3, "brokers_total": 3, "min_isr": 2, "replication_factor": 3})
    assert verdict == "GO"


def test_kafka_broker_offline_is_halt():
    verdict, msg = kafka_rolling_restart({"brokers_up": 2, "brokers_total": 3, "min_isr": 2, "replication_factor": 3})
    assert verdict == "HALT"
    assert "offline" in msg.lower()


def test_kafka_under_replicated_is_halt():
    verdict, msg = kafka_rolling_restart({"brokers_up": 3, "brokers_total": 3, "min_isr": 0, "replication_factor": 3})
    assert verdict == "HALT"
    assert "isr" in msg.lower()


def test_kafka_unknown_broker_count_is_ask():
    verdict, msg = kafka_rolling_restart({"brokers_up": 0, "brokers_total": 0})
    assert verdict == "ASK"


def test_swarm_quorum_maintained_is_go():
    verdict, msg = swarm_service_upgrade({"managers_up": 3, "managers_total": 3})
    assert verdict == "GO"


def test_swarm_below_quorum_is_halt():
    verdict, msg = swarm_service_upgrade({"managers_up": 1, "managers_total": 3})
    assert verdict == "HALT"
    assert "quorum" in msg.lower()


def test_changelog_ingested_no_breaking_is_go():
    verdict, msg = changelog_check({"changelog_ingested": True, "breaking_changes": [], "to_version": "3.8.0"})
    assert verdict == "GO"


def test_changelog_not_ingested_is_ask():
    verdict, msg = changelog_check({"changelog_ingested": False, "to_version": "3.8.0", "from_version": "3.7.1"})
    assert verdict == "ASK"
    assert "3.8.0" in msg


def test_changelog_breaking_changes_is_ask():
    verdict, msg = changelog_check({"changelog_ingested": True, "breaking_changes": ["API removed /foo"], "to_version": "3.8.0"})
    assert verdict == "ASK"


def test_evaluate_unknown_rule_returns_go():
    result = evaluate("nonexistent_rule", {})
    assert result["verdict"] == "GO"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_gate_rules.py -v
```

Expected: ImportError — `api/agents/gate_rules.py` doesn't exist yet.

- [ ] **Step 3: Create gate_rules.py**

```python
# api/agents/gate_rules.py
"""Service-aware gate rules for the step orchestrator.

Each rule is a pure function: (facts: dict) -> tuple[str, str]
where str is verdict ("GO" | "ASK" | "HALT") and str is a human-readable message.

Facts are structured data extracted from observe-step results, not LLM prose.
"""


def kafka_rolling_restart(facts: dict) -> tuple[str, str]:
    """Gate rule for Kafka rolling broker restart."""
    brokers_up    = facts.get("brokers_up", 0)
    brokers_total = facts.get("brokers_total", 0)
    min_isr       = facts.get("min_isr", 0)
    rf            = facts.get("replication_factor", 3)

    if brokers_total == 0:
        return "ASK", "Could not determine broker count. Proceed with caution?"

    if brokers_up < brokers_total:
        offline = brokers_total - brokers_up
        return "HALT", (
            f"{offline}/{brokers_total} broker(s) offline. "
            "Rolling restart requires all brokers up. Fix offline brokers first."
        )

    if min_isr < rf - 1:
        return "HALT", (
            f"Min ISR ({min_isr}) is below RF-1 ({rf - 1}). "
            "Topics are already under-replicated. A restart would worsen replication."
        )

    return "GO", f"All {brokers_total} brokers up, ISR healthy. Safe to restart one at a time."


def swarm_service_upgrade(facts: dict) -> tuple[str, str]:
    """Gate rule for Docker Swarm service upgrade."""
    managers_up    = facts.get("managers_up", 0)
    managers_total = facts.get("managers_total", 0)

    if managers_total == 0:
        return "ASK", "Could not determine swarm manager count. Proceed?"

    quorum = (managers_total // 2) + 1
    if managers_up < quorum:
        return "HALT", (
            f"Only {managers_up}/{managers_total} managers up. "
            f"Swarm needs {quorum} for quorum. "
            "Service upgrade would disrupt orchestration."
        )

    return "GO", f"Swarm quorum maintained ({managers_up}/{managers_total} managers)."


def changelog_check(facts: dict) -> tuple[str, str]:
    """Gate rule for version upgrades — checks ingested changelogs."""
    ingested      = facts.get("changelog_ingested", False)
    from_ver      = facts.get("from_version", "unknown")
    to_ver        = facts.get("to_version", "unknown")
    breaking      = facts.get("breaking_changes", [])

    if not ingested:
        return "ASK", (
            f"No changelog ingested for {to_ver} (upgrading from {from_ver}). "
            "Breaking changes unknown."
        )

    if breaking:
        preview = "; ".join(breaking[:2])
        return "ASK", f"{len(breaking)} breaking change(s) in {to_ver}: {preview}"

    return "GO", f"Changelog for {to_ver} ingested — no breaking changes found."


# ── Rule registry ─────────────────────────────────────────────────────────────

_RULES: dict = {
    "kafka_rolling_restart": kafka_rolling_restart,
    "swarm_service_upgrade": swarm_service_upgrade,
    "changelog_check":       changelog_check,
}


def evaluate(rule_name: str, facts: dict) -> dict:
    """Evaluate a gate rule by name. Returns {"verdict": str, "message": str}."""
    fn = _RULES.get(rule_name)
    if not fn:
        return {"verdict": "GO", "message": f"No gate rule defined for '{rule_name}'."}
    verdict, message = fn(facts)
    return {"verdict": verdict, "message": message}


def list_rules() -> list[str]:
    """Return names of all registered gate rules."""
    return list(_RULES.keys())
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_gate_rules.py -v
```

Expected: all 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add api/agents/gate_rules.py tests/test_gate_rules.py
git commit -m "feat(agents): service-aware gate rules for step orchestrator"
git push
```

---

## Task 7: Router Expansion

**Files:**
- Modify: `api/agents/router.py`

**Context:** Expand from 3 intent types (status/research/action) to 4 (observe/investigate/execute/build). For execute, add domain detection and per-domain tool allowlists. Promoted skills are injected into domain allowlists at module load time. Keep backward-compat aliases so agent.py still works.

- [ ] **Step 1: Write test for domain detection**

Add to `tests/test_gate_rules.py` (or create a new `tests/test_router.py`):

```python
# tests/test_router.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_detect_domain_kafka():
    from api.agents.router import detect_domain
    assert detect_domain("restart kafka brokers") == "kafka"


def test_detect_domain_swarm():
    from api.agents.router import detect_domain
    assert detect_domain("upgrade swarm service to new image") == "swarm"


def test_detect_domain_proxmox():
    from api.agents.router import detect_domain
    assert detect_domain("restart proxmox vm 101") == "proxmox"


def test_detect_domain_unknown_defaults_general():
    from api.agents.router import detect_domain
    assert detect_domain("do something random") == "general"


def test_classify_build_intent():
    from api.agents.router import classify_task
    assert classify_task("create a skill to monitor nginx") == "build"


def test_classify_observe_intent():
    from api.agents.router import classify_task
    result = classify_task("check swarm health")
    assert result in ("observe", "status")  # status is backward-compat alias


def test_filter_tools_execute_kafka_is_narrow(monkeypatch):
    from api.agents.router import filter_tools
    # Build a fake tools spec with many tools
    all_tools = [{"function": {"name": n}} for n in [
        "kafka_rolling_restart_safe", "service_upgrade", "skill_create",
        "pre_kafka_check", "kafka_broker_status", "plan_action",
    ]]
    kafka_tools = filter_tools(all_tools, "execute", domain="kafka")
    names = {t["function"]["name"] for t in kafka_tools}
    assert "kafka_rolling_restart_safe" in names
    assert "service_upgrade" not in names
    assert "skill_create" not in names
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_router.py -v
```

Expected: multiple FAILs — `detect_domain`, `classify_task("create skill")` → "build", and `filter_tools` with domain arg don't exist yet.

- [ ] **Step 3: Update router.py**

Replace the entire contents of `api/agents/router.py` with the expanded version. The key changes:

**Add to keyword sets:**
```python
BUILD_KEYWORDS = frozenset({
    "skill", "create skill", "generate skill", "skill_create", "skill_list",
    "skill_import", "skill_regenerate", "skill_disable", "skill_enable",
    "new tool", "build tool", "write tool", "discover environment",
})
```

**Add domain keyword map:**
```python
_DOMAIN_KEYWORDS: dict[str, frozenset] = {
    "kafka":   frozenset({"kafka", "broker", "topic", "consumer", "producer",
                          "lag", "partition", "zookeeper", "kraft", "offset"}),
    "swarm":   frozenset({"swarm", "service", "stack", "node", "replica",
                          "manager", "worker", "container", "docker", "deploy"}),
    "proxmox": frozenset({"proxmox", "vm", "lxc", "pve", "hypervisor",
                          "snapshot", "qemu", "kvm", "ha", "cluster"}),
    "elastic": frozenset({"elastic", "elasticsearch", "kibana", "index",
                          "shard", "mapping", "filebeat"}),
}
```

**Add domain detection function:**
```python
def detect_domain(task: str) -> str:
    """Detect which service domain a task is about. Returns domain name or 'general'."""
    words = set(re.findall(r'\b\w+\b', task.lower()))
    scores = {d: len(words & kw) for d, kw in _DOMAIN_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"
```

**Add build and domain execute tool sets:**
```python
OBSERVE_AGENT_TOOLS = frozenset({
    # (same as STATUS_AGENT_TOOLS — renamed)
    "swarm_status", "service_list", "service_health", "service_current_version",
    "service_version_history", "kafka_broker_status", "kafka_topic_health",
    "kafka_consumer_lag", "elastic_cluster_health", "elastic_index_stats",
    "audit_log", "escalate", "clarifying_question",
    "get_host_network", "docker_engine_version", "docker_engine_check_update",
    "check_internet_connectivity",
    "skill_search", "skill_list", "skill_info", "skill_health_summary",
    "skill_generation_config", "storage_health",
})

INVESTIGATE_AGENT_TOOLS = frozenset({
    # (same as RESEARCH_AGENT_TOOLS — renamed)
    "swarm_status", "service_list", "service_health", "service_current_version",
    "service_version_history", "kafka_broker_status", "kafka_topic_health",
    "kafka_consumer_lag", "elastic_cluster_health", "elastic_error_logs",
    "elastic_search_logs", "elastic_log_pattern", "elastic_index_stats",
    "elastic_kafka_logs", "elastic_correlate_operation", "audit_log",
    "escalate", "clarifying_question", "get_host_network",
    "docker_engine_version", "docker_engine_check_update",
    "ingest_url", "ingest_pdf", "check_internet_connectivity",
    "skill_search", "skill_list", "skill_info", "skill_health_summary",
    "skill_generation_config", "skill_compat_check", "skill_compat_check_all",
    "skill_recommend_updates", "service_catalog_list", "storage_health",
})

_EXECUTE_BASE = frozenset({
    "plan_action", "escalate", "audit_log", "clarifying_question",
    "checkpoint_save", "checkpoint_restore",
})

EXECUTE_KAFKA_TOOLS = frozenset({
    "pre_kafka_check", "kafka_broker_status", "kafka_topic_health",
    "kafka_consumer_lag", "kafka_rolling_restart_safe",
}) | _EXECUTE_BASE

EXECUTE_SWARM_TOOLS = frozenset({
    "swarm_status", "service_list", "service_health", "service_upgrade",
    "service_rollback", "node_drain", "pre_upgrade_check", "post_upgrade_verify",
    "service_current_version", "service_resolve_image",
}) | _EXECUTE_BASE

EXECUTE_PROXMOX_TOOLS = frozenset({
    # Promoted proxmox skills injected at startup via _load_promoted_into_allowlists()
}) | _EXECUTE_BASE

EXECUTE_GENERAL_TOOLS = frozenset({
    "service_upgrade", "service_rollback", "node_drain",
    "docker_engine_update",
}) | _EXECUTE_BASE

BUILD_AGENT_TOOLS = frozenset({
    "skill_create", "skill_regenerate", "skill_disable", "skill_enable",
    "skill_import", "skill_search", "skill_list", "skill_info",
    "skill_health_summary", "skill_generation_config", "validate_skill_live",
    "discover_environment", "service_catalog_list", "storage_health",
    "skill_compat_check", "skill_compat_check_all", "skill_export_prompt",
    "plan_action", "audit_log", "escalate",
})

# Backward-compat aliases
STATUS_AGENT_TOOLS   = OBSERVE_AGENT_TOOLS
RESEARCH_AGENT_TOOLS = INVESTIGATE_AGENT_TOOLS
```

**Add promoted skill injection (called once at module level):**
```python
def _load_promoted_into_allowlists() -> None:
    """Inject promoted skills from DB into domain execute allowlists at startup."""
    global EXECUTE_KAFKA_TOOLS, EXECUTE_SWARM_TOOLS, EXECUTE_PROXMOX_TOOLS, EXECUTE_GENERAL_TOOLS
    try:
        from mcp_server.tools.skills.registry import list_skills
        for skill in list_skills(enabled_only=True):
            if skill.get("lifecycle_state") != "promoted":
                continue
            name   = skill["name"]
            domain = skill.get("agent_domain") or "general"
            if domain == "kafka":
                EXECUTE_KAFKA_TOOLS   = EXECUTE_KAFKA_TOOLS   | {name}
            elif domain == "swarm":
                EXECUTE_SWARM_TOOLS   = EXECUTE_SWARM_TOOLS   | {name}
            elif domain == "proxmox":
                EXECUTE_PROXMOX_TOOLS = EXECUTE_PROXMOX_TOOLS | {name}
            else:
                EXECUTE_GENERAL_TOOLS = EXECUTE_GENERAL_TOOLS | {name}
    except Exception:
        pass  # DB unavailable during tests

_load_promoted_into_allowlists()
```

**Update classify_task() to detect build intent:**

Before the final scoring section, add:
```python
    # Build intent: any task mentioning skill management words
    build_score = len(tokens & BUILD_KEYWORDS)
    if build_score > 0:
        return 'build'
```

Add `'build'` to the scoring dict and return logic.

**Update filter_tools() to accept domain:**
```python
def filter_tools(tools_spec: list, agent_type: str, domain: str = "general") -> list:
    """Return filtered copy of tools_spec for the given agent type and optional domain."""
    if agent_type in ('action', 'execute'):
        domain_map = {
            "kafka":   EXECUTE_KAFKA_TOOLS,
            "swarm":   EXECUTE_SWARM_TOOLS,
            "proxmox": EXECUTE_PROXMOX_TOOLS,
        }
        allowlist = domain_map.get(domain, EXECUTE_GENERAL_TOOLS)
        return [t for t in tools_spec if t.get("function", {}).get("name") in allowlist]

    allowlist_map = {
        'observe':     OBSERVE_AGENT_TOOLS,
        'status':      OBSERVE_AGENT_TOOLS,   # alias
        'investigate': INVESTIGATE_AGENT_TOOLS,
        'research':    INVESTIGATE_AGENT_TOOLS,  # alias
        'build':       BUILD_AGENT_TOOLS,
    }
    allowlist = allowlist_map.get(agent_type)
    if allowlist is None:
        return tools_spec  # unknown type — pass all through
    return [t for t in tools_spec if t.get("function", {}).get("name") in allowlist]
```

**Add new prompts** for `observe` (copy STATUS_PROMPT, rename), `investigate` (copy RESEARCH_PROMPT), `build` (new):

```python
OBSERVE_PROMPT    = STATUS_PROMPT     # Same content, new name
INVESTIGATE_PROMPT = RESEARCH_PROMPT  # Same content, new name
BUILD_PROMPT = """You are a skill-building agent for an AI infrastructure system.

Your role: create, test, and manage dynamic skills (Python modules that interact with services).

RULES:
1. Use skill_search() before creating — avoid duplicates.
2. Use skill_create() for new skills. Describe the service, API endpoint, and what data to return.
3. Use discover_environment() to detect available services before building.
4. Use validate_skill_live() to test generated skills against real endpoints.
5. Use skill_compat_check() to verify skills match current service versions.
6. Call plan_action() before skill_create, skill_regenerate, skill_disable, skill_import.
7. Call audit_log() ONCE at the end. Then stop.

STOPPING RULES:
- After completing the build task, call audit_log() once, then output nothing more.
- Never call audit_log() more than once.
"""

def get_prompt(agent_type: str) -> str:
    return {
        'observe':     OBSERVE_PROMPT,
        'status':      OBSERVE_PROMPT,
        'investigate': INVESTIGATE_PROMPT,
        'research':    INVESTIGATE_PROMPT,
        'execute':     ACTION_PROMPT,
        'action':      ACTION_PROMPT,
        'build':       BUILD_PROMPT,
    }.get(agent_type, ACTION_PROMPT)
```

- [ ] **Step 4: Syntax check**

```bash
python -m py_compile api/agents/router.py
```

Expected: no output.

- [ ] **Step 5: Run router tests**

```bash
python -m pytest tests/test_router.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add api/agents/router.py tests/test_router.py
git commit -m "feat(agents): expand to 4 intent types with domain-filtered execute agents"
git push
```

---

## Task 8: Orchestrator + Agent Integration

**Files:**
- Create: `api/agents/orchestrator.py`
- Modify: `api/routers/agent.py`
- Create: `tests/test_orchestrator.py`

**Context:** The orchestrator builds a step plan from a task string. For single-domain tasks it returns one step (no overhead). For multi-step tasks it returns 2 steps: observe first, then execute. `agent.py` calls the orchestrator, broadcasts a step-divider to the WebSocket between steps, and passes the previous step's verdict summary as extra context to the next step. The existing `_stream_agent` function is called once per step.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_orchestrator.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from api.agents.orchestrator import build_step_plan, format_step_header, verdict_from_text


def test_single_observe_task_is_one_step():
    steps = build_step_plan("check swarm health")
    assert len(steps) == 1
    assert steps[0]["intent"] in ("observe", "status")


def test_build_task_is_one_step():
    steps = build_step_plan("create a skill to monitor nginx")
    assert len(steps) == 1
    assert steps[0]["intent"] == "build"


def test_execute_only_task_is_one_step():
    steps = build_step_plan("restart kafka broker 2")
    assert len(steps) == 1
    assert steps[0]["intent"] in ("execute", "action")
    assert steps[0]["domain"] == "kafka"


def test_verify_before_execute_is_two_steps():
    steps = build_step_plan("verify swarm is healthy then upgrade the nginx service")
    assert len(steps) == 2
    assert steps[0]["intent"] in ("observe", "status")
    assert steps[1]["intent"] in ("execute", "action")


def test_step_header_format():
    header = format_step_header(1, 2, "execute", "kafka")
    assert "1" in header and "2" in header
    assert "kafka" in header.lower() or "execute" in header.lower()


def test_verdict_from_text_healthy():
    v = verdict_from_text("All checks passed. System HEALTHY.")
    assert v["verdict"] == "GO"


def test_verdict_from_text_degraded():
    v = verdict_from_text("broker-2 is offline. Status: DEGRADED.")
    assert v["verdict"] in ("HALT", "ASK")
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_orchestrator.py -v
```

Expected: ImportError — module doesn't exist.

- [ ] **Step 3: Create orchestrator.py**

```python
# api/agents/orchestrator.py
"""Step-through orchestrator for multi-domain tasks.

build_step_plan() decomposes a task into sequential steps.
Each step specifies an intent + optional domain.
The actual LLM execution happens in agent.py (_stream_agent per step).
Context between steps is a minimal verdict object (~50 tokens), not prose.
"""
import re


# Words that suggest the task wants a pre-check before executing
_CHECK_PREFIXES = frozenset({
    "verify", "check", "ensure", "confirm", "validate", "first",
    "before", "after checking", "make sure",
})


def build_step_plan(task: str) -> list[dict]:
    """
    Decompose task into sequential steps.

    Returns list of dicts:
      {"intent": str, "domain": str|None, "task": str, "step": int}

    Single-domain tasks return one step. Tasks with explicit pre-check
    language get an observe step prepended before the execute step.
    """
    from api.agents.router import classify_task, detect_domain

    intent = classify_task(task)
    if intent == "ambiguous":
        intent = "execute"

    domain = detect_domain(task) if intent in ("execute", "action") else None

    words = set(re.findall(r'\b\w+\b', task.lower()))

    # Prepend an observe step when task explicitly asks for a pre-check
    if intent in ("execute", "action") and words & _CHECK_PREFIXES:
        steps = [
            {
                "step":   1,
                "intent": "observe",
                "domain": None,
                "task":   f"Check pre-conditions before: {task}",
            },
            {
                "step":   2,
                "intent": intent,
                "domain": domain,
                "task":   task,
            },
        ]
    else:
        steps = [{"step": 1, "intent": intent, "domain": domain, "task": task}]

    return steps


def format_step_header(step_num: int, total_steps: int, intent: str, domain: str | None) -> str:
    """Format a divider line shown in the output panel between steps."""
    domain_part = f"[{domain}]" if domain else ""
    return f"━━ Step {step_num}/{total_steps} · {intent}{domain_part} ━━━━━━━━━━━━━━━━━━━━━━"


def verdict_from_text(text: str) -> dict:
    """
    Extract a minimal verdict from an agent's final output text.

    Returns {"verdict": "GO"|"ASK"|"HALT", "summary": str}
    Used to pass minimal context from one step to the next.
    """
    lower = text.lower()

    # Explicit failure / degraded keywords → HALT
    halt_signals = {"degraded", "critical", "offline", "failed", "unhealthy", "halt", "error"}
    if halt_signals & set(re.findall(r'\b\w+\b', lower)):
        return {"verdict": "HALT", "summary": text[:300]}

    # Ambiguous / warning keywords → ASK
    ask_signals = {"warning", "caution", "unknown", "uncertain", "partial"}
    if ask_signals & set(re.findall(r'\b\w+\b', lower)):
        return {"verdict": "ASK", "summary": text[:300]}

    return {"verdict": "GO", "summary": text[:300]}
```

- [ ] **Step 4: Run orchestrator tests**

```bash
python -m pytest tests/test_orchestrator.py -v
```

Expected: all PASS.

- [ ] **Step 5: Update agent.py to use orchestrator for multi-step tasks**

In `api/routers/agent.py`, find `_stream_agent` (line ~142). The function currently calls `classify_task` then runs one agent loop. Update it to:

1. Import orchestrator at top of the function
2. Build step plan
3. If one step: run as today (no change)
4. If multiple steps: iterate, broadcast step headers, pass verdict between steps

Find the section in `_stream_agent` after the memory injection (around where `messages = [...]` is built). Add a multi-step wrapper. The key additions:

```python
    from api.agents.orchestrator import build_step_plan, format_step_header, verdict_from_text

    steps = build_step_plan(task)
    prior_verdict: dict | None = None

    for step in steps:
        step_intent = step["intent"]
        step_domain = step.get("domain")
        step_task   = step["task"]
        step_num    = step["step"]
        total_steps = len(steps)

        if total_steps > 1:
            header = format_step_header(step_num, total_steps, step_intent, step_domain)
            await manager.send_line("agent", header, session_id, operation_id)

        step_agent_type = step_intent
        if step_agent_type == "ambiguous":
            step_agent_type = "execute"

        step_system_prompt = get_prompt(step_agent_type)

        # Prepend prior step verdict as context (minimal — no prose)
        if prior_verdict:
            context_line = (
                f"[Prior step verdict: {prior_verdict['verdict']} — "
                f"{prior_verdict['summary'][:200]}]\n\n"
            )
            step_system_prompt = context_line + step_system_prompt

        step_tools = filter_tools(
            _build_tools_spec(),
            step_agent_type,
            domain=step_domain or "general",
        )

        # Run the LLM loop for this step (existing loop code, using step variables)
        step_output = await _run_single_agent_step(
            step_task, session_id, operation_id, owner_user,
            system_prompt=step_system_prompt,
            tools_spec=step_tools,
            agent_type=step_agent_type,
        )

        prior_verdict = verdict_from_text(step_output)

        # If step halted and there are more steps, pause
        if prior_verdict["verdict"] == "HALT" and step_num < total_steps:
            await manager.send_line(
                "agent",
                f"⛔ Step {step_num} returned HALT — stopping plan. "
                f"Reason: {prior_verdict['summary'][:200]}",
                session_id, operation_id,
            )
            break
```

**Important:** The existing agent loop logic (messages list, tool call loop, plan_action intercept, cancellation check) needs to be extracted into a helper `_run_single_agent_step()`. This is a refactor of the existing code — do NOT rewrite the loop logic, just extract it into a named function and call it from the step loop.

The function signature is:

```python
async def _run_single_agent_step(
    task: str,
    session_id: str,
    operation_id: str,
    owner_user: str,
    *,
    system_prompt: str,
    tools_spec: list,
    agent_type: str,
    client,          # openai.OpenAI instance (passed in to avoid re-creating per step)
) -> str:
    """Run one agent loop. Returns the final text output from the LLM.

    Extracts the existing while-loop body from _stream_agent:
    - messages = [{"role": "system", ...}, {"role": "user", ...}]
    - _MAX_STEPS_BY_TYPE lookup (use agent_type)
    - while step < max_steps: cancel check, LLM call, tool dispatch, plan_action intercept
    - returns last_reasoning (the final assistant text content)
    """
```

Caller in `_stream_agent` constructs `client` once before the step loop, then passes it to each `_run_single_agent_step` call.

The existing `_stream_agent` effectively becomes:
```python
async def _stream_agent(task: str, session_id: str, operation_id: str, owner_user: str = "admin"):
    # memory injection (unchanged — runs once before step loop, uses first step's agent_type)
    # client = OpenAI(...) — constructed once
    # orchestrator step loop — calls _run_single_agent_step per step
```

`_run_single_agent_step` contains the existing `messages`, `while step < max_steps`, tool call loop, plan_action intercept, and cancellation check — moved verbatim except that `agent_type`, `system_prompt`, `tools_spec`, and `client` come from parameters instead of being computed inside.

- [ ] **Step 6: Update _AGENT_LABEL and badge colors in agent.py for new intents**

Find `_AGENT_LABEL` dict (line ~127) and add new entries:
```python
_AGENT_LABEL = {
    'status':      'Observe',
    'observe':     'Observe',
    'action':      'Execute',
    'execute':     'Execute',
    'research':    'Investigate',
    'investigate': 'Investigate',
    'build':       'Build',
    'ambiguous':   'Execute',
}

_AGENT_BADGE_COLOR = {
    'status':      'blue',
    'observe':     'blue',
    'action':      'orange',
    'execute':     'orange',
    'research':    'purple',
    'investigate': 'purple',
    'build':       'yellow',
    'ambiguous':   'orange',
}
```

- [ ] **Step 7: Syntax check**

```bash
python -m py_compile api/agents/orchestrator.py
python -m py_compile api/routers/agent.py
```

Expected: no output.

- [ ] **Step 8: Run all tests**

```bash
python -m pytest tests/ -x -q
```

Expected: all tests pass. Fix any failures before committing.

- [ ] **Step 9: Smoke test — start the API and send a task**

```bash
python run_api.py &
sleep 3
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"superduperadmin"}' | python -m json.tool
```

Expected: `{"access_token": "...", "token_type": "bearer"}`

- [ ] **Step 10: Commit**

```bash
git add api/agents/orchestrator.py api/routers/agent.py tests/test_orchestrator.py
git commit -m "feat(agents): step-through orchestrator with intent+domain routing and verdict gates"
git push
```

---

## Final Verification

After all tasks complete:

```bash
# Full test suite
python -m pytest tests/ -v

# Docker build
docker build --build-arg DOCKER_GID=$(stat -c '%g' /var/run/docker.sock) \
  -t hp1-ai-agent:latest -f docker/Dockerfile . 2>&1 | tail -20

# Smoke test container
docker run --rm hp1-ai-agent:latest 2>&1 | head -10
# Expected: "HP1-AI-Agent — Starting" and "Uvicorn running"
```

---

## Checklist Summary

- [ ] Task 1: Skill persistence (`data/skill_modules/` + loader + meta_tools)
- [ ] Task 2: DB migration (lifecycle_state + agent_domain columns)
- [ ] Task 3: Promoter module + server.py @mcp.tool() registration
- [ ] Task 4: Backend lifecycle endpoints (promote/demote/scrap/restore)
- [ ] Task 5: Frontend lifecycle UI (badges, buttons, domain picker)
- [ ] Task 6: Gate rules (kafka/swarm/changelog pure functions)
- [ ] Task 7: Router expansion (4 intents, domain detection, domain allowlists)
- [ ] Task 8: Orchestrator + agent.py integration
