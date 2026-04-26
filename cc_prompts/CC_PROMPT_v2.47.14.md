# CC PROMPT — v2.47.14 — fix(gui): wire token cap settings into Agent Budgets section

## What this does

v2.47.13 was marked DONE (commit e030f67) but only the backend half of
the prompt actually landed:

| Layer | v2.47.13 outcome |
|-------|------------------|
| Backend `SETTINGS_KEYS` — 4 per-type token cap keys | ✅ registered |
| Frontend `OptionsContext.jsx` `DEFAULTS` — needs 5 keys | ❌ NOT applied |
| Frontend `OptionsContext.jsx` `SERVER_KEYS` — needs 5 keys | ❌ NOT applied |
| Frontend `OptionsModal.jsx` Agent Budgets render | ❌ NOT applied |

Verified by reading the live files: zero `agentMaxTotalTokens` references
in either frontend file. The backend accepts
`POST /api/settings -d '{"agentMaxTotalTokens_investigate": 220000}'`
correctly, but the GUI shows nothing — exactly the gap v2.47.13 was
supposed to close.

This prompt re-applies just the two frontend edits. Backend stays as-is
(no `api/routers/settings.py` changes — already correct since v2.47.13).

After this lands, **Settings → AI Services → Agent Budgets** will show:

```
Tool budget per type    [Observe 8] [Investigate 16] [Execute 14] [Build 12]

Token Caps
─────────
Per-type cap            [Observe 80000]   [Investigate 200000]
                        [Execute 150000]  [Build 120000]

Global token cap (fallback)  [200000]
```

Version bump: 2.47.13 → 2.47.14

---

## Change 1 — `gui/src/context/OptionsContext.jsx` — add 5 keys to DEFAULTS + SERVER_KEYS

CC: open `gui/src/context/OptionsContext.jsx`. Two edits in the same file.

### 1a. Add to DEFAULTS

Find the existing "Agent Budgets" block in `DEFAULTS` (around line 110):

```js
  // Agent Budgets (v2.36.5 — v2.36.6 allowlisted)
  agentToolBudget_observe:     8,
  agentToolBudget_investigate: 16,
  agentToolBudget_execute:     14,
  agentToolBudget_build:       12,
  renderToolPromptEnabled:     false,  // v2.36.8 — dark launch
  memoryEnabled:               true,   // v2.43.8 — MuninnDB memory toggle
  memoryBackend:               'muninndb', // v2.43.9 — 'muninndb'|'postgres'
```

Insert these 5 lines BEFORE the `renderToolPromptEnabled` line (so they
sit grouped with the other tool-budget entries):

```js
  // Agent Token Caps (v2.47.12 + v2.47.13 + v2.47.14 GUI)
  agentMaxTotalTokens:             200000,  // global fallback
  agentMaxTotalTokens_observe:     80000,
  agentMaxTotalTokens_investigate: 200000,
  agentMaxTotalTokens_execute:     150000,
  agentMaxTotalTokens_build:       120000,
```

After the edit the section should read:

```js
  // Agent Budgets (v2.36.5 — v2.36.6 allowlisted)
  agentToolBudget_observe:     8,
  agentToolBudget_investigate: 16,
  agentToolBudget_execute:     14,
  agentToolBudget_build:       12,
  // Agent Token Caps (v2.47.12 + v2.47.13 + v2.47.14 GUI)
  agentMaxTotalTokens:             200000,  // global fallback
  agentMaxTotalTokens_observe:     80000,
  agentMaxTotalTokens_investigate: 200000,
  agentMaxTotalTokens_execute:     150000,
  agentMaxTotalTokens_build:       120000,
  renderToolPromptEnabled:     false,  // v2.36.8 — dark launch
  memoryEnabled:               true,   // v2.43.8 — MuninnDB memory toggle
  memoryBackend:               'muninndb', // v2.43.9 — 'muninndb'|'postgres'
```

### 1b. Add to SERVER_KEYS

Find the existing Agent Budgets line in the `SERVER_KEYS` set (around line 200):

```js
  // Agent Budgets (v2.36.5 — v2.36.6 allowlisted)
  'agentToolBudget_observe', 'agentToolBudget_investigate',
  'agentToolBudget_execute', 'agentToolBudget_build',
  'renderToolPromptEnabled',  // v2.36.8
  'memoryEnabled',            // v2.43.8
  'memoryBackend',            // v2.43.9
```

Insert these lines BEFORE `'renderToolPromptEnabled',`:

```js
  // Agent Token Caps (v2.47.12 + v2.47.13 + v2.47.14 GUI)
  'agentMaxTotalTokens',
  'agentMaxTotalTokens_observe', 'agentMaxTotalTokens_investigate',
  'agentMaxTotalTokens_execute', 'agentMaxTotalTokens_build',
```

After the edit:

```js
  // Agent Budgets (v2.36.5 — v2.36.6 allowlisted)
  'agentToolBudget_observe', 'agentToolBudget_investigate',
  'agentToolBudget_execute', 'agentToolBudget_build',
  // Agent Token Caps (v2.47.12 + v2.47.13 + v2.47.14 GUI)
  'agentMaxTotalTokens',
  'agentMaxTotalTokens_observe', 'agentMaxTotalTokens_investigate',
  'agentMaxTotalTokens_execute', 'agentMaxTotalTokens_build',
  'renderToolPromptEnabled',  // v2.36.8
  'memoryEnabled',            // v2.43.8
  'memoryBackend',            // v2.43.9
```

---

## Change 2 — `gui/src/components/OptionsModal.jsx` — render the inputs

CC: open `gui/src/components/OptionsModal.jsx`. Find the Agent Budgets
section in `AIServicesTab` — search for the comment
`{/* Agent Budgets (v2.36.5) */}` (around line 1335). The current
structure ends with:

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

        {/* v2.36.8 — LARGE-LIST RENDERING prompt toggle (dark launch) */}
```

Insert these two new blocks BETWEEN the `</div>` that closes the
`grid grid-cols-2 gap-3` block AND the `{/* v2.36.8 — LARGE-LIST RENDERING ... */}`
comment. So the resulting structure becomes:

```jsx
          ))}
        </div>

        {/* Agent Token Caps — per-type (v2.47.14) */}
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

        {/* Global token cap fallback (v2.47.14) */}
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

        {/* v2.36.8 — LARGE-LIST RENDERING prompt toggle (dark launch) */}
```

CC: indentation must match the surrounding JSX (the new blocks are
siblings of the existing tool-budget grid, all inside the same outer
"Agent Budgets" div with the `<h3>Agent Budgets</h3>` header).

---

## Verify

```bash
# Confirm DEFAULTS has 5 new keys
grep -n "agentMaxTotalTokens" gui/src/context/OptionsContext.jsx
# Expected: 10 matches (5 in DEFAULTS + 5 in SERVER_KEYS)

# Confirm OptionsModal has the new render blocks
grep -n "agentMaxTotalTokens" gui/src/components/OptionsModal.jsx
# Expected: 5 matches (4 in the per-type grid + 1 in the global input)

# Backend keys should already be registered (from v2.47.13)
grep -n "agentMaxTotalTokens" api/routers/settings.py
# Expected: 5 matches (1 global + 4 per-type) — should be unchanged
```

After deploy:

1. Browser → claude.ai of DEATHSTAR GUI → Settings → AI Services
2. Scroll to "Agent Budgets" section at the bottom of the tab
3. Should see THREE distinct controls below the existing Tool budget grid:
   - "Token Caps" header + 4-input grid
   - "Global token cap (fallback)" + 1 input
4. Edit `Investigate` token cap from 200000 to 220000, click Save
5. Confirm via API:
   ```bash
   TOKEN=$(grep -oP '(?<="hp1_auth_token":")[^"]+' ~/.deathstar_token 2>/dev/null || echo "")
   curl -s -H "Authorization: Bearer $TOKEN" \
     http://192.168.199.10:8000/api/settings | \
     jq '.settings.agentMaxTotalTokens_investigate'
   # Expected: 220000
   ```

Force-refresh the browser after deploy to clear stale JS bundles.

---

## Why this didn't land in v2.47.13

Unknown — possibly CC's run hit a context cap, or the str_replace edit
in OptionsModal.jsx failed silently due to indentation mismatch and
the run continued past it. Either way, the v2.47.13 commit (e030f67)
only contains the `api/routers/settings.py` change. v2.47.14 closes
the gap with explicit before/after blocks for both files.

This is also a reminder for future settings-driven features: verify
all 4 layers (backend `SETTINGS_KEYS`, frontend `DEFAULTS`,
`SERVER_KEYS`, JSX render) actually changed before marking a prompt
DONE. The backend-only state is functional but invisible to operators.

---

## Version bump

Update `VERSION`: `2.47.13` → `2.47.14`

---

## Commit

```bash
git add -A
git commit -m "fix(gui): v2.47.14 wire token cap settings into Agent Budgets section"
git push origin main
```

Deploy:

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

After deploy:
- 5 token-cap inputs visible in Settings → AI Services → Agent Budgets
- Operator tunes any of them live via the GUI; effect on next agent step
- Trace shows `agent_type=` on any cap-exceeded message
