# PgBouncer Operator Guide

## Architecture

```
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
```

### How it works

- **Front-end (hp1_agent ↔ PgBouncer)**: Unix domain socket inside
  a shared Docker volume `pgbouncer-socket`. Auth type: `trust`.
  Security: only containers that mount the volume can reach the
  socket. There is no password.

- **Back-end (PgBouncer ↔ Postgres)**: TCP on `hp1-pg-net` (the
  Ansible-managed bridge). PgBouncer authenticates with the
  credential in `docker/.env` `DATABASE_URL`. The password lives
  exactly once, in that file (chmod 600, gitignored).

- **Pool mode**: `transaction`. Each Postgres transaction claims a
  backend connection, releases on commit/rollback. Backend
  utilisation capped at `default_pool_size=25` with `reserve_pool_size=5`
  burst capacity.

## Restrictions

These are hard requirements. If any aren't met, PgBouncer won't work
or won't be secure.

### 1. Single Docker host

PgBouncer and hp1_agent **must run on the same physical host.** Unix
domain sockets are kernel-level IPC; they don't traverse the network.
If you scale hp1_agent to multiple replicas across Swarm nodes, the
socket approach breaks immediately.

For multi-host: migrate to mTLS (recipe at the end of this doc).

### 2. Both containers must mount the same volume

The shared volume `pgbouncer-socket` is mounted at `/var/run/pgbouncer`
in both containers. The socket file is created inside that volume by
PgBouncer at startup. If hp1_agent doesn't mount the volume, it cannot
reach PgBouncer at all.

### 3. Permissions: socket mode 0777

The PgBouncer container runs as user `postgres` (UID 70). hp1_agent
runs as a different UID. To allow cross-UID access on the same socket,
PgBouncer creates the socket with mode `0777`.

This is acceptable because:
- The socket lives in a Docker volume, not on the host filesystem
- Only containers that mount the volume can reach it
- Inside that scope, restrictive permissions are unnecessary

If you tighten the threat model later (adversarial sidecars in the
same compose project), set `UNIX_SOCKET_GROUP` to a shared GID and
`UNIX_SOCKET_MODE: "0770"`.

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

Note (v2.49.7): the pgbouncer service does **not** set `env_file:` at
all. Compose interpolates `${POSTGRES_USER}` / `${POSTGRES_PASSWORD}`
from `docker/.env` via its standard project-default-env mechanism,
but does not bulk-import `.env` into the container.

This is required because the edoburu entrypoint unconditionally
re-parses `DATABASE_URL` when non-empty and overwrites the discrete
`DB_PASSWORD` with the URL-extracted (URL-encoded) substring,
breaking SCRAM. Compose's documented `environment` > `env_file`
precedence does **not** apply for empty/null values — empty-string
overrides fall through to env_file values
(github.com/docker/compose#11740, open since 2024). The only reliable
workaround is to not have env_file inherit `DATABASE_URL` into this
service at all.

Other services in the compose file that need `DATABASE_URL` (notably
hp1_agent) keep their `env_file: .env` and are unaffected.

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

### 6. PgBouncer admin requires the socket too

You can only reach the admin console from a container with the
volume mounted. There is no remote access:

```bash
docker exec -it hp1_pgbouncer \
  psql -h /var/run/pgbouncer -p 6432 -U pgbouncer pgbouncer
```

Then `SHOW POOLS;`, `SHOW STATS;`, `SHOW CLIENTS;`, `SHOW SERVERS;`,
`RELOAD;`, etc.

### 7. Startup ordering

When activating the pgbouncer profile, bring pgbouncer up first,
wait for the healthcheck to pass, then restart hp1_agent. The
Activate steps in `docker/README.md` do this in the right order.

If you swap DATABASE_URL to the socket form before pgbouncer is
running, hp1_agent will fail to start with a "no such file" error
on the socket path.

## Debugging

### "could not connect to server: No such file or directory"

The socket isn't there. Causes:

1. **PgBouncer container isn't running**:
   ```bash
   docker compose -f docker/docker-compose.yml --profile pgbouncer ps
   ```

2. **Volume not mounted in hp1_agent**:
   ```bash
   docker exec hp1_agent ls -la /var/run/pgbouncer
   ```
   Should show `.s.PGSQL.6432`.

3. **PgBouncer crashed before creating socket**:
   ```bash
   docker logs hp1_pgbouncer
   ```
   Look for config errors.

### "FATAL: password authentication failed for user 'hp1user'"

This is from the BACKEND connection (PgBouncer → Postgres). The
password in `DATABASE_URL` is wrong, or Postgres expects a different
auth method than what PgBouncer sends.

Verify by connecting directly to Postgres with the same creds:

```bash
psql -h 192.168.199.10 -p 5433 -U hp1user -d hp1_agent
```

If that fails, fix the password in `.env` first, then restart
pgbouncer.

### Pool stats look wrong

Inside hp1_pgbouncer:

```bash
psql -h /var/run/pgbouncer -p 6432 -U pgbouncer pgbouncer -c '
  SHOW POOLS;
  SHOW STATS;
  SHOW CLIENTS;
  SHOW SERVERS;
'
```

Healthy steady state:
- `SHOW POOLS`: `cl_active` ≤ `MAX_CLIENT_CONN`, `sv_active` ≤ `DEFAULT_POOL_SIZE`
- `SHOW CLIENTS`: most in state `idle`
- `SHOW SERVERS`: small number, mostly `idle`

If `cl_waiting > 0` for sustained periods, raise `DEFAULT_POOL_SIZE`
in the compose env block.

### Reload config without restarting

Most settings are reloadable via the admin console:

```bash
docker exec -it hp1_pgbouncer \
  psql -h /var/run/pgbouncer -p 6432 -U pgbouncer pgbouncer \
  -c 'RELOAD;'
```

Some settings (`listen_addr`, `unix_socket_dir`) require a full
container restart.

## Migration to mTLS (multi-host or scale-out)

When the single-host constraint becomes a blocker — splitting
hp1_agent across Swarm nodes, or a security audit demanding an
authenticated network channel between agent and pooler — migrate
to mTLS. Full recipe below.

### Prerequisites

- A CA you control (a one-shot self-signed CA is fine for homelab)
- OpenSSL on the host
- Ability to restart pgbouncer and all hp1_agent replicas

### Step 1 — Generate CA, server cert, client cert

In a working directory (`docker/pgbouncer/certs/`, gitignored):

```bash
mkdir -p docker/pgbouncer/certs
cd docker/pgbouncer/certs

# CA (5-year validity, homelab-appropriate)
openssl genrsa -out ca.key 4096
openssl req -new -x509 -days 1825 -key ca.key -out ca.crt \
  -subj "/CN=DEATHSTAR Internal CA"

# Server cert (PgBouncer side)
openssl genrsa -out server.key 4096
openssl req -new -key server.key -out server.csr \
  -subj "/CN=hp1_pgbouncer"
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key \
  -CAcreateserial -days 825 -out server.crt
chmod 600 server.key

# Client cert (hp1_agent side) — CN MUST match the PG username
openssl genrsa -out client.key 4096
openssl req -new -key client.key -out client.csr \
  -subj "/CN=hp1user"
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key \
  -CAcreateserial -days 825 -out client.crt
chmod 600 client.key
```

Add `docker/pgbouncer/certs/` to `.gitignore`.

### Step 2 — Update PgBouncer compose service

In the pgbouncer service block:

- Re-enable TCP port:
  ```yaml
  ports:
    - "6432:6432"
  ```

- Mount the cert directory:
  ```yaml
  volumes:
    - pgbouncer-socket:/var/run/pgbouncer
    - ./pgbouncer/certs:/etc/pgbouncer/certs:ro
  ```

- Replace the env block:
  ```yaml
  environment:
    DATABASE_URL: ${DATABASE_URL}
    POOL_MODE: transaction
    AUTH_TYPE: cert
    LISTEN_ADDR: "0.0.0.0"
    LISTEN_PORT: 6432
    CLIENT_TLS_SSLMODE: require
    CLIENT_TLS_CA_FILE: /etc/pgbouncer/certs/ca.crt
    CLIENT_TLS_CERT_FILE: /etc/pgbouncer/certs/server.crt
    CLIENT_TLS_KEY_FILE: /etc/pgbouncer/certs/server.key
    MAX_CLIENT_CONN: 200
    DEFAULT_POOL_SIZE: 25
    # ... capacity settings unchanged
  ```

The Unix socket can stay enabled in parallel for local debugging
(set both `UNIX_SOCKET_DIR` and `LISTEN_ADDR`) or be removed for
stricter isolation.

### Step 3 — Distribute client certs

For each hp1_agent host or replica:

- Place `ca.crt`, `client.crt`, `client.key` somewhere readable by
  the agent container — host volume mount or Docker secret
- Mount into the container at a known path (e.g. `/etc/pg-certs/`)
- Set permissions: `client.key` must be `chmod 600`

### Step 4 — Update hp1_agent's DATABASE_URL

```
DATABASE_URL=postgresql+asyncpg://hp1user@pgbouncer:6432/hp1_agent?sslmode=verify-full&sslrootcert=/etc/pg-certs/ca.crt&sslcert=/etc/pg-certs/client.crt&sslkey=/etc/pg-certs/client.key
```

No password. The cert IS the credential. The CN of the client cert
must match the username (`hp1user`).

### Step 5 — Cert rotation strategy

Pick one:

- **Manual**: regenerate certs annually, restart pgbouncer + all
  agents. Simple, fine for homelab.
- **step-ca + step-cli**: run `step-ca` as a service, certs auto-
  rotate every 24h. Significant ops uplift, proper for production.
- **cert-manager**: not applicable on Docker (k8s only).

For DEATHSTAR's likely scale, manual annual rotation is the right
trade.

### Step 6 — Verify mTLS is enforced

Try without the client cert:

```bash
psql -h hp1_pgbouncer -p 6432 -U hp1user hp1_agent
```

Should fail with a TLS handshake error. If it succeeds, cert auth
isn't enforced — check `CLIENT_TLS_SSLMODE: require`.

Try with cert:

```bash
psql "host=hp1_pgbouncer port=6432 user=hp1user dbname=hp1_agent \
      sslmode=verify-full sslrootcert=ca.crt sslcert=client.crt \
      sslkey=client.key"
```

Should succeed.

### Step 7 — Decommission the Unix socket (optional)

Once mTLS is verified working, remove socket mounts and the
`pgbouncer-socket` volume from compose. Set `UNIX_SOCKET_DIR=""`
in pgbouncer env to disable socket creation.

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

- **Trusted scope**: holders of valid client certs signed by your
  CA. Compromise of `client.key` requires re-issuing certs
  (revocation via CRL, or short-lived certs).
- **Untrusted scope**: anyone without a valid cert. PgBouncer
  rejects the TLS handshake before any Postgres protocol exchange.
- **Credential at rest**: the CA private key (`ca.key`, chmod 600,
  gitignored, ideally on a separate secure host or in a vault),
  server key, and per-host client keys.

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
