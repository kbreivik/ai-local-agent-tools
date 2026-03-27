# Security Hardening: Agent Loop Safety & Skill Sandbox

**Date:** 2026-03-27
**Status:** Ready to implement
**Target version:** 1.10.21 (bump from current 1.10.18)

---

## Goal

Fix two distinct security/safety gaps discovered in code review:

1. **P1 #6 / P2 #38 — `_cancel_flags` memory leak and phantom-flag injection** in `api/routers/agent.py`. The dict grows without bound; a `/stop` call for a non-existent session permanently inserts a key that is never cleaned up.
2. **P1 #7 — Skill sandbox gaps** in `mcp_server/tools/skills/validator.py`. Several modules (`os`, `socket`, `urllib`, `http`, `ftplib`, `ssl`) are not on the ban list, and `from ctypes import cdll` bypasses the existing `import ctypes` check.

---

## Architecture Impact

Both fixes are confined to two files plus new tests. No schema changes, no new dependencies, no API surface changes.

---

## Tech Stack

- Python 3.13, FastAPI, pytest
- `ast` module (already used by validator — no new imports needed for fix #2)
- `time.monotonic()` (stdlib — no new imports for fix #1)

---

## File Map

| File | Change type |
|---|---|
| `api/routers/agent.py` | Modify `_cancel_flags` type, add `_cleanup_stale_cancel_flags()`, validate session_id in `stop_agent`, pop flag in `_run_single_agent_step` finally block |
| `mcp_server/tools/skills/validator.py` | Extend `_BANNED_MODULES`, add `from ctypes import ...` block in the `ImportFrom` branch |
| `mcp_server/tools/skills/modules/proxmox_vm_status.py` | Update starter skill to remove `import os` (replace with inline path construction using stdlib only — see Task 2 notes) |
| `tests/test_cancel_flags.py` | New file — unit tests for cancel flag lifecycle |
| `tests/test_skill_validator.py` | New file — unit tests for expanded sandbox bans |
| `VERSION` | Bump to `1.10.21` in final commit |

---

## Pre-flight: Confirm Baseline

- [ ] Run `pytest tests/ -x -q` from `D:/claude_code/FAJK/HP1-AI-Agent-v1`
  - Expected: 17 pass, 1 fail (`test_collectors_proxmox_vms.py` — pre-existing, unrelated)

---

## Task 1 — `_cancel_flags` hardening in `api/routers/agent.py`

### Background

**Line 61 (current):**
```python
_cancel_flags: dict[str, bool] = {}
```

**Problem 1 (P1 #6):** Every session that runs through `_run_single_agent_step` pops its own key with `_cancel_flags.pop(session_id, False)` at the top of each step iteration. If the loop exits via exception *before* the pop fires on the first iteration, the key is never removed. More critically, the key is *inserted* in `stop_agent` at line 884 whether or not a session with that ID actually exists. A caller who POSTs a bogus `session_id` will create a key that lives forever.

**Problem 2 (P2 #38):** `stop_agent` at line 882–883 already validates `not req.session_id` (empty string), but a non-empty, non-existent session ID bypasses that guard completely and permanently inserts a `True` flag.

**Current `stop_agent` (lines 879–894):**
```python
@router.post("/stop")
async def stop_agent(req: StopRequest):
    if not req.session_id:
        return {"status": "error", "message": "session_id required"}
    _cancel_flags[req.session_id] = True
    ...
```

**Current cancel-check in `_run_single_agent_step` (line 191):**
```python
if _cancel_flags.pop(session_id, False):
```
This pop fires only at the top of each step iteration. If the loop is never entered (e.g., the LLM call immediately raises on step 1 before the pop), a flag set just before the run will remain. More importantly, flags set for sessions that never run at all accumulate indefinitely.

### Implementation

#### Step 1a — Change the type annotation and write the cleanup helper

**Change at line 61** — replace:
```python
_cancel_flags: dict[str, bool] = {}
```
with:
```python
# Values are (flag: bool, inserted_at: float) where inserted_at is time.monotonic().
# Entries older than _CANCEL_FLAG_TTL_SECONDS are pruned by _cleanup_stale_cancel_flags().
_CANCEL_FLAG_TTL_SECONDS = 300  # 5 minutes
_cancel_flags: dict[str, tuple[bool, float]] = {}
```

**Add after the new `_cancel_flags` definition:**
```python
def _cleanup_stale_cancel_flags() -> None:
    """Remove cancel flag entries that were inserted more than _CANCEL_FLAG_TTL_SECONDS ago."""
    cutoff = time.monotonic() - _CANCEL_FLAG_TTL_SECONDS
    stale = [k for k, (_, ts) in _cancel_flags.items() if ts < cutoff]
    for k in stale:
        _cancel_flags.pop(k, None)
```

#### Step 1b — Validate session_id length in `stop_agent`

**Change `stop_agent` (lines 879–884)** — replace the existing guard:
```python
if not req.session_id:
    return {"status": "error", "message": "session_id required"}
_cancel_flags[req.session_id] = True
```
with:
```python
sid = req.session_id.strip()
if not sid:
    return {"status": "error", "message": "session_id required"}
if len(sid) > 128:
    return {"status": "error", "message": "session_id too long"}
_cleanup_stale_cancel_flags()
_cancel_flags[sid] = (True, time.monotonic())
```

#### Step 1c — Update all reads of `_cancel_flags`

There is one read site in `_run_single_agent_step` at line 191:
```python
if _cancel_flags.pop(session_id, False):
```
Replace with:
```python
if _cancel_flags.pop(session_id, (False, 0.0))[0]:
```

#### Step 1d — Guarantee cleanup in `_run_single_agent_step` finally block

`_run_single_agent_step` currently has a `try/except Exception` block (lines 188–612) but no `finally`. The function does not hold any cancel-flag entry itself (it only *reads* one inserted by `stop_agent`), but we should also call `_cleanup_stale_cancel_flags()` periodically as a belt-and-suspenders measure. Add this at the top of the function just before the `while step < max_steps:` loop, inside the `try:` block:

```python
_cleanup_stale_cancel_flags()
```

This ensures every agent step invocation sweeps stale flags. The call is O(n) over the flag dict, which is expected to be tiny in normal operation.

Additionally, `_stream_agent` already has a `finally:` block (line 819). Add a call there as well:
```python
finally:
    _cleanup_stale_cancel_flags()   # ← add this line
    await plan_lock.release(session_id)
    ...
```

### Tests — `tests/test_cancel_flags.py` (new file)

```python
"""Unit tests for _cancel_flags lifecycle in api.routers.agent."""
import time
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import api.routers.agent as agent_mod


def _reset():
    agent_mod._cancel_flags.clear()


def test_stop_empty_session_id_rejected():
    _reset()
    import asyncio
    from api.routers.agent import StopRequest, stop_agent
    req = StopRequest(session_id="")
    result = asyncio.get_event_loop().run_until_complete(stop_agent(req))
    assert result["status"] == "error"
    assert not agent_mod._cancel_flags


def test_stop_too_long_session_id_rejected():
    _reset()
    import asyncio
    from api.routers.agent import StopRequest, stop_agent
    req = StopRequest(session_id="x" * 200)
    result = asyncio.get_event_loop().run_until_complete(stop_agent(req))
    assert result["status"] == "error"
    assert not agent_mod._cancel_flags


def test_stop_valid_session_inserts_flag():
    _reset()
    import asyncio
    from api.routers.agent import StopRequest, stop_agent
    req = StopRequest(session_id="test-session-abc")
    result = asyncio.get_event_loop().run_until_complete(stop_agent(req))
    assert result["status"] == "ok"
    assert "test-session-abc" in agent_mod._cancel_flags
    flag, ts = agent_mod._cancel_flags["test-session-abc"]
    assert flag is True
    assert isinstance(ts, float)


def test_cleanup_removes_stale_entries():
    _reset()
    # Insert an entry with a timestamp well in the past
    old_ts = time.monotonic() - (agent_mod._CANCEL_FLAG_TTL_SECONDS + 10)
    agent_mod._cancel_flags["stale-session"] = (True, old_ts)
    agent_mod._cleanup_stale_cancel_flags()
    assert "stale-session" not in agent_mod._cancel_flags


def test_cleanup_preserves_fresh_entries():
    _reset()
    agent_mod._cancel_flags["fresh-session"] = (True, time.monotonic())
    agent_mod._cleanup_stale_cancel_flags()
    assert "fresh-session" in agent_mod._cancel_flags


def test_flag_read_returns_bool_and_pops():
    _reset()
    agent_mod._cancel_flags["pop-me"] = (True, time.monotonic())
    # Simulate what the loop does
    val = agent_mod._cancel_flags.pop("pop-me", (False, 0.0))[0]
    assert val is True
    assert "pop-me" not in agent_mod._cancel_flags
```

- [ ] Create `tests/test_cancel_flags.py` with the tests above
- [ ] Run `pytest tests/test_cancel_flags.py -x -q`
  - Expected: **6 pass** (tests run against unchanged code — most will fail)
- [ ] Apply the changes in `api/routers/agent.py` described in steps 1a–1d
- [ ] Run `python -m py_compile api/routers/agent.py` — expect: no output (success)
- [ ] Run `pytest tests/test_cancel_flags.py -x -q`
  - Expected: **6 pass**
- [ ] Run `pytest tests/ -x -q`
  - Expected: 23 pass (17 original + 6 new), 1 pre-existing fail

---

## Task 2 — Skill sandbox hardening in `mcp_server/tools/skills/validator.py`

### Background

**Starter skill import audit (read before adding bans):**

| Skill file | Imports `os`? | Imports `socket`/`urllib`/`http`/`ssl`? |
|---|---|---|
| `proxmox_vm_status.py` | **YES** — `import os` at line 3 | No |
| `fortigate_system_status.py` | **YES** — `import os` at line 3 | No |
| `http_health_check.py` | No | No (`httpx` only) |

Both `proxmox_vm_status.py` and `fortigate_system_status.py` use `os` for two things:
1. `os.path.join` / `os.path.dirname` / `os.path.exists` — to locate `agent_settings.json`
2. `os.environ.get(...)` — to read config env vars

These are legitimate, controlled uses. However, if we ban `os`, these skills will fail validation when scanned by the validator. The validator is invoked on generated skills, but the loader (`loader.py`) also scans all files in `modules/`. Banning `os` *will* break the starter skill validation pass unless we update the starter skills first.

**Decision:** Update both starter skills to remove `import os` before adding `os` to `_BANNED_MODULES`. Use only `pathlib.Path` and a direct `environ` dict access pattern that does not require importing `os`.

However, `os.environ` is accessed as `os.environ.get(...)` in the starter skills — removing `import os` means replacing these with an alternative. The cleanest approach is:

```python
import json
from pathlib import Path
from os import environ as _env   # narrow import: only environ, not os.system etc.
```

**Problem:** `from os import environ` would still trigger the `ImportFrom` check if `os` is in `_BANNED_MODULES` (the `mod_root` check at line 76 uses `node.module.split(".")[0]` which equals `"os"`). So we cannot simply do `from os import environ`.

**Alternative — use `os.environ` via a lazy import guarded against the validator:** Not viable; the validator sees all imports.

**Best approach:** Change `os.path.*` to `pathlib.Path` operations (already imported as standard), and replace `os.environ.get(...)` with a private helper that calls `os.environ.get(...)` but is defined outside the main module body via an inline-only reference. This is messy.

**Cleanest approach for the starter skills:** Keep `import os` in the starter skills and instead ban a stricter subset that excludes `os` but adds explicit bans on the dangerous `os.*` calls beyond `os.system` and `os.popen`. Specifically, add to the call-level check:

```python
_BANNED_OS_ATTRS = frozenset({
    "system", "popen", "remove", "unlink", "rmdir", "makedirs",
    "mkdir", "rename", "replace", "listdir", "scandir", "walk",
    "execv", "execve", "execvp", "execvpe", "fork", "kill",
    "getenv",  # use os.environ.get — getenv is fine but document it
})
```

Wait — `os.environ.get` is attribute access on `os.environ`, not a direct `os.*` call. The current check catches `os.system(...)` via `isinstance(func.value, ast.Name) and func.value.id == "os"`. Reading `os.environ.get(key, default)` is `func = Attribute(value=Attribute(value=Name('os'), attr='environ'), attr='get')` — not caught by the current check. So `os.environ` access is already not blocked by the current banned-call check.

**Conclusion:** We can safely ban `os` at the import level, but we must first update the starter skills to not import `os`. The correct path for the starter skills is to replace:

```python
import os
...
os.path.join(...)
os.path.dirname(...)
os.path.exists(...)
os.environ.get(...)
```

with:

```python
import json
from pathlib import Path
import sys  # only if needed for path manipulation — not needed here

# For config reading:
_SETTINGS_PATH = Path(__file__).parents[5] / "data" / "agent_settings.json"

# For env var access — use a private helper that caches the environ reference:
def _env(key: str, default: str = "") -> str:
    import os as _os
    return _os.environ.get(key, default)
```

**But:** `import os as _os` inside a function would still appear in the AST and be caught if `os` is in `_BANNED_MODULES` (module name is `os`). The `mod_root` extraction at line 69 is `alias.name.split(".")[0]` — `"os"` splits to `["os"]`, so `mod_root == "os"`.

**Final decision (pragmatic and safe):** Do NOT add `os` to `_BANNED_MODULES`. Instead, extend the `os.*` call-level ban to cover a broader set of dangerous `os` attributes. This is strictly better than the status quo (which only bans `os.system` and `os.popen`), does not break the starter skills, and addresses the real threat (filesystem mutation, process execution). Document the rationale in the code.

Add a broader `_BANNED_OS_CALLS` set and update the call check accordingly. Also add `socket`, `urllib`, `http`, `ftplib`, and `ssl` to `_BANNED_MODULES` (none of the starter skills import them).

### Exact changes to `mcp_server/tools/skills/validator.py`

#### Change 1 — Extend `_BANNED_MODULES` (lines 7–9)

**Current:**
```python
_BANNED_MODULES = frozenset({
    "subprocess", "shutil", "importlib", "ctypes", "multiprocessing",
})
```

**New:**
```python
_BANNED_MODULES = frozenset({
    "subprocess", "shutil", "importlib", "ctypes", "multiprocessing",
    # Network exfiltration vectors — skills must use httpx (already on allow-list by absence)
    "socket", "urllib", "http", "ftplib", "ssl",
    # Note: 'os' is intentionally NOT banned here because starter skills use os.environ.get()
    # and os.path.*. Dangerous os.* calls are blocked at the call-level via _BANNED_OS_CALLS.
})
```

#### Change 2 — Add `_BANNED_OS_CALLS` constant (after `_WRITE_MODES`, line 27)

**Add after line 27:**
```python
# os.* calls that are never legitimate in a skill
_BANNED_OS_CALLS = frozenset({
    "system", "popen",           # already checked — kept here for documentation
    "remove", "unlink", "rmdir",
    "makedirs", "mkdir",
    "rename", "replace",
    "listdir", "scandir", "walk",
    "execv", "execve", "execvp", "execvpe",
    "fork", "kill", "killpg",
    "chown", "chmod",
    "symlink", "link",
})
```

#### Change 3 — Update the `os.*` call check (lines 88–92)

**Current:**
```python
            if isinstance(func, ast.Attribute):
                if isinstance(func.value, ast.Name) and func.value.id == "os":
                    if func.attr in ("system", "popen"):
                        return {"valid": False, "error": f"Banned call: os.{func.attr}"}
```

**New:**
```python
            if isinstance(func, ast.Attribute):
                if isinstance(func.value, ast.Name) and func.value.id == "os":
                    if func.attr in _BANNED_OS_CALLS:
                        return {"valid": False, "error": f"Banned call: os.{func.attr}"}
```

#### Change 4 — Add `from ctypes import ...` ban in `ImportFrom` check (after line 78)

The current `ImportFrom` block (lines 74–82):
```python
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mod_root = node.module.split(".")[0]
                if mod_root in _BANNED_MODULES:
                    return {"valid": False, "error": f"Banned import from: {node.module}"}
            if node.names:
                for alias in node.names:
                    if alias.name in _BANNED_NAMES:
                        return {"valid": False, "error": f"Banned import name: {alias.name}"}
```

`from ctypes import cdll` has `node.module == "ctypes"`, which is already in `_BANNED_MODULES`, so `mod_root == "ctypes"` — the existing check at line 77 already catches this. **Verify this before declaring the fix done.**

However, `from ctypes.util import find_library` has `node.module == "ctypes.util"`, which splits to `mod_root == "ctypes"` — also caught.

The original bug report states `from ctypes import ...` bypasses the check. Re-reading the validator: the `Import` branch (line 67) checks `alias.name.split(".")[0]` against `_BANNED_MODULES`. For `import ctypes`, `alias.name == "ctypes"` and `mod_root == "ctypes"` — caught. For `from ctypes import cdll`, this hits the `ImportFrom` branch at line 74, and `node.module == "ctypes"` so `mod_root == "ctypes"` — also caught by line 77.

**Conclusion:** The existing `ImportFrom` logic already catches `from ctypes import cdll` because `mod_root == "ctypes"` is in `_BANNED_MODULES`. The claim in the issue description appears to be incorrect for the current code. To be certain, write a test that confirms this and document the finding. No code change is needed for ctypes. The test itself is the deliverable.

### Tests — `tests/test_skill_validator.py` (new file)

```python
"""Unit tests for mcp_server.tools.skills.validator — sandbox ban rules."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from mcp_server.tools.skills.validator import validate_skill_code

# ── Helpers ──────────────────────────────────────────────────────────────────

_VALID_MINIMAL = '''
SKILL_META = {
    "name": "test_skill",
    "description": "A test skill",
    "category": "monitoring",
    "parameters": {},
}

def execute(**kwargs):
    return {"status": "ok", "data": None, "timestamp": "", "message": "ok"}
'''


def _skill_with_header(import_line: str, body: str = "") -> str:
    return f"""{import_line}

SKILL_META = {{
    "name": "test_skill",
    "description": "A test skill",
    "category": "monitoring",
    "parameters": {{}},
}}

def execute(**kwargs):
    {body or 'return {"status": "ok", "data": None, "timestamp": "", "message": "ok"}'}
"""


# ── Existing bans still work ──────────────────────────────────────────────────

def test_subprocess_banned():
    code = _skill_with_header("import subprocess")
    result = validate_skill_code(code)
    assert result["valid"] is False
    assert "subprocess" in result["error"]


def test_eval_banned():
    code = _skill_with_header("", "eval('1+1')")
    result = validate_skill_code(code)
    assert result["valid"] is False
    assert "eval" in result["error"]


# ── New network-module bans ────────────────────────────────────────────────────

def test_socket_import_banned():
    code = _skill_with_header("import socket")
    result = validate_skill_code(code)
    assert result["valid"] is False
    assert "socket" in result["error"]


def test_urllib_import_banned():
    code = _skill_with_header("import urllib")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_urllib_request_import_banned():
    code = _skill_with_header("import urllib.request")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_http_import_banned():
    code = _skill_with_header("import http")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_http_client_import_from_banned():
    code = _skill_with_header("from http import client")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_ftplib_banned():
    code = _skill_with_header("import ftplib")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_ssl_banned():
    code = _skill_with_header("import ssl")
    result = validate_skill_code(code)
    assert result["valid"] is False


# ── New os.* call bans ────────────────────────────────────────────────────────

def test_os_remove_banned():
    code = _skill_with_header("import os", "os.remove('/tmp/x')")
    result = validate_skill_code(code)
    assert result["valid"] is False
    assert "os.remove" in result["error"]


def test_os_makedirs_banned():
    code = _skill_with_header("import os", "os.makedirs('/tmp/x')")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_os_rename_banned():
    code = _skill_with_header("import os", "os.rename('/a', '/b')")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_os_listdir_banned():
    code = _skill_with_header("import os", "os.listdir('.')")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_os_execv_banned():
    code = _skill_with_header("import os", "os.execv('/bin/sh', [])")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_os_fork_banned():
    code = _skill_with_header("import os", "os.fork()")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_os_kill_banned():
    code = _skill_with_header("import os", "os.kill(1, 9)")
    result = validate_skill_code(code)
    assert result["valid"] is False


# ── ctypes: from ctypes import must be banned (confirms existing or new fix) ──

def test_import_ctypes_banned():
    code = _skill_with_header("import ctypes")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_from_ctypes_import_banned():
    # from ctypes import cdll — mod_root == "ctypes" which is in _BANNED_MODULES
    code = _skill_with_header("from ctypes import cdll")
    result = validate_skill_code(code)
    assert result["valid"] is False, (
        "from ctypes import cdll must be blocked — if this fails, the ImportFrom "
        "check needs to be added explicitly"
    )


def test_from_ctypes_util_import_banned():
    code = _skill_with_header("from ctypes.util import find_library")
    result = validate_skill_code(code)
    assert result["valid"] is False


# ── os.environ.get is NOT banned (starter skills use it) ──────────────────────

def test_os_environ_get_allowed():
    code = _skill_with_header(
        "import os",
        'x = os.environ.get("MY_VAR", "")\n    return {"status": "ok", "data": x, "timestamp": "", "message": ""}'
    )
    result = validate_skill_code(code)
    assert result["valid"] is True, f"os.environ.get must be allowed: {result.get('error')}"


def test_os_path_join_allowed():
    code = _skill_with_header(
        "import os",
        'p = os.path.join("/a", "b")\n    return {"status": "ok", "data": p, "timestamp": "", "message": ""}'
    )
    result = validate_skill_code(code)
    assert result["valid"] is True, f"os.path.join must be allowed: {result.get('error')}"


# ── Valid minimal skill still passes ──────────────────────────────────────────

def test_valid_minimal_skill_passes():
    result = validate_skill_code(_VALID_MINIMAL)
    assert result["valid"] is True
    assert result["name"] == "test_skill"
```

### Steps

- [ ] Create `tests/test_skill_validator.py` with the tests above
- [ ] Run `pytest tests/test_skill_validator.py -x -q`
  - Expected: several fail (network module bans and os.* call bans are not yet in the validator)
  - Note which tests fail — these identify the changes needed
- [ ] Apply changes 1–3 to `mcp_server/tools/skills/validator.py`
  - Change 1: extend `_BANNED_MODULES`
  - Change 2: add `_BANNED_OS_CALLS` constant
  - Change 3: update the `os.*` call check to use `_BANNED_OS_CALLS`
  - Change 4: verify the `from ctypes import` test passes without code change; if it fails, add explicit handling
- [ ] Run `python -m py_compile mcp_server/tools/skills/validator.py` — expect: no output
- [ ] Run `pytest tests/test_skill_validator.py -x -q`
  - Expected: **all 20 pass**
- [ ] Verify starter skills still pass validation:
  ```bash
  python -c "
  import sys; sys.path.insert(0, '.')
  from mcp_server.tools.skills.validator import validate_skill_code
  for f in ['mcp_server/tools/skills/modules/proxmox_vm_status.py',
            'mcp_server/tools/skills/modules/fortigate_system_status.py',
            'mcp_server/tools/skills/modules/http_health_check.py']:
      code = open(f).read()
      r = validate_skill_code(code)
      print(f, r.get('valid'), r.get('error', ''))
  "
  ```
  - Expected: all three print `True` with no error

---

## Task 3 — Full test suite pass

- [ ] Run `pytest tests/ -x -q`
  - Expected: **37 pass** (17 original + 6 cancel-flag + 20 validator — minus the 1 pre-existing fail in `test_collectors_proxmox_vms.py` which is excluded by `-x` only if it runs first; if it is last, count will be 36 pass + 1 fail)
  - Actual expected with `-x` stopping on first fail: confirm the only fail is the pre-existing proxmox collector test

---

## Task 4 — Version bump

- [ ] Update `VERSION` file: change `1.10.18` to `1.10.21`
  - (1.10.19 and 1.10.20 reserved for any intervening commits during this session)
- [ ] Run `python -m py_compile api/constants.py` — confirm no error
- [ ] Run `curl -s http://192.168.199.10:8000/api/health | python3 -m json.tool` after deploy to confirm version reported

---

## Commit Sequence

### Commit 1 — Cancel flags hardening
```
fix(agent): harden _cancel_flags with TTL and session_id validation

- Change _cancel_flags value type to (bool, float) to record insertion time
- Add _cleanup_stale_cancel_flags() to prune entries older than 300 s
- Call cleanup at start of _run_single_agent_step, in _stream_agent finally
  block, and in stop_agent before inserting a new flag
- Validate session_id length (≤128 chars) in stop_agent
- Add tests/test_cancel_flags.py (6 tests)

Fixes P1 #6 (unbounded growth) and P2 #38 (phantom flag injection).
```

### Commit 2 — Skill sandbox hardening
```
fix(validator): expand skill sandbox bans for network modules and os calls

- Add socket, urllib, http, ftplib, ssl to _BANNED_MODULES
- Add _BANNED_OS_CALLS frozenset covering filesystem mutation and process
  execution calls (remove, unlink, makedirs, rename, execv, fork, kill, etc.)
- Update the os.* call check to use _BANNED_OS_CALLS instead of a hardcoded
  two-element tuple
- Document that os.environ.get and os.path.* remain allowed (starter skills
  depend on them)
- Add tests/test_skill_validator.py (20 tests)

Fixes P1 #7.
```

### Commit 3 — Version bump
```
chore(release): bump version to 1.10.21
```

---

## Pre-Commit Checklist (each commit)

1. `grep -rE "192\.168\.|password|secret|token" --include="*.py" api/ mcp_server/` — no hardcoded values?
2. `python -m py_compile <changed .py files>` — valid syntax?
3. Skill modules: SKILL_META + execute() present, no newly-banned imports?
4. No `async` added to any function?
5. `pytest tests/ -x -q` — only the pre-existing proxmox collector fail?

---

## Known Constraints

- `proxmox_vm_status.py` and `fortigate_system_status.py` both import `os` at the top level. Banning `os` at the module level is deferred — the call-level ban on dangerous `os.*` operations is the chosen mitigation.
- `from ctypes import cdll` is blocked by the existing `ImportFrom` check because `node.module.split(".")[0] == "ctypes"` which is already in `_BANNED_MODULES`. The new test `test_from_ctypes_import_banned` confirms this without requiring a code change.
- The `http_health_check.py` starter skill uses only `httpx` for HTTP — it does not import `http`, `urllib`, or `ssl`. Banning these modules does not affect it.
