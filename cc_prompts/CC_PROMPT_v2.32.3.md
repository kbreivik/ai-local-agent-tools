# CC PROMPT — v2.32.3 — Attempt history table + context injection

## What this does
Creates an `agent_attempts` table that records what the agent tried on each entity and
whether it worked. Before each agent run, the harness queries last 3 attempts for the
detected entity and injects them into the system prompt as context. This prevents the
agent from repeating the same failed approach and enables it to escalate when a pattern
of failures is detected.

This addresses the "premature completion" and "one-shotting" failure modes from the
harness engineering research — agent tries same approach repeatedly without learning.

Version bump: 2.32.2 → 2.32.3

## Change 1 — api/db/agent_attempts.py — New file

Create `api/db/agent_attempts.py`:

```python
"""Agent attempt history — tracks what was tried on each entity and whether it worked."""
import json
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_TABLE = "agent_attempts"


def init_agent_attempts():
    """Create the agent_attempts table if it doesn't exist."""
    from api.db.base import get_sync_conn
    conn = get_sync_conn()
    try:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {_TABLE} (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                entity_id   TEXT NOT NULL,
                task_type   TEXT NOT NULL DEFAULT 'general',
                task_text   TEXT NOT NULL DEFAULT '',
                tools_used  TEXT NOT NULL DEFAULT '[]',
                outcome     TEXT NOT NULL DEFAULT 'unknown',
                summary     TEXT NOT NULL DEFAULT '',
                session_id  TEXT NOT NULL DEFAULT '',
                operation_id TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_attempts_entity
            ON {_TABLE} (entity_id, created_at DESC)
        """)
        conn.commit()
    except Exception as e:
        log.debug("init_agent_attempts failed: %s", e)
    finally:
        conn.close()


def record_attempt(
    *,
    entity_id: str,
    task_type: str = "general",
    task_text: str = "",
    tools_used: list[str] | None = None,
    outcome: str = "unknown",
    summary: str = "",
    session_id: str = "",
    operation_id: str = "",
):
    """Record an agent attempt on an entity. Never raises."""
    from api.db.base import get_sync_conn
    try:
        conn = get_sync_conn()
        conn.execute(
            f"""INSERT INTO {_TABLE}
                (entity_id, task_type, task_text, tools_used, outcome, summary,
                 session_id, operation_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entity_id[:200],
                task_type[:50],
                task_text[:500],
                json.dumps(tools_used or []),
                outcome[:20],
                summary[:500],
                session_id[:128],
                operation_id[:128],
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.debug("record_attempt failed: %s", e)


def get_recent_attempts(entity_id: str, limit: int = 3) -> list[dict]:
    """Return last N attempts for an entity, newest first."""
    from api.db.base import get_sync_conn
    try:
        conn = get_sync_conn()
        rows = conn.execute(
            f"""SELECT created_at, task_type, tools_used, outcome, summary
                FROM {_TABLE}
                WHERE entity_id = ?
                ORDER BY created_at DESC
                LIMIT ?""",
            (entity_id, limit),
        ).fetchall()
        conn.close()
        return [
            {
                "when": r[0],
                "task_type": r[1],
                "tools": json.loads(r[2]) if r[2] else [],
                "outcome": r[3],
                "summary": r[4],
            }
            for r in rows
        ]
    except Exception:
        return []


def _prune_old(days: int = 30):
    """Delete attempts older than N days. Called periodically."""
    from api.db.base import get_sync_conn
    try:
        conn = get_sync_conn()
        conn.execute(
            f"DELETE FROM {_TABLE} WHERE created_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
```

## Change 2 — api/main.py — Initialize the table on startup

In the `lifespan` function, after the existing `init_*` calls (near `init_agent_actions`),
add:

```python
    from api.db.agent_attempts import init_agent_attempts
    init_agent_attempts()
```

## Change 3 — api/routers/agent.py — Inject attempt history into agent context

In the `_stream_agent` function, find the section that does entity history context
injection. It starts with the comment:

```python
    # ── Entity history context injection ──────────────────────────────
```

AFTER that entire try/except block (the one that injects entity history into
`system_prompt`), add a NEW try/except block:

```python
    # ── Attempt history context injection (v2.32.3) ───────────────────
    # If task mentions a known entity, inject previous agent attempts as context
    try:
        from api.db.agent_attempts import get_recent_attempts
        from api.db.infra_inventory import resolve_host
        from api.agents.router import detect_domain

        _attempt_entity = None
        _attempt_lines = []

        # Try to resolve an entity from the task text
        for word in task.split():
            if len(word) < 4:
                continue
            entry = resolve_host(word)
            if entry:
                _attempt_entity = entry.get("label", word)
                break

        # Also try domain-level entity (kafka_cluster, swarm_cluster)
        if not _attempt_entity:
            domain = detect_domain(task)
            if domain == "kafka":
                _attempt_entity = "kafka_cluster"
            elif domain == "swarm":
                _attempt_entity = "swarm_cluster"

        if _attempt_entity:
            attempts = get_recent_attempts(_attempt_entity, limit=3)
            if attempts:
                _attempt_lines.append(f"PREVIOUS AGENT ATTEMPTS on {_attempt_entity} (last {len(attempts)}):")
                for i, a in enumerate(attempts, 1):
                    tools_str = ", ".join(a["tools"][:4]) if a["tools"] else "none"
                    _attempt_lines.append(
                        f"  [{i}] {a['when'][:16]} | {a['outcome']} | tools: {tools_str}"
                        f"{' | ' + a['summary'][:80] if a['summary'] else ''}"
                    )
                _attempt_lines.append(
                    "If previous attempts failed with the same approach, try a different strategy.\n"
                )
                attempt_hint = "\n".join(_attempt_lines) + "\n"
                from api.security.prompt_sanitiser import sanitise
                attempt_hint, _ = sanitise(attempt_hint, max_chars=1000, source_hint="attempt_history")
                system_prompt = attempt_hint + system_prompt
    except Exception:
        pass
```

## Change 4 — api/routers/agent.py — Record attempt after agent run completes

In the `_stream_agent` function, find the cleanup section at the end (the `finally` block
or the section after the step loop that records outcomes). After the `record_outcome` call:

```python
        try:
            from api.memory.feedback import record_outcome
            await record_outcome(...)
        except Exception as _oe:
            log.debug("record_outcome error: %s", _oe)
```

Add immediately after that try/except block:

```python
        # v2.32.3: Record attempt history for the detected entity
        try:
            from api.db.agent_attempts import record_attempt
            from api.db.infra_inventory import resolve_host
            from api.agents.router import detect_domain

            _rec_entity = None
            for word in task.split():
                if len(word) < 4:
                    continue
                entry = resolve_host(word)
                if entry:
                    _rec_entity = entry.get("label", word)
                    break
            if not _rec_entity:
                domain = detect_domain(task)
                if domain == "kafka":
                    _rec_entity = "kafka_cluster"
                elif domain == "swarm":
                    _rec_entity = "swarm_cluster"

            if _rec_entity:
                # Deduplicate tool names, preserve order
                _seen = set()
                _dedup_tools = []
                for t in all_tools_used:
                    if t not in _seen:
                        _seen.add(t)
                        _dedup_tools.append(t)

                record_attempt(
                    entity_id=_rec_entity,
                    task_type=first_intent,
                    task_text=task[:500],
                    tools_used=_dedup_tools[:10],
                    outcome=final_status,
                    summary=(last_reasoning or "")[:500] if isinstance(last_reasoning, str) else "",
                    session_id=session_id,
                    operation_id=operation_id if 'operation_id' in dir() else "",
                )
        except Exception as _ae:
            log.debug("record_attempt failed: %s", _ae)
```

## Version bump

Update VERSION file: 2.32.2 → 2.32.3

## Commit

```bash
git add -A
git commit -m "feat(agents): v2.32.3 attempt history table + context injection

New agent_attempts table records entity_id, task_type, tools_used,
outcome, and summary after every agent run. Before each new run, the
harness queries last 3 attempts for the detected entity and injects
them into the system prompt.

This prevents repeated failures with the same approach and enables
the agent to vary its strategy based on what was already tried.

- api/db/agent_attempts.py: init, record, query, prune functions
- api/main.py: init_agent_attempts() in lifespan
- api/routers/agent.py: inject attempt context + record after run"
git push origin main
```
