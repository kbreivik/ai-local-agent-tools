# CC PROMPT — v2.49.4 — fix(infra): AUTH_TYPE=scram-sha-256 + revert BACKEND_DATABASE_URL split

## What this does

Two corrections to v2.49.3, both rooted in the same misdiagnosis.

### Correction 1 — AUTH_TYPE=trust → scram-sha-256

PG14+ defaults to `password_encryption = scram-sha-256` and rejects
md5-hashed login attempts with `FATAL: server login failed: wrong
password type`. v2.49.3 left `AUTH_TYPE=trust`, which causes edoburu's
entrypoint to write **md5-hashed** entries to userlist.txt (per its
source: only `plain` and `scram-sha-256` branches write plaintext).

Fix: set `AUTH_TYPE: scram-sha-256`. The entrypoint then writes the
password as plaintext to userlist.txt; pgbouncer uses the plaintext
to derive a SCRAM proof on every upstream connection. PG14+ accepts.

Trade-off vs v2.49.1's "trust + volume isolation" model: front-side
now requires a password from hp1_agent. That password is already in
`DATABASE_URL`, so the cost is zero and we gain end-to-end SCRAM auth
on top of the existing volume isolation.

### Correction 2 — revert the BACKEND_DATABASE_URL split

v2.49.3 introduced `BACKEND_DATABASE_URL` based on a wrong diagnosis:
the assumption was that edoburu's URL parser truncated `hp1user` to
`hp1`. The actual PG username on this deployment is `hp1`, parsed
correctly. The `+asyncpg` driver suffix was never the problem — the
md5 vs SCRAM mismatch was.

Fix: pgbouncer reads `${DATABASE_URL}` again (single env var). The
`BACKEND_DATABASE_URL` env var is removed from `.env.example` and
PGBOUNCER.md. Operators should remove the line from their
`docker/.env` (no longer referenced; harmless if left in place).

Version bump: 2.49.3 → 2.49.4

---

## Change 1 — `docker/docker-compose.yml`

Find the `pgbouncer:` service `environment:` block (post v2.49.3):

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
````

Replace with:

````yaml
    environment:
      # Backend connection — image generates pgbouncer.ini from this.
      # DATABASE_URL must use the *internal* PG hostname/port
      # (hp1-postgres:5432 on hp1-pg-net), not the host-mapped 5433.
      # The edoburu entrypoint parses the URL fine including the
      # '+asyncpg' driver suffix; v2.49.3's BACKEND_DATABASE_URL
      # split was based on a wrong diagnosis and is reverted here.
      DATABASE_URL: ${DATABASE_URL}
      POOL_MODE: transaction
      # v2.49.4 — scram-sha-256 instead of trust:
      #   PG14+ defaults to password_encryption=scram-sha-256 and rejects
      #   md5-hashed userlist entries (which the entrypoint generates with
      #   AUTH_TYPE=trust). With AUTH_TYPE=scram-sha-256, the entrypoint
      #   writes plaintext to userlist.txt; pgbouncer uses it to derive
      #   SCRAM proofs against PG upstream.
      #   Front-side: hp1_agent must now send the password. It already
      #   does (the password is in DATABASE_URL).
      #   Volume isolation still applies as defense in depth.
      AUTH_TYPE: scram-sha-256
      # v2.49.3 — pin to 6432 (pgbouncer convention). Image default
      # is 5432, which collides with Postgres conventions and causes
      # the socket to land at .s.PGSQL.5432 instead of .s.PGSQL.6432.
      LISTEN_PORT: "6432"
````

(All other env vars below `LISTEN_PORT` stay as v2.49.3 set them. The
healthcheck and volumes blocks below the environment also stay
unchanged.)

## Change 2 — `docker/.env.example`

Find (post v2.49.3):

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

Replace with:

````bash
# DATABASE_URL — Postgres connection string used by hp1_agent AND
# by pgbouncer (when the pgbouncer profile is active).
#
# Direct (no pooler):
#   DATABASE_URL=postgresql+asyncpg://USER:PASS@hp1-postgres:5432/hp1_agent
#
# Via PgBouncer (Unix socket — recommended for production single-host):
#   DATABASE_URL=postgresql+asyncpg://USER:PASS@/hp1_agent?host=/var/run/pgbouncer&port=6432
#
# Notes:
# - hp1_agent uses asyncpg; the ?host= directive selects the Unix
#   socket directory and port=6432 selects which socket file
#   (.s.PGSQL.6432) inside it.
# - pgbouncer (AUTH_TYPE=scram-sha-256) requires the password on both
#   sides: hp1_agent sends it; pgbouncer uses it to derive a SCRAM
#   proof for the upstream connection to hp1-postgres.
# - PgBouncer setup, restrictions, mTLS migration: docker/PGBOUNCER.md
````

## Change 3 — `docker/PGBOUNCER.md`

Replace the section "### 4. Two URLs, two readers (split since v2.49.3)"
in its entirety. Find from the heading line through to the next `### N.`
heading (the "TCP listener is active inside the container" section,
which currently follows it).

Find:

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
````

Replace with:

````markdown
### 4. Single DATABASE_URL serves both readers

`DATABASE_URL` in `docker/.env` is read by both:

- **hp1_agent**: connects front-side via the Unix socket. The form
  is `postgresql+asyncpg://USER:PASS@/dbname?host=/var/run/pgbouncer&port=6432`.
  asyncpg interprets `?host=` as a socket directory and `port=6432`
  as the socket file suffix.
- **pgbouncer**: connects upstream to hp1-postgres on TCP. Its
  entrypoint parses the same URL, ignores `?host=` (it's connecting
  elsewhere), and uses USER/PASS to authenticate to hp1-postgres.

The edoburu entrypoint handles the `+asyncpg` driver suffix in the
scheme correctly — the suffix sits in the scheme part and the parser
strips it before extracting credentials. (v2.49.3 introduced a
`BACKEND_DATABASE_URL` split based on a wrong diagnosis; v2.49.4
reverted it.)

If credentials change in PG, update this single value.

### 5. SCRAM-SHA-256 end to end

Front-side (hp1_agent ↔ pgbouncer) and back-side (pgbouncer ↔ PG)
both use SCRAM-SHA-256.

Mechanism: edoburu's entrypoint writes the password as **plaintext**
to `/etc/pgbouncer/userlist.txt` (its branch logic for AUTH_TYPE in
{plain, scram-sha-256}). When hp1_agent connects, pgbouncer
challenges and verifies SCRAM against the plaintext. When pgbouncer
opens an upstream connection to PG, it derives a SCRAM proof from the
same plaintext. PG14+ accepts because it stores SCRAM verifiers
internally and verifies the proof — at no point does PG see the
plaintext over the wire.

The plaintext lives in `/etc/pgbouncer/userlist.txt` inside the
container's writable layer. It is not on the host filesystem and not
in any named volume — only for the container's lifetime. `docker
inspect` and `docker exec cat` can still read it; tighten with the
`auth_user` + `auth_query` pattern (see pgbouncer docs) if that's a
concern for your threat model.
````

(The "TCP listener is active inside the container" section that
followed v2.49.3's section 4 should remain in place but renumber from
5 to 6 if you also renumbered higher sections. If sections are not
strictly numbered, leave numbering as-is.)

## Change 4 — `docker/README.md`

Find the Activate block (post v2.49.3):

````
   DATABASE_URL=postgresql+asyncpg://hp1user:PASS@/hp1_agent?host=/var/run/pgbouncer&port=6432
   BACKEND_DATABASE_URL=postgresql://hp1user:PASS@hp1-postgres:5432/hp1_agent
````

Replace with:

````
   DATABASE_URL=postgresql+asyncpg://USER:PASS@/hp1_agent?host=/var/run/pgbouncer&port=6432
````

## Change 5 — VERSION

Update `VERSION`: 2.49.3 → 2.49.4

## Verify

````bash
# 1. Compose lints clean
docker compose -f docker/docker-compose.yml config > /dev/null

# 2. AUTH_TYPE is scram-sha-256
grep -q 'AUTH_TYPE: scram-sha-256' docker/docker-compose.yml
! grep -q 'AUTH_TYPE: trust' docker/docker-compose.yml

# 3. pgbouncer reads single DATABASE_URL
grep -E '^[[:space:]]+DATABASE_URL: \$\{DATABASE_URL\}$' docker/docker-compose.yml
! grep -q 'BACKEND_DATABASE_URL' docker/docker-compose.yml

# 4. .env.example no longer documents BACKEND_DATABASE_URL
! grep -q 'BACKEND_DATABASE_URL' docker/.env.example

# 5. LISTEN_PORT and healthcheck still consistent (carried from v2.49.3)
grep -q 'LISTEN_PORT: "6432"' docker/docker-compose.yml
grep -q '.s.PGSQL.6432' docker/docker-compose.yml
````

## Commit

````bash
git add -A
git commit -m "fix(infra): AUTH_TYPE=scram-sha-256 + revert BACKEND_DATABASE_URL split (v2.49.4)

Two corrections to v2.49.3, both rooted in the same misdiagnosis.

1. AUTH_TYPE=trust caused edoburu's entrypoint to write md5-hashed
   userlist entries (per its source: only 'plain' and 'scram-sha-256'
   branches write plaintext). PG14+ rejects md5 with 'wrong password
   type' when password_encryption=scram-sha-256.
   Fix: AUTH_TYPE=scram-sha-256 — entrypoint writes plaintext, pgbouncer
   derives SCRAM proofs upstream. End-to-end SCRAM, with the front-side
   trust+isolation model upgraded to SCRAM+isolation.

2. BACKEND_DATABASE_URL split was introduced under the wrong belief that
   edoburu's parser truncated the username. The actual username on this
   deployment is 'hp1' (parsed correctly); the issue was always md5 vs
   SCRAM, never URL parsing. Reverting to a single DATABASE_URL.

Operators should remove BACKEND_DATABASE_URL from docker/.env
(no longer referenced; harmless if left in place)."
git push origin main
````

## Deploy

After CC commits and CI image rebuild:

````bash
# On agent-01
cd /opt/hp1-agent
git pull origin main

# Optional cleanup: remove BACKEND_DATABASE_URL from docker/.env
sed -i '/^BACKEND_DATABASE_URL=/d' docker/.env

# Recreate pgbouncer to pick up new AUTH_TYPE
cd docker
docker compose --env-file .env --profile pgbouncer up -d --force-recreate pgbouncer

# Verify
docker logs hp1_pgbouncer --tail 30
docker exec hp1_pgbouncer cat /etc/pgbouncer/userlist.txt
# Should now show "hp1" "<plaintext-password>" (not md5...)
docker exec hp1_pgbouncer test -S /var/run/pgbouncer/.s.PGSQL.6432 && echo "socket OK"
docker compose ps pgbouncer
# Should reach (healthy)

# Real upstream auth test — should return one row
docker exec hp1_pgbouncer \
  psql -h /var/run/pgbouncer -p 6432 -U hp1 -d hp1_agent -c 'SELECT 1;'
````

If `SELECT 1;` returns one row, both upstream SCRAM and front-side
SCRAM are working. Next step: flip hp1_agent's `DATABASE_URL` to the
socket form and recreate hp1_agent (separate operator step).
