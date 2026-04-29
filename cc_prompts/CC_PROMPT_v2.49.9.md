# CC PROMPT — v2.49.9 — docs: PGBOUNCER.md staleness fixes

## What this does

Cleans up stale text in `docker/PGBOUNCER.md` left over from earlier
versions in the v2.49.x arc. The runbook works correctly as-is —
operator just confirmed end-to-end on agent-01 — but several
descriptive sections still say "trust" auth or refer to
`DATABASE_URL` as the credential source for pgbouncer. Both are
wrong post-v2.49.4 (scram-sha-256) and post-v2.49.7 (POSTGRES_*).

Three corrections, all targeted edits — no section rewrites:

1. Architecture diagram + "How it works": front-end auth is
   scram-sha-256 (not trust); credential lives in POSTGRES_PASSWORD
   in .env (not DATABASE_URL).

2. Duplicate "### 5." heading (SCRAM-SHA-256 and TCP listener both
   numbered 5) renumbered: TCP listener → 6, admin → 7, ordering → 8.

3. "Threat model summary → Option G" section retitled and rewritten
   to reflect SCRAM-SHA-256 + Unix socket model (was: trust + Unix
   socket).

Version bump: 2.49.8 → 2.49.9

---

## Change 1 — `docker/PGBOUNCER.md` (Architecture diagram caption)

Find:

````markdown
hp1_agent ──┐
            │
            ▼ Unix socket (no auth — trust)
        ┌──────────┐
        │ PgBouncer│  ← shared volume: pgbouncer-socket
        └──────────┘
            │
            ▼ TCP + password (DATABASE_URL credential)
        ┌──────────┐
        │ Postgres │ (hp1-postgres on hp1-pg-net)
        └──────────┘
````

Replace with:

````markdown
hp1_agent ──┐
            │
            ▼ Unix socket + SCRAM-SHA-256
        ┌──────────┐
        │ PgBouncer│  ← shared volume: pgbouncer-socket
        └──────────┘
            │
            ▼ TCP + SCRAM-SHA-256
        ┌──────────┐
        │ Postgres │ (hp1-postgres on hp1-pg-net)
        └──────────┘
````

## Change 2 — `docker/PGBOUNCER.md` ("How it works" bullets)

Find:

````markdown
- **Front-end (hp1_agent ↔ PgBouncer)**: Unix domain socket inside
  a shared Docker volume `pgbouncer-socket`. Auth type: `trust`.
  Security: only containers that mount the volume can reach the
  socket. There is no password.

- **Back-end (PgBouncer ↔ Postgres)**: TCP on `hp1-pg-net` (the
  Ansible-managed bridge). PgBouncer authenticates with the
  credential in `docker/.env` `DATABASE_URL`. The password lives
  exactly once, in that file (chmod 600, gitignored).
````

Replace with:

````markdown
- **Front-end (hp1_agent ↔ PgBouncer)**: Unix domain socket inside
  a shared Docker volume `pgbouncer-socket`. Auth type:
  `scram-sha-256`. hp1_agent sends the password (URL-encoded inside
  `DATABASE_URL`); pgbouncer verifies SCRAM against the plaintext
  in its in-container userlist.txt. Volume isolation is defence
  in depth — only containers that mount `pgbouncer-socket` can
  reach the socket at all.

- **Back-end (PgBouncer ↔ Postgres)**: TCP on `hp1-pg-net` (the
  Ansible-managed bridge). PgBouncer authenticates with the
  credential in `docker/.env` `POSTGRES_PASSWORD`. The same
  plaintext is read by both legs of SCRAM (front-side verify,
  back-side proof) — it lives exactly once on disk, in `.env`
  (chmod 600, gitignored).
````

## Change 3 — `docker/PGBOUNCER.md` (duplicate `### 5.` headings)

There are currently two sections numbered "### 5.". Renumber the
TCP listener section to 6, admin section to 7, ordering section to 8.

Find:

````markdown
### 5. TCP listener is active inside the container
````

Replace with:

````markdown
### 6. TCP listener is active inside the container
````

Find:

````markdown
### 6. PgBouncer admin requires the socket too
````

Replace with:

````markdown
### 7. PgBouncer admin requires the socket too
````

Find:

````markdown
### 7. Startup ordering
````

Replace with:

````markdown
### 8. Startup ordering
````

## Change 4 — `docker/PGBOUNCER.md` (Threat model summary section)

The "Option G" / "Option H" labels were placeholders from the
original design exploration. Retitle to plain language and update
"Option G" body to reflect SCRAM, not trust.

Find:

````markdown
## Threat model summary

### Option G (current — Unix socket + trust)

- **Trusted scope**: the agent-01 host. Anyone with shell access to
  agent-01 plus Docker permissions can reach the socket via
  `/var/lib/docker/volumes/agent_pgbouncer-socket/_data/`.
- **Untrusted scope**: the LAN, the internet, other hosts on
  hp1-pg-net. None can reach PgBouncer (no TCP listener).
- **Credential at rest**: the Postgres password in `docker/.env`
  (chmod 600, gitignored, Ansible-managed).

### Option H (future — mTLS)
````

Replace with:

````markdown
## Threat model summary

### Current — Unix socket + SCRAM-SHA-256

- **Trusted scope**: the agent-01 host. Anyone with shell access to
  agent-01 plus Docker permissions can reach the socket via
  `/var/lib/docker/volumes/docker_pgbouncer-socket/_data/`.
  Inside the docker network, anyone on the `hp1-pg-net` bridge can
  also reach pgbouncer's in-container TCP listener (no host port
  exposed; reachable only from `hp1_agent` and `hp1-postgres`).
- **Untrusted scope**: the LAN, the internet. Neither can reach
  PgBouncer (no host TCP port).
- **Auth boundary**: SCRAM-SHA-256 on both legs — front-side
  (hp1_agent → pgbouncer via socket) and back-side (pgbouncer →
  PG via TCP). PG never sees plaintext on the wire; pgbouncer's
  userlist.txt holds plaintext only inside the container's
  writable layer (no host filesystem, no named volume).
- **Credential at rest**: the Postgres password in `docker/.env`
  as `POSTGRES_PASSWORD` and embedded URL-encoded inside
  `DATABASE_URL` (chmod 600, gitignored, Ansible-managed). To
  rotate, update both fields.

### Future — mTLS (multi-host)
````

## Change 5 — VERSION

Update `VERSION`: 2.49.8 → 2.49.9

## Verify

````bash
# 1. No more "trust" references describing the runtime model
! grep -E '(Unix socket \(no auth — trust\)|Auth type: `trust`)' docker/PGBOUNCER.md

# 2. SCRAM language present in architecture and bullets
grep -q 'SCRAM-SHA-256$' docker/PGBOUNCER.md
grep -q 'Auth type:' docker/PGBOUNCER.md
grep -q 'scram-sha-256' docker/PGBOUNCER.md

# 3. Section numbering is clean — exactly one `### 5.`
test "$(grep -cE '^### 5\.' docker/PGBOUNCER.md)" -eq 1
test "$(grep -cE '^### 6\.' docker/PGBOUNCER.md)" -eq 1
test "$(grep -cE '^### 7\.' docker/PGBOUNCER.md)" -eq 1
test "$(grep -cE '^### 8\.' docker/PGBOUNCER.md)" -eq 1

# 4. Old Option G/H labels gone, plain language replaces them
! grep -q 'Option G' docker/PGBOUNCER.md
! grep -q 'Option H' docker/PGBOUNCER.md
grep -q 'Current — Unix socket + SCRAM-SHA-256' docker/PGBOUNCER.md
grep -q 'Future — mTLS' docker/PGBOUNCER.md
````

## Commit

````bash
git add -A
git commit -m "docs: PGBOUNCER.md staleness fixes (v2.49.9)

Three targeted corrections — no section rewrites:

1. Architecture diagram caption + How-it-works bullets: front-side
   auth is scram-sha-256 (not trust), credential is POSTGRES_PASSWORD
   (not DATABASE_URL). The runbook itself was already correct, but
   the descriptive paragraphs above it were left over from v2.49.1
   and didn't survive the v2.49.4 → v2.49.7 chain.

2. Duplicate '### 5.' headings (SCRAM-SHA-256 and TCP listener):
   renumbered TCP→6, admin→7, ordering→8.

3. Threat-model section's 'Option G/H' labels (placeholder names from
   the design exploration phase) replaced with plain language.
   'Option G' body rewritten for the actual SCRAM model — explicitly
   notes plaintext lives only in container writable layer and on
   .env at rest."
git push origin main
````

## Deploy

Docs-only. No image rebuild, no recreate needed.

````bash
# On agent-01
cd /opt/hp1-agent
git pull origin main
cat VERSION                                  # should now read 2.49.9
````
