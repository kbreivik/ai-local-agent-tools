# CC PROMPT — v2.24.4 — Inline sub-task offer in AgentFeed/OutputPanel; remove dashboard banner

## What this does
Moves the sub-task offer from the persistent dashboard banner into the agent output stream,
where it belongs. When an investigate run finishes with proposals, the offer appears inline
at the bottom of AgentFeed and OutputPanel — right below the result — with [Run Sub-agent]
and [Manual Runbook] buttons. Clicking Run opens an independent popup window that can be
moved aside while working. The `SubtaskOfferBanner` is removed from the dashboard entirely.
Version bump: v2.24.3 → v2.24.4

## Change 1 — gui/src/context/AgentOutputContext.jsx

Three additions:

### 1a. Add `pendingProposals` state near the other useState declarations:
Find:
```js
  const [currentSessionId,     setCurrentSessionId]     = useState(null)
```
Add after it:
```js
  const [pendingProposals,     setPendingProposals]     = useState([])
```

### 1b. On `agent_start`, clear proposals. Find the `if (t === 'agent_start')` block and
add `setPendingProposals([])` alongside the other resets inside it:
```js
      if (t === 'agent_start') {
        agentTypeRef.current  = msg.agent_type || null
        sessionIdRef.current  = msg.session_id || null
        feedStartRef.current  = Date.now()
        setAgentType(msg.agent_type || null)
        setCurrentSessionId(msg.session_id || null)
        setRunState('running')
        setPendingProposals([])           // ← add this line
        setOutputLines(prev => [...prev.slice(-500), msg])
        setFeedLines([{ type: 'start' }])
        return
      }
```

### 1c. Accumulate proposals from WS and inject into feedLines on done.

Find the WS `onmessage` handler in `_ensureWS`. After the existing `subtask_proposed` dispatch:
```js
      if (msg.type === 'subtask_proposed') {
        window.dispatchEvent(new CustomEvent('ds:ws-message', { detail: msg }))
      }
```
Add below it (still inside the singleton `onmessage`):
```js
      if (msg.type === 'subtask_proposed' && msg.proposal_id) {
        // Accumulate — deduplicate by proposal_id via listener set
        _msgListeners.forEach(fn => fn({ ...msg, _isProposal: true }))
      }
```

Then in `onMsg` inside the Provider `useEffect`, add a handler for `_isProposal` messages.
Find the comment `// ── add every non-start message to the raw log` and add BEFORE it:
```js
      // ── accumulate subtask proposals ───────────────────────────────────────
      if (msg._isProposal) {
        setPendingProposals(prev => {
          if (prev.some(p => p.proposal_id === msg.proposal_id)) return prev
          return [...prev, {
            proposal_id:       msg.proposal_id,
            task:              msg.task              || '',
            executable_steps:  msg.executable_steps  || [],
            manual_steps:      msg.manual_steps      || [],
            confidence:        msg.confidence        || 'medium',
            parent_session_id: msg.parent_session_id || '',
          }]
        })
        return  // don't add raw proposal messages to outputLines
      }
```

Then in the `done` branch of `onMsg`, inject the offer into feedLines.
Find:
```js
        } else if (t === 'done') {
          const elapsed = feedStartRef.current
            ? ((Date.now() - feedStartRef.current) / 1000).toFixed(1)
            : '?'
          const stepsMatch = msg.content?.match(/after (\d+) steps/)
          const steps = stepsMatch ? parseInt(stepsMatch[1]) : '?'
          const doneSessionId = sessionIdRef.current || msg.session_id || ''
          setFeedLines(prev => [...prev, { type: 'done', steps, elapsed, sessionId: doneSessionId }])
```
Replace with:
```js
        } else if (t === 'done') {
          const elapsed = feedStartRef.current
            ? ((Date.now() - feedStartRef.current) / 1000).toFixed(1)
            : '?'
          const stepsMatch = msg.content?.match(/after (\d+) steps/)
          const steps = stepsMatch ? parseInt(stepsMatch[1]) : '?'
          const doneSessionId = sessionIdRef.current || msg.session_id || ''
          setFeedLines(prev => {
            const next = [...prev, { type: 'done', steps, elapsed, sessionId: doneSessionId }]
            // Inject proposal offer inline if proposals were recorded for this run
            setPendingProposals(proposals => {
              if (proposals.length > 0) {
                next.push({ type: 'subtask_offer', proposals })
              }
              return []  // clear after injecting
            })
            return next
          })
```

### 1d. Expose `pendingProposals` in context value. Find the Provider value object and add:
```js
      pendingProposals,
```
alongside the other exported values.

---

## Change 2 — gui/src/components/SubtaskOfferCard.jsx  (NEW FILE)

Create this new file at `gui/src/components/SubtaskOfferCard.jsx`:

```jsx
/**
 * SubtaskOfferCard — inline offer shown at the bottom of AgentFeed / OutputPanel
 * when an investigate run completes with propose_subtask() proposals.
 * Replaces SubtaskOfferBanner (which was a persistent dashboard banner — wrong UX).
 */
import { useState } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''
const POPUP_FEATURES = 'popup,width=760,height=560,resizable=yes'

export default function SubtaskOfferCard({ proposals, onDismiss }) {
  const [launched, setLaunched] = useState(false)

  if (!proposals || proposals.length === 0) return null
  const latest = proposals[0]
  const extra  = proposals.length - 1
  const confColor = { high: '#22c55e', medium: '#00c8ee', low: '#f59e0b' }[latest.confidence] ?? '#94a3b8'

  const runSubAgent = async () => {
    try {
      const r = await fetch(`${BASE}/api/agent/subtask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          proposal_id:       latest.proposal_id,
          task:              latest.task,
          parent_session_id: latest.parent_session_id,
        }),
      })
      const d = await r.json()
      if (d.session_id) {
        window.open(`/subtask/${d.session_id}`, `subtask-${d.session_id}`, POPUP_FEATURES)
        setLaunched(true)
        onDismiss?.()
      }
    } catch (e) { console.error('run subtask failed', e) }
  }

  const openRunbook = () => {
    window.open(`/runbook/${latest.proposal_id}`, `runbook-${latest.proposal_id}`, POPUP_FEATURES)
    setLaunched(true)
    onDismiss?.()
  }

  if (launched) return null

  return (
    <div style={{
      marginTop: 10,
      padding: '8px 10px',
      background: 'rgba(0,200,238,0.06)',
      border: '1px solid rgba(0,200,238,0.25)',
      borderLeft: '3px solid var(--cyan, #00c8ee)',
      borderRadius: 2,
      fontFamily: 'var(--font-mono, monospace)',
    }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <span style={{ fontSize: 9, color: 'var(--cyan, #00c8ee)', letterSpacing: 1 }}>
          ⬡ SUB-TASK READY
        </span>
        <span style={{
          fontSize: 8, padding: '1px 5px', borderRadius: 2,
          background: `${confColor}22`, color: confColor,
          border: `1px solid ${confColor}44`,
        }}>
          {latest.confidence}
        </span>
        {extra > 0 && (
          <span style={{ fontSize: 9, color: 'var(--cyan, #00c8ee)' }}>+{extra} more</span>
        )}
      </div>

      {/* Task */}
      <div style={{ fontSize: 11, color: '#e2e8f0', marginBottom: 6, lineHeight: 1.5 }}>
        {latest.task}
      </div>

      {/* Steps summary */}
      {(latest.executable_steps?.length > 0 || latest.manual_steps?.length > 0) && (
        <div style={{ fontSize: 9, color: '#64748b', marginBottom: 8 }}>
          {latest.executable_steps?.length > 0 && (
            <span style={{ marginRight: 10 }}>
              ⚡ {latest.executable_steps.length} auto step{latest.executable_steps.length !== 1 ? 's' : ''}
            </span>
          )}
          {latest.manual_steps?.length > 0 && (
            <span>📋 {latest.manual_steps.length} manual step{latest.manual_steps.length !== 1 ? 's' : ''}</span>
          )}
        </div>
      )}

      {/* Action buttons */}
      <div style={{ display: 'flex', gap: 8 }}>
        <button
          onClick={runSubAgent}
          style={{
            padding: '3px 12px', fontSize: 10, fontFamily: 'inherit',
            background: 'rgba(0,200,238,0.15)', color: 'var(--cyan, #00c8ee)',
            border: '1px solid var(--cyan, #00c8ee)', borderRadius: 2, cursor: 'pointer',
          }}
        >
          ▶ Run Sub-agent
        </button>
        <button
          onClick={openRunbook}
          style={{
            padding: '3px 12px', fontSize: 10, fontFamily: 'inherit',
            background: 'transparent', color: '#94a3b8',
            border: '1px solid #334155', borderRadius: 2, cursor: 'pointer',
          }}
        >
          ✎ Manual Runbook
        </button>
        <button
          onClick={() => onDismiss?.()}
          style={{
            padding: '3px 8px', fontSize: 10, fontFamily: 'inherit',
            background: 'transparent', color: '#475569',
            border: '1px solid #1e293b', borderRadius: 2, cursor: 'pointer',
          }}
        >
          ×
        </button>
      </div>
    </div>
  )
}
```

---

## Change 3 — gui/src/components/AgentFeed.jsx

### 3a. Import SubtaskOfferCard at the top:
```jsx
import SubtaskOfferCard from './SubtaskOfferCard'
```

### 3b. Add state to track dismissed offers:
Inside the `AgentFeed` component function, after the existing `const [visible, setVisible] = useState(false)`:
```jsx
  const [dismissedOffers, setDismissedOffers] = useState(new Set())
```

### 3c. Add a render case for `subtask_offer` in the `feedLines.map`:
Find the `if (item.type === 'done')` block and add AFTER it (before the final `return null`):
```jsx
        if (item.type === 'subtask_offer') {
          if (dismissedOffers.has(i)) return null
          return (
            <SubtaskOfferCard
              key={i}
              proposals={item.proposals}
              onDismiss={() => setDismissedOffers(prev => new Set([...prev, i]))}
            />
          )
        }
```

---

## Change 4 — gui/src/components/OutputPanel.jsx

### 4a. Import SubtaskOfferCard:
```jsx
import SubtaskOfferCard from './SubtaskOfferCard'
```

### 4b. Get `pendingProposals` from context. In the destructure at the top of the component:
Find:
```jsx
  const { outputLines, runState, wsState, clearOutput, pendingChoices, clearChoices, agentType, lastAgentType, stopAgent } = useAgentOutput()
```
Replace with:
```jsx
  const { outputLines, runState, wsState, clearOutput, pendingChoices, clearChoices, agentType, lastAgentType, stopAgent, pendingProposals } = useAgentOutput()
```

### 4c. Add offer inline before the "View full log" button. Find:
```jsx
        {runState !== 'running' && outputLines.some(m => m.type === 'done' || m.type === 'error') && (
          <button
            onClick={() => onTab && onTab('Logs')}
```
Add BEFORE that block:
```jsx
        {runState !== 'running' && pendingProposals?.length > 0 && (
          <SubtaskOfferCard proposals={pendingProposals} />
        )}
```

---

## Change 5 — gui/src/App.jsx

### 5a. Remove the SubtaskOfferBanner import. Find:
```jsx
import SubtaskOfferBanner from './components/SubtaskOfferBanner'
```
Delete that line.

### 5b. Remove the `<SubtaskOfferBanner />` usage. Find:
```jsx
      <EscalationBanner />
      <SubtaskOfferBanner />
```
Replace with:
```jsx
      <EscalationBanner />
```

---

## Version bump
Update VERSION file: v2.24.3 → v2.24.4

## Commit
```
git add -A
git commit -m "feat(ux): inline sub-task offer in AgentFeed/OutputPanel; remove dashboard banner (v2.24.4)"
git push origin main
```
