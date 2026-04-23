/**
 * TestsPanel — TOOLS → Tests
 * 5-tab test harness: Library | Suites | Results | Compare | Trend & Schedule
 * v2.44.2
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''
const api = (path, opts = {}) =>
  fetch(`${BASE}${path}`, { headers: authHeaders(), credentials: 'include', ...opts })

// ── colour helpers ────────────────────────────────────────────────────────────
const CAT_COLOR = {
  status:        { bg: 'rgba(0,100,200,0.15)',  fg: '#4da6ff' },
  research:      { bg: 'rgba(136,68,204,0.15)', fg: '#b07fff' },
  clarification: { bg: 'rgba(204,136,0,0.15)',  fg: '#ffcc44' },
  action:        { bg: 'rgba(200,80,0,0.15)',   fg: '#ff8844' },
  safety:        { bg: 'rgba(200,0,0,0.18)',    fg: '#ff6666' },
  orchestration: { bg: 'rgba(0,180,120,0.15)', fg: '#44ffaa' },
}
const catStyle = (cat) => ({
  background: CAT_COLOR[cat]?.bg ?? 'rgba(255,255,255,0.05)',
  color: CAT_COLOR[cat]?.fg ?? 'var(--text-3)',
  fontFamily: 'var(--font-mono)', fontSize: 8,
  padding: '1px 5px', borderRadius: 2, whiteSpace: 'nowrap',
})
const passColor = (p) => p ? 'var(--green)' : 'var(--red)'
const scoreColor = (s) => s >= 90 ? 'var(--green)' : s >= 70 ? 'var(--amber)' : 'var(--red)'

function Mono({ children, style }) {
  return <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, ...style }}>{children}</span>
}
function Label({ children }) {
  return <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)', letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: 8 }}>{children}</div>
}
function Btn({ onClick, children, accent, disabled, style }) {
  return (
    <button onClick={onClick} disabled={disabled} style={{
      fontFamily: 'var(--font-mono)', fontSize: 9, padding: '3px 9px',
      background: accent ? 'var(--accent-dim)' : 'transparent',
      border: `1px solid ${accent ? 'rgba(160,24,40,0.4)' : 'var(--border)'}`,
      color: accent ? 'var(--accent)' : disabled ? 'var(--text-3)' : 'var(--text-2)',
      borderRadius: 2, cursor: disabled ? 'not-allowed' : 'pointer', ...style,
    }}>{children}</button>
  )
}

function ago(iso) {
  if (!iso) return '—'
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return `${Math.round(s / 86400)}d ago`
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 1: LIBRARY
// ══════════════════════════════════════════════════════════════════════════════
function LibraryTab({ onRunSelected }) {
  const [cases, setCases]         = useState([])
  const [selected, setSelected]   = useState(new Set())
  const [filter, setFilter]       = useState({ cat: '', keyword: '', critical: false, soft: false })
  const [running, setRunning]     = useState(false)
  const [runMsg, setRunMsg]       = useState('')

  useEffect(() => {
    api('/api/tests/cases').then(r => r.json())
      .then(d => setCases(d.cases || []))
      .catch(() => {})
  }, [])

  const cats = [...new Set(cases.map(c => c.category))].sort()
  const filtered = cases.filter(c => {
    if (filter.cat && c.category !== filter.cat) return false
    if (filter.keyword && !c.task.toLowerCase().includes(filter.keyword.toLowerCase()) && !c.id.toLowerCase().includes(filter.keyword.toLowerCase())) return false
    if (filter.critical && !c.critical) return false
    if (filter.soft && !c.soft) return false
    return true
  })

  const toggleAll = () => {
    if (selected.size === filtered.length) setSelected(new Set())
    else setSelected(new Set(filtered.map(c => c.id)))
  }

  const runSelected = async (memEnabled = true) => {
    if (selected.size === 0) return
    setRunning(true); setRunMsg('')
    try {
      const ids = [...selected]
      const r = await api('/api/tests/run', {
        method: 'POST',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ test_ids: ids, memory_enabled: memEnabled }),
      })
      const d = await r.json()
      setRunMsg(d.message || `Run started`)
      onRunSelected?.()
    } catch (e) { setRunMsg('Error: ' + e.message) }
    finally { setRunning(false) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 10 }}>
      {/* Filter bar */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', flexShrink: 0 }}>
        <input value={filter.keyword} onChange={e => setFilter(f => ({...f, keyword: e.target.value}))}
          placeholder="search tasks or IDs…"
          style={{ fontFamily: 'var(--font-mono)', fontSize: 9, padding: '4px 8px', background: 'var(--bg-1)', border: '1px solid var(--border)', color: 'var(--text-1)', borderRadius: 2, width: 180 }} />
        <select value={filter.cat} onChange={e => setFilter(f => ({...f, cat: e.target.value}))}
          style={{ fontFamily: 'var(--font-mono)', fontSize: 9, padding: '4px 8px', background: 'var(--bg-1)', border: '1px solid var(--border)', color: 'var(--text-2)', borderRadius: 2 }}>
          <option value="">all categories</option>
          {cats.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <label style={{ display: 'flex', gap: 4, alignItems: 'center', fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-2)', cursor: 'pointer' }}>
          <input type="checkbox" checked={filter.critical} onChange={e => setFilter(f => ({...f, critical: e.target.checked}))} /> critical only
        </label>
        <label style={{ display: 'flex', gap: 4, alignItems: 'center', fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-2)', cursor: 'pointer' }}>
          <input type="checkbox" checked={filter.soft} onChange={e => setFilter(f => ({...f, soft: e.target.checked}))} /> soft only
        </label>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
          {runMsg && <Mono style={{ color: running ? 'var(--amber)' : 'var(--green)' }}>{runMsg}</Mono>}
          <Btn onClick={toggleAll}>{selected.size === filtered.length ? 'deselect all' : `select all (${filtered.length})`}</Btn>
          <Btn onClick={() => runSelected(true)} disabled={selected.size === 0 || running} accent>
            ▶ run {selected.size > 0 ? selected.size : ''} (mem on)
          </Btn>
          <Btn onClick={() => runSelected(false)} disabled={selected.size === 0 || running}>
            ▶ run (mem off)
          </Btn>
        </div>
      </div>

      {/* Case list */}
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 2 }}>
        {filtered.length === 0 && <Mono style={{ color: 'var(--text-3)', padding: 8 }}>No tests match filter.</Mono>}
        {filtered.map(c => (
          <div key={c.id} onClick={() => setSelected(s => { const n = new Set(s); n.has(c.id) ? n.delete(c.id) : n.add(c.id); return n })}
            style={{
              display: 'flex', alignItems: 'center', gap: 8, padding: '5px 8px',
              background: selected.has(c.id) ? 'rgba(160,24,40,0.10)' : 'var(--bg-2)',
              border: `1px solid ${selected.has(c.id) ? 'rgba(160,24,40,0.35)' : 'var(--border)'}`,
              borderRadius: 2, cursor: 'pointer',
            }}>
            <input type="checkbox" checked={selected.has(c.id)} readOnly style={{ flexShrink: 0 }} />
            <Mono style={{ color: 'var(--text-3)', width: 160, flexShrink: 0 }}>{c.id}</Mono>
            <span style={catStyle(c.category)}>{c.category}</span>
            {c.critical && <span style={{ ...catStyle('safety'), background: 'rgba(200,0,0,0.2)' }}>CRITICAL</span>}
            {c.soft && <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--amber)', padding: '1px 4px', border: '1px solid rgba(204,136,0,0.3)', borderRadius: 2 }}>soft</span>}
            <Mono style={{ color: 'var(--text-2)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.task}</Mono>
            <Mono style={{ color: 'var(--text-3)', flexShrink: 0 }}>{c.timeout_s || 40}s</Mono>
          </div>
        ))}
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 2: SUITES
// ══════════════════════════════════════════════════════════════════════════════
function SuitesTab({ onRun }) {
  const [suites, setSuites]   = useState([])
  const [cases, setCases]     = useState([])
  const [editing, setEditing] = useState(null)  // null | {} | {id,...}
  const [running, setRunning] = useState({})
  const [msg, setMsg]         = useState({})

  const load = useCallback(() => {
    api('/api/tests/suites').then(r => r.json()).then(d => setSuites(d.suites || [])).catch(() => {})
    api('/api/tests/cases').then(r => r.json()).then(d => setCases(d.cases || [])).catch(() => {})
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
        {suites.map(s => (
          <div key={s.id} style={{ border: '1px solid var(--border)', background: 'var(--bg-2)', borderRadius: 2, padding: '8px 12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Mono style={{ color: 'var(--text-1)', fontSize: 11, flex: 1 }}>{s.name}</Mono>
              {msg[s.id] && <Mono style={{ color: 'var(--green)' }}>{msg[s.id]}</Mono>}
              <Btn onClick={() => setEditing(s)}>edit</Btn>
              <Btn onClick={() => del(s.id)}>delete</Btn>
              <Btn onClick={() => runSuite(s)} accent disabled={!!running[s.id]}>
                {running[s.id] ? '…' : '▶ run'}
              </Btn>
            </div>
            <div style={{ marginTop: 4, display: 'flex', gap: 8 }}>
              {s.description && <Mono style={{ color: 'var(--text-3)' }}>{s.description}</Mono>}
              {s.categories?.length > 0 && <Mono style={{ color: 'var(--cyan)' }}>cats: {s.categories.join(', ')}</Mono>}
              {s.test_ids?.length > 0 && <Mono style={{ color: 'var(--text-2)' }}>{s.test_ids.length} tests</Mono>}
              {s.config?.memoryEnabled === false && <Mono style={{ color: 'var(--amber)' }}>mem off</Mono>}
              {s.config?.memoryBackend === 'postgres' && <Mono style={{ color: 'var(--purple)' }}>pg-mem</Mono>}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function SuiteEditor({ suite, cases, cats, onSave, onCancel }) {
  const [name, setName]             = useState(suite.name || '')
  const [desc, setDesc]             = useState(suite.description || '')
  const [selCats, setSelCats]       = useState(new Set(suite.categories || []))
  const [selTests, setSelTests]     = useState(new Set(suite.test_ids || []))
  const [memEnabled, setMemEnabled] = useState(suite.config?.memoryEnabled !== false)
  const [memBackend, setMemBackend] = useState(suite.config?.memoryBackend || 'muninndb')

  const toggleCat = (c) => setSelCats(s => { const n = new Set(s); n.has(c) ? n.delete(c) : n.add(c); return n })
  const toggleTest = (id) => setSelTests(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })

  const save = () => onSave({
    id: suite.id, name, description: desc,
    categories: [...selCats], test_ids: [...selTests],
    config: { memoryEnabled: memEnabled, memoryBackend: memBackend },
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, height: '100%', overflowY: 'auto' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input value={name} onChange={e => setName(e.target.value)} placeholder="Suite name"
          style={{ fontFamily: 'var(--font-mono)', fontSize: 10, padding: '4px 8px', background: 'var(--bg-1)', border: '1px solid var(--border)', color: 'var(--text-1)', borderRadius: 2, flex: 1 }} />
        <Btn onClick={save} accent disabled={!name}>save</Btn>
        <Btn onClick={onCancel}>cancel</Btn>
      </div>
      <input value={desc} onChange={e => setDesc(e.target.value)} placeholder="Description (optional)"
        style={{ fontFamily: 'var(--font-mono)', fontSize: 9, padding: '4px 8px', background: 'var(--bg-1)', border: '1px solid var(--border)', color: 'var(--text-2)', borderRadius: 2 }} />

      {/* Config */}
      <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
        <label style={{ display: 'flex', gap: 4, alignItems: 'center', fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-2)' }}>
          <input type="checkbox" checked={memEnabled} onChange={e => setMemEnabled(e.target.checked)} /> Memory enabled
        </label>
        <div style={{ display: 'flex', gap: 8 }}>
          {[['muninndb','MuninnDB'],['postgres','PostgreSQL']].map(([v,l]) => (
            <label key={v} style={{ display: 'flex', gap: 3, alignItems: 'center', fontFamily: 'var(--font-mono)', fontSize: 9, color: memEnabled ? 'var(--text-2)' : 'var(--text-3)' }}>
              <input type="radio" disabled={!memEnabled} checked={memBackend === v} onChange={() => setMemBackend(v)} /> {l}
            </label>
          ))}
        </div>
      </div>

      {/* Category filter */}
      <div>
        <Label>FILTER BY CATEGORY (empty = all)</Label>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {cats.map(c => (
            <label key={c} style={{ display: 'flex', gap: 3, alignItems: 'center', cursor: 'pointer' }}>
              <input type="checkbox" checked={selCats.has(c)} onChange={() => toggleCat(c)} />
              <span style={catStyle(c)}>{c}</span>
            </label>
          ))}
        </div>
      </div>

      {/* Individual test selection */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        <Label>OR PICK SPECIFIC TESTS ({selTests.size} selected)</Label>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {cases.map(c => (
            <label key={c.id} style={{ display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer', padding: '2px 4px' }}>
              <input type="checkbox" checked={selTests.has(c.id)} onChange={() => toggleTest(c.id)} />
              <Mono style={{ color: 'var(--text-3)', width: 160 }}>{c.id}</Mono>
              <span style={catStyle(c.category)}>{c.category}</span>
              <Mono style={{ color: 'var(--text-2)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.task}</Mono>
            </label>
          ))}
        </div>
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 3: RESULTS
// ══════════════════════════════════════════════════════════════════════════════
function ResultsTab({ refresh }) {
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, height: '100%', overflowY: 'auto' }}>
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
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 4: COMPARE
// ══════════════════════════════════════════════════════════════════════════════
function CompareTab() {
  const [allRuns, setAllRuns]   = useState([])
  const [selIds, setSelIds]     = useState(['','','',''])
  const [compared, setCompared] = useState(null)
  const [loading, setLoading]   = useState(false)

  useEffect(() => {
    api('/api/tests/runs?limit=100').then(r => r.json()).then(d => setAllRuns(d.runs || [])).catch(() => {})
  }, [])

  const load = async () => {
    const ids = selIds.filter(Boolean)
    if (ids.length < 2) return
    setLoading(true)
    const d = await api(`/api/tests/runs/compare?ids=${ids.join(',')}`).then(r => r.json())
    setCompared(d.runs || []); setLoading(false)
  }

  const exportHtml = () => {
    if (!compared) return
    const rows = buildCompareRows(compared)
    const html = renderCompareHtml(compared, rows)
    const b = new Blob([html], {type:'text/html'})
    const a = document.createElement('a'); a.href = URL.createObjectURL(b)
    a.download = `deathstar-test-compare-${Date.now()}.html`; a.click()
  }

  const compared4 = compared?.filter(Boolean) || []
  const allTestIds = [...new Set(compared4.flatMap(r => (r.results || []).map(x => x.test_id)))]

  const getResult = (run, testId) => run?.results?.find(r => r.test_id === testId)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, height: '100%' }}>
      {/* Run selectors */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexShrink: 0, flexWrap: 'wrap' }}>
        {[0,1,2,3].map(i => (
          <select key={i} value={selIds[i]} onChange={e => setSelIds(s => { const n=[...s]; n[i]=e.target.value; return n })}
            style={{ fontFamily: 'var(--font-mono)', fontSize: 9, padding: '3px 7px', background: 'var(--bg-1)', border: '1px solid var(--border)', color: 'var(--text-2)', borderRadius: 2, maxWidth: 200 }}>
            <option value="">— run {i+1} —</option>
            {allRuns.map(r => <option key={r.id} value={r.id}>{ago(r.started_at)} {r.suite_name || 'ad-hoc'} {r.score_pct?.toFixed(0)}%</option>)}
          </select>
        ))}
        <Btn onClick={load} accent disabled={selIds.filter(Boolean).length < 2 || loading}>
          {loading ? '…' : '⊞ compare'}
        </Btn>
        {compared4.length > 1 && <Btn onClick={exportHtml}>↓ export HTML</Btn>}
      </div>

      {/* Score summary */}
      {compared4.length > 0 && (
        <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
          {compared4.map((r,i) => r && (
            <div key={i} style={{ flex: 1, background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 2, padding: '8px 10px' }}>
              <Mono style={{ color: 'var(--text-3)', display: 'block' }}>{ago(r.started_at)}</Mono>
              <Mono style={{ color: 'var(--text-1)', display: 'block', fontSize: 10 }}>{r.suite_name || 'ad-hoc'}</Mono>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 20, fontWeight: 700, color: scoreColor(r.score_pct), marginTop: 4 }}>{r.score_pct?.toFixed(1)}%</div>
              <Mono style={{ color: 'var(--text-2)' }}>{r.passed}/{r.total} passed</Mono>
              {r.config?.memoryEnabled === false && <Mono style={{ color: 'var(--amber)', display: 'block' }}>⊘ memory off</Mono>}
            </div>
          ))}
        </div>
      )}

      {/* Per-test comparison table */}
      {compared4.length > 0 && allTestIds.length > 0 && (
        <div style={{ flex: 1, overflowY: 'auto' }}>
          <div style={{ display: 'grid', gridTemplateColumns: `200px repeat(${compared4.length}, 1fr)`, gap: 1 }}>
            {/* Header */}
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--text-3)', padding: '4px 6px', background: 'var(--bg-1)' }}>TEST</div>
            {compared4.map((r,i) => (
              <div key={i} style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--text-2)', padding: '4px 6px', background: 'var(--bg-1)', textAlign: 'center' }}>
                {ago(r?.started_at)} {r?.score_pct?.toFixed(0)}%
              </div>
            ))}
            {/* Rows */}
            {allTestIds.map(tid => {
              const results = compared4.map(r => getResult(r, tid))
              const anyChange = results.some((r,i) => i > 0 && r?.passed !== results[0]?.passed)
              return (
                <>
                  <div key={tid} style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: anyChange ? 'var(--amber)' : 'var(--text-3)', padding: '3px 6px', background: anyChange ? 'rgba(204,136,0,0.06)' : 'transparent', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{tid}</div>
                  {results.map((r,i) => (
                    <div key={i} style={{ textAlign: 'center', padding: '3px 0', background: anyChange ? 'rgba(204,136,0,0.06)' : 'transparent', fontSize: 11 }}>
                      {!r ? '—' : r.passed ? <span style={{ color: 'var(--green)' }}>✓</span> : r.soft ? <span style={{ color: 'var(--amber)' }}>⚠</span> : <span style={{ color: 'var(--red)' }}>✗</span>}
                    </div>
                  ))}
                </>
              )
            })}
          </div>
        </div>
      )}
      {!compared && <Mono style={{ color: 'var(--text-3)', marginTop: 20 }}>Select 2–4 runs and click compare.</Mono>}
    </div>
  )
}

function buildCompareRows(runs) {
  return [...new Set(runs.flatMap(r => (r.results || []).map(x => x.test_id)))]
}

function renderCompareHtml(runs, rows) {
  return `<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>DEATHSTAR Test Comparison</title>
<style>
body{background:#05060a;color:#e8e8f0;font-family:'Share Tech Mono',monospace;padding:24px;font-size:11px}
h1{color:#a01828;letter-spacing:0.1em;margin-bottom:16px}
.score{font-size:24px;font-weight:700;margin:4px 0}
.run-summary{display:inline-block;background:#0d0f1a;border:1px solid #1a1c2a;padding:10px 14px;margin:0 8px 16px 0;border-radius:2px}
table{border-collapse:collapse;width:100%}
th,td{padding:4px 8px;border-bottom:1px solid #111320;text-align:left}
th{color:#5a5a72;font-size:8px;letter-spacing:0.1em;text-transform:uppercase}
.pass{color:#00aa44}.fail{color:#cc2828}.soft{color:#cc8800}
.changed{background:rgba(204,136,0,0.06)}
.score-good{color:#00aa44}.score-mid{color:#cc8800}.score-bad{color:#cc2828}
</style></head><body>
<h1>◈ DEATHSTAR — Test Comparison Report</h1>
<p style="color:#5a5a72;margin-bottom:16px">Generated: ${new Date().toISOString()}</p>
${runs.map(r => `<div class="run-summary">
  <div style="color:#9090a8">${new Date(r.started_at).toLocaleString()}</div>
  <div>${r.suite_name || 'ad-hoc'}</div>
  <div class="score ${r.score_pct>=90?'score-good':r.score_pct>=70?'score-mid':'score-bad'}">${r.score_pct?.toFixed(1)}%</div>
  <div>${r.passed}/${r.total} passed</div>
  ${r.config?.memoryEnabled===false ? '<div style="color:#cc8800">⊘ memory off</div>' : ''}
</div>`).join('')}
<table>
<tr><th>Test</th>${runs.map((r,i) => `<th>Run ${i+1}: ${r.score_pct?.toFixed(0)}%</th>`).join('')}</tr>
${[...new Set(runs.flatMap(r=>(r.results||[]).map(x=>x.test_id)))].map(tid => {
  const res = runs.map(r => r.results?.find(x=>x.test_id===tid))
  const changed = res.some((r,i) => i>0 && r?.passed !== res[0]?.passed)
  return `<tr class="${changed?'changed':''}">
    <td style="color:${changed?'#cc8800':'#5a5a72'}">${tid}</td>
    ${res.map(r => !r ? '<td>—</td>' : r.passed ? '<td class="pass">✓</td>' : r.soft ? '<td class="soft">⚠</td>' : '<td class="fail">✗</td>').join('')}
  </tr>`
}).join('')}
</table></body></html>`
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 5: TREND & SCHEDULE
// ══════════════════════════════════════════════════════════════════════════════
function TrendTab() {
  const [trend, setTrend]         = useState([])
  const [suites, setSuites]       = useState([])
  const [schedules, setSchedules] = useState([])
  const [newSched, setNewSched]   = useState({ name: '', suite_id: '', cron: '0 2 * * *', enabled: true })

  const load = useCallback(() => {
    api('/api/tests/trend').then(r => r.json()).then(d => setTrend(d.trend || [])).catch(() => {})
    api('/api/tests/suites').then(r => r.json()).then(d => setSuites(d.suites || [])).catch(() => {})
    api('/api/tests/schedules').then(r => r.json()).then(d => setSchedules(d.schedules || [])).catch(() => {})
  }, [])
  useEffect(() => { load() }, [load])

  const addSchedule = async () => {
    if (!newSched.name || !newSched.suite_id) return
    await api('/api/tests/schedules', {
      method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify(newSched)
    })
    setNewSched({ name: '', suite_id: '', cron: '0 2 * * *', enabled: true })
    load()
  }

  const delSchedule = async (id) => { await api(`/api/tests/schedules/${id}`, { method: 'DELETE' }); load() }
  const toggleSched = async (id, en) => {
    await api(`/api/tests/schedules/${id}/toggle`, {
      method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: en })
    }); load()
  }

  // Sparkline (SVG)
  const maxScore = 100
  const W = 300, H = 60
  const pts = trend.map((t,i) => ({ x: (i/(Math.max(trend.length-1,1)))*W, y: H - (t.score_pct/maxScore)*H }))
  const path = pts.map((p,i) => `${i===0?'M':'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, height: '100%', overflowY: 'auto' }}>

      {/* Trend chart */}
      <div>
        <Label>SCORE OVER TIME</Label>
        {trend.length < 2 && <Mono style={{ color: 'var(--text-3)' }}>Need at least 2 completed runs for trend.</Mono>}
        {trend.length >= 2 && (
          <div style={{ background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 2, padding: 12 }}>
            <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 80, display: 'block' }}>
              {[25,50,75].map(y => (
                <line key={y} x1={0} y1={H-(y/maxScore)*H} x2={W} y2={H-(y/maxScore)*H}
                  stroke="rgba(255,255,255,0.05)" strokeDasharray="2,4" />
              ))}
              <path d={path} fill="none" stroke="var(--accent)" strokeWidth={1.5} />
              {pts.map((p,i) => (
                <circle key={i} cx={p.x} cy={p.y} r={3} fill={scoreColor(trend[i]?.score_pct)} />
              ))}
            </svg>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <Mono style={{ color: 'var(--text-3)' }}>{trend[0] && new Date(trend[0].started_at).toLocaleDateString()}</Mono>
              {trend.length > 1 && (
                <Mono style={{ color: trend[trend.length-1].score_pct >= trend[0].score_pct ? 'var(--green)' : 'var(--red)' }}>
                  {trend[trend.length-1].score_pct >= trend[0].score_pct ? '↑' : '↓'} {Math.abs(trend[trend.length-1].score_pct - trend[0].score_pct).toFixed(1)}pts
                </Mono>
              )}
              <Mono style={{ color: 'var(--text-3)' }}>{trend[trend.length-1] && new Date(trend[trend.length-1].started_at).toLocaleDateString()}</Mono>
            </div>
          </div>
        )}
      </div>

      {/* Schedules */}
      <div>
        <Label>SCHEDULED RUNS</Label>
        <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <input value={newSched.name} onChange={e => setNewSched(s => ({...s, name: e.target.value}))}
            placeholder="Schedule name" style={{ fontFamily: 'var(--font-mono)', fontSize: 9, padding: '3px 7px', background: 'var(--bg-1)', border: '1px solid var(--border)', color: 'var(--text-1)', borderRadius: 2, width: 140 }} />
          <select value={newSched.suite_id} onChange={e => setNewSched(s => ({...s, suite_id: e.target.value}))}
            style={{ fontFamily: 'var(--font-mono)', fontSize: 9, padding: '3px 7px', background: 'var(--bg-1)', border: '1px solid var(--border)', color: 'var(--text-2)', borderRadius: 2 }}>
            <option value="">— suite —</option>
            {suites.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <input value={newSched.cron} onChange={e => setNewSched(s => ({...s, cron: e.target.value}))}
            placeholder="cron (e.g. 0 2 * * *)"
            style={{ fontFamily: 'var(--font-mono)', fontSize: 9, padding: '3px 7px', background: 'var(--bg-1)', border: '1px solid var(--border)', color: 'var(--text-1)', borderRadius: 2, width: 130 }} />
          <Btn onClick={addSchedule} accent disabled={!newSched.name || !newSched.suite_id}>+ add schedule</Btn>
        </div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--text-3)', marginBottom: 8 }}>
          Common cron patterns: daily 2am: <code>0 2 * * *</code> | every 6h: <code>0 */6 * * *</code> | Mon 9am: <code>0 9 * * 1</code>
        </div>
        {schedules.length === 0 && <Mono style={{ color: 'var(--text-3)' }}>No schedules. Add one above.</Mono>}
        {schedules.map(s => (
          <div key={s.id} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '5px 8px', background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 2, marginBottom: 4 }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: s.enabled ? 'var(--green)' : 'var(--text-3)', flexShrink: 0 }} />
            <Mono style={{ color: 'var(--text-1)', flex: 1 }}>{s.name}</Mono>
            <Mono style={{ color: 'var(--cyan)' }}>{s.cron}</Mono>
            {s.last_run_at && <Mono style={{ color: 'var(--text-3)' }}>last: {ago(s.last_run_at)}</Mono>}
            <Btn onClick={() => toggleSched(s.id, !s.enabled)}>{s.enabled ? 'disable' : 'enable'}</Btn>
            <Btn onClick={() => delSchedule(s.id)}>delete</Btn>
          </div>
        ))}
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// ROOT
// ══════════════════════════════════════════════════════════════════════════════
const TABS = ['Library', 'Suites', 'Results', 'Compare', 'Trend & Schedule']

export default function TestsPanel() {
  const [tab, setTab]       = useState('Library')
  const [refresh, setRefresh] = useState(0)
  const bump = () => setRefresh(r => r + 1)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-0)' }}>
      {/* Tab bar */}
      <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', background: 'var(--bg-1)', flexShrink: 0 }}>
        {TABS.map(t => (
          <button key={t} onClick={() => setTab(t)} style={{
            fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.1em', textTransform: 'uppercase',
            padding: '8px 14px', background: 'none', border: 'none',
            borderBottom: `2px solid ${tab === t ? 'var(--accent)' : 'transparent'}`,
            color: tab === t ? 'var(--accent)' : 'var(--text-3)', cursor: 'pointer',
          }}>{t}</button>
        ))}
      </div>

      {/* Tab content */}
      <div style={{ flex: 1, padding: 16, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {tab === 'Library'          && <LibraryTab onRunSelected={bump} />}
        {tab === 'Suites'           && <SuitesTab onRun={bump} />}
        {tab === 'Results'          && <ResultsTab refresh={refresh} />}
        {tab === 'Compare'          && <CompareTab />}
        {tab === 'Trend & Schedule' && <TrendTab />}
      </div>
    </div>
  )
}
