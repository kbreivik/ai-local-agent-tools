/**
 * TestsPanel — view and trigger integration test runs.
 * Shows last run results, score, per-test pass/fail, and a Run Tests button.
 */
import { useEffect, useState, useCallback } from 'react'

const API = ''   // proxied via Vite

async function fetchResults() {
  const r = await fetch(`${API}/api/tests/results`)
  return r.json()
}

async function fetchRunning() {
  const r = await fetch(`${API}/api/tests/running`)
  return r.json()
}

async function triggerRun(categories = null) {
  const r = await fetch(`${API}/api/tests/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ categories }),
  })
  return r.json()
}

// ── Category badge ─────────────────────────────────────────────────────────────

const CAT_COLOR = {
  status:   'bg-blue-900 text-blue-300',
  research: 'bg-purple-900 text-purple-300',
  ambiguous:'bg-yellow-900 text-yellow-300',
  action:   'bg-orange-900 text-orange-300',
  safety:   'bg-red-900 text-red-300',
}

function CatBadge({ cat }) {
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded font-mono ${CAT_COLOR[cat] ?? 'bg-slate-700 text-slate-300'}`}>
      {cat}
    </span>
  )
}

// ── Result row ─────────────────────────────────────────────────────────────────

function ResultRow({ r }) {
  const [open, setOpen] = useState(false)
  const icon = r.passed ? '✓' : r.soft ? '⚠' : '✗'
  const rowCls = r.passed
    ? 'border-green-900'
    : r.soft
      ? 'border-yellow-900'
      : r.critical
        ? 'border-red-500'
        : 'border-red-900'

  return (
    <div
      className={`border-l-2 ${rowCls} bg-slate-800 rounded px-3 py-2 text-xs cursor-pointer select-none`}
      onClick={() => setOpen(o => !o)}
    >
      <div className="flex items-center gap-2">
        <span className={`font-bold w-3 shrink-0 ${r.passed ? 'text-green-400' : r.soft ? 'text-yellow-400' : 'text-red-400'}`}>
          {icon}
        </span>
        <CatBadge cat={r.category} />
        <span className="text-slate-300 flex-1 truncate" title={r.task}>{r.task}</span>
        <span className="text-slate-600 shrink-0 font-mono">{r.duration_s}s</span>
        {r.agent_type && (
          <span className="text-slate-600 shrink-0 font-mono text-xs">[{r.agent_type}]</span>
        )}
        {r.critical && !r.passed && (
          <span className="text-red-400 text-xs shrink-0">⛔</span>
        )}
      </div>

      {open && (
        <div className="mt-2 space-y-1 pl-5">
          {r.failures.map((f, i) => (
            <div key={i} className="text-red-400">✗ {f}</div>
          ))}
          {r.warnings.map((w, i) => (
            <div key={i} className="text-yellow-400">⚠ {w}</div>
          ))}
          {r.tools_used?.length > 0 && (
            <div className="text-slate-500 font-mono">
              tools: {r.tools_used.join(' → ')}
            </div>
          )}
          {r.had_plan && <div className="text-orange-400">plan triggered</div>}
          {r.had_clarification && <div className="text-blue-400">clarification triggered</div>}
          {r.choices?.length > 0 && (
            <div className="text-green-400">choices: {r.choices.length}</div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Score ring ─────────────────────────────────────────────────────────────────

function ScoreBadge({ pct }) {
  const color = pct >= 90 ? 'text-green-400' : pct >= 70 ? 'text-yellow-400' : 'text-red-400'
  return (
    <div className={`text-3xl font-bold font-mono ${color}`}>{pct}%</div>
  )
}

// ── Main panel ─────────────────────────────────────────────────────────────────

const CATEGORIES = ['status', 'research', 'ambiguous', 'action', 'safety']

export default function TestsPanel() {
  const [data,      setData]      = useState(null)
  const [loading,   setLoading]   = useState(true)
  const [running,   setRunning]   = useState(false)
  const [filter,    setFilter]    = useState('all')   // 'all' | category | 'failed'
  const [startMsg,  setStartMsg]  = useState(null)

  const loadResults = useCallback(async () => {
    try {
      const d = await fetchResults()
      setData(d)
    } catch { /* API offline */ }
    finally { setLoading(false) }
  }, [])

  // Poll while running
  useEffect(() => {
    loadResults()
    const poll = setInterval(async () => {
      const { running: r } = await fetchRunning().catch(() => ({ running: false }))
      setRunning(r)
      if (!r) loadResults()
    }, 3000)
    return () => clearInterval(poll)
  }, [loadResults])

  const handleRun = async (cats = null) => {
    setStartMsg(null)
    const resp = await triggerRun(cats)
    if (resp.status === 'started') {
      setRunning(true)
      setStartMsg('Test run started…')
    } else {
      setStartMsg(resp.message ?? 'Error starting tests')
    }
  }

  // Filtered results
  const allResults = data?.results ?? []
  const filtered = filter === 'all'
    ? allResults
    : filter === 'failed'
      ? allResults.filter(r => !r.passed)
      : allResults.filter(r => r.category === filter)

  const ts = data?.timestamp
    ? new Date(data.timestamp).toLocaleString()
    : null

  return (
    <div className="flex flex-col h-full text-sm bg-slate-950">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-700 shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Tests</span>
          {running && (
            <span className="text-yellow-400 animate-pulse text-xs">⚡ Running…</span>
          )}
          {ts && !running && (
            <span className="text-slate-600 text-xs">{ts}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => handleRun(null)}
            disabled={running}
            className="text-xs px-2 py-1 bg-blue-800 hover:bg-blue-700 text-blue-200 rounded disabled:opacity-40 transition-colors"
          >
            {running ? '⏳' : '▶ Run All'}
          </button>
        </div>
      </div>

      {/* Score summary */}
      {data && data.total > 0 && !data.error && (
        <div className="flex items-center gap-6 px-4 py-3 border-b border-slate-800 shrink-0">
          <ScoreBadge pct={data.score_pct ?? 0} />
          <div className="space-y-0.5">
            <div className="text-slate-400 text-xs">
              <span className="text-green-400 font-bold">{data.passed}</span>
              <span className="text-slate-600">/{data.total} hard tests passed</span>
            </div>
            {data.soft_failed > 0 && (
              <div className="text-yellow-400 text-xs">{data.soft_failed} advisory failures</div>
            )}
            {data.failed > 0 && (
              <div className="text-red-400 text-xs font-bold">{data.failed} hard failures</div>
            )}
          </div>

          {/* Per-category quick buttons */}
          <div className="flex gap-1 ml-auto">
            {CATEGORIES.map(cat => {
              const catResults = allResults.filter(r => r.category === cat)
              const catPassed  = catResults.filter(r => r.passed).length
              const allPassed  = catPassed === catResults.length
              return catResults.length > 0 ? (
                <button
                  key={cat}
                  onClick={() => handleRun([cat])}
                  disabled={running}
                  title={`Run ${cat} tests (${catPassed}/${catResults.length})`}
                  className={`text-xs px-1.5 py-0.5 rounded transition-colors disabled:opacity-40 ${
                    allPassed
                      ? 'bg-green-900 text-green-300 hover:bg-green-800'
                      : 'bg-red-900 text-red-300 hover:bg-red-800'
                  }`}
                >
                  {cat[0].toUpperCase()} {catPassed}/{catResults.length}
                </button>
              ) : null
            })}
          </div>
        </div>
      )}

      {/* Filter bar */}
      {allResults.length > 0 && (
        <div className="flex gap-1 px-3 py-1.5 border-b border-slate-800 shrink-0">
          {['all', ...CATEGORIES, 'failed'].map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`text-xs px-2 py-0.5 rounded transition-colors ${
                filter === f
                  ? 'bg-blue-900 text-blue-300'
                  : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      )}

      {/* Results list */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1.5">
        {startMsg && (
          <p className="text-xs text-blue-400 px-1 py-1">{startMsg}</p>
        )}

        {loading && (
          <p className="text-xs text-slate-600 italic text-center py-6">Loading…</p>
        )}

        {!loading && data?.error && (
          <p className="text-xs text-red-400 text-center py-4">{data.error}</p>
        )}

        {!loading && !data?.error && allResults.length === 0 && (
          <div className="text-center py-8 space-y-2">
            <p className="text-xs text-slate-600 italic">No test results yet.</p>
            <button
              onClick={() => handleRun(null)}
              disabled={running}
              className="text-xs px-3 py-1.5 bg-blue-800 hover:bg-blue-700 text-blue-200 rounded disabled:opacity-40"
            >
              ▶ Run Tests Now
            </button>
          </div>
        )}

        {filtered.map(r => (
          <ResultRow key={r.id} r={r} />
        ))}
      </div>

      {/* Footer */}
      <div className="px-3 py-1 border-t border-slate-800 shrink-0">
        <p className="text-xs text-slate-700">
          Click any row to expand details. ⚠ = soft/advisory. ⛔ = critical safety.
        </p>
      </div>
    </div>
  )
}
