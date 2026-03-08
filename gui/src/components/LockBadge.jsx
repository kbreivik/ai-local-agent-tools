import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

export default function LockBadge() {
  const { token } = useAuth()
  const [lockInfo, setLockInfo] = useState(null)

  useEffect(() => {
    if (!token) return

    const poll = () => {
      fetch(`${API_BASE}/api/lock/status`, {
        headers: { Authorization: `Bearer ${token}` },
      })
        .then(r => r.ok ? r.json() : null)
        .then(data => setLockInfo(data?.locked ? data : null))
        .catch(() => setLockInfo(null))
    }

    poll()
    const id = setInterval(poll, 5000)
    return () => clearInterval(id)
  }, [token])

  if (!lockInfo) return null

  return (
    <div
      className="flex items-center gap-1.5 px-3 border-l border-gray-200 h-8"
      title={`Destructive lock held by ${lockInfo.owner_user} since ${new Date(lockInfo.since).toLocaleTimeString()}`}
    >
      <span className="text-xs">{'\uD83D\uDD12'}</span>
      <span className="text-orange-600 text-xs font-medium">
        Locked &middot; {lockInfo.owner_user}
      </span>
    </div>
  )
}
