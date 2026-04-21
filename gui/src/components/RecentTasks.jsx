/**
 * RecentTasks — v2.37.0
 *
 * Shows the N most recently run agent tasks (deduped by exact task text),
 * fetched from /api/logs/operations/recent. Click a row fills the task
 * textarea via useTask().setTask() — same UX as TaskTemplates. Does NOT
 * auto-run the agent.
 *
 * N is operator-tunable via the `recentTasksCount` Settings key
 * (default 10, range 1–50). The section uses CollapsibleSection with
 * defaultOpen={false} and storageKey='recent-tasks' so state persists
 * across reloads independently of Templates.
 *
 * Re-fetches when:
 *   - the component mounts
 *   - the window regains focus (so freshly-run tasks show up)
 *   - the recentTasksCount setting changes
 */
import { useEffect, useState, useCallback } from 'react'
import { useTask } from '../context/TaskContext'
import { useOptions } from '../context/OptionsContext'
import CollapsibleSection from './CollapsibleSection'

const AGENT_COLORS = {
  observe:     'var(--cyan)',
  status:      'var(--cyan)',
  investigate: 'var(--accent)',
  research:    'var(--accent)',
  execute:     'var(--amber)',
  action:      'var(--amber)',
  build:       'var(--green)',
  ambiguous:   'var(--cyan)',
}

const STATUS_COLORS = {
  completed: 'var(--green)',
  ok:        'var(--green)',
  failed:    'var(--red)',
  error:     'var(--red)',
  cancelled: 'var(--text-3)',
  escalated: 'var(--amber)',
  capped:    'var(--amber)',
}

function ago(seconds) {
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`
  return `${Math.floor(seconds / 86400)}d`
}

export default function RecentTasks() {
  const { setTask } = useTask()
  const { recentTasksCount } = useOptions()
  const limit = Math.max(1, Math.min(50, parseInt(recentTasksCount ?? 10, 10) || 10))

  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const fetchRecent = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const res = await fetch(
        `/api/logs/operations/recent?limit=${limit}`,
        { credentials: 'include' },
      )
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setItems(Array.isArray(data.items) ? data.items : [])
    } catch (e) {
      setError(String(e).slice(0, 120))
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [limit])

  useEffect(() => { fetchRecent() }, [fetchRecent])

  // Refetch on window focus so new runs appear without full reload
  useEffect(() => {
    const onFocus = () => { fetchRecent() }
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [fetchRecent])

  const pick = (task) => {
    setTask(task)
  }

  return (
    <CollapsibleSection
      title={`RECENT · ${items.length}`}
      defaultOpen={false}
      storageKey="recent-tasks"
    >
      {loading && items.length === 0 && (
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 9,
          color: 'var(--text-3)', padding: '4px 0',
        }}>
          loading…
        </div>
      )}
      {error && (
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 9,
          color: 'var(--red)', padding: '4px 0',
        }}>
          error: {error}
        </div>
      )}
      {!loading && !error && items.length === 0 && (
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 9,
          color: 'var(--text-3)', padding: '4px 0',
        }}>
          No recent tasks yet. Runs you start will show up here.
        </div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {items.map((item, idx) => {
          const color = AGENT_COLORS[item.agent_type] || 'var(--cyan)'
          const statusColor = STATUS_COLORS[item.status] || 'var(--text-3)'
          return (
            <button
              key={`${item.operation_id}-${idx}`}
              onClick={() => pick(item.task)}
              title={item.task}
              style={{
                textAlign: 'left',
                padding: '4px 8px',
                fontSize: 9,
                fontFamily: 'var(--font-mono)',
                letterSpacing: '0.03em',
                background: 'var(--bg-2)',
                border: '1px solid var(--border)',
                borderLeft: `2px solid ${color}`,
                borderRadius: 2,
                cursor: 'pointer',
                color: 'var(--text-2)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 8,
                transition: 'background 0.12s',
                width: '100%',
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-3)'}
              onMouseLeave={e => e.currentTarget.style.background = 'var(--bg-2)'}
            >
              <span style={{
                flex: 1,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}>
                {item.task}
              </span>
              <span style={{
                flexShrink: 0,
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                fontSize: 8,
              }}>
                <span style={{ color: statusColor }}>●</span>
                <span style={{ color: 'var(--text-3)' }}>{ago(item.age_seconds)}</span>
              </span>
            </button>
          )
        })}
      </div>
    </CollapsibleSection>
  )
}
