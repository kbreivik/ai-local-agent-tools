# CC PROMPT — v2.42.3 — feat(memory): MuninnDB first-tool hints — step 0 suggestion

## What this does

MuninnDB already stores tool sequences from every successful run via
`record_outcome` (tag: `tool_association`, concept: `tools_for:{task_slug}`).
The first tool in that sequence is the historically proven starting point for
that task type. This information is never surfaced to the agent — it discovers
the right first tool by trial and error on every run.

Fix: add `get_first_tool_hint(task, agent_type)` to `api/memory/feedback.py`
that retrieves the most-activated successful tool sequence for the task and
returns the first tool name. In `_stream_agent`, inject it as a one-line
system prompt hint before the loop starts: "For tasks like this, historically
successful runs started with: {tool_name}".

Version bump: 2.42.2 → 2.42.3.

---

## Change 1 — `api/memory/feedback.py` — add get_first_tool_hint()

Append after the `get_past_outcomes` function:

```python
async def get_first_tool_hint(task: str, agent_type: str) -> str | None:
    """Return the first tool from the most-activated successful sequence for
    this task, or None if no data exists.

    Uses the existing `tools_for:{task_slug}` engrams written by record_outcome.
    The most-accessed (highest weight) engram represents the most consistently
    successful starting approach for similar tasks.
    """
    try:
        client = get_client()
        task_key = task[:50].strip()
        task_slug = _slugify(task_key)
        concept = f"tools_for:{task_slug}"

        # Activate with task terms — the engram is found by concept match
        task_terms = [w for w in task_key.lower().split() if len(w) > 3][:5]
        if not task_terms:
            return None

        results = await client.activate(task_terms + [agent_type], max_results=10)
        if not results:
            return None

        # Filter to success engrams for this agent_type
        success_engrams = [
            r for r in results
            if "success" in r.get("tags", [])
            and agent_type in r.get("tags", [])
            and r.get("concept", "").startswith("tools_for:")
        ]

        if not success_engrams:
            return None

        # Most-activated engram is at index 0 (MuninnDB sorts by activation weight)
        best = success_engrams[0]
        content = best.get("content", "")

        # Extract tool sequence: "Successful tool sequence for '...': tool1,tool2,tool3"
        import re
        match = re.search(r":\s*([a-z_][a-z0-9_,]+)", content)
        if not match:
            return None

        first_tool = match.group(1).split(",")[0].strip()
        if not first_tool or len(first_tool) < 3:
            return None

        return first_tool

    except Exception as _e:
        log.debug("get_first_tool_hint failed: %s", _e)
        return None
```

---

## Change 2 — `api/routers/agent.py` — inject hint at step 0

Locate the section in `_stream_agent` that builds the system prompt
(near the `injected_sections` assembly, after `_preflight_skills_block` is
inserted). Add the hint injection immediately after the preflight skills block:

```python
        # v2.42.3 — MuninnDB first-tool hint (step 0)
        try:
            from api.memory.feedback import get_first_tool_hint
            _first_tool_hint = await get_first_tool_hint(task, first_intent)
            if _first_tool_hint:
                _hint_block = (
                    f"HISTORICAL HINT: For tasks similar to this, "
                    f"successful runs typically started with: {_first_tool_hint}. "
                    f"Consider this as your first tool call."
                )
                injected_sections.append(_hint_block)
                await manager.send_line(
                    "memory",
                    f"[hint] first-tool suggestion: {_first_tool_hint}",
                    status="ok", session_id=session_id,
                )
        except Exception as _hte:
            log.debug("first_tool_hint failed: %s", _hte)
```

---

## Change 3 — `tests/test_first_tool_hint.py`

```python
"""Tests for get_first_tool_hint — MuninnDB tool-sequence memory."""
from __future__ import annotations
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_returns_none_on_no_results():
    from api.memory.feedback import get_first_tool_hint
    mock_client = AsyncMock()
    mock_client.activate = AsyncMock(return_value=[])
    with patch("api.memory.feedback.get_client", return_value=mock_client):
        result = _run(get_first_tool_hint("check kafka status", "observe"))
    assert result is None


def test_returns_first_tool_from_sequence():
    from api.memory.feedback import get_first_tool_hint
    mock_client = AsyncMock()
    mock_client.activate = AsyncMock(return_value=[{
        "concept": "tools_for:check-kafka-status",
        "content": "Successful tool sequence for 'check kafka status': kafka_broker_status,kafka_topic_inspect,kafka_consumer_lag. Outcome: completed. Agent: observe.",
        "tags": ["tool_association", "observe", "success"],
    }])
    with patch("api.memory.feedback.get_client", return_value=mock_client):
        result = _run(get_first_tool_hint("check kafka status", "observe"))
    assert result == "kafka_broker_status"


def test_ignores_failure_engrams():
    from api.memory.feedback import get_first_tool_hint
    mock_client = AsyncMock()
    mock_client.activate = AsyncMock(return_value=[{
        "concept": "tools_for:check-kafka-status",
        "content": "Failed/cancelled tool sequence for 'check kafka status': audit_log. Outcome: failed. Agent: observe.",
        "tags": ["tool_association", "observe", "failure"],
    }])
    with patch("api.memory.feedback.get_client", return_value=mock_client):
        result = _run(get_first_tool_hint("check kafka status", "observe"))
    assert result is None


def test_ignores_wrong_agent_type():
    from api.memory.feedback import get_first_tool_hint
    mock_client = AsyncMock()
    mock_client.activate = AsyncMock(return_value=[{
        "concept": "tools_for:check-kafka",
        "content": "Successful tool sequence for 'check kafka': swarm_service_force_update. Outcome: completed. Agent: execute.",
        "tags": ["tool_association", "execute", "success"],
    }])
    with patch("api.memory.feedback.get_client", return_value=mock_client):
        result = _run(get_first_tool_hint("check kafka", "observe"))
    assert result is None


def test_returns_none_on_exception():
    from api.memory.feedback import get_first_tool_hint
    mock_client = AsyncMock()
    mock_client.activate = AsyncMock(side_effect=Exception("db down"))
    with patch("api.memory.feedback.get_client", return_value=mock_client):
        result = _run(get_first_tool_hint("check kafka", "observe"))
    assert result is None
```

---

## Version bump

Update `VERSION`: `2.42.2` → `2.42.3`

---

## Commit

```
git add -A
git commit -m "feat(memory): v2.42.3 MuninnDB first-tool hints — step 0 suggestion from historical sequences"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
