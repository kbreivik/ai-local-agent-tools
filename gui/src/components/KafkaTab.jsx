import React, { useEffect, useState } from 'react'
import { authHeaders } from '../api'

export default function KafkaTab() {
  const [data, setData] = useState(null)
  const [selectedTopic, setSelectedTopic] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    let stop = false
    async function load() {
      try {
        const r = await fetch('/api/kafka/overview', {
          credentials: 'include',
          headers: { ...authHeaders() },
        })
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const d = await r.json()
        if (!stop) { setData(d); setErr(null) }
      } catch (e) { if (!stop) setErr(String(e)) }
    }
    load()
    const iv = setInterval(load, 15000)
    return () => { stop = true; clearInterval(iv) }
  }, [])

  if (err) return <div className="mono" style={{ padding: 14, color: 'var(--red)' }}>KAFKA: {err}</div>
  if (!data) return <div className="mono" style={{ padding: 14, color: 'var(--text-2)' }}>loading…</div>

  const brokers = data.brokers || []
  const topics = data.topics || []
  const summary = data.summary || {}

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr 320px', gap: 14, padding: 14, overflow: 'auto' }}>
      {/* brokers */}
      <div>
        <div className="mono" style={{ fontSize: 10, letterSpacing: '0.2em', color: 'var(--text-2)', marginBottom: 8 }}>BROKERS</div>
        {brokers.map(b => (
          <div key={b.id} style={{
            padding: '6px 8px', marginBottom: 4,
            border: '1px solid var(--border)', borderRadius: 2,
            fontFamily: 'var(--font-mono)', fontSize: 11,
          }}>
            <span style={{ color: 'var(--cyan)' }}>#{b.id}</span> {b.host}:{b.port}
            {b.is_controller && <span style={{ marginLeft: 6, color: 'var(--amber)' }}>★</span>}
          </div>
        ))}
        <div className="mono" style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 8 }}>
          {summary.broker_count ?? brokers.length} up · {summary.under_replicated_partitions ?? 0} UR
        </div>
      </div>

      {/* topic grid */}
      <div>
        <div className="mono" style={{ fontSize: 10, letterSpacing: '0.2em', color: 'var(--text-2)', marginBottom: 8 }}>TOPICS</div>
        <table style={{ width: '100%', fontFamily: 'var(--font-mono)', fontSize: 11, borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ color: 'var(--text-2)', borderBottom: '1px solid var(--border)' }}>
              <th align="left" style={{ padding: 4 }}>NAME</th>
              <th align="right" style={{ padding: 4 }}>P</th>
              <th align="right" style={{ padding: 4 }}>UR</th>
              <th align="right" style={{ padding: 4 }}>MAX LAG</th>
            </tr>
          </thead>
          <tbody>
            {topics.map(t => (
              <tr key={t.name}
                  onClick={() => setSelectedTopic(t)}
                  style={{
                    cursor: 'pointer',
                    background: selectedTopic?.name === t.name ? 'var(--accent-dim)' : 'transparent',
                    color: t.under_replicated ? 'var(--amber)' : 'var(--text-0)',
                    borderBottom: '1px dashed var(--border)',
                  }}>
                <td style={{ padding: 4 }}>{t.name}</td>
                <td align="right" style={{ padding: 4 }}>{t.partitions}</td>
                <td align="right" style={{ padding: 4, color: t.under_replicated ? 'var(--red)' : 'var(--text-3)' }}>
                  {t.under_replicated || '·'}
                </td>
                <td align="right" style={{ padding: 4 }}>
                  {t.max_consumer_lag != null ? t.max_consumer_lag : '·'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* drill-in */}
      <div>
        <div className="mono" style={{ fontSize: 10, letterSpacing: '0.2em', color: 'var(--text-2)', marginBottom: 8 }}>PARTITIONS</div>
        {selectedTopic ? (
          <div>
            <div style={{ fontSize: 13, marginBottom: 6 }}>{selectedTopic.name}</div>
            {(selectedTopic._raw_partitions || []).map(p => (
              <div key={p.id} style={{
                padding: '6px 8px', marginBottom: 3,
                background: p.under_replicated ? 'rgba(204,136,0,0.15)' : 'var(--bg-2)',
                fontFamily: 'var(--font-mono)', fontSize: 11, borderRadius: 2,
              }}>
                <div>P{p.id} → leader <span style={{ color: 'var(--cyan)' }}>{p.leader}</span></div>
                <div style={{ color: 'var(--text-2)' }}>
                  R=[{(p.replicas || []).join(',')}] ISR=[{(p.isr || []).join(',')}]
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="mono" style={{ fontSize: 11, color: 'var(--text-3)' }}>
            select a topic →
          </div>
        )}
      </div>
    </div>
  )
}
