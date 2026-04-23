# CC PROMPT — v2.44.9 — fix(tests): pass auth token through test runner — WS URL + HTTP headers

## Root cause

Smoke run score was 31.8% but ALL failures show tools=0, steps=0, duration=0.
The test runner makes unauthenticated requests:

- `websockets.connect(WS_URL)` — no token in query string → WS auth fails → no messages received
- `http.post(f"{API_BASE}/api/agent/run", ...)` — no Authorization header → 401/403 → resp.raise_for_status() throws → timed_out=False, empty messages

Safety tests "pass" trivially because forbid_tools/forbid_sequence checks pass when
no tools are called. Clarification tests pass because soft=True. Real tests all fail.

`_get_test_token()` exists in test_agent.py but is only called in the CLI `__main__`
path — it was never threaded into `run_test()`.

Fix: add `token` parameter to `run_test` and `run_all_tests`, use it for both
the WS URL (`?token=`) and the http client default headers. In `_run_tests_bg`,
acquire a token via the login endpoint before starting the run.

Version bump: 2.44.8 → 2.44.9.

---

## Change 1 — `tests/integration/test_agent.py`

### 1a. `run_test` — add token param, use in WS URL and HTTP headers

Find the function signature (line ~231):
```python
async def run_test(tc: TestCase, http: httpx.AsyncClient) -> TestResult:
```
Replace with:
```python
async def run_test(tc: TestCase, http: httpx.AsyncClient, token: str = "") -> TestResult:
```

Find the WS connect line (~line 261):
```python
        async with websockets.connect(WS_URL, open_timeout=10) as ws:
```
Replace with:
```python
        ws_url = f"{WS_URL}?token={token}" if token else WS_URL
        async with websockets.connect(ws_url, open_timeout=10) as ws:
```

The `http` client already has headers set by the caller — no change needed to
the `http.post` calls since the client passed from `_run_tests_bg` will have
the Authorization header set at construction time.

### 1b. `run_all_tests` — add token param, thread through to run_test

Find the function signature (~line 593):
```python
async def run_all_tests(
    categories: list[str] | None,
    http: httpx.AsyncClient,
    args=None,
) -> list[TestResult]:
```
Replace with:
```python
async def run_all_tests(
    categories: list[str] | None,
    http: httpx.AsyncClient,
    args=None,
    token: str = "",
) -> list[TestResult]:
```

Find the call to run_test inside run_all_tests (~line 639):
```python
        result = await run_test(tc, http)
```
Replace with:
```python
        result = await run_test(tc, http, token=token)
```

---

## Change 2 — `api/routers/tests_api.py`

In `_run_tests_bg`, before the `async with httpx.AsyncClient(...)` block,
acquire a token and configure the client with auth headers:

Find:
```python
        async with httpx.AsyncClient(timeout=30.0) as http:
            results = await run_all_tests(
                categories=categories or None,
                http=http,
                args=None,
            )
```

Replace with:
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

---

## Verification

After deploy, trigger smoke-mem-on-fast again:
```bash
curl -X POST http://192.168.199.10:8000/api/tests/run \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"suite_id": "07db3255-bf03-40fd-a8f8-8b5ddcfca4bd"}'
```

This time tests should show non-zero steps, non-zero duration, and actual
tool calls in results. Score should be meaningfully different from 31.8%.

---

## Version bump

Update `VERSION`: `2.44.8` → `2.44.9`

---

## Commit

```
git add -A
git commit -m "fix(tests): v2.44.9 pass auth token through test runner — WS URL + HTTP headers"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
