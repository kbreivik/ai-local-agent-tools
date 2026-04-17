# CC PROMPT — v2.33.15 — feat(ui): live agent diagnostics overlay

## What this does
When running an investigate task, surface the harness's internal state
(tool budget used, DIAGNOSIS emitted Y/N, contradictions flagged, zero-result
streaks) as a compact live overlay in OutputPanel. Operators can see the
agent struggling BEFORE it exhausts budget and draws a bad conclusion.

Depends on v2.33.3 (budget nudge events), v2.33.12 (zero_result_pivot event),
v2.33.13 (contradiction_detected event).

Version bump: 2.33.14 → 2.33.15

## Change 1 — api/routers/agent.py — emit periodic diagnostics

In the agent loop, after each tool call resolves, broadcast a compact
state snapshot via WebSocket:

```python
# After each tool call processing block, emit diagnostics
budget = _MAX_TOOL_CALLS_BY_TYPE.get(agent_type, 16)
has_diagnosis = "DIAGNOSIS:" in "\n".join(step_outputs) if agent_type == "investigate" else True

await ws.send_json({
    "event": "agent_diagnostics",
    "tools_used": tools_used,
    "budget": budget,
    "budget_pct": int((tools_used / max(budget, 1)) * 100),
    "has_diagnosis": has_diagnosis,
    "zero_streaks": {k: v for k, v in _zero_streaks.items() if v > 0},
    "max_nonzero_by_tool": _nonzero_seen,
    "pivot_nudges_fired": list(_zero_pivot_fired),
    "subtask_proposed": subtask_proposed,
    "agent_type": agent_type,
})
```

If `_zero_streaks` / `_nonzero_seen` / `_zero_pivot_fired` are scoped inside
the loop (from v2.33.12), they're already accessible here.

## Change 2 — gui/src/components/AgentDiagnostics.jsx — new component

```jsx
import React from 'react';

/**
 * Compact live diagnostics overlay for agent runs.
 * Renders inline at the top of OutputPanel whenever an agent task is active.
 */
export default function AgentDiagnostics({ diag }) {
  if (!diag || diag.agent_type !== 'investigate') return null;

  const pct = diag.budget_pct ?? 0;
  const barColor = pct >= 80 ? 'var(--red)'
                  : pct >= 60 ? 'var(--amber)'
                  : 'var(--cyan)';

  const diagOk = diag.has_diagnosis;
  const zeroAlerts = Object.entries(diag.zero_streaks || {}).filter(([, n]) => n >= 2);

  return (
    <div className="mono" style={{
      display: 'flex', alignItems: 'center', gap: 12,
      padding: '6px 10px', marginBottom: 6,
      background: 'var(--bg-1)',
      border: '1px solid var(--border)',
      borderLeft: `3px solid ${barColor}`,
      borderRadius: 2, fontSize: 10,
      letterSpacing: '0.08em',
    }}>
      {/* Budget */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 90 }}>
        <span style={{ color: 'var(--text-2)', fontSize: 9 }}>BUDGET</span>
        <div>
          <span style={{ color: 'var(--text-0)' }}>{diag.tools_used}</span>
          <span style={{ color: 'var(--text-3)' }}> / {diag.budget}</span>
        </div>
        <div style={{ height: 2, background: 'var(--bg-3)', borderRadius: 1, overflow: 'hidden', width: 80 }}>
          <div style={{
            height: '100%', width: `${Math.min(100, pct)}%`,
            background: barColor, transition: 'width 0.3s',
          }} />
        </div>
      </div>

      {/* DIAGNOSIS status */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <span style={{ color: 'var(--text-2)', fontSize: 9 }}>DIAGNOSIS</span>
        <span style={{ color: diagOk ? 'var(--green)' : 'var(--text-3)' }}>
          {diagOk ? '✓ emitted' : '· not yet'}
        </span>
      </div>

      {/* Zero-result streaks */}
      {zeroAlerts.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={{ color: 'var(--text-2)', fontSize: 9 }}>ZERO-STREAKS</span>
          <div style={{ display: 'flex', gap: 4 }}>
            {zeroAlerts.map(([tool, n]) => (
              <span key={tool} title={`${tool}: ${n} consecutive zero results`}
                style={{
                  color: n >= 3 ? 'var(--red)' : 'var(--amber)',
                  padding: '0 4px',
                  border: `1px solid ${n >= 3 ? 'var(--red)' : 'var(--amber)'}`,
                  borderRadius: 1, fontSize: 9,
                }}>
                {tool.replace('elastic_', 'e_').replace('_logs', '')}×{n}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Pivot nudges fired */}
      {(diag.pivot_nudges_fired || []).length > 0 && (
        <div style={{ color: 'var(--amber)', fontSize: 9 }}>
          ⚠ {diag.pivot_nudges_fired.length} pivot nudge{diag.pivot_nudges_fired.length > 1 ? 's' : ''}
        </div>
      )}

      {/* Subtask proposed */}
      {diag.subtask_proposed && (
        <div style={{ color: 'var(--accent-hi)', fontSize: 9 }}>
          ◈ SUBTASK PROPOSED
        </div>
      )}

      <div style={{ flex: 1 }} />

      {/* Type indicator */}
      <div style={{ color: 'var(--text-3)', fontSize: 9 }}>
        {diag.agent_type?.toUpperCase()}
      </div>
    </div>
  );
}
```

## Change 3 — gui/src/components/OutputPanel.jsx — wire it in

Import the new component and add state:

```jsx
import AgentDiagnostics from './AgentDiagnostics';

// ...inside OutputPanel component...
const [agentDiag, setAgentDiag] = useState(null);

// In the WebSocket message handler, add a case:
if (evt.event === 'agent_diagnostics') {
  setAgentDiag(evt);
}

// Reset on new task start
if (evt.event === 'task_started') {
  setAgentDiag(null);
}
```

Render the component above the stream log:

```jsx
<AgentDiagnostics diag={agentDiag} />
{/* existing stream log content */}
```

## Change 4 — tests

Unit test for the React component (if testing library present):

```jsx
// tests/AgentDiagnostics.test.jsx
import { render, screen } from '@testing-library/react';
import AgentDiagnostics from '../src/components/AgentDiagnostics';

test('renders budget when agent_type is investigate', () => {
  render(<AgentDiagnostics diag={{
    agent_type: 'investigate',
    tools_used: 5, budget: 16, budget_pct: 31,
    has_diagnosis: false,
    zero_streaks: {}, pivot_nudges_fired: [],
  }} />);
  expect(screen.getByText(/5/)).toBeInTheDocument();
  expect(screen.getByText(/16/)).toBeInTheDocument();
  expect(screen.getByText(/not yet/i)).toBeInTheDocument();
});

test('renders nothing for observe agent', () => {
  const { container } = render(<AgentDiagnostics diag={{
    agent_type: 'observe',
    tools_used: 3, budget: 8,
  }} />);
  expect(container.firstChild).toBeNull();
});

test('shows zero-streak badge when tool hits 3+ zeros', () => {
  render(<AgentDiagnostics diag={{
    agent_type: 'investigate',
    tools_used: 7, budget: 16,
    has_diagnosis: false,
    zero_streaks: { elastic_search_logs: 4 },
    pivot_nudges_fired: [],
  }} />);
  expect(screen.getByText(/×4/)).toBeInTheDocument();
});
```

## Version bump
Update `VERSION`: 2.33.14 → 2.33.15

## Commit
```
git add -A
git commit -m "feat(ui): v2.33.15 live agent diagnostics overlay — budget, DIAGNOSIS, zero-streaks"
git push origin main
```

## How to test after push
1. Redeploy.
2. Run any investigate task (e.g. the elastic-search trace).
3. Observe the compact diagnostics bar appearing at the top of OutputPanel:
   - Budget counter + progress bar filling up
   - DIAGNOSIS toggle flipping from "· not yet" → "✓ emitted" when the agent writes DIAGNOSIS:
   - Zero-streak badges appearing as consecutive zero results accumulate
   - Pivot-nudge counter incrementing when v2.33.12 nudges fire
   - SUBTASK PROPOSED indicator when v2.33.3 path triggers
4. Run an observe task — expect no diagnostics bar (observe is not the target agent type).
5. Resize the panel — the bar should flex gracefully.
