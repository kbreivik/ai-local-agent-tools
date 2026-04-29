# CC PROMPT — v2.49.0 — feat(infra): PgBouncer transaction-pool in front of Postgres

## What this does

Adds PgBouncer (transaction-pool mode) between hp1_agent and
hp1-postgres. PgBouncer multiplexes many app-side logical connections
onto a small number of real backend connections, lifting the hard
ceiling we'd otherwise hit when hp1_agent scales to multiple replicas
or when total app-side pool sizing approaches PG's max_connections.

Topology after this lands:

    hp1_agent (sync ~20 + async ~30 + storage ~20 = ~70 logical conns)
        │
        └─► pgbouncer:6432 (transaction pool, default_pool_size=25)
                │
                └─► hp1-postgres:5432 (Ansible-managed)

Transaction pool mode means each transaction (not each connection)
claims a backend conn — released the moment the transaction commits
or rolls back. For DEATHSTAR's mostly-short transactions (settings
I/O, fact upserts, tool result writes), backend utilisation stays
low.

Caveats of transaction mode (documented for ops awareness, not
blockers):

- `LISTEN/NOTIFY` does NOT work across transaction-pooled conns. We
  don't currently use it. If you ever want to add it (e.g. for the
  v2.5x op_queue table), route those clients direct to PG.
- `SET` / `RESET` per session does NOT persist across transactions.
  We don't rely on session-level GUCs.
- Prepared statements at the protocol level need PgBouncer ≥1.21.
  We pin 1.22.

Activation: opt-in via the `pgbouncer` compose profile. Operator
populates `userlist.txt` with md5 hashes, flips `DATABASE_URL` in
`docker/.env` to point at `pgbouncer:6432`, then brings the service
up. README.md updated with the recipe.

Version bump: 2.48.0 → 2.49.0 (minor — new infrastructure subsystem)

---

## Change 1 — new file: `docker/pgbouncer/pgbouncer.ini`

Create with exactly this content:

```ini
;; PgBouncer config — DEATHSTAR (v2.49.0)
;; Transaction pool mode. Listens on 6432.

[databases]
;; Upstream resolved via hp1-pg-net bridge (Ansible-managed).
;; The hostname 'hp1-postgres' resolves on the shared docker network.
;; Port 5432 is the IN-NETWORK port; 5433 is the host-mapped port.
hp1_agent = host=hp1-postgres port=5432 dbname=hp1_agent

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432

;; Authenticate clients via userlist.txt (md5 hashes).
auth_type = md5
auth_file = /etc/pgbouncer/userlist.txt

;; Pool mode: transaction. Each tx claims a backend conn, releases on
;; commit/rollback. Does NOT support LISTEN/NOTIFY or session GUCs —
;; both unused in DEATHSTAR.
pool_mode = transaction

;; Capacity tuning.
;; max_client_conn — how many app-side conns we'll accept. Generous;
;; idle clients are cheap.
max_client_conn = 200
;; default_pool_size — backend conns per (db, user). Keep low; PG
;; max_connections=100 is shared with admin sessions.
default_pool_size = 25
reserve_pool_size = 5
reserve_pool_timeout = 3.0

;; Timeouts.
server_idle_timeout = 300
server_lifetime = 3600
query_wait_timeout = 30

;; Logging — keep low-noise.
log_connections = 0
log_disconnections = 0
log_pooler_errors = 1

;; Admin access. `psql -p 6432 -U pgbouncer pgbouncer` to inspect.
admin_users = pgbouncer
stats_users = pgbouncer
```

## Change 2 — new file: `docker/pgbouncer/userlist.txt`

Create with exactly this placeholder content:

```
;; PgBouncer userlist — md5 hashes
;;
;; Format per line: "username" "md5<hash>"
;;
;; Generate the hash for a given user/password with:
;;   echo -n "${PASSWORD}${USERNAME}" | md5sum | awk '{print "md5"$1}'
;;
;; Example workflow:
;;   USER=hp1user
;;   PASSWORD=...        # from docker/.env DB_PASSWORD or DATABASE_URL
;;   HASH=$(echo -n "${PASSWORD}${USER}" | md5sum | awk '{print "md5"$1}')
;;   echo "\"${USER}\" \"${HASH}\"" >> docker/pgbouncer/userlist.txt
;;
;; Add an admin entry as well so 'psql -p 6432 -U pgbouncer pgbouncer'
;; works:
;;   "pgbouncer" "md5<hash for the pgbouncer admin password>"
;;
;; This file MUST be populated before bringing up the pgbouncer
;; service. An empty userlist means pgbouncer rejects all clients.
```

## Change 3 — extend `docker/docker-compose.yml`

CC: open `docker/docker-compose.yml`. Add a new service block under
`services:`, placed AFTER `muninndb-proxy:` and BEFORE `hp1_agent:`.

```yaml
  # ── PgBouncer transaction pool (v2.49.0) ────────────────────────────
  # Multiplexes app-side conns onto a small backend pool to avoid
  # exhausting Postgres max_connections. Activated via the 'pgbouncer'
  # profile.
  #
  # Setup:
  #   1. Populate docker/pgbouncer/userlist.txt with md5 hashes
  #      (see file header for the recipe).
  #   2. In docker/.env, set DATABASE_URL to point at pgbouncer:
  #        DATABASE_URL=postgresql+asyncpg://hp1user:PASS@pgbouncer:6432/hp1_agent
  #   3. docker compose -f docker/docker-compose.yml \
  #        --profile pgbouncer up -d pgbouncer
  #      docker compose -f docker/docker-compose.yml up -d hp1_agent
  #
  # Health: docker exec hp1_pgbouncer \
  #           psql -p 6432 -U pgbouncer pgbouncer -c 'SHOW POOLS;'
  pgbouncer:
    image: edoburu/pgbouncer:1.22.1
    container_name: hp1_pgbouncer
    restart: unless-stopped
    profiles: ["pgbouncer"]
    networks:
      - agent-net
      - hp1-pg-net
    ports:
      - "6432:6432"
    volumes:
      - ./pgbouncer/pgbouncer.ini:/etc/pgbouncer/pgbouncer.ini:ro
      - ./pgbouncer/userlist.txt:/etc/pgbouncer/userlist.txt:ro
    healthcheck:
      test: ["CMD", "pg_isready", "-h", "127.0.0.1", "-p", "6432"]
      interval: 10s
      timeout: 5s
      retries: 6
      start_period: 5s
```

## Change 4 — document in `docker/.env.example`

CC: open `docker/.env.example`. Find the existing `DATABASE_URL=`
line. Add a comment block immediately above it:

```bash
# DATABASE_URL — Postgres connection string.
#
# Direct (no pooler):
#   DATABASE_URL=postgresql+asyncpg://hp1user:PASS@hp1-postgres:5432/hp1_agent
#
# Via PgBouncer (recommended once 'pgbouncer' compose profile is up):
#   DATABASE_URL=postgresql+asyncpg://hp1user:PASS@pgbouncer:6432/hp1_agent
#
# PgBouncer setup: see docker/pgbouncer/userlist.txt (md5 hash recipe)
# and docker-compose.yml :: pgbouncer service.
```

(Leave the existing live value unchanged — operator flips it manually
when bringing up the pgbouncer profile.)

## Change 5 — append a section to `docker/README.md`

CC: open `docker/README.md`. Append at the end:

````markdown

## PgBouncer transaction pool (v2.49.0)

Optional transaction-pool layer between hp1_agent and hp1-postgres.
Activate when scaling out (multiple agent replicas) or when sustained
PG `max_connections` pressure is observed.

### Activate

1. Generate md5 hashes and populate `docker/pgbouncer/userlist.txt`:

   ```bash
   USER=hp1user
   PASSWORD=...   # match docker/.env
   HASH=$(echo -n "${PASSWORD}${USER}" | md5sum | awk '{print "md5"$1}')
   echo "\"${USER}\" \"${HASH}\"" >> docker/pgbouncer/userlist.txt
   ```

2. Update `docker/.env` to route hp1_agent through pgbouncer:

   ```
   DATABASE_URL=postgresql+asyncpg://hp1user:PASS@pgbouncer:6432/hp1_agent
   ```

3. Bring up the service and restart hp1_agent so it picks up the new DSN:

   ```bash
   docker compose -f docker/docker-compose.yml \
     --profile pgbouncer up -d pgbouncer
   docker compose -f docker/docker-compose.yml up -d hp1_agent
   ```

### Verify

```bash
docker exec hp1_pgbouncer \
  psql -p 6432 -U pgbouncer pgbouncer -c 'SHOW POOLS;'
```

Healthy steady state: most clients in `cl_idle`, a small number of
backend conns in `sv_active` / `sv_idle`. Active client count should
match what hp1_agent's pools have currently checked out.

### Caveats

- Transaction-pool mode breaks `LISTEN/NOTIFY` and per-session `SET`
  — DEATHSTAR does not currently use either.
- Prepared-statement protocol is supported in pgbouncer ≥1.21. Image
  pinned to 1.22.1.
- If `userlist.txt` is empty, pgbouncer rejects all clients with an
  authentication failure. Always populate before activation.
````

## Verify

```bash
# 1. Lint compose
docker compose -f docker/docker-compose.yml config > /dev/null

# 2. Confirm new files
test -f docker/pgbouncer/pgbouncer.ini
test -f docker/pgbouncer/userlist.txt
grep -q "pgbouncer:" docker/docker-compose.yml

# 3. (Operator step, NOT part of CC verification) populate userlist.txt
#    + flip .env, then:
#    docker compose -f docker/docker-compose.yml \
#      --profile pgbouncer up -d pgbouncer
#    docker compose -f docker/docker-compose.yml up -d hp1_agent
#    curl -sf http://localhost:8000/api/health
#    docker exec hp1_pgbouncer psql -p 6432 -U pgbouncer pgbouncer \
#      -c 'SHOW POOLS;'
```

## Version bump

Update `VERSION`: 2.48.0 → 2.49.0

## Commit

```bash
git add -A
git commit -m "feat(infra): PgBouncer transaction-pool service (v2.49.0)

New compose service 'pgbouncer' (profile: pgbouncer, image
edoburu/pgbouncer:1.22.1) sits between hp1_agent and hp1-postgres.
Transaction pool mode multiplexes app-side logical conns
(sync ~20 + async ~30 + storage ~20) onto default_pool_size=25
backend conns, comfortably under PG's max_connections=100.

Opt-in activation: operator populates userlist.txt with md5 hashes,
flips DATABASE_URL in docker/.env to point at pgbouncer:6432, then
brings the service up. README.md updated with the recipe.

Caveats documented: LISTEN/NOTIFY and session GUCs unsupported in
transaction mode (both unused in DEATHSTAR). Prepared statements
require pgbouncer ≥1.21 (we pin 1.22)."
git push origin main
```

## Deploy

This prompt does NOT auto-activate pgbouncer. After CC commits and
the image is built, the operator runs the activation steps in
`docker/README.md`. Until activation, hp1_agent continues to talk
direct to hp1-postgres and behaviour is unchanged from v2.48.0.
