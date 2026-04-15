// Centralised API + WebSocket calls

const BASE = import.meta.env.VITE_API_BASE ?? ''  // empty = use Vite proxy

// ── Auth helpers ──────────────────────────────────────────────────────────────

export function getAuthToken() {
  // Token no longer stored in localStorage — auth via httpOnly cookie.
  // Kept for API script callers that still pass Bearer headers explicitly.
  return ''
}

export function authHeaders() {
  // Same-origin requests carry the httpOnly cookie automatically.
  // External API scripts should pass Authorization: Bearer <token> explicitly.
  return {}
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

// ── Settings ─────────────────────────────────────────────────────────────────

export async function fetchSettings() {
  const r = await fetch(`${BASE}/api/settings`, { headers: { ...authHeaders() } })
  if (!r.ok) throw new Error(`Settings fetch failed: HTTP ${r.status}`)
  const d = await r.json()
  return d.data?.settings ?? {}
}

export async function saveSettings(payload) {
  const r = await fetch(`${BASE}/api/settings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(payload),
  })
  if (!r.ok) { const d = await r.json(); throw new Error(d.detail || d.message || `HTTP ${r.status}`) }
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
  if (!r.ok) { const d = await r.json(); throw new Error(d.detail || d.message || `HTTP ${r.status}`) }
  return r.json()
}

export async function demoteSkill(skillName) {
  const r = await fetch(`${BASE}/api/skills/${encodeURIComponent(skillName)}/demote`, {
    method: 'POST',
    headers: { ...authHeaders() },
  })
  if (!r.ok) { const d = await r.json(); throw new Error(d.detail || d.message || `HTTP ${r.status}`) }
  return r.json()
}

export async function scrapSkill(skillName) {
  const r = await fetch(`${BASE}/api/skills/${encodeURIComponent(skillName)}`, {
    method: 'DELETE',
    headers: { ...authHeaders() },
  })
  if (!r.ok) { const d = await r.json(); throw new Error(d.detail || d.message || `HTTP ${r.status}`) }
  return r.status === 204 ? {} : r.json()
}

export async function purgeSkill(skillName) {
  const r = await fetch(`${BASE}/api/skills/${encodeURIComponent(skillName)}/purge`, {
    method: 'DELETE',
    headers: { ...authHeaders() },
  })
  if (!r.ok) { const d = await r.json(); throw new Error(d.detail || d.message || `HTTP ${r.status}`) }
  return r.status === 204 ? {} : r.json()
}

export async function restoreSkill(skillName) {
  const r = await fetch(`${BASE}/api/skills/${encodeURIComponent(skillName)}/restore`, {
    method: 'POST',
    headers: { ...authHeaders() },
  })
  if (!r.ok) { const d = await r.json(); throw new Error(d.detail || d.message || `HTTP ${r.status}`) }
  return r.json()
}

export async function regenerateSkill(skillName) {
  const r = await fetch(`${BASE}/api/skills/${encodeURIComponent(skillName)}/regenerate`, {
    method: 'POST',
    headers: { ...authHeaders() },
  })
  if (!r.ok) { const d = await r.json(); throw new Error(d.detail || d.message || `HTTP ${r.status}`) }
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

// ── Dashboard ─────────────────────────────────────────────────────────────────

export async function fetchDashboardContainers() {
  const r = await fetch(`${BASE}/api/dashboard/containers/agent01`, { headers: { ...authHeaders() } })
  return r.json()
}

export async function fetchDashboardSwarm() {
  const r = await fetch(`${BASE}/api/dashboard/containers/swarm`, { headers: { ...authHeaders() } })
  return r.json()
}

export async function fetchDashboardVMs() {
  const r = await fetch(`${BASE}/api/dashboard/vms`, { headers: { ...authHeaders() } })
  return r.json()
}

export async function fetchDashboardExternal() {
  const r = await fetch(`${BASE}/api/dashboard/external`, { headers: { ...authHeaders() } })
  return r.json()
}

export async function fetchCollectorData(component) {
  const r = await fetch(`${BASE}/api/status/collectors/${component}/data`, { headers: { ...authHeaders() } })
  if (!r.ok) return { status: 'error', data: null }
  return r.json()
}

export async function fetchContainerTags(containerId) {
  const r = await fetch(`${BASE}/api/dashboard/containers/${containerId}/tags`, {
    headers: { ...authHeaders() },
  })
  if (!r.ok) return { tags: [], error: `HTTP ${r.status}` }
  return r.json()
}

export async function fetchEntityHistory(entityId, hours = 48) {
  const r = await fetch(
    `${BASE}/api/entities/${encodeURIComponent(entityId)}/history?hours=${hours}`,
    { headers: { ...authHeaders() } }
  )
  if (!r.ok) return { changes: [], events: [] }
  return r.json()
}

export async function fetchResultRefs(sessionId = '') {
  const qs = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ''
  const r = await fetch(`${BASE}/api/logs/result-store${qs}`, { headers: { ...authHeaders() } })
  if (!r.ok) return { refs: [], count: 0 }
  return r.json()
}

export async function fetchResultRef(ref, offset = 0, limit = 20) {
  const r = await fetch(
    `${BASE}/api/logs/result-store/${encodeURIComponent(ref)}?offset=${offset}&limit=${limit}`,
    { headers: { ...authHeaders() } }
  )
  if (!r.ok) return null
  return r.json()
}

export async function fetchPipelineHealth() {
  const r = await fetch(`${BASE}/api/status/pipeline`, { headers: { ...authHeaders() } })
  if (!r.ok) return null
  return r.json()
}

export async function dashboardAction(path, body = null) {
  const r = await fetch(`${BASE}/api/dashboard/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!r.ok) {
    let msg = 'Action failed'
    try { const j = await r.json(); msg = j.error || j.detail || msg } catch (_) {}
    return { ok: false, error: msg }
  }
  return r.json()
}

// ── Ask agent (entity drawer) ────────────────────────────────────────────────

export async function askAgent(context, question, onChunk, onDone, onError) {
  try {
    const resp = await fetch(`${BASE}/api/agent/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ question, context }),
    })
    if (!resp.ok) {
      onError(`HTTP ${resp.status}`)
      return
    }
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const payload = line.slice(6)
        if (payload === '[DONE]') { onDone(); return }
        if (payload.startsWith('[ERROR]')) { onError(payload.slice(8)); return }
        onChunk(payload)
      }
    }
    onDone()
  } catch (e) {
    onError(e.message)
  }
}

export async function fetchAskSuggestions(status = '', section = '') {
  try {
    const r = await fetch(
      `${BASE}/api/agent/ask/suggestions?status=${encodeURIComponent(status)}&section=${encodeURIComponent(section)}`,
      { headers: authHeaders() }
    )
    if (!r.ok) return []
    const d = await r.json()
    return d.suggestions || []
  } catch {
    return []
  }
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

// ── Container log stream (SSE) ────────────────────────────────────────────────

export function createLogStream(containerId, tail = 200, onLine, onError) {
  const url = `${BASE}/api/dashboard/containers/${encodeURIComponent(containerId)}/logs/stream?tail=${tail}`
  const es = new EventSource(url, { withCredentials: true })
  es.onmessage = (e) => onLine(e.data)
  es.onerror = onError || (() => es.close())
  return es
}

// ── Unified log stream (SSE) ──────────────────────────────────────────────────

export function createUnifiedLogStream(tail = 200, onEvent, onError) {
  const url = `${BASE}/api/dashboard/logs/stream?tail=${tail}`
  const es = new EventSource(url, { withCredentials: true })
  es.onmessage = (e) => {
    try { onEvent(JSON.parse(e.data)) } catch { /* skip malformed */ }
  }
  es.onerror = onError || (() => es.close())
  return es
}
