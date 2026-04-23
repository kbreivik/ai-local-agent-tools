# CC PROMPT — v2.43.8 — feat(settings): memoryEnabled toggle — disable MuninnDB for testing

## What this does

Adds a `memoryEnabled` boolean setting (default: true). When false:
- `get_client()` returns a `NullMuninnClient` that silently returns
  empty results on all calls (same interface, no exceptions)
- All memory hooks fire-and-forget calls become no-ops
- Agent loop skips `get_past_outcomes`, `get_first_tool_hint`, doc chunk
  injection — effectively a clean-room agent run
- Platform Core card still shows MuninnDB health (the container may still
  run — the setting controls whether DEATHSTAR uses it)

Useful for: A/B testing agent quality without memory, debugging whether
MuninnDB content is hurting or helping a specific task type, isolating
fact-grounding quality from memory-grounding quality.

Version bump: 2.43.7 → 2.43.8.

---

## Change 1 — `api/memory/client.py`

Add a NullMuninnClient after the MuninnClient class:

```python
class NullMuninnClient:
    """Drop-in replacement when memoryEnabled=false. All ops are no-ops."""

    async def store(self, concept: str, content: str,
                    tags: list[str] | None = None) -> str | None:
        return None

    async def activate(self, context: list[str],
                       max_results: int = 5) -> list[dict]:
        return []

    async def search(self, query: str, limit: int = 20) -> list[dict]:
        return []

    async def recent(self, limit: int = 20) -> list[dict]:
        return []

    async def delete(self, engram_id: str) -> bool:
        return False

    async def count(self) -> int | None:
        return None

    async def health(self) -> bool:
        return False

    async def close(self) -> None:
        pass
```

Update `get_client()` to check the setting:

```python
def get_client() -> MuninnClient | NullMuninnClient:
    """Return the active memory client.

    Returns NullMuninnClient when memoryEnabled=false (setting), so all
    callers get graceful empty results without code changes.
    """
    try:
        from api.settings_manager import get_setting
        enabled = get_setting("memoryEnabled").get("value", True)
        if enabled is False or str(enabled).lower() in ("false", "0", "no"):
            return NullMuninnClient()
    except Exception:
        pass  # settings unavailable → default to real client

    global _client
    if _client is None:
        _client = MuninnClient()
    return _client
```

---

## Change 2 — `api/settings_manager.py`

Add `memoryEnabled` to CATEGORIES under agent behavior:

```python
"memoryEnabled": "agent",
```

(alongside `autoEscalate`, `requireConfirmation`, etc.)

---

## Change 3 — `gui/src/components/OptionsModal.jsx`

In `GeneralTab`, locate the block ending with the `renderToolPromptEnabled`
checkbox (around line 860). After its closing `</div>`, before the
`</div></div>` that closes the agent behavior section, add:

```jsx
        {/* v2.43.8 — MuninnDB / memory enable toggle */}
        <div className="mt-4 pt-3 border-t border-white/5">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={draft.memoryEnabled !== false}
              onChange={e => update('memoryEnabled', e.target.checked)}
            />
            <span>Enable MuninnDB memory (engrams, past outcomes, tool hints)</span>
          </label>
          <div className="text-xs text-gray-500 ml-6 mt-1">
            When off: agent runs without memory context — useful for testing
            grounding quality from facts alone. MuninnDB container continues
            running; DEATHSTAR simply ignores it.
          </div>
        </div>
```

Also add `memoryEnabled` to the SERVER_KEYS list (wherever renderToolPromptEnabled
is listed) so the settings page saves it to the backend.

---

## Change 4 — `api/routers/agent.py`

In `_stream_agent`, the three places that call memory:

**a) get_past_outcomes call** — already guarded by try/except, so
NullMuninnClient returning `[]` is transparent. No change needed.

**b) MuninnDB doc chunk injection** (around the
`if first_intent in ("research", "investigate"):` block):

Wrap with a quick check so we skip the entire block:

```python
        # MuninnDB doc chunks (research/investigate — Hebbian activation)
        # v2.43.8: skip entirely when memoryEnabled=false
        _mem_enabled = True
        try:
            from api.settings_manager import get_setting
            v = get_setting("memoryEnabled").get("value", True)
            _mem_enabled = v is not False and str(v).lower() not in ("false", "0", "no")
        except Exception:
            pass

        if _mem_enabled and first_intent in ("research", "investigate"):
            _mem = _get_mem_client()
            # ... existing doc chunk code unchanged ...
```

**c) record_outcome / feedback hooks** — NullMuninnClient silently
absorbs all store() calls. No change needed.

---

## Verification

1. Disable: `PATCH /api/settings {"memoryEnabled": false}`
2. Run a task — confirm `[memory]` lines are absent from the session output
3. Check `[context]` line shows 0 engrams activated
4. Re-enable: `PATCH /api/settings {"memoryEnabled": true}` — memory resumes

---

## Version bump

Update `VERSION`: `2.43.7` → `2.43.8`

---

## Commit

```
git add -A
git commit -m "feat(settings): v2.43.8 memoryEnabled toggle — NullMuninnClient when disabled"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
