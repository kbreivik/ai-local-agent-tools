# CC PROMPT — v2.25.1 — Proxmox card: optimistic maintenance toggle + chat button

## What this does
Adds optimistic local state to the Set/Clear Maintenance button so it toggles instantly on click
without waiting for the next poll (30s). Also adds a `⌘` chat button to Proxmox VM/LXC collapsed
cards that pre-fills the agent Command panel with an investigate prompt and switches to Commands tab.
Version bump: v2.25.0 → v2.25.1

---

## Change 1 — gui/src/components/ServiceCards.jsx

### 1a — ProxmoxCardExpanded: add optimistic localMaint state

FIND (exact):
```
function ProxmoxCardExpanded({ vm, proxmoxHost, proxmoxPort, onAction, confirm, showToast }) {
  const [loading, setLoading] = useState({})
  const mounted = useRef(true)
  useEffect(() => () => { mounted.current = false }, [])
```

REPLACE WITH:
```
function ProxmoxCardExpanded({ vm, proxmoxHost, proxmoxPort, onAction, confirm, showToast }) {
  const [loading, setLoading] = useState({})
  const [localMaint, setLocalMaint] = useState(!!vm.maintenance)
  const mounted = useRef(true)
  useEffect(() => () => { mounted.current = false }, [])
  // Sync optimistic state when vm prop refreshes from poll
  useEffect(() => { setLocalMaint(!!vm.maintenance) }, [vm.maintenance])
```

### 1b — ProxmoxCardExpanded: wire localMaint into the maintenance button

FIND (exact — the entire maintenance toggle block inside ProxmoxCardExpanded):
```
      {/* Maintenance toggle */}
      {vm.entity_id && (
        <div style={{ marginTop: 6, borderTop: '1px solid var(--bg-3)', paddingTop: 6 }}>
          <button
            onClick={async (e) => {
              e.stopPropagation()
              const BASE = import.meta.env.VITE_API_BASE ?? ''
              const headers = { 'Content-Type': 'application/json', ...authHeaders() }
              if (vm.maintenance) {
                await fetch(`${BASE}/api/maintenance/${encodeURIComponent(vm.entity_id)}`, { method: 'DELETE', headers })
              } else {
                await fetch(`${BASE}/api/maintenance/${encodeURIComponent(vm.entity_id)}`, {
                  method: 'POST', headers,
                  body: JSON.stringify({ reason: 'Set from dashboard' })
                })
              }
              // Trigger a data refresh
              window.dispatchEvent(new CustomEvent('ds:refresh-dashboard'))
            }}
            style={{
              padding: '2px 10px', fontSize: 9, fontFamily: 'var(--font-mono)',
              background: vm.maintenance ? 'var(--amber-dim)' : 'transparent',
              color: vm.maintenance ? 'var(--amber)' : 'var(--text-3)',
              border: `1px solid ${vm.maintenance ? 'var(--amber)' : 'var(--border)'}`,
              borderRadius: 2, cursor: 'pointer',
            }}
          >
            {vm.maintenance ? '\u2691 Clear Maintenance' : '\u2691 Set Maintenance'}
          </button>
        </div>
      )}
```

REPLACE WITH:
```
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
```

### 1c — ProxmoxCardCollapsed: add onChat prop + ⌘ chat button

FIND (exact):
```
function ProxmoxCardCollapsed({ vm, onEntityDetail }) {
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
        {onEntityDetail && (
          <button
            className="text-[10px] px-1 py-px ml-auto"
            style={{ color: 'var(--cyan)', background: 'none', border: 'none', cursor: 'pointer' }}
            onClick={e => { e.stopPropagation(); onEntityDetail(`proxmox_vms:${vm.node_api}:${vm.type === 'lxc' ? 'lxc' : 'qemu'}:${vm.vmid}`) }}
            title="Entity detail"
          >›</button>
        )}
      </div>
    </>
  )
}
```

REPLACE WITH:
```
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
```

### 1d — ServiceCards: accept and thread onChat prop

FIND (exact):
```
export default function ServiceCards({ activeFilters = null, onTab, onEntityDetail, compareMode, compareSet, onCompareAdd, showFilter, search = '' }) {
```

REPLACE WITH:
```
export default function ServiceCards({ activeFilters = null, onTab, onEntityDetail, onChat, compareMode, compareSet, onCompareAdd, showFilter, search = '' }) {
```

FIND (exact — the ProxmoxCardCollapsed usage in the VM InfraCard render):
```
                    collapsed={<ProxmoxCardCollapsed vm={vm} onEntityDetail={onEntityDetail} />}
```

REPLACE WITH:
```
                    collapsed={<ProxmoxCardCollapsed vm={vm} onEntityDetail={onEntityDetail} onChat={onChat} />}
```

---

## Change 2 — gui/src/components/CommandPanel.jsx

### 2a — Listen for ds:prefill-agent event to set the task input

FIND (exact):
```
  const { task, setTask }         = useTask()
  const { pendingChoices, clearChoices, runState, setRunState, stopAgent, isRunning, outputLines } = useAgentOutput()
```

REPLACE WITH:
```
  const { task, setTask }         = useTask()
  const { pendingChoices, clearChoices, runState, setRunState, stopAgent, isRunning, outputLines } = useAgentOutput()

  // Pre-fill task input when a card's chat button fires ds:prefill-agent
  useEffect(() => {
    const handler = (e) => { if (e.detail?.text) setTask(e.detail.text) }
    window.addEventListener('ds:prefill-agent', handler)
    return () => window.removeEventListener('ds:prefill-agent', handler)
  }, [setTask])
```

---

## Change 3 — gui/src/App.jsx

### 3a — DashboardView: add onChat callback

FIND (exact):
```
  const onExpandAllCards = () => {
    setAllCardsExpanded(true)
    window.dispatchEvent(new CustomEvent('ds:expand-all-cards'))
  }
```

REPLACE WITH:
```
  // VM card ⌘ button: pre-fill agent task and switch to Commands tab
  const onChat = useCallback((label) => {
    window.dispatchEvent(new CustomEvent('ds:prefill-agent', { detail: { text: `Investigate ${label}` } }))
    onTab('Commands')
  }, [onTab])

  const onExpandAllCards = () => {
    setAllCardsExpanded(true)
    window.dispatchEvent(new CustomEvent('ds:expand-all-cards'))
  }
```

### 3b — Pass onChat to the COMPUTE ServiceCards instance

FIND (exact):
```
    COMPUTE: showSection('COMPUTE') ? (
      summaryLoading ? <SkeletonGrid count={4} /> :
      <ServiceCardsErrorBoundary>
        <ServiceCards activeFilters={['vms']} onTab={onTab} onEntityDetail={onEntityClick} compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd} showFilter={showFilter} search={search} />
      </ServiceCardsErrorBoundary>
    ) : null,
```

REPLACE WITH:
```
    COMPUTE: showSection('COMPUTE') ? (
      summaryLoading ? <SkeletonGrid count={4} /> :
      <ServiceCardsErrorBoundary>
        <ServiceCards activeFilters={['vms']} onTab={onTab} onEntityDetail={onEntityClick} onChat={onChat} compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd} showFilter={showFilter} search={search} />
      </ServiceCardsErrorBoundary>
    ) : null,
```

---

## Version bump
Update VERSION: 2.25.0 → 2.25.1

---

## Commit
```bash
git add -A
git commit -m "feat(ui): v2.25.1 optimistic maintenance toggle + VM card chat button"
git push origin main
```
