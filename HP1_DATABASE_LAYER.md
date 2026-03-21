# Claude Code: Database Abstraction Layer for HP1-AI-Agent

## Problem

The project is hardcoded to SQLite. This blocks Swarm multi-replica, limits
to single-node, and ignores databases already running in the operator's network.

## Design: Auto-Detecting Storage Abstraction

The agent should detect what databases are reachable on the network, pick the best
available option, and fall back gracefully to SQLite (which always works).

**Principle: zero mandatory infrastructure.** SQLite is embedded and always available.
Everything else is an upgrade if present.

---

## Storage Pattern Analysis

| Pattern | Data | Write frequency | Read pattern | Concurrency need |
|---|---|---|---|---|
| Registry | skills, service_catalog, breaking_changes | Low (create/update skills) | Query by name, search by keyword, list/filter | Medium (Swarm replicas read, single writer) |
| Append log | audit_log, compat_log | Medium (every tool call) | Tail, time-range filter, count by action | High (multiple replicas write simultaneously) |
| KV/Blob | checkpoints, skill exports, settings | Low | Read by key/label | Low |
| Memory/Semantic | MuninnDB engrams | Low-Medium | Semantic search, activation | Handled by MuninnDB (external) |

---

## Recommended Database Tiers

### Tier 1: PostgreSQL (optimal for everything)

**Why it's the best single choice:**
- Handles all 3 patterns (relational, append log, JSONB for blobs)
- Native concurrent writes — solves the Swarm replica problem completely
- JSONB columns for flexible schema (skill parameters, checkpoint data)
- `LISTEN/NOTIFY` for real-time events (skill created, breaking change detected)
- Most homelabs already run it (for Grafana, Gitea, Nextcloud, Home Assistant, etc.)
- Works perfectly in Docker — official image, tiny footprint
- `pg_trgm` extension for fuzzy text search on skill descriptions (no separate search engine)

**What it replaces:** SQLite for everything + audit log files + checkpoint JSON files.

### Tier 2: SQLite (zero-config fallback)

**When to use:** No PostgreSQL available, single-node deployment, getting started quickly.
- Always works, no setup
- WAL mode handles concurrent readers with single writer
- Fine for single-replica Swarm or Docker Compose
- Embedded — no network dependency

**Limitation:** Multiple replicas writing = corruption risk. Single writer only.

### Tier 3: Redis (optional acceleration layer)

**Why it's useful alongside PostgreSQL or SQLite:**
- Caching: service_catalog lookups, skill metadata, doc retrieval results
- Pub/Sub: broadcast skill creation/deletion events to all replicas
- Rate limiting: throttle LLM calls for skill generation
- Session state: if the GUI needs it

**NOT a primary database.** Use it as a cache in front of PostgreSQL/SQLite.
Many homelabs already run Redis (for Nextcloud, caching, queues).

### What NOT to support (and why)

| Database | Why skip |
|---|---|
| MySQL/MariaDB | No JSONB, worse concurrent write handling than PostgreSQL, no `LISTEN/NOTIFY`. If the operator only has MySQL, they can still use SQLite locally. |
| MongoDB | Overkill, different query paradigm, rare in homelabs for infra tools. |
| CockroachDB/TiDB | Distributed SQL — impressive but way beyond homelab needs. |
| etcd/Consul | KV stores — too limited for relational queries. |
| InfluxDB/TimescaleDB | Time-series — only useful for the audit log pattern, not worth the complexity. |

**Bottom line: support PostgreSQL + SQLite. Optionally detect Redis for caching.**

---

## Architecture: Storage Backend Abstraction

```
mcp_server/tools/skills/
├── storage/
│   ├── __init__.py          # Exports get_backend() factory
│   ├── interface.py         # Abstract base class — the contract
│   ├── sqlite_backend.py    # SQLite implementation (default)
│   ├── postgres_backend.py  # PostgreSQL implementation
│   ├── cache.py             # Optional Redis cache wrapper
│   └── auto_detect.py       # Probe network, pick best backend
```

### `interface.py` — The Contract

Every backend implements this interface. All existing code calls these methods —
never raw SQL. The interface is sync (matching the project pattern).

```python
"""Storage backend interface — all backends implement this contract."""
from abc import ABC, abstractmethod
from typing import Any


class StorageBackend(ABC):
    """
    Abstract storage backend. Implementations: SQLite, PostgreSQL.
    All methods are synchronous (matching project convention).
    All methods return dicts or lists of dicts — never ORM objects.
    """

    # ── Lifecycle ───────────────────────────────────────────────────────
    @abstractmethod
    def init(self) -> None:
        """Create tables/schema if they don't exist. Idempotent."""

    @abstractmethod
    def close(self) -> None:
        """Close connections. Called on shutdown."""

    @abstractmethod
    def health_check(self) -> dict:
        """Return {"ok": bool, "backend": str, "details": str}."""

    # ── Skills Registry ─────────────────────────────────────────────────
    @abstractmethod
    def register_skill(self, meta: dict, file_path: str, **kwargs) -> dict: ...

    @abstractmethod
    def get_skill(self, name: str) -> dict | None: ...

    @abstractmethod
    def search_skills(self, query: str, category: str = "") -> list[dict]: ...

    @abstractmethod
    def list_skills(self, category: str = "", enabled_only: bool = True) -> list[dict]: ...

    @abstractmethod
    def update_skill(self, name: str, **fields) -> dict: ...

    @abstractmethod
    def delete_skill(self, name: str) -> dict: ...

    @abstractmethod
    def increment_call(self, name: str) -> None: ...

    @abstractmethod
    def record_error(self, name: str, error: str) -> None: ...

    # ── Service Catalog ─────────────────────────────────────────────────
    @abstractmethod
    def upsert_service(self, service_id: str, **fields) -> dict: ...

    @abstractmethod
    def get_service(self, service_id: str) -> dict | None: ...

    @abstractmethod
    def list_services(self) -> list[dict]: ...

    # ── Breaking Changes ────────────────────────────────────────────────
    @abstractmethod
    def add_breaking_change(self, service_id: str, to_version: str, description: str, **kwargs) -> dict: ...

    @abstractmethod
    def get_breaking_changes(self, service_id: str, unresolved_only: bool = False) -> list[dict]: ...

    @abstractmethod
    def resolve_breaking_change(self, change_id: int) -> dict: ...

    # ── Audit Log ───────────────────────────────────────────────────────
    @abstractmethod
    def append_audit(self, action: str, result: Any) -> dict: ...

    @abstractmethod
    def query_audit(self, action_prefix: str = "", limit: int = 50, offset: int = 0) -> list[dict]: ...

    # ── Compat Log ──────────────────────────────────────────────────────
    @abstractmethod
    def log_compat_check(self, skill_name: str, service_id: str, **kwargs) -> None: ...

    @abstractmethod
    def get_compat_history(self, skill_name: str, limit: int = 10) -> list[dict]: ...

    # ── Checkpoints ─────────────────────────────────────────────────────
    @abstractmethod
    def save_checkpoint(self, label: str, data: dict) -> dict: ...

    @abstractmethod
    def load_checkpoint(self, label: str) -> dict | None: ...

    @abstractmethod
    def list_checkpoints(self, limit: int = 20) -> list[dict]: ...

    # ── Settings ────────────────────────────────────────────────────────
    @abstractmethod
    def get_setting(self, key: str) -> Any: ...

    @abstractmethod
    def set_setting(self, key: str, value: Any) -> None: ...
```

### `auto_detect.py` — Probe and Select

Runs once at startup. Probes the network for available databases, picks the best,
and returns a configured backend instance.

```python
"""Auto-detect the best available storage backend."""
import os
import logging

log = logging.getLogger(__name__)


def detect_backend() -> "StorageBackend":
    """
    Probe for databases in priority order. Return the best available backend.

    Priority:
      1. Explicit override via STORAGE_BACKEND env var (postgres, sqlite)
      2. PostgreSQL — check DATABASE_URL or POSTGRES_* env vars, then probe
      3. SQLite — always available, the fallback

    For PostgreSQL, probes these sources:
      - DATABASE_URL env var (standard format: postgresql://user:pass@host:5432/dbname)
      - POSTGRES_HOST + POSTGRES_PORT + POSTGRES_DB + POSTGRES_USER + POSTGRES_PASSWORD
      - Well-known hostnames: postgres, postgresql, db, database (Docker DNS)
      - Well-known ports on gateway: 5432 on 172.17.0.1 (host from container)

    Returns a fully initialized backend (init() already called).
    """
    explicit = os.environ.get("STORAGE_BACKEND", "").lower()

    if explicit == "sqlite":
        log.info("Storage backend: SQLite (explicit override)")
        return _init_sqlite()

    if explicit == "postgres":
        backend = _try_postgres()
        if backend:
            return backend
        log.warning("PostgreSQL requested but not reachable — falling back to SQLite")
        return _init_sqlite()

    # Auto-detect: try PostgreSQL first, fall back to SQLite
    backend = _try_postgres()
    if backend:
        return backend

    log.info("Storage backend: SQLite (no PostgreSQL found)")
    return _init_sqlite()


def _try_postgres() -> "StorageBackend | None":
    """Attempt to connect to PostgreSQL. Returns backend or None."""
    dsn = _build_postgres_dsn()
    if not dsn:
        return None

    try:
        from mcp_server.tools.skills.storage.postgres_backend import PostgresBackend
        backend = PostgresBackend(dsn)
        backend.init()
        health = backend.health_check()
        if health["ok"]:
            log.info("Storage backend: PostgreSQL (%s)", health["details"])
            return backend
        backend.close()
    except ImportError:
        log.debug("psycopg2 not installed — PostgreSQL unavailable")
    except Exception as e:
        log.debug("PostgreSQL connection failed: %s", e)

    return None


def _build_postgres_dsn() -> str:
    """Build a PostgreSQL DSN from env vars or probe the network."""
    import httpx

    # Source 1: explicit DATABASE_URL
    url = os.environ.get("DATABASE_URL", "")
    if url and url.startswith("postgresql"):
        return url

    # Source 2: POSTGRES_* env vars
    host = os.environ.get("POSTGRES_HOST", "")
    if host:
        port = os.environ.get("POSTGRES_PORT", "5432")
        db = os.environ.get("POSTGRES_DB", "hp1_agent")
        user = os.environ.get("POSTGRES_USER", "hp1")
        password = os.environ.get("POSTGRES_PASSWORD", "")
        return f"postgresql://{user}:{password}@{host}:{port}/{db}"

    # Source 3: probe well-known Docker DNS names
    import socket
    probe_hosts = ["postgres", "postgresql", "db", "database"]

    # Also try the Docker host gateway (PostgreSQL on the host machine)
    try:
        # Docker Desktop
        socket.getaddrinfo("host.docker.internal", 5432, socket.AF_INET)
        probe_hosts.append("host.docker.internal")
    except socket.gaierror:
        pass
    probe_hosts.append("172.17.0.1")  # Linux Docker bridge

    for candidate in probe_hosts:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((candidate, 5432))
            sock.close()
            if result == 0:
                log.info("PostgreSQL detected at %s:5432", candidate)
                db = os.environ.get("POSTGRES_DB", "hp1_agent")
                user = os.environ.get("POSTGRES_USER", "hp1")
                password = os.environ.get("POSTGRES_PASSWORD", "hp1agent")
                return f"postgresql://{user}:{password}@{candidate}:5432/{db}"
        except Exception:
            continue

    return ""


def _init_sqlite() -> "StorageBackend":
    """Initialize and return SQLite backend."""
    from mcp_server.tools.skills.storage.sqlite_backend import SqliteBackend
    backend = SqliteBackend()
    backend.init()
    return backend


def detect_cache() -> "CacheBackend | None":
    """
    Optionally detect Redis for caching. Returns None if unavailable.
    Not required — everything works without it.

    Probes:
      - REDIS_URL env var
      - Well-known Docker names: redis, cache
      - Host gateway: 172.17.0.1:6379
    """
    import socket

    redis_url = os.environ.get("REDIS_URL", "")
    if redis_url:
        return _try_redis(redis_url)

    probe_hosts = ["redis", "cache", "172.17.0.1"]
    try:
        socket.getaddrinfo("host.docker.internal", 6379, socket.AF_INET)
        probe_hosts.insert(0, "host.docker.internal")
    except socket.gaierror:
        pass

    for candidate in probe_hosts:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((candidate, 6379))
            sock.close()
            if result == 0:
                return _try_redis(f"redis://{candidate}:6379/0")
        except Exception:
            continue

    return None


def _try_redis(url: str) -> "CacheBackend | None":
    try:
        from mcp_server.tools.skills.storage.cache import RedisCache
        cache = RedisCache(url)
        if cache.health_check()["ok"]:
            log.info("Cache backend: Redis (%s)", url.split("@")[-1])
            return cache
    except Exception:
        pass
    return None
```

### `sqlite_backend.py` — SQLite Implementation

This is what the existing `registry.py` becomes. Same SQL, just implementing the interface.

```python
"""SQLite storage backend — zero-config, always available."""
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp_server.tools.skills.storage.interface import StorageBackend


class SqliteBackend(StorageBackend):

    def __init__(self, db_path: str = ""):
        if not db_path:
            project_root = Path(__file__).parent.parent.parent.parent.parent
            db_path = str(project_root / "data" / "hp1_agent.db")
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
        return self._conn

    def init(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS skills ( ... );
            CREATE TABLE IF NOT EXISTS service_catalog ( ... );
            CREATE TABLE IF NOT EXISTS breaking_changes ( ... );
            CREATE TABLE IF NOT EXISTS skill_compat_log ( ... );
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                result TEXT DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS checkpoints (
                label TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                data TEXT NOT NULL,
                PRIMARY KEY (label, timestamp)
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        conn.commit()

    def health_check(self) -> dict:
        try:
            self._get_conn().execute("SELECT 1")
            return {"ok": True, "backend": "sqlite", "details": self.db_path}
        except Exception as e:
            return {"ok": False, "backend": "sqlite", "details": str(e)}

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ... implement all interface methods using sqlite3 ...
    # Pattern: self._get_conn().execute(sql, params), return dict(row)
```

### `postgres_backend.py` — PostgreSQL Implementation

Uses `psycopg2` (sync, matching project pattern). Connection pooling via
`psycopg2.pool.SimpleConnectionPool`.

```python
"""PostgreSQL storage backend — concurrent writes, Swarm-ready."""
import json
import os
from datetime import datetime, timezone
from typing import Any

from mcp_server.tools.skills.storage.interface import StorageBackend


class PostgresBackend(StorageBackend):

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._pool = None

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

    def _execute(self, sql: str, params: tuple = (), fetch: str = "none"):
        """Execute SQL. fetch: 'none', 'one', 'all'."""
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

    def init(self) -> None:
        # PostgreSQL-specific: use JSONB for flexible columns, TEXT ARRAY for tags
        self._execute("""
            CREATE TABLE IF NOT EXISTS skills (
                name           TEXT PRIMARY KEY,
                description    TEXT NOT NULL,
                category       TEXT DEFAULT 'general',
                version        TEXT DEFAULT '1.0.0',
                file_path      TEXT NOT NULL,
                auth_type      TEXT DEFAULT 'none',
                config_keys    JSONB DEFAULT '[]',
                parameters     JSONB DEFAULT '{}',
                annotations    JSONB DEFAULT '{}',
                compat         JSONB DEFAULT '{}',
                enabled        BOOLEAN DEFAULT TRUE,
                auto_generated BOOLEAN DEFAULT FALSE,
                generation_mode TEXT DEFAULT 'manual',
                created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                call_count     INTEGER DEFAULT 0,
                last_error     TEXT,
                last_called_at TIMESTAMPTZ
            );

            CREATE TABLE IF NOT EXISTS service_catalog (
                service_id       TEXT PRIMARY KEY,
                display_name     TEXT NOT NULL,
                service_type     TEXT DEFAULT '',
                detected_version TEXT DEFAULT '',
                known_latest     TEXT DEFAULT '',
                version_source   TEXT DEFAULT '',
                api_docs_ingested BOOLEAN DEFAULT FALSE,
                api_docs_version  TEXT DEFAULT '',
                changelog_ingested BOOLEAN DEFAULT FALSE,
                last_checked     TIMESTAMPTZ,
                created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                notes            TEXT DEFAULT '',
                metadata         JSONB DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS breaking_changes (
                id                 SERIAL PRIMARY KEY,
                service_id         TEXT NOT NULL REFERENCES service_catalog(service_id),
                from_version       TEXT DEFAULT '',
                to_version         TEXT NOT NULL,
                severity           TEXT DEFAULT 'warning',
                description        TEXT NOT NULL,
                affected_endpoints JSONB DEFAULT '[]',
                affected_skills    JSONB DEFAULT '[]',
                remediation        TEXT DEFAULT '',
                source             TEXT DEFAULT '',
                muninndb_ref       TEXT DEFAULT '',
                created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                resolved           BOOLEAN DEFAULT FALSE
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id         SERIAL PRIMARY KEY,
                timestamp  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                action     TEXT NOT NULL,
                result     JSONB DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
            CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(timestamp);

            CREATE TABLE IF NOT EXISTS checkpoints (
                label      TEXT NOT NULL,
                timestamp  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                data       JSONB NOT NULL,
                PRIMARY KEY (label, timestamp)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key        TEXT PRIMARY KEY,
                value      JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            -- Full-text search on skill descriptions
            CREATE INDEX IF NOT EXISTS idx_skills_search
            ON skills USING gin(to_tsvector('english', description));
        """)

    def health_check(self) -> dict:
        try:
            row = self._execute("SELECT version(), current_database()", fetch="one")
            return {"ok": True, "backend": "postgresql",
                    "details": f"{row['current_database']} ({row['version'][:30]}...)"}
        except Exception as e:
            return {"ok": False, "backend": "postgresql", "details": str(e)}

    def close(self) -> None:
        if self._pool:
            self._pool.closeall()
            self._pool = None

    def search_skills(self, query: str, category: str = "") -> list[dict]:
        """PostgreSQL full-text search — much better than SQLite LIKE."""
        sql = """
            SELECT *, ts_rank(to_tsvector('english', description),
                              plainto_tsquery('english', %s)) AS rank
            FROM skills
            WHERE enabled = TRUE
              AND to_tsvector('english', description) @@ plainto_tsquery('english', %s)
        """
        params = [query, query]
        if category:
            sql += " AND category = %s"
            params.append(category)
        sql += " ORDER BY rank DESC LIMIT 20"
        return self._execute(sql, tuple(params), fetch="all") or []

    def append_audit(self, action: str, result: Any) -> dict:
        """Concurrent-safe audit logging — PostgreSQL handles this natively."""
        self._execute(
            "INSERT INTO audit_log (action, result) VALUES (%s, %s)",
            (action, json.dumps(result, default=str)),
        )
        return {"ok": True}

    # ... implement remaining interface methods ...
    # Key difference from SQLite: use %s params, JSONB columns, TIMESTAMPTZ
```

### `cache.py` — Optional Redis Cache

Wraps the storage backend with a read-through cache. Optional — everything works without it.

```python
"""Optional Redis cache layer. Wraps any StorageBackend."""
import json
import logging
from typing import Any

log = logging.getLogger(__name__)


class RedisCache:
    """
    Read-through cache for hot data: skill metadata, service catalog.
    NOT used for audit log or checkpoints (write-heavy, not worth caching).
    TTL: 5 minutes for skill metadata, 1 minute for service versions.
    """

    def __init__(self, url: str):
        import redis
        self.client = redis.from_url(url, decode_responses=True)
        self.default_ttl = 300  # 5 minutes

    def health_check(self) -> dict:
        try:
            self.client.ping()
            return {"ok": True, "backend": "redis", "details": "connected"}
        except Exception as e:
            return {"ok": False, "backend": "redis", "details": str(e)}

    def get(self, key: str) -> Any:
        val = self.client.get(key)
        return json.loads(val) if val else None

    def set(self, key: str, value: Any, ttl: int = None) -> None:
        self.client.setex(key, ttl or self.default_ttl, json.dumps(value, default=str))

    def delete(self, key: str) -> None:
        self.client.delete(key)

    def invalidate_prefix(self, prefix: str) -> None:
        """Delete all keys matching a prefix. Use after writes."""
        for key in self.client.scan_iter(f"{prefix}*"):
            self.client.delete(key)

    def close(self) -> None:
        self.client.close()
```

### `__init__.py` — Singleton Factory

```python
"""Storage backend factory. Call get_backend() to get the active backend."""
import logging

log = logging.getLogger(__name__)

_backend = None
_cache = None


def get_backend():
    """Return the active storage backend (singleton). Auto-detects on first call."""
    global _backend
    if _backend is None:
        from mcp_server.tools.skills.storage.auto_detect import detect_backend
        _backend = detect_backend()
    return _backend


def get_cache():
    """Return the Redis cache (singleton), or None if unavailable."""
    global _cache
    if _cache is None:
        from mcp_server.tools.skills.storage.auto_detect import detect_cache
        _cache = detect_cache()  # May return None
    return _cache


def shutdown():
    """Close all connections. Call on app shutdown."""
    global _backend, _cache
    if _backend:
        _backend.close()
        _backend = None
    if _cache:
        _cache.close()
        _cache = None
```

---

## How Existing Code Changes

### Before (direct SQLite):
```python
# In registry.py, meta_tools.py, knowledge_base.py, orchestration.py
import sqlite3
conn = sqlite3.connect("data/skills.db")
conn.execute("INSERT INTO skills ...")
```

### After (via backend):
```python
# Everywhere
from mcp_server.tools.skills.storage import get_backend

db = get_backend()
db.register_skill(meta, file_path)
db.search_skills("fortigate")
db.append_audit("skill_create", {"name": "..."})
db.save_checkpoint("before_upgrade", snapshot_data)
```

The backend handles SQL dialect differences internally.
Calling code never sees SQL, connection objects, or database-specific types.

### Audit log migration

Currently `orchestration.py` writes JSONL to `logs/audit.log` via file append.
The storage backend absorbs this — `append_audit()` writes to the database.
Keep the JSONL file as a secondary output (for `tail -f` debugging) but the
database is the source of truth.

```python
# In orchestration.py — change audit_log() to use the backend
def audit_log(action: str, result: Any) -> dict:
    from mcp_server.tools.skills.storage import get_backend
    db = get_backend()
    db.append_audit(action, result)

    # Also write to file for tail-f debugging (non-critical)
    try:
        entry = {"timestamp": _ts(), "action": action, "result": result}
        with open(_audit_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        pass  # File write is best-effort

    return _ok({"action": action}, f"Audit entry logged: {action}")
```

### Checkpoint migration

Currently `orchestration.py` writes JSON files to `checkpoints/`.
The backend absorbs this — `save_checkpoint()` stores in the database.
Keep file output as secondary for portability.

---

## Requirements Additions

```
# In requirements.txt — add:
psycopg2-binary>=2.9.0    # PostgreSQL (binary wheel, no build deps needed)
redis>=5.0.0               # Optional cache layer
```

Both are optional at runtime — the code catches `ImportError` and falls back gracefully.
But they're baked into the Docker image so they're always available in containers.

---

## Environment Variables

```bash
# ── Storage Backend ───────────────────────────────────────────────────────────
# Explicit override: postgres | sqlite (default: auto-detect)
STORAGE_BACKEND=

# PostgreSQL connection (any ONE of these works)
DATABASE_URL=postgresql://hp1:hp1agent@postgres:5432/hp1_agent
# OR individual vars:
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=hp1_agent
POSTGRES_USER=hp1
POSTGRES_PASSWORD=hp1agent

# Redis cache (optional)
REDIS_URL=redis://redis:6379/0
```

---

## Docker Compose Addition — Optional PostgreSQL + Redis

Add to `docker-compose.yml` as opt-in services:

```yaml
services:
  agent:
    # ... existing agent config ...
    environment:
      - DATABASE_URL=${DATABASE_URL:-}
      - REDIS_URL=${REDIS_URL:-}
    depends_on:
      postgres:
        condition: service_healthy
        required: false    # Agent starts even without PostgreSQL
      redis:
        condition: service_healthy
        required: false

  # ── Optional: PostgreSQL ──────────────────────────────────────────────────
  postgres:
    image: postgres:16-alpine
    profiles: ["postgres"]   # Only starts with: docker compose --profile postgres up
    restart: unless-stopped
    environment:
      - POSTGRES_DB=${POSTGRES_DB:-hp1_agent}
      - POSTGRES_USER=${POSTGRES_USER:-hp1}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-hp1agent}
    volumes:
      - postgres-data:/var/lib/postgresql/data
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-hp1}"]
      interval: 10s
      timeout: 3s
      retries: 3
    deploy:
      resources:
        limits:
          memory: 256M

  # ── Optional: Redis ───────────────────────────────────────────────────────
  redis:
    image: redis:7-alpine
    profiles: ["redis"]
    restart: unless-stopped
    volumes:
      - redis-data:/data
    ports:
      - "${REDIS_PORT:-6379}:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 3
    deploy:
      resources:
        limits:
          memory: 64M

volumes:
  postgres-data:
    name: hp1-postgres-data
  redis-data:
    name: hp1-redis-data
```

**Usage patterns:**

```bash
# Minimal — SQLite, no external DB
docker compose up -d

# With PostgreSQL (Swarm-ready, concurrent writes)
docker compose --profile postgres up -d

# With PostgreSQL + Redis cache
docker compose --profile postgres --profile redis up -d

# Use existing PostgreSQL in your network
DATABASE_URL=postgresql://user:pass@nas.local:5432/hp1 docker compose up -d
```

---

## Swarm Stack Changes

In `swarm-stack.yml`, the agent should detect PostgreSQL if it exists on the network.
The auto-detect probes Docker DNS names (`postgres`, `postgresql`, `db`), so if
another stack runs PostgreSQL on the same overlay network, the agent finds it automatically.

No changes needed to the Swarm stack file — just ensure the agent is on a network
where PostgreSQL is reachable, or set `DATABASE_URL` explicitly.

---

## New Tool: Storage Health

```python
@mcp.tool()
def storage_health() -> dict:
    """Show current storage configuration: which backend, connection status, cache status."""
    from mcp_server.tools.skills.storage import get_backend, get_cache

    db = get_backend()
    db_health = db.health_check()

    cache = get_cache()
    cache_health = cache.health_check() if cache else {"ok": False, "backend": "none", "details": "not configured"}

    return {
        "status": "ok",
        "data": {
            "database": db_health,
            "cache": cache_health,
        },
        "timestamp": _ts(),
        "message": f"DB: {db_health['backend']} ({'ok' if db_health['ok'] else 'ERROR'}) | "
                   f"Cache: {cache_health['backend']} ({'ok' if cache_health['ok'] else 'none'})",
    }
```

---

## Implementation Order

1. `storage/__init__.py` — factory with get_backend/get_cache
2. `storage/interface.py` — abstract base class
3. `storage/sqlite_backend.py` — port existing registry.py SQL into the interface
4. `storage/auto_detect.py` — probe logic (start with SQLite-only path)
5. `storage/postgres_backend.py` — PostgreSQL implementation
6. `storage/cache.py` — Redis wrapper
7. Update `registry.py` to delegate to `get_backend()` instead of raw sqlite3
8. Update `orchestration.py` audit_log/checkpoint to use backend
9. Add `psycopg2-binary` and `redis` to requirements.txt
10. Add profiles to docker-compose.yml
11. Add `storage_health` tool to server.py
12. Test: starts with SQLite when no PostgreSQL available
13. Test: auto-detects PostgreSQL when `--profile postgres` is used
14. Test: falls back cleanly when PostgreSQL goes down mid-operation

---

## Testing Checklist

### SQLite (default)
- [ ] Agent starts with no DATABASE_URL — uses SQLite
- [ ] All skill operations work (register, search, list, info)
- [ ] Audit log writes to DB + file simultaneously
- [ ] `storage_health()` reports SQLite

### PostgreSQL
- [ ] `docker compose --profile postgres up -d` — PostgreSQL starts
- [ ] Agent auto-detects PostgreSQL via Docker DNS
- [ ] All skill operations work with PostgreSQL
- [ ] Full-text search on skill descriptions works (`ts_rank`)
- [ ] Concurrent writes from 2 replicas don't conflict
- [ ] JSONB columns store/retrieve complex data correctly
- [ ] `storage_health()` reports PostgreSQL + version

### Redis
- [ ] `docker compose --profile redis up -d` — Redis starts
- [ ] Agent detects Redis, uses it for caching
- [ ] Cache invalidation works after skill creation/deletion
- [ ] Agent works fine when Redis goes down (fallback to direct DB reads)

### Fallback
- [ ] PostgreSQL unreachable at startup → falls back to SQLite with warning
- [ ] PostgreSQL dies mid-operation → error returned, agent doesn't crash
- [ ] `STORAGE_BACKEND=sqlite` overrides auto-detect even if PostgreSQL is available
- [ ] Missing `psycopg2` → SQLite, no crash, clear log message

### Migration
- [ ] Data created in SQLite can coexist (no migration tool needed for v1 — each backend is independent)
- [ ] Future: add `migrate_data(from_backend, to_backend)` tool for moving between backends
