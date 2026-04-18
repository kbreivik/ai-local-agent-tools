/**
 * RunbooksPanel — browse, search, and edit runbooks.
 * Shown as a sidebar tab under MONITOR → Runbooks.
 *
 * v2.35.4: adds an editor modal for triage-classifier runbooks:
 *   title, body_md, triage_keywords, applies_to_agent_types, priority,
 *   is_active — plus a Test Match tool that runs the classifier against
 *   an arbitrary task string. Writes require sith_lord role (server-enforced).
 */
import { useState, useEffect, useCallback } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

const SOURCE_BADGE = {
  manual_completion: { label: 'manual', color: '#22c55e' },
  agent_proposed:    { label: 'agent',  color: '#00c8ee' },
  user_created:      { label: 'user',   color: '#a855f7' },
  triage_seed:       { label: 'triage', color: '#cc8800' },
  system_base:       { label: 'base',   color: '#64748b' },
}

const AGENT_TYPE_CHOICES = ['research', 'investigate', 'status', 'observe', 'action', 'execute', 'build']

function chipList(arr, onRemove) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
      {(arr || []).map((t, i) => (
        <span key={i} style={{
          fontSize: 10, padding: '2px 6px', borderRadius: 2,
          background: 'var(--bg-2)', color: 'var(--text-2)',
          fontFamily: 'var(--font-mono)', display: 'flex',
          alignItems: 'center', gap: 4,
        }}>
          {t}
          {onRemove && (
            <button
              onClick={() => onRemove(i)}
              style={{ background: 'none', border: 'none',
                       color: 'var(--red)', cursor: 'pointer',
                       fontSize: 10, padding: 0 }}>×</button>
          )}
        </span>
      ))}
    </div>
  )
}

function EditModal({ runbook, onClose, onSaved }) {
  const [form, setForm] = useState({
    title:                  runbook.title || '',
    body_md:                runbook.body_md || '',
    priority:               runbook.priority ?? 100,
    is_active:              runbook.is_active ?? true,
    triage_keywords:        runbook.triage_keywords || [],
    applies_to_agent_types: runbook.applies_to_agent_types || [],
  })
  const [kwInput, setKwInput] = useState('')
  const [saving,  setSaving]  = useState(false)
  const [error,   setError]   = useState('')
  const [preview, setPreview] = useState(false)
  const [testTask, setTestTask] = useState('')
  const [testResult, setTestResult] = useState(null)

  const addKw = () => {
    const v = kwInput.trim()
    if (v && !form.triage_keywords.includes(v)) {
      setForm({ ...form, triage_keywords: [...form.triage_keywords, v] })
    }
    setKwInput('')
  }

  const toggleAgentType = (t) => {
    const cur = form.applies_to_agent_types
    setForm({
      ...form,
      applies_to_agent_types: cur.includes(t)
        ? cur.filter(x => x !== t)
        : [...cur, t],
    })
  }

  const save = async () => {
    setSaving(true); setError('')
    try {
      const res = await fetch(`${BASE}/api/runbooks/${runbook.id}`, {
        method: 'PUT',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title:                  form.title,
          body_md:                form.body_md,
          priority:               Number(form.priority),
          is_active:              !!form.is_active,
          triage_keywords:        form.triage_keywords,
          applies_to_agent_types: form.applies_to_agent_types,
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      const data = await res.json()
      onSaved(data.runbook)
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setSaving(false)
    }
  }

  const runTestMatch = async () => {
    setTestResult(null)
    try {
      const res = await fetch(`${BASE}/api/runbooks/triage/test-match`, {
        method: 'POST',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task: testTask,
          agent_type: form.applies_to_agent_types[0] || 'research',
        }),
      })
      const data = await res.json()
      setTestResult(data.match || { none: true })
    } catch (e) {
      setTestResult({ error: String(e) })
    }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)',
                  zIndex: 1000, display: 'flex', alignItems: 'center',
                  justifyContent: 'center', padding: 20 }}>
      <div style={{ background: 'var(--bg-1)', border: '1px solid var(--border)',
                    borderRadius: 3, width: '90%', maxWidth: 820,
                    maxHeight: '90vh', overflowY: 'auto', padding: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 14 }}>
          <span style={{ fontSize: 11, letterSpacing: 1, color: 'var(--text-2)',
                         fontFamily: 'var(--font-mono)', flex: 1 }}>
            EDIT RUNBOOK — {runbook.name || runbook.id?.slice(0, 8)}
          </span>
          <button onClick={onClose}
            style={{ background: 'none', border: 'none', color: 'var(--text-2)',
                     fontSize: 16, cursor: 'pointer' }}>×</button>
        </div>

        {error && (
          <div style={{ background: 'var(--accent-dim)', color: 'var(--red)',
                        padding: '6px 10px', borderRadius: 2, fontSize: 10,
                        marginBottom: 10 }}>
            {error}
          </div>
        )}

        <label style={{ fontSize: 10, color: 'var(--text-3)',
                       fontFamily: 'var(--font-mono)' }}>TITLE</label>
        <input
          value={form.title}
          onChange={e => setForm({ ...form, title: e.target.value })}
          style={{ width: '100%', padding: 6, fontSize: 12,
                   background: 'var(--bg-2)', border: '1px solid var(--border)',
                   color: 'var(--text-1)', borderRadius: 2, marginBottom: 10 }}
        />

        <label style={{ fontSize: 10, color: 'var(--text-3)',
                       fontFamily: 'var(--font-mono)' }}>
          BODY (markdown)
          <button
            onClick={() => setPreview(!preview)}
            style={{ marginLeft: 10, fontSize: 9, padding: '1px 6px',
                     border: '1px solid var(--border)', borderRadius: 2,
                     background: 'transparent', color: 'var(--text-2)',
                     cursor: 'pointer', fontFamily: 'var(--font-mono)' }}>
            {preview ? 'edit' : 'preview'}
          </button>
        </label>
        {preview ? (
          <pre style={{ width: '100%', minHeight: 180, padding: 8,
                        background: 'var(--bg-2)', border: '1px solid var(--border)',
                        color: 'var(--text-1)', borderRadius: 2, marginBottom: 10,
                        fontFamily: 'var(--font-mono)', fontSize: 10,
                        whiteSpace: 'pre-wrap' }}>
            {form.body_md}
          </pre>
        ) : (
          <textarea
            value={form.body_md}
            onChange={e => setForm({ ...form, body_md: e.target.value })}
            style={{ width: '100%', minHeight: 180, padding: 8, fontSize: 10,
                     background: 'var(--bg-2)', border: '1px solid var(--border)',
                     color: 'var(--text-1)', borderRadius: 2, marginBottom: 10,
                     fontFamily: 'var(--font-mono)', resize: 'vertical' }}
          />
        )}

        <div style={{ display: 'flex', gap: 20, marginBottom: 10 }}>
          <div style={{ flex: 1 }}>
            <label style={{ fontSize: 10, color: 'var(--text-3)',
                           fontFamily: 'var(--font-mono)' }}>PRIORITY (0-999, lower wins)</label>
            <input
              type="number" min={0} max={999}
              value={form.priority}
              onChange={e => setForm({ ...form, priority: e.target.value })}
              style={{ width: '100%', padding: 6, fontSize: 11,
                       background: 'var(--bg-2)', border: '1px solid var(--border)',
                       color: 'var(--text-1)', borderRadius: 2 }}
            />
          </div>
          <div style={{ flex: 1, display: 'flex', alignItems: 'flex-end' }}>
            <label style={{ fontSize: 11, color: 'var(--text-1)',
                           display: 'flex', alignItems: 'center', gap: 6 }}>
              <input type="checkbox"
                checked={form.is_active}
                onChange={e => setForm({ ...form, is_active: e.target.checked })} />
              Active (eligible for injection)
            </label>
          </div>
        </div>

        <label style={{ fontSize: 10, color: 'var(--text-3)',
                       fontFamily: 'var(--font-mono)' }}>TRIAGE KEYWORDS</label>
        {chipList(form.triage_keywords,
          (i) => setForm({
            ...form,
            triage_keywords: form.triage_keywords.filter((_, idx) => idx !== i),
          })
        )}
        <div style={{ display: 'flex', gap: 6, marginTop: 6, marginBottom: 10 }}>
          <input
            value={kwInput}
            onChange={e => setKwInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addKw() } }}
            placeholder="type and Enter"
            style={{ flex: 1, padding: 5, fontSize: 10,
                     background: 'var(--bg-2)', border: '1px solid var(--border)',
                     color: 'var(--text-1)', borderRadius: 2,
                     fontFamily: 'var(--font-mono)' }}
          />
          <button onClick={addKw}
            style={{ fontSize: 10, padding: '3px 8px',
                     border: '1px solid var(--border)', borderRadius: 2,
                     background: 'transparent', color: 'var(--text-2)',
                     cursor: 'pointer', fontFamily: 'var(--font-mono)' }}>
            add
          </button>
        </div>

        <label style={{ fontSize: 10, color: 'var(--text-3)',
                       fontFamily: 'var(--font-mono)' }}>APPLIES TO AGENT TYPES</label>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '6px 0 12px' }}>
          {AGENT_TYPE_CHOICES.map(t => {
            const on = form.applies_to_agent_types.includes(t)
            return (
              <button key={t} onClick={() => toggleAgentType(t)}
                style={{ fontSize: 10, padding: '2px 8px',
                         border: '1px solid ' + (on ? 'var(--cyan)' : 'var(--border)'),
                         color: on ? 'var(--cyan)' : 'var(--text-3)',
                         borderRadius: 2, background: 'transparent', cursor: 'pointer',
                         fontFamily: 'var(--font-mono)' }}>
                {t}
              </button>
            )
          })}
        </div>

        {/* Test match */}
        <div style={{ marginTop: 8, padding: 10, border: '1px dashed var(--border)',
                      borderRadius: 2 }}>
          <div style={{ fontSize: 10, color: 'var(--text-3)',
                        fontFamily: 'var(--font-mono)', marginBottom: 6 }}>
            TEST MATCH — would the classifier pick THIS runbook?
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <input
              value={testTask}
              onChange={e => setTestTask(e.target.value)}
              placeholder="e.g. investigate kafka consumer lag"
              style={{ flex: 1, padding: 5, fontSize: 10,
                       background: 'var(--bg-2)', border: '1px solid var(--border)',
                       color: 'var(--text-1)', borderRadius: 2,
                       fontFamily: 'var(--font-mono)' }}
            />
            <button onClick={runTestMatch}
              style={{ fontSize: 10, padding: '3px 10px',
                       border: '1px solid var(--border)', borderRadius: 2,
                       background: 'transparent', color: 'var(--text-2)',
                       cursor: 'pointer', fontFamily: 'var(--font-mono)' }}>
              run
            </button>
          </div>
          {testResult && (
            <div style={{ marginTop: 6, fontSize: 10, color: 'var(--text-2)',
                          fontFamily: 'var(--font-mono)' }}>
              {testResult.none ? 'no match' :
               testResult.error ? 'error: ' + testResult.error :
               (
                 <div>
                   matched: <span style={{
                     color: testResult.runbook_name === runbook.name ? 'var(--green)' : 'var(--amber)',
                   }}>{testResult.runbook_name}</span>
                   {' '}score={testResult.score} kw=[{(testResult.matched_keywords || []).join(', ')}]
                   {testResult.runbook_name !== runbook.name && (
                     <div style={{ color: 'var(--amber)', marginTop: 3 }}>
                       Another runbook wins. Edit keywords/priority if this runbook should match.
                     </div>
                   )}
                 </div>
               )}
            </div>
          )}
        </div>

        {(runbook.last_edited_by || runbook.last_edited_at) && (
          <div style={{ marginTop: 10, fontSize: 9, color: 'var(--text-3)',
                        fontFamily: 'var(--font-mono)' }}>
            last edited by {runbook.last_edited_by || 'n/a'}
            {runbook.last_edited_at ? ' at ' + runbook.last_edited_at : ''}
          </div>
        )}

        <div style={{ marginTop: 14, display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button onClick={onClose}
            style={{ fontSize: 11, padding: '5px 12px',
                     border: '1px solid var(--border)', borderRadius: 2,
                     background: 'transparent', color: 'var(--text-2)',
                     cursor: 'pointer', fontFamily: 'var(--font-mono)' }}>
            cancel
          </button>
          <button onClick={save} disabled={saving}
            style={{ fontSize: 11, padding: '5px 14px',
                     border: '1px solid var(--accent)', borderRadius: 2,
                     background: 'var(--accent-dim)', color: 'var(--text-1)',
                     cursor: saving ? 'wait' : 'pointer',
                     fontFamily: 'var(--font-mono)' }}>
            {saving ? 'saving…' : 'save'}
          </button>
        </div>
      </div>
    </div>
  )
}


export default function RunbooksPanel() {
  const [runbooks, setRunbooks] = useState([])
  const [query, setQuery]       = useState('')
  const [loading, setLoading]   = useState(true)
  const [expanded, setExpanded] = useState(null)
  const [editing,  setEditing]  = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    fetch(`${BASE}/api/runbooks`, { headers: authHeaders() })
      .then(r => r.ok ? r.json() : { runbooks: [] })
      .then(d => setRunbooks(d.runbooks || []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const del = async (id) => {
    if (!confirm('Delete this runbook?')) return
    await fetch(`${BASE}/api/runbooks/${id}`, { method: 'DELETE', headers: authHeaders() })
    load()
  }

  const openEditor = async (rb) => {
    // Load full detail (including body_md, triage_keywords which may not be in list view)
    try {
      const res = await fetch(`${BASE}/api/runbooks/${rb.id}`, { headers: authHeaders() })
      const full = res.ok ? await res.json() : rb
      setEditing(full)
    } catch {
      setEditing(rb)
    }
  }

  const onSaved = (updated) => {
    setEditing(null)
    load()
  }

  const visible = query
    ? runbooks.filter(r =>
        r.title.toLowerCase().includes(query.toLowerCase()) ||
        (r.description || '').toLowerCase().includes(query.toLowerCase()) ||
        (r.tags || []).some(t => t.includes(query.toLowerCase())) ||
        (r.triage_keywords || []).some(t => t.toLowerCase().includes(query.toLowerCase()))
      )
    : runbooks

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%',
                  background: 'var(--bg-0)', color: 'var(--text-1)' }}>
      {/* Header */}
      <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)',
                    flexShrink: 0, display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10,
                       color: 'var(--text-3)', letterSpacing: 1 }}>
          RUNBOOKS
        </span>
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Search runbooks…"
          style={{ fontSize: 10, padding: '3px 8px', borderRadius: 2, flex: 1,
                   background: 'var(--bg-2)', border: '1px solid var(--border)',
                   color: 'var(--text-1)', fontFamily: 'var(--font-mono)', outline: 'none' }}
        />
        <button onClick={load}
          style={{ color: 'var(--text-3)', background: 'none', border: 'none',
                   cursor: 'pointer', fontSize: 12 }}>↺</button>
      </div>

      {/* List */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '10px 14px' }}>
        {loading && <p style={{ fontSize: 10, color: 'var(--text-3)' }}>Loading…</p>}
        {!loading && visible.length === 0 && (
          <p style={{ fontSize: 10, color: 'var(--text-3)' }}>
            {query ? 'No runbooks match your search.' : 'No runbooks saved yet. Complete a manual runbook checklist to save one.'}
          </p>
        )}
        {visible.map(rb => {
          const badge = SOURCE_BADGE[rb.source] || { label: rb.source, color: '#64748b' }
          const isOpen = expanded === rb.id
          const hasTriage = !!(rb.name || (rb.triage_keywords && rb.triage_keywords.length))
          return (
            <div key={rb.id} style={{ marginBottom: 8, borderRadius: 3,
                                       border: '1px solid var(--border)',
                                       background: 'var(--bg-1)' }}>
              {/* Summary row */}
              <div
                onClick={() => setExpanded(isOpen ? null : rb.id)}
                style={{ padding: '10px 12px', cursor: 'pointer',
                         display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 10, color: badge.color,
                               fontFamily: 'var(--font-mono)', flexShrink: 0 }}>
                  {badge.label}
                </span>
                <span style={{ fontSize: 11, color: 'var(--text-1)', flex: 1 }}>
                  {rb.title}
                  {rb.name && (
                    <span style={{ marginLeft: 8, fontSize: 9, color: 'var(--text-3)',
                                   fontFamily: 'var(--font-mono)' }}>
                      [{rb.name}]
                    </span>
                  )}
                </span>
                {hasTriage && rb.is_active === false && (
                  <span style={{ fontSize: 8, color: 'var(--red)',
                                 fontFamily: 'var(--font-mono)' }}>INACTIVE</span>
                )}
                <span style={{ fontSize: 9, color: 'var(--text-3)',
                               fontFamily: 'var(--font-mono)' }}>
                  {rb.steps?.length || 0} steps
                </span>
                {(rb.tags || []).map(t => (
                  <span key={t} style={{ fontSize: 8, padding: '1px 5px', borderRadius: 2,
                                          background: 'var(--bg-2)', color: 'var(--text-3)' }}>
                    {t}
                  </span>
                ))}
                <span style={{ color: 'var(--text-3)', fontSize: 12 }}>
                  {isOpen ? '▾' : '▸'}
                </span>
              </div>

              {/* Expanded steps */}
              {isOpen && (
                <div style={{ padding: '0 12px 12px', borderTop: '1px solid var(--border)' }}>
                  <p style={{ fontSize: 10, color: 'var(--text-3)', margin: '8px 0 6px' }}>
                    {rb.description}
                  </p>
                  {hasTriage && (
                    <div style={{ marginTop: 6, marginBottom: 8, fontSize: 10,
                                  color: 'var(--text-2)', fontFamily: 'var(--font-mono)' }}>
                      keywords: [{(rb.triage_keywords || []).join(', ')}]
                      {' · '}
                      agents: [{(rb.applies_to_agent_types || []).join(', ')}]
                      {' · '}
                      priority: {rb.priority ?? 100}
                    </div>
                  )}
                  {(rb.steps || []).map((step, i) => (
                    <div key={i} style={{ padding: '5px 0', borderBottom: '1px solid var(--border)',
                                          fontSize: 10, color: 'var(--text-2)' }}>
                      <span style={{ color: 'var(--text-3)', marginRight: 8 }}>
                        {String(i + 1).padStart(2, '0')}.
                      </span>
                      {step.title || step.description || String(step)}
                      {step.command && (
                        <div style={{ marginTop: 3, display: 'flex', gap: 6, alignItems: 'center' }}>
                          <code style={{ fontSize: 9, color: '#38bdf8',
                                         fontFamily: 'var(--font-mono)',
                                         background: 'var(--bg-2)',
                                         padding: '1px 6px', borderRadius: 2 }}>
                            {step.command}
                          </code>
                          <button
                            onClick={() => navigator.clipboard.writeText(step.command)}
                            style={{ fontSize: 8, color: 'var(--text-3)', background: 'none',
                                     border: '1px solid var(--border)', borderRadius: 2,
                                     cursor: 'pointer', padding: '1px 4px' }}>
                            copy
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
                  {hasTriage && rb.body_md && (
                    <details style={{ marginTop: 8 }}>
                      <summary style={{ fontSize: 9, color: 'var(--text-3)',
                                        fontFamily: 'var(--font-mono)', cursor: 'pointer' }}>
                        body_md (injected into system prompt)
                      </summary>
                      <pre style={{ fontSize: 10, color: 'var(--text-2)',
                                    whiteSpace: 'pre-wrap', background: 'var(--bg-2)',
                                    padding: 8, borderRadius: 2, marginTop: 4,
                                    fontFamily: 'var(--font-mono)' }}>
                        {rb.body_md}
                      </pre>
                    </details>
                  )}
                  {/* Actions */}
                  <div style={{ marginTop: 10, display: 'flex', gap: 8 }}>
                    <button
                      onClick={() => openEditor(rb)}
                      style={{ fontSize: 9, padding: '3px 8px', borderRadius: 2,
                               background: 'transparent', color: 'var(--cyan)',
                               border: '1px solid var(--border)', cursor: 'pointer',
                               fontFamily: 'var(--font-mono)' }}>
                      edit
                    </button>
                    <button
                      onClick={() => del(rb.id)}
                      style={{ fontSize: 9, padding: '3px 8px', borderRadius: 2,
                               background: 'transparent', color: 'var(--red)',
                               border: '1px solid var(--border)', cursor: 'pointer',
                               fontFamily: 'var(--font-mono)' }}>
                      delete
                    </button>
                    <span style={{ fontSize: 9, color: 'var(--text-3)', alignSelf: 'center' }}>
                      used {rb.run_count}x · by {rb.created_by}
                    </span>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {editing && (
        <EditModal
          runbook={editing}
          onClose={() => setEditing(null)}
          onSaved={onSaved}
        />
      )}
    </div>
  )
}
