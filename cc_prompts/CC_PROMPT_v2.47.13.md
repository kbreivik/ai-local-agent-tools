# CC PROMPT — v2.47.13 — feat(agent): register per-agent-type token cap settings

## What this does

Completes the v2.47.12 design by registering the four per-agent-type
token cap variables as real, GUI-editable settings.

v2.47.12 deployed `_token_cap_for(agent_type)` with a lookup chain
that already supports per-type keys — but only the global key
(`agentMaxTotalTokens`) was registered in `SETTINGS_KEYS`. This means
the per-type lookup branch was reachable in code but never matched
anything in the DB.

After this lands, the GUI Settings → Agent Budgets group shows:

| Existing (v2.47.12) | New (v2.47.13) |
|---------------------|-----------------|
| `agentToolBudget_observe` (8) | `agentMaxTotalTokens_observe` (80000) |
| `agentToolBudget_investigate` (16) | `agentMaxTotalTokens_investigate` (200000) |
| `agentToolBudget_execute` (14) | `agentMaxTotalTokens_execute` (150000) |
| `agentToolBudget_build` (12) | `agentMaxTotalTokens_build` (120000) |
| `agentMaxTotalTokens` (200000) | — already registered — |

**Zero code changes.** Pure settings-registry addition. The `_token_cap_for`
lookup chain in `api/routers/agent.py` already checks
`agentMaxTotalTokens_{canonical}` first — adding the keys to
`SETTINGS_KEYS` is what makes them take effect.

**Defaults rationale:**

| Type | Tool budget | Tool result avg | Estimated cumulative | Default |
|------|-------------|-----------------|----------------------|---------|
| observe | 8 | small (status snapshots) | ~50k | 80k |
| investigate | 16 | large (logs, queries) | ~150k | 200k |
| execute | 14 + verify | mixed | ~120k | 150k |
| build | 12 | moderate (skill code) | ~80k | 120k |

These match the global default (200k) for investigate, leave headroom
for the others, and can be tuned individually from the GUI without
redeploy.

**Range constraints:** All four use `min=10000, max=250000`. Setting
0 is not a valid "fall through to global" signal — instead the deployed
v2.47.12 `_coerce_token_cap` returns the hardcoded default for 0/invalid
values. Per-type keys with a non-zero value always win over the global.
This is intentional: operators tune the per-type value directly, and
the global is documented as a fallback for env-only setups.

Version bump: 2.47.12 → 2.47.13

---

## Change 1 — `api/routers/settings.py` — register four per-type token caps

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
    # Lookup at every cap check: per-type key → global → env → hardcoded.
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

CC: match the trailing-comma style of surrounding entries. The four
new keys belong inside the same `SETTINGS_KEYS` dict literal as
`agentMaxTotalTokens` and `agentToolBudget_*`.

---

## Verify

```bash
python -m py_compile api/routers/settings.py

# Confirm all five token-cap keys are registered
grep -n "agentMaxTotalTokens" api/routers/settings.py
# Expected: 5 matches (1 global + 4 per-type)
```

After deploy, confirm the keys appear in the API:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://192.168.199.10:8000/api/settings | \
  jq '.settings | with_entries(select(.key | contains("agentMaxTotalTokens")))'
# Expected: object with 5 keys
```

Confirm they appear in the GUI:
1. Open Settings → Agent Budgets group
2. Should see 4 new fields below the existing `agentMaxTotalTokens` entry
3. Edit `agentMaxTotalTokens_investigate` from 200000 to 220000, save
4. Trigger an investigate task; if cap fires, message shows
   `agent_type=investigate` and the tuned value 220000

Confirm per-type lookup works:
```bash
# Set per-type to a low value to force cap-exceeded
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  http://192.168.199.10:8000/api/settings \
  -d '{"agentMaxTotalTokens_observe": 15000}'

# Run an observe task that uses ~20k tokens
# Trace should show: "token cap exceeded (... > 15000, agent_type=observe)"

# Restore default
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  http://192.168.199.10:8000/api/settings \
  -d '{"agentMaxTotalTokens_observe": 80000}'
```

---

## What this does NOT do

- **Does not change the lookup chain semantics.** Setting a per-type
  value to 0 in the GUI still returns the hardcoded default (because
  v2.47.12's `_coerce_token_cap` treats 0 as misconfigured). To "use
  the global" the operator simply doesn't override the per-type — but
  since all four per-type keys are now registered with real defaults,
  the global is effectively a fallback for env-only setups.
- **Does not modify `_token_cap_for` or `_coerce_token_cap`.** The
  v2.47.12 implementation is unchanged. If a future version wants
  "set per-type to 0 → fall through to global" semantics, that's a
  separate code change in v2.47.14+.
- **Does not introduce a tree-wide token cap** for sub-agent trees.
  Each subagent still gets its own fresh per-type counter via fresh
  `StepState`.

---

## Version bump

Update `VERSION`: `2.47.12` → `2.47.13`

---

## Commit

```
git add -A
git commit -m "feat(agent): v2.47.13 register per-agent-type token cap settings"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

After deploy:
- 5 token-cap variables visible in Settings → Agent Budgets group
- Operator can tune any of them live via the GUI; effect on next agent step
- Trace shows `agent_type=` on any cap-exceeded message — guides further
  per-type tuning based on real workload data
