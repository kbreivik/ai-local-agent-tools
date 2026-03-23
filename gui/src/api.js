// Centralised API + WebSocket calls

const BASE = import.meta.env.VITE_API_BASE ?? ''  // empty = use Vite proxy

// ── Auth helpers ──────────────────────────────────────────────────────────────

export function getAuthToken() {
  return localStorage.getItem('hp1_auth_token') || ''
}

export function authHeaders() {
  const token = getAuthToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// ── REST ─────────────────────────────────────────────────────────────────────

export async function fetchHealth() {
  const r = await fetch(`${BASE}/api/health`, { headers: { ...authHeaders() } })
  return r.json()
}

export async function fetchTools(refresh = false) {
  const r = await fetch(`${BASE}/api/tools${refresh ? '?refresh=true' : ''}`, { headers: { ...authHeaders() } })
  const d = await r.json()
  return d.tools ?? []
}

export async function fetchStatus() {
  const r = await fetch(`${BASE}/api/status`, { headers: { ...authHeaders() } })
  return r.json()
}

export async function fetchLogs({ status = 'all', limit = 100, offset = 0, tool = '' } = {}) {
  const p = new URLSearchParams({ status, limit, offset, ...(tool ? { tool } : {}) })
  const r = await fetch(`${BASE}/api/logs?${p}`, { headers: { ...authHeaders() } })
  return r.json()
}

export async function invokeTool(toolName, params = {}) {
  const r = await fetch(`${BASE}/api/tools/${toolName}/invoke`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(params),
  })
  return r.json()
}

// ── Skills ────────────────────────────────────────────────────────────────────

export async function fetchSkills(category = '') {
  const qs = category ? `?category=${encodeURIComponent(category)}` : ''
  const r = await fetch(`${BASE}/api/skills${qs}`, { headers: { ...authHeaders() } })
  const d = await r.json()
  return d.skills ?? []
}

export async function executeSkill(skillName, params = {}) {
  const r = await fetch(`${BASE}/api/skills/${encodeURIComponent(skillName)}/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(params),
  })
  return r.json()
}

export async function promoteSkill(skillName, domain) {
  const r = await fetch(`${BASE}/api/skills/${encodeURIComponent(skillName)}/promote`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ domain }),
  })
  if (!r.ok) throw new Error((await r.json()).message || `HTTP ${r.status}`)
  return r.json()
}

export async function demoteSkill(skillName) {
  const r = await fetch(`${BASE}/api/skills/${encodeURIComponent(skillName)}/demote`, {
    method: 'POST',
    headers: { ...authHeaders() },
  })
  if (!r.ok) throw new Error((await r.json()).message || `HTTP ${r.status}`)
  return r.json()
}

export async function scrapSkill(skillName) {
  const r = await fetch(`${BASE}/api/skills/${encodeURIComponent(skillName)}`, {
    method: 'DELETE',
    headers: { ...authHeaders() },
  })
  if (!r.ok) throw new Error((await r.json()).message || `HTTP ${r.status}`)
  return r.status === 204 ? {} : r.json()
}

export async function restoreSkill(skillName) {
  const r = await fetch(`${BASE}/api/skills/${encodeURIComponent(skillName)}/restore`, {
    method: 'POST',
    headers: { ...authHeaders() },
  })
  if (!r.ok) throw new Error((await r.json()).message || `HTTP ${r.status}`)
  return r.json()
}

export async function runAgent(task, sessionId = '') {
  const r = await fetch(`${BASE}/api/agent/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ task, session_id: sessionId }),
  })
  return r.json()
}

export async function sendConfirmation(sessionId, approved) {
  const r = await fetch(`${BASE}/api/agent/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ session_id: sessionId, approved }),
  })
  return r.json()
}

export async function sendClarification(sessionId, answer) {
  const r = await fetch(`${BASE}/api/agent/clarify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ session_id: sessionId, answer }),
  })
  return r.json()
}

export async function fetchModels() {
  const r = await fetch(`${BASE}/api/agent/models`, { headers: { ...authHeaders() } })
  return r.json()
}

export async function fetchStats() {
  const r = await fetch(`${BASE}/api/logs/stats`, { headers: { ...authHeaders() } })
  return r.json()
}

export async function fetchStatusHistory(component, hours = 24) {
  const r = await fetch(`${BASE}/api/status/history/${component}?hours=${hours}`, { headers: { ...authHeaders() } })
  return r.json()
}

export async function fetchAlerts(limit = 20) {
  const r = await fetch(`${BASE}/api/alerts/recent?limit=${limit}`, { headers: { ...authHeaders() } })
  return r.json()
}

export async function dismissAlert(alertId) {
  const r = await fetch(`${BASE}/api/alerts/${alertId}/dismiss`, { method: 'POST', headers: { ...authHeaders() } })
  return r.json()
}

export async function dismissAllAlerts() {
  const r = await fetch(`${BASE}/api/alerts/dismiss-all`, { method: 'POST', headers: { ...authHeaders() } })
  return r.json()
}

export async function fetchOperations({ limit = 50, offset = 0, status = 'all' } = {}) {
  const p = new URLSearchParams({ limit, offset, status })
  const r = await fetch(`${BASE}/api/logs/operations?${p}`, { headers: { ...authHeaders() } })
  return r.json()
}

export async function fetchOperationDetail(opId) {
  const r = await fetch(`${BASE}/api/logs/operations/${opId}`, { headers: { ...authHeaders() } })
  return r.json()
}

export async function fetchEscalations(limit = 50) {
  const r = await fetch(`${BASE}/api/logs/escalations?limit=${limit}`, { headers: { ...authHeaders() } })
  return r.json()
}

export async function resolveEscalation(escId) {
  const r = await fetch(`${BASE}/api/logs/escalations/${escId}/resolve`, { method: 'POST', headers: { ...authHeaders() } })
  return r.json()
}

// ── Memory (MuninnDB) ─────────────────────────────────────────────────────────

export async function fetchMemoryHealth() {
  const r = await fetch(`${BASE}/api/memory/health`, { headers: { ...authHeaders() } })
  return r.json()
}

export async function fetchMemoryRecent(limit = 20) {
  const r = await fetch(`${BASE}/api/memory/recent?limit=${limit}`, { headers: { ...authHeaders() } })
  return r.json()
}

export async function searchMemory(q, limit = 20) {
  const r = await fetch(`${BASE}/api/memory/search?q=${encodeURIComponent(q)}&limit=${limit}`, { headers: { ...authHeaders() } })
  return r.json()
}

export async function activateMemory(context, maxResults = 5) {
  const r = await fetch(`${BASE}/api/memory/activate?max_results=${maxResults}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(context),
  })
  return r.json()
}

export async function deleteMemoryEngram(id) {
  const r = await fetch(`${BASE}/api/memory/${id}`, { method: 'DELETE', headers: { ...authHeaders() } })
  return r.ok
}

export async function fetchMemoryPatterns() {
  const r = await fetch(`${BASE}/api/memory/patterns`, { headers: { ...authHeaders() } })
  return r.json()
}

export async function fetchMemoryDocs() {
  const r = await fetch(`${BASE}/api/memory/docs`, { headers: { ...authHeaders() } })
  return r.json()
}

export async function triggerDocFetch(component = null, force = false) {
  const r = await fetch(`${BASE}/api/memory/fetch-docs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ component, force }),
  })
  return r.json()
}

export async function submitFeedback(sessionId, rating) {
  const r = await fetch(`${BASE}/api/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ session_id: sessionId, rating }),
  })
  return r.json()
}

// ── WebSocket ────────────────────────────────────────────────────────────────

const WS_BASE = (() => {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}`
})()

export function createOutputStream(onMessage, onOpen, onClose) {
  const token = getAuthToken()
  const wsUrl = `${WS_BASE}/ws/output${token ? `?token=${token}` : ''}`
  const ws = new WebSocket(wsUrl)

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
