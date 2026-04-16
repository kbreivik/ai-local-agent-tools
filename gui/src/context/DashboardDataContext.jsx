/**
 * DashboardDataContext — single source of truth for all dashboard data.
 *
 * Replaces independent polling in SubBar, DashboardView, PlatformCoreCards,
 * ConnectionSectionCards, and VMHostsSection. Components subscribe to this
 * context instead of fetching their own data.
 *
 * Tiered refresh intervals:
 *   summary (containers+swarm+vms+external+vm_hosts): 60s
 *   external only (health dots, latency): 30s — most volatile, own fast fetch
 *   connections list: one-time + WS-invalidated (changes only on user edit)
 *   stats: 60s
 *   health: 90s
 *
 * On mount: fetch everything immediately, then stagger subsequent polls
 * so they don't all fire at once. External fires at t+0, summary at t+200ms,
 * stats at t+400ms, health at t+600ms.
 */
import { createContext, useContext, useState, useEffect, useRef, useCallback } from 'react'
import { authHeaders, fetchDashboardExternal, fetchStats, fetchHealth } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

// Minimum backend version this frontend requires.
// Increment when a new required endpoint is added (e.g. /api/dashboard/summary).
// Format: major.minor — patch versions don't break API contracts.
const MIN_BACKEND_VERSION = '2.22'

const DashboardDataContext = createContext(null)

export function DashboardDataProvider({ children }) {
  // Summary data (containers + swarm + VMs + vm_hosts + collectors)
  const [summary, setSummary]     = useState(null)
  const [summaryTs, setSummaryTs] = useState(null)

  // External (health dots — refreshes faster)
  const [external, setExternal]   = useState(null)

  // Connections (almost never changes — fetch once)
  const [connections, setConnections]   = useState(null)
  const [connVersion, setConnVersion]   = useState(0)  // bump to force refetch

  // Agent stats + platform health
  const [stats, setStats]   = useState(null)
  const [health, setHealth] = useState(null)

  // Loading flags — true until first fetch completes
  const [summaryLoading, setSummaryLoading]       = useState(true)
  const [externalLoading, setExternalLoading]     = useState(true)
  const [connectionsLoading, setConnectionsLoading] = useState(true)

  const [versionMismatch, setVersionMismatch] = useState(null)  // null | string message

  const mountedRef = useRef(true)
  useEffect(() => () => { mountedRef.current = false }, [])

  // ── Summary fetch (60s) ─────────────────────────────────────────────────────
  const fetchSummary = useCallback(async () => {
    try {
      const r = await fetch(`${BASE}/api/dashboard/summary`, { headers: authHeaders() })
      if (r.status === 404) {
        // Backend doesn't have this endpoint yet — version mismatch
        setVersionMismatch(
          'Backend missing /api/dashboard/summary — backend version too old. Rebuild backend.'
        )
        setSummaryLoading(false)
        return
      }
      if (!r.ok || !mountedRef.current) return
      const d = await r.json()
      setSummary(d)
      setSummaryTs(Date.now())
      setSummaryLoading(false)
      setVersionMismatch(prev => prev?.includes('summary') ? null : prev)
    } catch (_) {
      setSummaryLoading(false)
    }
  }, [])

  // ── External fetch (30s) ────────────────────────────────────────────────────
  const fetchExternal = useCallback(async () => {
    try {
      const d = await fetchDashboardExternal()
      if (!mountedRef.current) return
      setExternal(d)
      setExternalLoading(false)
    } catch (_) {}
  }, [])

  // ── Connections fetch (once + on connVersion bump) ──────────────────────────
  const fetchConnections = useCallback(async () => {
    try {
      const r = await fetch(`${BASE}/api/connections`, { headers: authHeaders() })
      if (!r.ok || !mountedRef.current) return
      const d = await r.json()
      setConnections(d.data || [])
      setConnectionsLoading(false)
    } catch (_) {}
  }, [])

  // ── Stats fetch (60s) ───────────────────────────────────────────────────────
  const refreshStats = useCallback(async () => {
    try {
      const d = await fetchStats()
      if (!mountedRef.current) return
      setStats(d)
    } catch (_) {}
  }, [])

  // ── Health fetch (90s) ──────────────────────────────────────────────────────
  const refreshHealth = useCallback(async () => {
    try {
      const d = await fetchHealth()
      if (!mountedRef.current) return
      setHealth(d)

      // Version gate: warn if backend is older than this frontend expects
      const backendVer = d?.version || ''
      if (backendVer && MIN_BACKEND_VERSION) {
        const [majB, minB] = backendVer.split('.').map(Number)
        const [majMin, minMin] = MIN_BACKEND_VERSION.split('.').map(Number)
        if (majB < majMin || (majB === majMin && minB < minMin)) {
          setVersionMismatch(
            `Backend v${backendVer} is older than frontend requires (v${MIN_BACKEND_VERSION}+). ` +
            `Dashboard data may be missing. Rebuild and redeploy the backend.`
          )
        } else {
          setVersionMismatch(null)
        }
      }
    } catch (_) {}
  }, [])

  // ── Mount: staggered initial loads ─────────────────────────────────────────
  useEffect(() => {
    fetchExternal()                                      // t+0ms
    setTimeout(fetchSummary, 200)                        // t+200ms
    setTimeout(refreshStats, 400)                        // t+400ms
    setTimeout(refreshHealth, 600)                       // t+600ms
    setTimeout(fetchConnections, 800)                    // t+800ms

    // Polling intervals
    const externalId    = setInterval(fetchExternal, 30_000)   // 30s
    const summaryId     = setInterval(fetchSummary, 60_000)    // 60s
    const statsId       = setInterval(refreshStats, 60_000)    // 60s
    const healthId      = setInterval(refreshHealth, 90_000)   // 90s
    // Connections: no interval — only refetch when connVersion changes

    // WebSocket: re-fetch stats after agent run completes
    const agentDoneHandler = () => refreshStats()
    window.addEventListener('agent-done', agentDoneHandler)

    // WS: immediately refresh summary when health changes are broadcast
    const wsHealthHandler = (e) => {
      try {
        const msg = JSON.parse(e.data || '{}')
        // Refresh summary on: health transitions, vm_action completions,
        // escalation_recorded, swarm replica changes
        if (['alert', 'vm_action', 'escalation_recorded', 'health_change'].includes(msg.type)) {
          fetchSummary()
          if (msg.type === 'vm_action') fetchSummary()  // double refresh for action feedback
        }
      } catch (_) {}
    }
    window.addEventListener('ws:message', wsHealthHandler)
    return () => {
      clearInterval(externalId)
      clearInterval(summaryId)
      clearInterval(statsId)
      clearInterval(healthId)
      window.removeEventListener('agent-done', agentDoneHandler)
      window.removeEventListener('ws:message', wsHealthHandler)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Connections: refetch when connVersion bumps ──────────────────────────────
  useEffect(() => {
    if (connVersion > 0) fetchConnections()
  }, [connVersion]) // eslint-disable-line react-hooks/exhaustive-deps

  const invalidateConnections = useCallback(() => {
    setConnVersion(v => v + 1)
  }, [])

  // ── Derived helpers ─────────────────────────────────────────────────────────
  // Provide the same shape as individual fetchDashboard* results for compatibility
  const containersData = summary?.containers ?? null
  const swarmData      = summary?.swarm      ?? null
  const vmsData        = summary?.vms        ?? null
  const vmHostsData    = summary?.vm_hosts   ?? null
  const windowsData    = summary?.windows    ?? null
  const collectorsData = summary?.collectors ?? {}
  const externalData   = external            ?? summary?.external ?? null

  return (
    <DashboardDataContext.Provider value={{
      // Raw summary
      summary,
      summaryTs,
      summaryLoading,
      summaryStale: summaryTs ? (Date.now() - summaryTs) > 90_000 : false,

      // Derived data (same shape as old individual endpoints)
      containersData,
      swarmData,
      vmsData,
      vmHostsData,
      windowsData,
      externalData,
      collectorsData,

      // Individual
      connections,
      connectionsLoading,
      stats,
      health,
      externalLoading,

      // Version gate
      versionMismatch,

      // Actions
      invalidateConnections,
      refreshSummary: fetchSummary,
      refreshExternal: fetchExternal,
    }}>
      {children}
    </DashboardDataContext.Provider>
  )
}

export function useDashboardData() {
  const ctx = useContext(DashboardDataContext)
  if (!ctx) throw new Error('useDashboardData must be used inside DashboardDataProvider')
  return ctx
}
