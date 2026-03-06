/**
 * SparkLine — tiny inline health history chart.
 * Fetches /api/status/history/{component}?hours=N
 * Renders as a row of colored segments (pure CSS — no chart lib).
 */
import { useEffect, useState } from 'react'
import { fetchStatusHistory } from '../api'

const HEALTH_COLOR = {
  healthy:      'bg-green-500',
  ok:           'bg-green-500',
  green:        'bg-green-500',
  active:       'bg-green-500',
  degraded:     'bg-yellow-400',
  yellow:       'bg-yellow-400',
  critical:     'bg-red-500',
  red:          'bg-red-500',
  error:        'bg-red-600',
  unconfigured: 'bg-slate-600',
  unknown:      'bg-slate-700',
}

function bucket(history, buckets = 24) {
  if (!history || history.length === 0) return Array(buckets).fill('unknown')
  const now = Date.now()
  const windowMs = buckets * 3600 * 1000
  const bucketMs = windowMs / buckets
  const result = Array(buckets).fill(null)

  for (const entry of history) {
    const t = new Date(entry.timestamp).getTime()
    const idx = Math.floor((t - (now - windowMs)) / bucketMs)
    if (idx >= 0 && idx < buckets) {
      // Worst health wins within a bucket
      const prev = result[idx]
      const weights = { critical: 3, error: 3, red: 3, degraded: 2, yellow: 2, unknown: 1, healthy: 0, ok: 0, green: 0, unconfigured: 0 }
      if (prev === null || (weights[entry.health] ?? 1) > (weights[prev] ?? 1)) {
        result[idx] = entry.health
      }
    }
  }
  return result.map(v => v ?? 'unknown')
}

export default function SparkLine({ component, hours = 24, buckets = 24 }) {
  const [segments, setSegments] = useState([])

  useEffect(() => {
    fetchStatusHistory(component, hours)
      .then(d => setSegments(bucket(d.history ?? [], buckets)))
      .catch(() => setSegments(Array(buckets).fill('unknown')))

    const id = setInterval(() => {
      fetchStatusHistory(component, hours)
        .then(d => setSegments(bucket(d.history ?? [], buckets)))
        .catch(() => {})
    }, 60_000)
    return () => clearInterval(id)
  }, [component, hours, buckets])

  if (segments.length === 0) return null

  return (
    <div className="flex gap-px h-2 rounded overflow-hidden" title={`${component} health — last ${hours}h`}>
      {segments.map((health, i) => (
        <div
          key={i}
          className={`flex-1 ${HEALTH_COLOR[health] ?? 'bg-slate-700'}`}
          title={health}
        />
      ))}
    </div>
  )
}
