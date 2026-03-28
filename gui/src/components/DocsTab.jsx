import React, { useState, useEffect } from 'react'
import { useAuth } from '../context/AuthContext'

const API = import.meta.env.VITE_API_BASE || ''

function Badge({ children, color = 'gray' }) {
  const colors = {
    gray:   'bg-gray-100 text-gray-600',
    red:    'bg-red-100 text-red-700',
    green:  'bg-green-100 text-green-700',
    yellow: 'bg-yellow-100 text-yellow-700',
    blue:   'bg-blue-100 text-blue-700',
  }
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded font-mono ${colors[color] || colors.gray}`}>
      {children}
    </span>
  )
}

function Section({ title, error, children }) {
  return (
    <div className="mb-6">
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2 px-4">{title}</h3>
      {error
        ? <div className="px-4 text-xs text-red-600">Failed to load: {error}</div>
        : children}
    </div>
  )
}

export default function DocsTab() {
  const { token } = useAuth()
  const [docs,      setDocs]      = useState([])
  const [logRows,   setLogRows]   = useState([])
  const [docsError, setDocsError] = useState(null)
  const [logError,  setLogError]  = useState(null)
  const [expanded,  setExpanded]  = useState(null)
  const [filterSkill,   setFilterSkill]   = useState('')
  const [filterOutcome, setFilterOutcome] = useState('')

  useEffect(() => {
    if (!token) return
    const headers = { Authorization: `Bearer ${token}` }

    // Fetch user-ingested docs (PDFs / URLs via the ingest router)
    fetch(`${API}/api/memory/ingest/docs`, { headers })
      .then(r => r.json())
      .then(d => setDocs(d.docs || []))
      .catch(e => setDocsError(e.message))

    // Fetch generation log
    fetch(`${API}/api/skills/generation-log?limit=100`, { headers })
      .then(r => r.json())
      .then(d => setLogRows(d.log || []))
      .catch(e => setLogError(e.message))
  }, [token])

  const filteredLog = logRows.filter(row => {
    if (filterSkill   && !row.skill_name.includes(filterSkill)) return false
    if (filterOutcome && row.outcome !== filterOutcome)          return false
    return true
  })

  const toggleExpand = (id) => setExpanded(expanded === id ? null : id)

  return (
    <div className="flex flex-col h-full overflow-y-auto bg-white text-sm">
      <div className="px-4 py-3 border-b border-gray-200">
        <span className="font-semibold text-gray-700">Doc Pipeline</span>
        <span className="ml-2 text-xs text-gray-400">Ingested docs and skill generation traces</span>
      </div>

      {/* ── Ingested Documents ───────────────────────────────────────────── */}
      <Section title="Ingested Documents" error={docsError}>
        {docs.length === 0
          ? <div className="px-4 text-xs text-gray-400">No documents ingested yet. Use the Ingest tool to add API docs.</div>
          : (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-400 border-b border-gray-100">
                  <th className="text-left px-4 py-1 font-normal">Label</th>
                  <th className="text-left px-4 py-1 font-normal">Chunks</th>
                  <th className="text-left px-4 py-1 font-normal">Stored At</th>
                </tr>
              </thead>
              <tbody>
                {docs.map(d => (
                  <tr key={d.source_key} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="px-4 py-1.5 font-mono">{d.source_label || d.source_key}</td>
                    <td className="px-4 py-1.5">{d.chunk_count}</td>
                    <td className="px-4 py-1.5 text-gray-400">{d.stored_at ? d.stored_at.slice(0, 10) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </Section>

      {/* ── Generation Log ───────────────────────────────────────────────── */}
      <Section title="Generation Log" error={logError}>
        <div className="px-4 mb-2 flex gap-2">
          <input
            value={filterSkill}
            onChange={e => setFilterSkill(e.target.value)}
            placeholder="Filter by skill name…"
            className="text-xs border border-gray-200 rounded px-2 py-1 w-48 focus:outline-none focus:border-blue-400"
          />
          <select
            value={filterOutcome}
            onChange={e => setFilterOutcome(e.target.value)}
            className="text-xs border border-gray-200 rounded px-2 py-1 focus:outline-none focus:border-blue-400"
          >
            <option value="">All outcomes</option>
            <option value="success">success</option>
            <option value="error">error</option>
            <option value="export">export</option>
          </select>
        </div>

        {filteredLog.length === 0
          ? <div className="px-4 text-xs text-gray-400">No generation log entries.</div>
          : (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-400 border-b border-gray-100">
                  <th className="text-left px-4 py-1 font-normal">Skill</th>
                  <th className="text-left px-4 py-1 font-normal">Triggered By</th>
                  <th className="text-left px-4 py-1 font-normal">Backend</th>
                  <th className="text-left px-4 py-1 font-normal">Docs</th>
                  <th className="text-left px-4 py-1 font-normal">Tokens</th>
                  <th className="text-left px-4 py-1 font-normal">Outcome</th>
                  <th className="text-left px-4 py-1 font-normal">Date</th>
                </tr>
              </thead>
              <tbody>
                {filteredLog.map(row => (
                  <React.Fragment key={row.id}>
                    <tr
                      className={`border-b border-gray-50 hover:bg-gray-50 cursor-pointer ${expanded === row.id ? 'bg-blue-50' : ''}`}
                      onClick={() => toggleExpand(row.id)}
                    >
                      <td className="px-4 py-1.5 font-mono">{row.skill_name}</td>
                      <td className="px-4 py-1.5 text-gray-500">{row.triggered_by}</td>
                      <td className="px-4 py-1.5 text-gray-500">{row.backend}</td>
                      <td className="px-4 py-1.5">{(row.docs_retrieved || []).length}</td>
                      <td className="px-4 py-1.5">
                        {row.total_tokens === 0
                          ? <Badge color="yellow">0 — no docs</Badge>
                          : row.total_tokens}
                      </td>
                      <td className="px-4 py-1.5">
                        <Badge color={row.outcome === 'success' ? 'green' : row.outcome === 'error' ? 'red' : 'blue'}>
                          {row.outcome}
                        </Badge>
                      </td>
                      <td className="px-4 py-1.5 text-gray-400">
                        {row.created_at ? new Date(row.created_at * 1000).toLocaleDateString() : '—'}
                      </td>
                    </tr>
                    {expanded === row.id && (
                      <tr>
                        <td colSpan={7} className="px-6 py-3 bg-gray-50 text-xs text-gray-700">
                          {row.error_message && (
                            <div className="mb-2 text-red-600"><b>Error:</b> {row.error_message}</div>
                          )}
                          <div className="mb-1"><b>Keywords:</b> {JSON.stringify(row.keywords)}</div>
                          <div className="mb-1"><b>Sources:</b> {(row.sources_used || []).join(', ') || 'none'}</div>
                          <div className="mb-1"><b>Spec used:</b> {row.spec_used ? 'yes' : 'no'}</div>
                          {(row.spec_warnings || []).length > 0 && (
                            <div className="mb-1"><b>Spec warnings:</b> {row.spec_warnings.join('; ')}</div>
                          )}
                          {(row.docs_retrieved || []).length > 0 && (
                            <div>
                              <b>Docs injected:</b>
                              <ul className="mt-1 ml-3 space-y-0.5">
                                {row.docs_retrieved.map((d, i) => (
                                  <li key={i}>
                                    <span className="font-mono">{d.concept}</span>
                                    {' '}<Badge>{d.doc_type}</Badge>
                                    {' '}{d.tokens} tokens
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          )}
      </Section>
    </div>
  )
}
