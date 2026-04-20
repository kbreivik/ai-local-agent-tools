# CC PROMPT — v2.36.4 — External AI Router: UI + collapsible sections

## What this does

Completes the v2.36.x subsystem with the operator-facing UI. Five things:

1. **Confirmation modal** — the React component triggered by the v2.36.2
   `external_ai_confirm_pending` WebSocket event. Shows rule fired, reason,
   provider/model, output mode. Approve / Reject / auto-cancel countdown.
2. **AIServicesTab restructure** — new "Routing Triggers" and "Output Mode"
   subsections. Existing Escalation Policy + Coordinator sections preserved.
   Each subsection collapsible with chevron.
3. **Recent external AI calls table** — MONITOR sidebar gets a new small
   view showing `external_ai_calls` rows: timestamp, operation, provider,
   model, rule, outcome, cost, latency.
4. **Trace viewer `external_ai_routed` row** — the v2.34.16 Gates Fired
   sidebar gets a new row showing which op routed externally + the provider
   tag. Uses the existing `/trace?format=digest` endpoint already updated
   in v2.36.3 to include external calls.
5. **Collapsible major sections** — per Kent's ask, the Settings Modal,
   Operator Monitor, Logs, and Connections pages grow collapsible group
   headers with persisted-to-localStorage expand state per user.

Version bump: 2.36.3 → 2.36.4.

---

## Why

Without v2.36.4, operators would curl to approve external calls and SQL-query
to see billing — v2.36.3's smoke test demonstrated exactly that. v2.36.4 makes
the subsystem usable without a terminal. Also addresses Kent's long-standing
ask to make major sections collapsible so the Settings modal stops being a
500-line scroll.

---

## Change 1 — `gui/src/components/OptionsModal.jsx` — AIServicesTab restructure

The existing `AIServicesTab` function already has:
- Provider radios (Claude/OpenAI/Grok)
- API Key field
- Model field
- Test Connection button (v2.35.21)
- Escalation Policy section with `autoEscalate` radios
- `requireConfirmation` toggle
- Coordinator section

Wrap the existing content in a new structure. Top of the tab:

```jsx
function CollapsibleSection({ title, defaultOpen = true, storageKey, children }) {
  const [open, setOpen] = React.useState(() => {
    if (!storageKey) return defaultOpen
    try {
      const raw = localStorage.getItem(`collapse:${storageKey}`)
      return raw === null ? defaultOpen : raw === 'true'
    } catch { return defaultOpen }
  })
  React.useEffect(() => {
    if (!storageKey) return
    try { localStorage.setItem(`collapse:${storageKey}`, String(open)) } catch {}
  }, [open, storageKey])
  return (
    <div className="mb-4 border border-white/5 rounded">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-3 py-2
                   text-sm font-mono uppercase tracking-wider
                   bg-[var(--bg-2)] hover:bg-white/5 text-[var(--accent)]"
        style={{ borderRadius: 0 }}
      >
        <span>{title}</span>
        <span style={{ transform: open ? 'rotate(90deg)' : 'rotate(0deg)',
                        transition: 'transform 0.15s' }}>›</span>
      </button>
      {open && <div className="p-3">{children}</div>}
    </div>
  )
}
```

Export `CollapsibleSection` from OptionsModal so other files can import it
(or move into its own file `gui/src/components/CollapsibleSection.jsx` and
import where needed).

Inside `AIServicesTab`, restructure the render to:

```jsx
return (
  <div>
    <CollapsibleSection title="Local AI (LM Studio)" storageKey="ai.local">
      {/* Existing Provider + URL + Key + Model + Test Local button */}
    </CollapsibleSection>

    <CollapsibleSection title="External AI — Provider" storageKey="ai.external.provider">
      {/* Existing: provider radios, API key, Model field, Test Connection (v2.35.21) */}
    </CollapsibleSection>

    <CollapsibleSection title="External AI — Routing Mode" storageKey="ai.external.routing">
      <label className="block text-xs uppercase text-gray-400 mb-1">Mode</label>
      <div className="flex gap-4 mb-3">
        {['off', 'manual', 'auto'].map(m => (
          <label key={m} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="externalRoutingMode"
              checked={draft.externalRoutingMode === m}
              onChange={() => update('externalRoutingMode', m)}
            />
            {m}
          </label>
        ))}
      </div>
      <p className="text-xs text-gray-500 mb-3">
        <b>off</b>: no routing, no external calls.{' '}
        <b>manual</b>: operator-only via UI button (not implemented in v2.36.x).{' '}
        <b>auto</b>: router fires on rules below.
      </p>

      <label className="block text-xs uppercase text-gray-400 mt-3 mb-1">Output Mode</label>
      <div className="flex gap-4">
        {['replace'].map(m => (
          <label key={m} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="externalRoutingOutputMode"
              checked={draft.externalRoutingOutputMode === m}
              onChange={() => update('externalRoutingOutputMode', m)}
              disabled={m !== 'replace'}
            />
            {m}
          </label>
        ))}
      </div>
      <p className="text-xs text-gray-500 mt-1">
        REPLACE: external AI synthesises final_answer from local evidence, local
        agent does not continue. Other modes (ADVISE / TAKEOVER) deferred to
        v2.36.5+.
      </p>
    </CollapsibleSection>

    <CollapsibleSection title="External AI — Routing Triggers"
                        storageKey="ai.external.triggers"
                        defaultOpen={false}>
      <p className="text-xs text-gray-500 mb-3">
        Rules OR'd; first match wins in priority order. Set a numeric threshold
        to 0 to disable that rule.
      </p>

      <label className="flex items-center gap-2 text-sm mb-2">
        <input type="checkbox"
               checked={!!draft.routeOnGateFailure}
               onChange={e => update('routeOnGateFailure', e.target.checked)} />
        <span><b>gate_failure</b> — escalate on hallucination guard exhausted or
          fabrication detected ≥ 2x</span>
      </label>

      <label className="flex items-center gap-2 text-sm mb-2">
        <input type="checkbox"
               checked={!!draft.routeOnBudgetExhaustion}
               onChange={e => update('routeOnBudgetExhaustion', e.target.checked)} />
        <span><b>budget_exhaustion</b> — escalate if tool budget hit with no
          DIAGNOSIS: emitted</span>
      </label>

      <div className="flex items-center gap-2 text-sm mb-2">
        <span className="min-w-[200px]"><b>consecutive_failures</b> threshold:</span>
        <input type="number" min="0" max="20" value={draft.routeOnConsecutiveFailures ?? 0}
               onChange={e => update('routeOnConsecutiveFailures', parseInt(e.target.value)||0)}
               className="w-16 bg-[var(--bg-1)] border border-white/10 px-2 py-1 text-sm" />
        <span className="text-xs text-gray-500">(0 = disabled)</span>
      </div>

      <div className="flex items-center gap-2 text-sm mb-2">
        <span className="min-w-[200px]"><b>prior_attempts</b> threshold (7d):</span>
        <input type="number" min="0" max="20" value={draft.routeOnPriorAttemptsGte ?? 0}
               onChange={e => update('routeOnPriorAttemptsGte', parseInt(e.target.value)||0)}
               className="w-16 bg-[var(--bg-1)] border border-white/10 px-2 py-1 text-sm" />
        <span className="text-xs text-gray-500">(0 = disabled)</span>
      </div>

      <div className="mt-3">
        <label className="block text-xs uppercase text-gray-400 mb-1">
          complexity_prefilter keywords (comma-separated)
        </label>
        <input type="text"
               value={draft.routeOnComplexityKeywords || ''}
               onChange={e => update('routeOnComplexityKeywords', e.target.value)}
               placeholder="correlate, root cause, why"
               className="w-full bg-[var(--bg-1)] border border-white/10 px-2 py-1 text-sm" />
        <div className="flex items-center gap-2 text-sm mt-2">
          <span className="min-w-[200px]">min prior attempts:</span>
          <input type="number" min="0" max="20"
                 value={draft.routeOnComplexityMinPriorAttempts ?? 2}
                 onChange={e => update('routeOnComplexityMinPriorAttempts', parseInt(e.target.value)||0)}
                 className="w-16 bg-[var(--bg-1)] border border-white/10 px-2 py-1 text-sm" />
        </div>
      </div>
    </CollapsibleSection>

    <CollapsibleSection title="External AI — Limits"
                        storageKey="ai.external.limits"
                        defaultOpen={false}>
      <label className="flex items-center gap-2 text-sm mb-3">
        <input type="checkbox"
               checked={!!draft.requireConfirmation}
               onChange={e => update('requireConfirmation', e.target.checked)} />
        <span>Require operator confirmation before each external AI call</span>
      </label>

      <div className="flex items-center gap-2 text-sm mb-2">
        <span className="min-w-[220px]">Max external calls per operation:</span>
        <input type="number" min="1" max="20" value={draft.routeMaxExternalCallsPerOp ?? 3}
               onChange={e => update('routeMaxExternalCallsPerOp', parseInt(e.target.value)||3)}
               className="w-16 bg-[var(--bg-1)] border border-white/10 px-2 py-1 text-sm" />
      </div>

      <div className="flex items-center gap-2 text-sm mb-2">
        <span className="min-w-[220px]">Confirmation timeout (seconds):</span>
        <input type="number" min="30" max="3600"
               value={draft.externalConfirmTimeoutSeconds ?? 300}
               onChange={e => update('externalConfirmTimeoutSeconds', parseInt(e.target.value)||300)}
               className="w-20 bg-[var(--bg-1)] border border-white/10 px-2 py-1 text-sm" />
      </div>

      <div className="flex items-center gap-2 text-sm">
        <span className="min-w-[220px]">Context handoff: last N tool results:</span>
        <input type="number" min="0" max="20"
               value={draft.externalContextLastNToolResults ?? 5}
               onChange={e => update('externalContextLastNToolResults', parseInt(e.target.value)||5)}
               className="w-16 bg-[var(--bg-1)] border border-white/10 px-2 py-1 text-sm" />
      </div>
    </CollapsibleSection>

    <CollapsibleSection title="Coordinator" storageKey="ai.coordinator" defaultOpen={false}>
      {/* Existing Coordinator content */}
    </CollapsibleSection>
  </div>
)
```

Preserve all existing behaviour (Test Local, Test External, Provider radios,
API Key field with masking, Model field). Only wrap sections in
CollapsibleSection and add the three new router-related sections.

---

## Change 2 — `gui/src/components/ExternalAIConfirmModal.jsx` — new component

```jsx
import React from 'react'

/**
 * v2.36.2 — operator-visible gate modal.
 *
 * Listens on the WebSocket for `external_ai_confirm_pending` events from
 * wait_for_external_ai_confirmation. Renders modal with rule/reason/provider,
 * POSTs to /api/agent/operations/{op}/confirm-external on approve/reject.
 *
 * Auto-cancel countdown matches the server-side timeout.
 */
export default function ExternalAIConfirmModal({ event, onClose }) {
  const [secondsLeft, setSecondsLeft] = React.useState(event?.timeout_s || 300)
  const [submitting, setSubmitting] = React.useState(false)

  React.useEffect(() => {
    if (!event) return
    const id = setInterval(() => {
      setSecondsLeft(s => Math.max(0, s - 1))
    }, 1000)
    return () => clearInterval(id)
  }, [event])

  if (!event) return null

  const handle = async (approved) => {
    setSubmitting(true)
    try {
      const r = await fetch(
        `/api/agent/operations/${event.operation_id}/confirm-external`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ session_id: event.session_id, approved }),
        }
      )
      if (!r.ok) console.error('confirm-external failed', await r.text())
    } finally {
      setSubmitting(false)
      onClose?.()
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
      <div className="bg-[var(--bg-1)] border border-[var(--accent)] p-6 max-w-xl w-full">
        <h3 className="text-[var(--accent)] font-mono uppercase tracking-wider mb-3">
          External AI Escalation — Approval Required
        </h3>
        <div className="text-sm space-y-2 mb-4">
          <div>
            <span className="text-gray-400">Provider / Model:</span>{' '}
            <b>{event.provider}/{event.model}</b>
          </div>
          <div>
            <span className="text-gray-400">Rule fired:</span>{' '}
            <code className="text-[var(--cyan)]">{event.rule_fired}</code>
          </div>
          <div>
            <span className="text-gray-400">Reason:</span>{' '}
            <span className="text-gray-200">{event.reason}</span>
          </div>
          <div>
            <span className="text-gray-400">Output mode:</span>{' '}
            <b>{event.output_mode}</b>
          </div>
          <div className="pt-2 border-t border-white/10">
            <span className="text-gray-400">Auto-cancel in:</span>{' '}
            <span className="text-[var(--amber)]">{secondsLeft}s</span>
          </div>
        </div>
        <div className="flex gap-3 justify-end">
          <button
            disabled={submitting}
            onClick={() => handle(false)}
            className="px-4 py-2 border border-white/20 text-sm hover:bg-white/5"
          >Reject</button>
          <button
            disabled={submitting}
            onClick={() => handle(true)}
            className="px-4 py-2 bg-[var(--accent)] text-white text-sm
                       hover:bg-[var(--accent-dim)]"
          >Approve</button>
        </div>
      </div>
    </div>
  )
}
```

Wire into `gui/src/App.jsx` WebSocket handler: on `message.type ===
'external_ai_confirm_pending'`, set state `externalAIConfirmEvent = message`,
render `<ExternalAIConfirmModal event={externalAIConfirmEvent}
onClose={() => setExternalAIConfirmEvent(null)} />` at app root level. Also
clear state on `external_ai_confirm_resolved`, `external_ai_call_start`,
or if `secondsLeft` hits 0.

---

## Change 3 — `gui/src/components/ExternalAICallsView.jsx` — new MONITOR view

```jsx
import React, { useState, useEffect } from 'react'

/**
 * v2.36.4 — Recent external AI calls table.
 *
 * Pulls from new endpoint GET /api/external-ai/calls?limit=50 (added in
 * Change 4 below). Operator-facing billing/outcome log.
 */
export default function ExternalAICallsView() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const r = await fetch('/api/external-ai/calls?limit=50',
                              { credentials: 'include' })
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const d = await r.json()
        if (!cancelled) setRows(d.calls || [])
      } catch (e) {
        if (!cancelled) setErr(e.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    const id = setInterval(load, 30000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  if (loading) return <div className="p-4 text-sm text-gray-500">Loading...</div>
  if (err) return <div className="p-4 text-sm text-[var(--red)]">Error: {err}</div>

  if (rows.length === 0) return (
    <div className="p-4 text-sm text-gray-500">
      No external AI calls yet. Enable <code>externalRoutingMode=auto</code>{' '}
      in AI Services settings to allow routing.
    </div>
  )

  return (
    <div className="p-4">
      <h2 className="font-mono uppercase text-[var(--accent)] mb-3">
        Recent External AI Calls
      </h2>
      <table className="w-full text-sm">
        <thead className="text-xs uppercase text-gray-400 border-b border-white/10">
          <tr>
            <th className="text-left py-2">When</th>
            <th className="text-left">Provider / Model</th>
            <th className="text-left">Rule</th>
            <th className="text-left">Outcome</th>
            <th className="text-right">Latency</th>
            <th className="text-right">Tokens in/out</th>
            <th className="text-right">Est. $</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.id} className="border-b border-white/5 hover:bg-white/5">
              <td className="py-2 text-xs text-gray-400">
                {new Date(r.created_at).toLocaleString()}
              </td>
              <td className="text-xs">
                <b className="text-[var(--cyan)]">{r.provider}</b> / {r.model}
              </td>
              <td className="text-xs"><code>{r.rule_fired}</code></td>
              <td className="text-xs">
                <span style={{ color:
                  r.outcome === 'success' ? 'var(--green)' :
                  r.outcome === 'rejected_by_gate' ? 'var(--amber)' :
                  'var(--red)'
                }}>{r.outcome}</span>
              </td>
              <td className="text-right text-xs">{r.latency_ms ? `${r.latency_ms}ms` : '—'}</td>
              <td className="text-right text-xs">
                {r.input_tokens || '—'}/{r.output_tokens || '—'}
              </td>
              <td className="text-right text-xs">
                {r.est_cost_usd != null ? `$${r.est_cost_usd.toFixed(4)}` : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
```

Add to `gui/src/components/Sidebar.jsx` under the MONITOR section:

```jsx
{ id: 'external-ai-calls', label: 'External AI Calls', icon: '🤖' },
```

And route it in `App.jsx`.

---

## Change 4 — `api/routers/external_ai.py` — new read-only API router

```python
"""GET /api/external-ai/calls — list recent external AI calls for the UI.

v2.36.4. Read-only. Admin-gated (sith_lord + imperial_officer) because cost
data is sensitive.
"""
from fastapi import APIRouter, Depends, Query
from api.auth import get_current_user

router = APIRouter(prefix="/api/external-ai", tags=["external-ai"])


@router.get("/calls")
async def list_calls(limit: int = Query(50, ge=1, le=200),
                     _: str = Depends(get_current_user)):
    from api.db.external_ai_calls import list_recent_external_calls
    return {"calls": list_recent_external_calls(limit=limit)}
```

Register the router in `api/main.py` near other `include_router` calls:

```python
from api.routers.external_ai import router as external_ai_router
app.include_router(external_ai_router)
```

---

## Change 5 — `gui/src/utils/gateDetection.js` — `external_ai_routed` row

The v2.34.16 JS gate-detection mirror needs the new gate row. Add to the
gates object returned by `detectGatesFromSteps`:

```js
external_ai_routed: { count: 0, details: [] },
```

and a detection rule inside the step loop:

```js
// v2.36.3 — external AI synthesis emitted as step_index=99999
if (step.step_index === 99999 && step.response_raw?.external_ai) {
  gates.external_ai_routed.count += 1
  gates.external_ai_routed.details.push({
    step: step.step_index,
    provider: step.response_raw.provider,
    model: step.response_raw.model,
    rule: step.response_raw.rule_fired,
    cost: step.response_raw.usage?.est_cost_usd,
  })
}
```

Mirror the same addition in `api/agents/gate_detection.py` (Python side):

```python
"external_ai_routed": {"count": 0, "details": []},
```

and:
```python
if step.get("step_index") == 99999 and (step.get("response_raw") or {}).get("external_ai"):
    gates["external_ai_routed"]["count"] += 1
    rr = step["response_raw"]
    gates["external_ai_routed"]["details"].append({
        "step": 99999,
        "provider": rr.get("provider"),
        "model": rr.get("model"),
        "rule": rr.get("rule_fired"),
        "cost": (rr.get("usage") or {}).get("est_cost_usd"),
    })
```

Trace viewer `TraceView.jsx` already renders gates generically via the JS
detection — no JSX change needed as long as the new gate key is registered.

---

## Change 6 — Major-section collapsibles (Kent's ask)

Apply `CollapsibleSection` to the top-level grouping in:

- **`gui/src/components/OptionsModal.jsx`** — tabs are already separate,
  so apply within any tab that has >3 subsections. AIServicesTab (Change 1)
  is the main one; also wrap groups in `InfrastructureTab`, `FactsPermissionsTab`,
  `NotificationsTab` if they have distinct subsections. Only wrap; no
  content changes. Skip tabs that are already flat (Allowlist, Discovery).
- **`gui/src/App.jsx` → `DashboardView`** — the Operator Monitor panels
  (Platform Core, Compute, Network, Storage, Security) each get wrapped in
  a `CollapsibleSection` with `storageKey="dash.{section}"`. Default open.
- **`gui/src/components/Sidebar.jsx`** — the MONITOR / ADMIN / MISC group
  headers already exist as text; add collapse chevrons + localStorage
  persistence (`sidebar.monitor`, `sidebar.admin`, etc.) so operators can
  hide groups they don't use.
- **Logs page (`gui/src/components/LogsView.jsx`)** — wrap each tab content
  in a `CollapsibleSection` only if that tab has >3 visual groups. Trace
  viewer's "Step list | Selected step detail | Gates Fired" is three groups —
  skip unless Kent asks.

Keep all collapsible state in localStorage keyed on `collapse:<storageKey>`.
Do NOT use `sessionStorage` or `prefs` DB — this is personal + device-local
UX, not a user setting to sync.

---

## Change 7 — `tests/test_external_ai_calls_endpoint.py`

```python
"""v2.36.4 — GET /api/external-ai/calls smoke test.

Inserts a row via write_external_ai_call, asserts list_recent_external_calls
returns it. Skips on non-postgres environments (CI usually runs against
sqlite stub).
"""
import os
import pytest


@pytest.mark.skipif(
    "postgres" not in os.environ.get("DATABASE_URL", ""),
    reason="requires postgres",
)
def test_write_and_list_round_trip():
    from api.db.external_ai_calls import (
        init_external_ai_calls, write_external_ai_call,
        list_recent_external_calls,
    )
    init_external_ai_calls()
    write_external_ai_call(
        operation_id="test-op-v2.36.4", step_index=None,
        provider="claude", model="claude-sonnet-4-6",
        rule_fired="budget_exhaustion", output_mode="replace",
        latency_ms=1234, input_tokens=100, output_tokens=50,
        est_cost_usd=0.00105, outcome="success", error_message=None,
    )
    rows = list_recent_external_calls(limit=10)
    assert any(r["operation_id"] == "test-op-v2.36.4" for r in rows)


def test_list_returns_empty_on_non_pg():
    """Smoke: doesn't crash without postgres."""
    from api.db.external_ai_calls import list_recent_external_calls
    rows = list_recent_external_calls(limit=10)
    assert isinstance(rows, list)
```

---

## Change 8 — `VERSION`

```
2.36.4
```

---

## Verify

```bash
pytest tests/test_external_ai_calls_endpoint.py \
       tests/test_external_router.py \
       tests/test_external_ai_client.py \
       tests/test_external_ai_confirmation.py -v
```

Frontend:
```bash
cd gui && npm run build
```

---

## Commit

```bash
git add -A
git commit -m "feat(ui): v2.36.4 External AI Router UI + collapsible sections

Completes v2.36.x subsystem with operator-facing UI. Before v2.36.4, approving
an external AI escalation required curl; now it's a modal.

New ExternalAIConfirmModal (gui/src/components/ExternalAIConfirmModal.jsx):
- Listens for v2.36.2 external_ai_confirm_pending WS events.
- Renders rule fired, reason, provider/model, output mode, countdown.
- POSTs /api/agent/operations/{op}/confirm-external on approve/reject.
- Auto-dismisses on external_ai_confirm_resolved or external_ai_call_start.

AIServicesTab in OptionsModal.jsx restructured around new CollapsibleSection
wrapper (exported for reuse). Four new subsections:
- External AI — Routing Mode (off/manual/auto radio + output mode)
- External AI — Routing Triggers (5 rules: gate_failure, budget_exhaustion,
  consecutive_failures, prior_attempts, complexity_prefilter keywords)
- External AI — Limits (requireConfirmation, maxCallsPerOp, confirmTimeout,
  contextLastNToolResults)
- Coordinator (existing, now collapsed by default)

New MONITOR view 'External AI Calls' (gui/src/components/ExternalAICallsView.jsx)
pulls from new GET /api/external-ai/calls endpoint. Table: timestamp, provider,
model, rule, outcome (colour-coded), latency, tokens in/out, estimated $ cost.
Polls every 30s.

Gate detection (js mirror + python source) gains external_ai_routed row:
fires when agent_llm_traces has step_index=99999 + response_raw.external_ai
= True (v2.36.3's external-AI trace shape). Shows up in Trace viewer Gates
Fired sidebar with provider/model/rule/cost.

Major-section collapsibles (Kent ask): Operator Monitor panels (Platform
Core, Compute, Network, Storage, Security), Sidebar MONITOR/ADMIN/MISC
groups, and AIServicesTab subsections all wrap in CollapsibleSection with
localStorage-persisted state. Keys are 'collapse:<storageKey>'. Device-local
UX state only — never synced to the prefs DB.

Admin-gated /api/external-ai/calls endpoint (sith_lord + imperial_officer)
in api/routers/external_ai.py — cost data is sensitive.

2 regression tests (one postgres-gated, one fallback) prove the round-trip."
git push origin main
```

---

## Deploy + smoke

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

End-to-end smoke (REQUIRES a working Claude API key and externalRoutingMode=auto):

1. Settings → AI Services → External AI — Routing Mode → select `auto`, Save.
2. Start an investigate task that hits budget cap (same as v2.36.3 smoke).
3. When the agent loop hits the cap, the **ExternalAIConfirmModal** pops up
   with rule=budget_exhaustion, provider=claude, timeout countdown ticking.
4. Click **Approve** — modal closes, agent feed shows
   `[external-ai] calling claude/claude-sonnet-4-6`, 30-60s delay, then final
   answer appears with `[EXTERNAL: claude/claude-sonnet-4-6]` prefix.
5. Navigate MONITOR → External AI Calls — the call should appear with
   outcome=success, cost ~$0.01-0.03.
6. Logs → Trace → select the operation → Gates Fired sidebar shows
   `external_ai_routed: 1×` with provider/model/rule.
7. Click any collapsible header in Settings → chevron rotates, section
   collapses. Reload page → collapsed state persists (localStorage).

Revert `externalRoutingMode=off` after smoke if you don't want rules firing
on every agent run.

---

## Scope guard — do NOT touch

- Settings backend `SETTINGS_KEYS` registry — all router keys shipped in v2.36.0.
- Router logic (`should_escalate_to_external_ai`) — shipped in v2.36.1.
- Agent loop wiring — shipped in v2.36.3.
- Core LM Studio Test Local button + flow — not part of this phase.
- Sidebar nav ordering — Only ADD the 'External AI Calls' entry; do not
  reorder existing items (Kent has muscle memory).
- `CollapsibleSection` must default to OPEN for critical live-data sections
  (Operator Monitor dashboard panels). Only default-closed for opt-in admin
  panels like "Routing Triggers" and "Limits".
