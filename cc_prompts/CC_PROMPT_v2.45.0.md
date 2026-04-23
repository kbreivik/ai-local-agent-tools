# CC PROMPT — v2.45.0 — fix(tests): use caller's JWT token in test runner — no re-login needed

## Root cause

`_get_test_token()` tries to login with `username=admin, password=superduperadmin`
which returns "Invalid credentials" — the password is wrong. So `_test_token = ""`
and all agent/run calls get 401.

The correct fix: the `/api/tests/run` endpoint is called by an authenticated user.
Extract their Bearer token from the `Authorization` request header and pass it
directly to `_run_tests_bg`. No re-authentication needed.

Version bump: 2.44.9 → 2.45.0.

---

## Change — `api/routers/tests_api.py`

### Step 1: add `Request` import

Add `Request` to the fastapi import line:
```python
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
```

### Step 2: update `run_tests` endpoint to extract and pass caller token

Replace:
```python
@router.post("/run")
async def run_tests(
    body: RunTestsRequest,
    background_tasks: BackgroundTasks,
    _: str = Depends(get_current_user),
):
    global _running
    if _running:
        return {"status": "already_running",
                "message": "A test run is already in progress."}
    background_tasks.add_task(
        _run_tests_bg,
        categories=body.categories,
        test_ids=body.test_ids,
        suite_id=body.suite_id,
        memory_enabled=body.memory_enabled,
        suite_name="",
    )
    return {"status": "started",
            "message": f"Test run started (suite={body.suite_id}, categories={body.categories}, ids={len(body.test_ids or [])} tests)"}
```

With:
```python
@router.post("/run")
async def run_tests(
    request: Request,
    body: RunTestsRequest,
    background_tasks: BackgroundTasks,
    _: str = Depends(get_current_user),
):
    global _running
    if _running:
        return {"status": "already_running",
                "message": "A test run is already in progress."}

    # Extract the caller's Bearer token — pass it to the test runner so it can
    # make authenticated requests to /api/agent/run and the WebSocket.
    auth_header = request.headers.get("Authorization", "")
    caller_token = auth_header.removeprefix("Bearer ").strip()

    background_tasks.add_task(
        _run_tests_bg,
        categories=body.categories,
        test_ids=body.test_ids,
        suite_id=body.suite_id,
        memory_enabled=body.memory_enabled,
        suite_name="",
        caller_token=caller_token,
    )
    return {"status": "started",
            "message": f"Test run started (suite={body.suite_id}, categories={body.categories}, ids={len(body.test_ids or [])} tests)"}
```

### Step 3: update `_run_tests_bg` to accept and use caller_token

Add `caller_token: str = ""` parameter to `_run_tests_bg` signature:
```python
async def _run_tests_bg(
    categories: list[str] | None,
    test_ids: list[str] | None = None,
    suite_id: str | None = None,
    memory_enabled: bool | None = None,
    memory_backend: str | None = None,
    suite_name: str = "",
    caller_token: str = "",        # ← add this
) -> None:
```

Then replace the entire token acquisition block:
```python
        # Acquire a JWT token for the test runner
        _test_token = ""
        try:
            import httpx as _hx
            import os as _os
            _pw = _os.environ.get("ADMIN_PASSWORD", "superduperadmin")
            _lr = _hx.post(
                "http://localhost:8000/api/auth/login",
                json={"username": "admin", "password": _pw},
                timeout=5,
            )
            if _lr.status_code == 200:
                _test_token = _lr.json().get("access_token", "")
        except Exception as _te:
            import logging
            logging.getLogger(__name__).warning("test runner: token acquisition failed: %s", _te)

        _auth_headers = {"Authorization": f"Bearer {_test_token}"} if _test_token else {}
        async with httpx.AsyncClient(timeout=30.0, headers=_auth_headers) as http:
            results = await run_all_tests(
                categories=categories or None,
                http=http,
                args=None,
                token=_test_token,
            )
```

With:
```python
        # Use the caller's token directly — no re-login needed.
        _auth_headers = {"Authorization": f"Bearer {caller_token}"} if caller_token else {}
        async with httpx.AsyncClient(timeout=30.0, headers=_auth_headers) as http:
            results = await run_all_tests(
                categories=categories or None,
                http=http,
                args=None,
                token=caller_token,
            )
```

---

## Verification

After deploy, trigger smoke-mem-on-fast, wait for completion, then check:
```
GET /api/tests/results
```
Expect: results with non-zero `step_count`, non-zero `duration_s`, and actual
`tools_called` arrays. Score should be meaningfully different from 31.8%.

---

## Version bump

Update `VERSION`: `2.44.9` → `2.45.0`

---

## Commit

```
git add -A
git commit -m "fix(tests): v2.45.0 use caller JWT token in test runner — no re-login"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
