# CC PROMPT — v2.36.5 — Per-agent-type tool call budgets in Settings

## What this does

Moves the hardcoded `_MAX_TOOL_CALLS_BY_TYPE` dict in `api/routers/agent.py`
to runtime Settings lookup so operators can tune budgets without redeploy.
Four new Settings keys — one per canonical agent type (observe /
investigate / execute / build). Type aliases (status → observe, research →
investigate, action → execute) resolve to the canonical type's budget.

Defaults match current hardcoded values exactly — zero behaviour change on
a fresh install. Operators see status=capped too often → bump the
investigate knob from 16 → 20 in Settings, next task picks it up. No
restart, no deploy.

Version bump: 2.36.4 → 2.36.5 (`.x.N` — small addition, tuning).

---

## Why

Kent is seeing too many `status=capped` terminal outcomes with
`final_answer` produced by `run_forced_synthesis`. The tool-call budget
for the investigate agent (16) is too tight for real-world diagnostic
tasks. Rather than pick new numbers and hope, expose the knobs so Kent
can A/B-test values against real tasks.

The other agent-run caps (wall-clock, total tokens, destructive calls,
tool failures, max LLM steps) are NOT in scope — capping is almost
always the tool-call budget tripping first. If Kent later hits those
caps we add them in a follow-up prompt.

---

## Change 1 — `api/routers/settings.py` — add 4 keys

Append to `SETTINGS_KEYS` after the existing "Facts & Knowledge" group
block, under a new comment header:

```python
    # --- Agent Budgets (v2.36.5) ---
    # Per-agent-type tool call budget. When the agent makes N tool calls without
    # emitting a final synthesis, the loop forces synthesis via run_forced_synthesis
    # and the operation status becomes 'capped'. Defaults match the pre-v2.36.5
    # hardcoded values. Safe range 4..100. Set to 0 to restore the hardcoded default.
    # Type aliases: status→observe, research→investigate, action→execute.
    "agentToolBudget_observe":      {"env": None, "sens": False, "default": 8,  "type": "int", "group": "Agent Budgets"},
    "agentToolBudget_investigate":  {"env": None, "sens": False, "default": 16, "type": "int", "group": "Agent Budgets"},
    "agentToolBudget_execute":      {"env": None, "sens": False, "default": 14, "type": "int", "group": "Agent Budgets"},
    "agentToolBudget_build":        {"env": None, "sens": False, "default": 12, "type": "int", "group": "Agent Budgets"},
```

Those `default` values are the current hardcoded values from
`_MAX_TOOL_CALLS_BY_TYPE` in `api/routers/agent.py`. Do NOT change them —
the whole point of the prompt is zero behaviour change at default.

---

## Change 2 — `api/routers/agent.py` — helper + replace the dict

At the top of the file, right after the existing `_extract_response_model`
helper (and before `_step_temperature`), add:

```python
# ─── Per-agent-type tool call budgets (v2.36.5) ───────────────────────────────
# Runtime-Settings driven so operators can tune without redeploy. Falls back
# to the pre-v2.36.5 hardcoded values when Settings are unavailable or a
# key returns a malformed value.

_TOOL_BUDGET_DEFAULTS: dict[str, int] = {
    "observe":     8,
    "investigate": 16,
    "execute":     14,
    "build":       12,
}

# Agent-type aliases → canonical type. status / research / action are
# historical names that still appear in task classifications; they share
# the canonical type's budget.
_TOOL_BUDGET_ALIASES: dict[str, str] = {
    "status":      "observe",
    "research":    "investigate",
    "action":      "execute",
    "ambiguous":   "observe",   # ambiguous classifier routes to observe
}

# Accept anything from 4 (below which the agent has no room to work) to 100
# (above which wall-clock / token caps will trip first anyway). Misconfigured
# values get clamped and a warning is logged.
_TOOL_BUDGET_MIN = 4
_TOOL_BUDGET_MAX = 100


def _tool_budget_for(agent_type: str) -> int:
    """Return the tool call budget for `agent_type`, read fresh from Settings.

    Aliases resolved first (status→observe, research→investigate, action→execute).
    Unknown types fall back to the investigate budget (the most permissive of the
    four canonical types). Misconfigured values (None, non-int, <=0, >100) log
    a warning and fall back to the hardcoded default.
    """
    canonical = _TOOL_BUDGET_ALIASES.get(agent_type, agent_type)
    default = _TOOL_BUDGET_DEFAULTS.get(canonical, _TOOL_BUDGET_DEFAULTS["investigate"])
    key = f"agentToolBudget_{canonical}"

    try:
        from mcp_server.tools.skills.storage import get_backend
        raw = get_backend().get_setting(key)
    except Exception as e:
        log.debug("tool budget settings read failed for %s: %s", key, e)
        return default

    if raw is None or raw == "":
        return default

    try:
        value = int(raw)
    except (TypeError, ValueError):
        log.warning(
            "tool budget setting %s has non-int value %r; using default %d",
            key, raw, default,
        )
        return default

    if value <= 0:
        # Operator explicitly set 0 → fall back to default (documented behaviour).
        return default

    if value < _TOOL_BUDGET_MIN or value > _TOOL_BUDGET_MAX:
        log.warning(
            "tool budget setting %s=%d outside safe range [%d..%d]; "
            "clamping to default %d",
            key, value, _TOOL_BUDGET_MIN, _TOOL_BUDGET_MAX, default,
        )
        return default

    return value
```

Now find the existing `_MAX_TOOL_CALLS_BY_TYPE` dict inside
`_run_single_agent_step`. It looks like:

```python
    _MAX_TOOL_CALLS_BY_TYPE = {
        "status": 8, "observe": 8,
        "research": 16, "investigate": 16,
        "action": 14, "execute": 14,
        "build": 12,
    }
```

**Delete the dict entirely.** It's replaced by the helper above.

Then find every use of `_MAX_TOOL_CALLS_BY_TYPE.get(agent_type, 16)` in
the same function — there are several, including inside
`_maybe_force_empty_synthesis`. Replace each with
`_tool_budget_for(agent_type)`.

Grep target: `_MAX_TOOL_CALLS_BY_TYPE` should match ZERO lines in
`api/routers/agent.py` after this change. Use:

```bash
grep -n "_MAX_TOOL_CALLS_BY_TYPE" api/routers/agent.py
# expected: no output
```

Known call sites (verify by grep, these are the ones I identified; there
may be more):

1. Inside `_run_single_agent_step` top-of-loop:
   `_tool_budget = _MAX_TOOL_CALLS_BY_TYPE.get(agent_type, 16)`
   → replace with `_tool_budget = _tool_budget_for(agent_type)`

2. Inside `_run_single_agent_step` budget-nudge block:
   `_tool_budget = _MAX_TOOL_CALLS_BY_TYPE.get(agent_type, 16)`
   → same replacement (this is the block that fires the 60% nudge)

3. Budget-cap forced-synthesis path:
   `_budget_cap = _MAX_TOOL_CALLS_BY_TYPE.get(agent_type, 16)`
   → `_budget_cap = _tool_budget_for(agent_type)`

4. Inside `_maybe_force_empty_synthesis`:
   `_budget_for_synth = _MAX_TOOL_CALLS_BY_TYPE.get(agent_type, 16)`
   → `_budget_for_synth = _tool_budget_for(agent_type)`

5. v2.34.15 budget-truncation block (where batch tools overflow cap):
   `_tool_budget = _MAX_TOOL_CALLS_BY_TYPE.get(agent_type, 16)`
   → same replacement

Call sites read the budget ONCE per step iteration (or once per helper
invocation), so a mid-task Settings change takes effect within one step
— no stale budgets from earlier in the loop. That's the intended
behaviour: Kent can bump the budget mid-run if a task is about to cap
and he wants to see it continue.

---

## Change 3 — `gui/src/components/OptionsModal.jsx` — AIServicesTab

Add a new "Agent Budgets" subsection to `AIServicesTab` AFTER the
existing Coordinator section. No CollapsibleSection dependency (v2.36.4
might not have landed yet when v2.36.5 runs) — plain header + grid.

Insert just before the closing `</div>` of the AIServicesTab's root
element:

```jsx
      {/* Agent Budgets (v2.36.5) */}
      <div className="mt-6 pt-4 border-t border-white/10">
        <h3 className="text-sm font-mono uppercase tracking-wider text-[var(--accent)] mb-1">
          Agent Budgets
        </h3>
        <p className="text-xs text-gray-500 mb-3">
          Tool call budget per agent type. When reached, the loop forces
          synthesis and status becomes 'capped'. Raising a value lets the
          agent gather more evidence before synthesising. Safe range 4..100.
          Changes take effect on the next task — no restart needed.
        </p>
        <div className="grid grid-cols-2 gap-3">
          {[
            ['agentToolBudget_observe',     'Observe',     'status checks, read-only'],
            ['agentToolBudget_investigate', 'Investigate', 'why/diagnose/logs'],
            ['agentToolBudget_execute',     'Execute',     'fix/restart/deploy'],
            ['agentToolBudget_build',       'Build',       'skill management'],
          ].map(([key, label, hint]) => (
            <div key={key}>
              <label className="block text-xs uppercase text-gray-400 mb-1">
                {label}
                <span className="ml-2 normal-case text-gray-500">— {hint}</span>
              </label>
              <input
                type="number"
                min="4"
                max="100"
                value={draft[key] ?? ''}
                onChange={e => update(key, parseInt(e.target.value) || 0)}
                className="w-24 bg-[var(--bg-1)] border border-white/10 px-2 py-1 text-sm"
              />
            </div>
          ))}
        </div>
      </div>
```

This assumes the AIServicesTab has `draft` + `update` in scope (it does
— that's the standard Settings form pattern per v2.35.21). If the
variable names differ in the current file, adapt but keep the 4-input
structure.

---

## Change 4 — `tests/test_tool_budget_settings.py`

New file. Tests the helper in isolation with a mocked settings backend.

```python
"""v2.36.5 — Per-agent-type tool call budget helper tests.

Locks the fallback behaviour: misconfigured values return the hardcoded
default, valid values round-trip, aliases resolve correctly.
"""
import logging
from unittest.mock import patch, MagicMock


def _mock_backend(settings: dict | None = None):
    """Return a mock backend that returns `settings.get(key)` on get_setting."""
    settings = settings or {}
    backend = MagicMock()
    backend.get_setting = MagicMock(side_effect=lambda k: settings.get(k))
    return backend


def test_returns_default_when_setting_absent():
    from api.routers.agent import _tool_budget_for
    with patch("mcp_server.tools.skills.storage.get_backend",
               return_value=_mock_backend({})):
        assert _tool_budget_for("observe") == 8
        assert _tool_budget_for("investigate") == 16
        assert _tool_budget_for("execute") == 14
        assert _tool_budget_for("build") == 12


def test_returns_setting_value_when_configured():
    from api.routers.agent import _tool_budget_for
    with patch("mcp_server.tools.skills.storage.get_backend",
               return_value=_mock_backend({
                   "agentToolBudget_investigate": 24,
                   "agentToolBudget_observe": 10,
               })):
        assert _tool_budget_for("investigate") == 24
        assert _tool_budget_for("observe") == 10
        # Unconfigured types still use default
        assert _tool_budget_for("execute") == 14


def test_string_int_is_accepted():
    """Settings backend may return int as string (JSONB round-trip can do this)."""
    from api.routers.agent import _tool_budget_for
    with patch("mcp_server.tools.skills.storage.get_backend",
               return_value=_mock_backend({"agentToolBudget_investigate": "20"})):
        assert _tool_budget_for("investigate") == 20


def test_non_int_value_falls_back(caplog):
    from api.routers.agent import _tool_budget_for
    with patch("mcp_server.tools.skills.storage.get_backend",
               return_value=_mock_backend({"agentToolBudget_investigate": "not-a-number"})):
        with caplog.at_level(logging.WARNING):
            result = _tool_budget_for("investigate")
    assert result == 16
    assert any("non-int" in r.message for r in caplog.records)


def test_zero_value_falls_back_to_default():
    """Operator-documented: 0 means 'restore hardcoded default'."""
    from api.routers.agent import _tool_budget_for
    with patch("mcp_server.tools.skills.storage.get_backend",
               return_value=_mock_backend({"agentToolBudget_investigate": 0})):
        assert _tool_budget_for("investigate") == 16


def test_negative_value_falls_back():
    from api.routers.agent import _tool_budget_for
    with patch("mcp_server.tools.skills.storage.get_backend",
               return_value=_mock_backend({"agentToolBudget_investigate": -5})):
        assert _tool_budget_for("investigate") == 16


def test_out_of_range_clamps(caplog):
    """3 (below min) and 500 (above max) both fall back to default with warning."""
    from api.routers.agent import _tool_budget_for

    with patch("mcp_server.tools.skills.storage.get_backend",
               return_value=_mock_backend({"agentToolBudget_investigate": 3})):
        with caplog.at_level(logging.WARNING):
            assert _tool_budget_for("investigate") == 16
        assert any("outside safe range" in r.message for r in caplog.records)

    caplog.clear()

    with patch("mcp_server.tools.skills.storage.get_backend",
               return_value=_mock_backend({"agentToolBudget_investigate": 500})):
        with caplog.at_level(logging.WARNING):
            assert _tool_budget_for("investigate") == 16
        assert any("outside safe range" in r.message for r in caplog.records)


def test_alias_resolution():
    """status/research/action aliases route to observe/investigate/execute."""
    from api.routers.agent import _tool_budget_for
    with patch("mcp_server.tools.skills.storage.get_backend",
               return_value=_mock_backend({
                   "agentToolBudget_observe": 10,
                   "agentToolBudget_investigate": 20,
                   "agentToolBudget_execute": 18,
               })):
        assert _tool_budget_for("status") == 10
        assert _tool_budget_for("research") == 20
        assert _tool_budget_for("action") == 18
        assert _tool_budget_for("ambiguous") == 10   # → observe


def test_unknown_type_falls_back_to_investigate_default():
    """Unknown agent types (future additions) get the most permissive default."""
    from api.routers.agent import _tool_budget_for
    with patch("mcp_server.tools.skills.storage.get_backend",
               return_value=_mock_backend({})):
        assert _tool_budget_for("mystery_type") == 16   # investigate default


def test_backend_read_failure_falls_back():
    """Settings backend exception (DB down, etc.) must not crash the agent loop."""
    from api.routers.agent import _tool_budget_for
    bad_backend = MagicMock()
    bad_backend.get_setting = MagicMock(side_effect=RuntimeError("db down"))
    with patch("mcp_server.tools.skills.storage.get_backend",
               return_value=bad_backend):
        assert _tool_budget_for("investigate") == 16
        assert _tool_budget_for("observe") == 8


def test_no_max_tool_calls_dict_reference_remains():
    """Structural guard: v2.36.5 removes _MAX_TOOL_CALLS_BY_TYPE entirely.

    Any reference in api/routers/agent.py is a regression — the helper is the
    only path to the budget after this prompt lands.
    """
    import pathlib
    src = pathlib.Path(__file__).parent.parent / "api" / "routers" / "agent.py"
    text = src.read_text(encoding="utf-8")
    assert "_MAX_TOOL_CALLS_BY_TYPE" not in text, (
        "v2.36.5 removed _MAX_TOOL_CALLS_BY_TYPE — if it reappears, a regression "
        "has been introduced. Use _tool_budget_for(agent_type) instead."
    )
```

---

## Change 5 — `VERSION`

```
2.36.5
```

---

## Verify

```bash
# Grep must return zero lines
grep -n "_MAX_TOOL_CALLS_BY_TYPE" api/routers/agent.py && echo "FAIL" || echo "ok"

# Helper-shape tests
pytest tests/test_tool_budget_settings.py -v

# Regression: existing agent-loop tests should still pass
pytest tests/test_prompt_snapshots.py tests/test_forced_synthesis_drift.py -v
```

---

## Commit

```bash
git add -A
git commit -m "feat(agents): v2.36.5 per-agent-type tool call budgets in Settings

Moves _MAX_TOOL_CALLS_BY_TYPE from a hardcoded dict in api/routers/agent.py
to runtime Settings lookup so operators can tune without redeploy. Defaults
match current values exactly — zero behaviour change on a fresh install.

Four new Settings keys under 'Agent Budgets' group (int type, safe range 4..100):
  agentToolBudget_observe       (default 8)
  agentToolBudget_investigate   (default 16)
  agentToolBudget_execute       (default 14)
  agentToolBudget_build         (default 12)

New helper _tool_budget_for(agent_type) reads Settings fresh on every call
with layered fallback: Settings backend exception → hardcoded default;
None/empty/0 → hardcoded default; non-int → hardcoded default + warning log;
out-of-range (<4 or >100) → hardcoded default + warning log. Agent-type
aliases resolved via _TOOL_BUDGET_ALIASES (status→observe, research→
investigate, action→execute, ambiguous→observe).

Budget is read at the top of each step iteration in _run_single_agent_step
and in the budget-nudge / budget-cap / forced-synthesis / batch-truncate
paths — a mid-task Settings change takes effect within one step. Desired
behaviour: operator sees a task about to cap, bumps the knob, task finishes.

AIServicesTab in OptionsModal.jsx gains an 'Agent Budgets' section with
4 number inputs. No CollapsibleSection dependency (v2.36.4 may not have
landed yet).

11 regression tests in tests/test_tool_budget_settings.py cover default
fallback, configured values, string-int coercion, non-int guard, zero and
negative values, out-of-range clamping, alias resolution, unknown-type
fallback, backend-exception safety, and a structural guard that fails if
_MAX_TOOL_CALLS_BY_TYPE ever reappears in agent.py."
git push origin main
```

---

## Deploy + smoke

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

Smoke:

1. GET `/api/settings` should include the 4 new keys with defaults:
   ```bash
   curl -s http://192.168.199.10:8000/api/settings | \
     jq '. | to_entries | map(select(.key | startswith("agentToolBudget_")))'
   ```
   Expect 4 entries with values 8/16/14/12.

2. Visit Settings → AI Services in browser → scroll to bottom → see
   "Agent Budgets" section with 4 number inputs pre-filled with defaults.

3. Start any agent task (e.g. "Observe dashboard status") → confirm it
   runs normally. Budget = 8 for observe, no regression.

4. Bump `agentToolBudget_investigate` to 24 via Settings UI, Save. Start
   an investigate task that historically caps. Expect the task to use up
   to 24 tool calls now before forcing synthesis. Verify:
   ```bash
   # Right after the task runs:
   psql -c "SELECT operation_id, final_status,
              (SELECT COUNT(*) FROM tool_calls WHERE operation_id = ops.id) AS tool_count
            FROM operations ops
            ORDER BY created_at DESC LIMIT 5;"
   ```
   The capped tasks should now cap at 24 (not 16) — or better, succeed.

5. Set `agentToolBudget_investigate` to 0 via curl to confirm the
   "restore default" semantics:
   ```bash
   curl -sS -X POST http://192.168.199.10:8000/api/settings \
     -H 'Content-Type: application/json' \
     -H "Cookie: hp1_auth_cookie=$(cat ~/.hp1_cookie)" \
     -d '{"key":"agentToolBudget_investigate","value":0}'
   # Next investigate run should use budget 16 (hardcoded default)
   ```

6. Set an out-of-range value to confirm clamping:
   ```bash
   curl -sS -X POST http://192.168.199.10:8000/api/settings \
     -H 'Content-Type: application/json' \
     -H "Cookie: hp1_auth_cookie=$(cat ~/.hp1_cookie)" \
     -d '{"key":"agentToolBudget_investigate","value":9999}'
   # docker logs hp1_agent 2>&1 | grep "outside safe range"
   # Should see a warning on next investigate run.
   ```

Restore sensible values after smoke.

---

## Scope guard — do NOT touch

- `_MAX_STEPS_BY_TYPE` (max LLM step iterations) — out of scope. Separate prompt if needed.
- `_AGENT_MAX_WALL_CLOCK_S`, `_AGENT_MAX_TOTAL_TOKENS`, `_AGENT_MAX_DESTRUCTIVE`, `_AGENT_MAX_TOOL_FAILURES` — env-var driven, out of scope.
- `_SUBAGENT_*` — sub-agent budgets unchanged. Sub-agents inherit their agent_type's budget via `_tool_budget_for` automatically.
- `MIN_SUBSTANTIVE_BY_TYPE` in `api/agents/__init__.py` — the hallucination guard's floor, separate concern.
- External AI router (v2.36.0-4) wiring — untouched.
- Settings "Facts & Knowledge" group — untouched.
