# CC PROMPT — v2.45.24 — feat(ui): Facts & Knowledge settings tab

## What this does
Adds a "Facts & Knowledge" tab to OptionsModal exposing the 27 settings keys
currently API-only. Per the v2.45.17 audit, all 27 keys are registered in
`api/routers/settings.py` (lines 82–121) and `OptionsContext.jsx` defaults,
but there is no UI to edit them — operators must POST `/api/settings`
directly or set env vars.

This prompt:
1. Adds `'Facts & Knowledge'` to the TABS array in OptionsModal.jsx.
2. Creates a `FactsKnowledgeTab` component grouped by purpose (injection,
   half-life decay, source weights, age rejection, runbook injection,
   preflight panel).
3. Wires the new tab into OptionsModal's tab routing.

Version bump: 2.45.23 → 2.45.24

---

## Context

Existing TABS:
```javascript
export const TABS = ['General', 'Infrastructure', 'AI Services', 'Connections',
'Allowlist', 'Permissions', 'Facts Permissions', 'Access', 'Naming',
'Appearance', 'Notifications', 'Layouts']
```

The 27 keys to expose (from `api/routers/settings.py` Facts & Knowledge group):
- Injection: `factInjectionThreshold`, `factInjectionMaxRows`, `factInjectionTopN`
- Half-life: `factHalfLifeHours_collector`, `factHalfLifeHours_agent`,
  `factHalfLifeHours_manual_phase1`, `factHalfLifeHours_manual_phase2`,
  `factHalfLifeHours_agent_volatile`, `factVerifyCountCap`
- Source weights: `factSourceWeight_manual`, `factSourceWeight_proxmox_collector`,
  `factSourceWeight_swarm_collector`, `factSourceWeight_docker_agent_collector`,
  `factSourceWeight_pbs_collector`, `factSourceWeight_fortiswitch_collector`,
  `factSourceWeight_kafka_collector`, `factSourceWeight_agent_observation`,
  `factSourceWeight_rag_extraction`
- Age rejection: `factAgeRejectionMode` (off/soft/medium/hard),
  `factAgeRejectionMaxAgeMin`, `factAgeRejectionMinConfidence`
- Runbook: `runbookInjectionMode` (off/replace/augment/replace+shrink),
  `runbookClassifierMode` (off/heuristic/llm)
- Preflight: `preflightPanelMode` (off/on_ambiguity/always_visible),
  `preflightLLMFallbackEnabled`, `preflightDisambiguationTimeout`

CC: cross-check the actual list against `SETTINGS_KEYS` in
`api/routers/settings.py` — if any key in the list above is missing or named
differently in the source, use the source-of-truth name. If keys exist that
the list above is missing (e.g. v2.36+ additions), include them under the
appropriate section.

---

## Change 1 — TABS array

In `gui/src/components/OptionsModal.jsx`, find:

```javascript
export const TABS = ['General', 'Infrastructure', 'AI Services', 'Connections', 'Allowlist', 'Permissions', 'Facts Permissions', 'Access', 'Naming', 'Appearance', 'Notifications', 'Layouts']
```

Replace with:

```javascript
export const TABS = ['General', 'Infrastructure', 'AI Services', 'Connections', 'Allowlist', 'Permissions', 'Facts Permissions', 'Facts & Knowledge', 'Access', 'Naming', 'Appearance', 'Notifications', 'Layouts']
```

(Added `'Facts & Knowledge'` between `'Facts Permissions'` and `'Access'`.)

---

## Change 2 — FactsKnowledgeTab component

In `gui/src/components/OptionsModal.jsx`, find a good spot to add the
component (near the other named tab functions like `NotificationsTab`,
`PermissionsTab`, etc.). Pattern-match the existing tab's structure: takes
`{ draft, update }`, renders `Field` + input controls, calls
`update('keyName', value)` on change.

Add this function:

```javascript
export function FactsKnowledgeTab({ draft, update }) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-[color:var(--text-1)] mb-3">Injection</h3>

      <Field
        label="Injection threshold"
        hint="Confidence floor for facts shown to the agent (0.0–1.0). Default 0.7."
      >
        <TextInput
          type="number"
          value={draft.factInjectionThreshold ?? 0.7}
          onChange={v => update('factInjectionThreshold', parseFloat(v) || 0)}
        />
      </Field>

      <Field
        label="Max rows injected"
        hint="Hard cap on facts injected into the system prompt. Default 40."
      >
        <TextInput
          type="number"
          value={draft.factInjectionMaxRows ?? 40}
          onChange={v => update('factInjectionMaxRows', parseInt(v) || 0)}
        />
      </Field>

      <h3 className="text-sm font-semibold text-[color:var(--text-1)] mt-6 mb-3">Half-life decay (hours)</h3>

      <Field
        label="Collector facts"
        hint="How fast collector facts age out. Default 168h (7 days)."
      >
        <TextInput
          type="number"
          value={draft.factHalfLifeHours_collector ?? 168}
          onChange={v => update('factHalfLifeHours_collector', parseFloat(v) || 0)}
        />
      </Field>

      <Field label="Agent observation" hint="Default 24h.">
        <TextInput
          type="number"
          value={draft.factHalfLifeHours_agent ?? 24}
          onChange={v => update('factHalfLifeHours_agent', parseFloat(v) || 0)}
        />
      </Field>

      <Field label="Volatile (probes)" hint="Short-lived probes (TCP reachability). Default 2h.">
        <TextInput
          type="number"
          value={draft.factHalfLifeHours_agent_volatile ?? 2}
          onChange={v => update('factHalfLifeHours_agent_volatile', parseFloat(v) || 0)}
        />
      </Field>

      <Field label="Manual phase 1 (≤30d)" hint="Default 720h (30d).">
        <TextInput
          type="number"
          value={draft.factHalfLifeHours_manual_phase1 ?? 720}
          onChange={v => update('factHalfLifeHours_manual_phase1', parseFloat(v) || 0)}
        />
      </Field>

      <Field label="Manual phase 2 (>30d)" hint="Default 1440h (60d).">
        <TextInput
          type="number"
          value={draft.factHalfLifeHours_manual_phase2 ?? 1440}
          onChange={v => update('factHalfLifeHours_manual_phase2', parseFloat(v) || 0)}
        />
      </Field>

      <Field label="Verify-count cap" hint="Cap on verify_count for confidence boost. Default 10.">
        <TextInput
          type="number"
          value={draft.factVerifyCountCap ?? 10}
          onChange={v => update('factVerifyCountCap', parseInt(v) || 0)}
        />
      </Field>

      <h3 className="text-sm font-semibold text-[color:var(--text-1)] mt-6 mb-3">Source weights</h3>

      {[
        ['manual',                   1.0],
        ['proxmox_collector',        0.9],
        ['swarm_collector',          0.9],
        ['docker_agent_collector',   0.85],
        ['pbs_collector',            0.85],
        ['fortiswitch_collector',    0.85],
        ['kafka_collector',          0.8],
        ['agent_observation',        0.5],
        ['rag_extraction',           0.4],
      ].map(([src, dflt]) => {
        const key = `factSourceWeight_${src}`
        return (
          <Field key={src} label={src} hint={`Default ${dflt}.`}>
            <TextInput
              type="number"
              value={draft[key] ?? dflt}
              onChange={v => update(key, parseFloat(v) || 0)}
            />
          </Field>
        )
      })}

      <h3 className="text-sm font-semibold text-[color:var(--text-1)] mt-6 mb-3">Fact-age rejection</h3>

      <Field label="Mode" hint="off | soft | medium | hard">
        <select
          value={draft.factAgeRejectionMode ?? 'medium'}
          onChange={e => update('factAgeRejectionMode', e.target.value)}
          className="w-full bg-[color:var(--bg-2)] border border-[color:var(--border)] rounded px-3 py-1.5 text-xs"
        >
          <option value="off">off</option>
          <option value="soft">soft</option>
          <option value="medium">medium</option>
          <option value="hard">hard</option>
        </select>
      </Field>

      <Field label="Max age (minutes)" hint="Default 5.">
        <TextInput
          type="number"
          value={draft.factAgeRejectionMaxAgeMin ?? 5}
          onChange={v => update('factAgeRejectionMaxAgeMin', parseInt(v) || 0)}
        />
      </Field>

      <Field label="Min confidence" hint="Default 0.85.">
        <TextInput
          type="number"
          value={draft.factAgeRejectionMinConfidence ?? 0.85}
          onChange={v => update('factAgeRejectionMinConfidence', parseFloat(v) || 0)}
        />
      </Field>

      <h3 className="text-sm font-semibold text-[color:var(--text-1)] mt-6 mb-3">Runbook injection</h3>

      <Field label="Mode" hint="off | replace | augment | replace+shrink">
        <select
          value={draft.runbookInjectionMode ?? 'replace'}
          onChange={e => update('runbookInjectionMode', e.target.value)}
          className="w-full bg-[color:var(--bg-2)] border border-[color:var(--border)] rounded px-3 py-1.5 text-xs"
        >
          <option value="off">off</option>
          <option value="replace">replace</option>
          <option value="augment">augment</option>
          <option value="replace+shrink">replace+shrink</option>
        </select>
      </Field>

      <Field label="Classifier mode" hint="off | heuristic | llm">
        <select
          value={draft.runbookClassifierMode ?? 'heuristic'}
          onChange={e => update('runbookClassifierMode', e.target.value)}
          className="w-full bg-[color:var(--bg-2)] border border-[color:var(--border)] rounded px-3 py-1.5 text-xs"
        >
          <option value="off">off</option>
          <option value="heuristic">heuristic</option>
          <option value="llm">llm</option>
        </select>
      </Field>

      <h3 className="text-sm font-semibold text-[color:var(--text-1)] mt-6 mb-3">Preflight</h3>

      <Field label="Panel mode" hint="off | on_ambiguity | always_visible">
        <select
          value={draft.preflightPanelMode ?? 'always_visible'}
          onChange={e => update('preflightPanelMode', e.target.value)}
          className="w-full bg-[color:var(--bg-2)] border border-[color:var(--border)] rounded px-3 py-1.5 text-xs"
        >
          <option value="off">off</option>
          <option value="on_ambiguity">on_ambiguity</option>
          <option value="always_visible">always_visible</option>
        </select>
      </Field>

      <Field label="LLM fallback enabled">
        <Toggle
          value={!!draft.preflightLLMFallbackEnabled}
          onChange={v => update('preflightLLMFallbackEnabled', v)}
          label="Use LLM tier when regex + keyword tiers fail"
        />
      </Field>

      <Field label="Disambiguation timeout (seconds)" hint="Default 300.">
        <TextInput
          type="number"
          value={draft.preflightDisambiguationTimeout ?? 300}
          onChange={v => update('preflightDisambiguationTimeout', parseInt(v) || 0)}
        />
      </Field>
    </div>
  )
}
```

---

## Change 3 — wire tab into the modal

CC: locate the `OptionsModal` component body where it routes `activeTab` to a
component (look for `{activeTab === 'General' && <GeneralTab ...`). Add a
new branch:

```javascript
{activeTab === 'Facts & Knowledge' && <FactsKnowledgeTab draft={draft} update={update} />}
```

Place it next to the other tab-render lines, in a logical position (after
'Facts Permissions' before 'Access').

---

## Verify

```bash
cd gui && npm run build 2>&1 | tail -30
```

Expected: build succeeds. After deploy, opening Settings → Facts & Knowledge
should show the 6 sections (Injection, Half-life, Source weights, Age
rejection, Runbook, Preflight) with editable inputs reflecting current values.

---

## Version bump

Update `VERSION`: `2.45.23` → `2.45.24`

---

## Commit

```
git add -A
git commit -m "feat(ui): v2.45.24 Facts & Knowledge settings tab"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
