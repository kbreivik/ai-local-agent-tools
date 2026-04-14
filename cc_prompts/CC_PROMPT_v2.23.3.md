# CC PROMPT — v2.23.3 — DB-backed vm_exec allowlist + session/permanent approval flow

## What this does
The vm_exec allowlist is hardcoded in vm.py with no management UI and no mechanism for
the agent to request approval when a command is blocked. This blocked `ss -tlnp` and
`docker port` during a legitimate Kafka port investigation.

Five changes: (1) New `api/db/vm_exec_allowlist.py` — Postgres-backed allowlist table,
seeded from hardcoded base patterns, with session/permanent scopes. (2) Expand the
hardcoded base with missing network/Docker diagnostics (`ss`, `nc`, `netstat`, `ip`,
`docker port`, `docker network`, etc.). (3) Modify `_validate_command` in vm.py to load
DB patterns (60s cache), and return a structured blocked response with a pattern
suggestion. (4) Add three new MCP tools: `vm_exec_allowlist_request`, `vm_exec_allowlist_add`,
`vm_exec_allowlist_list` — enabling agent to request approval and add patterns with the
plan_action gate. (5) Add a new "Allowlist" tab to OptionsModal showing all patterns with
scope, source, who added them, and controls to add/remove custom patterns.
Version bump: 2.23.2 → 2.23.3

---

## Change 1 — api/db/vm_exec_allowlist.py (NEW FILE)

Create this file at `api/db/vm_exec_allowlist.py`:

```python
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
    (r'^curl\s+-[sSmIf]+\b',           'Curl with safe flags (no file writes)'),
    (r'^dig\b',                        'DNS lookup'),
    (r'^nslookup\b',                   'DNS lookup (legacy)'),
    (r'^host\b',                       'DNS lookup'),
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
```

---

## Change 2 — api/routers/vm_exec_allowlist.py (NEW FILE)

Create `api/routers/vm_exec_allowlist.py`:

```python
"""GET/POST/DELETE /api/vm-exec-allowlist — manage the vm_exec command allowlist."""
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from api.auth import get_current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/vm-exec-allowlist", tags=["vm-exec-allowlist"])


class AddPatternRequest(BaseModel):
    pattern: str
    description: str
    scope: str = "permanent"   # 'permanent' | 'session'
    session_id: str = ""


@router.get("")
def list_allowlist(_: str = Depends(get_current_user)):
    from api.db.vm_exec_allowlist import list_all
    return {"patterns": list_all(include_base=True)}


@router.post("")
def add_pattern(body: AddPatternRequest, user: str = Depends(get_current_user)):
    from api.db.vm_exec_allowlist import add_pattern as _add
    result = _add(body.pattern, body.description, body.scope,
                  body.session_id, added_by=user, approved_by=user)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Failed to add pattern"))
    return {"status": "ok", "data": result}


@router.delete("/{pattern_id}")
def delete_pattern(pattern_id: str, user: str = Depends(get_current_user)):
    from api.db.vm_exec_allowlist import remove_pattern as _remove
    result = _remove(pattern_id, actor=user)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Failed to remove pattern"))
    return {"status": "ok", "data": result}
```

---

## Change 3 — api/main.py: Init table + register router

In the lifespan function, add after the VM action log init block:

```python
    # Initialize vm_exec allowlist table
    try:
        from api.db.vm_exec_allowlist import init_allowlist
        init_allowlist()
    except Exception as e:
        _log.debug("vm_exec_allowlist init skipped: %s", e)
```

At the top of the file, add the import with the other router imports:
```python
from api.routers.vm_exec_allowlist import router as vm_exec_allowlist_router
```

In the router registration section, add:
```python
app.include_router(vm_exec_allowlist_router)
```

---

## Change 4 — mcp_server/tools/vm.py: Rewrite _validate_command + add three tools

### 4a. Replace _validate_command entirely

Replace the entire `_validate_command` function with this version that loads from DB
(60s cache), returns a structured blocked response, and suggests a pattern:

```python
def _suggest_pattern(segment: str) -> str:
    """Generate a safe regex pattern suggestion for a blocked command segment."""
    import re as _re
    # Take the first word (command name)
    first_word = segment.strip().split()[0] if segment.strip() else segment
    # Escape for regex, anchor at start
    return r'^' + _re.escape(first_word) + r'\b'


def _load_allowlist(session_id: str = "") -> list[str]:
    """Load allowlist patterns from DB (cached 30s). Falls back to base patterns."""
    try:
        from api.db.vm_exec_allowlist import get_patterns
        return get_patterns(session_id=session_id)
    except Exception:
        # Fallback: hardcoded base patterns (avoids import of DB module at module level)
        try:
            from api.db.vm_exec_allowlist import BASE_PATTERNS
            return [p for p, _ in BASE_PATTERNS]
        except Exception:
            return []


def _validate_command(command: str, session_id: str = "") -> tuple:
    """Validate a command against the allowlist (DB-backed, 30s cache).

    Returns:
        (True, cleaned_command)  — command is allowed
        (False, error_dict)      — command blocked; error_dict has:
            {"blocked": True, "message": str, "segment": str,
             "pattern_suggestion": str, "hint": str}
        (False, error_str)       — shell metachar rejected (not a pattern issue)
    """
    import re as _re

    # Strip '2>/dev/null' before metachar check — safe stderr discard.
    cleaned = _re.sub(r'\s*2>/dev/null', '', command).strip()

    # Strip Go template --format arguments before metachar check.
    sanitized = _re.sub(r"""--format\s+['"]?\{\{[^'"]*\}\}['"]?""", '--format TEMPLATE', cleaned)

    # Block remaining shell injection chars
    if any(c in sanitized for c in [';', '`', '$', '>', '<', '&&', '||']):
        return False, f"Shell metacharacters not allowed: {command!r}"

    # Split on pipe — allow up to 3 segments
    parts = [p.strip() for p in sanitized.split('|')]
    if len(parts) > 3:
        return False, "Maximum two pipes allowed (e.g. cmd | sort -hr | head -20)"

    allowlist = _load_allowlist(session_id=session_id)

    for part in parts:
        if not any(_re.match(p, part) for p in allowlist):
            suggestion = _suggest_pattern(part)
            return False, {
                "blocked": True,
                "segment": part,
                "pattern_suggestion": suggestion,
                "message": (
                    f"Command segment not in allowlist: {part!r}. "
                    "Call vm_exec_allowlist_request() to request approval for this session "
                    "or permanent addition."
                ),
                "hint": (
                    f"Call vm_exec_allowlist_request(command={command!r}, "
                    f"reason='<why you need this>', scope='session') "
                    f"then plan_action() then vm_exec_allowlist_add(pattern={suggestion!r}, ...)"
                ),
            }

    return True, cleaned
```

### 4b. Update vm_exec to handle the new blocked response

Find the block in `vm_exec` that handles the invalid command:
```python
    valid, result_or_error = _validate_command(command)
    if not valid:
        return {"status": "error", "message": result_or_error, "data": None, "timestamp": _ts()}
```

Replace with:
```python
    valid, result_or_error = _validate_command(command)
    if not valid:
        if isinstance(result_or_error, dict) and result_or_error.get("blocked"):
            return {
                "status": "blocked",
                "message": result_or_error["message"],
                "data": {
                    "command": command,
                    "blocked_segment": result_or_error.get("segment", ""),
                    "pattern_suggestion": result_or_error.get("pattern_suggestion", ""),
                    "hint": result_or_error.get("hint", ""),
                },
                "timestamp": _ts(),
            }
        return {"status": "error", "message": result_or_error, "data": None, "timestamp": _ts()}
```

### 4c. Add three new tools at end of vm.py

Add after the `ssh_capabilities` function and before `resolve_entity`:

```python
def vm_exec_allowlist_request(command: str, reason: str, scope: str = "session") -> dict:
    """Request approval to add a blocked command to the vm_exec allowlist.

    Call this when vm_exec returns status='blocked'. It suggests a regex pattern
    and returns instructions for the approval flow.

    Flow after calling this tool:
    1. Call plan_action() with the suggested pattern and reason
    2. After user approves, call vm_exec_allowlist_add() with the pattern
    3. Retry vm_exec() with the original command

    Args:
        command: The full command that was blocked (e.g. "ss -tlnp")
        reason:  Why this command is needed for the current task
        scope:   'session' (expires when this session ends) or 'permanent' (persists)
    """
    if scope not in ("session", "permanent"):
        scope = "session"

    suggestion = _suggest_pattern(command.strip().split()[0] if command.strip() else command)

    # Also try to load similar existing patterns for context
    existing_context = ""
    try:
        from api.db.vm_exec_allowlist import list_all
        patterns = list_all(include_base=True)
        similar = [p["pattern"] for p in patterns
                   if command.strip().split()[0].lower() in p.get("description", "").lower()]
        if similar:
            existing_context = f" (similar patterns already allowed: {similar[:2]})"
    except Exception:
        pass

    scope_note = (
        "This session only — pattern will be deleted when the session ends."
        if scope == "session" else
        "Permanent — pattern will persist across sessions and be visible in Settings → Allowlist."
    )

    return {
        "status": "ok",
        "message": f"Allowlist request prepared for: {command!r}",
        "data": {
            "command": command,
            "reason": reason,
            "scope": scope,
            "scope_note": scope_note,
            "suggested_pattern": suggestion,
            "existing_context": existing_context,
            "next_steps": [
                f"1. Call plan_action(summary='Add {command!r} to vm_exec allowlist ({scope})', "
                f"steps=['Add pattern: {suggestion}', 'Scope: {scope}', 'Reason: {reason}'], "
                f"risk_level='low', reversible=True)",
                f"2. After approval: call vm_exec_allowlist_add(pattern={suggestion!r}, "
                f"description={reason!r}, scope={scope!r})",
                "3. Retry: call vm_exec() with the original command",
            ],
        },
        "timestamp": _ts(),
    }


def vm_exec_allowlist_add(pattern: str, description: str,
                          scope: str = "session", session_id: str = "") -> dict:
    """Add a pattern to the vm_exec allowlist after plan_action approval.

    Only call this AFTER the user has approved via plan_action().
    For session scope, the pattern is automatically deleted when the session ends.
    For permanent scope, it persists and appears in Settings → Allowlist.

    Args:
        pattern:     Regex pattern to allow (e.g. r'^ss\\b'). Use the suggested_pattern
                     from vm_exec_allowlist_request().
        description: Human-readable description of what the pattern allows.
        scope:       'session' (expires with this session) or 'permanent' (persists).
        session_id:  Current session ID (required for session scope — use the session_id
                     from the current agent context if known, or leave blank).
    """
    import re as _re
    # Validate the pattern compiles
    try:
        _re.compile(pattern)
    except _re.error as e:
        return {"status": "error", "message": f"Invalid regex pattern: {e}",
                "data": None, "timestamp": _ts()}

    try:
        from api.db.vm_exec_allowlist import add_pattern
        result = add_pattern(
            pattern=pattern,
            description=description,
            scope=scope,
            session_id=session_id,
            added_by="agent",
            approved_by="user",
        )
        if result.get("ok"):
            return {
                "status": "ok",
                "message": f"Pattern {pattern!r} added ({scope}). Retry vm_exec() now.",
                "data": result,
                "timestamp": _ts(),
            }
        return {"status": "error", "message": result.get("error", "Failed to add pattern"),
                "data": None, "timestamp": _ts()}
    except Exception as e:
        return {"status": "error", "message": str(e), "data": None, "timestamp": _ts()}


def vm_exec_allowlist_list() -> dict:
    """Show all vm_exec allowlist patterns — base (built-in) and custom (user-added).

    Use to understand what commands are currently allowed before attempting vm_exec,
    or to verify a pattern was successfully added after vm_exec_allowlist_add().
    """
    try:
        from api.db.vm_exec_allowlist import list_all
        patterns = list_all(include_base=True)
        base = [p for p in patterns if p.get("is_base")]
        custom = [p for p in patterns if not p.get("is_base")]
        session = [p for p in custom if p.get("scope") == "session"]
        permanent = [p for p in custom if p.get("scope") == "permanent"]
        return {
            "status": "ok",
            "message": f"{len(patterns)} patterns ({len(base)} base, {len(permanent)} custom permanent, {len(session)} session)",
            "data": {
                "total": len(patterns),
                "base_count": len(base),
                "custom_permanent": permanent,
                "custom_session": session,
                "base_sample": [p["pattern"] for p in base[:10]],
            },
            "timestamp": _ts(),
        }
    except Exception as e:
        return {"status": "error", "message": f"vm_exec_allowlist_list failed: {e}",
                "data": None, "timestamp": _ts()}
```

---

## Change 5 — api/agents/router.py: Add new tools to allowlists

Find `OBSERVE_AGENT_TOOLS` and `INVESTIGATE_AGENT_TOOLS` frozensets.
Add to both:
```python
    "vm_exec_allowlist_list",
    "vm_exec_allowlist_request",
```

Find `EXECUTE_GENERAL_TOOLS`, `EXECUTE_KAFKA_TOOLS`, `EXECUTE_SWARM_TOOLS`,
`EXECUTE_PROXMOX_TOOLS` (all execute-type allowlists).
Add to all four:
```python
    "vm_exec_allowlist_list",
    "vm_exec_allowlist_request",
    "vm_exec_allowlist_add",
```

Also add `vm_exec_allowlist_request` and `vm_exec_allowlist_add` to `BUILD_AGENT_TOOLS`
if it exists.

---

## Change 6 — api/routers/agent.py: Purge session allowlist on session end

In `_stream_agent`, at the very end of the `finally` block (after `complete_operation`),
add session allowlist cleanup:

```python
        # Purge session-scoped allowlist entries for this session
        try:
            from api.db.vm_exec_allowlist import purge_session
            purge_session(session_id)
        except Exception as _al_e:
            log.debug("allowlist session purge failed: %s", _al_e)
```

---

## Change 7 — gui/src/components/OptionsModal.jsx: Add "Allowlist" tab

### 7a. Add "Allowlist" to TABS array

Find:
```javascript
export const TABS = ['General', 'Infrastructure', 'AI Services', 'Connections', 'Permissions', 'Access', 'Naming', 'Display', 'Notifications', 'Layouts']
```

Replace with:
```javascript
export const TABS = ['General', 'Infrastructure', 'AI Services', 'Connections', 'Allowlist', 'Permissions', 'Access', 'Naming', 'Display', 'Notifications', 'Layouts']
```

### 7b. Add AllowlistTab component

Add this component before the OptionsModal root export function:

```javascript
// ── Tab: Allowlist ────────────────────────────────────────────────────────────

function AllowlistTab() {
  const [patterns, setPatterns] = useState([])
  const [loading, setLoading] = useState(true)
  const [addOpen, setAddOpen] = useState(false)
  const [form, setForm] = useState({ pattern: '', description: '', scope: 'permanent' })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const fetchPatterns = () => {
    setLoading(true)
    fetch(`${BASE}/api/vm-exec-allowlist`, { headers: { ...authHeaders() } })
      .then(r => r.ok ? r.json() : { patterns: [] })
      .then(d => { setPatterns(d.patterns || []); setLoading(false) })
      .catch(() => setLoading(false))
  }

  useEffect(() => { fetchPatterns() }, [])

  const save = async () => {
    if (!form.pattern.trim() || !form.description.trim()) {
      setError('Pattern and description are required'); return
    }
    setSaving(true); setError('')
    try {
      const r = await fetch(`${BASE}/api/vm-exec-allowlist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(form),
      })
      if (r.ok) {
        setForm({ pattern: '', description: '', scope: 'permanent' })
        setAddOpen(false)
        fetchPatterns()
      } else {
        const d = await r.json()
        setError(d.detail || 'Failed to add pattern')
      }
    } catch (e) { setError(e.message) }
    setSaving(false)
  }

  const remove = async (id) => {
    if (!window.confirm('Remove this pattern?')) return
    await fetch(`${BASE}/api/vm-exec-allowlist/${id}`, {
      method: 'DELETE', headers: { ...authHeaders() }
    })
    fetchPatterns()
  }

  const base = patterns.filter(p => p.is_base)
  const custom = patterns.filter(p => !p.is_base)
  const session = custom.filter(p => p.scope === 'session')
  const permanent = custom.filter(p => p.scope === 'permanent')

  const _scopeBadge = (p) => {
    if (p.is_base) return { label: 'base', bg: 'var(--bg-3)', color: 'var(--text-3)' }
    if (p.scope === 'session') return { label: 'session', bg: 'rgba(0,200,238,0.12)', color: 'var(--cyan)' }
    return { label: 'permanent', bg: 'rgba(0,170,68,0.12)', color: 'var(--green)' }
  }

  return (
    <div>
      <p className="text-xs mb-3" style={{ color: 'var(--text-3)' }}>
        Commands the agent can run via <code className="text-xs">vm_exec</code>. Base patterns are built-in.
        Custom patterns can be added permanently or per-session (auto-deleted when agent session ends).
        The agent can also request approval via <code className="text-xs">vm_exec_allowlist_request()</code>.
      </p>

      {/* Summary */}
      <div className="flex gap-4 mb-4 text-xs" style={{ color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
        <span><span style={{ color: 'var(--text-1)' }}>{base.length}</span> base</span>
        <span><span style={{ color: 'var(--green)' }}>{permanent.length}</span> custom permanent</span>
        <span><span style={{ color: 'var(--cyan)' }}>{session.length}</span> session</span>
      </div>

      {/* Add button */}
      <div className="flex justify-between items-center mb-3">
        <span className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
          CUSTOM PATTERNS
        </span>
        <button
          onClick={() => setAddOpen(o => !o)}
          className="text-[10px] px-2 py-1 rounded"
          style={{ background: 'var(--accent-dim)', color: 'var(--accent)', border: '1px solid var(--accent)' }}
        >
          {addOpen ? '✕ Cancel' : '+ Add Pattern'}
        </button>
      </div>

      {/* Add form */}
      {addOpen && (
        <div className="mb-4 p-3 rounded" style={{ background: 'var(--bg-2)', border: '1px solid var(--border)' }}>
          <div className="mb-2">
            <label className="text-[10px] block mb-1" style={{ color: 'var(--text-3)' }}>Regex pattern</label>
            <input
              className="w-full text-[10px] px-2 py-1 rounded"
              style={{ background: 'var(--bg-3)', border: '1px solid var(--border)', color: 'var(--text-1)', fontFamily: 'var(--font-mono)' }}
              placeholder={String.raw`^ss\b`}
              value={form.pattern}
              onChange={e => setForm(f => ({ ...f, pattern: e.target.value }))}
            />
          </div>
          <div className="mb-2">
            <label className="text-[10px] block mb-1" style={{ color: 'var(--text-3)' }}>Description</label>
            <input
              className="w-full text-[10px] px-2 py-1 rounded"
              style={{ background: 'var(--bg-3)', border: '1px solid var(--border)', color: 'var(--text-1)' }}
              placeholder="Socket statistics (ss -tlnp)"
              value={form.description}
              onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
            />
          </div>
          <div className="mb-3">
            <label className="text-[10px] block mb-1" style={{ color: 'var(--text-3)' }}>Scope</label>
            <div className="flex gap-3">
              {[['permanent', 'Permanent'], ['session', 'Session only']].map(([v, l]) => (
                <label key={v} className="flex items-center gap-1.5 cursor-pointer text-[10px]" style={{ color: 'var(--text-1)' }}>
                  <input type="radio" value={v} checked={form.scope === v} onChange={() => setForm(f => ({ ...f, scope: v }))} />
                  {l}
                </label>
              ))}
            </div>
          </div>
          {error && <div className="text-[10px] mb-2" style={{ color: 'var(--red)' }}>{error}</div>}
          <button
            onClick={save} disabled={saving}
            className="text-[10px] px-3 py-1 rounded"
            style={{ background: 'var(--accent)', color: '#fff', opacity: saving ? 0.5 : 1 }}
          >
            {saving ? 'Adding…' : 'Add Pattern'}
          </button>
        </div>
      )}

      {/* Custom patterns */}
      {custom.length === 0 && !addOpen && (
        <div className="text-[10px] mb-4" style={{ color: 'var(--text-3)' }}>
          No custom patterns. The agent can request additions via <code>vm_exec_allowlist_request()</code>.
        </div>
      )}
      {custom.map(p => {
        const badge = _scopeBadge(p)
        return (
          <div key={p.id} className="flex items-start justify-between mb-2 p-2 rounded"
               style={{ background: 'var(--bg-2)', border: '1px solid var(--border)' }}>
            <div className="min-w-0">
              <div className="flex items-center gap-2 mb-0.5">
                <span className="text-[10px]" style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-1)' }}>{p.pattern}</span>
                <span className="text-[8px] px-1.5 py-px rounded" style={{ background: badge.bg, color: badge.color }}>{badge.label}</span>
              </div>
              <div className="text-[9px]" style={{ color: 'var(--text-3)' }}>
                {p.description}
                {p.added_by && p.added_by !== 'system' && ` · added by ${p.added_by}`}
                {p.approved_by && ` · approved by ${p.approved_by}`}
              </div>
            </div>
            <button
              onClick={() => remove(p.id)}
              className="text-[9px] ml-2 flex-shrink-0"
              style={{ color: 'var(--red)', background: 'none', border: 'none', cursor: 'pointer' }}
            >✕</button>
          </div>
        )
      })}

      {/* Base patterns (collapsible) */}
      <details className="mt-4">
        <summary className="text-[10px] cursor-pointer" style={{ color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
          BASE PATTERNS ({base.length}) — built-in, read-only ▾
        </summary>
        <div className="mt-2 space-y-1">
          {base.map(p => (
            <div key={p.pattern} className="flex items-center gap-2 px-2 py-1 rounded"
                 style={{ background: 'var(--bg-2)' }}>
              <span className="text-[9px] flex-1" style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-3)' }}>{p.pattern}</span>
              <span className="text-[9px]" style={{ color: 'var(--text-3)' }}>{p.description}</span>
            </div>
          ))}
        </div>
      </details>

      {loading && <div className="text-[10px] mt-2" style={{ color: 'var(--text-3)' }}>Loading…</div>}
    </div>
  )
}
```

### 7c. Wire AllowlistTab into the modal render block

Find the tab content render block in OptionsModal. It contains lines like:
```javascript
                {tab === 'Connections'    && <ConnectionsTab />}
                {tab === 'Permissions'    && <PermissionsTab />}
```

Add between them:
```javascript
                {tab === 'Allowlist'      && <AllowlistTab />}
```

Also add `AllowlistTab` to the named exports at the bottom of the file if there is an
existing export list:
```javascript
export { GeneralTab, InfrastructureTab, AIServicesTab, ConnectionsTab, AllowlistTab, PermissionsTab, AccessTab, NamingTab, DisplayTab, UpdateStatus }
```

---

## Version bump

Update `VERSION`: `2.23.2` → `2.23.3`

---

## Commit

```
git add -A
git commit -m "feat(vm-exec): DB-backed allowlist + session/permanent approval flow + UI"
git push origin main
```
