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

### 5. PgBouncer admin requires the socket too

You can only reach the admin console from a container with the
volume mounted. There is no remote access:

```bash
docker exec -it hp1_pgbouncer \
  psql -h /var/run/pgbouncer -p 6432 -U pgbouncer pgbouncer
```

Then `SHOW POOLS;`, `SHOW STATS;`, `SHOW CLIENTS;`, `SHOW SERVERS;`,
`RELOAD;`, etc.

### 6. Startup ordering

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
