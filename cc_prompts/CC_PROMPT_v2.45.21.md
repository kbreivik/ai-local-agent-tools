# CC PROMPT — v2.45.21 — fix(security): /metrics auth + CORS_ALLOW_ALL startup warning

## What this does
Two small security gaps from the v2.45.17 audit, bundled because each is
trivial:

1. `/metrics` endpoint is currently unauthenticated. Exposes operational
   intelligence (escalation rates, hallucination guard hits, tool patterns,
   broker counts). Add `Depends(get_current_user)` so only authenticated
   users can read it.

2. `CORS_ALLOW_ALL=true` opens CORS to `*` with no startup warning, unlike
   the admin-password default check. Add a parallel critical-level log line.

Version bump: 2.45.20 → 2.45.21

---

## Change 1 — `api/main.py` — protect /metrics endpoint

Find this block:

```python
@app.get("/metrics")
async def metrics():
    body, ctype = render_metrics()
    return Response(content=body, media_type=ctype)
```

Replace with:

```python
@app.get("/metrics")
async def metrics(_: str = Depends(get_current_user)):
    """Prometheus metrics endpoint (auth-required since v2.45.21).

    Operator scrapers must include the JWT bearer token or auth cookie.
    Returns 401 for unauthenticated requests. This protects operational
    intelligence (escalation frequency, hallucination guard hits, tool
    failure patterns) from anonymous LAN scraping.
    """
    body, ctype = render_metrics()
    return Response(content=body, media_type=ctype)
```

CC: confirm `from api.auth import get_current_user, check_secrets` is already
imported at the top of main.py — it is (line ~19). Confirm `Depends` is in the
fastapi imports — it is. No new imports needed.

---

## Change 2 — `api/main.py` — CORS_ALLOW_ALL critical-log warning

Find this block in the `lifespan` function (the existing critical-secrets
check). Look for `check_secrets()` and the surrounding context:

```python
    # Crypto boot-safety: refuse to start if env key is missing but encrypted data exists
    from api.crypto import check_encryption_key_safe
    check_encryption_key_safe()
    check_secrets()
    await _start_logger()
```

Right AFTER the `check_secrets()` line, insert:

```python
    # v2.45.21 — Loud CORS warning. Mirrors the ADMIN_PASSWORD default check.
    if CORS_ORIGINS_ALL:
        import logging as _logging_cors
        _logging_cors.getLogger(__name__).critical(
            "SECURITY: CORS_ALLOW_ALL=true — every origin is accepted. "
            "Set CORS_ALLOW_ALL=false and use CORS_ORIGINS for specific hosts."
        )
```

---

## Change 3 — Document the auth requirement for Prometheus scrapers

Find the `.env.example` file at the repo root.

Look for the `CORS_ALLOW_ALL` line. Right above it, ensure there is or insert
a comment block explaining the metrics auth (find an existing free spot near
the auth section if one exists, else add at the end before
`CORS_ALLOW_ALL=`):

```
# /metrics is auth-required (v2.45.21). Prometheus scrapers must send the
# JWT bearer token or hp1_auth cookie. Generate a long-lived API token via
# the Users page or POST /api/auth/tokens.
```

CC: if `.env.example` does not contain `CORS_ALLOW_ALL` at all, skip this
change — the comment is informational only.

---

## Verify

```bash
python -m py_compile api/main.py
grep -n "Depends(get_current_user)" api/main.py | grep metrics
grep -n "CORS_ALLOW_ALL=true" api/main.py
```

Expected:
- `metrics(_: str = Depends(get_current_user))` line present
- `critical(.*CORS_ALLOW_ALL=true` line present

---

## Version bump

Update `VERSION`: `2.45.20` → `2.45.21`

---

## Commit

```
git add -A
git commit -m "fix(security): v2.45.21 protect /metrics with auth + warn on CORS_ALLOW_ALL"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

After deploy:
- Anonymous `curl http://192.168.199.10:8000/metrics` should return 401.
- Authenticated `curl -b "hp1_auth=$TOKEN" http://192.168.199.10:8000/metrics`
  should still return the metrics body.
- If `CORS_ALLOW_ALL=true` in .env, container logs should show the CRITICAL
  line at startup.
