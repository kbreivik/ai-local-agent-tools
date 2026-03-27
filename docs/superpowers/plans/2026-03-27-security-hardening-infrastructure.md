# Security Hardening — Infrastructure Fixes

**Date:** 2026-03-27
**Version target:** 1.10.22 (Bundles A/B/C land at 1.10.19/20/21; this plan at 1.10.22)
**Branch:** main

---

## Goal

Close three infrastructure-level security gaps in HP1-AI-Agent:

- **P1 #3 — DB path portability**: Both `api/db/base.py` and `api/db/migrate_sqlite.py` hard-code a Windows absolute path (`D:/claude_code/...`) as the SQLite fallback. This silently fails inside Docker where no `D:/` drive exists. Replace with a `__file__`-relative path so the default works on any host OS.
- **P1 #10 — SSH host key verification**: `api/routers/ansible.py` uses `paramiko.AutoAddPolicy()`, which silently accepts any SSH host key and exposes the agent to man-in-the-middle attacks. Replace with `WarningPolicy()` with an env-var opt-out.
- **P1 #11 — Docker TCP 2375**: `docker/docker-compose.yml` hard-codes `DOCKER_HOST=tcp://192.168.199.21:2375` — plain, unauthenticated TCP. Convert to an env-var interpolation and document the TLS migration path.

## Architecture

- FastAPI backend (Python 3.13) — `api/` tree
- All tool functions sync; FastAPI route handlers may be async
- Paramiko for SSH connectivity in `api/routers/ansible.py`
- Docker daemon accessed via `DOCKER_HOST` env var in both compose and `api/collectors/swarm.py`
- Test suite: `pytest tests/ -x -q` from project root
  - 17 tests currently pass; 1 pre-existing fail in `test_collectors_proxmox_vms.py` — expected throughout

## Tech Stack

- `pathlib.Path` (stdlib) — for portable DB path resolution
- `paramiko.WarningPolicy` — stdlib Paramiko class, already a dependency
- `logging` (stdlib) — for SSH host key disable warning
- `os.environ` (stdlib) — env-var opt-out for SSH check and DOCKER_HOST
- No new third-party dependencies introduced

## File Map

| File | Bundle | Changes |
|------|--------|---------|
| `api/db/base.py` | A | Replace hard-coded Windows fallback with `__file__`-relative path |
| `api/db/migrate_sqlite.py` | A | Same fix — identical fallback expression |
| `tests/test_db_path.py` | A | New — TDD test: verify DB path resolves portably without env vars set |
| `api/routers/ansible.py` | B | Replace `AutoAddPolicy` with `WarningPolicy`; add `DISABLE_HOST_KEY_CHECK` opt-out |
| `docker/docker-compose.yml` | C | Parameterise `DOCKER_HOST`; add TLS pass-through env vars and comment block |
| `docker/.env.example` | C | Document TLS variables (`DOCKER_TLS_VERIFY`, `DOCKER_CERT_PATH`) |
| `VERSION` | — | Bump to `1.10.22` in final commit |

---

## Bundle A — DB path portability

### Context

`api/db/base.py` line 18–21:
```python
_SQLITE_PATH = Path(os.environ.get(
    "SQLITE_PATH",
    os.environ.get("DB_PATH", "D:/claude_code/FAJK/HP1-AI-Agent-v1/data/hp1_agent.db")
))
```

`api/db/migrate_sqlite.py` line 21–24 (identical pattern):
```python
_SQLITE_PATH = Path(os.environ.get(
    "SQLITE_PATH",
    os.environ.get("DB_PATH", "D:/claude_code/FAJK/HP1-AI-Agent-v1/data/hp1_agent.db"),
))
```

**File depth analysis:**
- `api/db/base.py` is at depth `<project_root>/api/db/base.py` — three levels below root: `base.py` → `db/` → `api/` → project root. So `Path(__file__).parent.parent.parent` resolves to the project root. Confirmed: `parent` = `api/db/`, `parent.parent` = `api/`, `parent.parent.parent` = project root.
- `api/db/migrate_sqlite.py` is at the same depth (`api/db/migrate_sqlite.py`), so the same `.parent.parent.parent` count applies.

**Replacement expression (same for both files):**
```python
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_SQLITE_PATH = Path(os.environ.get(
    "SQLITE_PATH",
    os.environ.get("DB_PATH", str(_PROJECT_ROOT / "data" / "hp1_agent.db"))
))
```

This resolves correctly on Linux (Docker), macOS, and Windows regardless of where the repo is cloned.

### Task A1 — Write failing test first (TDD)

**File:** `tests/test_db_path.py` (new)

**Steps:**

- [ ] **A1.1** Create `tests/test_db_path.py`:

  ```python
  """
  TDD: verify SQLite path falls back to a __file__-relative path, not an absolute
  Windows path, when neither SQLITE_PATH nor DB_PATH env vars are set.
  """
  import os
  import importlib
  from pathlib import Path
  import pytest


  def _reload_base():
      """Reload api.db.base with clean env (no SQLITE_PATH / DB_PATH)."""
      import api.db.base as mod
      return importlib.reload(mod)


  def test_db_path_no_env_vars(monkeypatch):
      """Without env vars, _SQLITE_PATH must be relative to the project root."""
      monkeypatch.delenv("SQLITE_PATH", raising=False)
      monkeypatch.delenv("DB_PATH", raising=False)
      monkeypatch.delenv("DATABASE_URL", raising=False)

      mod = _reload_base()
      path = mod._SQLITE_PATH

      # Must end with data/hp1_agent.db (using posix-style comparison)
      assert path.parts[-1] == "hp1_agent.db", f"Wrong filename: {path}"
      assert path.parts[-2] == "data", f"Wrong parent dir: {path}"

      # Must NOT contain any Windows drive letter or absolute Windows path component
      path_str = str(path)
      assert "D:/claude_code" not in path_str, (
          f"DB path still contains hard-coded Windows path: {path_str}"
      )
      assert "C:/claude_code" not in path_str, (
          f"DB path contains hard-coded Windows path: {path_str}"
      )

      # Path must be resolvable — parent directory exists (project root / data)
      # (we don't create the file, just confirm the parent is reachable)
      project_root = Path(__file__).parent.parent
      expected = project_root / "data" / "hp1_agent.db"
      assert path == expected, (
          f"Expected {expected}, got {path}"
      )


  def test_db_path_env_sqlite_path_override(monkeypatch, tmp_path):
      """SQLITE_PATH env var must override the default."""
      custom = tmp_path / "custom.db"
      monkeypatch.setenv("SQLITE_PATH", str(custom))
      monkeypatch.delenv("DB_PATH", raising=False)
      monkeypatch.delenv("DATABASE_URL", raising=False)

      mod = _reload_base()
      assert mod._SQLITE_PATH == custom, (
          f"SQLITE_PATH override not respected: {mod._SQLITE_PATH}"
      )


  def test_db_path_env_db_path_fallback(monkeypatch, tmp_path):
      """DB_PATH env var must be used when SQLITE_PATH is unset."""
      custom = tmp_path / "fallback.db"
      monkeypatch.delenv("SQLITE_PATH", raising=False)
      monkeypatch.setenv("DB_PATH", str(custom))
      monkeypatch.delenv("DATABASE_URL", raising=False)

      mod = _reload_base()
      assert mod._SQLITE_PATH == custom, (
          f"DB_PATH fallback not respected: {mod._SQLITE_PATH}"
      )
  ```

- [ ] **A1.2** Run the new test file — expect `test_db_path_no_env_vars` to **fail** (confirms the hard-coded path is present before the fix):
  ```bash
  pytest tests/test_db_path.py -v
  ```
  Expected: `test_db_path_no_env_vars` FAILED; other two tests PASS (env overrides already work).

---

### Task A2 — Fix `api/db/base.py`

**File:** `api/db/base.py`

**Steps:**

- [ ] **A2.1** Open `api/db/base.py`. The `Path` import already exists at line 10. Locate the `_SQLITE_PATH` assignment at lines 18–21:

  ```python
  _SQLITE_PATH = Path(os.environ.get(
      "SQLITE_PATH",
      os.environ.get("DB_PATH", "D:/claude_code/FAJK/HP1-AI-Agent-v1/data/hp1_agent.db")
  ))
  ```

  Replace it with:

  ```python
  _PROJECT_ROOT = Path(__file__).parent.parent.parent  # api/db/base.py → api/db/ → api/ → project root
  _SQLITE_PATH = Path(os.environ.get(
      "SQLITE_PATH",
      os.environ.get("DB_PATH", str(_PROJECT_ROOT / "data" / "hp1_agent.db"))
  ))
  ```

- [ ] **A2.2** Verify syntax:
  ```bash
  python -m py_compile api/db/base.py
  ```

---

### Task A3 — Fix `api/db/migrate_sqlite.py`

**File:** `api/db/migrate_sqlite.py`

**Steps:**

- [ ] **A3.1** Open `api/db/migrate_sqlite.py`. The `Path` import already exists at line 14. Locate the `_SQLITE_PATH` assignment at lines 21–24:

  ```python
  _SQLITE_PATH = Path(os.environ.get(
      "SQLITE_PATH",
      os.environ.get("DB_PATH", "D:/claude_code/FAJK/HP1-AI-Agent-v1/data/hp1_agent.db"),
  ))
  ```

  Replace it with:

  ```python
  _PROJECT_ROOT = Path(__file__).parent.parent.parent  # api/db/migrate_sqlite.py → api/db/ → api/ → project root
  _SQLITE_PATH = Path(os.environ.get(
      "SQLITE_PATH",
      os.environ.get("DB_PATH", str(_PROJECT_ROOT / "data" / "hp1_agent.db"))
  ))
  ```

- [ ] **A3.2** Verify syntax:
  ```bash
  python -m py_compile api/db/migrate_sqlite.py
  ```

---

### Task A4 — Verify tests pass

- [ ] **A4.1** Run the DB path test — all three tests must now pass:
  ```bash
  pytest tests/test_db_path.py -v
  ```
  Expected: 3 PASSED.

- [ ] **A4.2** Run full suite — baseline unchanged:
  ```bash
  pytest tests/ -x -q
  ```
  Expected: pre-existing proxmox collector failure only; all other tests pass.

- [ ] **A4.3** Pre-commit check — confirm no new absolute Windows paths:
  ```bash
  grep -rn "D:/claude_code\|C:/claude_code" api/ tests/
  ```
  Expected: no output.

- [ ] **A4.4** Commit and push:
  ```
  fix(db): replace hard-coded Windows DB path fallback with __file__-relative path
  ```
  ```bash
  git push
  ```

---

## Bundle B — SSH host key verification

### Context

`api/routers/ansible.py` line 102:
```python
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
```

`AutoAddPolicy` silently adds any unknown host key to the known-hosts store without warning the user. This prevents detection of MITM attacks. Paramiko provides `WarningPolicy` as a safer alternative — it still connects (acceptable for a homelab operator who has just configured a new VM) but emits a `WARNING` log message so the key mismatch is visible.

The same file also sets `ANSIBLE_HOST_KEY_CHECKING=False` at line 136 for Ansible playbooks. This is separate from the Paramiko SSH client used by the `/test-connection` endpoint. The Ansible env var is out of scope for this plan.

**Opt-out design:**
- Env var: `DISABLE_HOST_KEY_CHECK` (string, case-insensitive)
- If `DISABLE_HOST_KEY_CHECK=true` → use `AutoAddPolicy()` (original behaviour, for bootstrapping new VMs)
- If unset or any other value → use `WarningPolicy()` (new default)
- A startup-time log line at WARNING level is emitted when the opt-out is active

### Task B1 — Update `api/routers/ansible.py`

**File:** `api/routers/ansible.py`

**Steps:**

- [ ] **B1.1** Open `api/routers/ansible.py`. Locate the `test_connection` route starting at line 87. Find the Paramiko block at lines 100–102:

  ```python
  import paramiko
  client = paramiko.SSHClient()
  client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
  ```

  Replace those three lines with:

  ```python
  import paramiko
  client = paramiko.SSHClient()
  _disable_hkc = os.environ.get("DISABLE_HOST_KEY_CHECK", "").lower() == "true"
  if _disable_hkc:
      log.warning(
          "SECURITY: SSH host key checking is disabled (DISABLE_HOST_KEY_CHECK=true). "
          "Only use this option on isolated lab networks."
      )
      client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
  else:
      client.set_missing_host_key_policy(paramiko.WarningPolicy())
  ```

  The `os` module is already imported at line 3. The `log` logger is already defined at line 15.

- [ ] **B1.2** Verify syntax:
  ```bash
  python -m py_compile api/routers/ansible.py
  ```

- [ ] **B1.3** Run full test suite — no change expected (ansible router has no automated tests in the current suite):
  ```bash
  pytest tests/ -x -q
  ```

- [ ] **B1.4** Commit and push:
  ```
  fix(ansible): replace AutoAddPolicy with WarningPolicy; add DISABLE_HOST_KEY_CHECK opt-out
  ```
  ```bash
  git push
  ```

### Task B2 — Manual verification checklist

These steps require a running agent instance with network access to a Swarm manager host.

- [ ] **B2.1 — Default (WarningPolicy) path:**
  1. Ensure `DISABLE_HOST_KEY_CHECK` is unset or empty in the container environment.
  2. Call `POST /api/ansible/test-connection` (with valid auth token) pointing at a manager host whose key is NOT in the container's `~/.ssh/known_hosts`.
  3. Verify: connection succeeds (or fails due to auth, not due to a host key exception).
  4. Check container logs: look for `WARNING:api.routers.ansible:...` lines from Paramiko's WarningPolicy (the log line is emitted by Paramiko internals, not our code, at logger name `paramiko.transport`).
  5. Verify no `SECURITY: SSH host key checking is disabled` line appears in the logs.

- [ ] **B2.2 — Opt-out (AutoAddPolicy) path:**
  1. Set `DISABLE_HOST_KEY_CHECK=true` in the container environment and restart.
  2. Check startup logs: `SECURITY: SSH host key checking is disabled (DISABLE_HOST_KEY_CHECK=true).` must appear when the endpoint is called.
  3. Verify connection still succeeds for unknown hosts.
  4. Remove `DISABLE_HOST_KEY_CHECK` from env and restart before going to production.

- [ ] **B2.3 — Known-hosts note:** Full known-hosts file management (pre-populating `/home/agent/.ssh/known_hosts` with Swarm manager host keys via Ansible) is the recommended next step but is out of scope for this plan. When implemented, `WarningPolicy` will suppress the warning for known hosts automatically.

---

## Bundle C — Docker TCP 2375 hardening

### Context

`docker/docker-compose.yml` line 123:
```yaml
- DOCKER_HOST=${DOCKER_HOST:-tcp://192.168.199.21:2375}
```

The `${DOCKER_HOST:-...}` syntax is already present, which is correct — the env var interpolation is already there. However, the comment block at lines 120–122 only documents the plain-TCP requirement; it does not document the TLS upgrade path or make TLS variables available as pass-through environment entries.

`docker/.env.example` lines 45–55 already documents `DOCKER_HOST` with a port 2375 value and includes `DOCKER_ENGINE_HOST` / SSH-tunnel variables. It does not document TLS variables (`DOCKER_TLS_VERIFY`, `DOCKER_CERT_PATH`).

`api/collectors/swarm.py` line 36: `host = os.environ.get("DOCKER_HOST", "npipe:////./pipe/docker_engine")` — reads from env, does not hard-code port 2375. No Python-level change needed.

`mcp_server/tools/skills/discovery.py` line 27 and `mcp_server/tools/skills/fingerprints.py` line 53: reference port 2375 as a probe target during environment discovery (fingerprinting). These are legitimate discovery probes, not connection defaults — out of scope for this plan.

### Task C1 — Update `docker/docker-compose.yml`

**File:** `docker/docker-compose.yml`

**Steps:**

- [ ] **C1.1** Open `docker/docker-compose.yml`. Locate lines 119–126 in the `hp1_agent` service `environment` block:

  ```yaml
      environment:
        # agent-01 is not in the Swarm — manage manager-01 via Docker TCP API.
        # Override here so it applies even if not set in .env.
        # Port 2375 = plain TCP (ensure dockerd on manager-01 has -H tcp://0.0.0.0:2375).
        - DOCKER_HOST=${DOCKER_HOST:-tcp://192.168.199.21:2375}
        # AGENT01_DOCKER_HOST is the LOCAL socket used only by DockerAgent01Collector to list
        # agent-01's own containers. Kept separate so DOCKER_HOST can still target manager-01.
        - AGENT01_DOCKER_HOST=unix:///var/run/docker.sock
  ```

  Replace with:

  ```yaml
      environment:
        # agent-01 is not in the Swarm — manage manager-01 via Docker TCP API.
        # Override here so it applies even if not set in .env.
        #
        # DOCKER_HOST default uses plain TCP (port 2375, unauthenticated).
        # For production TLS migration, configure Docker daemon on manager-01 with:
        #   --tlsverify --tlscacert=/etc/docker/certs/ca.pem
        #   --tlscert=/etc/docker/certs/server-cert.pem
        #   --tlskey=/etc/docker/certs/server-key.pem
        #   -H tcp://0.0.0.0:2376
        # Then set in .env (or docker/.env):
        #   DOCKER_HOST=tcp://192.168.199.21:2376
        #   DOCKER_TLS_VERIFY=1
        #   DOCKER_CERT_PATH=/path/to/client/certs
        - DOCKER_HOST=${DOCKER_HOST:-tcp://192.168.199.21:2375}
        # TLS pass-throughs: set these in .env to enable TLS without editing this file.
        - DOCKER_TLS_VERIFY=${DOCKER_TLS_VERIFY:-}
        - DOCKER_CERT_PATH=${DOCKER_CERT_PATH:-}
        # AGENT01_DOCKER_HOST is the LOCAL socket used only by DockerAgent01Collector to list
        # agent-01's own containers. Kept separate so DOCKER_HOST can still target manager-01.
        - AGENT01_DOCKER_HOST=unix:///var/run/docker.sock
  ```

  Note: `${DOCKER_TLS_VERIFY:-}` passes the env var through if set, or passes an empty string if unset — Docker ignores empty `DOCKER_TLS_VERIFY` and `DOCKER_CERT_PATH`, so this is safe.

---

### Task C2 — Update `docker/.env.example`

**File:** `docker/.env.example`

**Steps:**

- [ ] **C2.1** Open `docker/.env.example`. Locate the Docker daemon section at lines 45–55:

  ```
  # ── Docker daemon (remote Swarm manager) ─────────────────────────────────────
  # agent-01 is NOT in the Swarm — it manages manager-01 remotely over TCP.
  # Docker daemon TCP API port: 2375 (plain) or 2376 (TLS). 2377 is Swarm control plane only.
  # Requires: dockerd on manager-01 started with -H tcp://0.0.0.0:2375 (or systemd override).
  DOCKER_HOST=tcp://192.168.199.21:2375

  # ── Docker Engine SSH (alternative remote management via SSH tunnel) ──────────
  DOCKER_ENGINE_HOST=
  DOCKER_ENGINE_USER=root
  DOCKER_ENGINE_SSH_KEY=/home/agent/.ssh/id_rsa
  # DOCKER_ENGINE_SSH_PORT=22
  ```

  Replace with:

  ```
  # ── Docker daemon (remote Swarm manager) ─────────────────────────────────────
  # agent-01 is NOT in the Swarm — it manages manager-01 remotely over TCP.
  # Docker daemon TCP API port: 2375 (plain) or 2376 (TLS). 2377 is Swarm control plane only.
  # Requires: dockerd on manager-01 started with -H tcp://0.0.0.0:2375 (or systemd override).
  DOCKER_HOST=tcp://192.168.199.21:2375

  # ── Docker TLS (optional — upgrade from plain TCP 2375 to TLS 2376) ──────────
  # Step 1: configure dockerd on manager-01 with TLS certs (see docs/runbooks/docker-tls.md).
  # Step 2: set these variables and change DOCKER_HOST port to 2376:
  #   DOCKER_HOST=tcp://192.168.199.21:2376
  #   DOCKER_TLS_VERIFY=1
  #   DOCKER_CERT_PATH=/home/agent/.docker/certs   # directory with ca.pem, cert.pem, key.pem
  DOCKER_TLS_VERIFY=
  DOCKER_CERT_PATH=

  # ── Docker Engine SSH (alternative remote management via SSH tunnel) ──────────
  DOCKER_ENGINE_HOST=
  DOCKER_ENGINE_USER=root
  DOCKER_ENGINE_SSH_KEY=/home/agent/.ssh/id_rsa
  # DOCKER_ENGINE_SSH_PORT=22
  ```

---

### Task C3 — Verify compose file validity

No automated tests are appropriate for Docker Compose config changes. Use the manual checklist below.

- [ ] **C3.1** Validate compose file syntax (requires Docker and Compose CLI):
  ```bash
  docker compose -f docker/docker-compose.yml config --quiet
  ```
  Expected: no errors.

- [ ] **C3.2** Confirm env-var interpolation works with no `.env` present:
  ```bash
  cd docker && docker compose config | grep DOCKER_HOST
  ```
  Expected output contains: `DOCKER_HOST: tcp://192.168.199.21:2375`

- [ ] **C3.3** Confirm TLS pass-throughs appear empty when not set:
  ```bash
  cd docker && docker compose config | grep DOCKER_TLS
  ```
  Expected: `DOCKER_TLS_VERIFY:` with empty or no value.

- [ ] **C3.4** Manual verification on the running agent (hp1-prod-agent-01):
  1. Pull the updated compose file to the host.
  2. Confirm `docker compose -f docker/docker-compose.yml config` parses cleanly.
  3. Confirm the agent container still starts and `/api/health` returns `{"status":"ok"}`.
  4. Confirm `docker exec hp1_agent env | grep DOCKER` shows `DOCKER_HOST=tcp://192.168.199.21:2375` and empty `DOCKER_TLS_VERIFY` / `DOCKER_CERT_PATH`.

- [ ] **C3.5** Commit and push:
  ```
  fix(docker): add TLS pass-through env vars and migration comment to docker-compose.yml
  ```
  ```bash
  git push
  ```

---

### Task C4 — Manual TLS migration checklist (future reference)

This checklist is provided for reference. It is NOT part of the current implementation — execute it only when upgrading to TLS is planned.

- [ ] **C4.1** On each Swarm manager (e.g., `192.168.199.21`):
  - Generate TLS CA, server cert, and client cert.
  - Add to `/etc/docker/daemon.json`:
    ```json
    {
      "hosts": ["unix:///var/run/docker.sock", "tcp://0.0.0.0:2376"],
      "tls": true,
      "tlscacert": "/etc/docker/certs/ca.pem",
      "tlscert": "/etc/docker/certs/server-cert.pem",
      "tlskey": "/etc/docker/certs/server-key.pem",
      "tlsverify": true
    }
    ```
  - Restart Docker: `systemctl restart docker`
  - Verify: `curl --tlsverify --cacert ca.pem --cert cert.pem --key key.pem https://192.168.199.21:2376/version`

- [ ] **C4.2** Place client certs on hp1-prod-agent-01 at `/home/agent/.docker/certs/` (ca.pem, cert.pem, key.pem).

- [ ] **C4.3** Update `docker/.env`:
  ```
  DOCKER_HOST=tcp://192.168.199.21:2376
  DOCKER_TLS_VERIFY=1
  DOCKER_CERT_PATH=/home/agent/.docker/certs
  ```

- [ ] **C4.4** Restart agent container and verify Swarm tools respond: `curl -s http://192.168.199.10:8000/api/health`.

- [ ] **C4.5** Close firewall rule for port 2375 on manager hosts (iptables or FortiGate policy).

---

## Bundle D — Version bump

### Task D1 — Final version bump

**File:** `VERSION`

**Steps:**

- [ ] **D1.1** Verify all previous commits are pushed:
  ```bash
  git log --oneline -6
  git status
  ```

- [ ] **D1.2** Run full test suite one final time:
  ```bash
  pytest tests/ -x -q
  ```
  Expected: pre-existing proxmox collector failure only; all other tests pass (the new `test_db_path.py` adds 3 more passing tests).

- [ ] **D1.3** Run pre-commit checklist:
  ```bash
  grep -rE "D:/claude_code|C:/claude_code" api/ tests/ mcp_server/
  ```
  Expected: no output (hard-coded Windows paths eliminated).

  ```bash
  grep -rn "AutoAddPolicy" api/
  ```
  Expected: no output (replaced with WarningPolicy).

  ```bash
  python -m py_compile api/db/base.py api/db/migrate_sqlite.py api/routers/ansible.py
  for f in mcp_server/tools/skills/modules/*.py; do python -m py_compile "$f"; done
  ```
  Expected: no errors.

- [ ] **D1.4** Update `VERSION` from `1.10.18` to `1.10.22`.

  Note: Versions 1.10.19, 1.10.20, and 1.10.21 are reserved for the three preceding bundle commits in this plan's implementation sequence:
  - 1.10.19 — auth endpoints plan (separate plan: `2026-03-27-security-hardening-auth-endpoints.md`)
  - 1.10.20 — reserved for any intermediate bundle committed before this plan completes
  - 1.10.21 — reserved for intermediate bundle
  - 1.10.22 — this plan's final state

  If this plan is the only in-flight security plan and bundles A/B/C were committed as part of it, set `VERSION` to `1.10.22`.

- [ ] **D1.5** Commit and push:
  ```
  chore(release): bump version to 1.10.22
  ```
  ```bash
  git push
  ```

---

## Verification Summary

| Condition | How to verify |
|-----------|--------------|
| DB path works in Docker | Start container with no `SQLITE_PATH`/`DB_PATH` env vars; confirm DB file created at `/app/data/hp1_agent.db` |
| DB path test passes | `pytest tests/test_db_path.py -v` — 3 PASSED |
| No Windows path in source | `grep -rn "D:/claude_code" api/ tests/` — no output |
| SSH uses WarningPolicy by default | `grep -n "AutoAddPolicy\|WarningPolicy" api/routers/ansible.py` — only `WarningPolicy` appears in active code |
| SSH opt-out documented | `DISABLE_HOST_KEY_CHECK=true` triggers `AutoAddPolicy` + WARNING log |
| Docker TLS env vars available | `docker compose config | grep DOCKER_TLS` shows pass-through vars |
| Compose file parses cleanly | `docker compose -f docker/docker-compose.yml config --quiet` — no errors |
| Full test suite | `pytest tests/ -x -q` — 1 pre-existing fail only; `test_db_path.py` adds 3 new passes |

---

## Notes and Cautions

- **`migrate_sqlite.py` is a one-shot migration script.** It is invoked manually (`python -m api.db.migrate_sqlite`) and does not run in normal container operation. The path fix is still necessary: if a developer clones the repo and runs the migration without setting `SQLITE_PATH`, the hard-coded Windows path would silently fail on Linux.
- **`_PROJECT_ROOT` naming**: Both files define `_PROJECT_ROOT` as a module-level variable. Since `migrate_sqlite.py` imports `api.db.base` later in its body (line 137), there is no name collision — each module has its own namespace.
- **Module reload in tests**: The `test_db_path.py` test uses `importlib.reload()` to re-evaluate the module-level `_SQLITE_PATH` with different env vars. This pattern works correctly for testing module-level constants that are evaluated at import time.
- **`ANSIBLE_HOST_KEY_CHECKING=False`** (line 136 in `ansible.py`) is out of scope. It controls Ansible's SSH host key policy for playbook runs, not the Paramiko SSH test-connection endpoint. Addressing it would require managing an Ansible `known_hosts` file and is a separate infrastructure concern.
- **Port 2375 in `discovery.py` and `fingerprints.py`**: These files probe port 2375 as part of environment discovery fingerprinting. This is legitimate scanner behaviour (the agent is discovering what services are running), not a connection default. No change needed.
- **`.env.example` in repo root** (`.env.example`): This file already documents `SQLITE_PATH` with the hard-coded Windows path as an example on line 9. This is a comment/example, not a live default. However, after the fix, consider updating that line to:
  ```
  # SQLITE_PATH=/app/data/hp1_agent.db   (Docker default; omit to use __file__-relative default)
  ```
  This is a cosmetic improvement and can be done as part of the Bundle A commit.
