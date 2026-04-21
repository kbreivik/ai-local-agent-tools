/**
 * AnalysisView — v2.38.0 — sith_lord-only diagnostic SQL templates.
 *
 * Fetches template catalog from /api/admin/analysis/templates, renders
 * a picker + param form, runs the selected template on "Run", shows
 * results as a collapsible JSON tree. Three Download buttons (JSON /
 * CSV / MD) hit /api/admin/analysis/dump.
 *
 * 403 handled gracefully — non-sith_lord users see a "requires admin
 * role" notice instead of a broken component.
 */
import { useEffect, useState } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''


function JsonTree({ data, depth = 0 }) {
  if (data === null) return <span className="text-[var(--text-3)]">null</span>
  if (typeof data !== 'object') {
    const s = String(data)
    const color = typeof data === 'number'  ? 'var(--cyan)'
                : typeof data === 'boolean' ? 'var(--amber)'
                : 'var(--text-2)'
    return <span style={{ color }} title={s.length > 80 ? s : undefined}>
      {typeof data === 'string' ? `"${s}"` : s}
    </span>
  }
  const isArr = Array.isArray(data)
  const entries = isArr ? data.map((v, i) => [i, v]) : Object.entries(data)
  const [open, setOpen] = useState(depth < 2)
  if (entries.length === 0) {
    return <span className="text-[var(--text-3)]">{isArr ? '[]' : '{}'}</span>
  }
  return (
    <div style={{ marginLeft: depth === 0 ? 0 : 12 }}>
      <button
        onClick={() => setOpen(o => !o)}
        className="text-[var(--text-3)] hover:text-[var(--accent)] font-mono text-xs"
      >
        {open ? '▼' : '▶'} {isArr ? `[${entries.length}]` : `{${entries.length}}`}
      </button>
      {open && (
        <div style={{ borderLeft: '1px dashed var(--border)', paddingLeft: 8, marginTop: 2 }}>
          {entries.map(([k, v]) => (
            <div key={k} style={{ fontFamily: 'var(--font-mono)', fontSize: 11, lineHeight: 1.5 }}>
              <span style={{ color: 'var(--accent)' }}>{k}</span>
              <span style={{ color: 'var(--text-3)' }}>: </span>
              <JsonTree data={v} depth={depth + 1} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}


function ParamForm({ params, values, onChange }) {
  if (!params || params.length === 0) {
    return <div className="text-xs text-[var(--text-3)]">No parameters for this template.</div>
  }
  return (
    <div className="flex flex-col gap-2">
      {params.map((p) => {
        const id = `ap-${p.name}`
        return (
          <label key={p.name} htmlFor={id} className="flex flex-col gap-1">
            <span className="text-xs font-mono uppercase tracking-wider text-[var(--text-3)]">
              {p.name}
              {p.required ? ' *' : ''}
              <span className="ml-2 normal-case tracking-normal text-[var(--text-3)]">
                ({p.type}){p.default !== undefined ? `, default: ${p.default}` : ''}
              </span>
            </span>
            <input
              id={id}
              type={p.type === 'int' ? 'number' : 'text'}
              min={p.min}
              max={p.max}
              value={values[p.name] ?? ''}
              onChange={(e) => onChange({ ...values, [p.name]: e.target.value })}
              placeholder={p.default !== undefined ? String(p.default) : ''}
              className="px-2 py-1 bg-[var(--bg-2)] border border-[var(--border)] rounded
                         text-sm font-mono text-[var(--text-1)]"
              style={{ borderRadius: 2 }}
            />
            {p.description && (
              <span className="text-[10px] text-[var(--text-3)]">{p.description}</span>
            )}
          </label>
        )
      })}
    </div>
  )
}


export default function AnalysisView() {
  const [templates, setTemplates]     = useState([])
  const [loadErr, setLoadErr]         = useState(null)
  const [selected, setSelected]       = useState('')
  const [paramValues, setParamValues] = useState({})
  const [result, setResult]           = useState(null)
  const [running, setRunning]         = useState(false)
  const [runErr, setRunErr]           = useState(null)

  useEffect(() => {
    fetch(`${BASE}/api/admin/analysis/templates`, { credentials: 'include', headers: authHeaders() })
      .then(async (r) => {
        if (r.status === 403) throw new Error('Access denied — sith_lord role required.')
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((d) => setTemplates(d.templates || []))
      .catch((e) => setLoadErr(e.message))
  }, [])

  const currentTpl = templates.find((t) => t.id === selected)

  const onSelect = (tid) => {
    setSelected(tid)
    setParamValues({})
    setResult(null)
    setRunErr(null)
  }

  const runQuery = async () => {
    if (!selected) return
    setRunning(true); setRunErr(null); setResult(null)
    try {
      const r = await fetch(`${BASE}/api/admin/analysis/run`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ template_id: selected, params: paramValues }),
      })
      const data = await r.json()
      if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`)
      setResult(data)
    } catch (e) {
      setRunErr(String(e.message || e))
    } finally {
      setRunning(false)
    }
  }

  const download = (format) => {
    if (!selected) return
    const url = `${BASE}/api/admin/analysis/dump?format=${format}`
    fetch(url, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ template_id: selected, params: paramValues }),
    })
      .then(async (r) => {
        if (!r.ok) {
          const err = await r.json().catch(() => ({}))
          throw new Error(err.detail || `HTTP ${r.status}`)
        }
        return r.blob().then((blob) => ({ blob, r }))
      })
      .then(({ blob, r }) => {
        // Read filename from Content-Disposition
        const cd = r.headers.get('Content-Disposition') || ''
        const match = /filename="?([^"]+)"?/i.exec(cd)
        const filename = match ? match[1] : `analysis-${selected}.${format}`
        const href = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = href
        a.download = filename
        document.body.appendChild(a)
        a.click()
        a.remove()
        URL.revokeObjectURL(href)
      })
      .catch((e) => setRunErr(String(e.message || e)))
  }

  if (loadErr) {
    return (
      <div className="p-4 text-sm text-[var(--amber)] font-mono">
        {loadErr}
      </div>
    )
  }

  return (
    <div className="p-4 flex flex-col gap-4 h-full overflow-auto">
      <div>
        <h2 className="text-[var(--accent)] font-mono uppercase tracking-wider text-sm mb-1">
          Analysis — SQL templates
        </h2>
        <div className="text-xs text-[var(--text-3)]">
          Admin-only. Pick a template, fill params, hit Run. Results are
          capped by the template's row_cap (max 10,000). Downloads work
          after the query has run.
        </div>
      </div>

      <div className="flex flex-col gap-3 p-3 bg-[var(--bg-2)] border border-[var(--border)]" style={{ borderRadius: 2 }}>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-mono uppercase tracking-wider text-[var(--text-3)]">Template</span>
          <select
            value={selected}
            onChange={(e) => onSelect(e.target.value)}
            className="px-2 py-1 bg-[var(--bg-1)] border border-[var(--border)] text-sm font-mono text-[var(--text-1)]"
            style={{ borderRadius: 2 }}
          >
            <option value="">— pick a template —</option>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>{t.title}</option>
            ))}
          </select>
        </label>
        {currentTpl && (
          <div className="text-xs text-[var(--text-2)] leading-snug">{currentTpl.description}</div>
        )}
        {currentTpl && (
          <ParamForm params={currentTpl.params} values={paramValues} onChange={setParamValues} />
        )}
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={runQuery}
            disabled={!selected || running}
            className="px-3 py-1 bg-[var(--accent)] text-white font-mono text-xs uppercase tracking-wider
                       disabled:opacity-40 disabled:cursor-not-allowed"
            style={{ borderRadius: 2 }}
          >
            {running ? 'Running…' : 'Run'}
          </button>
          {result && (
            <>
              <button onClick={() => download('json')}
                      className="px-3 py-1 bg-[var(--bg-3)] border border-[var(--border)] text-[var(--text-1)] font-mono text-xs uppercase"
                      style={{ borderRadius: 2 }}>
                Dump JSON
              </button>
              <button onClick={() => download('csv')}
                      className="px-3 py-1 bg-[var(--bg-3)] border border-[var(--border)] text-[var(--text-1)] font-mono text-xs uppercase"
                      style={{ borderRadius: 2 }}>
                Dump CSV
              </button>
              <button onClick={() => download('md')}
                      className="px-3 py-1 bg-[var(--bg-3)] border border-[var(--border)] text-[var(--text-1)] font-mono text-xs uppercase"
                      style={{ borderRadius: 2 }}>
                Dump Markdown
              </button>
            </>
          )}
        </div>
        {runErr && (
          <div className="text-xs font-mono text-[var(--red)] whitespace-pre-wrap">{runErr}</div>
        )}
      </div>

      {result && (
        <div className="flex flex-col gap-2 p-3 bg-[var(--bg-2)] border border-[var(--border)]" style={{ borderRadius: 2 }}>
          <div className="text-xs font-mono text-[var(--text-3)]">
            Rows: <span className="text-[var(--text-1)]">{result.row_count}</span>
            {result.truncated && (
              <span className="ml-2 text-[var(--amber)]">(truncated at row_cap)</span>
            )}
            <span className="ml-4">Latency: {result.latency_ms}ms</span>
            <span className="ml-4">Columns: {(result.columns || []).join(', ')}</span>
          </div>
          <div style={{
            maxHeight: '60vh', overflow: 'auto',
            background: 'var(--bg-1)', padding: 8, border: '1px solid var(--border)', borderRadius: 2
          }}>
            <JsonTree data={result.rows} />
          </div>
        </div>
      )}
    </div>
  )
}
