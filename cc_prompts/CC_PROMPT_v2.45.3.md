# CC PROMPT — v2.45.3 — feat(ui): SuitesTab last-run duration + score badge per suite

## What this does

In the Suites tab, each suite card shows a second info row. Currently it shows
description, categories, test count, and memory config. This prompt adds last-run
stats: duration (e.g. "8m 32s"), score (e.g. "72.4%"), and time-ago ("3h ago"),
so users can plan when to schedule suites (overnight, weekend, etc.).

Data source: `GET /api/tests/runs?limit=200` already returns `started_at`,
`finished_at`, `suite_id`, `score_pct`, `passed`, `total`, `status`. No backend
changes needed.

Version bump: 2.45.2 → 2.45.3.

---

## Change — `gui/src/components/TestsPanel.jsx` — SuitesTab only

### 1. Add a `durStr` helper near the top of the file (alongside `ago`):

```js
function durStr(startedAt, finishedAt) {
  if (!startedAt || !finishedAt) return null
  const s = Math.round((new Date(finishedAt) - new Date(startedAt)) / 1000)
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s/60)}m ${s%60}s`
  return `${Math.floor(s/3600)}h ${Math.floor((s%3600)/60)}m`
}
```

### 2. Update `SuitesTab` — add `lastRun` state, fetch runs in `load()`, show stats

Replace the entire `function SuitesTab({ onRun })` with:

```jsx
function SuitesTab({ onRun }) {
  const [suites, setSuites]   = useState([])
  const [cases, setCases]     = useState([])
  const [lastRun, setLastRun] = useState({})   // suite_id → {score, passed, total, dur, ago}
  const [editing, setEditing] = useState(null)
  const [running, setRunning] = useState({})
  const [msg, setMsg]         = useState({})

  const load = useCallback(() => {
    api('/api/tests/suites').then(r => r.json()).then(d => setSuites(d.suites || [])).catch(() => {})
    api('/api/tests/cases').then(r => r.json()).then(d => setCases(d.cases || [])).catch(() => {})
    // Fetch recent runs and build per-suite last-run map
    api('/api/tests/runs?limit=200').then(r => r.json()).then(d => {
      const map = {}
      for (const run of (d.runs || [])) {
        if (!run.suite_id || run.status !== 'completed') continue
        if (!map[run.suite_id]) {
          map[run.suite_id] = {
            score:   run.score_pct,
            passed:  run.passed,
            total:   run.total,
            dur:     durStr(run.started_at, run.finished_at),
            agoStr:  ago(run.started_at),
          }
        }
      }
      setLastRun(map)
    }).catch(() => {})
  }, [])

  useEffect(() => { load() }, [load])

  const save = async (suite) => {
    await api('/api/tests/suites', {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify(suite),
    })
    setEditing(null); load()
  }

  const del = async (id) => {
    if (!confirm('Delete suite?')) return
    await api(`/api/tests/suites/${id}`, { method: 'DELETE' })
    load()
  }

  const runSuite = async (suite) => {
    setRunning(r => ({...r, [suite.id]: true})); setMsg(m => ({...m, [suite.id]: ''}))
    try {
      const body = { suite_id: suite.id, test_ids: suite.test_ids || [], categories: suite.categories || [], ...suite.config }
      const r = await api('/api/tests/run', {
        method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const d = await r.json()
      setMsg(m => ({...m, [suite.id]: d.message || 'started'}))
      onRun?.()
    } catch (e) { setMsg(m => ({...m, [suite.id]: 'error'})) }
    finally { setRunning(r => ({...r, [suite.id]: false})) }
  }

  const cats = [...new Set(cases.map(c => c.category))].sort()

  if (editing !== null) {
    return <SuiteEditor suite={editing} cases={cases} cats={cats} onSave={save} onCancel={() => setEditing(null)} />
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, height: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
        <Label>SUITES</Label>
        <Btn onClick={() => setEditing({})} accent>+ new suite</Btn>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 6 }}>
        {suites.length === 0 && <Mono style={{ color: 'var(--text-3)' }}>No suites yet. Create one to group tests.</Mono>}
        {suites.map(s => {
          const lr = lastRun[s.id]
          const scoreCol = lr ? (lr.score >= 90 ? 'var(--green)' : lr.score >= 70 ? 'var(--amber)' : 'var(--red)') : 'var(--text-3)'
          return (
            <div key={s.id} style={{ border: '1px solid var(--border)', background: 'var(--bg-2)', borderRadius: 2, padding: '8px 12px' }}>
              {/* Top row: name + actions */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Mono style={{ color: 'var(--text-1)', fontSize: 11, flex: 1 }}>{s.name}</Mono>
                {msg[s.id] && <Mono style={{ color: 'var(--green)' }}>{msg[s.id]}</Mono>}
                <Btn onClick={() => setEditing(s)}>edit</Btn>
                <Btn onClick={() => del(s.id)}>delete</Btn>
                <Btn onClick={() => runSuite(s)} accent disabled={!!running[s.id]}>
                  {running[s.id] ? '…' : '▶ run'}
                </Btn>
              </div>

              {/* Info row: config tags + last run stats */}
              <div style={{ marginTop: 5, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                {s.description && <Mono style={{ color: 'var(--text-3)' }}>{s.description}</Mono>}
                {s.categories?.length > 0 && <Mono style={{ color: 'var(--cyan)' }}>cats: {s.categories.join(', ')}</Mono>}
                {s.test_ids?.length > 0 && <Mono style={{ color: 'var(--text-2)' }}>{s.test_ids.length} tests</Mono>}
                {s.config?.memoryEnabled === false && <Mono style={{ color: 'var(--amber)' }}>mem off</Mono>}
                {s.config?.memoryBackend === 'postgres' && <Mono style={{ color: 'var(--text-3)' }}>pg-mem</Mono>}

                {/* Divider + last run */}
                {lr ? (
                  <>
                    <span style={{ color: 'var(--border)', fontFamily: 'var(--font-mono)', fontSize: 9 }}>·</span>
                    <Mono style={{ color: 'var(--text-3)' }}>last:</Mono>
                    {lr.dur && (
                      <span style={{
                        fontFamily: 'var(--font-mono)', fontSize: 9,
                        color: 'var(--text-2)',
                        background: 'var(--bg-3)',
                        padding: '1px 6px', borderRadius: 2,
                        border: '1px solid var(--border)',
                      }}>⏱ {lr.dur}</span>
                    )}
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: 9,
                      color: scoreCol,
                      background: 'var(--bg-3)',
                      padding: '1px 6px', borderRadius: 2,
                      border: `1px solid ${scoreCol}44`,
                    }}>{lr.score?.toFixed(1)}% ({lr.passed}/{lr.total})</span>
                    <Mono style={{ color: 'var(--text-3)' }}>{lr.agoStr}</Mono>
                  </>
                ) : (
                  <>
                    <span style={{ color: 'var(--border)', fontFamily: 'var(--font-mono)', fontSize: 9 }}>·</span>
                    <Mono style={{ color: 'var(--text-3)' }}>no runs yet</Mono>
                  </>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
```

---

## Version bump

Update `VERSION`: `2.45.2` → `2.45.3`

---

## Commit

```
git add -A
git commit -m "feat(ui): v2.45.3 SuitesTab last-run duration + score badge per suite"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
