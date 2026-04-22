# CC PROMPT — v2.40.4 — refactor(agents): extract context-building helpers into api/agents/context.py

## What this does

Second pass of the agent.py split. Extracts context-injection helpers that
build the system prompt from various sources (preflight, entity history, RAG,
MuninnDB, attempt history) into `api/agents/context.py`.

Functions to move from agent.py:
- `_build_prerun_external_context()`   (line ~806)
- `_extract_working_memory()`          (line ~611)
- `_build_subagent_context()`          (line ~3724)

These are pure or near-pure — they read from DB/files and return strings.
No side effects, no WebSocket calls, no LLM calls.

Version bump: 2.40.3 → 2.40.4.

---

## Change 1 — create `api/agents/context.py`

Create new file `api/agents/context.py`:

```python
"""Agent context-building helpers — v2.40.4.

Extracted from api/routers/agent.py.

Provides functions that assemble context blocks for injection into
agent system prompts. All functions are sync, pure or near-pure
(DB reads only, no side effects).

Imported back into agent.py:
    from api.agents.context import (
        _build_prerun_external_context,
        _extract_working_memory,
        _build_subagent_context,
    )
"""
from __future__ import annotations
import logging

log = logging.getLogger(__name__)
```

Then copy verbatim from agent.py:
- `_build_prerun_external_context(task, preflight_facts_block, max_facts)`
- `_extract_working_memory(think_text, step)`
- `_build_subagent_context(parent_diagnosis, scope_entity, parent_tool_history)`

Note: `_build_subagent_context` may reference other module-level constants
(e.g. MAX_SUBAGENT_CONTEXT_CHARS). Move those constants too, or pass them
as parameters — whichever is simpler. If they reference imports only
available in the router context, keep `_build_subagent_context` in agent.py
and only move the first two.

---

## Change 2 — `api/routers/agent.py` — replace with imports

Delete the three function definitions from agent.py and add:

```python
from api.agents.context import (
    _build_prerun_external_context,
    _extract_working_memory,
    _build_subagent_context,   # only if moved in Change 1
)
```

---

## Change 3 — verify line count reduction

CC must report the new line count of agent.py in the commit message body.
Target: ≤5100 lines after this prompt (was 5523 before v2.40.3).

---

## Version bump

Update `VERSION` file: `2.40.3` → `2.40.4`

---

## Commit

```
git add -A
git commit -m "refactor(agents): v2.40.4 extract context-building helpers into api/agents/context.py"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
