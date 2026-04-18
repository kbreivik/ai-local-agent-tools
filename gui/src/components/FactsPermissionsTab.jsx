// FactsPermissionsTab — v2.35.0.1 Settings tab.
// Admin-only UI to list / grant / revoke fact-admin permissions.
// Fetches /api/facts/permissions and mutates via POST / DELETE.
//
// Backend gates mutations behind require_role('sith_lord'); this UI also
// hides itself for non-admins via the userRole prop.

import { useEffect, useState } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

const ACTIONS = ['lock', 'unlock', 'manual_write', 'grant', 'config_refresh_schedule']

async function req(path, opts = {}) {
  const r = await fetch(`${BASE}/api/facts${path}`, {
    headers: { 'Content-Type': 'application/json', ...authHeaders() }, ...opts,
  })
  const text = await r.text()
  let body
  try { body = text ? JSON.parse(text) : null } catch { body = text }
  if (!r.ok) {
    const msg = (body && body.detail) || r.statusText || 'Request failed'
    const err = new Error(msg); err.status = r.status; throw err
  }
  return body
}

export default function FactsPermissionsTab({ userRole = '' }) {
  const isAdmin = userRole === 'sith_lord'
  const [perms, setPerms] = useState([])
  const [err, setErr]     = useState('')

  const [granteeType,  setGranteeType]  = useState('user')
  const [granteeId,    setGranteeId]    = useState('')
  const [action,       setAction]       = useState('lock')
  const [factPattern,  setFactPattern]  = useState('prod.*')
  const [expiresAt,    setExpiresAt]    = useState('')
  const [busy,         setBusy]         = useState(false)

  const load = async () => {
    try {
      const d = await req('/permissions')
      setPerms(d.permissions || [])
      setErr('')
    } catch (e) {
      setErr(e.message || 'Failed to load')
    }
  }

  useEffect(() => { load() }, [])

  const grant = async (e) => {
    e.preventDefault()
    if (!granteeId || !factPattern) return
    setBusy(true); setErr('')
    try {
      await req('/permissions', {
        method: 'POST',
        body: JSON.stringify({
          grantee_type: granteeType,
          grantee_id: granteeId,
          action,
          fact_pattern: factPattern,
          expires_at: expiresAt || null,
        }),
      })
      setGranteeId('')
      await load()
    } catch (ex) { setErr(ex.message || 'Failed to grant') }
    finally { setBusy(false) }
  }

  const revoke = async (id) => {
    try {
      await req(`/permissions/${id}`, { method: 'DELETE' })
      await load()
    } catch (e) { setErr(e.message || 'Failed to revoke') }
  }

  if (!isAdmin) {
    return (
      <div style={{ padding: 16, fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-3)' }}>
        Only sith_lord users may manage fact permissions.
      </div>
    )
  }

  return (
    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-2)' }}>
      <h2 style={{ fontSize: 12, color: 'var(--text-1)', marginBottom: 8 }}>Facts Permissions</h2>
      <p style={{ color: 'var(--text-3)', marginBottom: 12 }}>
        Grant specific users or roles the ability to lock, unlock, or manually
        edit facts matching a pattern. Pattern wildcards use <code>*</code>.
      </p>

      {err && <div style={{ color: 'var(--red)', marginBottom: 10 }}>{err}</div>}

      {/* Grant form */}
      <form onSubmit={grant} style={{
        display: 'grid', gridTemplateColumns: 'repeat(6, 1fr) auto', gap: 6,
        alignItems: 'end', marginBottom: 14,
      }}>
        <div>
          <div style={{ fontSize: 9, color: 'var(--text-3)' }}>Grantee type</div>
          <select value={granteeType} onChange={e => setGranteeType(e.target.value)}
            style={inputStyle}>
            <option value="user">user</option>
            <option value="role">role</option>
          </select>
        </div>
        <div>
          <div style={{ fontSize: 9, color: 'var(--text-3)' }}>Grantee id</div>
          <input value={granteeId} onChange={e => setGranteeId(e.target.value)}
            placeholder={granteeType === 'user' ? 'username' : 'role name'}
            style={inputStyle} />
        </div>
        <div>
          <div style={{ fontSize: 9, color: 'var(--text-3)' }}>Action</div>
          <select value={action} onChange={e => setAction(e.target.value)} style={inputStyle}>
            {ACTIONS.map(a => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
        <div style={{ gridColumn: 'span 2' }}>
          <div style={{ fontSize: 9, color: 'var(--text-3)' }}>Fact pattern</div>
          <input value={factPattern} onChange={e => setFactPattern(e.target.value)}
            placeholder="prod.kafka.*" style={inputStyle} />
        </div>
        <div>
          <div style={{ fontSize: 9, color: 'var(--text-3)' }}>Expires (ISO, optional)</div>
          <input value={expiresAt} onChange={e => setExpiresAt(e.target.value)}
            placeholder="2026-12-31T00:00:00Z" style={inputStyle} />
        </div>
        <button type="submit" disabled={busy}
          style={{ padding: '6px 14px', background: 'var(--accent)', color: '#fff',
                   border: 'none', cursor: 'pointer', fontFamily: 'var(--font-mono)',
                   fontSize: 10, opacity: busy ? 0.6 : 1 }}>
          GRANT
        </button>
      </form>

      {/* Existing permissions */}
      <div style={{ border: '1px solid var(--border)' }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: '60px 80px 150px 120px 200px 160px 60px',
          gap: 0, padding: '6px 8px', background: 'var(--bg-2)',
          fontSize: 9, color: 'var(--text-3)', letterSpacing: 1,
        }}>
          <div>ID</div><div>TYPE</div><div>GRANTEE</div><div>ACTION</div>
          <div>FACT PATTERN</div><div>EXPIRES</div><div></div>
        </div>
        {perms.length === 0 && (
          <div style={{ padding: 10, color: 'var(--text-3)' }}>No permissions granted yet.</div>
        )}
        {perms.map(p => (
          <div key={p.id} style={{
            display: 'grid',
            gridTemplateColumns: '60px 80px 150px 120px 200px 160px 60px',
            gap: 0, padding: '6px 8px', borderTop: '1px solid var(--border)',
            opacity: p.revoked ? 0.4 : 1, alignItems: 'center',
          }}>
            <div>{p.id}</div>
            <div>{p.grantee_type}</div>
            <div style={{ color: 'var(--text-1)' }}>{p.grantee_id}</div>
            <div style={{ color: 'var(--cyan)' }}>{p.action}</div>
            <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--amber)' }}>{p.fact_pattern}</div>
            <div style={{ fontSize: 9, color: 'var(--text-3)' }}>{p.expires_at || 'never'}</div>
            <div>
              {!p.revoked && (
                <button onClick={() => revoke(p.id)}
                  style={{ padding: '2px 6px', fontSize: 9, background: 'none',
                           border: '1px solid var(--red)', color: 'var(--red)',
                           cursor: 'pointer' }}>
                  REVOKE
                </button>
              )}
              {p.revoked && <span style={{ color: 'var(--text-3)' }}>revoked</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

const inputStyle = {
  width: '100%', background: 'var(--bg-2)', color: 'var(--text-1)',
  border: '1px solid var(--border)', padding: 5,
  fontFamily: 'var(--font-mono)', fontSize: 10,
}
