// Centralised API + WebSocket calls

const BASE = import.meta.env.VITE_API_BASE ?? ''  // empty = use Vite proxy

// ── REST ─────────────────────────────────────────────────────────────────────

export async function fetchHealth() {
  const r = await fetch(`${BASE}/api/health`)
  return r.json()
}

export async function fetchTools(refresh = false) {
  const r = await fetch(`${BASE}/api/tools${refresh ? '?refresh=true' : ''}`)
  const d = await r.json()
  return d.tools ?? []
}

export async function fetchStatus() {
  const r = await fetch(`${BASE}/api/status`)
  return r.json()
}

export async function fetchLogs({ status = 'all', limit = 100, offset = 0, tool = '' } = {}) {
  const p = new URLSearchParams({ status, limit, offset, ...(tool ? { tool } : {}) })
  const r = await fetch(`${BASE}/api/logs?${p}`)
  return r.json()
}

export async function invokeTool(toolName, params = {}) {
  const r = await fetch(`${BASE}/api/tools/${toolName}/invoke`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  return r.json()
}

export async function runAgent(task, sessionId = '') {
  const r = await fetch(`${BASE}/api/agent/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task, session_id: sessionId }),
  })
  return r.json()
}

export async function sendConfirmation(sessionId, approved) {
  const r = await fetch(`${BASE}/api/agent/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, approved }),
  })
  return r.json()
}

export async function sendClarification(sessionId, answer) {
  const r = await fetch(`${BASE}/api/agent/clarify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, answer }),
  })
  return r.json()
}

export async function fetchModels() {
  const r = await fetch(`${BASE}/api/agent/models`)
  return r.json()
}

export async function fetchStats() {
  const r = await fetch(`${BASE}/api/logs/stats`)
  return r.json()
}

export async function fetchStatusHistory(component, hours = 24) {
  const r = await fetch(`${BASE}/api/status/history/${component}?hours=${hours}`)
  return r.json()
}

export async function fetchAlerts(limit = 20) {
  const r = await fetch(`${BASE}/api/alerts/recent?limit=${limit}`)
  return r.json()
}

export async function dismissAlert(alertId) {
  const r = await fetch(`${BASE}/api/alerts/${alertId}/dismiss`, { method: 'POST' })
  return r.json()
}

export async function dismissAllAlerts() {
  const r = await fetch(`${BASE}/api/alerts/dismiss-all`, { method: 'POST' })
  return r.json()
}

export async function fetchOperations({ limit = 50, offset = 0, status = 'all' } = {}) {
  const p = new URLSearchParams({ limit, offset, status })
  const r = await fetch(`${BASE}/api/logs/operations?${p}`)
  return r.json()
}

export async function fetchOperationDetail(opId) {
  const r = await fetch(`${BASE}/api/logs/operations/${opId}`)
  return r.json()
}

export async function fetchEscalations(limit = 50) {
  const r = await fetch(`${BASE}/api/logs/escalations?limit=${limit}`)
  return r.json()
}

export async function resolveEscalation(escId) {
  const r = await fetch(`${BASE}/api/logs/escalations/${escId}/resolve`, { method: 'POST' })
  return r.json()
}

// ── Memory (MuninnDB) ─────────────────────────────────────────────────────────

export async function fetchMemoryHealth() {
  const r = await fetch(`${BASE}/api/memory/health`)
  return r.json()
}

export async function fetchMemoryRecent(limit = 20) {
  const r = await fetch(`${BASE}/api/memory/recent?limit=${limit}`)
  return r.json()
}

export async function searchMemory(q, limit = 20) {
  const r = await fetch(`${BASE}/api/memory/search?q=${encodeURIComponent(q)}&limit=${limit}`)
  return r.json()
}

export async function activateMemory(context, maxResults = 5) {
  const r = await fetch(`${BASE}/api/memory/activate?max_results=${maxResults}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(context),
  })
  return r.json()
}

export async function deleteMemoryEngram(id) {
  const r = await fetch(`${BASE}/api/memory/${id}`, { method: 'DELETE' })
  return r.ok
}

export async function fetchMemoryPatterns() {
  const r = await fetch(`${BASE}/api/memory/patterns`)
  return r.json()
}

export async function fetchMemoryDocs() {
  const r = await fetch(`${BASE}/api/memory/docs`)
  return r.json()
}

export async function triggerDocFetch(component = null, force = false) {
  const r = await fetch(`${BASE}/api/memory/fetch-docs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ component, force }),
  })
  return r.json()
}

// ── WebSocket ────────────────────────────────────────────────────────────────

const WS_BASE = (() => {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}`
})()

export function createOutputStream(onMessage, onOpen, onClose) {
  const ws = new WebSocket(`${WS_BASE}/ws/output`)

  ws.onopen = () => {
    onOpen?.()
    // Keepalive ping every 20s
    ws._ping = setInterval(() => ws.readyState === 1 && ws.send('ping'), 20_000)
  }

  ws.onmessage = (e) => {
    try { onMessage(JSON.parse(e.data)) } catch { /* ignore pong */ }
  }

  ws.onclose = () => {
    clearInterval(ws._ping)
    onClose?.()
  }

  ws.onerror = (err) => console.error('WS error', err)

  return ws
}
