# CC PROMPT — v2.49.5 — fix(infra): bypass DATABASE_URL parsing in pgbouncer (URL-encoding bug)

## What this does

Fixes a SCRAM auth failure on both legs (front-side and upstream)
caused by the edoburu entrypoint extracting the password from
`DATABASE_URL` **without URL-decoding it**.

When the PG password contains URL-special characters (`%`, `$`, `@`,
`:`, etc.), `DATABASE_URL` carries the URL-encoded form. The edoburu
entrypoint's `parse_url` function takes the encoded substring as-is
and writes it to `userlist.txt`. Result:

- **Front-side**: hp1_agent's asyncpg driver URL-decodes the password
  before sending it to pgbouncer. Pgbouncer compares against the
  encoded userlist value → mismatch → SCRAM fails.
- **Upstream**: pgbouncer derives a SCRAM proof from the encoded
  userlist value. PG's stored hash is for the decoded password →
  mismatch → SCRAM fails.

Observed userlist after v2.49.4: the password contained `%25` and
`%24` literals where the real password has `%` and `$`. Two encode
layers, only one decode layer.

Fix: stop feeding pgbouncer a URL. Use discrete env vars
(`DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME`). The
entrypoint's `generate_userlist_if_needed` and `generate_config_db_entry`
functions read these directly as raw strings — no URL parsing, no
encoding artifacts. The image's source code (entrypoint.sh) supports
this path explicitly: when DB_USER + DB_PASSWORD + DB_HOST are set,
DATABASE_URL is not needed and not consulted.

hp1_agent continues to use `DATABASE_URL` (asyncpg requires URL form).
Only pgbouncer's compose env changes.

Version bump: 2.49.4 → 2.49.5

---

## Change 1 — `docker/docker-compose.yml`

Find the `pgbouncer:` service `environment:` block (post v2.49.4):

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
````

Replace with:

````yaml
    environment:
      # v2.49.5 — bypass DATABASE_URL parsing.
      #   The edoburu entrypoint extracts the password substring from
      #   DATABASE_URL without URL-decoding it. When the password contains
      #   URL-special chars (%, $, @, :, etc.), the encoded form ends up
      #   in userlist.txt verbatim, while asyncpg (front-side) and PG
      #   (upstream) both work with the decoded form. Result: SCRAM fails
      #   on both legs.
      #   Discrete DB_* env vars bypass URL parsing entirely. The
      #   entrypoint reads them as raw strings (see entrypoint.sh
      #   generate_userlist_if_needed + generate_config_db_entry).
      #   hp1_agent still uses DATABASE_URL — only pgbouncer changes here.
      DB_HOST: hp1-postgres
      DB_PORT: "5432"
      DB_USER: ${POSTGRES_USER}
      DB_PASSWORD: ${POSTGRES_PASSWORD}
      DB_NAME: ${POSTGRES_DB:-hp1_agent}
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
````

(Everything below `AUTH_TYPE` stays unchanged: `LISTEN_PORT: "6432"`,
pool sizing, listener notes, socket dir/mode.)

## Change 2 — `docker/.env.example`

The discrete vars are sourced from existing `POSTGRES_*` entries.
Confirm those entries already exist in the example file (they do
in current state — used by the dev-profile postgres service); if
present, no edit needed in this file. Verify with:

````bash
grep -E '^POSTGRES_(USER|PASSWORD|DB)=' docker/.env.example
````

If any of `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` are
missing from `.env.example`, add them at an appropriate place in
the file (near other PG-related entries):

````bash
# Postgres credentials — used by hp1_agent (via DATABASE_URL),
# the dev-profile postgres service, and the pgbouncer profile
# (which reads them as DB_USER/DB_PASSWORD/DB_NAME directly to
# bypass URL-encoding issues with special chars in the password).
POSTGRES_USER=hp1
POSTGRES_PASSWORD=changeme
POSTGRES_DB=hp1_agent
````

If they already exist, leave them alone — only update the comment
nearby (if any) to mention the pgbouncer profile reuses them.

## Change 3 — `docker/PGBOUNCER.md`

In the section "### 4. Single DATABASE_URL serves both readers" (added
in v2.49.4), correct the claim that pgbouncer reads `DATABASE_URL`.
It no longer does.

Find:

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
````

Replace with:

````markdown
### 4. Two readers, two credential sources

| Reader | Credential source | Form |
|---|---|---|
| hp1_agent | `DATABASE_URL` in `docker/.env` | `postgresql+asyncpg://USER:PASS@/dbname?host=/var/run/pgbouncer&port=6432` |
| pgbouncer | `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` in `docker/.env` | discrete env vars |

The split exists because the edoburu entrypoint extracts the password
from `DATABASE_URL` **without URL-decoding it**. Passwords containing
URL-special chars (`%`, `$`, `@`, `:`) get written to `userlist.txt`
in URL-encoded form, while asyncpg (front-side) and PG (upstream)
both expect the decoded form. SCRAM auth fails on both legs.

By passing pgbouncer the discrete `DB_HOST` / `DB_PORT` / `DB_USER` /
`DB_PASSWORD` / `DB_NAME` env vars (mapped from `POSTGRES_*` in
`.env`), the entrypoint takes them as raw strings — no URL parsing,
no encoding artifacts.

If PG credentials change, update `POSTGRES_USER` / `POSTGRES_PASSWORD`
in `docker/.env` AND the embedded credentials in `DATABASE_URL` (the
latter URL-encoded as needed for the URL form).
````

(Section 5 "SCRAM-SHA-256 end to end" stays unchanged. Section 6
"TCP listener" stays unchanged.)

## Change 4 — VERSION

Update `VERSION`: 2.49.4 → 2.49.5

## Verify

````bash
# 1. Compose lints clean
docker compose -f docker/docker-compose.yml config > /dev/null

# 2. pgbouncer no longer references DATABASE_URL
! grep -E '^[[:space:]]+DATABASE_URL: \$\{' docker/docker-compose.yml

# 3. Discrete DB_* env vars are present
grep -q 'DB_HOST: hp1-postgres' docker/docker-compose.yml
grep -q 'DB_USER: \${POSTGRES_USER}' docker/docker-compose.yml
grep -q 'DB_PASSWORD: \${POSTGRES_PASSWORD}' docker/docker-compose.yml
grep -q 'DB_NAME: \${POSTGRES_DB' docker/docker-compose.yml

# 4. Carryovers from v2.49.4 still in place
grep -q 'AUTH_TYPE: scram-sha-256' docker/docker-compose.yml
grep -q 'LISTEN_PORT: "6432"' docker/docker-compose.yml
````

## Commit

````bash
git add -A
git commit -m "fix(infra): bypass DATABASE_URL parsing in pgbouncer (URL-encoding bug, v2.49.5)

The edoburu entrypoint extracts the password substring from DATABASE_URL
without URL-decoding it. Passwords with URL-special chars (%, \$, @, :)
end up in userlist.txt URL-encoded, while asyncpg (front-side) and PG
(upstream) both work with the decoded form. SCRAM fails on both legs.

Fix: pgbouncer now reads discrete DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/
DB_NAME env vars (mapped from existing POSTGRES_* values in docker/.env).
The entrypoint reads them as raw strings — no URL parsing, no encoding
artifacts. hp1_agent continues to use DATABASE_URL (asyncpg requires URL
form)."
git push origin main
````

## Deploy

After CC commits and CI image rebuild:

````bash
# On agent-01
cd /opt/hp1-agent
git pull origin main

# Confirm POSTGRES_PASSWORD is set in docker/.env
# (POSTGRES_USER and POSTGRES_DB already are — confirmed earlier)
grep '^POSTGRES_PASSWORD=' docker/.env || echo "MISSING — add it before recreating pgbouncer"

# If missing, add it with the real PG password (no URL-encoding,
# just the literal characters):
#   echo 'POSTGRES_PASSWORD=<real-password>' >> docker/.env

# Recreate pgbouncer to pick up new env block
cd docker
docker compose --env-file .env --profile pgbouncer up -d --force-recreate pgbouncer

# Verify userlist now has the raw password (not URL-encoded)
docker exec hp1_pgbouncer cat /etc/pgbouncer/userlist.txt
# Compare against the actual PG password — should match exactly.

# Health
docker compose ps pgbouncer
# Expect: (healthy)

# Real upstream auth test — should return one row
docker exec -e PGPASSWORD="$(grep ^POSTGRES_PASSWORD= .env | cut -d= -f2-)" \
  hp1_pgbouncer \
  psql -h /var/run/pgbouncer -p 6432 -U hp1 -d hp1_agent -c 'SELECT 1;'
````

If `SELECT 1;` returns one row, both SCRAM legs work and the
front-side flip for hp1_agent (`DATABASE_URL` to socket form) is the
next operator step.
