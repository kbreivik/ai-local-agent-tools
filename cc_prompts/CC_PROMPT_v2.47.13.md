# CC PROMPT — v2.47.13 — feat(agent): per-agent-type token cap settings + GUI

## What this does

Completes v2.47.12 by:

1. **Registering 4 per-agent-type token cap keys** in the backend
   (`agentMaxTotalTokens_observe / _investigate / _execute / _build`).
2. **Adding all 5 token-cap keys to the frontend** so they appear in the
   Settings GUI.

v2.47.12 only did the backend half. The global key (`agentMaxTotalTokens`)
is registered in `SETTINGS_KEYS` and `_token_cap_for()` reads it — but
the GUI has no input for it. Operators can only change it via direct
`POST /api/settings`, which defeats the "settings-driven" goal.

This prompt closes that gap. After it lands, **Settings → AI Services →
Agent Budgets** shows 5 new input fields below the existing
`agentToolBudget_*` row:

```
Agent Budgets
─────────────
Tool budget per type     [Observe 8] [Investigate 16] [Execute 14] [Build 12]
Token cap per type       [Observe 80000] [Investigate 200000] [Execute 150000] [Build 120000]
Global token cap         [200000]
```

The Agent Budgets section currently lives **at the bottom of the
AI Services tab**, not its own tab. v2.47.13 keeps it there for
consistency — moving it would be a separate UX change.

**Defaults rationale:**

| Type | Tool budget | Tool result avg | Estimated cumulative | Default |
|------|-------------|-----------------|----------------------|---------|
| observe | 8 | small (status snapshots) | ~50k | 80k |
| investigate | 16 | large (logs, queries) | ~150k | 200k |
| execute | 14 + verify | mixed | ~120k | 150k |
| build | 12 | moderate (skill code) | ~80k | 120k |

Version bump: 2.47.12 → 2.47.13

---

## Change 1 — `api/routers/settings.py` — register 4 per-type token caps

CC: open `api/routers/settings.py`. Find the existing v2.47.12 entry
`"agentMaxTotalTokens"` (added at the bottom of the "Agent Budgets"
group, with the comment `# --- Agent Token Cap (v2.47.12) ---`).

Add these four entries IMMEDIATELY after the `"agentMaxTotalTokens"`
block, before the next section. The trailing comma on the
`"agentMaxTotalTokens"` block must be present so the dict literal
remains valid:

```python
    # --- Per-agent-type Token Caps (v2.47.13) ---
    # Per-type overrides for the v2.47.12 global agentMaxTotalTokens.
    # Lookup order at every cap check: per-type → global → env → hardcoded.
    # Defaults calibrated to each type's tool budget and typical tool result
    # sizes. Tune individually in the GUI based on observed run patterns.
    "agentMaxTotalTokens_observe": {
        "env": None, "sens": False,
        "default": 80000, "type": "int",
        "min": 10000, "max": 250000,
        "group": "Agent Budgets",
        "description": (
            "Token cap for observe (status) runs. Short tool chains, small "
            "results — 80000 is generous for typical status checks. "
            "Range 10000..250000."
        ),
    },
    "agentMaxTotalTokens_investigate": {
        "env": None, "sens": False,
        "default": 200000, "type": "int",
        "min": 10000, "max": 250000,
        "group": "Agent Budgets",
        "description": (
            "Token cap for investigate (research) runs. Longest tool chains, "
            "biggest cumulative prompts — 200000 matches the global default. "
            "Range 10000..250000."
        ),
    },
    "agentMaxTotalTokens_execute": {
        "env": None, "sens": False,
        "default": 150000, "type": "int",
        "min": 10000, "max": 250000,
        "group": "Agent Budgets",
        "description": (
            "Token cap for execute (action) runs. Moderate length plus "
            "post-action verify steps. Range 10000..250000."
        ),
    },
    "agentMaxTotalTokens_build": {
        "env": None, "sens": False,
        "default": 120000, "type": "int",
        "min": 10000, "max": 250000,
        "group": "Agent Budgets",
        "description": (
            "Token cap for build (skill creation) runs. Moderate verbosity "
            "from skill_create / skill_regenerate. Range 10000..250000."
        ),
    },
```

CC: match the trailing-comma style of surrounding entries. The four new
keys belong inside the same `SETTINGS_KEYS` dict literal as
`agentMaxTotalTokens` and `agentToolBudget_*`.

---

## Change 2 — `gui/src/context/OptionsContext.jsx` — add 5 keys to DEFAULTS + SERVER_KEYS

CC: open `gui/src/context/OptionsContext.jsx`. Two edits in the same file.

### 2a. Add to DEFAULTS

Find the "Agent Budgets" section in the `DEFAULTS` object (around line 110):

```js
  // Agent Budgets (v2.36.5 — v2.36.6 allowlisted)
  agentToolBudget_observe:     8,
  agentToolBudget_investigate: 16,
  agentToolBudget_execute:     14,
  agentToolBudget_build:       12,
```

Replace with:

```js
  // Agent Budgets (v2.36.5 — v2.36.6 allowlisted)
  agentToolBudget_observe:     8,
  agentToolBudget_investigate: 16,
  agentToolBudget_execute:     14,
  agentToolBudget_build:       12,

  // Agent Token Caps (v2.47.12 + v2.47.13)
  agentMaxTotalTokens:             200000,  // global fallback
  agentMaxTotalTokens_observe:     80000,
  agentMaxTotalTokens_investigate: 200000,
  agentMaxTotalTokens_execute:     150000,
  agentMaxTotalTokens_build:       120000,
```

### 2b. Add to SERVER_KEYS

Find the `SERVER_KEYS` set's "Agent Budgets" line (around line 200):

```js
  // Agent Budgets (v2.36.5 — v2.36.6 allowlisted)
  'agentToolBudget_observe', 'agentToolBudget_investigate',
  'agentToolBudget_execute', 'agentToolBudget_build',
```

Replace with:

```js
  // Agent Budgets (v2.36.5 — v2.36.6 allowlisted)
  'agentToolBudget_observe', 'agentToolBudget_investigate',
  'agentToolBudget_execute', 'agentToolBudget_build',

  // Agent Token Caps (v2.47.12 + v2.47.13)
  'agentMaxTotalTokens',
  'agentMaxTotalTokens_observe', 'agentMaxTotalTokens_investigate',
  'agentMaxTotalTokens_execute', 'agentMaxTotalTokens_build',
```

CC: keep the trailing comma after `'agentToolBudget_build',` so the
Set literal remains valid.

---

## Change 3 — `gui/src/components/OptionsModal.jsx` — render 5 new inputs in Agent Budgets section

CC: open `gui/src/components/OptionsModal.jsx`. Find the existing
"Agent Budgets" section in `AIServicesTab` (search for the comment
`{/* Agent Budgets (v2.36.5) */}` — it's around line 1335).

The current grid renders 4 tool-budget inputs:

```jsx
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
```

DIRECTLY AFTER this `</div>` closing tag (the one that closes
`grid-cols-2 gap-3`), and BEFORE the next existing section
(`{/* v2.36.8 — LARGE-LIST RENDERING prompt toggle (dark launch) */}`),
insert these new blocks:

```jsx
        {/* Agent Token Caps — per-type (v2.47.13) */}
        <div className="mt-4 pt-3 border-t border-white/5">
          <h4 className="text-xs font-mono uppercase tracking-wider text-[var(--accent)] mb-1">
            Token Caps
          </h4>
          <p className="text-xs text-gray-500 mb-3">
            Cumulative prompt + completion tokens per agent run. When exceeded,
            the loop forces synthesis and status becomes 'capped'. Per-type values
            override the global. Subagents get their own fresh counter.
            Range 10000..250000. Changes take effect on the next task.
          </p>
          <div className="grid grid-cols-2 gap-3">
            {[
              ['agentMaxTotalTokens_observe',     'Observe',     'short tool chains'],
              ['agentMaxTotalTokens_investigate', 'Investigate', 'longest, most token-hungry'],
              ['agentMaxTotalTokens_execute',     'Execute',     'plus verify steps'],
              ['agentMaxTotalTokens_build',       'Build',       'moderate verbosity'],
            ].map(([key, label, hint]) => (
              <div key={key}>
                <label className="block text-xs uppercase text-gray-400 mb-1">
                  {label}
                  <span className="ml-2 normal-case text-gray-500">— {hint}</span>
                </label>
                <input
                  type="number"
                  min="10000"
                  max="250000"
                  step="10000"
                  value={draft[key] ?? ''}
                  onChange={e => update(key, parseInt(e.target.value) || 0)}
                  className="w-32 bg-[var(--bg-1)] border border-white/10 px-2 py-1 text-sm"
                />
              </div>
            ))}
          </div>
        </div>

        {/* Agent Token Caps — global fallback (v2.47.12) */}
        <div className="mt-3">
          <label className="block text-xs uppercase text-gray-400 mb-1">
            Global token cap (fallback)
            <span className="ml-2 normal-case text-gray-500">
              — used when no per-type override is set
            </span>
          </label>
          <input
            type="number"
            min="10000"
            max="250000"
            step="10000"
            value={draft.agentMaxTotalTokens ?? ''}
            onChange={e => update('agentMaxTotalTokens', parseInt(e.target.value) || 0)}
            className="w-32 bg-[var(--bg-1)] border border-white/10 px-2 py-1 text-sm"
          />
        </div>
```

CC: match the indentation of the surrounding JSX (this block is inside
the `{/* Agent Budgets (v2.36.5) */}` outer div). The `</div>` that
closes the entire Agent Budgets block (the one with the
`<h3>Agent Budgets</h3>` heading) should remain after these new blocks.

---

## Verify

```bash
# Backend
python -m py_compile api/routers/settings.py

# Confirm all five token-cap keys are registered
grep -n "agentMaxTotalTokens" api/routers/settings.py
# Expected: 5 matches (1 global + 4 per-type)

# Frontend (no compile, but syntax check by reading)
grep -n "agentMaxTotalTokens" gui/src/context/OptionsContext.jsx
# Expected: at least 10 matches (5 in DEFAULTS + 5 in SERVER_KEYS)

grep -n "agentMaxTotalTokens" gui/src/components/OptionsModal.jsx
# Expected: 5 matches (4 in the per-type grid + 1 in the global input)
```

After deploy:

1. Open browser → claude.ai of DEATHSTAR GUI → Settings → AI Services
2. Scroll to "Agent Budgets" section at the bottom
3. Should now see TWO grids:
   - "Tool budget per type" (existing 4)
   - "Token Caps" (new 4)
   - "Global token cap (fallback)" (new 1)
4. Edit `Investigate` token cap from 200000 to 220000, click Save
5. Confirm via API:
   ```bash
   curl -s -H "Authorization: Bearer $TOKEN" \
     http://192.168.199.10:8000/api/settings | \
     jq '.settings.agentMaxTotalTokens_investigate'
   # Expected: 220000
   ```
6. Run an investigate task; trace shows the new cap if/when exceeded

---

## What this does NOT do

- **Does not move Agent Budgets to its own settings tab.** The section
  stays at the bottom of "AI Services". A future prompt could split
  it out if the section grows further.
- **Does not change `_token_cap_for` semantics.** v2.47.12's behaviour
  is unchanged — setting a per-type to 0 in the GUI still returns the
  hardcoded default (because `_coerce_token_cap` treats 0 as misconfigured).
  All four per-type keys now have real defaults so this rarely matters.
- **Does not introduce a tree-wide token cap** for sub-agent trees.
  Each subagent gets its own fresh per-type counter via fresh `StepState`.

---

## Version bump

Update `VERSION`: `2.47.12` → `2.47.13`

---

## Commit

```
git add -A
git commit -m "feat(agent): v2.47.13 per-agent-type token cap settings + GUI"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

After deploy:
- 5 token-cap inputs visible in Settings → AI Services → Agent Budgets
- Operator can tune any of them live via the GUI; effect on next agent step
- Trace shows `agent_type=` on any cap-exceeded message — guides further
  per-type tuning based on real workload data
