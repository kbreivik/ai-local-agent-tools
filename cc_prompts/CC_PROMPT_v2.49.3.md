# CC PROMPT — v2.49.3 — fix(infra): split BACKEND_DATABASE_URL + pin LISTEN_PORT=6432

## What this does

Fixes three deviations between v2.49.1's spec and observed runtime
behaviour after first deploy on agent-01:

1. **Username parsing failure.** The edoburu entrypoint's URL parser
   chokes on the `+asyncpg` driver suffix in `DATABASE_URL`, truncating
   `hp1user` to `hp1` when generating `userlist.txt` and the
   `[databases]` block. Result: pgbouncer tries to authenticate
   upstream to Postgres as `hp1`, which doesn't exist.

2. **`LISTEN_PORT` not pinned.** Image default 5432 was used, so the
   socket landed at `.s.PGSQL.5432` instead of `.s.PGSQL.6432` as
   documented. The healthcheck (which checks for `.s.PGSQL.6432`)
   would have failed permanently.

3. **`LISTEN_ADDR=""` did not disable the TCP listener.** The empty
   string was treated as unset, so the image kept `listen_addr =
   0.0.0.0`. Exposure is limited to `hp1-pg-net` (no host port
   mapping) but this still deviates from the spec. We accept the
   internal TCP listener as harmless and document it rather than
   fight the image further.

Fix:
- Introduce `BACKEND_DATABASE_URL` env var: bare `postgresql://`
  scheme (no `+asyncpg`), readable by edoburu's parser.
- pgbouncer service consumes `BACKEND_DATABASE_URL` as its
  `DATABASE_URL`. hp1_agent keeps using the asyncpg-flavoured
  `DATABASE_URL` directly.
- Pin `LISTEN_PORT: "6432"`.
- Update healthcheck, PGBOUNCER.md, README.md, .env.example to
  reference 6432 consistently.
- Document the internal-only TCP listener in PGBOUNCER.md.

Version bump: 2.49.2 → 2.49.3

---

## Change 1 — `docker/docker-compose.yml`

Find the `pgbouncer:` service `environment:` block:

````yaml
    environment:
      # Backend connection — image generates pgbouncer.ini from this.
      # DATABASE_URL in .env must use the *internal* PG hostname/port
      # (hp1-postgres:5432 on hp1-pg-net), not the host-mapped 5433.
      DATABASE_URL: ${DATABASE_URL}
      POOL_MODE: transaction
      AUTH_TYPE: trust
      MAX_CLIENT_CONN: 200
      DEFAULT_POOL_SIZE: 25
      RESERVE_POOL_SIZE: 5
      RESERVE_POOL_TIMEOUT: 3
      SERVER_IDLE_TIMEOUT: 300
      SERVER_LIFETIME: 3600
      QUERY_WAIT_TIMEOUT: 30
      ADMIN_USERS: pgbouncer
      STATS_USERS: pgbouncer
      # Unix socket only — no TCP listener.
      LISTEN_ADDR: ""
      UNIX_SOCKET_DIR: /var/run/pgbouncer
      UNIX_SOCKET_MODE: "0777"
````

Replace with:

````yaml
    environment:
      # Backend connection — pgbouncer reads BACKEND_DATABASE_URL from
      # docker/.env and exposes it to its entrypoint as DATABASE_URL.
      # BACKEND_DATABASE_URL must use the bare 'postgresql://' scheme
      # (no '+asyncpg'); the edoburu entrypoint's URL parser cannot
      # tolerate driver suffixes and silently mangles the username.
      DATABASE_URL: ${BACKEND_DATABASE_URL}
      POOL_MODE: transaction
      AUTH_TYPE: trust
      # v2.49.3 — pin to 6432 (pgbouncer convention). Image default
      # is 5432, which collides with Postgres conventions and causes
      # the socket to land at .s.PGSQL.5432 instead of .s.PGSQL.6432.
      LISTEN_PORT: "6432"
      MAX_CLIENT_CONN: 200
      DEFAULT_POOL_SIZE: 25
      RESERVE_POOL_SIZE: 5
      RESERVE_POOL_TIMEOUT: 3
      SERVER_IDLE_TIMEOUT: 300
      SERVER_LIFETIME: 3600
      QUERY_WAIT_TIMEOUT: 30
      ADMIN_USERS: pgbouncer
      STATS_USERS: pgbouncer
      # NOTE: image keeps a TCP listener on 0.0.0.0:6432 inside the
      # container regardless of LISTEN_ADDR setting. No host port is
      # mapped, so reachability is confined to the hp1-pg-net bridge
      # (hp1_agent, hp1-postgres, future containers on that bridge).
      # See docker/PGBOUNCER.md "Threat model" for the implications.
      UNIX_SOCKET_DIR: /var/run/pgbouncer
      UNIX_SOCKET_MODE: "0777"
````

In the same service, find the healthcheck:

````yaml
    healthcheck:
      test: ["CMD-SHELL", "test -S /var/run/pgbouncer/.s.PGSQL.6432 || exit 1"]
````

Leave it as-is — it now matches because `LISTEN_PORT: "6432"` is
pinned. (Verify step below confirms it.)

## Change 2 — `docker/.env.example`

Find the `DATABASE_URL` documentation block (added in v2.49.1):

````bash
# DATABASE_URL — Postgres connection string used by hp1_agent AND
# (when active) by pgbouncer to authenticate upstream to Postgres.
#
# Direct (no pooler):
#   DATABASE_URL=postgresql+asyncpg://hp1user:PASS@hp1-postgres:5432/hp1_agent
#
# Via PgBouncer (Unix socket — recommended for production single-host):
#   DATABASE_URL=postgresql+asyncpg://hp1user:PASS@/hp1_agent?host=/var/run/pgbouncer
#
# Notes:
# - The socket form embeds no host (just `@/dbname?host=`).
# - PgBouncer's trust auth ignores the password on the front-side
#   connection from hp1_agent. The same PASS value IS read by
#   pgbouncer to authenticate upstream to hp1-postgres.
# - PgBouncer setup, restrictions, mTLS migration: docker/PGBOUNCER.md
````

Replace with:

````bash
# DATABASE_URL — Postgres connection string used by hp1_agent.
#
# Direct (no pooler):
#   DATABASE_URL=postgresql+asyncpg://hp1user:PASS@hp1-postgres:5432/hp1_agent
#
# Via PgBouncer (Unix socket — recommended for production single-host):
#   DATABASE_URL=postgresql+asyncpg://hp1user:PASS@/hp1_agent?host=/var/run/pgbouncer&port=6432
#
# Notes:
# - hp1_agent uses the +asyncpg driver suffix; asyncpg supports the
#   ?host= directive for Unix socket connections.
# - PgBouncer's trust auth ignores the password on the front-side
#   connection from hp1_agent. The PASS value here is irrelevant when
#   the socket form is used.
# - PgBouncer setup, restrictions, mTLS migration: docker/PGBOUNCER.md

# BACKEND_DATABASE_URL — Postgres connection string used by pgbouncer
# to authenticate UPSTREAM to hp1-postgres. Required when the
# 'pgbouncer' compose profile is active. Ignored otherwise.
#
# Must use the bare 'postgresql://' scheme — the edoburu entrypoint's
# URL parser does NOT tolerate driver suffixes (the '+asyncpg' suffix
# causes the parser to mangle the username and break upstream auth).
#
#   BACKEND_DATABASE_URL=postgresql://hp1user:PASS@hp1-postgres:5432/hp1_agent
#
# The PASS value here MUST be the real Postgres password — pgbouncer
# uses it to authenticate to hp1-postgres on every backend connection.
````

## Change 3 — `docker/PGBOUNCER.md`

Replace the section "### 4. DATABASE_URL serves two roles when PgBouncer is active":

Find:

````markdown
### 4. DATABASE_URL serves two roles when PgBouncer is active

The same `DATABASE_URL` env var is read by:

- **hp1_agent**: to connect front-side via the socket. The password
  in the URL is ignored (PgBouncer's trust auth doesn't check it).
- **PgBouncer**: to connect backend to Postgres. The password IS
  required here — PgBouncer authenticates upstream as `hp1user`.

Both clients read the same URL because the form
`postgresql+asyncpg://hp1user:PASS@/hp1_agent?host=/var/run/pgbouncer`
is parsed by both: hp1_agent uses the `?host=` socket directive,
PgBouncer ignores the socket directive (it's connecting elsewhere)
and uses the `hp1user:PASS@` portion for upstream auth.

If you want to separate these (front-side gets no password,
back-side gets a real one), split into two env vars:
- `DATABASE_URL` for hp1_agent (no password)
- `BACKEND_DATABASE_URL` for PgBouncer (with password)

Then update `pgbouncer:` env block in compose to pass
`BACKEND_DATABASE_URL` as `DATABASE_URL`. Not done by default to
keep the configuration minimal.
````

Replace with:

````markdown
### 4. Two URLs, two readers (split since v2.49.3)

PgBouncer and hp1_agent read **different** env vars in `docker/.env`:

| Env var | Reader | Scheme | Notes |
|---|---|---|---|
| `DATABASE_URL` | hp1_agent | `postgresql+asyncpg://...` | Uses asyncpg driver |
| `BACKEND_DATABASE_URL` | pgbouncer | `postgresql://...` | Bare scheme — edoburu can't parse `+asyncpg` |

The split exists because the edoburu entrypoint's URL parser silently
mangles usernames when the scheme contains a `+`-delimited driver
suffix (observed: `hp1user` parsed as `hp1`, breaking upstream auth).

Both URLs point at the same database with the same credentials. The
hp1_agent URL uses the socket form (`@/hp1_agent?host=/var/run/pgbouncer`);
the pgbouncer URL uses TCP form (`@hp1-postgres:5432/hp1_agent`)
because that's how pgbouncer reaches Postgres upstream.

If the credentials change in Postgres, update **both** values.

### 5. TCP listener is active inside the container

Despite `LISTEN_ADDR=""`, the edoburu image keeps a TCP listener on
`0.0.0.0:6432` inside the container. No host port is mapped, so this
listener is reachable only from other containers on the
`hp1-pg-net` Docker network: `hp1-postgres`, `hp1_agent`, and any
future containers attached to that bridge.

This is a deviation from v2.49.1's "Unix socket only" goal but the
exposure surface is bounded to internal Docker networking. The
documented threat model in this file already assumes the agent-01
host is the trust boundary; an attacker with shell on agent-01
already has Docker access and can reach the socket regardless.

If a future requirement tightens this further (e.g., adversarial
sidecars in the same compose project), use the mTLS migration recipe
to enforce cert-based auth on the TCP listener.
````

Then renumber subsequent sections in PGBOUNCER.md if they're numbered
sequentially (5 → 6, 6 → 7, etc.) — leave them alone if they aren't.

Also find and replace any remaining `:6432` admin console examples
to confirm they use port 6432 (most should already; this is just
sanity).

## Change 4 — `docker/README.md`

Find the Activate block referring to `DATABASE_URL`:

````
   DATABASE_URL=postgresql+asyncpg://hp1user:PASS@/hp1_agent?host=/var/run/pgbouncer
````

Replace with:

````
   DATABASE_URL=postgresql+asyncpg://hp1user:PASS@/hp1_agent?host=/var/run/pgbouncer&port=6432
   BACKEND_DATABASE_URL=postgresql://hp1user:PASS@hp1-postgres:5432/hp1_agent
````

Find the verification block and update to reference port 6432 — the
existing block already does this (it's the runtime that was wrong,
not the docs). Confirm with grep.

## Change 5 — VERSION

Update `VERSION`: 2.49.2 → 2.49.3

## Verify

````bash
# 1. Compose lints clean
docker compose -f docker/docker-compose.yml config > /dev/null

# 2. LISTEN_PORT is pinned
grep -q 'LISTEN_PORT: "6432"' docker/docker-compose.yml

# 3. pgbouncer reads BACKEND_DATABASE_URL
grep -q 'DATABASE_URL: \${BACKEND_DATABASE_URL}' docker/docker-compose.yml
! grep -E '^[[:space:]]+DATABASE_URL: \$\{DATABASE_URL\}$' docker/docker-compose.yml

# 4. Healthcheck still references 6432 (now matches reality)
grep -q '.s.PGSQL.6432' docker/docker-compose.yml

# 5. .env.example documents both vars
grep -q 'BACKEND_DATABASE_URL=postgresql://' docker/.env.example
grep -q 'DATABASE_URL=postgresql+asyncpg://' docker/.env.example
````

## Commit

````bash
git add -A
git commit -m "fix(infra): split BACKEND_DATABASE_URL + pin LISTEN_PORT=6432 (v2.49.3)

Three runtime deviations from v2.49.1's spec, observed on first deploy:

1. edoburu entrypoint's URL parser chokes on '+asyncpg' driver
   suffix, truncating 'hp1user' to 'hp1' in the generated
   userlist.txt and [databases] block. Upstream auth would fail.
   Fix: pgbouncer reads a separate BACKEND_DATABASE_URL env var
   with bare 'postgresql://' scheme.

2. LISTEN_PORT was unset, defaulted to 5432, so the socket landed
   at .s.PGSQL.5432 instead of the documented .s.PGSQL.6432.
   Healthcheck would have failed permanently. Fix: pin to 6432.

3. LISTEN_ADDR=\"\" did not disable the TCP listener — image kept
   listen_addr=0.0.0.0:6432. Exposure bounded to hp1-pg-net (no
   host port mapping). Documented in PGBOUNCER.md as accepted
   deviation; threat model already assumed agent-01 host as trust
   boundary."
git push origin main
````

## Deploy

After CC commits and CI image rebuild:

````bash
# On agent-01
cd /opt/hp1-agent
git pull origin main

# Add BACKEND_DATABASE_URL to docker/.env (bare postgresql:// scheme)
# Example value (replace PASS with the real PG password):
#   BACKEND_DATABASE_URL=postgresql://hp1user:PASS@hp1-postgres:5432/hp1_agent

# Recreate pgbouncer (env_file change requires recreate, not restart)
cd docker
docker compose --env-file .env --profile pgbouncer up -d --force-recreate pgbouncer

# Verify
docker logs hp1_pgbouncer --tail 30 | grep -E 'auth_user|listen_port|listening'
docker exec hp1_pgbouncer cat /etc/pgbouncer/userlist.txt
# Should now show "hp1user" not "hp1"
docker exec hp1_pgbouncer test -S /var/run/pgbouncer/.s.PGSQL.6432 && echo "socket OK"
docker exec hp1_pgbouncer \
  psql -h /var/run/pgbouncer -p 6432 -U pgbouncer pgbouncer -c 'SHOW DATABASES;'
docker exec hp1_pgbouncer \
  psql -h /var/run/pgbouncer -p 6432 -U hp1user -d hp1_agent -c 'SELECT 1;'
# This last one tests upstream auth and should return one row.
````
