/**
 * MemoryPanel — browse and search MuninnDB cognitive memory.
 * Shows recent engrams, supports keyword search + context activation.
 */
import { useEffect, useState, useCallback, useRef } from 'react'
import { fetchMemoryHealth, fetchMemoryRecent, searchMemory, activateMemory, deleteMemoryEngram, fetchMemoryPatterns, fetchMemoryDocs, triggerDocFetch } from '../api'

const POLL_MS = 30_000

// ── Patterns view ──────────────────────────────────────────────────────────

const STATUS_COLOR = {
  completed: 'text-green-400',
  failed:    'text-red-400',
  escalated: 'text-orange-400',
  cancelled: 'text-slate-400',
}

function PatternsView() {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const d = await fetchMemoryPatterns()
      setData(d)
    } catch (e) {
      setError('Failed to load patterns')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return (
    <div className="flex-1 flex items-center justify-center">
      <span className="text-slate-600 text-xs">Loading patterns…</span>
    </div>
  )
  if (error) return (
    <div className="flex-1 flex items-center justify-center">
      <span className="text-red-500 text-xs">{error}</span>
    </div>
  )
  if (!data) return null

  const totalRuns = data.total_runs ?? 0
  const statuses  = data.status_breakdown ?? {}

  return (
    <div className="flex-1 overflow-y-auto px-3 py-2 space-y-4 text-xs">

      {/* Stats row */}
      <div className="flex flex-wrap gap-3">
        <Stat label="Total Runs" value={totalRuns} />
        {Object.entries(statuses).map(([s, n]) => (
          <Stat key={s} label={s} value={n} accent={STATUS_COLOR[s]} />
        ))}
        <Stat label="Positive signals" value={data.positive_signals ?? 0} accent="text-green-400" />
        <Stat label="Negative signals" value={data.negative_signals ?? 0} accent="text-red-400"   />
      </div>

      {/* Avg steps */}
      {Object.keys(data.avg_steps_per_agent_type ?? {}).length > 0 && (
        <Section title="Avg Steps per Agent Type">
          <div className="flex flex-wrap gap-2">
            {Object.entries(data.avg_steps_per_agent_type).map(([agent, avg]) => (
              <span key={agent} className="bg-slate-800 rounded px-2 py-0.5 font-mono">
                {agent}: <span className="text-blue-300">{avg}</span>
              </span>
            ))}
          </div>
        </Section>
      )}

      {/* Successful sequences */}
      {data.most_successful_sequences?.length > 0 && (
        <Section title="Top Successful Sequences">
          {data.most_successful_sequences.map((s, i) => (
            <SequenceRow key={i} seq={s} color="text-green-400" />
          ))}
        </Section>
      )}

      {/* Failed sequences */}
      {data.most_failed_sequences?.length > 0 && (
        <Section title="Top Failed Sequences">
          {data.most_failed_sequences.map((s, i) => (
            <SequenceRow key={i} seq={s} color="text-red-400" />
          ))}
        </Section>
      )}

      {/* Top tools */}
      {data.top_tools?.length > 0 && (
        <Section title="Most Used Tools">
          <div className="flex flex-wrap gap-1.5">
            {data.top_tools.map(({ tool, count }) => (
              <span key={tool} className="bg-slate-800 rounded px-2 py-0.5 font-mono">
                {tool} <span className="text-blue-300">×{count}</span>
              </span>
            ))}
          </div>
        </Section>
      )}

      {/* Recommendations */}
      {data.recommendations?.length > 0 && (
        <Section title="Recommendations">
          <ul className="space-y-1">
            {data.recommendations.map((r, i) => (
              <li key={i} className="flex gap-2 text-slate-300">
                <span className="text-yellow-500 shrink-0">›</span>
                <span>{r}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <div className="pt-1">
        <button onClick={load} className="text-slate-600 hover:text-slate-400 text-xs">
          ↺ Refresh
        </button>
      </div>
    </div>
  )
}

function Stat({ label, value, accent }) {
  return (
    <div className="bg-slate-800 rounded px-2 py-1">
      <div className="text-slate-500 text-xs">{label}</div>
      <div className={`font-mono font-bold ${accent ?? 'text-slate-200'}`}>{value}</div>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div>
      <p className="text-slate-500 font-semibold uppercase tracking-wider text-xs mb-1">{title}</p>
      <div className="space-y-1">{children}</div>
    </div>
  )
}

function SequenceRow({ seq, color }) {
  return (
    <div className="flex items-center gap-1 bg-slate-800 rounded px-2 py-1">
      <span className={`font-mono font-bold ${color} shrink-0 w-6`}>×{seq.count}</span>
      <span className="text-slate-400 font-mono text-xs truncate">
        {seq.sequence.join(' → ')}
      </span>
    </div>
  )
}

function EngramCard({ engram, onDelete }) {
  const [deleting, setDeleting] = useState(false)
  const score = engram.score ?? null
  const tags  = engram.tags ?? []

  const handleDelete = async () => {
    setDeleting(true)
    await onDelete(engram.id)
  }

  return (
    <div className="border border-slate-800 rounded p-2 text-xs hover:border-slate-600 transition-colors">
      <div className="flex items-start justify-between gap-2 mb-1">
        <span className="text-blue-400 font-mono truncate flex-1" title={engram.concept}>
          {engram.concept}
        </span>
        <div className="flex items-center gap-2 shrink-0">
          {score !== null && (
            <span className="text-slate-500 font-mono">{(score * 100).toFixed(0)}%</span>
          )}
          <button
            onClick={handleDelete}
            disabled={deleting}
            className="text-slate-700 hover:text-red-400 transition-colors text-xs"
            title="Delete engram"
          >
            ×
          </button>
        </div>
      </div>
      <p className="text-slate-400 leading-snug line-clamp-3">{engram.content}</p>
      {tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1.5">
          {tags.map(t => (
            <span key={t} className="bg-slate-800 text-slate-500 px-1 rounded font-mono text-xs">
              {t}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Documentation view ─────────────────────────────────────────────────────

const COMPONENT_LABEL = {
  kafka:         'Apache Kafka',
  nginx:         'nginx',
  elasticsearch: 'Elasticsearch',
  swarm:         'Docker Swarm',
  filebeat:      'Filebeat',
}

const COMPONENT_COLOR = {
  kafka:         'text-orange-300',
  nginx:         'text-green-300',
  elasticsearch: 'text-yellow-300',
  swarm:         'text-blue-300',
  filebeat:      'text-purple-300',
}

function DocsView() {
  const [sources,  setSources]  = useState([])
  const [loading,  setLoading]  = useState(true)
  const [fetching, setFetching] = useState({})  // { component: bool }
  const [docQuery, setDocQuery] = useState('')
  const [docResults, setDocResults] = useState([])
  const [searching, setSearching] = useState(false)

  const loadStatus = useCallback(async () => {
    try {
      const d = await fetchMemoryDocs()
      setSources(d.sources ?? [])
    } catch { /* offline */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { loadStatus() }, [loadStatus])

  const handleFetch = async (component) => {
    setFetching(prev => ({ ...prev, [component]: true }))
    try {
      await triggerDocFetch(component, false)
      // Poll once after 3s for updated status
      setTimeout(loadStatus, 3000)
    } finally {
      setFetching(prev => ({ ...prev, [component]: false }))
    }
  }

  const handleDocSearch = async (e) => {
    e.preventDefault()
    if (!docQuery.trim()) return
    setSearching(true)
    setDocResults([])
    try {
      const d = await searchMemory(docQuery, 20)
      const docOnly = (d.results ?? []).filter(e =>
        e.concept?.startsWith('docs:') ||
        (e.tags ?? []).includes('documentation')
      )
      setDocResults(docOnly)
    } finally {
      setSearching(false)
    }
  }

  if (loading) return (
    <div className="flex-1 flex items-center justify-center">
      <span className="text-slate-600 text-xs">Loading documentation status…</span>
    </div>
  )

  return (
    <div className="flex flex-col h-full">
      {/* Source cards */}
      <div className="px-3 py-2 space-y-1.5 shrink-0">
        {sources.map(src => {
          const label = COMPONENT_LABEL[src.component] ?? src.component
          const color = COMPONENT_COLOR[src.component] ?? 'text-slate-300'
          const ts    = src.last_fetched
            ? new Date(src.last_fetched).toLocaleDateString()
            : 'never'
          return (
            <div
              key={src.component}
              className="flex items-center justify-between bg-slate-800 rounded px-3 py-2"
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className={`text-xs font-medium ${color}`}>{label}</span>
                  {src.fresh && (
                    <span className="text-xs text-green-500">✓</span>
                  )}
                </div>
                <div className="text-slate-500 text-xs font-mono mt-0.5">
                  {src.chunks > 0
                    ? `${src.chunks} chunks · ${ts}`
                    : 'not ingested'}
                </div>
              </div>
              <button
                onClick={() => handleFetch(src.component)}
                disabled={!!fetching[src.component]}
                title={src.chunks > 0 ? 'Re-fetch docs' : 'Fetch docs'}
                className="ml-3 text-xs px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-300 disabled:opacity-40 transition-colors shrink-0"
              >
                {fetching[src.component] ? '…' : src.chunks > 0 ? '↺' : 'Fetch'}
              </button>
            </div>
          )
        })}
        {sources.length === 0 && (
          <p className="text-xs text-slate-600 italic text-center py-3">
            MuninnDB offline or no sources configured
          </p>
        )}
      </div>

      {/* Divider + doc search */}
      <div className="border-t border-slate-700 mx-3 mt-1 mb-2" />
      <form onSubmit={handleDocSearch} className="flex gap-2 px-3 pb-2 shrink-0">
        <input
          value={docQuery}
          onChange={e => setDocQuery(e.target.value)}
          placeholder="Search documentation…"
          className="flex-1 bg-slate-800 text-slate-200 text-xs rounded px-2 py-1 border border-slate-700 focus:outline-none focus:border-blue-600 placeholder-slate-600"
        />
        <button
          type="submit"
          disabled={searching || !docQuery.trim()}
          className="text-xs px-2 py-1 bg-blue-800 text-blue-200 rounded hover:bg-blue-700 disabled:opacity-50 transition-colors"
        >
          {searching ? '…' : 'Search'}
        </button>
      </form>

      {/* Search results */}
      <div className="flex-1 overflow-y-auto px-3 pb-2 space-y-2">
        {docResults.length === 0 && docQuery && !searching && (
          <p className="text-xs text-slate-600 italic text-center py-2">No results</p>
        )}
        {docResults.map(e => {
          // Strip metadata header from display
          const body = e.content?.replace(/^\[source:[^\]]+\]\n\n/, '').trim() ?? ''
          const srcM = e.content?.match(/source:\s*([^|]+)/)
          const src  = srcM ? srcM[1].trim() : e.concept
          return (
            <div key={e.id} className="border border-slate-800 rounded p-2 text-xs hover:border-slate-600">
              <div className="text-blue-400 font-mono mb-1 text-xs">{src}</div>
              <p className="text-slate-400 leading-snug line-clamp-4">{body}</p>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function MemoryPanel() {
  const [engrams, setEngrams]     = useState([])
  const [health, setHealth]       = useState(null)
  const [query, setQuery]         = useState('')
  const [mode, setMode]           = useState('recent')   // 'recent' | 'search' | 'activate' | 'patterns' | 'docs'
  const [loading, setLoading]     = useState(false)
  const [count, setCount]         = useState(0)
  const [showAlerts, setShowAlerts] = useState(false)
  const inputRef                  = useRef(null)

  const loadRecent = useCallback(async () => {
    try {
      const d = await fetchMemoryRecent(30)
      setEngrams(d.engrams ?? [])
      setCount(d.count ?? 0)
    } catch { /* MuninnDB offline */ }
  }, [])

  const checkHealth = useCallback(async () => {
    try {
      const h = await fetchMemoryHealth()
      setHealth(h)
    } catch {
      setHealth({ reachable: false })
    }
  }, [])

  useEffect(() => {
    checkHealth()
    loadRecent()
    const id = setInterval(() => {
      checkHealth()
      if (mode === 'recent') loadRecent()
    }, POLL_MS)
    return () => clearInterval(id)
  }, [checkHealth, loadRecent, mode])

  const handleSearch = async (e) => {
    e.preventDefault()
    if (!query.trim()) return
    setLoading(true)
    try {
      if (mode === 'activate') {
        const d = await activateMemory([query], 10)
        setEngrams(d.activations ?? [])
        setCount(d.count ?? 0)
      } else {
        const d = await searchMemory(query, 30)
        setEngrams(d.results ?? [])
        setCount(d.count ?? 0)
      }
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (id) => {
    await deleteMemoryEngram(id)
    setEngrams(prev => prev.filter(e => e.id !== id))
    setCount(prev => Math.max(0, prev - 1))
  }

  const switchMode = (m) => {
    setMode(m)
    setEngrams([])
    if (m === 'recent') loadRecent()
    else if (m !== 'patterns' && m !== 'docs') setTimeout(() => inputRef.current?.focus(), 50)
  }

  const reachable = health?.reachable !== false
  const alertCount = (engrams).filter(e => e.concept?.startsWith('alert:')).length
  const visibleEngrams = (mode !== 'recent' || showAlerts)
    ? engrams
    : engrams.filter(e => !e.concept?.startsWith('alert:'))

  return (
    <div className="flex flex-col h-full text-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-700 shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Memory</span>
          <span className={`w-2 h-2 rounded-full ${reachable ? 'bg-green-500' : 'bg-red-600 animate-pulse'}`} />
          {count > 0 && (
            <span className="text-xs text-slate-600 font-mono">{count}</span>
          )}
          {mode === 'recent' && alertCount > 0 && (
            <button
              onClick={() => setShowAlerts(v => !v)}
              style={{fontSize:'11px', opacity:0.7, background:'transparent',
                      border:'1px solid #444', borderRadius:'4px',
                      padding:'1px 6px', cursor:'pointer', color:'#8b949e'}}
            >
              {showAlerts ? 'Hide alerts' : `+${alertCount} alerts`}
            </button>
          )}
        </div>
        <div className="flex gap-1">
          {['recent', 'search', 'activate', 'patterns', 'docs'].map(m => (
            <button
              key={m}
              onClick={() => switchMode(m)}
              className={`text-xs px-2 py-0.5 rounded transition-colors ${
                mode === m
                  ? 'bg-blue-900 text-blue-300'
                  : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      {/* Search bar (visible in search + activate modes) */}
      {mode !== 'recent' && mode !== 'patterns' && mode !== 'docs' && (
        <form onSubmit={handleSearch} className="flex gap-2 px-3 py-2 border-b border-slate-800 shrink-0">
          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder={mode === 'activate' ? 'Context terms…' : 'Search engrams…'}
            className="flex-1 bg-slate-800 text-slate-200 text-xs rounded px-2 py-1 border border-slate-700 focus:outline-none focus:border-blue-600 placeholder-slate-600"
          />
          <button
            type="submit"
            disabled={loading || !query.trim()}
            className="text-xs px-2 py-1 bg-blue-800 text-blue-200 rounded hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {loading ? '…' : mode === 'activate' ? 'Activate' : 'Search'}
          </button>
        </form>
      )}

      {/* Patterns / Docs view — separate render paths */}
      {mode === 'patterns' ? (
        <PatternsView />
      ) : mode === 'docs' ? (
        <DocsView />
      ) : (
        <>
          {/* Engram list */}
          <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
            {!reachable && (
              <p className="text-xs text-red-400 text-center py-4">
                MuninnDB offline — check container
              </p>
            )}
            {reachable && engrams.length === 0 && !loading && (
              <p className="text-xs text-slate-600 italic text-center py-4">
                {mode === 'recent' ? 'No engrams stored yet' : 'No results'}
              </p>
            )}
            {visibleEngrams.map(e => (
              <EngramCard key={e.id} engram={e} onDelete={handleDelete} />
            ))}
          </div>

          {/* Footer */}
          {mode === 'activate' && (
            <div className="px-3 py-1 border-t border-slate-800 shrink-0">
              <p className="text-xs text-slate-700">
                Activate: Hebbian scoring — full-text + recency + access frequency
              </p>
            </div>
          )}
        </>
      )}
    </div>
  )
}
