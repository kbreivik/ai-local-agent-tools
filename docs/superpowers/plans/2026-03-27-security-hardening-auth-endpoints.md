# Security Hardening — Auth & Endpoint Protection

**Date:** 2026-03-27
**Version target:** 1.10.19
**Branch:** main

---

## Goal

Close authentication gaps and reduce attack surface on the HP1-AI-Agent API. Seven discrete tasks covering insecure default detection, CORS tightening, missing auth guards on agent/skill endpoints, login rate limiting, input length validation, and a WebSocket URL protocol fix.

## Architecture

- FastAPI backend (Python 3.13) — `api/` tree
- Vue 3 GUI — `gui/src/`
- All tool functions are sync; FastAPI route handlers may be async
- Single admin user via bcrypt + JWT (HS256, 24 h expiry)
- Auth dependency: `get_current_user` in `api/auth.py`
- Test suite: `pytest tests/ -x -q` from project root
  - 17 tests currently pass; 1 pre-existing fail in `test_collectors_proxmox_vms.py` — expected throughout

## Tech Stack

- Python stdlib `time` / `collections.defaultdict` for rate limiter — no third-party library
- `pydantic.Field` for input length constraints — already a dependency
- `fastapi.Request` for IP extraction — already a dependency
- `logging` (stdlib) for secret-warning output

## File Map

| File | Changes |
|------|---------|
| `api/auth.py` | Add `check_secrets()` function |
| `api/main.py` | Call `check_secrets()` in lifespan; change CORS default to `"false"` |
| `api/routers/agent.py` | Add `Depends(get_current_user)` to `/stop` and `/clarify`; add `Field` constraints to `RunRequest` |
| `api/routers/skills.py` | Add `Depends(get_current_user)` to `list_skills`, `get_skill`, `execute_skill` |
| `api/routers/auth.py` | Add `request: Request` param and per-IP rate limiter to `login` |
| `gui/src/context/AgentOutputContext.jsx` | Fix WebSocket URL to use correct protocol and host |
| `tests/test_auth_guards.py` | New file — auth guard tests for agent and skill endpoints |
| `tests/test_auth_rate_limit.py` | New file — login rate limit test |

---

## Tasks

### Task 1 — Insecure-default secret warnings

**Files:** `api/auth.py`, `api/main.py`

**Context:**
- `api/auth.py` line 12: `SECRET_KEY = os.environ.get("JWT_SECRET", "hp1-jwt-secret-change-in-prod-2026")`
- `api/auth.py` line 17: `_ADMIN_PASS = os.environ.get("ADMIN_PASSWORD", "superduperadmin")`
- `api/main.py` lines 68–107: `lifespan` async context manager — call site for `check_secrets()`

**Steps:**

- [ ] **1.1** Open `api/auth.py`. After the config block (line 20, after `_STORED_HASH` assignment), add:

  ```python
  import logging as _log_module
  _auth_log = _log_module.getLogger(__name__)

  _INSECURE_JWT_DEFAULT = "hp1-jwt-secret-change-in-prod-2026"
  _INSECURE_PASS_DEFAULT = "superduperadmin"


  def check_secrets() -> None:
      """Log CRITICAL warnings when known insecure defaults are in use.

      Called from the app lifespan — never at module import time.
      Does NOT raise; homelab may intentionally use defaults on a trusted LAN.
      """
      if SECRET_KEY == _INSECURE_JWT_DEFAULT:
          _auth_log.critical(
              "SECURITY: JWT_SECRET is set to the insecure default value. "
              "Set JWT_SECRET env var to a strong random secret before exposing this service."
          )
      if _ADMIN_PASS == _INSECURE_PASS_DEFAULT:
          _auth_log.critical(
              "SECURITY: ADMIN_PASSWORD is set to the insecure default 'superduperadmin'. "
              "Set ADMIN_PASSWORD env var to a strong password before exposing this service."
          )
  ```

- [ ] **1.2** Open `api/main.py`. Add `check_secrets` to the existing `api.auth` import line (line 19):

  ```python
  from api.auth import get_current_user, check_secrets
  ```

- [ ] **1.3** In `api/main.py`, inside the `lifespan` function, call `check_secrets()` immediately after `await init_db()` (before the logger start). The lifespan body already starts at line 70:

  ```python
  async with lifespan(app):
      await init_db()
      check_secrets()          # <-- insert here
      await _start_logger()
      ...
  ```

  Place it after `await init_db()` on its own line.

- [ ] **1.4** Verify syntax:
  ```bash
  python -m py_compile api/auth.py api/main.py
  ```

- [ ] **1.5** Run tests — expect same pass/fail as baseline:
  ```bash
  pytest tests/ -x -q
  ```

- [ ] **1.6** Commit:
  ```
  fix(auth): add check_secrets() to warn on insecure default JWT and admin password
  ```

---

### Task 2 — CORS default hardening

**Files:** `api/main.py`

**Context:**
- Line 64: comment says `# Allow all origins in dev — tighten in production`
- Line 65: `CORS_ORIGINS_ALL = os.environ.get("CORS_ALLOW_ALL", "true").lower() == "true"`
- The default `"true"` means wildcard CORS is active unless explicitly disabled

**Steps:**

- [ ] **2.1** Open `api/main.py`. Change line 64–65 from:

  ```python
  # Allow all origins in dev — tighten in production
  CORS_ORIGINS_ALL = os.environ.get("CORS_ALLOW_ALL", "true").lower() == "true"
  ```

  To:

  ```python
  # CORS_ALLOW_ALL=true enables wildcard origins (dev convenience). Default is false (restrictive).
  CORS_ORIGINS_ALL = os.environ.get("CORS_ALLOW_ALL", "false").lower() == "true"
  ```

- [ ] **2.2** Verify syntax:
  ```bash
  python -m py_compile api/main.py
  ```

- [ ] **2.3** Run tests:
  ```bash
  pytest tests/ -x -q
  ```

- [ ] **2.4** Commit:
  ```
  fix(cors): change CORS_ALLOW_ALL default from true to false
  ```

---

### Task 3 — Auth on `/stop` and `/clarify`

**Files:** `api/routers/agent.py`

**Context:**
- `get_current_user` is already imported at line 18: `from api.auth import get_current_user`
- `clarify_agent` is at line 865–872 — no auth dependency
- `stop_agent` is at line 879–894 — no auth dependency
- `/confirm` at line 853 already has `user: str = Depends(get_current_user)` — follow the same pattern

**Steps:**

- [ ] **3.1** Open `api/routers/agent.py`. Add auth to `clarify_agent` (line 865). Change:

  ```python
  @router.post("/clarify")
  async def clarify_agent(req: ClarifyRequest):
  ```

  To:

  ```python
  @router.post("/clarify")
  async def clarify_agent(req: ClarifyRequest, _: str = Depends(get_current_user)):
  ```

- [ ] **3.2** Add auth to `stop_agent` (line 879). Change:

  ```python
  @router.post("/stop")
  async def stop_agent(req: StopRequest):
  ```

  To:

  ```python
  @router.post("/stop")
  async def stop_agent(req: StopRequest, _: str = Depends(get_current_user)):
  ```

- [ ] **3.3** Verify syntax:
  ```bash
  python -m py_compile api/routers/agent.py
  ```

- [ ] **3.4** Run tests:
  ```bash
  pytest tests/ -x -q
  ```

- [ ] **3.5** Commit:
  ```
  fix(agent): require auth on /stop and /clarify endpoints
  ```

---

### Task 4 — Auth on skill read and execute endpoints

**Files:** `api/routers/skills.py`

**Context:**
- `get_current_user` is already imported at line 6: `from api.auth import get_current_user`
- `list_skills` (line 19), `execute_skill` (line 38), `get_skill` (line 55) — none have auth
- All lifecycle endpoints (`promote`, `demote`, `scrap`, `restore`, `regenerate`, `purge`) already use `Depends(get_current_user)`
- `list_skills` and `get_skill` use `def` (sync); `execute_skill` uses `def` (sync) — keep them sync

**Steps:**

- [ ] **4.1** Open `api/routers/skills.py`. Add auth to `list_skills` (line 19). Change:

  ```python
  @router.get("")
  def list_skills(
      category: str = Query("", description="Filter by category"),
      include_disabled: bool = Query(False),
  ):
  ```

  To:

  ```python
  @router.get("")
  def list_skills(
      category: str = Query("", description="Filter by category"),
      include_disabled: bool = Query(False),
      _: str = Depends(get_current_user),
  ):
  ```

- [ ] **4.2** Add auth to `execute_skill` (line 38). Change:

  ```python
  @router.post("/{skill_name}/execute")
  def execute_skill(skill_name: str, params: dict = {}):
  ```

  To:

  ```python
  @router.post("/{skill_name}/execute")
  def execute_skill(skill_name: str, params: dict = {}, _: str = Depends(get_current_user)):
  ```

- [ ] **4.3** Add auth to `get_skill` (line 55). Change:

  ```python
  @router.get("/{skill_name}")
  def get_skill(skill_name: str):
  ```

  To:

  ```python
  @router.get("/{skill_name}")
  def get_skill(skill_name: str, _: str = Depends(get_current_user)):
  ```

- [ ] **4.4** Verify syntax:
  ```bash
  python -m py_compile api/routers/skills.py
  ```

- [ ] **4.5** Run tests. Note: `test_skills_router.py` already calls with `auth_headers()` for all endpoints, so existing tests should continue passing:
  ```bash
  pytest tests/ -x -q
  ```

- [ ] **4.6** Commit:
  ```
  fix(skills): require auth on list, get, and execute endpoints
  ```

---

### Task 5 — Login rate limiter

**Files:** `api/routers/auth.py`

**Context:**
- `login` function at line 21 — no rate limiting
- No `slowapi` or rate-limit library in requirements.txt
- Must use stdlib only: `time`, `collections.defaultdict`
- FastAPI's `Request` object is already available as `fastapi.Request`

**Implementation details:**
- Keyed by IP from `request.client.host` (falls back to `"unknown"` if `request.client` is None — possible in test client)
- Window: 10 attempts per 60 seconds
- On exceed: raise `HTTPException(429, "Too many login attempts. Try again later.")`
- State is module-level dict; resets on container restart (acceptable for homelab)

**Steps:**

- [ ] **5.1** Open `api/routers/auth.py`. Add imports at the top of the file after the existing imports:

  ```python
  import time
  from collections import defaultdict
  from fastapi import APIRouter, HTTPException, Depends, Request
  ```

  Note: `Request` is the only addition to the existing FastAPI import. The current import line is:
  ```python
  from fastapi import APIRouter, HTTPException, Depends
  ```
  Change it to:
  ```python
  from fastapi import APIRouter, HTTPException, Depends, Request
  ```
  And add after the imports block:
  ```python
  import time
  from collections import defaultdict
  ```

- [ ] **5.2** Add the rate limiter state and constants after the imports, before the `router` definition:

  ```python
  _login_attempts: dict[str, list[float]] = defaultdict(list)
  _RATE_LIMIT = 10        # max attempts per window
  _RATE_WINDOW = 60.0     # seconds
  ```

- [ ] **5.3** Update the `login` function signature to accept `request: Request`:

  Change:
  ```python
  @router.post("/login", response_model=LoginResponse)
  async def login(req: LoginRequest):
      user = authenticate(req.username, req.password)
  ```

  To:
  ```python
  @router.post("/login", response_model=LoginResponse)
  async def login(req: LoginRequest, request: Request):
      ip = request.client.host if request.client else "unknown"
      now = time.time()
      # Remove timestamps outside the current window
      _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < _RATE_WINDOW]
      if len(_login_attempts[ip]) >= _RATE_LIMIT:
          raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")
      _login_attempts[ip].append(now)
      user = authenticate(req.username, req.password)
  ```

- [ ] **5.4** Verify syntax:
  ```bash
  python -m py_compile api/routers/auth.py
  ```

- [ ] **5.5** Run tests:
  ```bash
  pytest tests/ -x -q
  ```

- [ ] **5.6** Commit:
  ```
  fix(auth): add per-IP login rate limiter (10 attempts / 60 s, stdlib only)
  ```

---

### Task 6 — Input length validation on `RunRequest`

**Files:** `api/routers/agent.py`

**Context:**
- `RunRequest` at line 117:
  ```python
  class RunRequest(BaseModel):
      task: str = "Perform a full infrastructure health check and report status."
      session_id: str = ""
  ```
- `pydantic.Field` is available — add it to the pydantic import

**Steps:**

- [ ] **6.1** Open `api/routers/agent.py`. The existing pydantic import is at line 15:

  ```python
  from pydantic import BaseModel
  ```

  Change to:

  ```python
  from pydantic import BaseModel, Field
  ```

- [ ] **6.2** Update `RunRequest` (line 117):

  Change:
  ```python
  class RunRequest(BaseModel):
      task: str = "Perform a full infrastructure health check and report status."
      session_id: str = ""
  ```

  To:
  ```python
  class RunRequest(BaseModel):
      task: str = Field(
          default="Perform a full infrastructure health check and report status.",
          max_length=4096,
      )
      session_id: str = Field(default="", max_length=128)
  ```

- [ ] **6.3** Verify syntax:
  ```bash
  python -m py_compile api/routers/agent.py
  ```

- [ ] **6.4** Run tests:
  ```bash
  pytest tests/ -x -q
  ```

- [ ] **6.5** Commit:
  ```
  fix(agent): add max_length validation to RunRequest task and session_id fields
  ```

---

### Task 7 — WebSocket URL protocol fix

**Files:** `gui/src/context/AgentOutputContext.jsx`

**Context:**
- Line 123:
  ```js
  const url = `ws://${location.hostname}:8000/ws/output${token ? `?token=${token}` : ''}`
  ```
- Problems:
  1. Hardcoded `:8000` port — breaks when running behind a reverse proxy on port 443
  2. Hardcoded `ws://` — breaks under HTTPS (must use `wss://`)
  3. `location.hostname` omits port — `location.host` includes it when non-standard

**Steps:**

- [ ] **7.1** Open `gui/src/context/AgentOutputContext.jsx`. Find line 123 and replace:

  ```js
  const url = `ws://${location.hostname}:8000/ws/output${token ? `?token=${token}` : ''}`
  ```

  With:

  ```js
  const wsProto = location.protocol === 'https:' ? 'wss' : 'ws'
  const url = `${wsProto}://${location.host}/ws/output${token ? `?token=${token}` : ''}`
  ```

- [ ] **7.2** Verify no other hardcoded `ws://` + `:8000` patterns remain in the GUI:
  ```bash
  grep -rn "ws://.*:8000" gui/src/
  ```
  Expected: no output.

- [ ] **7.3** Run tests (backend only — GUI has no automated tests):
  ```bash
  pytest tests/ -x -q
  ```

- [ ] **7.4** Commit:
  ```
  fix(gui): derive WebSocket protocol and host from window.location
  ```

---

### Task 8 — New auth-guard tests

**Files:** `tests/test_auth_guards.py` (new), `tests/test_auth_rate_limit.py` (new)

**Context:**
- Test pattern used throughout project: `auth_headers()` helper, `TestClient(app)`, `pytest.skip` if auth unavailable
- Default credentials: `admin` / `superduperadmin`
- The rate limiter state (`_login_attempts`) is module-level — reset between test runs automatically
- The rate limit test must send 11 requests; the 11th should return 429

**Steps:**

- [ ] **8.1** Create `tests/test_auth_guards.py` with the following content:

  ```python
  """Tests that protected endpoints reject unauthenticated requests."""
  import pytest
  from fastapi.testclient import TestClient
  from api.main import app

  client = TestClient(app)


  def auth_headers():
      r = client.post("/api/auth/login", json={"username": "admin", "password": "superduperadmin"})
      if r.status_code != 200:
          pytest.skip("Auth not available in test env")
      return {"Authorization": f"Bearer {r.json()['access_token']}"}


  # ── Agent endpoints ───────────────────────────────────────────────────────────

  def test_stop_requires_auth():
      """POST /api/agent/stop without token returns 401 or 403."""
      r = client.post("/api/agent/stop", json={"session_id": "test-session"})
      assert r.status_code in (401, 403)


  def test_clarify_requires_auth():
      """POST /api/agent/clarify without token returns 401 or 403."""
      r = client.post("/api/agent/clarify", json={"session_id": "test-session", "answer": "yes"})
      assert r.status_code in (401, 403)


  # ── Skill endpoints ───────────────────────────────────────────────────────────

  def test_list_skills_requires_auth():
      """GET /api/skills without token returns 401 or 403."""
      r = client.get("/api/skills")
      assert r.status_code in (401, 403)


  def test_execute_skill_requires_auth():
      """POST /api/skills/x/execute without token returns 401 or 403."""
      r = client.post("/api/skills/http_health_check/execute", json={})
      assert r.status_code in (401, 403)


  def test_get_skill_requires_auth():
      """GET /api/skills/x without token returns 401 or 403."""
      r = client.get("/api/skills/http_health_check")
      assert r.status_code in (401, 403)
  ```

- [ ] **8.2** Create `tests/test_auth_rate_limit.py` with the following content:

  ```python
  """Tests for login rate limiting."""
  import pytest
  from fastapi.testclient import TestClient
  from api.main import app
  import api.routers.auth as auth_router_module

  client = TestClient(app)


  def test_login_rate_limit():
      """Sending 11 login attempts from the same IP triggers 429 on the 11th."""
      # Clear any state from previous test runs
      auth_router_module._login_attempts.clear()

      payload = {"username": "admin", "password": "wrong-password"}
      last_status = None
      for i in range(11):
          r = client.post("/api/auth/login", json=payload)
          last_status = r.status_code

      assert last_status == 429, (
          f"Expected 429 on 11th attempt, got {last_status}"
      )
  ```

- [ ] **8.3** Run the new test files in isolation to verify they pass (auth guards must be in place from Tasks 3 and 4):
  ```bash
  pytest tests/test_auth_guards.py tests/test_auth_rate_limit.py -v
  ```
  Expected: all 6 tests pass.

- [ ] **8.4** Run full suite:
  ```bash
  pytest tests/ -x -q
  ```
  Expected: pre-existing proxmox collector failure only; all other tests pass.

- [ ] **8.5** Commit:
  ```
  test(auth): add auth guard tests for agent/skill endpoints and login rate limit
  ```

---

### Task 9 — Version bump

**Files:** `VERSION`

**Steps:**

- [ ] **9.1** Update `VERSION` from `1.10.18` to `1.10.19`.

- [ ] **9.2** Run full test suite one final time:
  ```bash
  pytest tests/ -x -q
  ```

- [ ] **9.3** Run pre-commit checklist:
  ```bash
  grep -rE "192\.168\.|password|secret|token" --include="*.py" api/ mcp_server/ tests/
  ```
  Review output — confirm no new hardcoded secrets introduced. Existing occurrences (e.g., env var names, test credential strings) are expected and acceptable.

  ```bash
  python -m py_compile api/auth.py api/main.py api/routers/agent.py api/routers/skills.py api/routers/auth.py
  ```

- [ ] **9.4** Commit and push:
  ```
  chore(release): bump version to 1.10.19
  ```
  ```bash
  git push
  ```

---

## Verification Summary

After all tasks are complete, these conditions must hold:

| Condition | How to verify |
|-----------|--------------|
| CRITICAL log on insecure defaults | Start app with default env — check logs for CRITICAL lines |
| CORS defaults to restrictive | `CORS_ALLOW_ALL` unset → `CORSMiddleware` uses `CORS_ORIGINS` list, not `["*"]` |
| `/stop` and `/clarify` need auth | `test_stop_requires_auth`, `test_clarify_requires_auth` — both pass |
| `/api/skills` read endpoints need auth | `test_list_skills_requires_auth`, `test_get_skill_requires_auth`, `test_execute_skill_requires_auth` — all pass |
| Login rate limit active | `test_login_rate_limit` — 11th request returns 429 |
| `RunRequest.task` capped at 4096 chars | `task` field uses `Field(max_length=4096)` |
| WebSocket uses correct protocol | `ws://` on HTTP, `wss://` on HTTPS; uses `location.host` not hardcoded `:8000` |
| Full test suite | `pytest tests/ -x -q` — 1 pre-existing fail only |

---

## Notes and Cautions

- **Test credential clearing**: The rate limiter test clears `_login_attempts` at the start — this is safe because `TestClient` runs in-process and shares module state. Do not remove the `clear()` call or the test will be order-dependent.
- **`execute_skill` mutable default**: `params: dict = {}` is a pre-existing issue (mutable default argument). Do not fix it as part of this plan — it is out of scope and the existing tests depend on the current signature.
- **CORS list includes RFC-invalid entry**: `"http://192.168.0.0/16"` in `CORS_ORIGINS` is not a valid origin (CIDR notation is not supported by the CORS spec). This is a pre-existing issue — do not fix it as part of this plan.
- **`check_secrets()` timing**: Must be called from `lifespan`, not at module import time. If called at import time the function would run before environment variables are loaded from `.env` in some deployment configurations.
- **Rate limiter IP in TestClient**: `request.client` may be `None` or `testclient` in FastAPI's TestClient. The `request.client.host if request.client else "unknown"` guard handles this — all test requests share the `"testclient"` IP bucket, which is intentional for the rate limit test.
