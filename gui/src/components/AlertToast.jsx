/**
 * AlertToast — fixed top-right toast notifications.
 * Polls /api/alerts/recent every 10s, shows up to 3 at a time.
 * Auto-dismisses after 10s. Click X to dismiss early.
 */
import { useEffect, useRef, useState } from 'react'
import { fetchAlerts, dismissAlert, dismissAllAlerts } from '../api'

const SEVERITY_STYLE = {
  critical: 'bg-red-900 border-red-600 text-red-200',
  warning:  'bg-yellow-900 border-yellow-600 text-yellow-200',
  info:     'bg-blue-900 border-blue-600 text-blue-200',
}

const SEVERITY_ICON = {
  critical: '🔴',
  warning:  '🟡',
  info:     '🔵',
}

function Toast({ alert, onDismiss }) {
  const timerRef = useRef(null)

  useEffect(() => {
    timerRef.current = setTimeout(() => onDismiss(alert.id), 10_000)
    return () => clearTimeout(timerRef.current)
  }, [alert.id])

  const style = SEVERITY_STYLE[alert.severity] ?? SEVERITY_STYLE.warning

  return (
    <div className={`flex items-start gap-2 px-3 py-2.5 rounded border text-xs max-w-xs shadow-lg ${style} animate-fade-in`}>
      <span className="shrink-0 text-sm">{SEVERITY_ICON[alert.severity] ?? '⚪'}</span>
      <div className="flex-1 min-w-0">
        <div className="font-semibold font-mono">{alert.component}</div>
        <div className="opacity-90 mt-0.5 leading-tight">{alert.message}</div>
        <div className="opacity-60 mt-1">{new Date(alert.timestamp).toLocaleTimeString()}</div>
      </div>
      <button
        onClick={() => onDismiss(alert.id)}
        className="shrink-0 opacity-60 hover:opacity-100 text-base leading-none"
      >
        ×
      </button>
    </div>
  )
}

export default function AlertToast() {
  const [alerts, setAlerts] = useState([])
  const seenRef = useRef(new Set())

  const load = () => {
    fetchAlerts(20)
      .then(d => {
        const fresh = (d.alerts ?? []).filter(a => !seenRef.current.has(a.id))
        if (fresh.length > 0) {
          setAlerts(prev => [...fresh, ...prev].slice(0, 5))
          fresh.forEach(a => seenRef.current.add(a.id))
        }
      })
      .catch(() => {})
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 10_000)
    return () => clearInterval(id)
  }, [])

  const dismiss = (id) => {
    setAlerts(prev => prev.filter(a => a.id !== id))
    dismissAlert(id).catch(() => {})
  }

  if (alerts.length === 0) return null

  return (
    <div className="fixed top-12 right-3 z-50 flex flex-col gap-2 pointer-events-auto">
      {alerts.slice(0, 3).map(alert => (
        <Toast key={alert.id} alert={alert} onDismiss={dismiss} />
      ))}
    </div>
  )
}
