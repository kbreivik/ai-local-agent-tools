/**
 * MemoryPanel — browse and search MuninnDB cognitive memory.
 * Shows recent engrams, supports keyword search + context activation.
 */
import { useEffect, useState, useCallback, useRef } from 'react'
import { fetchMemoryHealth, fetchMemoryRecent, searchMemory, activateMemory, deleteMemoryEngram } from '../api'

const POLL_MS = 30_000

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

export default function MemoryPanel() {
  const [engrams, setEngrams]     = useState([])
  const [health, setHealth]       = useState(null)
  const [query, setQuery]         = useState('')
  const [mode, setMode]           = useState('recent')   // 'recent' | 'search' | 'activate'
  const [loading, setLoading]     = useState(false)
  const [count, setCount]         = useState(0)
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
    else setTimeout(() => inputRef.current?.focus(), 50)
  }

  const reachable = health?.reachable !== false

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
        </div>
        <div className="flex gap-1">
          {['recent', 'search', 'activate'].map(m => (
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
      {mode !== 'recent' && (
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
        {engrams.map(e => (
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
    </div>
  )
}
