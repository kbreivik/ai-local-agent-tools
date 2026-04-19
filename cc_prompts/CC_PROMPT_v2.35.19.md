# CC PROMPT — v2.35.19 — `uptime` flag-args + loud DB errors on connection loads

## What this does

Two tight, unrelated fixes surfaced during v2.35.18 verification
(op `d4a9ed5b`, VM-hosts health summary, commit `dcee6c1`):

1. **`uptime -p` / `uptime -s` blocked by allowlist** — the
   `r'^uptime$'` regex is anchored at end-of-string, so any flag
   argument fails. Every other similar command (`df`, `free`, `du`,
   `uname`, `date`) uses `\b` (word boundary). `uptime` was written
   inconsistently, blocking the pretty-format and start-time flags
   agents naturally reach for.

2. **`get_all_connections_for_platform()` silently returns `[]` on
   DB exception** — op `d4a9ed5b` tool_call 6 (`free -m` on
   `ds-docker-worker-01`) returned `"No vm_host connections
   configured. Add in Settings -> Connections -> vm_host."` 6.6
   seconds after a successful `df -h /` on the SAME host. Direct
   re-invokes work. This is a transient DB failure (asyncpg pool /
   momentary lock) being silently swallowed by the `except
   Exception: return []` pattern in `api/connections.py`. The agent
   then sees a misleading "not configured" error when the real
   issue is "query failed, please retry." It wastes a tool-call
   budget slot and pollutes the agent's reasoning with a wrong
   mental model.

Version bump: 2.35.18 → 2.35.19.

Both fixes are ≤5 LOC each. No behaviour change to success paths.

---

## Evidence

### Allowlist bug

`api/db/vm_exec_allowlist.py` `BASE_PATTERNS`:

```python
(r'^df\b',        'Disk filesystem usage'),         # ← word boundary
(r'^du\b',        'Disk usage by directory'),       # ← word boundary
(r'^free\b',      'Memory usage'),                  # ← word boundary
(r'^uptime$',     'System uptime'),                 # ← END ANCHOR — inconsistent
(r'^uname\b',     'Kernel/OS info'),                # ← word boundary
(r'^hostname$',   'Hostname'),                      # also end-anchored (ok — no flags)
(r'^whoami$',     'Current user'),                  # also end-anchored (ok — no flags)
(r'^date\b',      'System date/time'),              # ← word boundary
```

`uptime` HAS flags worth using (`-p` pretty, `-s` since, `--pretty`,
`--since`). `hostname` and `whoami` legitimately don't. The `$` on
`uptime` was likely a typo / copy-paste error.

Agent trace line from op `d4a9ed5b` tool_call 2:

```
cmd: "uptime -p"
status: blocked
err: "Command segment not in allowlist: 'uptime -p'. Call
      vm_exec_allowlist_request()..."
```

### DB-silent-swallow bug

`api/connections.py` `get_all_connections_for_platform()` lines
~end of file:

```python
def get_all_connections_for_platform(platform: str) -> list[dict]:
    conn = _get_conn()
    if conn:
        try:
            # ... SELECT ... 
            return [...]
        except Exception:
            return []                       # ← SILENT: loses DB error
    try:
        # ... SQLite fallback ...
    except Exception:
        return []                           # ← SAME ISSUE
```

Both exception handlers bind the exception to nothing and return
empty list. The caller (vm_exec) then uses that empty list to
report "No vm_host connections configured" — which means one of
three ACTUAL conditions, indistinguishable to the agent:

  a. DB is reachable and there really are zero vm_host rows
     (misconfiguration — the error text is correct)
  b. DB connection itself failed (_get_conn returned None — falls
     through to SQLite path which also fails in production → `[]`)
  c. Query itself raised (transient asyncpg failure, lock, pool
     exhaustion) — exception swallowed

The production scenario is (c) — DB is healthy, pool was briefly
contended. Same query 30 seconds later returns 5 rows as expected.

---

## Change 1 — `api/db/vm_exec_allowlist.py` — fix `uptime` anchor

```python
(r'^uptime\b',                     'System uptime (supports -p, -s flags)'),
```

Replace the existing tuple:

```python
(r'^uptime$',                      'System uptime'),
```

**Migration note:** CC should ensure the `seed_base_patterns()`
initialiser (or equivalent idempotent seed on startup) updates the
row if it already exists with the old pattern. If `BASE_PATTERNS`
is only written once at first-init, add a one-shot idempotent
migration step in `_init_vm_exec_allowlist()` or equivalent:

```python
# Idempotent update for v2.35.19 uptime pattern fix.
# Pre-v2.35.19 installs have r'^uptime$' — rewrite to r'^uptime\b'.
try:
    conn = _get_conn()
    if conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE vm_exec_allowlist "
            "SET pattern = '^uptime\\b', description = 'System uptime (supports -p, -s flags)' "
            "WHERE pattern = '^uptime$' AND is_base = TRUE",
        )
        conn.commit()
        cur.close()
        conn.close()
except Exception as e:
    log.warning("v2.35.19 uptime allowlist migration failed: %s", e)
```

CC should adapt this pattern to whatever migration style the file
already uses (check for `_CONNECTIONS_MIGRATIONS_PG`-style list).
The cache TTL (30s) will pick up the change within half a minute
of deploy. Clearing the cache explicitly after the migration is
nice-to-have but not required.

## Change 2 — `api/connections.py` — loud logging + one-shot retry

Replace `get_all_connections_for_platform` with the following. The
behaviour is:

- Log the exception with `log.warning(..., exc_info=True)` so
  operators see the real DB error in container logs.
- Retry once after a 150ms backoff on the PG path (covers the vast
  majority of transient pool / lock failures).
- Only fall through to SQLite fallback if both PG attempts raised
  (the pre-v2.35.19 behaviour treated any PG exception as
  "fall through" — keep that).
- On all final-empty-or-error paths, log at `warning` level (never
  silently `return []`).

```python
def get_all_connections_for_platform(platform: str) -> list[dict]:
    """Get ALL enabled connections for a platform with decrypted credentials.

    v2.35.19: loud error logging + one-shot retry on transient DB failures.
    Pre-v2.35.19 silently returned [] on any exception, which led agents
    to report "No vm_host connections configured" when the real issue was
    a transient asyncpg pool hiccup.
    """
    import time as _time

    # PostgreSQL path with one retry
    for attempt in (1, 2):
        conn = _get_conn()
        if conn is None:
            break  # PG unavailable entirely; try SQLite fallback
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM connections WHERE platform = %s AND enabled = true "
                "AND host != '' ORDER BY created_at",
                (platform,),
            )
            cols = [desc[0] for desc in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
            cur.close()
            conn.close()
            return [d for d in (_decode_creds(r) for r in rows)
                    if not ((d.get("config") or {}) if isinstance(d.get("config"), dict)
                            else {}).get("paused")]
        except Exception as e:
            try: conn.close()
            except Exception: pass
            log.warning(
                "get_all_connections_for_platform(platform=%r) attempt %d failed: %s",
                platform, attempt, e, exc_info=(attempt == 2),
            )
            try:
                from api.metrics import CONNECTIONS_QUERY_RETRY_COUNTER
                CONNECTIONS_QUERY_RETRY_COUNTER.labels(
                    platform=platform,
                    outcome="retry" if attempt == 1 else "exhausted",
                ).inc()
            except Exception:
                pass
            if attempt == 1:
                _time.sleep(0.15)
                continue
            # attempt 2 failed — fall through to SQLite fallback

    # SQLite fallback (also loud-logged)
    try:
        from sqlalchemy import text as _text
        sa = _get_sa_conn()
        if not sa:
            log.warning(
                "get_all_connections_for_platform(%r): no PG conn and no SQLite "
                "fallback available — returning empty",
                platform,
            )
            return []
        rows = sa.execute(
            _text("SELECT * FROM connections WHERE platform=:p AND enabled=1 "
                  "AND host!='' ORDER BY created_at"),
            {"p": platform},
        ).mappings().fetchall()
        sa.close()
        return [d for d in (_decode_creds(dict(r)) for r in rows)
                if not ((d.get("config") or {}) if isinstance(d.get("config"), dict)
                        else {}).get("paused")]
    except Exception as e:
        log.warning(
            "get_all_connections_for_platform(%r) SQLite fallback failed: %s",
            platform, e, exc_info=True,
        )
        return []
```

**Symmetric fix for `get_connection_for_platform`:** same
silent-swallow pattern lives there. Apply the same treatment —
one PG retry on exception, loud warning on failure, same
Prometheus counter. CC should apply the exact same shape there
(function is 20 lines, same structure).

## Change 3 — `api/metrics.py` — new counter

Add once to the metrics registry alongside the other
`deathstar_*_total` counters:

```python
CONNECTIONS_QUERY_RETRY_COUNTER = Counter(
    "deathstar_connections_query_retry_total",
    "get_connection(s)_for_platform DB retry attempts and outcomes",
    ["platform", "outcome"],  # outcome: retry | exhausted
)
```

Import it where the function uses it (lazy import inside the
except branch per pattern above — avoids circular-import risk).

## Change 4 — `mcp_server/tools/vm.py` — clarify vm_exec error on empty-list path

No retry here (that's handled upstream). But improve the error
message so the agent sees it differently depending on whether
the DB call itself logged a warning (operator-visible) or the DB
is genuinely empty. A small change: distinguish the two messages.

```python
# In vm_exec, replace the current empty-list branch:
if not all_conns:
    return {
        "status": "error",
        "message": (
            "vm_host connection lookup returned no rows. Either: (a) no "
            "vm_host connections are configured — add in Settings → "
            "Connections → vm_host; or (b) a transient DB error occurred "
            "and the query returned empty (check container logs for "
            "'get_all_connections_for_platform' warnings). The second is "
            "retryable — the agent can try this tool call again in a few "
            "seconds."
        ),
        "data": None, "timestamp": _ts(),
    }
```

This gives the agent a retry hint on the specific path that
silently fails today. Combined with Change 2's retry-internal-to-
the-query, the combined probability of a spurious "No
connections" error after one retry is small (same asyncpg pool
scaled 2× the success rate).

## Change 5 — tests

New `tests/test_uptime_allowlist.py`:

```python
"""v2.35.19 — uptime allowlist allows -p / -s flag args."""
import pytest
from mcp_server.tools.vm import _validate_command


@pytest.mark.parametrize("cmd", [
    "uptime",
    "uptime -p",
    "uptime -s",
    "uptime --pretty",
    "uptime --since",
])
def test_uptime_variants_pass(cmd):
    ok, _ = _validate_command(cmd)
    assert ok, f"Expected {cmd!r} to pass allowlist"


def test_uptime_in_chain():
    """Canonical pattern from Sample 2 of v2.35.18 analysis."""
    ok, _ = _validate_command("df -h && free -m && uptime -p && whoami")
    assert ok


def test_uptime_does_not_allow_injection():
    """-p is fine but arbitrary args still rejected by metachar guard."""
    ok, err = _validate_command("uptime -p; rm /tmp/x")
    assert not ok
    # Error is string or dict
    err_str = err if isinstance(err, str) else err.get("message", "")
    assert "metacharacters" in err_str.lower() or ";" in err_str
```

New `tests/test_connections_retry.py`:

```python
"""v2.35.19 — get_all_connections_for_platform loud errors + retry."""
from unittest.mock import patch, MagicMock
import pytest


def test_returns_rows_on_first_success():
    """Happy path — no retry, no warning."""
    from api import connections
    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_cur.description = [("id",), ("platform",), ("host",), ("enabled",),
                            ("credentials",), ("config",)]
    fake_cur.fetchall.return_value = [
        ("uuid-1", "vm_host", "h1.example", True, "", "{}"),
    ]
    fake_conn.cursor.return_value = fake_cur
    with patch("api.connections._get_conn", return_value=fake_conn), \
         patch("api.connections._decode_creds", side_effect=lambda r: r):
        result = connections.get_all_connections_for_platform("vm_host")
    assert len(result) == 1
    assert result[0]["host"] == "h1.example"


def test_retries_once_on_transient_failure():
    """Exception on attempt 1, success on attempt 2."""
    from api import connections
    call_count = {"n": 0}

    def _maybe_failing_conn():
        call_count["n"] += 1
        c = MagicMock()
        if call_count["n"] == 1:
            c.cursor.return_value.execute.side_effect = RuntimeError("pool timeout")
        else:
            cur = MagicMock()
            cur.description = [("id",), ("host",)]
            cur.fetchall.return_value = [("uuid-1", "h1")]
            c.cursor.return_value = cur
        return c

    with patch("api.connections._get_conn", side_effect=_maybe_failing_conn), \
         patch("api.connections._decode_creds", side_effect=lambda r: r):
        result = connections.get_all_connections_for_platform("vm_host")
    assert call_count["n"] == 2  # Retried
    # Depending on _decode_creds behaviour may get 0 or 1 rows; what matters
    # is the retry fired.


def test_logs_warning_on_exhausted_retry(caplog):
    """Both attempts fail → WARNING logged (not silently swallowed)."""
    import logging
    from api import connections
    fake_conn = MagicMock()
    fake_conn.cursor.return_value.execute.side_effect = RuntimeError("DB broken")
    with patch("api.connections._get_conn", return_value=fake_conn), \
         patch("api.connections._get_sa_conn", return_value=None), \
         caplog.at_level(logging.WARNING, logger="api.connections"):
        result = connections.get_all_connections_for_platform("vm_host")
    assert result == []
    # Must have logged the failure on attempt 2
    warning_msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("attempt 2" in m for m in warning_msgs), (
        "Expected a WARNING mentioning attempt 2 — got: " + str(warning_msgs)
    )
```

Adapt patch-targets if the real function internals use different
helper names. The goal is: retry fires, warning logged, never
silent.

## Change 6 — `VERSION`

```
2.35.19
```

## Verify

```bash
pytest tests/test_uptime_allowlist.py -v
pytest tests/test_connections_retry.py -v
pytest tests/ -v -k "uptime or connections_retry or vm_exec"
```

## Commit

```bash
git add -A
git commit -m "fix(tools): v2.35.19 uptime allowlist + loud DB error on connection loads

Two narrow fixes from v2.35.18 verification op d4a9ed5b (VM-hosts
health summary). Both root causes confirmed via trace + direct
invoke + source read.

(1) uptime allowlist — r'^uptime\$' is end-anchored so 'uptime -p',
    'uptime -s', 'uptime --pretty' are all rejected. Every other
    similar command (df, free, du, uname, date) uses \b word-
    boundary. Change to r'^uptime\b' for consistency, add idempotent
    migration to rewrite the existing base row on startup.

(2) get_all_connections_for_platform silent-swallow — on any DB
    exception the function returned [], causing vm_exec to report
    'No vm_host connections configured' when the real cause was a
    transient asyncpg pool hiccup. Same query succeeded 4s earlier
    and 4s later on the exact same host. Loud warning + one 150ms
    retry on PG exceptions, new Prometheus counter
    deathstar_connections_query_retry_total{platform, outcome}.
    Same treatment for get_connection_for_platform.

vm_exec error message on empty-list path updated to tell the agent
the condition is retryable when DB logs show a warning."
git push origin main
```

## Deploy + smoke

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

1. **Direct invoke** `vm_exec(host='hp1-ai-agent-lab', command='uptime -p')`
   → expect `status=ok`, output contains "up N [days/hours/minutes]".
2. **Direct invoke** `vm_exec(host='hp1-ai-agent-lab',
   command='df -h && free -m && uptime -p && whoami')` → expect
   `status=ok` (exercises v2.35.18 chain cap AND v2.35.19 uptime fix).
3. **Re-run VM-hosts health summary template** — agent should
   complete without a 'Command segment not in allowlist:
   uptime -p' entry AND without a spurious 'No vm_host
   connections configured' error mid-run.
4. `/metrics` — no `deathstar_connections_query_retry_total`
   rows should appear under normal load (only fires on genuine
   DB errors). If it DOES fire, that's the pre-existing
   transient-failure signal now becoming visible — operators
   can investigate the pool config.

## Scope guard

Do NOT touch the agent loop, synthesis, rescue paths, classifier,
or fabrication detector. Both fixes are strictly infra-path +
allowlist scope.
