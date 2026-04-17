"""DB-backed vm_exec allowlist — extends the hardcoded base with user-managed patterns.

Table: vm_exec_allowlist
  id          TEXT PK
  pattern     TEXT UNIQUE      -- regex pattern (same format as _ALLOWLIST in vm.py)
  description TEXT
  scope       TEXT             -- 'permanent' | 'session'
  session_id  TEXT             -- only populated for session-scoped entries
  added_by    TEXT
  approved_by TEXT
  is_base     BOOLEAN          -- True = seeded from hardcoded list, cannot be deleted
  created_at  TIMESTAMPTZ

Session-scoped entries are deleted when the session ends (called from agent loop cleanup).
Permanent entries persist across restarts.
"""
import logging
import time
import uuid
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS vm_exec_allowlist (
    id          TEXT PRIMARY KEY,
    pattern     TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    scope       TEXT NOT NULL DEFAULT 'permanent',
    session_id  TEXT NOT NULL DEFAULT '',
    added_by    TEXT NOT NULL DEFAULT 'system',
    approved_by TEXT NOT NULL DEFAULT '',
    is_base     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_vm_allowlist_scope ON vm_exec_allowlist(scope);
CREATE INDEX IF NOT EXISTS idx_vm_allowlist_session ON vm_exec_allowlist(session_id);
"""

_initialized = False

# ── In-memory cache ────────────────────────────────────────────────────────────
_cache: list[str] = []          # list of regex patterns (base + DB)
_cache_ts: float = 0.0
_CACHE_TTL = 30.0               # seconds

# ── Base patterns (hardcoded, always present) ──────────────────────────────────
# These are seeded into the DB on first init (is_base=True) and always loaded
# even if DB is unavailable.
BASE_PATTERNS: list[tuple[str, str]] = [
    # ── System info ──────────────────────────────────────────────────────────
    (r'^df\b',                         'Disk filesystem usage'),
    (r'^du\b',                         'Disk usage by directory'),
    (r'^free\b',                       'Memory usage'),
    (r'^uptime$',                      'System uptime'),
    (r'^uname\b',                      'Kernel/OS info'),
    (r'^hostname$',                    'Hostname'),
    (r'^whoami$',                      'Current user'),
    (r'^date\b',                       'System date/time'),
    (r'^timedatectl\b',                'Systemd time/timezone info'),
    # ── Process / resource ───────────────────────────────────────────────────
    (r'^ps\b',                         'Process list'),
    (r'^top\b',                        'Process monitor (non-interactive only)'),
    (r'^lsof\b',                       'Open files and ports'),
    # ── Network diagnostics ──────────────────────────────────────────────────
    (r'^ss\b',                         'Socket statistics (ss -tlnp etc.)'),
    (r'^netstat\b',                    'Network connections (legacy ss)'),
    (r'^nc\s+-[zv]+\b',               'Netcat port probe (-z -v flags only)'),
    (r'^ncat\s+-[zv]+\b',             'Ncat port probe (-z -v flags only)'),
    (r'^ip\s+(addr|route|link|neigh)\b', 'IP address / route / link info'),
    (r'^ping\s+-c\b',                  'Ping with count limit (not infinite)'),
    (r'^curl\s+--head\b',              'HTTP HEAD probe (read-only)'),
    (r'^curl\s+-I\b',                  'HTTP HEAD probe (read-only)'),
    (r'^curl\s+-o\s+/dev/null\b',      'HTTP response timing to /dev/null'),
    (r'^curl\s+-[sSmIf]+\b',           'Curl with safe flags (no file writes)'),
    (r'^dig\b',                        'DNS lookup'),
    (r'^nslookup\b',                   'DNS lookup (legacy)'),
    (r'^host\b',                       'DNS lookup'),
    (r'^traceroute\s+-m\b',            'Route trace with hop limit'),
    (r'^mtr\s+-r\s+-c\b',              'MTR packet report with count'),
    (r'^tracepath\b',                  'Path MTU discovery'),
    # ── Docker exec: read-only network diagnostics inside containers ────────
    (r'^docker exec \S+ nc\s+-[zv]+\b',           'Port probe inside container'),
    (r'^docker exec \S+ ncat\s+-[zv]+\b',         'Ncat port probe inside container'),
    (r'^docker exec \S+ netstat\b',               'Socket listing inside container'),
    (r'^docker exec \S+ ss\b',                    'Socket stats inside container'),
    (r'^docker exec \S+ cat /etc/resolv\.conf$',  'DNS config inside container'),
    (r'^docker exec \S+ ip\s+(addr|route|link|neigh)\b', 'Network info inside container'),
    (r'^docker exec \S+ ping\s+-c\b',             'Ping inside container'),
    (r'^docker exec \S+ dig\b',                   'DNS lookup inside container'),
    (r'^docker exec \S+ nslookup\b',              'DNS lookup inside container'),
    (r'^docker exec \S+ host\b',                  'DNS lookup inside container'),
    # ── Docker read-only ─────────────────────────────────────────────────────
    (r'^docker system df',             'Docker disk usage summary'),
    (r'^docker volume ls',             'List Docker volumes'),
    (r'^docker volume inspect\b',      'Inspect Docker volume'),
    (r'^docker container inspect\b',   'Inspect Docker container'),
    (r'^docker inspect\b',             'Inspect Docker object'),
    (r'^docker ps\b',                  'List Docker containers'),
    (r'^docker images\b',              'List Docker images'),
    (r'^docker logs\b',                'Docker container logs'),
    (r'^docker port\b',                'Container port mappings'),
    (r'^docker network\s+(ls|inspect)\b', 'Docker network list/inspect'),
    (r'^docker exec \S+ kafka-[a-z-]+\.sh\b', 'Kafka CLI tools in containers'),
    # ── Proxmox host diagnostics ──────────────────────────────────────────────
    (r'^qm list$',                         'Proxmox: list all VMs and status'),
    (r'^qm status\b',                      'Proxmox: VM status by VMID'),
    (r'^pct list$',                        'Proxmox: list all LXC containers'),
    (r'^pct status\b',                     'Proxmox: LXC status by VMID'),
    # ── Kernel diagnostics ────────────────────────────────────────────────────
    (r'^dmesg\b',                          'Kernel ring buffer (OOM, hardware errors)'),
    (r'^docker service ps\b',          'Swarm service task list'),
    (r'^docker service inspect\b',     'Swarm service details'),
    (r'^docker node inspect\b',        'Swarm node details'),
    (r'^docker node ls\b',             'Swarm node list'),
    # ── Package management (read) ─────────────────────────────────────────────
    (r'^apt list',                     'APT package list'),
    (r'^apt-cache\b',                  'APT package cache query'),
    # ── Systemd ──────────────────────────────────────────────────────────────
    (r'^systemctl list',               'List systemd units'),
    (r'^systemctl status\b',           'Systemd service status'),
    (r'^journalctl\b',                 'Systemd journal'),
    # ── File / text tools ─────────────────────────────────────────────────────
    (r'^cat /etc/os-release$',         'OS release info'),
    (r'^cat /proc/[\w/]+$',            'Kernel proc file'),
    (r'^ls\b',                         'List directory'),
    (r'^stat\b',                       'File/dir metadata'),
    (r'^find\b',                       'Find files'),
    (r'^wc\b',                         'Word/line count'),
    (r'^sort\b',                       'Sort input'),
    (r'^head\b',                       'First N lines'),
    (r'^tail\b',                       'Last N lines'),
    (r'^grep\b',                       'Pattern search'),
    (r'^awk\b',                        'Text processing'),
    (r'^cut\b',                        'Cut fields'),
    (r'^xargs\b',                      'Build command from stdin'),
    (r'^timeout\b',                    'Run command with timeout'),
    # ── Write (require plan_action approval via agent prompt) ─────────────────
    (r'^docker image prune\b',         'Remove unused Docker images'),
    (r'^docker container prune\b',     'Remove stopped Docker containers'),
    (r'^docker volume prune\b',        'Remove unused Docker volumes'),
    (r'^docker system prune\b',        'Remove unused Docker objects'),
    (r'^docker builder prune\b',       'Remove Docker build cache'),
    (r'^journalctl --vacuum',          'Vacuum journal logs'),
    (r'^apt-get autoremove\b',         'Remove unused packages'),
    (r'^apt-get clean$',               'Clean APT cache'),
    (r'^apt-get autoclean$',           'Clean old APT cache'),
]


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_allowlist():
    """Create table and seed base patterns. Called on startup."""
    global _initialized
    if _initialized:
        return
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        for stmt in _DDL.strip().split(";"):
            s = stmt.strip()
            if s:
                cur.execute(s)
        # Seed base patterns (idempotent — ON CONFLICT DO NOTHING)
        for pattern, description in BASE_PATTERNS:
            cur.execute(
                """INSERT INTO vm_exec_allowlist
                   (id, pattern, description, scope, is_base, added_by)
                   VALUES (%s, %s, %s, 'permanent', TRUE, 'system')
                   ON CONFLICT (pattern) DO NOTHING""",
                (str(uuid.uuid4()), pattern, description),
            )
        cur.close()
        conn.close()
        _initialized = True
        log.info("vm_exec_allowlist table ready (%d base patterns)", len(BASE_PATTERNS))
    except Exception as e:
        log.warning("vm_exec_allowlist init failed (will use hardcoded base): %s", e)


def get_patterns(session_id: str = "") -> list[str]:
    """Return all active regex patterns: base + permanent + session-scoped for this session.

    Cached for _CACHE_TTL seconds. Falls back to BASE_PATTERNS if DB unavailable.
    """
    global _cache, _cache_ts
    now = time.monotonic()
    if _cache and (now - _cache_ts) < _CACHE_TTL:
        return _cache

    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        if session_id:
            cur.execute(
                """SELECT pattern FROM vm_exec_allowlist
                   WHERE scope = 'permanent'
                      OR (scope = 'session' AND session_id = %s)
                   ORDER BY is_base DESC, created_at""",
                (session_id,),
            )
        else:
            cur.execute(
                "SELECT pattern FROM vm_exec_allowlist WHERE scope = 'permanent' ORDER BY is_base DESC, created_at"
            )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        _cache = [r[0] for r in rows]
        _cache_ts = now
        return _cache
    except Exception as e:
        log.debug("get_patterns DB failed, using base: %s", e)
        return [p for p, _ in BASE_PATTERNS]


def invalidate_cache():
    """Force cache refresh on next get_patterns() call."""
    global _cache_ts
    _cache_ts = 0.0


def add_pattern(pattern: str, description: str, scope: str = "permanent",
                session_id: str = "", added_by: str = "agent",
                approved_by: str = "") -> dict:
    """Add a new pattern. Returns {ok, id} or {ok: False, error}."""
    if scope not in ("permanent", "session"):
        return {"ok": False, "error": "scope must be 'permanent' or 'session'"}
    if not pattern.strip():
        return {"ok": False, "error": "pattern is required"}
    pid = str(uuid.uuid4())
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO vm_exec_allowlist
               (id, pattern, description, scope, session_id, added_by, approved_by, is_base)
               VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE)
               ON CONFLICT (pattern) DO UPDATE SET
                 scope=EXCLUDED.scope, session_id=EXCLUDED.session_id,
                 approved_by=EXCLUDED.approved_by, added_by=EXCLUDED.added_by""",
            (pid, pattern, description, scope, session_id or "", added_by, approved_by or ""),
        )
        conn.commit()
        cur.close()
        conn.close()
        invalidate_cache()
        log.info("vm_exec_allowlist: added pattern %r scope=%s by %s", pattern, scope, added_by)
        return {"ok": True, "id": pid, "pattern": pattern, "scope": scope}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def remove_pattern(pattern_id: str, actor: str = "admin") -> dict:
    """Remove a non-base pattern by ID."""
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT is_base, pattern FROM vm_exec_allowlist WHERE id = %s", (pattern_id,))
        row = cur.fetchone()
        if not row:
            cur.close(); conn.close()
            return {"ok": False, "error": "Pattern not found"}
        if row[0]:  # is_base
            cur.close(); conn.close()
            return {"ok": False, "error": "Cannot remove base patterns"}
        cur.execute("DELETE FROM vm_exec_allowlist WHERE id = %s", (pattern_id,))
        conn.commit()
        cur.close()
        conn.close()
        invalidate_cache()
        log.info("vm_exec_allowlist: removed pattern %r by %s", row[1], actor)
        return {"ok": True, "pattern": row[1]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def list_all(include_base: bool = True) -> list[dict]:
    """Return all patterns with metadata."""
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        if include_base:
            cur.execute(
                "SELECT id, pattern, description, scope, session_id, added_by, approved_by, is_base, created_at"
                " FROM vm_exec_allowlist ORDER BY is_base DESC, created_at"
            )
        else:
            cur.execute(
                "SELECT id, pattern, description, scope, session_id, added_by, approved_by, is_base, created_at"
                " FROM vm_exec_allowlist WHERE NOT is_base ORDER BY created_at"
            )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close()
        conn.close()
        for r in rows:
            if r.get("created_at"):
                try:
                    r["created_at"] = r["created_at"].isoformat()
                except Exception:
                    pass
        return rows
    except Exception as e:
        log.debug("list_all failed: %s", e)
        return [{"pattern": p, "description": d, "scope": "permanent", "is_base": True}
                for p, d in BASE_PATTERNS]


def purge_session(session_id: str) -> int:
    """Delete all session-scoped entries for a completed session. Returns count deleted."""
    if not session_id:
        return 0
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM vm_exec_allowlist WHERE scope = 'session' AND session_id = %s",
            (session_id,),
        )
        count = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        if count:
            invalidate_cache()
            log.info("vm_exec_allowlist: purged %d session entries for %s", count, session_id)
        return count
    except Exception as e:
        log.debug("purge_session failed: %s", e)
        return 0
