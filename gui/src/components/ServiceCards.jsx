/**
 * ServiceCards — four-section infrastructure dashboard.
 * Sections: Containers·agent-01, Containers·Swarm, VMs·Proxmox, External Services
 * Cards expand inline on click; one open at a time globally.
 * Accepts activeFilters prop to show/hide sections (containers_local, containers_swarm, vms, external).
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import {
  fetchDashboardContainers, fetchDashboardSwarm,
  fetchDashboardVMs, fetchDashboardExternal,
  fetchCollectorData, dashboardAction, fetchContainerTags, createLogStream,
  authHeaders,
} from '../api'
import { compareSemver, compareBuildTag } from '../utils/versionCheck'
import { useOptions } from '../context/OptionsContext'

const POLL_MS = 30_000

// Filter loopback/placeholder IPs from compact display — show real addresses only
function _displayIp(ip) {
  if (!ip) return ''
  const host = ip.split(':')[0]
  if (host === '127.0.0.1' || host === 'localhost' || host === '0.0.0.0') return ''
  return ip
}

// Format port mapping for compact display: "8000→8000/tcp" → "8000"
function _compactPort(portStr) {
  if (!portStr) return ''
  const host = portStr.split('→')[0]?.trim()
  return host ? `:${host}` : ''
}

// Format container ip:port for compact — filter loopback, show first mapping
function _containerNet(c) {
  // Try ip_port first (from collector) — _displayIp strips loopback
  const filtered = _displayIp(c.ip_port)
  if (filtered) return filtered
  // Try ports array — strip loopback prefix, keep port
  if (c.ports?.length) {
    for (const p of c.ports) {
      const host = p.split('→')[0]?.trim()
      if (host && !host.startsWith('127.') && !host.startsWith('0.0.0')) return host
      // If loopback, show just the port number prefixed with :
      const portOnly = p.split(':').pop()?.split('/')[0]?.split('→')[0]?.trim()
      if (portOnly && /^\d+$/.test(portOnly)) return `:${portOnly}`
    }
  }
  return ''
}

const UNIFI_FILTER_FIELDS = [
  { key: 'type_label', label: 'type' },
  { key: 'state',      label: 'status' },
]

const FG_FILTER_FIELDS = [
  { key: 'type',   label: 'type' },
  { key: 'status', label: 'status' },
]

const BASE = import.meta.env.VITE_API_BASE ?? ''

// Platform slug → connection test helper
async function testConnectionByPlatform(platformSlug) {
  // Map external service slugs to connection platform names
  const SLUG_TO_PLATFORM = { proxmox: 'proxmox', fortigate: 'fortigate', truenas: 'truenas', lm_studio: null }
  const platform = SLUG_TO_PLATFORM[platformSlug] ?? platformSlug
  if (!platform) return { status: 'error', message: 'No connection for this service' }
  try {
    const lr = await fetch(`${BASE}/api/connections?platform=${platform}`, { headers: { ...authHeaders() } })
    if (!lr.ok) return { status: 'error', message: 'Failed to fetch connections' }
    const conns = (await lr.json()).data || []
    const conn = conns.find(c => c.host && c.enabled !== false)
    if (!conn) return { status: 'error', message: 'No connection configured for this platform' }
    const tr = await fetch(`${BASE}/api/connections/${conn.id}/test`, { method: 'POST', headers: { ...authHeaders() } })
    return await tr.json()
  } catch (e) {
    return { status: 'error', message: String(e) }
  }
}

// ── Toast system ───────────────────────────────────────────────────────────────

function Toast({ toasts }) {
  return (
    <div className="fixed bottom-4 right-4 flex flex-col gap-2 z-50">
      {toasts.map(t => (
        <div key={t.id} className={`px-4 py-2 rounded text-sm text-white shadow-lg ${t.type === 'error' ? 'bg-red-700' : 'bg-green-700'}`}>
          {t.msg}
        </div>
      ))}
    </div>
  )
}

function useToast() {
  const [toasts, setToasts] = useState([])
  const show = useCallback((msg, type = 'success') => {
    const id = Date.now()
    setToasts(prev => [...prev, { id, msg, type }])
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 3000)
  }, [])
  return { toasts, show }
}

// ── Visual helpers ─────────────────────────────────────────────────────────────

const DOT_CLS = {
  green: 'bg-green-500 ring-1 ring-green-400/40',
  amber: 'bg-amber-500 ring-1 ring-amber-400/40',
  red:   'bg-red-500 ring-1 ring-red-400/60 animate-pulse',
  grey:  'bg-gray-600',
}

const CARD_STATE = {
  healthy: { bg: 'bg-[#131325]', border: 'border-[#1e1e3a]', nameCls: 'text-gray-100' },
  warn:    { bg: 'bg-[#161008]', border: 'border-[#3a2a0a]', nameCls: 'text-amber-200' },
  error:   { bg: 'bg-[#130808]', border: 'border-[#3a0e0e]', nameCls: 'text-red-300' },
  unknown: { bg: 'bg-[#131325]', border: 'border-[#222]',    nameCls: 'text-gray-400' },
}

function cardState(dot) {
  if (dot === 'red')   return CARD_STATE.error
  if (dot === 'amber') return CARD_STATE.warn
  if (dot === 'grey')  return CARD_STATE.unknown
  return CARD_STATE.healthy
}

function Dot({ color }) {
  return <span className={`inline-block w-[6px] h-[6px] rounded-full flex-shrink-0 ${DOT_CLS[color] || DOT_CLS.grey}`} />
}

function PullBadge({ lastPullAt }) {
  if (!lastPullAt) return <span className="text-[9px] px-1.5 py-px rounded bg-[#2a1010] text-red-400 border border-[#3a1818]">↓ unknown</span>
  const age = Math.max(0, Date.now() - new Date(lastPullAt).getTime())
  const hours = age / 3600000
  if (hours < 24) {
    const mins = Math.round(age / 60000)
    const label = mins < 1 ? 'just now' : mins < 60 ? `${mins} min ago` : `${Math.round(hours)}h ago`
    return <span className="text-[9px] px-1.5 py-px rounded bg-[#0d2a0d] text-green-400 border border-[#1a3a1a]">↓ {label}</span>
  }
  const days = Math.round(hours / 24)
  const cls = days <= 7
    ? 'bg-[#2a200a] text-amber-400 border-[#3a2e12]'
    : 'bg-[#2a1010] text-red-400 border-[#3a1818]'
  return <span className={`text-[9px] px-1.5 py-px rounded border ${cls}`}>↓ {days}d ago</span>
}

function _fmtBytes(bytes) {
  if (bytes == null) return null
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`
  if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(0)} KB`
  return `${bytes} B`
}

function _fgBytes(bytes) {
  if (!bytes) return '—'
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`
  if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(0)} KB`
  return `${bytes} B`
}

function VolBar({ vol }) {
  const name = vol.name || vol.mountpoint
  const used = _fmtBytes(vol.used_bytes)
  if (!vol.used_bytes && !vol.total_bytes) {
    return <div className="text-[10px] text-gray-600 mb-1">{name}</div>
  }
  if (!vol.total_bytes) {
    // Only usage known (Docker volumes) — show name + size badge, no bar
    return (
      <div className="flex justify-between text-[10px] text-gray-600 mb-[5px]" title={`${name}: ${used} used`}>
        <span>{name}</span>
        <span className="text-gray-700 font-mono">{used}</span>
      </div>
    )
  }
  const totalFmt = _fmtBytes(vol.total_bytes)
  // used_bytes=0 means Proxmox list-level fallback (no guest agent) — show capacity only
  if (!vol.used_bytes) {
    return (
      <div className="flex justify-between text-[10px] text-gray-600 mb-[5px]" title={`${name}: ${totalFmt} provisioned`}>
        <span>{name}</span>
        <span className="text-gray-700 font-mono">{totalFmt}</span>
      </div>
    )
  }
  const pct = Math.round((vol.used_bytes / vol.total_bytes) * 100)
  const fillCls = pct > 80 ? 'bg-red-500' : pct > 60 ? 'bg-amber-500' : 'bg-violet-500'
  return (
    <div className="mb-[5px]" title={`${name}: ${used} / ${totalFmt} (${pct}%)`}>
      <div className="flex justify-between text-[10px] text-gray-600 mb-[2px]">
        <span>{name}</span>
        <span className="text-gray-700">{used} / {totalFmt}</span>
      </div>
      <div className="h-[4px] rounded bg-[#0a0a18] overflow-hidden">
        <div className={`h-full rounded ${fillCls}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function ActionBtn({ label, onClick, variant = 'default', loading, disabled }) {
  const base = 'text-[10px] px-2 py-1 rounded border w-full text-left disabled:opacity-40 transition-colors'
  const variants = {
    primary: 'bg-violet-600/20 text-violet-300 border-violet-500/30 hover:bg-violet-600/30',
    urgent:  'bg-red-900/30 text-red-400 border-red-700/40 hover:bg-red-900/50',
    default: 'bg-[#0d0d1a] text-gray-500 border-[#222] hover:text-gray-300',
    danger:  'bg-transparent text-red-500/40 border-red-900/20 hover:text-red-500/70',
  }
  return (
    <button
      className={`${base} ${variants[variant]}`}
      onClick={onClick}
      disabled={disabled || loading}
    >
      {loading ? '…' : label}
    </button>
  )
}

// ── Confirm dialog ─────────────────────────────────────────────────────────────

function useConfirm() {
  const [pending, setPending] = useState(null)
  const confirm = useCallback((msg) => new Promise(res => setPending({ msg, res })), [])
  const resolve = useCallback((val) => setPending(p => { p?.res(val); return null }), [])
  return { pending, confirm, resolve }
}

// ── Generic card shell ──────────────────────────────────────────────────────────

const _SLOT_COLORS = ['#00aa44','#00c8ee','#cc8800','#7c6af7']

function InfraCard({ cardKey, openKeys, setOpenKeys, lastOpenedKey, setLastOpenedKey, forceExpanded, dot, name, sub, net, uptime, collapsed, expanded, compareMode, compareSet, onCompareAdd, entityForCompare }) {
  const isOpen = forceExpanded || (openKeys || new Set()).has(cardKey)
  const subText = sub ? (typeof sub === 'object' ? sub.text : sub) : ''
  const compareId = entityForCompare?.id
  const slotIdx = compareId ? (compareSet || []).findIndex(e => e.id === compareId) : -1
  const isSelected = slotIdx >= 0
  const [hovered, setHovered] = useState(false)

  const toggle = (e) => {
    if ((e.ctrlKey || e.metaKey) && compareMode && entityForCompare && onCompareAdd) {
      e.stopPropagation()
      onCompareAdd(entityForCompare)
      return
    }

    if (e.shiftKey && lastOpenedKey) {
      // Shift+click: expand range between lastOpenedKey and this cardKey
      const section = e.currentTarget.closest('[data-section-key]')
      if (section) {
        const cards = [...section.querySelectorAll('[data-card-key]')]
        const keys = cards.map(el => el.getAttribute('data-card-key'))
        const lastIdx = keys.indexOf(lastOpenedKey)
        const thisIdx = keys.indexOf(cardKey)
        if (lastIdx >= 0 && thisIdx >= 0) {
          const [from, to] = lastIdx < thisIdx ? [lastIdx, thisIdx] : [thisIdx, lastIdx]
          const rangeKeys = keys.slice(from, to + 1)
          setOpenKeys(prev => {
            const next = new Set(prev)
            rangeKeys.forEach(k => next.add(k))
            return next
          })
          return
        }
      }
    }

    // Normal click: toggle this card
    setOpenKeys(prev => {
      const next = new Set(prev)
      if (next.has(cardKey)) {
        next.delete(cardKey)
      } else {
        next.add(cardKey)
        setLastOpenedKey?.(cardKey)
      }
      return next
    })
  }

  return (
    <div
      data-card-key={cardKey}
      className={`border rounded-lg cursor-pointer transition-all ${isOpen ? 'border-violet-500 shadow-[0_0_0_1px_rgba(124,106,247,0.15)]' : ''}`}
      style={{
        background: isSelected ? `${_SLOT_COLORS[slotIdx]}0d` : 'var(--bg-2)',
        borderColor: isOpen ? undefined : 'var(--border)',
        padding: isOpen ? '10px' : '8px 12px',
        transition: 'border-color 0.15s ease, padding 0.15s ease',
        outline: isSelected ? `1px solid ${_SLOT_COLORS[slotIdx]}` : 'none',
        outlineOffset: isSelected ? -1 : 0,
        position: 'relative',
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={toggle}
    >
      {isSelected && (
        <div style={{
          position: 'absolute', top: 5, right: 5, width: 15, height: 15, borderRadius: 2,
          background: _SLOT_COLORS[slotIdx], color: '#05060a',
          fontFamily: 'var(--font-mono)', fontSize: 8, fontWeight: 'bold',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 2,
        }}>{slotIdx + 1}</div>
      )}
      {compareMode && !isSelected && (
        <span style={{
          position: 'absolute', bottom: 3, right: 6,
          fontFamily: 'var(--font-mono)', fontSize: 7,
          color: 'var(--text-3)', letterSpacing: '0.04em',
          opacity: hovered ? 1 : 0, transition: 'opacity 0.1s', pointerEvents: 'none',
        }}>ctrl+click</span>
      )}
      {/* Header row — always visible, click to toggle */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 min-w-0">
          <Dot color={dot} />
          <span className="text-[12px] font-semibold truncate" style={{ color: 'var(--text-1)' }}>{name}</span>
          <span className="text-[10px]" style={{ color: 'var(--text-3)' }}>{isOpen ? '▾' : '▸'}</span>
        </div>
        {subText && <span className="text-[10px] mono shrink-0 ml-2" style={{ color: 'var(--text-3)' }}>{subText}</span>}
      </div>

      {/* Row 2 — IP + uptime (collapsed only) */}
      {!isOpen && (net || uptime) && (
        <div className="flex items-center justify-between mt-0.5">
          {net ? <span className="text-[10px] mono" style={{ color: 'var(--text-3)' }}>{net}</span> : <span />}
          {uptime && <span className="text-[10px]" style={{ color: 'var(--text-3)' }}>↑ {uptime}</span>}
        </div>
      )}

      {/* Collapsed problem badge */}
      {!isOpen && collapsed}

      {/* Expanded content */}
      {isOpen && (
        <div className="mt-1" onClick={e => e.stopPropagation()}>
          {expanded}
        </div>
      )}
    </div>
  )
}

// ── Section wrapper ────────────────────────────────────────────────────────────

function Section({ label, meta, errorCount, dot, auth, host, runningCount, totalCount, issueCount, filterBar, children, compareMode, compareSet, onCompareAdd, entityForCompare, countLabels, cardMinWidth: sectionMinWidth }) {
  const { cardMinWidth: globalMin, cardMaxWidth } = useOptions()
  const _min = sectionMinWidth ?? globalMin ?? 300
  const _max = cardMaxWidth ? `${cardMaxWidth}px` : '1fr'
  const NAME_W = 174
  const isCluster = dot != null  // new two-row header when dot/auth/host are provided

  if (!isCluster) {
    // Legacy compact header (Containers, External Services)
    return (
      <div>
        <div className="flex items-baseline gap-2 mb-2">
          <span className="text-[11px] text-gray-600 uppercase tracking-wider">{label}</span>
          {meta && <span className="text-[10px] text-gray-800">{meta}</span>}
          {errorCount > 0 && <span className="text-[10px] text-red-500/60">{errorCount} issue{errorCount !== 1 ? 's' : ''}</span>}
        </div>
        {filterBar}
        <div className="grid gap-2" data-section-key={label} style={{
          gridTemplateColumns: `repeat(auto-fill, minmax(${_min}px, ${_max}))`,
          ...(cardMaxWidth ? { justifyContent: 'start' } : {}),
        }}>
          {children}
        </div>
      </div>
    )
  }

  // New two-row cluster header with collapsible grid
  const [sectionExpanded, setSectionExpanded] = useState(true)
  useEffect(() => {
    const onExpand = () => setSectionExpanded(true)
    const onCollapse = () => setSectionExpanded(false)
    window.addEventListener('ds:expand-all-sections', onExpand)
    window.addEventListener('ds:collapse-all-sections', onCollapse)
    return () => {
      window.removeEventListener('ds:expand-all-sections', onExpand)
      window.removeEventListener('ds:collapse-all-sections', onCollapse)
    }
  }, [])
  const dotColor = dot === 'green' ? 'var(--green)' : dot === 'red' ? 'var(--red)' : 'var(--amber)'
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 2, overflow: 'hidden', marginBottom: 4 }}>
      {/* Row 1: identity | gap | counts | auth — click to collapse */}
      <div
        onClick={(e) => {
          if ((e.ctrlKey || e.metaKey) && compareMode && onCompareAdd && entityForCompare) {
            e.stopPropagation()
            onCompareAdd(entityForCompare)
            return
          }
          setSectionExpanded(prev => !prev)
        }}
        style={{ display: 'flex', alignItems: 'stretch', background: 'var(--bg-1)',
                  borderBottom: '1px solid var(--border)', minHeight: 36,
                  cursor: 'pointer', userSelect: 'none' }}>
        {/* Name zone */}
        <div style={{ width: NAME_W, flexShrink: 0, display: 'flex', alignItems: 'center',
                      gap: 9, padding: '0 8px 0 10px',
                      borderRight: '2px solid rgba(255,255,255,0.11)' }}>
          <div style={{ width: 10, height: 10, borderRadius: '50%', flexShrink: 0,
                        background: dotColor, boxShadow: `0 0 7px ${dotColor}` }} />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.1em',
                         textTransform: 'uppercase', color: 'var(--text-1)', whiteSpace: 'nowrap',
                         overflow: 'hidden', textOverflow: 'ellipsis', flex: 1 }}>{label}</span>
          <span style={{
            fontSize: 8, color: 'var(--text-3)',
            transition: 'transform 0.1s', display: 'flex', alignItems: 'center',
            transform: sectionExpanded ? 'rotate(90deg)' : 'none',
          }}>▶</span>
        </div>
        <div style={{ flex: 1 }} />
        {[
          { num: runningCount, lbl: (countLabels || [])[0] || 'running', color: 'var(--green)' },
          { num: totalCount,   lbl: (countLabels || [])[1] || 'total',   color: 'var(--text-1)' },
          { num: issueCount,   lbl: (countLabels || [])[2] || 'issues',  color: issueCount > 0 ? 'var(--red)' : 'var(--text-3)' },
        ].map(({ num, lbl, color }) => (
          <div key={lbl} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center',
                                   justifyContent: 'center', padding: '0 14px', minWidth: 52,
                                   borderLeft: '1px solid var(--border)', gap: 1 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 14, lineHeight: 1, color }}>{num}</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--text-3)',
                           letterSpacing: '0.06em', textTransform: 'uppercase' }}>{lbl}</span>
          </div>
        ))}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '0 16px',
                      borderLeft: '1px solid var(--border)', flexShrink: 0 }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-2)',
                         letterSpacing: '0.08em' }}>{auth}</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--text-3)' }}>{host}</span>
        </div>
      </div>

      {/* Row 2: spacer + filterBar — always visible, clicks don't collapse */}
      {filterBar && (
        <div onClick={e => e.stopPropagation()} style={{ display: 'flex', alignItems: 'stretch',
                      background: 'var(--bg-0)', borderBottom: '1px solid var(--border)' }}>
          <div style={{ width: NAME_W, flexShrink: 0,
                        borderRight: '2px solid rgba(255,255,255,0.07)' }} />
          <div style={{ flex: 1, overflow: 'hidden', padding: '6px 10px' }}>{filterBar}</div>
        </div>
      )}

      {/* Children grid — collapses */}
      <div style={{
        overflow: 'hidden',
        maxHeight: sectionExpanded ? 9999 : 0,
        opacity: sectionExpanded ? 1 : 0,
        transition: 'max-height 0.25s ease, opacity 0.2s ease',
      }}>
        <div className="grid gap-2" data-section-key={label} style={{
          padding: 2, background: 'var(--bg-0)',
          gridTemplateColumns: `repeat(auto-fill, minmax(${_min}px, ${_max}))`,
          ...(cardMaxWidth ? { justifyContent: 'start' } : {}),
        }}>
          {children}
        </div>
      </div>
    </div>
  )
}

// ── Stats row ──────────────────────────────────────────────────────────────────

function StatRow({ stats }) {
  return (
    <div className="flex gap-2 mb-2">
      {stats.map(({ v, l, color }) => (
        <div key={l} className="flex-1 bg-[#0d0d1a] rounded p-1.5">
          <div className={`text-[12px] font-semibold ${color || 'text-gray-300'}`}>{v ?? '—'}</div>
          <div className="text-[9px] text-gray-700 mt-px">{l}</div>
        </div>
      ))}
    </div>
  )
}

function Divider() {
  return <div className="h-px bg-[#1a1a30] my-2" />
}

function Actions({ buttons }) {
  return <div className="flex flex-col gap-1.5 mt-1.5">{buttons}</div>
}

// ── Container card ─────────────────────────────────────────────────────────────

function ContainerCardExpanded({ c, isSwarm, onAction, confirm, showToast, onTagsLoaded, onTab }) {
  const [loading, setLoading] = useState({})
  const [scaleOpen, setScaleOpen] = useState(false)
  const [scaleVal, setScaleVal] = useState(1)
  const mounted = useRef(true)
  useEffect(() => () => { mounted.current = false }, [])

  const [logsOpen, setLogsOpen] = useState(false)
  const [logLines, setLogLines] = useState([])
  const [logsPaused, setLogsPaused] = useState(false)
  const [popoutOpen, setPopoutOpen] = useState(false)
  const logsPausedRef = useRef(false)
  const esRef = useRef(null)
  const logsScrollRef = useRef(null)
  const popoutScrollRef = useRef(null)

  useEffect(() => () => { esRef.current?.close() }, [])

  useEffect(() => {
    if (!logsPaused) {
      if (logsScrollRef.current) {
        logsScrollRef.current.scrollTop = logsScrollRef.current.scrollHeight
      }
      if (popoutScrollRef.current) {
        popoutScrollRef.current.scrollTop = popoutScrollRef.current.scrollHeight
      }
    }
  }, [logLines, logsPaused])

  const [tags, setTags]             = useState([])
  const [tagsLoading, setTagsLoading] = useState(false)
  const [tagsError, setTagsError]   = useState(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [selectedTag, setSelectedTag] = useState('')
  const [versionPickerOpen, setVersionPickerOpen] = useState(false)
  const [updateStatus, setUpdateStatus] = useState(null)

  useEffect(() => {
    if (!c.image?.startsWith('ghcr.io/')) return
    fetch(`${BASE}/api/dashboard/update-status`, { headers: { ...authHeaders() } })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (mounted.current && d) setUpdateStatus(d) })
      .catch(() => {})
  }, [c.image])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (isSwarm || !c.image?.startsWith('ghcr.io/')) return
    setTagsLoading(true)
    fetchContainerTags(c.id)
      .then(data => {
        if (!mounted.current) return
        setTagsLoading(false)
        if (data.error && !data.tags?.length) {
          setTagsError(data.error)
          return
        }
        // Filter out versions before 1.12.2 (broken self-update, no sidecar recreate)
        const MIN_SAFE = [1, 12, 2]
        const t = (data.tags || []).filter(v => {
          const parts = v.split('.').map(Number)
          for (let i = 0; i < 3; i++) {
            if ((parts[i] || 0) < MIN_SAFE[i]) return false
            if ((parts[i] || 0) > MIN_SAFE[i]) return true
          }
          return true  // equal is ok
        })
        setTags(t)
        setTagsError(null)
        if (t[0]) {
          setSelectedTag(t[0])
          onTagsLoaded?.(c.id, t[0])
        }
      })
      .catch(err => {
        if (!mounted.current) return
        setTagsLoading(false)
        setTagsError(err?.message || 'fetch failed')
      })
  // onTagsLoaded intentionally excluded — it's a stable useCallback from the parent;
  // including it would cause re-fetching on every render without behavior change.
  }, [c.id, c.image, isSwarm])  // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (key, path, body, msg) => {
    if (msg) {
      const ok = await confirm(msg)
      if (!ok) return
    }
    setLoading(l => ({ ...l, [key]: true }))
    const r = await dashboardAction(path, body)
    if (!mounted.current) return
    setLoading(l => ({ ...l, [key]: false }))
    if (!r.ok) showToast(r.error || 'Action failed', 'error')
    else { showToast('Done'); onAction() }
  }

  const openLogs = () => {
    if (logsOpen) {
      esRef.current?.close()
      esRef.current = null
      setLogLines([])
      setLogsOpen(false)
      return
    }
    setLogLines([])
    setLogsPaused(false)
    logsPausedRef.current = false
    setLogsOpen(true)
    esRef.current = createLogStream(
      c.id,
      200,
      (line) => {
        if (logsPausedRef.current) return
        setLogLines(prev => [...prev, line].slice(-500))
      },
      () => { esRef.current?.close(); esRef.current = null; setLogsOpen(false) },
    )
  }

  const pauseLogs = () => {
    const next = !logsPaused
    setLogsPaused(next)
    logsPausedRef.current = next
  }

  const pullPath = isSwarm ? `services/${c.name}/pull` : `containers/${c.id}/pull`
  const pullColor = c.last_pull_at && (Date.now() - new Date(c.last_pull_at).getTime()) > 7 * 86400000 ? 'urgent' : 'primary'

  return (
    <>
      <StatRow stats={[
        { v: c.last_pull_at ? _pulledAgo(c.last_pull_at) : 'unknown', l: 'Pulled', color: !c.last_pull_at ? 'text-red-400' : 'text-gray-300' },
        { v: c.uptime || (c.running_replicas != null ? `${c.running_replicas}/${c.desired_replicas}` : '—'), l: isSwarm ? 'Replicas' : 'Uptime' },
      ]} />
      {c.ports?.length > 0 && (
        <div className="text-[10px] text-[#4a6a9a] font-mono mb-1.5">
          <span className="text-[9px] text-gray-700">ports </span>{c.ports.join(' · ')}
        </div>
      )}
      {/* Reachable endpoint — from ip_port (VM LAN IP + host port) */}
      {(() => {
        const ep = c.ip_port ? _displayIp(c.ip_port) : ''
        if (!ep) return null
        const href = `http://${ep}`
        return (
          <div className="text-[10px] font-mono mb-1.5">
            <span className="text-[9px] text-gray-700">endpoint </span>
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[#00c8ee] hover:underline"
              onClick={e => e.stopPropagation()}
            >
              {ep}
            </a>
          </div>
        )
      })()}
      {/* Docker networks */}
      {c.networks?.length > 0 && (
        <div className="text-[10px] text-[#4a6a9a] font-mono mb-1.5">
          <span className="text-[9px] text-gray-700">networks </span>
          {c.networks.join(' · ')}
        </div>
      )}
      {/* Internal Docker IPs — dimmed, secondary info */}
      {c.ip_addresses?.length > 0 && (
        <div className="text-[10px] text-gray-700 font-mono mb-1.5">
          <span className="text-[9px] text-gray-800">int.ips </span>
          {c.ip_addresses.join(' · ')}
        </div>
      )}
      <Divider />
      {(c.volumes || []).map(v => <VolBar key={v.name || v.mountpoint} vol={v} />)}
      {c.volumes?.length > 0 && <Divider />}
      {!isSwarm && c.image?.startsWith('ghcr.io/') && (() => {
        const severity = (c.running_version && tags[0])
          ? compareSemver(c.running_version, tags[0])
          : null
        const hasUpdate = severity === 'major' || severity === 'minor' || severity === 'patch'

        return (
          <>
            <Divider />
            {/* Running version info rows */}
            {c.running_version && (
              <div className="flex justify-between text-[9px] mb-0.5">
                <span className="text-gray-700">Running</span>
                <span className="text-gray-500 font-mono">{c.running_version}</span>
              </div>
            )}
            {c.built_at && (
              <div className="flex justify-between text-[9px] mb-0.5">
                <span className="text-gray-700">Built</span>
                <span className="text-gray-500 font-mono">{c.built_at.slice(0, 10)}</span>
              </div>
            )}
            {/* Status badge */}
            {c.running_version && (
              <div className="flex justify-between text-[9px] mb-1.5">
                <span className="text-gray-700">Status</span>
                {tagsLoading
                  ? <span className="text-gray-700">…</span>
                  : tagsError
                  ? <span className="text-gray-700">version check unavailable</span>
                  : !tags.length
                  // No semver tags on GHCR — fall back to digest comparison
                  ? updateStatus?.update_available === false
                    ? <span className="text-[9px] px-1.5 py-px rounded bg-[#0d1f0d] text-green-400 border border-[#1a3a1a]">✓ latest</span>
                    : updateStatus?.update_available === true
                    ? <span className="text-[9px] px-1.5 py-px rounded bg-[#2a1e05] text-amber-400 border border-[#3d2d0a]">⬆ update available</span>
                    : <span className="text-gray-700">no versioned tags</span>
                  : severity === 'current'
                  ? <span className="text-[9px] px-1.5 py-px rounded bg-[#0d1f0d] text-green-400 border border-[#1a3a1a]">✓ latest</span>
                  : severity === 'ahead'
                  // Running version is NEWER than highest known tag (e.g. GHCR pagination was stale)
                  // Trust the digest comparison from update-status as the authoritative signal
                  ? updateStatus?.update_available === false
                    ? <span className="text-[9px] px-1.5 py-px rounded bg-[#0d1f0d] text-green-400 border border-[#1a3a1a]">✓ latest</span>
                    : updateStatus?.update_available === true
                    ? <span className="text-[9px] px-1.5 py-px rounded bg-[#2a1e05] text-amber-400 border border-[#3d2d0a]">⬆ update available</span>
                    : <span className="text-gray-700">✓ ahead of tagged</span>
                  : hasUpdate
                  ? <span className={`text-[9px] px-1.5 py-px rounded border ${severity === 'major' ? 'bg-[#1a0808] text-red-400 border-[#3a1010]' : 'bg-[#2a1e05] text-amber-400 border-[#3d2d0a]'}`}>
                      ⬆ {tags[0]} {severity}
                    </span>
                  : <span className="text-gray-700">—</span>
                }
              </div>
            )}

            {/* Auto-update toggle — only for agent container */}
            {c.name?.includes('hp1_agent') && c.image?.startsWith('ghcr.io/') && (
              <AutoUpdateToggle />
            )}

            {/* Update drawer trigger — only when update available */}
            {hasUpdate && !tagsError && (
              <>
                <ActionBtn
                  key="update"
                  label={drawerOpen ? '✕ Cancel Update' : `⬆ Update Available — Choose Version`}
                  variant={severity === 'major' ? 'urgent' : 'primary'}
                  onClick={() => setDrawerOpen(o => !o)}
                />
                {drawerOpen && (
                  <div className="mt-1 mb-2 bg-[#0a0a15] border border-[#2a2440] rounded-md p-2">
                    <div className="text-[9px] text-gray-700 mb-1.5">Select version to pull:</div>
                    <select
                      className="w-full bg-[#0d0d1a] border border-[#2a2a4a] text-gray-300 rounded text-[10px] px-1.5 py-1 mb-1.5"
                      value={selectedTag}
                      onChange={e => setSelectedTag(e.target.value)}
                    >
                      {tags.map(t => (
                        <option key={t} value={t}>
                          {t}{t === c.running_version || `v${t}` === `v${c.running_version}` ? ' ← running' : ''}
                        </option>
                      ))}
                    </select>
                    <ActionBtn
                      key="pull-versioned"
                      label={`↓ Pull ${selectedTag}`}
                      variant="primary"
                      loading={loading['pull-versioned']}
                      onClick={() => {
                        act('pull-versioned', `containers/${c.id}/pull?tag=${selectedTag}`, null, null)
                        setDrawerOpen(false)
                      }}
                    />
                  </div>
                )}
              </>
            )}

            {/* Re-pull when up to date */}
            {!hasUpdate && !tagsError && tags.length > 0 && severity === 'current' && (
              <ActionBtn
                key="repull"
                label="↓ Re-pull Image"
                loading={loading.pull}
                onClick={() => act('pull', `containers/${c.id}/pull`, null, null)}
              />
            )}

            {/* Fallback pull when version check unavailable or no tags */}
            {(tagsError || (!tagsLoading && !tags.length) || severity === 'ahead' || severity === 'unknown') &&
             updateStatus?.update_available !== false && (
              <ActionBtn
                key="pull"
                label="↓ Pull Latest"
                variant={pullColor}
                loading={loading.pull}
                onClick={() => act('pull', pullPath, null, null)}
              />
            )}

            {/* Choose version picker — always available when tags loaded */}
            {tags.length > 0 && (
              <>
                <ActionBtn
                  key="choose-version"
                  label={versionPickerOpen ? '✕ Cancel' : '↓ Choose version ▾'}
                  onClick={() => setVersionPickerOpen(o => !o)}
                />
                {versionPickerOpen && (
                  <div className="mt-1 mb-1 bg-[#0a0a15] border border-[#2a2440] rounded-md p-2">
                    <div className="text-[9px] text-gray-700 mb-1.5">Select version to pull:</div>
                    <select
                      className="w-full bg-[#0d0d1a] border border-[#2a2a4a] text-gray-300 rounded text-[10px] px-1.5 py-1 mb-1.5"
                      value={selectedTag}
                      onChange={e => setSelectedTag(e.target.value)}
                    >
                      {tags.map(t => (
                        <option key={t} value={t}>
                          {t}{t === c.running_version || `v${t}` === `v${c.running_version}` ? ' ← running' : ''}
                        </option>
                      ))}
                    </select>
                    <ActionBtn
                      key="pull-versioned-picker"
                      label={`↓ Pull ${selectedTag}`}
                      variant="primary"
                      loading={loading['pull-versioned']}
                      onClick={() => {
                        act('pull-versioned', `containers/${c.id}/pull?tag=${selectedTag}`, null, null)
                        setVersionPickerOpen(false)
                      }}
                    />
                  </div>
                )}
              </>
            )}
          </>
        )
      })()}
      <Actions buttons={[
        !c.image?.startsWith('ghcr.io/') && !isSwarm && (
          <ActionBtn key="pull" label="↓ Pull Latest" variant={pullColor} loading={loading.pull} onClick={() => act('pull', pullPath, null, null)} />
        ),
        <ActionBtn key="logs" label={logsOpen ? '✕ Close Logs' : 'View Logs'} onClick={openLogs} />,
        !isSwarm && <ActionBtn key="restart" label="Restart" loading={loading.restart} onClick={() => act('restart', `containers/${c.id}/restart`, null, `Restart ${c.name}?`)} />,
        !isSwarm && <ActionBtn key="stop" label="Stop" variant="danger" loading={loading.stop} onClick={() => act('stop', `containers/${c.id}/stop`, null, `Stop ${c.name}? This will terminate the container.`)} />,
        isSwarm && !scaleOpen && <ActionBtn key="scale" label="Scale" loading={loading.scale} onClick={() => { setScaleVal(c.desired_replicas ?? 1); setScaleOpen(true) }} />,
      ].filter(Boolean)} />
      {scaleOpen && (
        <div className="mt-3 flex items-center gap-2">
          <button className="px-2 py-1 bg-[#1e1e3a] text-white rounded text-sm" onClick={() => setScaleVal(v => Math.max(0, v - 1))}>−</button>
          <input
            type="number" min="0"
            value={scaleVal}
            onChange={e => setScaleVal(parseInt(e.target.value) || 0)}
            className="w-16 text-center bg-[#0d0d1a] border border-[#2a2a4a] text-white rounded text-sm py-1"
          />
          <button className="px-2 py-1 bg-[#1e1e3a] text-white rounded text-sm" onClick={() => setScaleVal(v => v + 1)}>+</button>
          <button
            className="px-3 py-1 bg-[#7c6af7] text-white rounded text-sm"
            onClick={() => { act('scale', `services/${c.name}/scale`, { replicas: scaleVal }, null); setScaleOpen(false) }}
          >Confirm</button>
          <button className="px-2 py-1 text-[#888] text-sm" onClick={() => setScaleOpen(false)}>✕</button>
        </div>
      )}
      {logsOpen && (
        <div className="mt-2 rounded border border-[#2a2a4a] bg-[#060610] overflow-hidden">
          <div className="flex justify-between items-center px-2 py-1 border-b border-[#1a1a3a]">
            <span className="text-[11px] text-gray-600 font-mono">logs — {c.name}</span>
            <div className="flex gap-1">
              <button
                className={`text-[11px] px-1.5 py-0.5 rounded ${logsPaused ? 'bg-[#7c6af7] text-white' : 'bg-[#1a1a3a] text-gray-400 hover:text-white'}`}
                onClick={pauseLogs}
              >
                {logsPaused ? '▶ Resume' : '⏸ Pause'}
              </button>
              <button
                className="text-[11px] px-1.5 py-0.5 rounded bg-[#1a1a3a] text-gray-400 hover:text-white"
                onClick={() => { setLogLines([]); setLogsPaused(false); logsPausedRef.current = false }}
              >
                Clear
              </button>
              <button
                className="text-[11px] px-1.5 py-0.5 rounded bg-[#1a1a3a] text-gray-400 hover:text-white"
                onClick={() => setPopoutOpen(true)}
              >
                ⤢ Pop out
              </button>
            </div>
          </div>
          <div ref={logsScrollRef} className="overflow-y-auto max-h-48 font-mono p-2">
            {logLines.length === 0
              ? <span className="text-[11px] text-gray-700 italic">waiting for log lines…</span>
              : logLines.map((l, i) => (
                  <div key={i} className="text-[11px] text-green-400 leading-tight whitespace-pre break-all">{l}</div>
                ))
            }
          </div>
        </div>
      )}
      {popoutOpen && (
        <div
          className="fixed z-50 rounded border border-[#2a2a4a] bg-[#060610] shadow-2xl flex flex-col"
          style={{ top: '5vh', left: '5vw', width: '90vw', height: '85vh', resize: 'both', overflow: 'auto', minWidth: 600, minHeight: 300 }}
        >
          <div className="flex justify-between items-center px-3 py-1.5 border-b border-[#1a1a3a] shrink-0">
            <span className="text-xs text-gray-500 font-mono">logs — {c.name}</span>
            <div className="flex gap-1">
              <button
                className={`text-xs px-2 py-0.5 rounded ${logsPaused ? 'bg-[#7c6af7] text-white' : 'bg-[#1a1a3a] text-gray-400 hover:text-white'}`}
                onClick={pauseLogs}
              >
                {logsPaused ? '▶ Resume' : '⏸ Pause'}
              </button>
              <button
                className="text-xs px-2 py-0.5 rounded bg-[#1a1a3a] text-gray-400 hover:text-white"
                onClick={() => { setLogLines([]); setLogsPaused(false); logsPausedRef.current = false }}
              >
                Clear
              </button>
              <button
                className="text-xs px-2 py-0.5 rounded bg-[#1a1a3a] text-gray-400 hover:text-white"
                onClick={() => setPopoutOpen(false)}
              >
                ✕ Close
              </button>
            </div>
          </div>
          <div ref={popoutScrollRef} className="flex-1 overflow-y-auto font-mono p-3" style={{ minHeight: 0 }}>
            {logLines.length === 0
              ? <span className="text-xs text-gray-700 italic">waiting for log lines…</span>
              : logLines.map((l, i) => (
                  <div key={i} className="text-xs text-green-400 leading-snug whitespace-pre">{l}</div>
                ))
            }
          </div>
        </div>
      )}
    </>
  )
}

function ContainerCardCollapsed({ c, onEntityDetail }) {
  return (
    <div className="flex items-center gap-1">
      {c.problem && <div className="text-[10px] px-1.5 py-px rounded inline-flex items-center gap-1" style={{ background: 'var(--red-dim)', color: 'var(--red)' }}>⚠ {c.problem}</div>}
      {onEntityDetail && (
        <button
          className="text-[10px] px-1 py-px ml-auto"
          style={{ color: 'var(--cyan)', background: 'none', border: 'none', cursor: 'pointer' }}
          onClick={e => { e.stopPropagation(); onEntityDetail(`docker:${c.name || c.id}`) }}
          title="Entity detail"
        >›</button>
      )}
    </div>
  )
}

// ── VM / LXC card ─────────────────────────────────────────────────────────────

function ProxmoxCardExpanded({ vm, proxmoxHost, proxmoxPort, onAction, confirm, showToast }) {
  const [loading, setLoading] = useState({})
  const [localMaint, setLocalMaint] = useState(!!vm.maintenance)
  const mounted = useRef(true)
  useEffect(() => () => { mounted.current = false }, [])
  // Sync optimistic state when vm prop refreshes from poll
  useEffect(() => { setLocalMaint(!!vm.maintenance) }, [vm.maintenance])

  const apiBase = vm.type === 'lxc' ? 'lxc' : 'vms'

  const act = async (key, action, msg) => {
    if (msg) {
      const ok = await confirm(msg)
      if (!ok) return
    }
    setLoading(l => ({ ...l, [key]: true }))
    const r = await dashboardAction(`${apiBase}/${vm.node_api}/${vm.vmid}/${action}`)
    if (!mounted.current) return
    setLoading(l => ({ ...l, [key]: false }))
    if (!r.ok) showToast(r.error || 'Action failed', 'error')
    else { showToast('Done'); onAction() }
  }

  const isLxc = vm.type === 'lxc'
  const _pxHost = proxmoxHost || location.hostname
  const _pxPort = proxmoxPort || 8006
  const _pxBase = `https://${_pxHost}:${_pxPort}`
  const openConsole = (type) =>
    window.open(`${_pxBase}/?console=${type}&vmid=${vm.vmid}&node=${vm.node_api}&novnc=1`, '_blank')

  return (
    <>
      <StatRow stats={[
        { v: vm.cpu_pct != null ? `${vm.cpu_pct}%` : '—', l: 'CPU' },
        { v: vm.mem_used_gb != null ? `${vm.mem_used_gb} / ${vm.maxmem_gb} GB` : '—', l: 'RAM' },
      ]} />
      <Divider />
      {(vm.disks || []).map(d => <VolBar key={d.mountpoint} vol={{ name: d.mountpoint, used_bytes: d.used_bytes, total_bytes: d.total_bytes }} />)}
      {vm.disks?.length > 0 && <Divider />}
      <Actions buttons={
        vm.status === 'stopped'
          ? [
            <ActionBtn key="start" label={isLxc ? 'Start Container' : 'Start VM'} variant="urgent" loading={loading.start} onClick={() => act('start', 'start', null)} />,
            <ActionBtn key="proxmox" label="View in Proxmox" onClick={() => window.open(_pxBase, '_blank')} />,
          ]
          : [
            !isLxc && <ActionBtn key="console" label="Open Console" onClick={() => openConsole('kvm')} />,
            isLxc && <ActionBtn key="console" label="Open Console" onClick={() => openConsole('lxc')} />,
            <ActionBtn key="proxmox" label="View in Proxmox" onClick={() => window.open(_pxBase, '_blank')} />,
            isLxc && <ActionBtn key="stop" label="Stop" variant="danger" loading={loading.stop} onClick={() => act('stop', 'stop', `Stop ${vm.name}?`)} />,
            <ActionBtn key="reboot" label="Reboot" variant="danger" loading={loading.reboot} onClick={() => act('reboot', 'reboot', `Reboot ${vm.name}? It will be temporarily unreachable.`)} />,
          ].filter(Boolean)
      } />
      {/* Maintenance toggle — optimistic: updates UI instantly, then syncs on next poll */}
      {vm.entity_id && (
        <div style={{ marginTop: 6, borderTop: '1px solid var(--bg-3)', paddingTop: 6 }}>
          <button
            onClick={async (e) => {
              e.stopPropagation()
              const next = !localMaint
              setLocalMaint(next)  // optimistic update — immediate visual response
              const BASE = import.meta.env.VITE_API_BASE ?? ''
              const headers = { 'Content-Type': 'application/json', ...authHeaders() }
              if (!next) {
                await fetch(`${BASE}/api/maintenance/${encodeURIComponent(vm.entity_id)}`, { method: 'DELETE', headers })
              } else {
                await fetch(`${BASE}/api/maintenance/${encodeURIComponent(vm.entity_id)}`, {
                  method: 'POST', headers,
                  body: JSON.stringify({ reason: 'Set from dashboard' })
                })
              }
              window.dispatchEvent(new CustomEvent('ds:refresh-dashboard'))
            }}
            style={{
              padding: '2px 10px', fontSize: 9, fontFamily: 'var(--font-mono)',
              background: localMaint ? 'var(--amber-dim)' : 'transparent',
              color: localMaint ? 'var(--amber)' : 'var(--text-3)',
              border: `1px solid ${localMaint ? 'var(--amber)' : 'var(--border)'}`,
              borderRadius: 2, cursor: 'pointer',
            }}
          >
            {localMaint ? '\u2691 Clear Maintenance' : '\u2691 Set Maintenance'}
          </button>
        </div>
      )}
    </>
  )
}

function ProxmoxCardCollapsed({ vm, onEntityDetail, onChat }) {
  const typeBadge = vm.type === 'lxc'
    ? <span className="text-[9px] px-1 py-px rounded bg-[#0a1a2a] text-cyan-600 border border-[#0d2030] mr-1">LXC</span>
    : <span className="text-[9px] px-1 py-px rounded bg-[#0d0a2a] text-violet-600 border border-[#1a1040] mr-1">VM</span>
  return (
    <>
      <div className="text-[10px] text-[#383850] mb-1">{vm.vcpus} vCPU · {vm.maxmem_gb} GB RAM</div>
      <div className="flex items-center">
        {vm.problem
          ? <div className="text-[10px] px-1.5 py-px rounded inline-flex items-center gap-1 bg-amber-950/40 text-amber-400 border border-amber-900/30">⚠ {vm.problem}</div>
          : <>{typeBadge}<span className="text-[9px] px-1.5 py-px rounded bg-[#0d1a2a] text-blue-400 border border-[#1a2a3a]">● {vm.status}</span></>}
        {vm.maintenance && (
          <span style={{
            fontSize: 7, fontFamily: 'var(--font-mono)', padding: '1px 4px',
            background: 'var(--amber-dim)', color: 'var(--amber)',
            borderRadius: 2, letterSpacing: 0.5, marginLeft: 4,
          }}>MAINT</span>
        )}
        <span style={{ flex: 1 }} />
        {onChat && (
          <button
            className="text-[10px] px-1 py-px"
            style={{ color: 'var(--amber)', background: 'none', border: 'none', cursor: 'pointer', opacity: 0.7 }}
            onClick={e => { e.stopPropagation(); onChat(vm.name) }}
            title="Ask agent about this VM"
          >⌘</button>
        )}
        {onEntityDetail && (
          <button
            className="text-[10px] px-1 py-px"
            style={{ color: 'var(--cyan)', background: 'none', border: 'none', cursor: 'pointer' }}
            onClick={e => { e.stopPropagation(); onEntityDetail(`proxmox_vms:${vm.node_api}:${vm.type === 'lxc' ? 'lxc' : 'qemu'}:${vm.vmid}`) }}
            title="Entity detail"
          >›</button>
        )}
      </div>
    </>
  )
}

// ── Generic connection filter bar ──────────────────────────────────────────────

function ConnectionFilterBar({ items, filters, setFilters, fields = [] }) {
  if (!items?.length) return null

  const chipBase = 'text-[9px] px-1.5 py-px rounded border cursor-pointer select-none transition-colors'
  const chip = (active) => active
    ? `${chipBase} bg-violet-600/30 text-violet-300 border-violet-500/40`
    : `${chipBase} bg-[#0d0d1a] text-gray-600 border-[#1a1a30] hover:text-gray-400`

  const toggle = (key, val) =>
    setFilters(f => ({ ...f, [key]: f[key] === val ? null : val }))

  const hasAnyFilter = fields.some(f => filters[f.key]) || filters.name

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mb-2 px-0.5">
      {fields.map(({ key, label }) => {
        const values = [...new Set(items.map(i => i[key]).filter(Boolean))].sort()
        if (values.length < 2) return null
        return (
          <div key={key} className="flex items-center gap-1">
            <span className="text-[9px] text-gray-700">{label}</span>
            {values.map(v => (
              <button
                key={v}
                className={chip(filters[key] === v)}
                onClick={() => toggle(key, v)}
              >
                {v}
              </button>
            ))}
          </div>
        )
      })}

      <div className="flex items-center gap-1">
        <span className="text-[9px] text-gray-700">name</span>
        <input
          type="text"
          placeholder="filter..."
          value={filters.name || ''}
          onChange={e => setFilters(f => ({ ...f, name: e.target.value || '' }))}
          className="text-[9px] w-20 bg-[#0d0d1a] border border-[#1a1a30] rounded px-1.5 py-px text-gray-400 placeholder-gray-700 focus:outline-none focus:border-violet-500/40"
        />
        {filters.name && (
          <button className="text-[9px] text-gray-700 hover:text-gray-500"
            onClick={() => setFilters(f => ({ ...f, name: '' }))}>✕</button>
        )}
      </div>

      {hasAnyFilter && (
        <button
          className="text-[9px] text-gray-700 hover:text-violet-400 ml-1"
          onClick={() => setFilters({})}
        >clear</button>
      )}
    </div>
  )
}

function applyConnectionFilters(items, filters, fields = []) {
  return items.filter(item => {
    for (const { key } of fields) {
      if (filters[key] && item[key] !== filters[key]) return false
    }
    if (filters.name && !item.name?.toLowerCase().includes(filters.name.toLowerCase())) {
      return false
    }
    return true
  })
}

// ── Proxmox filter bar ────────────────────────────────────────────────────────

function ProxmoxFilterBar({ items, filters, setFilters, sort, onSort }) {
  const [dropOpen, setDropOpen] = useState(false)
  const nodes = [...new Set(items.map(v => v.node_api))].sort()
  const pools = [...new Set(items.map(v => v.pool || '').filter(Boolean))].sort()
  const hasLxc = items.some(v => v.type === 'lxc')
  const hasVm  = items.some(v => v.type === 'vm')

  const toggle = (key, val) => setFilters(f => ({ ...f, [key]: f[key] === val ? null : val }))

  const chipBase = 'text-[9px] px-1.5 py-px rounded border cursor-pointer select-none transition-colors'
  const chip = (active) => active
    ? `${chipBase} bg-violet-600/30 text-violet-300 border-violet-500/40`
    : `${chipBase} bg-[#0d0d1a] text-gray-600 border-[#1a1a30] hover:text-gray-400`

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mb-2 px-0.5">
      {/* Node filter */}
      {nodes.length > 1 && (
        <div className="flex items-center gap-1">
          <span className="text-[9px] text-gray-700">node</span>
          {nodes.map(n => (
            <button key={n} className={chip(filters.node === n)} onClick={() => toggle('node', n)}>{n}</button>
          ))}
        </div>
      )}
      {/* Pool filter */}
      {pools.length > 0 && (
        <div className="flex items-center gap-1">
          <span className="text-[9px] text-gray-700">pool</span>
          {pools.map(p => (
            <button key={p} className={chip(filters.pool === p)} onClick={() => toggle('pool', p)}>{p}</button>
          ))}
        </div>
      )}
      {/* Type filter */}
      {hasLxc && hasVm && (
        <div className="flex items-center gap-1">
          <span className="text-[9px] text-gray-700">type</span>
          <button className={chip(filters.type === 'vm')}  onClick={() => toggle('type', 'vm')}>VM</button>
          <button className={chip(filters.type === 'lxc')} onClick={() => toggle('type', 'lxc')}>LXC</button>
        </div>
      )}
      {/* Status filter */}
      <div className="flex items-center gap-1">
        <span className="text-[9px] text-gray-700">status</span>
        <button className={chip(filters.status === 'running')} onClick={() => toggle('status', 'running')}>running</button>
        <button className={chip(filters.status === 'stopped')} onClick={() => toggle('status', 'stopped')}>stopped</button>
      </div>
      {/* Name prefix filter */}
      <div className="flex items-center gap-1">
        <span className="text-[9px] text-gray-700">name</span>
        <input
          type="text"
          placeholder="hp1-"
          value={filters.name || ''}
          onChange={e => setFilters(f => ({ ...f, name: e.target.value || null }))}
          className="text-[9px] w-16 bg-[#0d0d1a] border border-[#1a1a30] rounded px-1.5 py-px text-gray-400 placeholder-gray-700 focus:outline-none focus:border-violet-500/40"
        />
        {filters.name && (
          <button className="text-[9px] text-gray-700 hover:text-gray-500" onClick={() => setFilters(f => ({ ...f, name: null }))}>✕</button>
        )}
      </div>
      {/* Clear all */}
      {(filters.node || filters.pool || filters.type || filters.status || filters.name) && (
        <button
          className="text-[9px] text-gray-700 hover:text-violet-400 ml-1"
          onClick={() => setFilters({})}
        >clear</button>
      )}
      {/* Sort chip */}
      {sort && onSort && (() => {
        const SORT_FIELDS = [
          { key: 'vmid',   label: 'vmid'   },
          { key: 'name',   label: 'Name'   },
          { key: 'status', label: 'Status' },
          { key: 'cpu',    label: 'CPU %'  },
          { key: 'ram',    label: 'RAM %'  },
        ]
        const currentLabel = SORT_FIELDS.find(f => f.key === sort.sortBy)?.label ?? sort.sortBy
        const toggleDir = () => onSort(sort.sortBy, sort.sortDir === 'asc' ? 'desc' : 'asc')
        const selectField = (key) => {
          if (key === sort.sortBy) {
            toggleDir()
          } else {
            onSort(key, 'asc')
          }
          setDropOpen(false)
        }
        return (
          <div className="relative flex items-center gap-0.5">
            <button
              className="text-[9px] px-1.5 py-px rounded-l border bg-violet-600/30 text-violet-300 border-violet-500/40 cursor-pointer select-none"
              onClick={() => setDropOpen(o => !o)}
            >
              Sort: {currentLabel}
            </button>
            <button
              className="text-[9px] px-1 py-px rounded-r border bg-violet-600/30 text-violet-300 border-violet-500/40 cursor-pointer select-none"
              onClick={toggleDir}
            >
              {sort.sortDir === 'asc' ? '↑' : '↓'}
            </button>
            {dropOpen && (
              <div className="absolute top-full right-0 mt-0.5 z-10 bg-[#0a0a15] border border-[#2a2440] rounded-md p-1 min-w-[80px]">
                {SORT_FIELDS.map(f => (
                  <button
                    key={f.key}
                    className={`block w-full text-left text-[9px] px-2 py-0.5 rounded ${
                      sort.sortBy === f.key
                        ? 'bg-violet-600/30 text-violet-300'
                        : 'text-gray-500 hover:text-gray-300 hover:bg-[#111122]'
                    }`}
                    onClick={() => selectField(f.key)}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        )
      })()}
    </div>
  )
}

function applyProxmoxFilters(items, filters) {
  return items.filter(v => {
    if (filters.node   && v.node_api !== filters.node)              return false
    if (filters.pool   && (v.pool || '') !== filters.pool)          return false
    if (filters.type   && v.type !== filters.type)                  return false
    if (filters.status && v.status !== filters.status)              return false
    if (filters.name   && !v.name.toLowerCase().includes(filters.name.toLowerCase())) return false
    return true
  })
}

function sortProxmoxItems(items, sortBy, sortDir) {
  const dir = sortDir === 'asc' ? 1 : -1
  return [...items].sort((a, b) => {
    switch (sortBy) {
      case 'vmid':
        return (a.vmid - b.vmid) * dir
      case 'name':
        return (a.name || '').localeCompare(b.name || '') * dir
      case 'status': {
        const rank = s => s === 'running' ? 0 : s === 'stopped' ? 1 : 2
        return (rank(a.status) - rank(b.status)) * dir
      }
      case 'cpu': {
        if (a.cpu_pct == null && b.cpu_pct == null) return 0
        if (a.cpu_pct == null) return 1
        if (b.cpu_pct == null) return -1
        return (a.cpu_pct - b.cpu_pct) * dir
      }
      case 'ram': {
        const aPct = a.maxmem_gb ? (a.mem_used_gb ?? 0) / a.maxmem_gb : null
        const bPct = b.maxmem_gb ? (b.mem_used_gb ?? 0) / b.maxmem_gb : null
        if (aPct == null && bPct == null) return 0
        if (aPct == null) return 1
        if (bPct == null) return -1
        return (aPct - bPct) * dir
      }
      default:
        return 0
    }
  })
}

// ── External service card ─────────────────────────────────────────────────────

function ExternalCardExpanded({ svc, onAction }) {
  const [probeLoading, setProbeLoading] = useState(false)
  const [probeResult, setProbeResult] = useState(null)
  const [liveLatency, setLiveLatency] = useState(null)
  const mounted = useRef(true)
  useEffect(() => () => { mounted.current = false }, [])

  const probe = async () => {
    setProbeLoading(true)
    setProbeResult(null)
    const r = await testConnectionByPlatform(svc.slug)
    if (!mounted.current) return
    setProbeLoading(false)
    setProbeResult(r.status === 'ok' ? 'ok' : 'fail')
    // Also try the dashboard probe for latency
    const dr = await dashboardAction(`external/${svc.slug}/probe`)
    if (!mounted.current) return
    if (dr.latency_ms != null) setLiveLatency(dr.latency_ms)
    setTimeout(() => { if (mounted.current) { setProbeResult(null); onAction() } }, 2000)
  }

  const latency = liveLatency ?? svc.latency_ms
  return (
    <>
      <StatRow stats={[
        { v: latency != null ? `${latency} ms` : '—', l: 'Latency', color: !svc.reachable ? 'text-red-400' : latency > 100 ? 'text-amber-400' : 'text-green-400' },
        { v: svc.reachable ? 'online' : 'offline', l: 'Status', color: svc.reachable ? 'text-gray-300' : 'text-red-400' },
      ]} />
      {probeResult && (
        <div className={`text-[10px] mb-1 ${probeResult === 'ok' ? 'text-green-400' : 'text-red-400'}`}>
          {probeResult === 'ok' ? '✓ Connection verified' : '✕ Connection failed'}
        </div>
      )}
      {svc.storage && <><VolBar vol={{ name: svc.storage.name, used_bytes: svc.storage.used_bytes, total_bytes: svc.storage.total_bytes }} /><Divider /></>}
      <Actions buttons={[
        <ActionBtn key="probe" label="Test Connection" loading={probeLoading} onClick={probe} />,
        svc.open_ui_url && <ActionBtn key="ui" label="Open UI" onClick={() => window.open(svc.open_ui_url, '_blank')} />,
      ].filter(Boolean)} />
    </>
  )
}

function ExternalCardCollapsed({ svc, onEntityDetail, compareMode, onCompareAdd }) {
  const [reconnecting, setReconnecting] = useState(false)
  const [reconnectResult, setReconnectResult] = useState(null)
  const latencyColor = !svc.reachable ? 'text-red-400' : svc.latency_ms > 100 ? 'text-amber-400' : 'text-green-400'
  const showReconnect = svc.dot === 'red' || svc.dot === 'grey' || svc.problem === 'not configured'

  const reconnect = async (e) => {
    e.stopPropagation()
    setReconnecting(true)
    const r = await testConnectionByPlatform(svc.slug)
    setReconnecting(false)
    setReconnectResult(r.status === 'ok' ? 'ok' : 'fail')
    setTimeout(() => setReconnectResult(null), 3000)
  }

  return (
    <div className="flex items-center gap-1">
      {svc.problem
        ? <div className="text-[10px] px-1.5 py-px rounded inline-flex gap-1" style={{ background: 'var(--red-dim)', color: 'var(--red)' }}>⚠ {svc.problem}</div>
        : <span className={`text-[10px] font-mono ${latencyColor}`}>● {svc.latency_ms != null ? `${svc.latency_ms} ms` : '—'}</span>}
      {showReconnect && (
        <button className="text-[9px] px-1.5 py-0.5 rounded ml-1"
                style={{ background: 'var(--accent-dim)', color: 'var(--accent)' }}
                onClick={reconnect} disabled={reconnecting}>
          {reconnecting ? '…' : reconnectResult === 'ok' ? '✓' : reconnectResult === 'fail' ? '✕' : 'Reconnect'}
        </button>
      )}
      {onEntityDetail && (
        <button
          className="text-[10px] px-1 py-px ml-auto"
          style={{ color: 'var(--cyan)', background: 'none', border: 'none', cursor: 'pointer' }}
          onClick={e => { e.stopPropagation(); onEntityDetail(`external_services:${svc.slug}`) }}
          title="Entity detail"
        >›</button>
      )}
    </div>
  )
}

// ── Alert bar ─────────────────────────────────────────────────────────────────

function AlertBar({ containers, swarm, vms, external }) {
  const issues = []
  let idx = 0
  for (const c of containers?.containers || []) if (c.problem) issues.push({ sev: c.dot, text: `${c.name} ${c.problem}`, idx: idx++ })
  for (const s of swarm?.services || []) if (s.problem) issues.push({ sev: s.dot, text: `${s.name} ${s.problem}`, idx: idx++ })
  for (const v of [...(vms?.vms || []), ...(vms?.lxc || [])]) if (v.problem) issues.push({ sev: v.dot, text: `${v.name} ${v.problem}`, idx: idx++ })
  for (const e of external?.services || []) if (e.problem) issues.push({ sev: e.dot, text: `${e.name} ${e.problem}`, idx: idx++ })
  if (!issues.length) return null
  const SEV_ORDER = { red: 0, amber: 1, grey: 2, green: 3 }
  issues.sort((a, b) => {
    const sa = SEV_ORDER[a.sev] ?? 2
    const sb = SEV_ORDER[b.sev] ?? 2
    if (sa !== sb) return sa - sb
    return a.idx - b.idx
  })
  const shown = issues.slice(0, 3)
  const extra = issues.length - 3
  return (
    <div className="bg-[#1a0a0a] border-b border-[#3a1010] px-5 py-2 flex items-center gap-2 text-[11px]">
      <span className="text-red-400 text-[13px]">⚠</span>
      <span className="text-red-400/80 flex-1">{shown.map(i => i.text).join(' · ')}{extra > 0 ? ` · +${extra} more` : ''}</span>
      <span className="bg-red-500 text-white text-[10px] px-2 py-px rounded-full">{issues.length}</span>
    </div>
  )
}

// ── Utility ───────────────────────────────────────────────────────────────────

function _relativeTime(iso) {
  if (!iso) return 'unknown'
  const age = Date.now() - new Date(iso).getTime()
  const mins = Math.round(age / 60000)
  if (mins < 60) return `${mins} min ago`
  const hours = Math.round(age / 3600000)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

function _pulledAgo(iso) {
  if (!iso) return 'unknown'
  const age = Date.now() - new Date(iso).getTime()
  const mins = Math.round(age / 60000)
  if (mins < 60) return `${Math.max(1, mins)}m ago`
  const hours = Math.floor(age / 3600000)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  const remHours = hours % 24
  return remHours > 0 ? `${days}d ${remHours}h ago` : `${days}d ago`
}

function _computeContainerSub(c, knownLatest) {
  const latestTag = knownLatest[c.id]
  // Shorten image to just the repo:tag part (strip registry host)
  const imageParts = (c.image || '').split('/')
  const shortImage = imageParts[imageParts.length - 1] || c.image || ''

  if (!latestTag || !c.running_version) return shortImage
  const severity = compareBuildTag(c.running_version, latestTag)
  if (severity === 'major') return { text: `${shortImage} — update avail`, cls: 'text-[#b04020]' }
  if (severity === 'minor' || severity === 'patch') return { text: `${shortImage} — update avail`, cls: 'text-[#92601a]' }
  return shortImage
}

// ── Auto-update toggle (agent container only) ────────────────────────────────

function AutoUpdateToggle() {
  const [info, setInfo] = useState(null)
  const [toggling, setToggling] = useState(false)

  const fetchStatus = () => {
    fetch(`${BASE}/api/dashboard/update-status`, { headers: { ...authHeaders() } })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setInfo(d) })
      .catch(() => {})
  }

  useEffect(() => { fetchStatus() }, [])

  const toggle = async () => {
    if (!info) return
    setToggling(true)
    try {
      const r = await fetch(`${BASE}/api/dashboard/auto-update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ enabled: !info.auto_update }),
      })
      if (r.ok) fetchStatus()
    } catch (_) {}
    setToggling(false)
  }

  if (!info) return null

  return (
    <div className="flex items-center justify-between text-[9px] mb-1.5">
      <label className="flex items-center gap-1.5 cursor-pointer">
        <input
          type="checkbox"
          checked={!!info.auto_update}
          onChange={toggle}
          disabled={toggling}
          className="accent-blue-500"
        />
        <span className="text-gray-500">Auto-update</span>
      </label>
      <span className="text-gray-600">
        {info.auto_update
          ? info.update_available
            ? info.latest_version && info.latest_version !== info.current_version
              ? `will update to ${info.latest_version} within 5 min`
              : 'new build available — will apply within 5 min'
            : info.last_checked
              ? `checked ${new Date(info.last_checked).toLocaleTimeString()}`
              : 'checking...'
          : 'off'}
      </span>
    </div>
  )
}

// ── Main export ───────────────────────────────────────────────────────────────

export default function ServiceCards({ activeFilters = null, onTab, onEntityDetail, onChat, compareMode, compareSet, onCompareAdd, showFilter, search = '' }) {
  // If no filter passed, show everything
  const show = (key) => !activeFilters || activeFilters.includes(key)
  const isPinned = (entityId) => (compareSet || []).some(e => e.id === entityId)
  const matchesShowFilter = (dot) => {
    if (!showFilter || showFilter === 'ALL') return true
    if (showFilter === 'ERRORS') return dot === 'red'
    if (showFilter === 'DEGRADED') return dot === 'amber'
    if (showFilter === 'IN MAINT') return dot === 'grey'
    return true
  }
  const _sl = search?.toLowerCase() || ''
  const matchesSearch = (...fields) => {
    if (!_sl) return true
    return fields.some(f => f && String(f).toLowerCase().includes(_sl))
  }
  const [containers, setContainers] = useState(null)
  const [swarm, setSwarm]           = useState(null)
  const [vms, setVMs]               = useState(null)
  const [external, setExternal]     = useState(null)
  const [openKeys, setOpenKeys]     = useState(new Set())
  const [lastOpenedKey, setLastOpenedKey] = useState(null)
  const [expandAllFlag, setExpandAllFlag] = useState(false)
  const [isInitialLoad, setIsInitialLoad] = useState(true)
  // Per-cluster filter state keyed by connection_id (or cluster index fallback)
  const [proxmoxFilterMap, setProxmoxFilterMap] = useState({})

  const getClusterFilters = (key) => proxmoxFilterMap[key] || {}
  const setClusterFilters = (key, updater) => setProxmoxFilterMap(prev => ({
    ...prev,
    [key]: typeof updater === 'function' ? updater(prev[key] || {}) : updater,
  }))
  const [sortBy, setSortBy] = useState(() => {
    try {
      const s = JSON.parse(localStorage.getItem('hp1_proxmox_sort') || '{}')
      return s.sortBy || 'name'
    } catch { return 'name' }
  })
  const [sortDir, setSortDir] = useState(() => {
    try {
      const s = JSON.parse(localStorage.getItem('hp1_proxmox_sort') || '{}')
      return s.sortDir || 'asc'
    } catch { return 'asc' }
  })
  useEffect(() => {
    localStorage.setItem('hp1_proxmox_sort', JSON.stringify({ sortBy, sortDir }))
  }, [sortBy, sortDir])
  const [knownLatest, setKnownLatest] = useState({})
  const { pending, confirm, resolve } = useConfirm()

  const onTagsLoaded = useCallback((containerId, latestTag) => {
    setKnownLatest(prev => ({ ...prev, [containerId]: latestTag }))
  }, [])

  // Proactively fetch tags for GHCR containers so version badge shows on collapsed view
  const fetchedTagIds = useRef(new Set())
  useEffect(() => {
    for (const container of containers?.containers || []) {
      if (!container.image?.startsWith('ghcr.io/')) continue
      if (fetchedTagIds.current.has(container.id)) continue
      fetchedTagIds.current.add(container.id)
      fetchContainerTags(container.id).then(data => {
        if (data?.tags?.[0]) setKnownLatest(prev => ({ ...prev, [container.id]: data.tags[0] }))
      }).catch(() => {})
    }
  }, [containers])
  const { toasts, show: showToast } = useToast()

  // UniFi + PBS collector data (60s poll, separate from 30s base)
  const [unifiData, setUnifiData] = useState(null)
  const [unifiConn, setUnifiConn] = useState(null)
  const [unifiFilters, setUnifiFilters] = useState({})
  const [fgFilters, setFgFilters] = useState({})
  const [pbsData, setPbsData]     = useState(null)
  const [pbsConn, setPbsConn]     = useState(null)
  useEffect(() => {
    if (!show('unifi')) return
    const loadUnifi = () => {
      fetchCollectorData('unifi').then(r => r?.data ? setUnifiData(r.data) : null).catch(() => {})
      fetch(`${BASE}/api/connections?platform=unifi`, { headers: { ...authHeaders() } })
        .then(r => r.json()).then(d => setUnifiConn((d.data || []).find(c => c.host))).catch(() => {})
    }
    loadUnifi()
    const id = setInterval(loadUnifi, 60000)
    return () => clearInterval(id)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!show('pbs')) return
    const loadPbs = () => {
      fetchCollectorData('pbs').then(r => r?.data ? setPbsData(r.data) : null).catch(() => {})
      fetch(`${BASE}/api/connections?platform=pbs`, { headers: { ...authHeaders() } })
        .then(r => r.json()).then(d => setPbsConn((d.data || []).find(c => c.host))).catch(() => {})
    }
    loadPbs()
    const id = setInterval(loadPbs, 60000)
    return () => clearInterval(id)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  // TrueNAS pools
  const [truenasData, setTruenasData] = useState(null)
  const [truenasConn, setTruenasConn] = useState(null)
  useEffect(() => {
    if (!show('truenas')) return
    const loadTruenas = () => {
      fetchCollectorData('truenas').then(r => r?.data ? setTruenasData(r.data) : null).catch(() => {})
      fetch(`${BASE}/api/connections?platform=truenas`, { headers: { ...authHeaders() } })
        .then(r => r.json()).then(d => setTruenasConn((d.data || []).find(c => c.host))).catch(() => {})
    }
    loadTruenas()
    const id = setInterval(loadTruenas, 60000)
    return () => clearInterval(id)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  // FortiGate interfaces
  const [fgData, setFgData] = useState(null)
  const [fgConn, setFgConn] = useState(null)
  useEffect(() => {
    if (!show('fortigate')) return
    const loadFg = () => {
      fetchCollectorData('fortigate').then(r => r?.data ? setFgData(r.data) : null).catch(() => {})
      fetch(`${BASE}/api/connections?platform=fortigate`, { headers: { ...authHeaders() } })
        .then(r => r.json()).then(d => setFgConn((d.data || []).find(c => c.host))).catch(() => {})
    }
    loadFg()
    const id = setInterval(loadFg, 60000)
    return () => clearInterval(id)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const load = useCallback(async () => {
    const [c, s, v, e] = await Promise.allSettled([
      fetchDashboardContainers(),
      fetchDashboardSwarm(),
      fetchDashboardVMs(),
      fetchDashboardExternal(),
    ])
    if (c.status === 'fulfilled') {
      setContainers(c.value)
      const currentIds = new Set((c.value?.containers || []).map(x => x.id))
      setKnownLatest(prev =>
        Object.fromEntries(Object.entries(prev).filter(([id]) => currentIds.has(id)))
      )
    }
    if (s.status === 'fulfilled') setSwarm(s.value)
    if (v.status === 'fulfilled') setVMs(v.value)
    if (e.status === 'fulfilled') setExternal(e.value)
    setIsInitialLoad(false)
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, POLL_MS)
    return () => clearInterval(id)
  }, [load])

  // Listen for expand/collapse all cards events from DrillDownBar
  useEffect(() => {
    const expandAll = () => setExpandAllFlag(true)
    const collapseAll = () => {
      setOpenKeys(new Set())
      setExpandAllFlag(false)
    }
    window.addEventListener('ds:expand-all-cards', expandAll)
    window.addEventListener('ds:collapse-all-cards', collapseAll)
    return () => {
      window.removeEventListener('ds:expand-all-cards', expandAll)
      window.removeEventListener('ds:collapse-all-cards', collapseAll)
    }
  }, [])

  // Don't count intentionally stopped resources as issues — only real problems
  const errorCount = (items) => (items || []).filter(i => i.problem && i.problem !== 'stopped').length

  return (
    <div className="flex flex-col gap-6">
      {pending && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-[#1a1a2e] border border-[#2a2a4a] rounded-lg p-6 max-w-sm w-full mx-4">
            <p className="text-white mb-4">{pending.msg}</p>
            <div className="flex gap-3 justify-end">
              <button className="px-4 py-2 text-sm text-[#888] hover:text-white" onClick={() => resolve(false)}>Cancel</button>
              <button className="px-4 py-2 text-sm bg-[#7c6af7] text-white rounded hover:bg-[#6b5af0]" onClick={() => resolve(true)}>Confirm</button>
            </div>
          </div>
        </div>
      )}
      {isInitialLoad && (
        <div className="flex justify-center py-12">
          <div className="w-6 h-6 border-2 border-[#7c6af7] border-t-transparent rounded-full animate-spin" />
        </div>
      )}

      {!isInitialLoad && <>
        {/* Containers · agent-01 — cluster Section header */}
        {show('containers_local') && (
          <Section
            label={containers?.connection_label || 'agent-01'}
            dot={containers?.containers?.some(c => c.dot === 'red') ? 'red'
               : containers?.containers?.some(c => c.dot === 'amber') ? 'amber' : 'green'}
            auth="DOCKER"
            host={containers?.connection_host || containers?.agent01_ip || ''}
            runningCount={containers?.containers?.filter(c => c.status === 'running' || c.dot === 'green').length ?? 0}
            totalCount={containers?.containers?.length ?? 0}
            issueCount={errorCount(containers?.containers)}
          >
            {[...(containers?.containers || [])].sort((a, b) => (a.name || '').localeCompare(b.name || '')).filter(c => (matchesShowFilter(c.dot) || isPinned(`docker:${c.name || c.id}`)) && matchesSearch(c.name, c.image, c.id)).map(c => (
              <InfraCard
                key={c.id} cardKey={`c-${c.id}`} openKeys={openKeys} setOpenKeys={setOpenKeys} lastOpenedKey={lastOpenedKey} setLastOpenedKey={setLastOpenedKey} forceExpanded={expandAllFlag}
                dot={c.dot} name={c.name || c.id?.slice(0, 12) || '(unknown)'} sub={_computeContainerSub(c, knownLatest)} net={_containerNet(c)} uptime={c.uptime}
                collapsed={<ContainerCardCollapsed c={c} onEntityDetail={onEntityDetail} />}
                expanded={<ContainerCardExpanded
                  c={c} isSwarm={false} onAction={load} confirm={confirm} showToast={showToast}
                  onTagsLoaded={onTagsLoaded} onTab={onTab}
                />}
                compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd}
                entityForCompare={{ id: `docker:${c.name || c.id}`, label: c.name, platform: 'docker', section: 'COMPUTE', metadata: { status: c.status, dot: c.dot, image: c.image, uptime: c.uptime } }}
              />
            ))}
          </Section>
        )}

        {/* Containers · Swarm — cluster Section header */}
        {show('containers_swarm') && (
          <Section
            label={swarm?.cluster_label || 'Docker Swarm'}
            dot={swarm?.services?.some(s => (s.dot || 'green') === 'red') ? 'red'
               : swarm?.services?.some(s => (s.dot || 'green') === 'amber') ? 'amber' : 'green'}
            auth="SWARM"
            host={`${swarm?.swarm_managers ?? '?'} mgr · ${swarm?.swarm_workers ?? '?'} wkr`}
            runningCount={swarm?.services?.filter(s => s.running_replicas === s.desired_replicas).length ?? 0}
            totalCount={swarm?.services?.length ?? 0}
            issueCount={errorCount(swarm?.services)}
          >
            {[...(swarm?.services || [])].sort((a, b) => (a.name || '').localeCompare(b.name || '')).filter(s => (matchesShowFilter(s.dot || 'green') || isPinned(`swarm:${s.name}`)) && matchesSearch(s.name, s.image)).map(s => (
              <InfraCard
                key={s.id || s.name} cardKey={`s-${s.id || s.name}`} openKeys={openKeys} setOpenKeys={setOpenKeys} lastOpenedKey={lastOpenedKey} setLastOpenedKey={setLastOpenedKey} forceExpanded={expandAllFlag}
                dot={s.dot || 'green'} name={s.name} sub={s.image} net={s.ports?.[0] ? _compactPort(s.ports[0]) : ''}
                uptime={s.running_replicas != null ? `${s.running_replicas}/${s.desired_replicas} replicas` : ''}
                collapsed={<ContainerCardCollapsed c={s} />}
                expanded={<ContainerCardExpanded c={{ ...s }} isSwarm={true} onAction={load} confirm={confirm} showToast={showToast} onTab={onTab} />}
                compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd}
                entityForCompare={{ id: `swarm:${s.name}`, label: s.name, platform: 'docker', section: 'COMPUTE', metadata: { replicas: `${s.running_replicas}/${s.desired_replicas}`, dot: s.dot, image: s.image } }}
              />
            ))}
          </Section>
        )}

        {/* VMs + LXC · Proxmox */}
        {/* VMs + LXC · Proxmox — one Section per cluster */}
        {show('vms') && (() => {
          const clusters = vms?.clusters || []

          // Backward compat: if no clusters array, fall back to flat vms/lxc
          const clusterList = clusters.length > 0 ? clusters : (
            (vms?.vms?.length || vms?.lxc?.length)
              ? [{
                  health: vms?.health,
                  connection_label: vms?.connection_label || 'Proxmox Cluster',
                  connection_host: vms?.connection_host || '',
                  connection_id: '',
                  vms: vms?.vms || [],
                  lxc: vms?.lxc || [],
                }]
              : []
          )

          if (!clusterList.length) return null

          return clusterList.map((cluster, clusterIdx) => {
            const allItems = [...(cluster.vms || []), ...(cluster.lxc || [])]
            const clusterFilters = getClusterFilters(cluster.connection_id || clusterIdx)
            const filtered = applyProxmoxFilters(allItems, clusterFilters)
            const sorted   = sortProxmoxItems(filtered, sortBy, sortDir)
            const connLabel = cluster.connection_label || 'Proxmox Cluster'
            const connHost  = cluster.connection_host || ''
            const runningCount = allItems.filter(v => v.status === 'running').length
            const issues = allItems.filter(v => v.dot === 'red' || v.dot === 'amber').length
            const clusterDot = cluster.health === 'healthy' ? 'green'
                             : cluster.health === 'critical' ? 'red'
                             : cluster.health === 'error' ? 'red'
                             : issues > 0 ? 'amber' : 'green'

            return (
              <Section
                key={cluster.connection_id || clusterIdx}
                label={connLabel}
                dot={clusterDot}
                auth="API"
                host={connHost}
                runningCount={runningCount}
                totalCount={allItems.length}
                issueCount={issues}
                cardMinWidth={240}
                compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd}
                entityForCompare={{
                  id: `cluster:proxmox:${connLabel}`,
                  label: connLabel, platform: 'proxmox', section: 'COMPUTE',
                  metadata: { host: connHost, running: runningCount, total: allItems.length, issues }
                }}
                filterBar={
                  <ProxmoxFilterBar
                    items={allItems}
                    filters={getClusterFilters(cluster.connection_id || clusterIdx)}
                    setFilters={(updater) => setClusterFilters(cluster.connection_id || clusterIdx, updater)}
                    sort={{ sortBy, sortDir }}
                    onSort={(by, dir) => { setSortBy(by); setSortDir(dir) }}
                  />
                }
              >
                {sorted.length === 0 && allItems.length > 0 && (
                  <div className="col-span-full text-[10px] text-gray-700 py-2">no items match filter</div>
                )}
                {sorted.filter(vm =>
                  (matchesShowFilter(vm.dot) || isPinned(`proxmox:${vm.name}:${vm.vmid}`))
                  && matchesSearch(vm.name, vm.vmid, vm.node, vm.ip)
                ).map(vm => (
                  <InfraCard
                    key={`${vm.type}-${vm.vmid}`}
                    cardKey={`v-${cluster.connection_id || clusterIdx}-${vm.type}-${vm.vmid}`}
                    openKeys={openKeys} setOpenKeys={setOpenKeys} lastOpenedKey={lastOpenedKey} setLastOpenedKey={setLastOpenedKey} forceExpanded={expandAllFlag}
                    dot={vm.dot}
                    name={vm.name}
                    sub={`${vm.type === 'lxc' ? 'CT' : 'VM'} ${vm.vmid} · ${vm.node}${vm.pool ? ` · ${vm.pool}` : ''}`}
                    net={vm.ip || ''} uptime={vm.uptime || ''}
                    collapsed={<ProxmoxCardCollapsed vm={vm} onEntityDetail={onEntityDetail} onChat={onChat} />}
                    expanded={<ProxmoxCardExpanded vm={vm} proxmoxHost={cluster.connection_host} proxmoxPort={cluster.connection_port || 8006} onAction={load} confirm={confirm} showToast={showToast} />}
                    compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd}
                    entityForCompare={{
                      id: `proxmox:${vm.name}:${vm.vmid}`,
                      label: vm.name, platform: 'proxmox', section: 'COMPUTE',
                      metadata: { vmid: vm.vmid, node: vm.node_api, type: vm.type, status: vm.status,
                                  vcpus: vm.vcpus, maxmem_gb: vm.maxmem_gb, cpu_pct: vm.cpu_pct, dot: vm.dot }
                    }}
                  />
                ))}
              </Section>
            )
          })
        })()}

        {/* External Services */}
        {show('external') && (
          <Section
            label="External Services"
            meta={`${external?.services?.filter(s => s.reachable).length ?? '…'} / ${external?.services?.length ?? '…'} reachable`}
            errorCount={errorCount(external?.services)}
          >
            {(external?.services || []).filter(svc => (matchesShowFilter(svc.dot) || isPinned(`external_services:${svc.slug}`)) && matchesSearch(svc.name, svc.host_port, svc.slug)).map(svc => (
              <InfraCard
                key={svc.slug} cardKey={`e-${svc.slug}`} openKeys={openKeys} setOpenKeys={setOpenKeys} lastOpenedKey={lastOpenedKey} setLastOpenedKey={setLastOpenedKey} forceExpanded={expandAllFlag}
                dot={svc.dot} name={svc.name} sub={svc.service_type} net={svc.host_port}
                uptime={svc.latency_ms != null ? `${svc.latency_ms}ms` : ''}
                collapsed={<ExternalCardCollapsed svc={svc} onEntityDetail={onEntityDetail} compareMode={compareMode} onCompareAdd={onCompareAdd} />}
                expanded={<ExternalCardExpanded svc={svc} onAction={load} />}
                compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd}
                entityForCompare={{ id: `external_services:${svc.slug}`, label: svc.name, platform: svc.slug, section: svc.service_type === 'fortigate' ? 'NETWORK' : 'PLATFORM', metadata: { host_port: svc.host_port, latency_ms: svc.latency_ms, reachable: svc.reachable, dot: svc.dot } }}
              />
            ))}
          </Section>
        )}

        {/* UniFi Devices */}
        {show('unifi') && unifiConn && (() => {
          const devices   = unifiData?.devices || []
          const devUp     = devices.filter(d => d.state === 'connected').length
          const devDown   = devices.length - devUp
          const dot       = unifiData?.health === 'healthy' ? 'green'
                          : unifiData?.health === 'degraded' ? 'amber'
                          : unifiData ? 'red' : 'grey'
          const clientTot = unifiData?.client_count ?? 0
          const filteredDevices = applyConnectionFilters(devices, unifiFilters, UNIFI_FILTER_FIELDS)
          return (
            <Section
              label={unifiConn.label || unifiConn.host}
              dot={dot}
              auth="API KEY"
              host={`${unifiConn.host}:${unifiConn.port || 443}`}
              runningCount={devUp}
              totalCount={devices.length}
              issueCount={devDown}
              countLabels={['up', 'total', 'issues']}
              compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd}
              entityForCompare={{
                id: `unifi:${unifiConn.label || unifiConn.host}`,
                label: unifiConn.label || unifiConn.host,
                platform: 'unifi', section: 'NETWORK',
                metadata: { host: `${unifiConn.host}:${unifiConn.port || 443}`, devices: devices.length, clients: clientTot }
              }}
              filterBar={
                <ConnectionFilterBar
                  items={devices}
                  filters={unifiFilters}
                  setFilters={setUnifiFilters}
                  fields={UNIFI_FILTER_FIELDS}
                />
              }
            >
              {filteredDevices.filter(d => {
                const devDot = d.state === 'connected' ? 'green' : 'amber'
                const eid = `unifi:device:${d.mac || d.name}`
                return (matchesShowFilter(devDot) || isPinned(eid)) && matchesSearch(d.name, d.mac, d.model)
              }).map(dev => {
                const devDot = dev.state === 'connected' ? 'green' : 'amber'
                const uptimeFmt = (() => {
                  if (!dev.uptime) return ''
                  const d = Math.floor(dev.uptime / 86400)
                  const h = Math.floor((dev.uptime % 86400) / 3600)
                  return d > 0 ? `${d}d` : `${h}h`
                })()
                return (
                  <InfraCard
                    key={dev.mac || dev.name}
                    cardKey={`unifi-${dev.mac || dev.name}`}
                    openKeys={openKeys} setOpenKeys={setOpenKeys} lastOpenedKey={lastOpenedKey} setLastOpenedKey={setLastOpenedKey} forceExpanded={expandAllFlag}
                    dot={devDot}
                    name={dev.name}
                    sub={`${dev.type_label} · ${dev.model}`}
                    net={_displayIp(dev.ip) || ''}
                    uptime={uptimeFmt}
                    collapsed={
                      <div className="text-[10px] mt-1" style={{ color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
                        {dev.clients} clients
                      </div>
                    }
                    expanded={
                      <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-3)' }}>
                        <div>Model: <span style={{ color: 'var(--text-1)' }}>{dev.model}</span></div>
                        <div>Clients: <span style={{ color: 'var(--text-1)' }}>{dev.clients}</span></div>
                        <div>Uptime: <span style={{ color: 'var(--text-1)' }}>{uptimeFmt || '—'}</span></div>
                        <div>Version: <span style={{ color: 'var(--text-1)' }}>{dev.version || '—'}</span></div>
                        <div>State: <span style={{ color: devDot === 'green' ? 'var(--green)' : 'var(--amber)' }}>{dev.state}</span></div>
                        <div>MAC: <span style={{ color: 'var(--text-2)' }}>{dev.mac}</span></div>
                      </div>
                    }
                    compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd}
                    entityForCompare={{
                      id: `unifi:device:${dev.mac || dev.name}`,
                      label: dev.name, platform: 'unifi', section: 'NETWORK',
                      metadata: { type: dev.type_label, model: dev.model, clients: dev.clients, state: dev.state, uptime: dev.uptime, version: dev.version }
                    }}
                  />
                )
              })}
              {filteredDevices.length === 0 && unifiData && (
                <div className="col-span-full text-[10px] text-gray-700 py-2">No devices found</div>
              )}
              {!unifiData && (
                <div className="col-span-full text-[10px] text-gray-700 py-2">Loading UniFi devices…</div>
              )}
            </Section>
          )
        })()}

        {/* PBS Datastores */}
        {show('pbs') && pbsConn && (() => {
          const datastores = pbsData?.datastores || []
          const dsOk    = datastores.filter(d => d.usage_pct <= 85).length
          const dsWarn  = datastores.filter(d => d.usage_pct > 85).length
          const dot     = pbsData?.health === 'healthy' ? 'green'
                        : pbsData?.health === 'degraded' ? 'amber'
                        : pbsData ? 'red' : 'grey'
          const tasks   = pbsData?.tasks || {}
          return (
            <Section
              label={pbsConn.label || pbsConn.host}
              dot={dot}
              auth="TOKEN"
              host={`${pbsConn.host}:${pbsConn.port || 8007}`}
              runningCount={dsOk}
              totalCount={datastores.length}
              issueCount={dsWarn}
              countLabels={['ok', 'total', 'issues']}
              compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd}
              entityForCompare={{
                id: `pbs:${pbsConn.label || pbsConn.host}`,
                label: pbsConn.label || pbsConn.host,
                platform: 'pbs', section: 'STORAGE',
                metadata: { host: `${pbsConn.host}:${pbsConn.port || 8007}`, datastores: datastores.length }
              }}
            >
              {datastores.filter(ds => {
                const dsDot = ds.usage_pct > 95 ? 'red' : ds.usage_pct > 85 ? 'amber' : 'green'
                const eid = `pbs:datastore:${ds.name}`
                return (matchesShowFilter(dsDot) || isPinned(eid)) && matchesSearch(ds.name)
              }).map(ds => {
                const pct = ds.usage_pct ?? 0
                const dsDot = pct > 95 ? 'red' : pct > 85 ? 'amber' : 'green'
                const barColor = pct > 95 ? 'var(--red)' : pct > 85 ? 'var(--amber)' : 'var(--green)'
                return (
                  <InfraCard
                    key={ds.name}
                    cardKey={`pbs-${ds.name}`}
                    openKeys={openKeys} setOpenKeys={setOpenKeys} lastOpenedKey={lastOpenedKey} setLastOpenedKey={setLastOpenedKey} forceExpanded={expandAllFlag}
                    dot={dsDot}
                    name={ds.name}
                    sub={`${Math.round(pct)}% used`}
                    net={''}
                    uptime={`${ds.total_gb} GB`}
                    collapsed={
                      <div style={{ marginTop: 4 }}>
                        <div style={{ height: 3, borderRadius: 2, background: 'var(--bg-3)', overflow: 'hidden' }}>
                          <div style={{ height: '100%', width: `${pct}%`, background: barColor, borderRadius: 2 }} />
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, marginTop: 2, fontFamily: 'var(--font-mono)', color: 'var(--text-3)' }}>
                          <span>{ds.used_gb} GB used</span>
                          <span>{ds.total_gb} GB total</span>
                        </div>
                      </div>
                    }
                    expanded={
                      <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-3)' }}>
                        <div style={{ marginBottom: 6 }}>
                          <div style={{ height: 4, borderRadius: 2, background: 'var(--bg-3)', overflow: 'hidden', marginBottom: 4 }}>
                            <div style={{ height: '100%', width: `${pct}%`, background: barColor, borderRadius: 2 }} />
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                            <span>{ds.used_gb} GB used</span>
                            <span style={{ color: 'var(--text-1)' }}>{Math.round(pct)}%</span>
                            <span>{ds.total_gb} GB total</span>
                          </div>
                        </div>
                        <div>GC status: <span style={{ color: 'var(--text-1)' }}>{ds.gc_status || '—'}</span></div>
                        {ds.snapshot_count != null && (
                          <div>Snapshots: <span style={{ color: 'var(--text-1)' }}>{ds.snapshot_count}</span></div>
                        )}
                        {tasks.recent_count != null && (
                          <div style={{ marginTop: 4, paddingTop: 4, borderTop: '1px solid var(--bg-3)' }}>
                            Tasks (last 20): <span style={{ color: 'var(--green)' }}>{tasks.recent_count - (tasks.failed_count || 0)} OK</span>
                            {tasks.failed_count > 0 && <span style={{ color: 'var(--red)', marginLeft: 6 }}>{tasks.failed_count} failed</span>}
                          </div>
                        )}
                      </div>
                    }
                    compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd}
                    entityForCompare={{
                      id: `pbs:datastore:${ds.name}`,
                      label: ds.name, platform: 'pbs', section: 'STORAGE',
                      metadata: { usage_pct: pct, used_gb: ds.used_gb, total_gb: ds.total_gb, gc_status: ds.gc_status }
                    }}
                  />
                )
              })}
              {datastores.length === 0 && pbsData && (
                <div className="col-span-full text-[10px] text-gray-700 py-2">No datastores found</div>
              )}
              {!pbsData && (
                <div className="col-span-full text-[10px] text-gray-700 py-2">Loading PBS datastores…</div>
              )}
            </Section>
          )
        })()}
        {/* TrueNAS Pools */}
        {show('truenas') && truenasConn && (() => {
          const pools   = truenasData?.pools || []
          const poolsOk = pools.filter(p => p.healthy && p.status === 'ONLINE' && p.usage_pct <= 85).length
          const issues  = pools.filter(p => !p.healthy || p.status !== 'ONLINE' || p.usage_pct > 85).length
          const dot     = truenasData?.health === 'healthy' ? 'green'
                        : truenasData?.health === 'degraded' ? 'amber'
                        : truenasData ? 'red' : 'grey'
          return (
            <Section
              label={truenasConn.label || truenasConn.host}
              dot={dot}
              auth="API KEY"
              host={`${truenasConn.host}:${truenasConn.port || 443}`}
              runningCount={poolsOk}
              totalCount={pools.length}
              issueCount={issues}
              countLabels={['ok', 'total', 'issues']}
              compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd}
              entityForCompare={{
                id: `truenas:${truenasConn.label || truenasConn.host}`,
                label: truenasConn.label || truenasConn.host,
                platform: 'truenas', section: 'STORAGE',
                metadata: { host: `${truenasConn.host}:${truenasConn.port || 443}`, pools: pools.length }
              }}
            >
              {pools.filter(pool => {
                const poolDot = !pool.healthy || pool.status !== 'ONLINE' ? 'red'
                              : pool.usage_pct > 85 ? 'amber' : 'green'
                return (matchesShowFilter(poolDot) || isPinned(`truenas:pool:${pool.name}`)) && matchesSearch(pool.name)
              }).map(pool => {
                const pct      = pool.usage_pct ?? 0
                const healthy  = pool.healthy && pool.status === 'ONLINE'
                const poolDot  = !healthy ? 'red' : pct > 85 ? 'amber' : 'green'
                const barColor = !healthy ? 'var(--red)' : pct > 85 ? 'var(--amber)' : 'var(--green)'
                return (
                  <InfraCard
                    key={pool.name}
                    cardKey={`truenas-${pool.name}`}
                    openKeys={openKeys} setOpenKeys={setOpenKeys} lastOpenedKey={lastOpenedKey} setLastOpenedKey={setLastOpenedKey} forceExpanded={expandAllFlag}
                    dot={poolDot}
                    name={pool.name}
                    sub={`${Math.round(pct)}% used`}
                    net={''}
                    uptime={`${pool.size_gb} GB`}
                    collapsed={
                      <div style={{ marginTop: 4 }}>
                        <div style={{ height: 3, borderRadius: 2, background: 'var(--bg-3)', overflow: 'hidden' }}>
                          <div style={{ height: '100%', width: `${pct}%`, background: barColor, borderRadius: 2 }} />
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, marginTop: 2, fontFamily: 'var(--font-mono)', color: 'var(--text-3)' }}>
                          <span>{pool.allocated_gb} GB used</span>
                          <span>{pool.size_gb} GB total</span>
                        </div>
                      </div>
                    }
                    expanded={
                      <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-3)' }}>
                        <div style={{ marginBottom: 6 }}>
                          <div style={{ height: 4, borderRadius: 2, background: 'var(--bg-3)', overflow: 'hidden', marginBottom: 4 }}>
                            <div style={{ height: '100%', width: `${pct}%`, background: barColor, borderRadius: 2 }} />
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                            <span>{pool.allocated_gb} GB used</span>
                            <span style={{ color: 'var(--text-1)' }}>{Math.round(pct)}%</span>
                            <span>{pool.size_gb} GB total</span>
                          </div>
                        </div>
                        <div>Status: <span style={{ color: poolDot === 'green' ? 'var(--green)' : 'var(--red)' }}>{pool.status}</span></div>
                        <div>Free: <span style={{ color: 'var(--text-1)' }}>{pool.free_gb} GB</span></div>
                        <div>vDevs: <span style={{ color: 'var(--text-1)' }}>{pool.vdev_count}</span></div>
                        <div>Scan: <span style={{ color: 'var(--text-1)' }}>{pool.scan_state || '—'}{pool.scan_errors > 0 ? ` (${pool.scan_errors} errors)` : ''}</span></div>
                      </div>
                    }
                    compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd}
                    entityForCompare={{
                      id: `truenas:pool:${pool.name}`,
                      label: pool.name, platform: 'truenas', section: 'STORAGE',
                      metadata: { status: pool.status, healthy: pool.healthy, usage_pct: pct, allocated_gb: pool.allocated_gb, size_gb: pool.size_gb, free_gb: pool.free_gb, scan_state: pool.scan_state }
                    }}
                  />
                )
              })}
              {pools.length === 0 && truenasData && (
                <div className="col-span-full text-[10px] text-gray-700 py-2">No pools found</div>
              )}
              {!truenasData && (
                <div className="col-span-full text-[10px] text-gray-700 py-2">Loading TrueNAS pools…</div>
              )}
            </Section>
          )
        })()}
        {/* FortiGate Interfaces */}
        {show('fortigate') && fgConn && (() => {
          const ifaces     = fgData?.interfaces || []
          const ifacesUp   = ifaces.filter(i => i.link && !((i.rx_errors || 0) + (i.tx_errors || 0))).length
          const ifacesDown = ifaces.filter(i => !i.link).length
          const ifacesWarn = ifaces.filter(i => i.link && ((i.rx_errors || 0) + (i.tx_errors || 0)) > 0).length
          const issues     = ifacesDown + ifacesWarn
          const dot        = fgData?.health === 'healthy' ? 'green'
                           : fgData?.health === 'degraded' ? 'amber'
                           : fgData ? 'red' : 'grey'
          const hostname   = fgData?.hostname || fgConn.label || fgConn.host
          const version    = fgData?.version || ''
          const haMode     = fgData?.ha_mode || ''

          return (
            <Section
              label={hostname}
              dot={dot}
              auth="API KEY"
              host={`${fgConn.host}:${fgConn.port || 443}`}
              runningCount={ifacesUp}
              totalCount={ifaces.length}
              issueCount={issues}
              countLabels={['up', 'total', 'issues']}
              filterBar={
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {version && (
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)',
                                  display: 'flex', gap: 12, alignItems: 'center' }}>
                      <span>{version}</span>
                      {haMode && haMode !== 'standalone' && (
                        <span style={{ color: 'var(--amber)' }}>HA: {haMode}</span>
                      )}
                      {fgData?.serial && <span>{fgData.serial}</span>}
                    </div>
                  )}
                  <ConnectionFilterBar
                    items={ifaces.map(i => ({ ...i, status: i.link ? 'up' : 'down' }))}
                    filters={fgFilters}
                    setFilters={setFgFilters}
                    fields={FG_FILTER_FIELDS}
                  />
                </div>
              }
              compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd}
              entityForCompare={{
                id: `fortigate:${fgConn.label || fgConn.host}`,
                label: hostname,
                platform: 'fortigate', section: 'NETWORK',
                metadata: { host: `${fgConn.host}:${fgConn.port || 443}`, version, ha_mode: haMode, interfaces: ifaces.length }
              }}
            >
              {applyConnectionFilters(ifaces.map(i => ({ ...i, status: i.link ? 'up' : 'down' })), fgFilters, FG_FILTER_FIELDS).filter(i => {
                const errors = (i.rx_errors || 0) + (i.tx_errors || 0)
                const ifDot = !i.link ? 'red' : errors > 0 ? 'amber' : 'green'
                const eid = `fortigate:iface:${i.name}`
                return (matchesShowFilter(ifDot) || isPinned(eid)) && matchesSearch(i.name, i.alias, i.ip)
              }).map(iface => {
                const errors = (iface.rx_errors || 0) + (iface.tx_errors || 0)
                const ifDot  = !iface.link ? 'red' : errors > 0 ? 'amber' : 'green'
                const label  = iface.alias || iface.name
                const speed  = iface.speed ? `${iface.speed >= 1000 ? `${iface.speed / 1000}G` : `${iface.speed}M`}` : ''

                return (
                  <InfraCard
                    key={iface.name}
                    cardKey={`fg-${iface.name}`}
                    openKeys={openKeys} setOpenKeys={setOpenKeys} lastOpenedKey={lastOpenedKey} setLastOpenedKey={setLastOpenedKey} forceExpanded={expandAllFlag}
                    dot={ifDot}
                    name={label}
                    sub={`${iface.type || ''} ${speed ? '· ' + speed : ''}`.trim()}
                    net={iface.ip || ''}
                    uptime={''}
                    collapsed={
                      <div style={{ marginTop: 4 }}>
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center',
                                      fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)' }}>
                          <span style={{ color: ifDot === 'green' ? 'var(--green)' : ifDot === 'amber' ? 'var(--amber)' : 'var(--red)' }}>
                            {iface.link ? '● up' : '○ down'}
                          </span>
                          {iface.ip && <span>{iface.ip}</span>}
                          {errors > 0 && <span style={{ color: 'var(--amber)' }}>{errors} errors</span>}
                        </div>
                      </div>
                    }
                    expanded={
                      <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-3)' }}>
                        <div>Interface: <span style={{ color: 'var(--text-1)' }}>{iface.name}</span></div>
                        {iface.alias && <div>Alias: <span style={{ color: 'var(--text-1)' }}>{iface.alias}</span></div>}
                        <div>Type: <span style={{ color: 'var(--text-1)' }}>{iface.type || '—'}</span></div>
                        <div>IP: <span style={{ color: 'var(--text-1)' }}>{iface.ip || '—'}</span></div>
                        <div>Speed: <span style={{ color: 'var(--text-1)' }}>{speed || '—'}</span></div>
                        <div>Link: <span style={{ color: iface.link ? 'var(--green)' : 'var(--red)' }}>
                          {iface.link ? 'up' : 'down'}
                        </span></div>
                        {(iface.rx_bytes != null || iface.tx_bytes != null) && (
                          <div style={{ marginTop: 4, paddingTop: 4, borderTop: '1px solid var(--bg-3)' }}>
                            <div>RX: <span style={{ color: 'var(--text-1)' }}>{_fgBytes(iface.rx_bytes)}</span></div>
                            <div>TX: <span style={{ color: 'var(--text-1)' }}>{_fgBytes(iface.tx_bytes)}</span></div>
                            {errors > 0 && (
                              <div style={{ color: 'var(--amber)' }}>
                                Errors: RX {iface.rx_errors || 0} · TX {iface.tx_errors || 0}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    }
                    compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd}
                    entityForCompare={{
                      id: `fortigate:iface:${iface.name}`,
                      label: `${hostname}/${label}`, platform: 'fortigate', section: 'NETWORK',
                      metadata: { interface: iface.name, alias: iface.alias, link: iface.link,
                                  type: iface.type, ip: iface.ip, speed: iface.speed,
                                  rx_bytes: iface.rx_bytes, tx_bytes: iface.tx_bytes, errors }
                    }}
                  />
                )
              })}
              {ifaces.length === 0 && fgData && (
                <div className="col-span-full text-[10px] text-gray-700 py-2">No interfaces found</div>
              )}
              {!fgData && (
                <div className="col-span-full text-[10px] text-gray-700 py-2">Loading FortiGate interfaces…</div>
              )}
            </Section>
          )
        })()}
      </>}

      <Toast toasts={toasts} />
    </div>
  )
}
