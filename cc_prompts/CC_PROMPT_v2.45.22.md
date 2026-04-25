# CC PROMPT — v2.45.22 — feat(ui): wire PreflightPanel — preflight_needed WS handler + Commands import

## What this does
Connects the orphaned `gui/src/components/PreflightPanel.jsx` (187 lines,
v2.35.1) to the live agent output. Currently:
- Backend emits `preflight_needed` WS events when entity disambiguation is
  required.
- `AgentOutputContext.jsx` has no handler — the events are dropped.
- The component is imported nowhere — it never renders.

This prompt:
1. Adds a `preflight` state slot to `AgentOutputContext.jsx`.
2. Adds a `preflight_needed` WS message handler.
3. Imports + renders `PreflightPanel` inside the Commands view, with picker
   callbacks that POST the chosen entity ID to the resume endpoint.

Version bump: 2.45.21 → 2.45.22

---

## Context

The component already implements its UI (candidates list, refine box, cancel,
countdown timer). It expects these props:

```
preflight, sessionId, onPick, onRefine, onCancel,
mode = 'always_visible', timeoutSec = 300
```

And consumes a `preflight` object with shape:

```json
{
  "ambiguous": true,
  "candidates": [...],
  "preflight_facts": [...],
  "agent_type": "investigate",
  "tier_used": "regex|keyword|llm"
}
```

The backend resume endpoint is `POST /api/agent/preflight/{session_id}/resolve`
with body `{ "entity_id": "..." }` — confirm the path against
`api/routers/agent.py` (search for `preflight` route handlers); if a different
path exists, use that instead.

CC: search `api/routers/agent.py` for `preflight` to confirm the resolve
endpoint path before wiring the onPick handler. Update the fetch URL in
Change 3 below to match the actual route.

---

## Change 1 — `gui/src/context/AgentOutputContext.jsx` — add `preflight` state

Find the block of `useState` declarations near the top of `AgentOutputProvider`.
After `const [subAgents, setSubAgents] = useState([])`, insert:

```javascript
  const [preflight, setPreflight] = useState(null)  // v2.45.22
```

---

## Change 2 — `gui/src/context/AgentOutputContext.jsx` — handle WS event

Find the `onMsg` callback inside the `useEffect`. Look for one of the existing
type handlers, e.g. `if (t === 'subagent_done')`. Right AFTER that block (and
before the `if (msg._isProposal)` block), insert:

```javascript
      // ── preflight_needed (v2.45.22) ───────────────────────────────────────
      // Backend has classified the task and detected ambiguity in entity
      // resolution. Render the PreflightPanel so the operator can pick one.
      if (t === 'preflight_needed') {
        setPreflight({
          ambiguous:        msg.ambiguous !== false,
          candidates:       msg.candidates       || [],
          preflight_facts:  msg.preflight_facts  || [],
          agent_type:       msg.agent_type       || '',
          tier_used:        msg.tier_used        || '',
          session_id:       msg.session_id       || '',
        })
        return
      }
      // Clear preflight on terminal events
      if (t === 'preflight_resolved' || t === 'preflight_cancelled') {
        setPreflight(null)
        return
      }
```

Also, find the existing `if (t === 'agent_start')` handler. Inside it, near
the other `setX(null)` calls (e.g. `setHallucinationBlocks([])`,
`setSubAgents([])`), add:

```javascript
        setPreflight(null)                // ← clear preflight on new run
```

Also, find the `clearOutput` callback. Inside it, alongside the other
`setX` resets, add:

```javascript
    setPreflight(null)
```

---

## Change 3 — `gui/src/context/AgentOutputContext.jsx` — expose in context

Find the `<AgentOutputContext.Provider value={{...}}>` JSX block. Add `preflight`
to the value object:

```javascript
      hallucinationBlocks,
      agentDiag,
      subAgents,
      preflight,                  // ← add this
      setPreflight,               // ← add this so panel can clear it on resolve
```

---

## Change 4 — Commands view — render PreflightPanel

CC: locate the file that renders the agent output / Commands page. The most
likely candidates are:
- `gui/src/components/CommandsView.jsx`
- `gui/src/components/OutputPanel.jsx`
- `gui/src/views/Commands.jsx`

Use the directory listing under `gui/src/components` and `gui/src/views` to
identify the actual file. Look for a component that uses `useAgentOutput()`
and renders the agent feed, plan modal, or escalation banner — that is where
the panel belongs.

Inside that component, near the top, add the import:

```javascript
import PreflightPanel from './PreflightPanel'   // path relative to the file
```

(Adjust path if PreflightPanel lives in a different directory than the
caller file.)

In the component body, destructure the new fields:

```javascript
const { preflight, setPreflight, currentSessionId } = useAgentOutput()
```

(Merge into the existing `useAgentOutput()` destructure if it is already
called — do not call it twice.)

Then, in the render output, ABOVE the agent feed (above any plan modal /
escalation banner / feed list), insert:

```jsx
{preflight && (
  <PreflightPanel
    preflight={preflight}
    sessionId={preflight.session_id || currentSessionId}
    mode="always_visible"
    timeoutSec={300}
    onPick={async (entityId) => {
      try {
        await fetch(
          `/api/agent/preflight/${preflight.session_id || currentSessionId}/resolve`,
          {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ entity_id: entityId }),
          },
        )
      } catch (e) { console.error('preflight resolve failed', e) }
      setPreflight(null)
    }}
    onRefine={async (refinedTask) => {
      try {
        await fetch(
          `/api/agent/preflight/${preflight.session_id || currentSessionId}/refine`,
          {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refined_task: refinedTask }),
          },
        )
      } catch (e) { console.error('preflight refine failed', e) }
      setPreflight(null)
    }}
    onCancel={async () => {
      try {
        await fetch(
          `/api/agent/preflight/${preflight.session_id || currentSessionId}/cancel`,
          { method: 'POST', credentials: 'include' },
        )
      } catch (e) { console.error('preflight cancel failed', e) }
      setPreflight(null)
    }}
  />
)}
```

CC: if any of `/api/agent/preflight/{sid}/resolve|refine|cancel` routes do
not exist in `api/routers/agent.py`, leave the fetch handlers as-is and add a
TODO comment above each — operators can wire the backend in a follow-up
prompt. The frontend rendering must work either way.

---

## Verify

```bash
# Frontend lint
cd gui && npm run lint 2>&1 | head -30 || true
cd ..
# Optional: build
# cd gui && npm run build && cd ..
grep -n "preflight_needed\|setPreflight" gui/src/context/AgentOutputContext.jsx
grep -rn "PreflightPanel" gui/src/components gui/src/views 2>/dev/null | head -10
```

Expected: `setPreflight` referenced from at least 2 places in
AgentOutputContext.jsx; `PreflightPanel` imported in at least one
component file outside its own definition.

---

## Version bump

Update `VERSION`: `2.45.21` → `2.45.22`

---

## Commit

```
git add -A
git commit -m "feat(ui): v2.45.22 wire PreflightPanel — preflight_needed handler + Commands view import"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
