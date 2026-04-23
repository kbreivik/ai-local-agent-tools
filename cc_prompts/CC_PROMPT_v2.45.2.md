# CC PROMPT — v2.45.2 — feat(ui): TestsPanel auto-refresh — poll running state, live indicator, manual refresh button

## What this does

Results tab never auto-updates — user must navigate away and back to see new
runs. Fix: root component polls `/api/tests/running` every 5s. While running,
bumps `refresh` every 5s so Results re-fetches. Shows a pulsing amber dot in
the tab bar when a run is active. Results tab gets a manual ⟳ refresh button.
Trend & Schedule also refreshes on completion.

Version bump: 2.45.1 → 2.45.2.

---

## Change — `gui/src/components/TestsPanel.jsx`

### 1. Root component — add polling

Replace the root `TestsPanel` export:

```jsx
export default function TestsPanel() {
  const [tab, setTab]         = useState('Library')
  const [refresh, setRefresh] = useState(0)
  const [isRunning, setIsRunning] = useState(false)
  const pollRef = useRef(null)

  const bump = () => setRefresh(r => r + 1)

  // Poll running state every 5s; bump refresh while active
  useEffect(() => {
    let wasRunning = false
    const tick = () => {
      api('/api/tests/running').then(r => r.json()).then(d => {
        const running = !!d.running
        setIsRunning(running)
        if (running) {
          bump()
        } else if (wasRunning) {
          // Final bump on completion
          bump()
        }
        wasRunning = running
      }).catch(() => {})
    }
    tick() // immediate first check
    pollRef.current = setInterval(tick, 5000)
    return () => clearInterval(pollRef.current)
  }, [])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-0)' }}>
      {/* Tab bar */}
      <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', background: 'var(--bg-1)', flexShrink: 0, alignItems: 'center' }}>
        {TABS.map(t => (
          <button key={t} onClick={() => setTab(t)} style={{
            fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.1em', textTransform: 'uppercase',
            padding: '8px 14px', background: 'none', border: 'none',
            borderBottom: `2px solid ${tab === t ? 'var(--accent)' : 'transparent'}`,
            color: tab === t ? 'var(--accent)' : 'var(--text-3)', cursor: 'pointer',
          }}>{t}</button>
        ))}
        {/* Running indicator */}
        {isRunning && (
          <div style={{ marginLeft: 'auto', marginRight: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{
              width: 6, height: 6, borderRadius: '50%', background: 'var(--amber)',
              animation: 'pulse 1s ease-in-out infinite',
            }} />
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--amber)', letterSpacing: '0.1em' }}>RUNNING</span>
          </div>
        )}
      </div>

      {/* Tab content */}
      <div style={{ flex: 1, padding: 16, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {tab === 'Library'          && <LibraryTab onRunSelected={bump} />}
        {tab === 'Suites'           && <SuitesTab onRun={bump} />}
        {tab === 'Results'          && <ResultsTab refresh={refresh} isRunning={isRunning} onRefresh={bump} />}
        {tab === 'Compare'          && <CompareTab />}
        {tab === 'Trend & Schedule' && <TrendTab refresh={refresh} />}
      </div>
    </div>
  )
}
```

Also add the CSS pulse keyframe — inject it once near the top of the component
file (before any function definitions), after the imports:

```jsx
// Inject pulse keyframe once
if (typeof document !== 'undefined' && !document.getElementById('tp-pulse')) {
  const s = document.createElement('style')
  s.id = 'tp-pulse'
  s.textContent = '@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }'
  document.head.appendChild(s)
}
```

### 2. ResultsTab — add refresh button + isRunning prop

Replace `function ResultsTab({ refresh })` signature and add a refresh button:

```jsx
function ResultsTab({ refresh, isRunning, onRefresh }) {
  const [runs, setRuns]         = useState([])
  const [expanded, setExpanded] = useState(null)
  const [detail, setDetail]     = useState(null)
  const [loading, setLoading]   = useState(true)

  const load = useCallback(() => {
    api('/api/tests/runs').then(r => r.json())
      .then(d => { setRuns(d.runs || []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load, refresh])

  const expand = async (run) => {
    if (expanded === run.id) { setExpanded(null); setDetail(null); return }
    setExpanded(run.id)
    const d = await api(`/api/tests/runs/${run.id}`).then(r => r.json())
    setDetail(d)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, height: '100%' }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
        {isRunning && (
          <Mono c="amber">⟳ run in progress — auto-refreshing every 5s</Mono>
        )}
        <div style={{ marginLeft: 'auto' }}>
          <Btn small onClick={() => { load(); onRefresh?.() }}>⟳ refresh</Btn>
        </div>
      </div>

      {/* Run list */}
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 6 }}>
        {loading && <Mono style={{ color: 'var(--text-3)' }}>Loading runs…</Mono>}
        {!loading && runs.length === 0 && <Mono style={{ color: 'var(--text-3)' }}>No runs yet. Trigger a run from Library or Suites tab.</Mono>}
        {runs.map(run => (
          <div key={run.id} style={{ border: '1px solid var(--border)', background: 'var(--bg-2)', borderRadius: 2, overflow: 'hidden' }}>
            <div onClick={() => expand(run)} style={{ display: 'flex', gap: 10, padding: '7px 12px', cursor: 'pointer', alignItems: 'center' }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-3)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
              <span style={{ color: run.status === 'completed' ? 'var(--green)' : run.status === 'error' ? 'var(--red)' : 'var(--amber)', fontSize: 10 }}>
                {run.status === 'completed' ? '✓' : run.status === 'error' ? '✗' : '…'}
              </span>
              <Mono style={{ color: 'var(--text-3)', width: 80 }}>{ago(run.started_at)}</Mono>
              <Mono style={{ color: 'var(--text-1)', flex: 1 }}>{run.suite_name || 'ad-hoc'}</Mono>
              <Mono style={{ color: scoreColor(run.score_pct) }}>{run.score_pct?.toFixed(1)}%</Mono>
              <Mono style={{ color: 'var(--text-2)' }}>{run.passed}/{run.total}</Mono>
              <Mono style={{ color: 'var(--text-3)', fontSize: 8 }}>{run.id?.slice(0,8)}</Mono>
              <span style={{ color: 'var(--text-3)', fontSize: 10 }}>{expanded === run.id ? '▲' : '▼'}</span>
            </div>
            {expanded === run.id && detail && (
              <div style={{ borderTop: '1px solid var(--border)', padding: '8px 12px' }}>
                {(detail.results || []).map(r => (
                  <div key={r.test_id} style={{ display: 'flex', gap: 8, padding: '2px 0', borderBottom: '1px solid var(--bg-3)', alignItems: 'center' }}>
                    <span style={{ color: passColor(r.passed), fontSize: 9, width: 12, flexShrink: 0 }}>{r.passed ? '✓' : r.soft ? '⚠' : '✗'}</span>
                    <Mono style={{ color: 'var(--text-3)', width: 160, flexShrink: 0 }}>{r.test_id}</Mono>
                    <span style={catStyle(r.category)}>{r.category}</span>
                    <Mono style={{ color: 'var(--text-2)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.task}</Mono>
                    <Mono style={{ color: 'var(--text-3)' }}>{r.step_count}s</Mono>
                    <Mono style={{ color: 'var(--text-3)' }}>{r.duration_s?.toFixed(1)}s</Mono>
                    {r.failures?.length > 0 && <Mono style={{ color: 'var(--red)' }}>{r.failures[0]?.slice(0,40)}</Mono>}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
```

### 3. TrendTab — accept refresh prop

Replace `function TrendTab()` with `function TrendTab({ refresh })` and add
`refresh` to the existing useEffect dependency:

```jsx
function TrendTab({ refresh }) {
  ...
  useEffect(() => { load() }, [load, refresh])
  ...
}
```

CC: Only the signature and the useEffect need to change in TrendTab — leave
all other TrendTab logic intact.

---

## Version bump

Update `VERSION`: `2.45.1` → `2.45.2`

---

## Commit

```
git add -A
git commit -m "feat(ui): v2.45.2 TestsPanel auto-refresh — poll running state, live amber indicator, manual refresh"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
