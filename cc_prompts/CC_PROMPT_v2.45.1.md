# CC PROMPT — v2.45.1 — fix(tests): generate fresh internal JWT for test runner instead of stale localStorage token

## Root cause

`localStorage.getItem('hp1_auth_token')` is a stale JWT from before v2.30.1
switched to httpOnly cookies. REST calls succeed because the browser also sends
the valid `hp1_auth` cookie with `credentials: 'include'`. But the WebSocket
uses only `?token=<caller_token>` — no cookie — and the stale JWT is rejected
with close code 1008 (policy violation).

`api/auth.py` already has `create_internal_token(expires_minutes=5)` which
generates a fresh sith_lord JWT using the same SECRET_KEY. Use this instead
of the caller's potentially stale token. Extend lifetime to cover the full
test run (60 minutes).

Version bump: 2.45.0 → 2.45.1.

---

## Change — `api/routers/tests_api.py`

In `_run_tests_bg`, find the block:
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

Replace with:
```python
        # Generate a fresh internal JWT — the caller's token may be stale
        # (localStorage token from before v2.30.1 httpOnly cookie switch).
        # The WS connection uses ?token= (no cookie), so must be a valid JWT.
        from api.auth import create_internal_token
        _fresh_token = create_internal_token(expires_minutes=90)
        _auth_headers = {"Authorization": f"Bearer {_fresh_token}"} if _fresh_token else {}
        async with httpx.AsyncClient(timeout=30.0, headers=_auth_headers) as http:
            results = await run_all_tests(
                categories=categories or None,
                http=http,
                args=None,
                token=_fresh_token,
            )
```

---

## Verification

After deploy, trigger smoke-mem-on-fast. Within 30 seconds, check:
```javascript
fetch('/api/logs/operations?limit=5', {headers:{Authorization:`Bearer ${localStorage.hp1_auth_token}`}})
  .then(r=>r.json()).then(d=>d.operations?.map(o=>o.started_at?.slice(11,19)+' '+o.status+' '+o.task?.slice(0,30)))
```
Should show NEW operations appearing with status `running` from the current time.
Score should be non-trivially different from 31.8%.

---

## Version bump

Update `VERSION`: `2.45.0` → `2.45.1`

---

## Commit

```
git add -A
git commit -m "fix(tests): v2.45.1 use create_internal_token for test runner — replaces stale localStorage JWT"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
