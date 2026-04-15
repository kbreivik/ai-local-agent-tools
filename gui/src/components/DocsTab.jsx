/**
 * DocsTab — Browse and search ingested documentation.
 * Two panels: Source Browser (left) + Search Results (right).
 * Generation Log preserved below.
 */
import React, { useState, useEffect, useCallback, useRef } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE || ''

// ── Small helpers ─────────────────────────────────────────────────────────────

function ScoreBar({ score }) {
  // RRF scores are typically 0.01–0.04; normalise to 0–100 for display
  const pct = Math.min(100, Math.round((score / 0.04) * 100))
  const color = pct > 60 ? 'var(--green)' : pct > 30 ? 'var(--amber)' : 'var(--text-3)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
      <div style={{ flex: 1, height: 3, background: 'var(--bg-3)', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 2 }} />
      </div>
      <span style={{ fontSize: 8, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', width: 28 }}>
        {pct}%
      </span>
    </div>
  )
}

function ChunkCard({ result, onAskAgent }) {
  const [expanded, setExpanded] = useState(false)
  const [contextChunks, setContextChunks] = useState(null)
  const [loadingCtx, setLoadingCtx] = useState(false)

  const loadContext = async () => {
    if (contextChunks) { setExpanded(e => !e); return }
    setExpanded(true)
    setLoadingCtx(true)
    try {
      const params = new URLSearchParams({
        platform: result.platform,
        source_url: result.source_url || '',
        chunk_index: result.chunk_index ?? 0,
        window: 2,
      })
      const r = await fetch(`${BASE}/api/docs/chunks/around?${params}`, { headers: authHeaders() })
      const d = await r.json()
      setContextChunks(d.chunks || [])
    } catch { setContextChunks([]) }
    setLoadingCtx(false)
  }

  return (
    <div style={{
      background: 'var(--bg-2)', border: '1px solid var(--border)',
      borderRadius: 2, marginBottom: 8, overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{ padding: '7px 10px', borderBottom: '1px solid var(--bg-3)',
        display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 2,
          background: 'var(--accent-dim)', color: 'var(--accent)',
          fontFamily: 'var(--font-mono)', letterSpacing: 0.5 }}>
          {result.platform}
        </span>
        <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 2,
          background: 'var(--bg-3)', color: 'var(--cyan)',
          fontFamily: 'var(--font-mono)' }}>
          {result.doc_type}
        </span>
        <span style={{ fontSize: 9, color: 'var(--text-2)', flex: 1, fontFamily: 'var(--font-mono)' }}>
          {result.source_label || result.source_url || '—'}
        </span>
        {result.version && (
          <span style={{ fontSize: 8, color: 'var(--text-3)' }}>v{result.version}</span>
        )}
        <div style={{ width: 80 }}>
          <ScoreBar score={result.rrf_score} />
        </div>
      </div>

      {/* Content */}
      <div style={{ padding: '8px 10px' }}>
        {expanded && contextChunks ? (
          loadingCtx
            ? <div style={{ fontSize: 10, color: 'var(--text-3)', fontStyle: 'italic' }}>Loading context…</div>
            : contextChunks.map((c, i) => (
                <pre key={i} style={{
                  fontSize: 10, fontFamily: 'var(--font-mono)', color: c.chunk_index === (result.chunk_index ?? 0)
                    ? 'var(--text-1)' : 'var(--text-3)',
                  whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: 0,
                  paddingBottom: 6, marginBottom: 6,
                  borderBottom: i < contextChunks.length - 1 ? '1px solid var(--bg-3)' : 'none',
                  background: c.chunk_index === (result.chunk_index ?? 0) ? 'var(--bg-3)' : 'transparent',
                  padding: '4px 6px', borderRadius: 2,
                }}>
                  <span style={{ fontSize: 8, color: 'var(--text-3)', marginRight: 6 }}>#{c.chunk_index}</span>
                  {c.content}
                </pre>
              ))
        ) : (
          <pre style={{
            fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-1)',
            whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: 0,
            maxHeight: 140, overflow: 'hidden',
          }}>
            {result.content}
          </pre>
        )}
      </div>

      {/* Footer actions */}
      <div style={{ padding: '4px 10px 7px', display: 'flex', gap: 8, alignItems: 'center' }}>
        <button onClick={loadContext} style={{
          fontSize: 9, color: 'var(--cyan)', background: 'none',
          border: '1px solid var(--border)', borderRadius: 2, padding: '2px 8px', cursor: 'pointer',
          fontFamily: 'var(--font-mono)',
        }}>
          {expanded ? '↑ collapse context' : '±2 context'}
        </button>
        <button onClick={() => onAskAgent(result)} style={{
          fontSize: 9, color: 'var(--accent)', background: 'var(--accent-dim)',
          border: '1px solid var(--accent)', borderRadius: 2, padding: '2px 8px', cursor: 'pointer',
          fontFamily: 'var(--font-mono)',
        }}>
          Ask agent →
        </button>
        {result.source_url && (
          <a href={result.source_url} target="_blank" rel="noopener noreferrer" style={{
            fontSize: 9, color: 'var(--text-3)', textDecoration: 'none',
            fontFamily: 'var(--font-mono)',
          }}>
            source ↗
          </a>
        )}
      </div>
    </div>
  )
}

// ── Source browser ────────────────────────────────────────────────────────────

function SourceBrowser({ selectedPlatform, onSelectPlatform }) {
  const [sources, setSources] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetch(`${BASE}/api/docs/sources`, { headers: authHeaders() })
      .then(r => r.json())
      .then(d => { setSources(d.platforms || []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  if (loading) return (
    <div style={{ fontSize: 9, color: 'var(--text-3)', padding: 12, fontFamily: 'var(--font-mono)' }}>
      Loading sources…
    </div>
  )

  if (!sources.length) return (
    <div style={{ fontSize: 9, color: 'var(--text-3)', padding: 12, fontFamily: 'var(--font-mono)' }}>
      No documents indexed. Ingest docs via Settings → Ingest.
    </div>
  )

  return (
    <div>
      {/* All platforms row */}
      <div
        onClick={() => onSelectPlatform('')}
        style={{
          padding: '6px 10px', cursor: 'pointer', fontSize: 10,
          background: !selectedPlatform ? 'var(--accent-dim)' : 'transparent',
          color: !selectedPlatform ? 'var(--accent)' : 'var(--text-2)',
          borderBottom: '1px solid var(--bg-3)', display: 'flex', justifyContent: 'space-between',
          fontFamily: 'var(--font-mono)',
        }}
      >
        <span>ALL</span>
        <span style={{ color: 'var(--text-3)', fontSize: 9 }}>
          {sources.reduce((s, p) => s + p.total_chunks, 0)} chunks
        </span>
      </div>

      {sources.map(p => {
        const isActive = selectedPlatform === p.platform
        return (
          <div key={p.platform}>
            <div
              onClick={() => onSelectPlatform(isActive ? '' : p.platform)}
              style={{
                padding: '6px 10px', cursor: 'pointer',
                background: isActive ? 'var(--accent-dim)' : 'transparent',
                color: isActive ? 'var(--accent)' : 'var(--text-2)',
                borderBottom: '1px solid var(--bg-3)', fontSize: 10,
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                fontFamily: 'var(--font-mono)', letterSpacing: 0.3,
              }}
              onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = 'var(--bg-3)' }}
              onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = 'transparent' }}
            >
              <span style={{ textTransform: 'uppercase', letterSpacing: 0.5 }}>{p.platform}</span>
              <span style={{ fontSize: 8, color: 'var(--text-3)' }}>{p.total_chunks}</span>
            </div>
            {isActive && p.sources.map((s, i) => (
              <div key={i} style={{
                padding: '4px 10px 4px 20px',
                borderBottom: '1px solid var(--bg-3)',
                background: 'var(--bg-1)',
              }}>
                <div style={{ fontSize: 9, color: 'var(--text-2)', fontFamily: 'var(--font-mono)' }}>
                  {s.source_label || s.source_url || s.doc_type}
                </div>
                <div style={{ fontSize: 8, color: 'var(--text-3)', display: 'flex', gap: 8, marginTop: 1 }}>
                  <span>{s.doc_type}</span>
                  <span>{s.chunk_count} chunks</span>
                  {s.last_updated && <span>{s.last_updated.slice(0, 10)}</span>}
                </div>
              </div>
            ))}
          </div>
        )
      })}
    </div>
  )
}

// ── Ask panel ─────────────────────────────────────────────────────────────────

function AskPanel({ platform }) {
  const [question, setQuestion]   = useState('')
  const [answer, setAnswer]       = useState('')
  const [sources, setSources]     = useState([])
  const [streaming, setStreaming] = useState(false)
  const [error, setError]         = useState(null)
  const [done, setDone]           = useState(false)
  const answerRef = useRef(null)

  // Auto-scroll as answer streams
  useEffect(() => {
    if (answerRef.current) {
      answerRef.current.scrollTop = answerRef.current.scrollHeight
    }
  }, [answer])

  const ask = async () => {
    if (!question.trim() || streaming) return
    setAnswer('')
    setSources([])
    setError(null)
    setDone(false)
    setStreaming(true)

    try {
      const token = localStorage.getItem('hp1_auth_token')
      const resp = await fetch(`${BASE}/api/docs/ask`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ question: question.trim(), platform }),
      })

      if (!resp.ok) {
        setError(`Request failed: ${resp.status}`)
        setStreaming(false)
        return
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''

      while (true) {
        const { done: rDone, value } = await reader.read()
        if (rDone) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() || ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const msg = JSON.parse(line.slice(6))
            if (msg.type === 'chunk')   setAnswer(a => a + msg.text)
            if (msg.type === 'sources') setSources(msg.sources || [])
            if (msg.type === 'done')    setDone(true)
            if (msg.type === 'error') {
              setError(msg.message)
              setStreaming(false)
            }
          } catch { /* skip malformed SSE */ }
        }
      }
    } catch (e) {
      setError(`Connection error: ${e.message}`)
    }
    setStreaming(false)
  }

  const handleAskAgent = () => {
    if (!answer) return
    const text = `I found this in the documentation:\n\n${answer}\n\nApply this to our infrastructure and investigate if needed.`
    window.dispatchEvent(new CustomEvent('ds:prefill-agent', { detail: { text } }))
    window.dispatchEvent(new CustomEvent('navigate-to-commands'))
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* Question input */}
      <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)',
        background: 'var(--bg-1)', flexShrink: 0 }}>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            value={question}
            onChange={e => setQuestion(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && !e.shiftKey && ask()}
            placeholder="Ask a question about the ingested documentation…"
            style={{
              flex: 1, padding: '6px 10px', background: 'var(--bg-2)',
              border: '1px solid var(--border)', borderRadius: 2, color: 'var(--text-1)',
              fontSize: 11, fontFamily: 'var(--font-mono)', outline: 'none',
            }}
            onFocus={e => e.target.style.borderColor = 'var(--accent)'}
            onBlur={e => e.target.style.borderColor = 'var(--border)'}
          />
          <button
            onClick={ask}
            disabled={streaming || !question.trim()}
            style={{
              padding: '6px 16px', background: streaming ? 'var(--bg-3)' : 'var(--accent)',
              color: streaming ? 'var(--text-3)' : '#fff',
              border: 'none', borderRadius: 2, fontSize: 10, fontFamily: 'var(--font-mono)',
              cursor: streaming ? 'default' : 'pointer', letterSpacing: 0.5,
              opacity: (!question.trim() && !streaming) ? 0.5 : 1,
            }}
          >
            {streaming ? '\u23F3 thinking\u2026' : 'ASK'}
          </button>
        </div>
        {platform && (
          <div style={{ marginTop: 4, fontSize: 8, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
            Scoped to: <span style={{ color: 'var(--accent)' }}>{platform}</span>
            {' \u2014 '}searching all platforms will give broader results
          </div>
        )}
        <div style={{ marginTop: 4, fontSize: 8, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
          Answers are grounded in ingested docs only \u00B7 sources shown below answer \u00B7 LM Studio required
        </div>
      </div>

      {/* Answer area */}
      <div ref={answerRef} style={{ flex: 1, overflow: 'auto', padding: 14 }}>
        {error && (
          <div style={{ padding: '8px 10px', borderRadius: 2, background: 'var(--red-dim)',
            color: 'var(--red)', fontSize: 10, fontFamily: 'var(--font-mono)', marginBottom: 8 }}>
            \u2715 {error}
          </div>
        )}

        {!answer && !error && !streaming && (
          <div style={{ color: 'var(--text-3)', fontSize: 10, fontFamily: 'var(--font-mono)',
            paddingTop: 20, textAlign: 'center' }}>
            Ask a question to get a grounded answer from your ingested documentation.
            <br />
            <span style={{ fontSize: 9, marginTop: 4, display: 'block' }}>
              Example: "How do I configure Proxmox HA?" or "What are the Kafka min.insync.replicas settings?"
            </span>
          </div>
        )}

        {answer && (
          <>
            <div style={{
              background: 'var(--bg-2)', border: '1px solid var(--border)',
              borderRadius: 2, padding: '12px 14px', marginBottom: 12,
              fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-1)',
              lineHeight: 1.7, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            }}>
              {answer}
              {streaming && (
                <span style={{ display: 'inline-block', width: 8, height: 13,
                  background: 'var(--accent)', marginLeft: 2, animation: 'pulse 1s infinite' }} />
              )}
            </div>

            {done && (
              <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
                <button onClick={handleAskAgent} style={{
                  fontSize: 9, color: 'var(--accent)', background: 'var(--accent-dim)',
                  border: '1px solid var(--accent)', borderRadius: 2, padding: '3px 10px',
                  cursor: 'pointer', fontFamily: 'var(--font-mono)',
                }}>
                  Ask agent to investigate \u2192
                </button>
                <button onClick={() => { setAnswer(''); setSources([]); setDone(false) }} style={{
                  fontSize: 9, color: 'var(--text-3)', background: 'none',
                  border: '1px solid var(--border)', borderRadius: 2, padding: '3px 10px',
                  cursor: 'pointer',
                }}>
                  Clear
                </button>
              </div>
            )}
          </>
        )}

        {/* Sources */}
        {sources.length > 0 && (
          <div>
            <div style={{ fontSize: 8, fontFamily: 'var(--font-mono)', color: 'var(--text-3)',
              letterSpacing: 1, marginBottom: 6 }}>SOURCES USED</div>
            {sources.map((s, i) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', gap: 8, padding: '5px 8px',
                background: 'var(--bg-2)', border: '1px solid var(--border)',
                borderRadius: 2, marginBottom: 4, fontSize: 9, fontFamily: 'var(--font-mono)',
              }}>
                <span style={{ color: 'var(--text-3)', flexShrink: 0 }}>[{i + 1}]</span>
                <span style={{ color: 'var(--accent)', flexShrink: 0 }}>{s.platform}</span>
                <span style={{ color: 'var(--text-2)', flex: 1 }}>{s.source_label || s.source_url || s.doc_type}</span>
                {s.version && <span style={{ color: 'var(--text-3)' }}>v{s.version}</span>}
                {s.source_url && (
                  <a href={s.source_url} target="_blank" rel="noopener noreferrer"
                    style={{ color: 'var(--cyan)', textDecoration: 'none' }}>\u2197</a>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main DocsTab ──────────────────────────────────────────────────────────────

export default function DocsTab() {
  const [mode, setMode]                 = useState('browse')  // 'browse' | 'ask'
  const [query, setQuery]               = useState('')
  const [platform, setPlatform]         = useState('')
  const [results, setResults]           = useState(null)   // null = not searched yet
  const [searching, setSearching]       = useState(false)
  const [searchError, setSearchError]   = useState(null)

  // Generation log (preserved from original)
  const [logRows, setLogRows]           = useState([])
  const [logExpanded, setLogExpanded]   = useState(null)
  const [filterSkill, setFilterSkill]   = useState('')
  const [filterOutcome, setFilterOutcome] = useState('')
  const [logError, setLogError]         = useState(null)

  const inputRef = useRef(null)

  useEffect(() => {
    fetch(`${BASE}/api/skills/generation-log?limit=100`, { headers: authHeaders() })
      .then(r => r.json()).then(d => setLogRows(d.log || [])).catch(e => setLogError(e.message))
  }, [])

  const search = useCallback(async (q = query, p = platform) => {
    if (!q.trim()) return
    setSearching(true)
    setSearchError(null)
    try {
      const params = new URLSearchParams({ q: q.trim(), limit: 12 })
      if (p) params.set('platform', p)
      const r = await fetch(`${BASE}/api/docs/search?${params}`, { headers: authHeaders() })
      const d = await r.json()
      setResults(d.results || [])
    } catch (e) {
      setSearchError(e.message)
      setResults([])
    }
    setSearching(false)
  }, [query, platform])

  const handlePlatformSelect = (p) => {
    setPlatform(p)
    if (query.trim()) search(query, p)
  }

  const handleAskAgent = (result) => {
    const text = `Based on this documentation from ${result.source_label || result.platform}:\n\n${result.content}\n\nInvestigate this in our infrastructure.`
    window.dispatchEvent(new CustomEvent('ds:prefill-agent', { detail: { text } }))
    // Navigate to Commands tab
    window.dispatchEvent(new CustomEvent('navigate-to-commands'))
  }

  const filteredLog = logRows.filter(row => {
    if (filterSkill && !row.skill_name.includes(filterSkill)) return false
    if (filterOutcome && row.outcome !== filterOutcome) return false
    return true
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden',
      background: 'var(--bg-0)', color: 'var(--text-1)' }}>

      {/* Header + mode toggle */}
      <div style={{ padding: '10px 14px 8px', borderBottom: '1px solid var(--border)',
        background: 'var(--bg-1)', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
          <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 13,
            color: 'var(--text-1)', letterSpacing: 0.5 }}>
            DOCUMENTATION
          </span>
          {/* Mode toggle */}
          <div style={{ display: 'flex', gap: 0, marginLeft: 'auto' }}>
            {[['browse', 'Browse'], ['ask', 'Ask (AI)']].map(([m, label]) => (
              <button key={m} onClick={() => setMode(m)} style={{
                fontSize: 9, padding: '3px 12px', fontFamily: 'var(--font-mono)',
                letterSpacing: 0.5, cursor: 'pointer',
                background: mode === m ? 'var(--accent-dim)' : 'var(--bg-3)',
                color: mode === m ? 'var(--accent)' : 'var(--text-3)',
                border: `1px solid ${mode === m ? 'var(--accent)' : 'var(--border)'}`,
                borderRadius: m === 'browse' ? '2px 0 0 2px' : '0 2px 2px 0',
              }}>{label}</button>
            ))}
          </div>
        </div>
        <div style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
          {mode === 'browse'
            ? 'Search ingested docs \u00B7 click a source to filter \u00B7 Ask agent \u2192 injects chunk as context'
            : 'Grounded Q&A from your ingested docs via LM Studio \u00B7 sources cited inline'}
        </div>
      </div>

      {/* Main area: mode-dependent content */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
        {mode === 'ask' && (
          <AskPanel platform={platform} />
        )}
        {mode === 'browse' && <>

        {/* Left: Source browser */}
        <div style={{
          width: 200, flexShrink: 0, borderRight: '1px solid var(--border)',
          overflow: 'auto', background: 'var(--bg-1)',
        }}>
          <div style={{ padding: '6px 10px 4px', fontSize: 7, fontFamily: 'var(--font-mono)',
            color: 'var(--text-3)', letterSpacing: 1, textTransform: 'uppercase',
            borderBottom: '1px solid var(--bg-3)' }}>
            SOURCES
          </div>
          <SourceBrowser selectedPlatform={platform} onSelectPlatform={handlePlatformSelect} />
        </div>

        {/* Right: Search + results */}
        <div style={{ flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column', minWidth: 0 }}>

          {/* Search bar */}
          <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)',
            background: 'var(--bg-1)', flexShrink: 0, display: 'flex', gap: 8 }}>
            <input
              ref={inputRef}
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && search()}
              placeholder="Search documentation… (Enter to search)"
              style={{
                flex: 1, padding: '5px 10px', background: 'var(--bg-2)',
                border: '1px solid var(--border)', borderRadius: 2,
                color: 'var(--text-1)', fontSize: 11,
                fontFamily: 'var(--font-mono)', outline: 'none',
              }}
              onFocus={e => e.target.style.borderColor = 'var(--accent)'}
              onBlur={e => e.target.style.borderColor = 'var(--border)'}
            />
            <button
              onClick={() => search()}
              disabled={searching || !query.trim()}
              style={{
                padding: '5px 16px', background: 'var(--accent)', color: '#fff',
                border: 'none', borderRadius: 2, fontSize: 10, fontFamily: 'var(--font-mono)',
                cursor: 'pointer', opacity: (!query.trim() || searching) ? 0.5 : 1,
                letterSpacing: 0.5,
              }}
            >
              {searching ? '…' : 'SEARCH'}
            </button>
            {results !== null && (
              <button
                onClick={() => { setResults(null); setQuery(''); }}
                style={{
                  padding: '5px 10px', background: 'none', color: 'var(--text-3)',
                  border: '1px solid var(--border)', borderRadius: 2, fontSize: 10,
                  cursor: 'pointer',
                }}
              >✕</button>
            )}
          </div>

          {/* Results */}
          <div style={{ flex: 1, overflow: 'auto', padding: 14 }}>
            {/* Platform filter badge */}
            {platform && (
              <div style={{ marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
                  Filtering:
                </span>
                <span style={{
                  fontSize: 9, padding: '1px 6px', borderRadius: 2,
                  background: 'var(--accent-dim)', color: 'var(--accent)',
                  fontFamily: 'var(--font-mono)',
                }}>
                  {platform}
                </span>
                <button onClick={() => handlePlatformSelect('')}
                  style={{ fontSize: 9, color: 'var(--text-3)', background: 'none', border: 'none',
                    cursor: 'pointer', padding: 0 }}>✕</button>
              </div>
            )}

            {results === null && !searching && (
              <div style={{ color: 'var(--text-3)', fontSize: 10, fontFamily: 'var(--font-mono)',
                paddingTop: 20, textAlign: 'center' }}>
                Enter a search query above or click a source to explore.
                <br />
                <span style={{ fontSize: 9, marginTop: 4, display: 'block' }}>
                  Uses hybrid vector + keyword search (bge-small-en-v1.5 + BM25 RRF)
                </span>
              </div>
            )}

            {searching && (
              <div style={{ color: 'var(--text-3)', fontSize: 10, fontFamily: 'var(--font-mono)',
                paddingTop: 20, textAlign: 'center' }}>
                Searching…
              </div>
            )}

            {searchError && (
              <div style={{ color: 'var(--red)', fontSize: 10, padding: '8px 0' }}>
                ✕ {searchError}
              </div>
            )}

            {results !== null && !searching && results.length === 0 && (
              <div style={{ color: 'var(--text-3)', fontSize: 10, fontFamily: 'var(--font-mono)',
                paddingTop: 20, textAlign: 'center' }}>
                No results found.
                {platform && ' Try clearing the platform filter.'}
              </div>
            )}

            {results !== null && results.length > 0 && (
              <>
                <div style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)',
                  marginBottom: 10 }}>
                  {results.length} chunk{results.length !== 1 ? 's' : ''} · RRF score ·{' '}
                  click ±2 to expand context
                </div>
                {results.map((r, i) => (
                  <ChunkCard key={`${r.platform}-${r.source_url}-${r.chunk_index}-${i}`}
                    result={r} onAskAgent={handleAskAgent} />
                ))}
              </>
            )}
          </div>
        </div>
        </>}
      </div>

      {/* Generation Log (collapsed by default, expand on demand) */}
      <GenerationLogSection logRows={filteredLog} logError={logError}
        filterSkill={filterSkill} setFilterSkill={setFilterSkill}
        filterOutcome={filterOutcome} setFilterOutcome={setFilterOutcome}
        expanded={logExpanded} setExpanded={setLogExpanded} />
    </div>
  )
}

function GenerationLogSection({ logRows, logError, filterSkill, setFilterSkill, filterOutcome, setFilterOutcome, expanded, setExpanded }) {
  const [open, setOpen] = useState(false)

  return (
    <div style={{ borderTop: '1px solid var(--border)', flexShrink: 0, background: 'var(--bg-1)' }}>
      <div
        onClick={() => setOpen(o => !o)}
        style={{ padding: '6px 14px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}
      >
        <span style={{ fontSize: 9, color: 'var(--text-3)', transition: 'transform 0.1s',
          display: 'inline-block', transform: open ? 'rotate(90deg)' : 'none' }}>▶</span>
        <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-2)',
          letterSpacing: 0.5 }}>GENERATION LOG</span>
        <span style={{ fontSize: 9, color: 'var(--text-3)', marginLeft: 4 }}>
          {logRows.length} entries
        </span>
      </div>

      {open && (
        <div style={{ maxHeight: 300, overflow: 'auto', borderTop: '1px solid var(--bg-3)' }}>
          {/* Filters */}
          <div style={{ padding: '6px 14px', display: 'flex', gap: 8, borderBottom: '1px solid var(--bg-3)' }}>
            <input
              value={filterSkill} onChange={e => setFilterSkill(e.target.value)}
              placeholder="filter skill…"
              style={{ fontSize: 9, padding: '2px 8px', background: 'var(--bg-2)',
                border: '1px solid var(--border)', borderRadius: 2, color: 'var(--text-1)',
                fontFamily: 'var(--font-mono)', outline: 'none', width: 140 }}
            />
            <select value={filterOutcome} onChange={e => setFilterOutcome(e.target.value)}
              style={{ fontSize: 9, padding: '2px 6px', background: 'var(--bg-2)',
                border: '1px solid var(--border)', borderRadius: 2, color: 'var(--text-1)' }}>
              <option value="">all outcomes</option>
              <option value="success">success</option>
              <option value="error">error</option>
              <option value="export">export</option>
            </select>
          </div>

          {logError && <div style={{ padding: '6px 14px', fontSize: 9, color: 'var(--red)' }}>{logError}</div>}
          {logRows.length === 0 && (
            <div style={{ padding: '8px 14px', fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
              No log entries.
            </div>
          )}
          {logRows.map(row => (
            <div key={row.id} style={{ borderBottom: '1px solid var(--bg-3)' }}>
              <div
                onClick={() => setExpanded(expanded === row.id ? null : row.id)}
                style={{ padding: '5px 14px', cursor: 'pointer', display: 'flex',
                  gap: 10, alignItems: 'center', fontSize: 9, fontFamily: 'var(--font-mono)',
                  background: expanded === row.id ? 'var(--bg-3)' : 'transparent' }}
              >
                <span style={{ color: row.outcome === 'success' ? 'var(--green)'
                  : row.outcome === 'error' ? 'var(--red)' : 'var(--cyan)' }}>
                  {row.outcome === 'success' ? '✓' : row.outcome === 'error' ? '✕' : '→'}
                </span>
                <span style={{ color: 'var(--text-1)', flex: 1 }}>{row.skill_name}</span>
                <span style={{ color: 'var(--text-3)' }}>{row.backend}</span>
                <span style={{ color: 'var(--text-3)' }}>
                  {row.created_at ? new Date(row.created_at * 1000).toLocaleDateString() : '—'}
                </span>
              </div>
              {expanded === row.id && (
                <div style={{ padding: '6px 20px 8px', fontSize: 9, color: 'var(--text-2)',
                  fontFamily: 'var(--font-mono)', background: 'var(--bg-2)' }}>
                  {row.error_message && (
                    <div style={{ color: 'var(--red)', marginBottom: 4 }}>Error: {row.error_message}</div>
                  )}
                  <div>keywords: {JSON.stringify(row.keywords)}</div>
                  <div>sources: {(row.sources_used || []).join(', ') || 'none'}</div>
                  {(row.docs_retrieved || []).length > 0 && (
                    <div>docs: {row.docs_retrieved.map(d => `${d.concept}(${d.tokens}t)`).join(', ')}</div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
