// FactsView — v2.35.0.1
// Two-pane browser for the known_facts store:
//   left:  searchable/filterable list of facts
//   right: selected fact detail — sources, history (with diff viewer),
//          lock controls, refresh + conflict buttons.
//
// Deep-linkable via the hash `#/facts/<fact_key>` to open a specific key.

import { useEffect, useMemo, useState, useCallback } from 'react'
import { authHeaders } from '../api'
import FactDiffViewer from './FactDiffViewer'

const BASE = import.meta.env.VITE_API_BASE ?? ''

async function factsFetch(path, opts = {}) {
  const r = await fetch(`${BASE}/api/facts${path}`, {
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    ...opts,
  })
  const text = await r.text()
  let body
  try { body = text ? JSON.parse(text) : null } catch { body = text }
  if (!r.ok) {
    const msg = (body && body.detail) || r.statusText || 'Request failed'
    const err = new Error(msg)
    err.status = r.status
    throw err
  }
  return body
}

function tierColour(confidence) {
  if (confidence >= 0.9) return 'var(--green)'
  if (confidence >= 0.7) return 'var(--cyan)'
  if (confidence >= 0.5) return 'var(--amber)'
  return 'var(--red)'
}

function freshnessLabel(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const sec = Math.max(0, Math.round((Date.now() - d.getTime()) / 1000))
  if (sec < 60)       return `${sec}s ago`
  if (sec < 3600)     return `${Math.round(sec / 60)}m ago`
  if (sec < 86400)    return `${Math.round(sec / 3600)}h ago`
  return `${Math.round(sec / 86400)}d ago`
}

// ── Fact list ────────────────────────────────────────────────────────────────

function FactList({ facts, selected, onSelect, conflictKeys, lockKeys }) {
  if (!facts.length) {
    return (
      <div style={{ padding: 16, color: 'var(--text-3)', fontSize: 10, fontFamily: 'var(--font-mono)' }}>
        No facts match the current filter.
      </div>
    )
  }
  return (
    <div style={{ overflowY: 'auto', height: '100%' }}>
      {facts.map(f => {
        const isSel = selected === f.fact_key
        const hasConflict = conflictKeys.has(f.fact_key)
        const hasLock     = lockKeys.has(f.fact_key)
        return (
          <button
            key={`${f.fact_key}:${f.source}`}
            onClick={() => onSelect(f.fact_key)}
            data-testid={`fact-row-${f.fact_key}`}
            style={{
              display: 'block', width: '100%', textAlign: 'left',
              padding: '8px 10px',
              background: isSel ? 'var(--accent-dim)' : 'transparent',
              border: 'none',
              borderLeft: `3px solid ${hasConflict ? 'var(--red)' : isSel ? 'var(--accent)' : 'transparent'}`,
              borderBottom: '1px solid var(--border)',
              cursor: 'pointer',
              color: isSel ? 'var(--accent)' : 'var(--text-2)',
              fontFamily: 'var(--font-mono)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{
                width: 6, height: 6, borderRadius: '50%',
                background: tierColour(f.confidence ?? 0), flexShrink: 0,
              }} />
              <span style={{ fontSize: 10, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {f.fact_key}
              </span>
              {hasLock && <span title="locked" style={{ fontSize: 9, color: 'var(--amber)' }}>⚿</span>}
              {hasConflict && <span title="pending review" style={{ fontSize: 9, color: 'var(--red)' }}>⚠</span>}
            </div>
            <div style={{ fontSize: 8, color: 'var(--text-3)', marginTop: 2 }}>
              {(f.confidence ?? 0).toFixed(2)} · {freshnessLabel(f.last_verified)}
              {hasConflict && <span style={{ color: 'var(--red)', marginLeft: 8 }}>CONFLICT (pending admin)</span>}
            </div>
          </button>
        )
      })}
    </div>
  )
}

// ── Lock modal ───────────────────────────────────────────────────────────────

function FactLockModal({ fact, onClose, onLocked, canLock }) {
  const [value, setValue] = useState(() => {
    const first = (fact.sources || [])[0]
    if (!first) return ''
    try { return JSON.stringify(first.fact_value, null, 2) } catch { return String(first.fact_value) }
  })
  const [note, setNote] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    setErr(''); setBusy(true)
    let parsed
    try { parsed = JSON.parse(value) } catch { parsed = value }
    try {
      await factsFetch('/locks', {
        method: 'POST',
        body: JSON.stringify({ fact_key: fact.fact_key, locked_value: parsed, note }),
      })
      onLocked()
    } catch (e) {
      setErr(e.message || 'Failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200,
    }}>
      <div style={{ background: 'var(--bg-1)', border: '1px solid var(--accent)', padding: 20, width: 480, maxWidth: '90%' }}>
        <h3 style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-1)', margin: '0 0 10px' }}>
          Lock: <span style={{ color: 'var(--accent)' }}>{fact.fact_key}</span>
        </h3>
        {!canLock && (
          <div style={{ color: 'var(--amber)', fontSize: 10, marginBottom: 10 }}>
            Read-only: you do not have `lock` permission on this fact pattern.
          </div>
        )}
        <label style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>LOCKED VALUE (JSON or string)</label>
        <textarea
          value={value}
          onChange={e => setValue(e.target.value)}
          disabled={!canLock}
          rows={6}
          style={{ width: '100%', background: 'var(--bg-2)', color: 'var(--text-1)', border: '1px solid var(--border)', padding: 6, fontFamily: 'var(--font-mono)', fontSize: 10, marginTop: 4, marginBottom: 10 }}
        />
        <label style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>NOTE (optional)</label>
        <input
          value={note}
          onChange={e => setNote(e.target.value)}
          disabled={!canLock}
          style={{ width: '100%', background: 'var(--bg-2)', color: 'var(--text-1)', border: '1px solid var(--border)', padding: 6, fontFamily: 'var(--font-mono)', fontSize: 10, marginTop: 4 }}
        />
        {err && <div style={{ color: 'var(--red)', fontSize: 10, marginTop: 8 }}>{err}</div>}
        <div style={{ display: 'flex', gap: 8, marginTop: 12, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ padding: '4px 10px', background: 'none', border: '1px solid var(--border)', color: 'var(--text-2)', fontFamily: 'var(--font-mono)', fontSize: 10, cursor: 'pointer' }}>CANCEL</button>
          {canLock && (
            <button onClick={submit} disabled={busy} style={{ padding: '4px 10px', background: 'var(--accent)', border: 'none', color: '#fff', fontFamily: 'var(--font-mono)', fontSize: 10, cursor: 'pointer', opacity: busy ? 0.6 : 1 }}>
              {busy ? 'LOCKING…' : 'LOCK'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Conflict resolve modal ───────────────────────────────────────────────────

function ConflictResolveModal({ conflict, onClose, onResolved, canResolve }) {
  const [editing, setEditing] = useState(false)
  const [newValue, setNewValue] = useState(() => {
    try { return JSON.stringify(conflict.locked_value, null, 2) } catch { return '' }
  })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const submit = async (resolution) => {
    setErr(''); setBusy(true)
    try {
      const body = { resolution }
      if (resolution === 'edit_lock') {
        let parsed
        try { parsed = JSON.parse(newValue) } catch { parsed = newValue }
        body.new_value = parsed
      }
      await factsFetch(`/conflicts/${conflict.id}/resolve`, {
        method: 'POST', body: JSON.stringify(body),
      })
      onResolved()
    } catch (e) {
      setErr(e.message || 'Failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200,
    }}>
      <div style={{ background: 'var(--bg-1)', border: '1px solid var(--red)', padding: 20, width: 560, maxWidth: '90%' }}>
        <h3 style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--red)', margin: '0 0 10px' }}>
          Conflict: {conflict.fact_key}
        </h3>
        <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-2)' }}>
          <div>Locked value: <span style={{ color: 'var(--cyan)' }}>{JSON.stringify(conflict.locked_value)}</span></div>
          <div style={{ marginTop: 4 }}>Offered ({conflict.offered_source}): <span style={{ color: 'var(--amber)' }}>{JSON.stringify(conflict.offered_value)}</span></div>
        </div>
        {!canResolve && (
          <div style={{ color: 'var(--amber)', fontSize: 10, marginTop: 10 }}>
            Read-only: you do not have `unlock` permission on this fact pattern.
          </div>
        )}
        {editing && canResolve && (
          <textarea value={newValue} onChange={e => setNewValue(e.target.value)} rows={4}
            style={{ width: '100%', background: 'var(--bg-2)', color: 'var(--text-1)', border: '1px solid var(--border)', padding: 6, fontFamily: 'var(--font-mono)', fontSize: 10, marginTop: 10 }}
          />
        )}
        {err && <div style={{ color: 'var(--red)', fontSize: 10, marginTop: 8 }}>{err}</div>}
        <div style={{ display: 'flex', gap: 8, marginTop: 14, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ padding: '4px 10px', background: 'none', border: '1px solid var(--border)', color: 'var(--text-2)', fontFamily: 'var(--font-mono)', fontSize: 10, cursor: 'pointer' }}>CLOSE</button>
          {canResolve && (
            <>
              <button onClick={() => submit('keep_lock')} disabled={busy} style={{ padding: '4px 10px', background: 'var(--accent)', color: '#fff', border: 'none', fontFamily: 'var(--font-mono)', fontSize: 10, cursor: 'pointer' }}>KEEP LOCK</button>
              <button onClick={() => submit('accept_collector')} disabled={busy} style={{ padding: '4px 10px', background: 'var(--cyan)', color: '#000', border: 'none', fontFamily: 'var(--font-mono)', fontSize: 10, cursor: 'pointer' }}>ACCEPT COLLECTOR</button>
              {!editing && (
                <button onClick={() => setEditing(true)} style={{ padding: '4px 10px', background: 'var(--amber)', color: '#000', border: 'none', fontFamily: 'var(--font-mono)', fontSize: 10, cursor: 'pointer' }}>EDIT LOCK…</button>
              )}
              {editing && (
                <button onClick={() => submit('edit_lock')} disabled={busy} style={{ padding: '4px 10px', background: 'var(--amber)', color: '#000', border: 'none', fontFamily: 'var(--font-mono)', fontSize: 10, cursor: 'pointer' }}>SAVE NEW LOCK</button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Fact detail pane ────────────────────────────────────────────────────────

function FactDetail({ factKey, userRole, onChanged, conflictsForKey }) {
  const [data, setData]       = useState(null)
  const [err, setErr]         = useState('')
  const [loading, setLoading] = useState(false)
  const [showLock, setShowLock]         = useState(false)
  const [activeConflict, setActiveConflict] = useState(null)

  const isAdmin = userRole === 'sith_lord'

  const load = useCallback(async () => {
    if (!factKey) return
    setLoading(true); setErr('')
    try {
      const d = await factsFetch(`/key/${encodeURIComponent(factKey)}`)
      setData(d)
    } catch (e) { setErr(e.message || 'Failed to load') }
    finally { setLoading(false) }
  }, [factKey])

  useEffect(() => { load() }, [load])

  const refresh = async () => {
    try {
      await factsFetch(`/key/${encodeURIComponent(factKey)}/refresh`, { method: 'POST' })
      await load()
      onChanged?.()
    } catch (e) { setErr(e.message) }
  }

  const removeLock = async () => {
    try {
      await factsFetch(`/locks/${encodeURIComponent(factKey)}`, { method: 'DELETE' })
      await load()
      onChanged?.()
    } catch (e) { setErr(e.message) }
  }

  if (!factKey) {
    return <div style={{ padding: 20, fontSize: 10, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>Select a fact on the left.</div>
  }
  if (loading && !data) {
    return <div style={{ padding: 20, fontSize: 10, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>Loading…</div>
  }
  if (!data) {
    return <div style={{ padding: 20, fontSize: 10, color: 'var(--red)', fontFamily: 'var(--font-mono)' }}>{err || 'No data'}</div>
  }

  const { sources = [], history = [], lock } = data

  return (
    <div style={{ overflowY: 'auto', height: '100%', padding: 14, fontFamily: 'var(--font-mono)' }}>
      <div style={{ fontSize: 12, color: 'var(--accent)', wordBreak: 'break-all' }}>{factKey}</div>
      <div style={{ height: 1, background: 'var(--border)', margin: '8px 0 12px' }} />

      {err && <div style={{ color: 'var(--red)', fontSize: 10, marginBottom: 8 }}>{err}</div>}

      <div style={{ fontSize: 9, color: 'var(--text-3)', marginBottom: 6, letterSpacing: 1 }}>SOURCES ({sources.length})</div>
      {sources.map(s => (
        <div key={s.source} style={{ padding: 8, background: 'var(--bg-2)', border: '1px solid var(--border)', marginBottom: 6 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: tierColour(s.confidence ?? 0) }} />
            <span style={{ fontSize: 10, color: 'var(--text-1)' }}>{s.source}</span>
            <span style={{ fontSize: 9, color: 'var(--text-3)' }}>verified {freshnessLabel(s.last_verified)}</span>
            <span style={{ fontSize: 9, color: 'var(--text-3)', marginLeft: 'auto' }}>conf {(s.confidence ?? 0).toFixed(2)} · seen {s.verify_count}x</span>
          </div>
          <div style={{ fontSize: 10, color: 'var(--text-2)', marginTop: 4, wordBreak: 'break-all' }}>
            {JSON.stringify(s.fact_value)}
          </div>
        </div>
      ))}

      {/* Lock section */}
      <div style={{ fontSize: 9, color: 'var(--text-3)', margin: '14px 0 6px', letterSpacing: 1 }}>LOCK</div>
      {lock ? (
        <div style={{ padding: 8, background: 'var(--bg-2)', border: '1px solid var(--amber)', marginBottom: 6, fontSize: 10, color: 'var(--text-1)' }}>
          <div>Locked by <b>{lock.locked_by}</b> · {freshnessLabel(lock.locked_at)}</div>
          <div style={{ color: 'var(--text-2)', marginTop: 4 }}>{JSON.stringify(lock.locked_value)}</div>
          {lock.note && <div style={{ color: 'var(--text-3)', marginTop: 4 }}>Note: {lock.note}</div>}
          <div style={{ marginTop: 8 }}>
            <button onClick={removeLock} data-testid="remove-lock"
              style={{ padding: '3px 8px', fontSize: 9, background: 'none', border: '1px solid var(--border)', color: 'var(--text-2)', cursor: 'pointer' }}>
              REMOVE LOCK
            </button>
          </div>
        </div>
      ) : (
        <button
          onClick={() => setShowLock(true)}
          data-testid="lock-fact-btn"
          disabled={!isAdmin}
          title={isAdmin ? 'Create lock' : 'Sith Lord only (or with explicit lock permission)'}
          style={{
            padding: '4px 10px', fontSize: 10,
            background: isAdmin ? 'var(--accent)' : 'var(--bg-2)',
            color: isAdmin ? '#fff' : 'var(--text-3)',
            border: isAdmin ? 'none' : '1px solid var(--border)',
            cursor: isAdmin ? 'pointer' : 'not-allowed',
            fontFamily: 'var(--font-mono)', opacity: isAdmin ? 1 : 0.5,
          }}>
          LOCK THIS
        </button>
      )}

      {/* Manual refresh */}
      {sources.some(s => s.source === 'manual') && (
        <div style={{ marginTop: 10 }}>
          <button onClick={refresh} style={{ padding: '3px 8px', fontSize: 9, background: 'none', border: '1px solid var(--border)', color: 'var(--text-2)', cursor: 'pointer' }}>
            REFRESH MANUAL
          </button>
        </div>
      )}

      {/* Conflicts pending review for this key */}
      {conflictsForKey.length > 0 && (
        <>
          <div style={{ fontSize: 9, color: 'var(--red)', margin: '14px 0 6px', letterSpacing: 1 }}>PENDING REVIEWS ({conflictsForKey.length})</div>
          {conflictsForKey.map(c => (
            <div key={c.id} style={{ padding: 8, background: 'var(--bg-2)', borderLeft: '3px solid var(--red)', border: '1px solid var(--border)', marginBottom: 6 }}>
              <div style={{ fontSize: 10, color: 'var(--text-1)' }}>
                <b>{c.offered_source}</b> offered {JSON.stringify(c.offered_value)} — lock kept {JSON.stringify(c.locked_value)}
              </div>
              <div style={{ marginTop: 6 }}>
                <button onClick={() => setActiveConflict(c)}
                  style={{ padding: '3px 8px', fontSize: 9, background: 'var(--red)', border: 'none', color: '#fff', cursor: 'pointer' }}>
                  RESOLVE…
                </button>
              </div>
            </div>
          ))}
        </>
      )}

      {/* History */}
      <div style={{ fontSize: 9, color: 'var(--text-3)', margin: '14px 0 6px', letterSpacing: 1 }}>HISTORY ({history.length})</div>
      {history.length === 0 && <div style={{ fontSize: 10, color: 'var(--text-3)' }}>No prior changes recorded.</div>}
      {history.map(h => (
        <FactDiffViewer key={h.id}
          priorValue={h.prior_value} newValue={h.new_value}
          priorTimestamp={null} newTimestamp={h.changed_at}
          source={h.source} actor={h.changed_by}
        />
      ))}

      {showLock && (
        <FactLockModal
          fact={data}
          canLock={isAdmin}
          onClose={() => setShowLock(false)}
          onLocked={async () => { setShowLock(false); await load(); onChanged?.() }}
        />
      )}
      {activeConflict && (
        <ConflictResolveModal
          conflict={activeConflict}
          canResolve={isAdmin}
          onClose={() => setActiveConflict(null)}
          onResolved={async () => { setActiveConflict(null); await load(); onChanged?.() }}
        />
      )}
    </div>
  )
}

// ── Root ─────────────────────────────────────────────────────────────────────

export default function FactsView({ userRole = '' }) {
  const [facts, setFacts]       = useState([])
  const [conflicts, setConflicts] = useState([])
  const [locks, setLocks]       = useState([])
  const [selected, setSelected] = useState(null)
  const [pattern, setPattern]   = useState('')
  const [minConf, setMinConf]   = useState(0)
  const [changedOnly, setChangedOnly] = useState(false)
  const [err, setErr]           = useState('')

  const reload = useCallback(async () => {
    setErr('')
    try {
      const params = new URLSearchParams()
      if (pattern) params.set('pattern', pattern)
      if (minConf) params.set('min_confidence', String(minConf))
      params.set('max_rows', '500')
      const data = await factsFetch(`?${params.toString()}`)
      let rows = data.facts || []
      if (changedOnly) {
        rows = rows.filter(f => f.change_detected)
      }
      setFacts(rows)

      const [cf, lk] = await Promise.all([
        factsFetch('/conflicts').catch(() => ({ conflicts: [] })),
        factsFetch('/locks').catch(() => ({ locks: [] })),
      ])
      setConflicts(cf.conflicts || [])
      setLocks(lk.locks || [])
    } catch (e) {
      setErr(e.message || 'Failed to load facts')
    }
  }, [pattern, minConf, changedOnly])

  // Initial + periodic reload
  useEffect(() => { reload() }, [reload])
  useEffect(() => {
    const id = setInterval(() => reload(), 30000)
    return () => clearInterval(id)
  }, [reload])

  // Deep-link support
  useEffect(() => {
    const applyHash = () => {
      const m = window.location.hash.match(/^#\/facts\/(.+)$/)
      if (m) setSelected(decodeURIComponent(m[1]))
    }
    applyHash()
    window.addEventListener('hashchange', applyHash)
    return () => window.removeEventListener('hashchange', applyHash)
  }, [])

  const conflictKeys = useMemo(() => new Set(conflicts.map(c => c.fact_key)), [conflicts])
  const lockKeys     = useMemo(() => new Set(locks.map(l => l.fact_key)), [locks])
  const conflictsForSelected = useMemo(
    () => conflicts.filter(c => c.fact_key === selected),
    [conflicts, selected]
  )

  // De-dup facts by fact_key for list view (show best row per key)
  const displayRows = useMemo(() => {
    const byKey = new Map()
    for (const f of facts) {
      const cur = byKey.get(f.fact_key)
      if (!cur || (f.confidence ?? 0) > (cur.confidence ?? 0)) byKey.set(f.fact_key, f)
    }
    return Array.from(byKey.values()).sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0))
  }, [facts])

  return (
    <div data-testid="facts-view" style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-0)' }}>
      {/* Toolbar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '10px 14px', borderBottom: '1px solid var(--border)',
        fontFamily: 'var(--font-mono)', fontSize: 10,
      }}>
        <input
          placeholder="Search: prod.kafka.*"
          value={pattern}
          onChange={e => setPattern(e.target.value)}
          data-testid="facts-search"
          style={{ flex: 1, background: 'var(--bg-2)', color: 'var(--text-1)', border: '1px solid var(--border)', padding: 6, fontFamily: 'var(--font-mono)', fontSize: 10 }}
        />
        <label style={{ color: 'var(--text-3)', display: 'flex', alignItems: 'center', gap: 6 }}>
          Min confidence:
          <select value={minConf} onChange={e => setMinConf(Number(e.target.value))}
            style={{ background: 'var(--bg-2)', color: 'var(--text-1)', border: '1px solid var(--border)', padding: 3, fontSize: 10 }}>
            <option value={0}>0.0</option>
            <option value={0.5}>≥0.5</option>
            <option value={0.7}>≥0.7</option>
            <option value={0.9}>≥0.9</option>
          </select>
        </label>
        <label style={{ color: 'var(--text-3)', display: 'flex', alignItems: 'center', gap: 6 }}>
          <input type="checkbox" checked={changedOnly} onChange={e => setChangedOnly(e.target.checked)} />
          Changed recently
        </label>
        <button onClick={reload} style={{ padding: '4px 10px', background: 'none', border: '1px solid var(--border)', color: 'var(--text-2)', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: 10 }}>
          ↻
        </button>
      </div>
      {conflicts.length > 0 && (
        <div data-testid="conflict-banner" style={{
          padding: '4px 14px', background: 'rgba(160,24,40,0.15)', color: 'var(--red)',
          fontFamily: 'var(--font-mono)', fontSize: 10, borderBottom: '1px solid var(--border)',
        }}>
          ⚠ {conflicts.length} pending conflict{conflicts.length === 1 ? '' : 's'} require admin review.
        </div>
      )}
      {err && <div style={{ padding: 8, color: 'var(--red)', fontSize: 10, fontFamily: 'var(--font-mono)' }}>{err}</div>}

      {/* Body */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <div style={{ width: 380, borderRight: '1px solid var(--border)', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          <FactList
            facts={displayRows}
            selected={selected}
            onSelect={setSelected}
            conflictKeys={conflictKeys}
            lockKeys={lockKeys}
          />
        </div>
        <div style={{ flex: 1, overflow: 'hidden' }}>
          <FactDetail
            factKey={selected}
            userRole={userRole}
            onChanged={reload}
            conflictsForKey={conflictsForSelected}
          />
        </div>
      </div>
    </div>
  )
}
