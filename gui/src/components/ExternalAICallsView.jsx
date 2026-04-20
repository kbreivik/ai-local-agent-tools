import React, { useState, useEffect } from 'react'

/**
 * v2.36.4 — Recent external AI calls table.
 *
 * Pulls from GET /api/external-ai/calls?limit=50. Operator-facing
 * billing/outcome log for external AI escalations.
 */
export default function ExternalAICallsView() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const r = await fetch('/api/external-ai/calls?limit=50',
                              { credentials: 'include' })
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const d = await r.json()
        if (!cancelled) setRows(d.calls || [])
      } catch (e) {
        if (!cancelled) setErr(e.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    const id = setInterval(load, 30000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  if (loading) return <div className="p-4 text-sm text-gray-500">Loading...</div>
  if (err) return <div className="p-4 text-sm text-[var(--red)]">Error: {err}</div>

  if (rows.length === 0) return (
    <div className="p-4 text-sm text-gray-500">
      No external AI calls yet. Enable <code>externalRoutingMode=auto</code>{' '}
      in AI Services settings to allow routing.
    </div>
  )

  return (
    <div className="p-4">
      <h2 className="font-mono uppercase text-[var(--accent)] mb-3">
        Recent External AI Calls
      </h2>
      <table className="w-full text-sm">
        <thead className="text-xs uppercase text-gray-400 border-b border-white/10">
          <tr>
            <th className="text-left py-2">When</th>
            <th className="text-left">Provider / Model</th>
            <th className="text-left">Rule</th>
            <th className="text-left">Outcome</th>
            <th className="text-right">Latency</th>
            <th className="text-right">Tokens in/out</th>
            <th className="text-right">Est. $</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.id} className="border-b border-white/5 hover:bg-white/5">
              <td className="py-2 text-xs text-gray-400">
                {new Date(r.created_at).toLocaleString()}
              </td>
              <td className="text-xs">
                <b className="text-[var(--cyan)]">{r.provider}</b> / {r.model}
              </td>
              <td className="text-xs"><code>{r.rule_fired}</code></td>
              <td className="text-xs">
                <span style={{ color:
                  r.outcome === 'success' ? 'var(--green)' :
                  r.outcome === 'rejected_by_gate' ? 'var(--amber)' :
                  'var(--red)'
                }}>{r.outcome}</span>
              </td>
              <td className="text-right text-xs">{r.latency_ms ? `${r.latency_ms}ms` : '—'}</td>
              <td className="text-right text-xs">
                {r.input_tokens || '—'}/{r.output_tokens || '—'}
              </td>
              <td className="text-right text-xs">
                {r.est_cost_usd != null ? `$${r.est_cost_usd.toFixed(4)}` : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
