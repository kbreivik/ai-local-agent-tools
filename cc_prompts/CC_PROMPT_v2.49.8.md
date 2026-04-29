# CC PROMPT — v2.49.8 — docs+infra: pgbouncer cutover runbook + sidecar/depends_on hardening

## What this does

Two related cleanups now that pgbouncer auth is finally working:

### Part 1 — Pgbouncer cutover runbook (PGBOUNCER.md)

After v2.49.7 the pgbouncer service runs and authenticates correctly,
but hp1_agent still connects directly to hp1-postgres. The whole point
of the v2.49.x arc was to put pgbouncer in front of hp1_agent. This
adds a clean operator runbook for that flip — including the `$$`
escaping rule, rollback, and a footnote on the saga that produced
the current shape.

### Part 2 — Sidecar/depends_on hardening (docker-compose.yml)

The auto-update / re-pull sidecar pattern in `dashboard.py`
(`_restart_self_container`) recreates hp1_agent via:

```
docker compose --project-name docker -f /compose/docker-compose.yml \
  --env-file /compose/.env up -d --force-recreate hp1_agent
```

Two concerns once hp1_agent uses the pgbouncer socket:

1. **No depends_on declared.** If pgbouncer is stopped/unhealthy when
   the sidecar recreates hp1_agent, the agent will crash-loop on the
   missing socket. Adding `depends_on: pgbouncer` (with `required:
   false` so the dep is ignored when the profile is inactive) makes
   compose verify pgbouncer is healthy before starting hp1_agent.

2. **Profile activation across recreate.** The sidecar runs
   `up -d --force-recreate hp1_agent` without `--profile pgbouncer`.
   That's fine for hp1_agent itself (always-on, no profile), but it
   means a sidecar-driven recreate cannot bring pgbouncer along if
   it was stopped. Documenting this is enough; auto-recovery of
   pgbouncer is out of scope.

### .env.example footnote

Adds the single most important gotcha — `$$ → $` interpolation
reduction — to `.env.example` so future operators don't repeat the
v2.49.5–v2.49.7 saga.

Version bump: 2.49.7 → 2.49.8

---

## Change 1 — `docker/PGBOUNCER.md`

Append a new section at the end of the file (after the "Migration to
mTLS" section that's already there). Find the very end of the file
and append:

````markdown

---

## Operator runbook: cutting hp1_agent over to pgbouncer

After the pgbouncer profile is up, healthy, and `SHOW POOLS;` works,
hp1_agent still connects directly to PG until you flip its
`DATABASE_URL`. This section is the one-shot recipe.

### Pre-flight

1. Pgbouncer container is healthy:
   ```bash
   docker compose -f docker/docker-compose.yml --profile pgbouncer ps pgbouncer
   docker exec hp1_pgbouncer test -S /var/run/pgbouncer/.s.PGSQL.6432 && echo OK
   ```
2. Upstream auth works — should return one row:
   ```bash
   docker exec hp1_pgbouncer sh -c \
     'PGPASSWORD="${DB_PASSWORD}" psql -h /var/run/pgbouncer -p 6432 \
      -U ${DB_USER} -d ${DB_NAME} -c "SELECT 1;"'
   ```
3. hp1_agent is currently healthy on the direct PG connection. (Don't
   flip if hp1_agent is already broken — debug that first.)

### The flip

Edit `docker/.env` and change `DATABASE_URL` from the direct form to
the socket form:

```diff
-DATABASE_URL=postgresql+asyncpg://USER:PASS@hp1-postgres:5432/hp1_agent
+DATABASE_URL=postgresql+asyncpg://USER:PASS@/hp1_agent?host=/var/run/pgbouncer&port=6432
```

URL-encoding rules for `PASS`:
- `$` → `%24` (per char)
- `%` → `%25` (per char)
- `@` → `%40` (per char)
- `:` → `%3A` (per char)

The `POSTGRES_PASSWORD` line below stays the same (literal password
with `$$` → `$$$$` escaping for compose interpolation; see
`.env.example` for details).

Then recreate hp1_agent:

```bash
cd /opt/hp1-agent/docker
docker compose --env-file .env up -d --force-recreate hp1_agent
docker logs hp1_agent --tail 30
docker compose ps hp1_agent
```

Expect `Up X (healthy)` and the usual startup banner. The agent's
`/api/health` should respond within ~10s.

### Verification

The single most useful check — does the agent's pool actually use
pgbouncer? Look at pgbouncer's client list:

```bash
docker exec hp1_pgbouncer sh -c \
  'psql -h /var/run/pgbouncer -p 6432 -U pgbouncer pgbouncer \
   -c "SHOW CLIENTS;"'
```

You should see entries with `database=hp1_agent`, `user=hp1`,
`addr=unix`. If `addr=unix` is present, hp1_agent is genuinely
talking through the socket.

### Rollback

If hp1_agent crash-loops or pool stats look wrong, revert to direct
PG with one line edit and a recreate:

```bash
cd /opt/hp1-agent/docker
sed -i 's|@/hp1_agent?host=/var/run/pgbouncer&port=6432|@hp1-postgres:5432/hp1_agent|' .env
docker compose --env-file .env up -d --force-recreate hp1_agent
```

(Optional) Stop pgbouncer entirely:
```bash
docker compose --profile pgbouncer down
```

The `pgbouncer-socket` volume mount on hp1_agent stays; it's a
harmless empty directory when pgbouncer isn't running.

### Saga footnote (v2.49.0–v2.49.7, 2026-04-29)

The path to this working configuration produced eight versions in a
single afternoon. The shape of the final design encodes lessons from
each:

| Version | What was learned |
|---|---|
| v2.49.0 | First TCP+md5 design — superseded |
| v2.49.1 | Unix socket + trust — image tag was bogus |
| v2.49.2 | Real edoburu tag is `vX.Y.Z-pN`, not `X.Y.Z` |
| v2.49.3 | Misdiagnosis: split URL split — wrong fix to wrong problem |
| v2.49.4 | PG14+ rejects md5 → `AUTH_TYPE=scram-sha-256` |
| v2.49.5 | Discrete `DB_*` vars to bypass URL-encoded password |
| v2.49.6 | `DATABASE_URL: ""` to suppress entrypoint clobber — didn't work |
| v2.49.7 | Drop `env_file:` from pgbouncer service entirely |
| v2.49.8 | (this) — runbook + depends_on + escape footnote |

The non-obvious traps, in order of how-much-time-they-cost:

1. **edoburu's entrypoint always runs `parse_url(DATABASE_URL)`** when
   that var is non-empty, even if you provided discrete `DB_PASSWORD`
   yourself. The discrete vars get clobbered.
2. **Compose's `environment: { VAR: "" }` does not override `env_file`**
   for empty/null values. Open issue docker/compose#11740 since 2024.
3. **Compose `${VAR}` interpolation reduces `$$` to `$`** during YAML
   parsing. Passwords with literal `$$` need `$$$$` in `.env`.
4. **edoburu writes md5 hashes to userlist when AUTH_TYPE=trust** —
   the source-of-truth branch is in entrypoint.sh and only `plain`
   and `scram-sha-256` write plaintext.
5. **PG14+ stores SCRAM verifiers** and rejects md5-hashed login
   attempts with `wrong password type`.
````

## Change 2 — `docker/docker-compose.yml`

Find the `hp1_agent` service block. Locate its existing
`depends_on:` (if any) — most likely there is no depends_on on
hp1_agent yet. If there IS a depends_on block, add the pgbouncer
entry to it; if there ISN'T, add a fresh one in a sensible spot
(typically right after `image:` or before `volumes:`).

Insert this block (the right spot is right before the `volumes:`
section of `hp1_agent`):

````yaml
    # v2.49.8 — pgbouncer is profile-gated, so this dependency is
    # marked required: false. When the pgbouncer profile is inactive,
    # compose silently ignores the dep. When the profile IS active,
    # compose waits for pgbouncer's healthcheck to pass before
    # (re)creating hp1_agent — preventing the sidecar auto-update
    # from racing pgbouncer at recreate time.
    depends_on:
      pgbouncer:
        condition: service_healthy
        required: false
````

## Change 3 — `docker/.env.example`

Find the `DATABASE_URL` block (still post-v2.49.6 form because
v2.49.7 didn't touch this file). Replace the existing comment header
in front of `POSTGRES_PASSWORD`-related entries with a clear gotcha
warning. Find the existing `POSTGRES_PASSWORD=` example line; insert
THIS comment immediately above it:

````bash

# ── PostgreSQL credentials ─────────────────────────────────────────
# Used by hp1_agent (via DATABASE_URL above), the dev-profile postgres
# service, AND the pgbouncer profile (which reads them as
# DB_USER/DB_PASSWORD/DB_NAME directly to bypass URL-encoding bugs in
# the edoburu entrypoint's URL parser).
#
# ⚠️  COMPOSE INTERPOLATION GOTCHA — passwords with literal '$' chars
#
# docker compose reduces '$$' → '$' once during ${VAR} interpolation
# in compose YAML. So a password containing literal '$$' must be
# written as '$$$$' in .env to survive interpolation. Example:
#
#   real password:    Jw%ZY%F$$Bz2Fn2L      (contains $$)
#   .env value:       POSTGRES_PASSWORD=Jw%ZY%F$$$$Bz2Fn2L
#   in container:     DB_PASSWORD=Jw%ZY%F$$Bz2Fn2L
#
# Single '$' chars need '$$' in .env. Other URL-special chars
# (%, @, :) pass through unchanged in .env but must be URL-encoded
# inside DATABASE_URL above (e.g. '%' as '%25', '$' as '%24').
````

## Change 4 — VERSION

Update `VERSION`: 2.49.7 → 2.49.8

## Verify

````bash
# 1. Compose lints clean
docker compose -f docker/docker-compose.yml config > /dev/null

# 2. depends_on with required: false present on hp1_agent
grep -A 4 'depends_on:' docker/docker-compose.yml | grep -q 'required: false'

# 3. Runbook section present in PGBOUNCER.md
grep -q 'Operator runbook: cutting hp1_agent over to pgbouncer' docker/PGBOUNCER.md
grep -q 'Saga footnote' docker/PGBOUNCER.md

# 4. .env.example has the $$ gotcha warning
grep -q 'COMPOSE INTERPOLATION GOTCHA' docker/.env.example

# 5. Carryovers from earlier prompts still in place
grep -q 'AUTH_TYPE: scram-sha-256' docker/docker-compose.yml
grep -q 'LISTEN_PORT: "6432"' docker/docker-compose.yml
! grep -q 'env_file:' <(awk '/^  pgbouncer:/{flag=1} /^  [a-z_]+:/ && NR>1 && !/pgbouncer/{flag=0} flag' docker/docker-compose.yml)
````

## Commit

````bash
git add -A
git commit -m "docs+infra: pgbouncer cutover runbook + sidecar hardening (v2.49.8)

After v2.49.7 the pgbouncer profile runs and authenticates correctly
but hp1_agent still connects direct to PG. This adds the cutover
runbook (operator-facing) plus two infra hardenings.

PGBOUNCER.md:
- 'Operator runbook' section: pre-flight checks, the .env flip,
  verification via SHOW CLIENTS, rollback, and saga footnote
  documenting v2.49.0-v2.49.7 lessons.

docker-compose.yml:
- hp1_agent.depends_on.pgbouncer with required: false. Ignored when
  the pgbouncer profile is inactive; when active, ensures the
  sidecar auto-update doesn't race pgbouncer at recreate time.

.env.example:
- Footnote on the \$\$ → \$ compose interpolation gotcha — by far
  the most likely future trap for any operator with a password
  containing literal dollar signs.

Sidecar/auto-update analysis (no code changes needed):
- _restart_self_container() in api/routers/dashboard.py runs
  'docker compose ... up -d --force-recreate hp1_agent' WITHOUT
  --profile pgbouncer. This is correct: pgbouncer (profile-gated,
  always-on once started) is not touched by the recreate, so its
  pool state survives unaffected.
- The pgbouncer-socket volume is bind-mounted on hp1_agent
  unconditionally (not profile-gated on the agent side), so the
  socket is reachable across recreates.
- depends_on with required:false provides health-gating without
  forcing pgbouncer activation."
git push origin main
````

## Deploy

After CC commits, on agent-01:

````bash
cd /opt/hp1-agent
git pull origin main

# This prompt is doc + compose-additive. No image rebuild needed.
# But hp1_agent compose definition changed (depends_on added), so a
# recreate IS needed for the new dependency to register. Pgbouncer
# profile is currently active, so this also exercises the new
# health-gate.
cd docker
docker compose --env-file .env --profile pgbouncer up -d hp1_agent

# hp1_agent should come back up; if pgbouncer is healthy, no delay.
docker compose ps
docker logs hp1_agent --tail 20
````

The cutover (flipping `DATABASE_URL` to the socket form) is
**deliberately separate** from this prompt — it's an operator
decision per the runbook in `PGBOUNCER.md`, not an automated change.
Do that when ready.
