# CC PROMPT — v2.29.0 — Doc search: backend endpoints + DocsTab Browse mode

## What this does
Exposes the existing `search_docs()` + `doc_chunks` pgvector table to users via:

1. Two new backend routes in a new `api/routers/docs.py` router:
   - `GET /api/docs/search?q=&platform=&doc_type=&limit=` — hybrid search results
   - `GET /api/docs/sources` — all ingested sources grouped by platform with chunk counts

2. DocsTab.jsx rewrite: replaces the current read-only table with a two-panel layout:
   - Left: Source Browser (platforms → doc count → sources, click to filter)
   - Right: Search box + results (chunk text, source label, score bar, ±2 chunk expander,
     "Ask agent →" button that pre-fills CommandPanel)
   - Preserves existing Generation Log section below

Version bump: 2.28.9 → 2.29.0

---

## Change 1 — api/routers/docs.py (NEW FILE)

```python
"""User-facing doc search endpoints. Wraps api/rag/doc_search.py.

Separate from the ingest router — search is read-only and available to all roles.
"""
import logging
import os
from fastapi import APIRouter, Depends, Query
from api.auth import get_current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/docs", tags=["docs"])


@router.get("/search")
def search_docs_endpoint(
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    platform: str = Query("", description="Platform filter (empty = all)"),
    doc_type: str = Query("", description="doc_type filter (empty = all)"),
    limit: int = Query(12, ge=1, le=50),
    _: str = Depends(get_current_user),
):
    """Hybrid semantic + keyword search over ingested doc_chunks."""
    if not os.environ.get("DATABASE_URL", ""):
        return {"results": [], "query": q, "message": "pgvector unavailable (SQLite mode)"}
    try:
        from api.rag.doc_search import search_docs
        doc_type_filter = [doc_type] if doc_type else None
        results = search_docs(
            query=q,
            platform=platform or "",
            doc_type_filter=doc_type_filter,
            limit=limit,
            token_budget=8000,
        )
        return {"results": results, "query": q, "total": len(results)}
    except Exception as e:
        log.warning("docs/search failed: %s", e)
        return {"results": [], "query": q, "error": str(e)}


@router.get("/sources")
def list_doc_sources(_: str = Depends(get_current_user)):
    """List all ingested sources grouped by platform with chunk counts and doc_types."""
    if not os.environ.get("DATABASE_URL", ""):
        return {"platforms": []}
    try:
        import psycopg2
        from pgvector.psycopg2 import register_vector
        dsn = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        register_vector(conn)
        cur = conn.cursor()
        cur.execute("""
            SELECT
                platform,
                doc_type,
                source_label,
                source_url,
                COUNT(*) AS chunk_count,
                MAX(created_at) AS last_updated
            FROM doc_chunks
            GROUP BY platform, doc_type, source_label, source_url
            ORDER BY platform, source_label
        """)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close(); conn.close()

        # Group by platform
        platforms = {}
        for row in rows:
            p = row["platform"]
            if p not in platforms:
                platforms[p] = {"platform": p, "total_chunks": 0, "sources": []}
            platforms[p]["total_chunks"] += row["chunk_count"]
            platforms[p]["sources"].append({
                "doc_type":     row["doc_type"],
                "source_label": row["source_label"],
                "source_url":   row["source_url"],
                "chunk_count":  row["chunk_count"],
                "last_updated": row["last_updated"].isoformat() if row["last_updated"] else None,
            })

        return {"platforms": sorted(platforms.values(), key=lambda x: x["platform"])}
    except Exception as e:
        log.warning("docs/sources failed: %s", e)
        return {"platforms": [], "error": str(e)}


@router.get("/chunks/around")
def get_chunks_around(
    platform: str = Query(...),
    source_url: str = Query(...),
    chunk_index: int = Query(...),
    window: int = Query(2, ge=1, le=5),
    _: str = Depends(get_current_user),
):
    """Fetch ±window chunks around a given chunk_index for context expansion."""
    if not os.environ.get("DATABASE_URL", ""):
        return {"chunks": []}
    try:
        import psycopg2
        from pgvector.psycopg2 import register_vector
        dsn = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        register_vector(conn)
        cur = conn.cursor()
        cur.execute("""
            SELECT chunk_index, content FROM doc_chunks
            WHERE platform = %s AND source_url = %s
              AND chunk_index BETWEEN %s AND %s
            ORDER BY chunk_index
        """, (platform, source_url, max(0, chunk_index - window), chunk_index + window))
        cols = [d[0] for d in cur.description]
        chunks = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close(); conn.close()
        return {"chunks": chunks}
    except Exception as e:
        log.warning("docs/chunks/around failed: %s", e)
        return {"chunks": [], "error": str(e)}
```

---

## Change 2 — api/main.py: mount docs router

NOTE for CC: Read api/main.py to find the router mounting section.
Add alongside the other router imports and includes:

```python
from api.routers.docs import router as docs_router
app.include_router(docs_router)
```

---

## Change 3 — gui/src/components/DocsTab.jsx: full rewrite

Replace the entire file content with:

```jsx
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

// ── Main DocsTab ──────────────────────────────────────────────────────────────

export default function DocsTab() {
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

      {/* Header */}
      <div style={{ padding: '10px 14px 8px', borderBottom: '1px solid var(--border)',
        background: 'var(--bg-1)', flexShrink: 0 }}>
        <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 13,
          color: 'var(--text-1)', letterSpacing: 0.5, marginBottom: 2 }}>
          DOCUMENTATION
        </div>
        <div style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
          Search ingested docs · click a source to filter · Ask agent → injects chunk as context
        </div>
      </div>

      {/* Main area: source browser + search */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>

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
```

---

## Change 4 — gui/src/App.jsx: listen for navigate-to-commands event

NOTE for CC: Find the existing navigate-to-output and navigate-to-logs listeners in AppShell.
Add a similar listener for the new navigate-to-commands event:

FIND (exact):
```jsx
  // "Full log →" with session_id navigates to Logs tab (session output view)
  useEffect(() => {
    const handler = () => setActiveTab('Logs')
    window.addEventListener('navigate-to-logs', handler)
    return () => window.removeEventListener('navigate-to-logs', handler)
  }, [])
```

REPLACE WITH:
```jsx
  // "Full log →" with session_id navigates to Logs tab (session output view)
  useEffect(() => {
    const handler = () => setActiveTab('Logs')
    window.addEventListener('navigate-to-logs', handler)
    return () => window.removeEventListener('navigate-to-logs', handler)
  }, [])

  // Doc search "Ask agent →" navigates to Commands tab
  useEffect(() => {
    const handler = () => setActiveTab('Commands')
    window.addEventListener('navigate-to-commands', handler)
    return () => window.removeEventListener('navigate-to-commands', handler)
  }, [])
```

---

## Version bump
Update VERSION: 2.28.9 → 2.29.0

## Commit
```bash
git add -A
git commit -m "feat(docs): v2.29.0 doc search API + Browse mode in DocsTab (source browser, chunk search, context expand, Ask agent)"
git push origin main
```
