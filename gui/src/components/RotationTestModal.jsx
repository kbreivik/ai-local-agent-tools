/**
 * RotationTestModal — tests new profile credentials against all linked connections
 * before saving. Shows per-connection pass/fail, supports role-gated override.
 */
import { useState, useEffect } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

const RESULT_COLORS = {
  pending:  { color: 'var(--text-3)', icon: '○' },
  running:  { color: 'var(--amber)',   icon: '◌' },
  ok:       { color: 'var(--green)',   icon: '✓' },
  fail:     { color: 'var(--red)',     icon: '✕' },
}

export default function RotationTestModal({
  profileId,
  profileName,
  newCredentials,
  userRole,          // 'sith_lord' | 'imperial_officer' | 'stormtrooper' | 'droid'
  onConfirmed,       // called on successful save (profiles should refresh)
  onCancel,
}) {
  const [phase, setPhase] = useState('testing')   // testing | results | saving | done | error
  const [results, setResults] = useState([])
  const [allOk, setAllOk] = useState(false)
  const [overrideReason, setOverrideReason] = useState('')
  const [overrideError, setOverrideError] = useState('')
  const [saving, setSaving] = useState(false)
  const [errorMsg, setErrorMsg] = useState('')

  const canOverride = userRole === 'sith_lord' || userRole === 'imperial_officer'
  const needsReason = userRole === 'imperial_officer'

  useEffect(() => {
    _runTest()
  }, [])

  const _runTest = async () => {
    setPhase('testing')
    setResults([])
    setErrorMsg('')
    try {
      const r = await fetch(`${BASE}/api/credential-profiles/${profileId}/test-rotation`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ new_credentials: newCredentials }),
      })
      const d = await r.json()
      if (!r.ok) {
        setPhase('error')
        setErrorMsg(d.detail || d.message || 'Test failed')
        return
      }
      if (d.results?.length === 0) {
        // No linked connections — save immediately
        await _confirm(false, '', [])
        return
      }
      setResults(d.results || [])
      setAllOk(d.all_ok || false)
      setPhase('results')
    } catch (e) {
      setPhase('error')
      setErrorMsg(e.message)
    }
  }

  const _confirm = async (override, reason, testResults) => {
    setSaving(true)
    try {
      const r = await fetch(`${BASE}/api/credential-profiles/${profileId}/confirm-rotation`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          new_credentials:  newCredentials,
          override:         override,
          override_reason:  reason,
          test_results:     testResults,
        }),
      })
      const d = await r.json()
      if (!r.ok) {
        setOverrideError(d.detail || d.message || 'Save failed')
        setSaving(false)
        return
      }
      setPhase('done')
      setTimeout(() => onConfirmed?.(), 800)
    } catch (e) {
      setOverrideError(e.message)
      setSaving(false)
    }
  }

  const handleSaveAnyway = async () => {
    if (needsReason && !overrideReason.trim()) {
      setOverrideError('Please provide a reason for this override')
      return
    }
    setOverrideError('')
    await _confirm(true, overrideReason, results)
  }

  const passCount = results.filter(r => r.ok).length
  const failCount = results.filter(r => !r.ok).length

  return (
    <>
      {/* Backdrop */}
      <div style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
        zIndex: 200, display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <div style={{
          background: 'var(--bg-1)', border: '1px solid var(--border)',
          borderRadius: 4, width: 520, maxHeight: '80vh',
          display: 'flex', flexDirection: 'column',
          boxShadow: '0 8px 32px rgba(0,0,0,0.6)',
        }}>
          {/* Header */}
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '12px 16px', borderBottom: '1px solid var(--border)',
          }}>
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-1)', fontFamily: 'var(--font-mono)', letterSpacing: 0.5 }}>
                CREDENTIAL ROTATION TEST
              </div>
              <div style={{ fontSize: 9, color: 'var(--text-3)', marginTop: 2 }}>
                {profileName} — testing new credentials against linked connections
              </div>
            </div>
            {phase !== 'testing' && phase !== 'saving' && (
              <button onClick={onCancel}
                style={{ background: 'none', border: 'none', color: 'var(--text-3)', fontSize: 14, cursor: 'pointer' }}>
                ✕
              </button>
            )}
          </div>

          {/* Body */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px' }}>

            {/* Testing phase */}
            {phase === 'testing' && (
              <div style={{ textAlign: 'center', padding: '24px 0' }}>
                <div style={{ fontSize: 24, marginBottom: 8, animation: 'spin 1s linear infinite',
                  display: 'inline-block' }}>◌</div>
                <div style={{ fontSize: 11, color: 'var(--text-2)' }}>Testing credentials against all linked connections…</div>
                <style>{`@keyframes spin { from { transform: rotate(0deg) } to { transform: rotate(360deg) } }`}</style>
              </div>
            )}

            {/* Results phase */}
            {(phase === 'results' || phase === 'saving') && (<>
              {/* Summary bar */}
              <div style={{ display: 'flex', gap: 16, marginBottom: 10, fontSize: 10,
                fontFamily: 'var(--font-mono)', padding: '6px 10px', borderRadius: 2,
                background: allOk ? 'rgba(0,170,68,0.08)' : 'rgba(204,40,40,0.08)',
                border: `1px solid ${allOk ? 'var(--green)' : 'var(--red)'}` }}>
                <span style={{ color: 'var(--green)' }}>✓ {passCount} passed</span>
                {failCount > 0 && <span style={{ color: 'var(--red)' }}>✕ {failCount} failed</span>}
                <span style={{ color: 'var(--text-3)', marginLeft: 'auto' }}>
                  {results.length} connection{results.length !== 1 ? 's' : ''} tested
                </span>
              </div>

              {/* Per-connection results */}
              <div style={{ border: '1px solid var(--border)', borderRadius: 2, overflow: 'hidden', marginBottom: 12 }}>
                {results.map((r, i) => {
                  const s = r.ok ? RESULT_COLORS.ok : RESULT_COLORS.fail
                  return (
                    <div key={r.conn_id || i} style={{
                      display: 'flex', alignItems: 'center', gap: 8,
                      padding: '5px 10px', fontSize: 10,
                      borderBottom: i < results.length - 1 ? '1px solid var(--bg-3)' : 'none',
                      background: i % 2 ? 'var(--bg-2)' : 'var(--bg-1)',
                    }}>
                      <span style={{ color: s.color, fontSize: 11, flexShrink: 0 }}>{s.icon}</span>
                      <span style={{ color: 'var(--text-1)', fontWeight: 500, minWidth: 140 }}>{r.label}</span>
                      <span style={{ color: 'var(--text-3)', fontFamily: 'var(--font-mono)', fontSize: 9 }}>{r.host}</span>
                      <span style={{ color: r.ok ? 'var(--green)' : 'var(--red)', marginLeft: 'auto', fontSize: 9 }}>
                        {r.message || (r.ok ? 'OK' : 'Failed')}
                      </span>
                      {r.duration_ms != null && (
                        <span style={{ color: 'var(--text-3)', fontSize: 9, flexShrink: 0 }}>{r.duration_ms}ms</span>
                      )}
                    </div>
                  )
                })}
              </div>

              {/* Override section — only shown on failures */}
              {!allOk && (<>
                <div style={{ borderTop: '1px solid var(--border)', paddingTop: 10, marginTop: 4 }}>
                  {canOverride ? (<>
                    <div style={{ fontSize: 9, color: 'var(--amber)', marginBottom: 8, padding: '4px 8px',
                      border: '1px solid var(--amber)', borderRadius: 2, background: 'rgba(204,136,0,0.08)' }}>
                      ⚠ {failCount} connection{failCount !== 1 ? 's' : ''} failed. Saving anyway will be logged
                      {userRole === 'sith_lord' ? ' — admin override.' : ' — provide a reason.'}
                    </div>

                    {needsReason && (
                      <div style={{ marginBottom: 8 }}>
                        <label style={{ fontSize: 9, color: 'var(--text-2)', display: 'block', marginBottom: 3 }}>
                          Override reason (required)
                        </label>
                        <textarea
                          value={overrideReason}
                          onChange={e => setOverrideReason(e.target.value)}
                          rows={2}
                          placeholder="e.g. Device temporarily offline — credentials verified manually"
                          style={{
                            width: '100%', background: 'var(--bg-2)', border: '1px solid var(--border)',
                            borderRadius: 2, padding: '4px 8px', fontSize: 9, color: 'var(--text-1)',
                            resize: 'none', outline: 'none', fontFamily: 'var(--font-sans)',
                          }}
                        />
                      </div>
                    )}

                    {overrideError && (
                      <div style={{ fontSize: 9, color: 'var(--red)', marginBottom: 6 }}>{overrideError}</div>
                    )}
                  </>) : (
                    <div style={{ fontSize: 10, color: 'var(--text-3)', padding: '8px',
                      border: '1px solid var(--border)', borderRadius: 2 }}>
                      Credential save requires all tests to pass, or an imperial_officer / sith_lord override.
                      Contact your administrator to proceed.
                    </div>
                  )}
                </div>
              </>)}
            </>)}

            {/* Error phase */}
            {phase === 'error' && (
              <div style={{ color: 'var(--red)', fontSize: 10, padding: '12px 0' }}>
                Test failed: {errorMsg}
              </div>
            )}

            {/* Done phase */}
            {phase === 'done' && (
              <div style={{ textAlign: 'center', padding: '16px 0', color: 'var(--green)', fontSize: 12 }}>
                ✓ Credentials saved successfully
              </div>
            )}
          </div>

          {/* Footer */}
          {phase !== 'testing' && phase !== 'done' && (
            <div style={{
              display: 'flex', gap: 8, padding: '10px 16px',
              borderTop: '1px solid var(--border)', justifyContent: 'flex-end',
            }}>
              {phase !== 'saving' && (
                <button onClick={onCancel} disabled={saving}
                  style={{ fontSize: 10, padding: '4px 14px', borderRadius: 2, cursor: 'pointer',
                    background: 'var(--bg-3)', border: '1px solid var(--border)', color: 'var(--text-2)' }}>
                  Cancel
                </button>
              )}
              {allOk && phase === 'results' && (
                <button onClick={() => _confirm(false, '', results)} disabled={saving}
                  style={{ fontSize: 10, padding: '4px 14px', borderRadius: 2, cursor: 'pointer',
                    background: 'var(--green)', border: 'none', color: '#fff', fontWeight: 600, opacity: saving ? 0.6 : 1 }}>
                  {saving ? 'Saving…' : '✓ Save credentials'}
                </button>
              )}
              {!allOk && canOverride && phase === 'results' && (
                <button onClick={handleSaveAnyway} disabled={saving}
                  style={{ fontSize: 10, padding: '4px 14px', borderRadius: 2, cursor: 'pointer',
                    background: 'var(--amber)', border: 'none', color: '#fff', fontWeight: 600, opacity: saving ? 0.6 : 1 }}>
                  {saving ? 'Saving…' : '⚠ Save anyway (override)'}
                </button>
              )}
              {phase === 'error' && (
                <button onClick={_runTest}
                  style={{ fontSize: 10, padding: '4px 14px', borderRadius: 2, cursor: 'pointer',
                    background: 'var(--bg-3)', border: '1px solid var(--border)', color: 'var(--text-2)' }}>
                  Retry test
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  )
}
