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
  dashboardAction, fetchContainerTags, createLogStream,
  authHeaders,
} from '../api'
import { compareSemver, compareBuildTag } from '../utils/versionCheck'
import { useOptions } from '../context/OptionsContext'

const POLL_MS = 30_000

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

function InfraCard({ cardKey, openKey, setOpenKey, dot, name, sub, net, collapsed, expanded }) {
  const isOpen = openKey === cardKey
  const cs = cardState(dot)
  const { cardMinHeight } = useOptions()
  return (
    <div
      className={`${cs.bg} border ${isOpen ? 'border-violet-500 shadow-[0_0_0_1px_rgba(124,106,247,0.15)]' : cs.border} rounded-lg px-2.5 py-2.5 cursor-pointer transition-colors`}
      style={isOpen ? undefined : { minHeight: cardMinHeight }}
      onClick={() => setOpenKey(isOpen ? null : cardKey)}
    >
      <div className="flex items-center gap-1.5 mb-0.5">
        <Dot color={dot} />
        <span className={`text-[12px] font-semibold truncate ${cs.nameCls}`}>{name}</span>
      </div>
      {sub && (
        typeof sub === 'object'
          ? <div className={`text-[10px] font-mono truncate mb-0.5 ${sub.cls}`}>{sub.text}</div>
          : <div className="text-[10px] text-[#3a3a5a] font-mono truncate mb-0.5">{sub}</div>
      )}
      <div className="text-[10px] text-[#4a5a7a] font-mono mb-1">{net || '—'}</div>
      {isOpen ? (
        <div onClick={e => e.stopPropagation()}>
          {expanded}
          <button className="mt-1.5 w-full text-[9px] text-gray-700 hover:text-gray-500" onClick={() => setOpenKey(null)}>✕ close</button>
        </div>
      ) : collapsed}
    </div>
  )
}

// ── Section wrapper ────────────────────────────────────────────────────────────

function Section({ label, meta, errorCount, filterBar, children }) {
  const { cardMinWidth, cardMaxWidth } = useOptions()
  const _min = cardMinWidth ?? 300
  const _max = cardMaxWidth ? `${cardMaxWidth}px` : '1fr'
  return (
    <div>
      <div className="flex items-baseline gap-2 mb-2">
        <span className="text-[11px] text-gray-600 uppercase tracking-wider">{label}</span>
        {meta && <span className="text-[10px] text-gray-800">{meta}</span>}
        {errorCount > 0 && <span className="text-[10px] text-red-500/60">{errorCount} issue{errorCount !== 1 ? 's' : ''}</span>}
      </div>
      {filterBar}
      <div className="grid gap-2" style={{
        gridTemplateColumns: `repeat(auto-fill, minmax(${_min}px, ${_max}))`,
        ...(cardMaxWidth ? { justifyContent: 'start' } : {}),
      }}>
        {children}
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
        { v: c.uptime || (c.replicas_running != null ? `${c.replicas_running}/${c.replicas_desired}` : '—'), l: isSwarm ? 'Replicas' : 'Uptime' },
      ]} />
      {c.ports?.length > 0 && (
        <div className="text-[10px] text-[#4a6a9a] font-mono mb-1.5">
          <span className="text-[9px] text-gray-700">ports </span>{c.ports.join(' · ')}
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
                  ? <span className="text-gray-700">no versioned tags</span>
                  : severity === 'current'
                  ? <span className="text-[9px] px-1.5 py-px rounded bg-[#0d1f0d] text-green-400 border border-[#1a3a1a]">✓ latest</span>
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
            {(tagsError || (!tagsLoading && !tags.length) || severity === 'ahead' || severity === 'unknown') && (
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
        isSwarm && !scaleOpen && <ActionBtn key="scale" label="Scale" loading={loading.scale} onClick={() => { setScaleVal(c.replicas_desired ?? 1); setScaleOpen(true) }} />,
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

function ContainerCardCollapsed({ c, latestTag }) {
  const severity = (c.running_version && latestTag)
    ? compareSemver(c.running_version, latestTag)
    : null
  const hasUpdate = severity === 'major' || severity === 'minor' || severity === 'patch'
  return (
    <>
      <div className="text-[10px] text-[#383850] mb-1">{c.uptime || (c.replicas_running != null ? `${c.replicas_running}/${c.replicas_desired} replicas` : '')}</div>
      {c.problem && (
        <div className="text-[10px] px-1.5 py-px rounded inline-flex items-center gap-1 bg-red-950/50 text-red-400 border border-red-900/40 mb-1">⚠ {c.problem}</div>
      )}
      {(c.running_version || c.built_at) && (
        <div className="border-t border-[#1a1a30] pt-1 mt-0.5">
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
          {c.running_version && (
            <div className="flex justify-between text-[9px]">
              <span className="text-gray-700">Status</span>
              {severity === 'current'
                ? <span className="text-[9px] px-1.5 py-px rounded bg-[#0d1f0d] text-green-400 border border-[#1a3a1a]">✓ latest</span>
                : hasUpdate
                ? <span className={`text-[9px] px-1.5 py-px rounded border ${severity === 'major' ? 'bg-[#1a0808] text-red-400 border-[#3a1010]' : 'bg-[#2a1e05] text-amber-400 border-[#3d2d0a]'}`}>↑ {latestTag}</span>
                : <span className="text-gray-700">—</span>
              }
            </div>
          )}
        </div>
      )}
    </>
  )
}

// ── VM / LXC card ─────────────────────────────────────────────────────────────

function ProxmoxCardExpanded({ vm, onAction, confirm, showToast }) {
  const [loading, setLoading] = useState({})
  const mounted = useRef(true)
  useEffect(() => () => { mounted.current = false }, [])

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
            <ActionBtn key="proxmox" label="View in Proxmox" onClick={() => window.open(`https://${location.hostname}:8006`, '_blank')} />,
          ]
          : [
            !isLxc && <ActionBtn key="console" label="Open Console" onClick={() => window.open(`https://${location.hostname}:8006/?console=kvm&vmid=${vm.vmid}&node=${vm.node_api}&novnc=1`, '_blank')} />,
            isLxc && <ActionBtn key="console" label="Open Console" onClick={() => window.open(`https://${location.hostname}:8006/?console=lxc&vmid=${vm.vmid}&node=${vm.node_api}&novnc=1`, '_blank')} />,
            <ActionBtn key="proxmox" label="View in Proxmox" onClick={() => window.open(`https://${location.hostname}:8006`, '_blank')} />,
            isLxc && <ActionBtn key="stop" label="Stop" variant="danger" loading={loading.stop} onClick={() => act('stop', 'stop', `Stop ${vm.name}?`)} />,
            <ActionBtn key="reboot" label="Reboot" variant="danger" loading={loading.reboot} onClick={() => act('reboot', 'reboot', `Reboot ${vm.name}? It will be temporarily unreachable.`)} />,
          ].filter(Boolean)
      } />
    </>
  )
}

function ProxmoxCardCollapsed({ vm }) {
  const typeBadge = vm.type === 'lxc'
    ? <span className="text-[9px] px-1 py-px rounded bg-[#0a1a2a] text-cyan-600 border border-[#0d2030] mr-1">LXC</span>
    : <span className="text-[9px] px-1 py-px rounded bg-[#0d0a2a] text-violet-600 border border-[#1a1040] mr-1">VM</span>
  return (
    <>
      <div className="text-[10px] text-[#383850] mb-1">{vm.vcpus} vCPU · {vm.maxmem_gb} GB RAM</div>
      {vm.problem
        ? <div className="text-[10px] px-1.5 py-px rounded inline-flex items-center gap-1 bg-amber-950/40 text-amber-400 border border-amber-900/30 mb-1">⚠ {vm.problem}</div>
        : <div className="flex items-center">{typeBadge}<span className="text-[9px] px-1.5 py-px rounded bg-[#0d1a2a] text-blue-400 border border-[#1a2a3a]">● {vm.status}</span></div>}
    </>
  )
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
          <div className="relative flex items-center gap-0.5 ml-auto">
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
  const [liveLatency, setLiveLatency] = useState(null)
  const mounted = useRef(true)
  useEffect(() => () => { mounted.current = false }, [])

  const probe = async () => {
    setProbeLoading(true)
    const r = await dashboardAction(`external/${svc.slug}/probe`)
    if (!mounted.current) return
    setProbeLoading(false)
    if (r.latency_ms != null) setLiveLatency(r.latency_ms)
  }

  const latency = liveLatency ?? svc.latency_ms
  return (
    <>
      <StatRow stats={[
        { v: latency != null ? `${latency} ms` : '—', l: 'Latency', color: !svc.reachable ? 'text-red-400' : latency > 100 ? 'text-amber-400' : 'text-green-400' },
        { v: svc.reachable ? 'online' : 'offline', l: 'Status', color: svc.reachable ? 'text-gray-300' : 'text-red-400' },
      ]} />
      {svc.storage && <><VolBar vol={{ name: svc.storage.name, used_bytes: svc.storage.used_bytes, total_bytes: svc.storage.total_bytes }} /><Divider /></>}
      <Actions buttons={[
        <ActionBtn key="probe" label="Test Connection" loading={probeLoading} onClick={probe} />,
        svc.open_ui_url && <ActionBtn key="ui" label="Open UI" onClick={() => window.open(svc.open_ui_url, '_blank')} />,
      ].filter(Boolean)} />
    </>
  )
}

function ExternalCardCollapsed({ svc }) {
  const latencyColor = !svc.reachable ? 'text-red-400' : svc.latency_ms > 100 ? 'text-amber-400' : 'text-green-400'
  return (
    <>
      <div className="text-[10px] text-[#383850] mb-1 truncate">{svc.summary}</div>
      {svc.problem
        ? <div className="text-[10px] px-1.5 py-px rounded inline-flex gap-1 bg-red-950/50 text-red-400 border border-red-900/40">⚠ {svc.problem}</div>
        : <span className={`text-[10px] font-mono ${latencyColor}`}>● {svc.latency_ms != null ? `${svc.latency_ms} ms` : '—'}</span>}
    </>
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
  if (!latestTag || !c.running_version) return c.image
  const severity = compareBuildTag(c.running_version, latestTag)
  const imageName = c.image.split('/').pop().split(':')[0]
  if (severity === 'major') return { text: `${imageName}: not latest`, cls: 'text-[#b04020]' }
  if (severity === 'minor' || severity === 'patch') return { text: `${imageName}: not latest`, cls: 'text-[#92601a]' }
  return c.image
}

// ── Auto-update toggle (agent container only) ────────────────────────────────

const BASE = import.meta.env.VITE_API_BASE ?? ''

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

export default function ServiceCards({ activeFilters = null, onTab }) {
  // If no filter passed, show everything
  const show = (key) => !activeFilters || activeFilters.includes(key)
  const [containers, setContainers] = useState(null)
  const [swarm, setSwarm]           = useState(null)
  const [vms, setVMs]               = useState(null)
  const [external, setExternal]     = useState(null)
  const [openKey, setOpenKey]       = useState(null)
  const [isInitialLoad, setIsInitialLoad] = useState(true)
  const [proxmoxFilters, setProxmoxFilters] = useState({})
  const [sortBy, setSortBy] = useState(() => {
    try {
      const s = JSON.parse(localStorage.getItem('hp1_proxmox_sort') || '{}')
      return s.sortBy || 'vmid'
    } catch { return 'vmid' }
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
        {/* Containers · agent-01 */}
        {show('containers_local') && (
          <Section
            label="Containers · agent-01"
            meta={`${containers?.agent01_ip || ''} · ${containers?.containers?.length ?? '…'} running`}
            errorCount={errorCount(containers?.containers)}
          >
            {(containers?.containers || []).map(c => (
              <InfraCard
                key={c.id} cardKey={`c-${c.id}`} openKey={openKey} setOpenKey={setOpenKey}
                dot={c.dot} name={c.name} sub={_computeContainerSub(c, knownLatest)} net={c.ip_port}
                collapsed={<ContainerCardCollapsed c={c} latestTag={knownLatest[c.id]} />}
                expanded={<ContainerCardExpanded
                  c={c} isSwarm={false} onAction={load} confirm={confirm} showToast={showToast}
                  onTagsLoaded={onTagsLoaded} onTab={onTab}
                />}
              />
            ))}
          </Section>
        )}

        {/* Containers · Swarm */}
        {show('containers_swarm') && (
          <Section
            label="Containers · Swarm"
            meta={`${swarm?.swarm_managers ?? '…'} managers · ${swarm?.swarm_workers ?? '…'} workers · ${swarm?.services?.length ?? '…'} services`}
            errorCount={errorCount(swarm?.services)}
          >
            {(swarm?.services || []).map(s => (
              <InfraCard
                key={s.id || s.name} cardKey={`s-${s.id || s.name}`} openKey={openKey} setOpenKey={setOpenKey}
                dot={s.dot || 'green'} name={s.name} sub={s.image} net={s.ports?.[0] ? `:${s.ports[0].split('→')[0]}` : ''}
                collapsed={<ContainerCardCollapsed c={{ ...s, uptime: `${s.replicas_running}/${s.replicas_desired} replicas · since ${_relativeTime(s.created_at)}`, last_pull_at: s.last_pull_at }} />}
                expanded={<ContainerCardExpanded c={{ ...s }} isSwarm={true} onAction={load} confirm={confirm} showToast={showToast} onTab={onTab} />}
              />
            ))}
          </Section>
        )}

        {/* VMs + LXC · Proxmox */}
        {show('vms') && (() => {
          const allItems = [...(vms?.vms || []), ...(vms?.lxc || [])]
          const filtered = applyProxmoxFilters(allItems, proxmoxFilters)
          const sorted   = sortProxmoxItems(filtered, sortBy, sortDir)
          const nodeSet = [...new Set(allItems.map(v => v.node))].join(' · ') || 'no data'
          const vmCount = (vms?.vms || []).length
          const lxcCount = (vms?.lxc || []).length
          const metaStr = `${nodeSet} · ${vmCount} VM${vmCount !== 1 ? 's' : ''} · ${lxcCount} LXC`
          return (
            <Section
              label={`Proxmox Cluster (${sorted.length})`}
              meta={metaStr}
              errorCount={errorCount(allItems)}
              filterBar={
                <ProxmoxFilterBar
                  items={allItems}
                  filters={proxmoxFilters}
                  setFilters={setProxmoxFilters}
                  sort={{ sortBy, sortDir }}
                  onSort={(by, dir) => { setSortBy(by); setSortDir(dir) }}
                />
              }
            >
              {sorted.length === 0 && allItems.length > 0 && (
                <div className="col-span-full text-[10px] text-gray-700 py-2">no items match filter</div>
              )}
              {sorted.map(vm => (
                <InfraCard
                  key={`${vm.type}-${vm.vmid}`}
                  cardKey={`v-${vm.type}-${vm.vmid}`}
                  openKey={openKey} setOpenKey={setOpenKey}
                  dot={vm.dot}
                  name={vm.name}
                  sub={`${vm.type === 'lxc' ? 'CT' : 'VM'} ${vm.vmid} · ${vm.node}${vm.pool ? ` · ${vm.pool}` : ''}`}
                  net={vm.ip || ''}
                  collapsed={<ProxmoxCardCollapsed vm={vm} />}
                  expanded={<ProxmoxCardExpanded vm={vm} onAction={load} confirm={confirm} showToast={showToast} />}
                />
              ))}
            </Section>
          )
        })()}

        {/* External Services */}
        {show('external') && (
          <Section
            label="External Services"
            meta={`${external?.services?.filter(s => s.reachable).length ?? '…'} / ${external?.services?.length ?? '…'} reachable`}
            errorCount={errorCount(external?.services)}
          >
            {(external?.services || []).map(svc => (
              <InfraCard
                key={svc.slug} cardKey={`e-${svc.slug}`} openKey={openKey} setOpenKey={setOpenKey}
                dot={svc.dot} name={svc.name} sub={svc.service_type} net={svc.host_port}
                collapsed={<ExternalCardCollapsed svc={svc} />}
                expanded={<ExternalCardExpanded svc={svc} onAction={load} />}
              />
            ))}
          </Section>
        )}
      </>}

      <Toast toasts={toasts} />
    </div>
  )
}
