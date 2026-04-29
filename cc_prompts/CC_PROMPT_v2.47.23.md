# CC PROMPT — v2.47.23 — fix(db): ThreadedConnectionPool + maxconn=20 + connect_timeout in postgres_backend

## What this does

Fixes "connection pool exhausted" errors visible to operators when saving
settings or under any moderate concurrent load. Three changes to
`mcp_server/tools/skills/storage/postgres_backend.py`:

1. **`SimpleConnectionPool` → `ThreadedConnectionPool`.** SimpleConnectionPool
   is documented as not thread-safe. FastAPI runs sync `def` endpoints in a
   threadpool, so concurrent requests can corrupt the pool's in-use bookkeeping.
   ThreadedConnectionPool adds a `threading.Lock` around getconn/putconn — the
   minimum correct primitive for our use.

2. **`maxconn=5` → `maxconn=20`.** This singleton serves settings I/O, skills
   registry, audit log, checkpoints, breaking changes, and the generation log.
   With ~80 settings keys per save plus several collectors and the agent loop
   sharing one pool, 5 is starvation-bait.

3. **`connect_timeout=5` + pre-ping retry.** Postgres can drop idle conns
   (server-side `idle_in_transaction_session_timeout`, network blips,
   server restarts). A stale conn handed out by the pool produces a confusing
   "connection failed" error mid-request. Wrap `_execute` to detect the stale-
   conn errors (`OperationalError` / `InterfaceError`), discard the conn back
   to the pool with `close=True`, get a fresh one, retry once.

Version bump: 2.47.22 → 2.47.23

---

## Change 1 — `mcp_server/tools/skills/storage/postgres_backend.py`

CC: open the file. Locate the `_get_pool` method (around line 26):

```python
    def _get_pool(self):
        if self._pool is None:
            import psycopg2
            import psycopg2.pool
            import psycopg2.extras
            self._pool = psycopg2.pool.SimpleConnectionPool(
                minconn=1,
                maxconn=5,
                dsn=self.dsn,
                cursor_factory=psycopg2.extras.RealDictCursor,
            )
        return self._pool
```

Replace with:

```python
    def _get_pool(self):
        if self._pool is None:
            import psycopg2
            import psycopg2.pool
            import psycopg2.extras
            # v2.47.23: ThreadedConnectionPool (thread-safe), maxconn=20,
            # connect_timeout=5. SimpleConnectionPool was not thread-safe
            # and maxconn=5 caused "connection pool exhausted" under
            # moderate concurrent load (settings save + collectors +
            # agent loop hitting the same singleton).
            self._pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=2,
                maxconn=20,
                dsn=self.dsn,
                cursor_factory=psycopg2.extras.RealDictCursor,
                connect_timeout=5,
            )
        return self._pool
```

Locate `_execute` (around line 38):

```python
    def _execute(self, sql: str, params: tuple = (), fetch: str = "none"):
        """Execute SQL. fetch: 'none', 'one', 'all'. Returns rows or None."""
        pool = self._get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                if fetch == "one":
                    result = cur.fetchone()
                elif fetch == "all":
                    result = cur.fetchall()
                else:
                    result = None
                conn.commit()
                return result
        except Exception:
            conn.rollback()
            raise
        finally:
            pool.putconn(conn)
```

Replace with:

```python
    def _execute(self, sql: str, params: tuple = (), fetch: str = "none"):
        """Execute SQL. fetch: 'none', 'one', 'all'. Returns rows or None.

        v2.47.23: pre-ping retry. If the conn handed out by the pool is
        stale (server dropped it; usually surfaces as OperationalError or
        InterfaceError on first use), discard it via putconn(close=True)
        so the pool refills, get a fresh one, retry once. Subsequent
        failures bubble up unchanged.
        """
        import psycopg2
        pool = self._get_pool()
        last_err = None
        for attempt in (1, 2):
            conn = pool.getconn()
            released = False
            try:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    if fetch == "one":
                        result = cur.fetchone()
                    elif fetch == "all":
                        result = cur.fetchall()
                    else:
                        result = None
                    conn.commit()
                    return result
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                last_err = e
                try:
                    conn.rollback()
                except Exception:
                    pass
                # Stale conn — discard so pool rebuilds on next getconn
                try:
                    pool.putconn(conn, close=True)
                    released = True
                except Exception:
                    pass
                if attempt == 1:
                    log.warning("Postgres conn was stale, retrying: %s", e)
                    continue
                raise
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise
            finally:
                if not released:
                    try:
                        pool.putconn(conn)
                    except Exception:
                        pass
        if last_err:
            raise last_err
```

## Verify

```bash
# 1. Compile
python -m py_compile mcp_server/tools/skills/storage/postgres_backend.py

# 2. Confirm the new constants are in place
grep -n "ThreadedConnectionPool\|maxconn=20\|connect_timeout=5" \
  mcp_server/tools/skills/storage/postgres_backend.py

# 3. After deploy:
#    - GET /api/health → 200
#    - POST /api/settings (one key change) → 200, no "connection pool exhausted"
curl -s http://localhost:8000/api/health | head -c 200
```

## Version bump

Update `VERSION`: 2.47.22 → 2.47.23

## Commit

```bash
git add -A
git commit -m "fix(db): ThreadedConnectionPool + maxconn=20 + connect_timeout (v2.47.23)

SimpleConnectionPool was not thread-safe and maxconn=5 starved under
concurrent load. Switch to ThreadedConnectionPool, bump pool to 20,
add connect_timeout=5, and wrap _execute with a one-shot pre-ping
retry that detects stale conns via OperationalError/InterfaceError.

Fixes 'connection pool exhausted' visible when saving settings."
git push origin main
```

## Deploy

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
