"""Auto-detect the best available storage backend.

Priority order:
  1. Explicit STORAGE_BACKEND env var (postgres | sqlite)
  2. PostgreSQL — DATABASE_URL, POSTGRES_* vars, Docker DNS probe, host gateway probe
  3. SQLite — always available, zero-config fallback

Runs once at startup. Cached in storage/__init__.py as singleton.
"""
import logging
import os
import re
import socket

log = logging.getLogger(__name__)

_PG_PROBE_TIMEOUT = 1.0   # seconds — fast probe, don't block startup
_REDIS_PROBE_TIMEOUT = 1.0


def detect_backend():
    """Probe for databases and return the best available backend (initialized)."""
    explicit = os.environ.get("STORAGE_BACKEND", "").lower().strip()

    if explicit == "sqlite":
        log.info("Storage: SQLite (explicit override)")
        return _init_sqlite()

    if explicit == "postgres":
        backend = _try_postgres()
        if backend:
            return backend
        log.warning("Storage: PostgreSQL requested but not reachable — falling back to SQLite")
        return _init_sqlite()

    # Auto-detect
    backend = _try_postgres()
    if backend:
        return backend

    log.info("Storage: SQLite (no PostgreSQL found)")
    return _init_sqlite()


def detect_cache():
    """Probe for Redis. Returns RedisCache or None — never raises."""
    redis_url = os.environ.get("REDIS_URL", "")
    if redis_url:
        return _try_redis(redis_url)

    probe_hosts = ["redis", "cache"]

    # Docker Desktop
    try:
        socket.getaddrinfo("host.docker.internal", 6379, socket.AF_INET)
        probe_hosts.insert(0, "host.docker.internal")
    except OSError:
        pass

    probe_hosts.append("172.17.0.1")  # Linux bridge gateway

    for host in probe_hosts:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(_REDIS_PROBE_TIMEOUT)
            if s.connect_ex((host, 6379)) == 0:
                s.close()
                result = _try_redis(f"redis://{host}:6379/0")
                if result:
                    return result
            s.close()
        except Exception:
            pass

    return None


# ── PostgreSQL helpers ────────────────────────────────────────────────────────

def _try_postgres():
    """Try to connect to PostgreSQL. Returns backend or None."""
    dsn = _build_postgres_dsn()
    if not dsn:
        return None

    try:
        from mcp_server.tools.skills.storage.postgres_backend import PostgresBackend
        backend = PostgresBackend(dsn)
        backend.init()
        health = backend.health_check()
        if health["ok"]:
            log.info("Storage: PostgreSQL — %s", health["details"])
            return backend
        backend.close()
    except ImportError:
        log.debug("psycopg2 not installed — PostgreSQL unavailable")
    except Exception as e:
        log.debug("PostgreSQL connection failed: %s", e)

    return None


def _build_postgres_dsn() -> str:
    """Build a PostgreSQL DSN from env vars or network probe.

    Detection order:
      1. DATABASE_URL — dialect suffix stripped for psycopg2 compatibility
      2. POSTGRES_HOST env var — build DSN from individual POSTGRES_* vars
      3. Network probe — try hp1-postgres first, then generic Docker DNS names
    """
    # Source 1: explicit DATABASE_URL
    # Strip +dialect suffix (e.g. +asyncpg) so psycopg2 can use the URL.
    # The main app uses asyncpg; the storage backend uses psycopg2.
    url = os.environ.get("DATABASE_URL", "")
    if url:
        url = re.sub(r'^(postgresql|postgres)\+\w+(://)', r'\1\2', url)
        if url.startswith(("postgresql://", "postgres://")):
            return url

    # Source 2: individual POSTGRES_* env vars
    host = os.environ.get("POSTGRES_HOST", "")
    if host:
        port = os.environ.get("POSTGRES_PORT", "5432")
        db = os.environ.get("POSTGRES_DB", "hp1_agent")
        user = os.environ.get("POSTGRES_USER", "hp1")
        password = os.environ.get("POSTGRES_PASSWORD", "")
        return f"postgresql://{user}:{password}@{host}:{port}/{db}"

    # Source 3: probe well-known Docker DNS names + gateway
    # hp1-postgres is the container name on hp1-pg-net — try it first.
    probe_hosts = ["hp1-postgres", "postgres", "postgresql", "db", "database"]

    try:
        socket.getaddrinfo("host.docker.internal", 5432, socket.AF_INET)
        probe_hosts.append("host.docker.internal")
    except OSError:
        pass
    probe_hosts.append("172.17.0.1")

    for candidate in probe_hosts:
        if _port_open(candidate, 5432):
            log.info("PostgreSQL detected at %s:5432", candidate)
            db = os.environ.get("POSTGRES_DB", "hp1_agent")
            user = os.environ.get("POSTGRES_USER", "hp1")
            password = os.environ.get("POSTGRES_PASSWORD", "")
            return f"postgresql://{user}:{password}@{candidate}:5432/{db}"

    return ""


# ── Redis helpers ─────────────────────────────────────────────────────────────

def _try_redis(url: str):
    """Try to connect to Redis. Returns RedisCache or None."""
    try:
        from mcp_server.tools.skills.storage.cache import RedisCache
        cache = RedisCache(url)
        if cache.health_check()["ok"]:
            log.info("Cache: Redis — %s", url.split("@")[-1])
            return cache
        cache.close()
    except ImportError:
        log.debug("redis package not installed — cache unavailable")
    except Exception as e:
        log.debug("Redis connection failed: %s", e)
    return None


def _init_sqlite():
    """Initialize and return the SQLite backend."""
    from mcp_server.tools.skills.storage.sqlite_backend import SqliteBackend
    backend = SqliteBackend()
    backend.init()
    return backend


def _port_open(host: str, port: int) -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(_PG_PROBE_TIMEOUT)
        result = s.connect_ex((host, port)) == 0
        s.close()
        return result
    except Exception:
        return False
