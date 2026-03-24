# Alert Strip Tray + Unified Card Grid — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Alert strip fills all horizontal space in SubBar, (2) clicking it opens a grouped dropdown tray that navigates to the affected infra section, (3) the Options card width/height settings apply to ServiceCards infra tiles as well as DashboardCards status cards.

**Architecture:** `activeFilters` state lifts from `DashboardView` to `AppShell` so SubBar can set it via `onAlertNavigate`. SubBar stores raw per-source API results alongside the existing flat `alerts[]` so the tray can render grouped sections. `Section` in `ServiceCards.jsx` switches from a fixed `cols` prop to `repeat(auto-fill, minmax(...))` using `useOptions()` — identical to the formula already used in `DashboardCards.jsx`. `InfraCard` applies `cardMinHeight` only when collapsed.

**Tech Stack:** React 19, Vite, Tailwind CSS v4. No test framework — verification gate is `npm run build` (Vite + ESLint).

**Spec:** `docs/superpowers/specs/2026-03-24-alert-strip-tray-grid-design.md`

---

## File Map

| File | Changes |
|---|---|
| `gui/src/App.jsx` | Task 1: lift `activeFilters` to `AppShell`; Task 2: add `onAlertNavigate` + wire to `SubBar` |
| `gui/src/App.jsx` (SubBar) | Task 2: per-source state, `alertTrayOpen`, tray render, flex-fill strip |
| `gui/src/components/ServiceCards.jsx` (Section) | Task 3: auto-fill grid via `useOptions()`, remove `cols` prop |
| `gui/src/components/ServiceCards.jsx` (InfraCard) | Task 4: `cardMinHeight` when collapsed |

---

## Task 1 — Lift activeFilters from DashboardView to AppShell

**Files:**
- Modify: `gui/src/App.jsx` — `AppShell` function (line ~494) and `DashboardView` function (line ~415)

### Context

Currently `activeFilters`, `toggleFilter`, and `toggleAll` are owned by `DashboardView` (lines 416–445). `AppShell` passes `onTab={setActiveTab}` to `SubBar`. After this task, `AppShell` owns the filter state and `DashboardView` receives it as props. `SubBar` gains an `onAlertNavigate` prop (used in Task 2).

### Steps

- [ ] **Step 1: Add `useCallback` to the React import in App.jsx**

Current line 1:
```js
import React, { useState, useEffect, useRef, lazy, Suspense } from 'react'
```
Change to:
```js
import React, { useState, useEffect, useRef, lazy, Suspense, useCallback } from 'react'
```

- [ ] **Step 2: Update DashboardView to accept props instead of owning state**

Replace the entire `DashboardView` function (lines 415–461) with:

```jsx
function DashboardView({ activeFilters, onToggleFilter, onToggleAll }) {
  return (
    <div className="flex flex-col flex-1 overflow-hidden min-h-0">
      <CardFilterBar activeFilters={activeFilters} onToggle={onToggleFilter} onToggleAll={onToggleAll} />
      {/* Single unified scroll area — one scrollbar for both sections */}
      <div className="flex-1 overflow-auto min-h-0">
        <DashboardCards activeFilters={activeFilters} />
        <div className="border-t border-gray-200 px-5 py-4">
          <ServiceCardsErrorBoundary>
            <ServiceCards activeFilters={activeFilters} />
          </ServiceCardsErrorBoundary>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Move filter state + handlers into AppShell, add onAlertNavigate**

Replace the `AppShell` function opening (the `function AppShell()` block, lines ~494–519) with the version below. Keep everything inside the function body after the `const gridCols` line unchanged.

```jsx
function AppShell() {
  const [activeTab, setActiveTab] = useState('Dashboard')
  const { panelOpen } = useCommandPanel()

  // Filter state (lifted here so SubBar can set it via onAlertNavigate)
  const [activeFilters, setActiveFilters] = useState(() => {
    try {
      const saved = localStorage.getItem(FILTER_KEY)
      if (!saved) return ALL_CARD_KEYS.map(c => c.key)
      const loaded = JSON.parse(saved)
      const newKeys = ALL_CARD_KEYS.map(c => c.key).filter(k => !loaded.includes(k))
      return [...loaded, ...newKeys]
    } catch {
      return ALL_CARD_KEYS.map(c => c.key)
    }
  })

  const toggleFilter = (key) => {
    setActiveFilters(prev => {
      const next = prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]
      localStorage.setItem(FILTER_KEY, JSON.stringify(next))
      return next
    })
  }

  const toggleAll = () => {
    setActiveFilters(prev => {
      const allKeys = ALL_CARD_KEYS.map(c => c.key)
      const allActive = allKeys.every(k => prev.includes(k))
      const next = allActive ? [] : allKeys
      localStorage.setItem(FILTER_KEY, JSON.stringify(next))
      return next
    })
  }

  // Called by SubBar tray — navigates to Dashboard and isolates one section.
  // localStorage is NOT updated (transient navigation; user restores with filter bar).
  const onAlertNavigate = useCallback((sectionKey) => {
    setActiveTab('Dashboard')
    setActiveFilters([sectionKey])
  }, [])

  // "Full log →" link in AgentFeed navigates to Output tab
  useEffect(() => {
    const handler = () => setActiveTab('Output')
    window.addEventListener('navigate-to-output', handler)
    return () => window.removeEventListener('navigate-to-output', handler)
  }, [])

  const gridCols = (panelOpen && activeTab !== 'Commands')
    ? '360px 1fr'
    : '0px 1fr'
```

- [ ] **Step 4: Pass new props to SubBar and DashboardView in AppShell's return**

In the `return (...)` of `AppShell`, change:

```jsx
<SubBar onTab={setActiveTab} />
```
to:
```jsx
<SubBar onTab={setActiveTab} onAlertNavigate={onAlertNavigate} />
```

And change:
```jsx
{activeTab === 'Dashboard' && (
  <DashboardView />
)}
```
to:
```jsx
{activeTab === 'Dashboard' && (
  <DashboardView
    activeFilters={activeFilters}
    onToggleFilter={toggleFilter}
    onToggleAll={toggleAll}
  />
)}
```

- [ ] **Step 5: Verify build passes**

```bash
cd D:/claude_code/FAJK/HP1-AI-Agent-v1/gui && npm run build
```

Expected: build succeeds with 0 errors. ESLint may warn about unused vars if the old `DashboardView` internals weren't fully removed — fix any errors before proceeding.

- [ ] **Step 6: Commit**

```bash
cd D:/claude_code/FAJK/HP1-AI-Agent-v1
git add gui/src/App.jsx
git commit -m "refactor(dashboard): lift activeFilters to AppShell, add onAlertNavigate"
git push
```

---

## Task 2 — Alert strip: flex-fill width + dropdown tray

**Files:**
- Modify: `gui/src/App.jsx` — `SubBar` function (lines ~222–381)

### Context

`SubBar` currently:
- Holds `alerts[]` (flat, sorted array of `{ sev, text, idx }`) derived from `Promise.allSettled` of 4 fetch calls
- Renders a `<button>` with `style={{ maxWidth: 420 }}` when `alerts.length > 0`
- Does NOT store the raw per-source API results

This task:
1. Adds four raw-source state vars (`rawContainers`, `rawSwarm`, `rawVms`, `rawExternal`) populated by the same `refreshAlerts` function
2. Changes the strip to flex-fill (`flex: 1; minWidth: 0`)
3. Wraps the strip in a `position: relative` container
4. Adds `alertTrayOpen` state + trayRef
5. Renders the grouped tray as `position: absolute` below the strip
6. Closes tray on outside click (mousedown) and Escape key — same pattern as the Tools dropdown in `Header`
7. Each tray section row calls `onAlertNavigate(sectionKey)` and closes the tray

### Tray section → filter key mapping

| Tray section | `sectionKey` | Raw data source |
|---|---|---|
| Containers · agent-01 | `containers_local` | `rawContainers.containers[]` |
| Swarm services | `containers_swarm` | `rawSwarm.services[]` |
| Proxmox VMs / LXC | `vms` | `rawVms.vms[]` + `rawVms.lxc[]` |
| External services | `external` | `rawExternal.services[]` |

### Steps

- [ ] **Step 1: Update SubBar signature to accept onAlertNavigate, then add raw-source state vars**

Change the function signature:
```js
function SubBar({ onTab }) {
```
to:
```js
function SubBar({ onTab, onAlertNavigate }) {
```

Then, after the existing state declarations (`const [alerts, setAlerts] = useState([])`), add:

```jsx
const [rawContainers, setRawContainers] = useState(null)
const [rawSwarm,      setRawSwarm]      = useState(null)
const [rawVms,        setRawVms]        = useState(null)
const [rawExternal,   setRawExternal]   = useState(null)
const [alertTrayOpen, setAlertTrayOpen] = useState(false)
const trayRef = useRef(null)
```

- [ ] **Step 2: Populate raw-source state in refreshAlerts**

Replace the `refreshAlerts` function body (the `.then(([c, s, v, e]) => { ... })` block) with:

```js
const refreshAlerts = () => {
  Promise.allSettled([
    fetchDashboardContainers(),
    fetchDashboardSwarm(),
    fetchDashboardVMs(),
    fetchDashboardExternal(),
  ]).then(([c, s, v, e]) => {
    // Store raw per-source data for tray grouping
    if (c.status === 'fulfilled') setRawContainers(c.value)
    if (s.status === 'fulfilled') setRawSwarm(s.value)
    if (v.status === 'fulfilled') setRawVms(v.value)
    if (e.status === 'fulfilled') setRawExternal(e.value)

    // Flat sorted list for the strip badge count
    const issues = []
    let idx = 0
    const SEV = { red: 0, amber: 1, grey: 2, green: 3 }
    if (c.status === 'fulfilled') for (const x of c.value?.containers || []) if (x.problem) issues.push({ sev: x.dot, text: `${x.name} ${x.problem}`, idx: idx++ })
    if (s.status === 'fulfilled') for (const x of s.value?.services   || []) if (x.problem) issues.push({ sev: x.dot, text: `${x.name} ${x.problem}`, idx: idx++ })
    if (v.status === 'fulfilled') for (const x of [...(v.value?.vms || []), ...(v.value?.lxc || [])]) if (x.problem) issues.push({ sev: x.dot, text: `${x.name} ${x.problem}`, idx: idx++ })
    if (e.status === 'fulfilled') for (const x of e.value?.services   || []) if (x.problem) issues.push({ sev: x.dot, text: `${x.name} ${x.problem}`, idx: idx++ })
    issues.sort((a, b) => (SEV[a.sev] ?? 2) - (SEV[b.sev] ?? 2) || a.idx - b.idx)
    setAlerts(issues)
  }).catch(() => {})
}
```

- [ ] **Step 3: Add outside-click and Escape useEffects for tray**

Add these two `useEffect` calls inside `SubBar`, after the existing `useEffect` (the one that calls `loadAll` and sets the interval):

```js
// Close alert tray on outside click (same pattern as Tools dropdown)
useEffect(() => {
  const handler = (e) => {
    if (trayRef.current && !trayRef.current.contains(e.target)) {
      setAlertTrayOpen(false)
    }
  }
  document.addEventListener('mousedown', handler)
  return () => document.removeEventListener('mousedown', handler)
}, [])

// Close alert tray on Escape
useEffect(() => {
  const handler = (e) => {
    if (e.key === 'Escape') setAlertTrayOpen(false)
  }
  document.addEventListener('keydown', handler)
  return () => document.removeEventListener('keydown', handler)
}, [])
```

- [ ] **Step 4: Replace the alert strip button with flex-fill + tray**

Replace the current alert strip block:

```jsx
{/* Alert strip — shows stopped/unhealthy infra items, click to open Dashboard */}
{alerts.length > 0 && (
  <button
    onClick={() => onTab?.('Dashboard')}
    title={`${alerts.length} infrastructure alert${alerts.length !== 1 ? 's' : ''} — click to view`}
    className="flex items-center gap-1.5 px-2 h-full border-l border-orange-100 bg-orange-50/60 hover:bg-orange-50 transition-colors shrink min-w-0 overflow-hidden"
    style={{ maxWidth: 420 }}
  >
    <span className="text-orange-500 text-[12px] shrink-0">⚠</span>
    <span className="text-[11px] text-orange-700/80 truncate">
      {alerts.slice(0, 3).map(i => i.text).join(' · ')}
      {alerts.length > 3 ? ` · +${alerts.length - 3} more` : ''}
    </span>
    <span className="text-[10px] bg-orange-400 text-white rounded-full px-1.5 py-px shrink-0 ml-0.5">{alerts.length}</span>
  </button>
)}
```

With this new block:

```jsx
{/* Alert strip — flex-fills remaining space; click opens grouped tray */}
{alerts.length > 0 && (
  <div ref={trayRef} className="relative border-l border-orange-100" style={{ flex: 1, minWidth: 0 }}>
    <button
      onClick={() => setAlertTrayOpen(o => !o)}
      title={`${alerts.length} infrastructure alert${alerts.length !== 1 ? 's' : ''} — click for details`}
      className="flex items-center gap-1.5 px-2 h-8 w-full bg-orange-50/60 hover:bg-orange-50 transition-colors overflow-hidden"
    >
      <span className="text-orange-500 text-[12px] shrink-0">⚠</span>
      <span className="text-[11px] text-orange-700/80 truncate">
        {alerts.slice(0, 3).map(i => i.text).join(' · ')}
        {alerts.length > 3 ? ` · +${alerts.length - 3} more` : ''}
      </span>
      <span className="text-[10px] bg-orange-400 text-white rounded-full px-1.5 py-px shrink-0 ml-0.5">{alerts.length}</span>
    </button>

    {alertTrayOpen && (
      <div className="absolute top-full left-0 z-50 min-w-full bg-[#1e293b] border border-[#334155] rounded-b shadow-xl"
           style={{ maxHeight: 400, overflowY: 'auto' }}>
        {/* Tray header */}
        <div className="px-3 py-2 border-b border-[#334155] flex items-center gap-2">
          <span className="text-orange-400 text-[11px]">⚠</span>
          <span className="text-[11px] font-semibold text-slate-200">{alerts.length} Infrastructure Issue{alerts.length !== 1 ? 's' : ''}</span>
        </div>

        {/* Per-section rows */}
        {[
          {
            key: 'containers_local',
            label: 'CONTAINERS · agent-01',
            items: (rawContainers?.containers || []).filter(x => x.problem).map(x => ({ name: x.name, problem: x.problem })),
          },
          {
            key: 'containers_swarm',
            label: 'SWARM SERVICES',
            items: (rawSwarm?.services || []).filter(x => x.problem).map(x => ({ name: x.name, problem: x.problem })),
          },
          {
            key: 'vms',
            label: 'PROXMOX VMs / LXC',
            items: [...(rawVms?.vms || []), ...(rawVms?.lxc || [])].filter(x => x.problem).map(x => ({ name: x.name, problem: x.problem })),
          },
          {
            key: 'external',
            label: 'EXTERNAL SERVICES',
            items: (rawExternal?.services || []).filter(x => x.problem).map(x => ({ name: x.name, problem: x.problem })),
          },
        ].map(({ key, label, items }) => {
          const shown = items.slice(0, 5)
          const extra = items.length - shown.length
          const hasIssues = items.length > 0
          return (
            <div
              key={key}
              className={`border-b border-[#1e293b] ${hasIssues ? 'cursor-pointer hover:bg-[#243447]' : 'opacity-50 cursor-pointer hover:opacity-70'} transition-colors`}
              onClick={() => { onAlertNavigate(key); setAlertTrayOpen(false) }}
            >
              <div className="flex items-center justify-between px-3 py-1.5">
                <div>
                  <span className="text-[9px] text-slate-400 uppercase tracking-wider font-semibold">{label}</span>
                  {hasIssues
                    ? <span className="ml-2 text-[10px] text-orange-400">{items.length} issue{items.length !== 1 ? 's' : ''}</span>
                    : <span className="ml-2 text-[10px] text-slate-600">0 issues</span>
                  }
                </div>
                <span className="text-[10px] text-slate-500 shrink-0 ml-2">→</span>
              </div>
              {shown.length > 0 && (
                <div className="px-3 pb-1.5 flex flex-col gap-0.5">
                  {shown.map((item, i) => (
                    <div key={i} className="flex justify-between text-[10px]">
                      <span className="text-amber-300 truncate">{item.name}</span>
                      <span className="text-slate-500 ml-2 shrink-0">{item.problem}</span>
                    </div>
                  ))}
                  {extra > 0 && (
                    <div className="text-[9px] text-slate-600 mt-0.5">+ {extra} more</div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    )}
  </div>
)}
```

- [ ] **Step 5: Verify build passes**

```bash
cd D:/claude_code/FAJK/HP1-AI-Agent-v1/gui && npm run build
```

Expected: 0 errors. Fix any real errors.

- [ ] **Step 6: Commit**

```bash
cd D:/claude_code/FAJK/HP1-AI-Agent-v1
git add gui/src/App.jsx
git commit -m "feat(subbar): alert strip fills width, dropdown tray with grouped issues and navigation"
git push
```

> **Note:** `rawContainers/rawSwarm/rawVms/rawExternal` start as `null` (initial load). The `|| []` fallbacks in the tray section render handle null correctly — all four section rows always render, showing "0 issues" when null or empty. This is intentional; no null-guard needed.

---

## Task 3 — Section auto-fill grid (Options controls ServiceCards width)

**Files:**
- Modify: `gui/src/components/ServiceCards.jsx` — `Section` component (line ~165) and its three callsites with explicit `cols={4}` (lines 762, 788, 817)

### Context

`Section` currently uses a fixed `cols` prop:
```js
function Section({ label, meta, errorCount, cols = 5, filterBar, children }) {
  ...
  <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
```

`DashboardCards.jsx` uses the following formula (lines 632–637):
```js
const _min = cardMinWidth ?? 280
const _max = cardMaxWidth ? `${cardMaxWidth}px` : '1fr'
gridTemplateColumns: `repeat(auto-fill, minmax(${_min}px, ${_max}))`,
...(cardMaxWidth ? { justifyContent: 'start' } : {}),
```

`ServiceCards.jsx` doesn't import or use `useOptions()` at all.

The Proxmox empty-state message has a `col-span-4` class (line ~793) that must be updated since `cols` is no longer fixed.

### Steps

- [ ] **Step 1: Add useOptions import to ServiceCards.jsx**

At the top of `gui/src/components/ServiceCards.jsx`, after the existing imports, add:

```js
import { useOptions } from '../context/OptionsContext'
```

- [ ] **Step 2: Update Section component to use auto-fill grid**

Replace the `Section` function (lines ~165–179) with:

```jsx
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
```

- [ ] **Step 3: Remove cols prop from Section callsites**

The `containers_local` section (line ~737) passes no `cols` prop — it uses the default 5. The other three sections pass `cols={4}` explicitly. Remove `cols` from all three explicit callsites below, and also remove the `cols = 5` default from the `Section` function signature (already done in Step 2 above).

In the Swarm section (line ~758–763), change:
```jsx
<Section
  label="Containers · Swarm"
  meta={...}
  errorCount={errorCount(swarm?.services)}
  cols={4}
>
```
to:
```jsx
<Section
  label="Containers · Swarm"
  meta={...}
  errorCount={errorCount(swarm?.services)}
>
```

In the Proxmox section (line ~784–790), change:
```jsx
<Section
  label="Proxmox Cluster"
  meta={metaStr}
  errorCount={errorCount(allItems)}
  cols={4}
  filterBar={...}
>
```
to:
```jsx
<Section
  label="Proxmox Cluster"
  meta={metaStr}
  errorCount={errorCount(allItems)}
  filterBar={...}
>
```

In the External section (line ~813–818), change:
```jsx
<Section
  label="External Services"
  meta={...}
  errorCount={errorCount(external?.services)}
  cols={4}
>
```
to:
```jsx
<Section
  label="External Services"
  meta={...}
  errorCount={errorCount(external?.services)}
>
```

- [ ] **Step 4: Fix the Proxmox empty-state col-span**

In the Proxmox section, find the empty-state message (line ~793):
```jsx
<div className="col-span-4 text-[10px] text-gray-700 py-2">no items match filter</div>
```
Change `col-span-4` to `col-span-full`:
```jsx
<div className="col-span-full text-[10px] text-gray-700 py-2">no items match filter</div>
```

- [ ] **Step 5: Verify build passes**

```bash
cd D:/claude_code/FAJK/HP1-AI-Agent-v1/gui && npm run build
```

Expected: 0 errors. ESLint will warn if `cols` prop still appears somewhere — remove any remaining instances.

- [ ] **Step 6: Commit**

```bash
cd D:/claude_code/FAJK/HP1-AI-Agent-v1
git add gui/src/components/ServiceCards.jsx
git commit -m "feat(servicecards): Section uses auto-fill grid from Options, remove fixed cols prop"
git push
```

---

## Task 4 — InfraCard respects cardMinHeight when collapsed

**Files:**
- Modify: `gui/src/components/ServiceCards.jsx` — `InfraCard` function (lines ~135–161)

### Context

`InfraCard` currently has no height styling. The outer `<div>` renders with only Tailwind classes. We want collapsed cards to respect `cardMinHeight` from Options (default 70px), but leave expanded cards unconstrained (expanded panels contain variable-length content that would be clipped).

`isOpen` is already available inside the function (`const isOpen = openKey === cardKey`).

### Steps

- [ ] **Step 1: Add useOptions call to InfraCard**

Inside `InfraCard`, after `const isOpen = openKey === cardKey` and `const cs = cardState(dot)`, add:

```js
const { cardMinHeight } = useOptions()
```

- [ ] **Step 2: Apply minHeight to the outer div when collapsed**

In the `InfraCard` return, the outer `<div>` currently is:
```jsx
<div
  className={`${cs.bg} border ${isOpen ? 'border-violet-500 shadow-[0_0_0_1px_rgba(124,106,247,0.15)]' : cs.border} rounded-lg px-2.5 py-2.5 cursor-pointer transition-colors`}
  onClick={() => setOpenKey(isOpen ? null : cardKey)}
>
```

Add the conditional `style` prop:
```jsx
<div
  className={`${cs.bg} border ${isOpen ? 'border-violet-500 shadow-[0_0_0_1px_rgba(124,106,247,0.15)]' : cs.border} rounded-lg px-2.5 py-2.5 cursor-pointer transition-colors`}
  style={isOpen ? undefined : { minHeight: cardMinHeight }}
  onClick={() => setOpenKey(isOpen ? null : cardKey)}
>
```

- [ ] **Step 3: Verify build passes**

```bash
cd D:/claude_code/FAJK/HP1-AI-Agent-v1/gui && npm run build
```

Expected: 0 errors.

- [ ] **Step 4: Commit**

```bash
cd D:/claude_code/FAJK/HP1-AI-Agent-v1
git add gui/src/components/ServiceCards.jsx
git commit -m "feat(servicecards): InfraCard respects cardMinHeight when collapsed"
git push
```

---

## Final: Deploy

After all four tasks are committed and pushed, CI builds the Docker image automatically. Deploy with:

```bash
ssh ansible@192.168.222.10 "cd /home/ansible && ansible-playbook -i hp1-infra/inventory/hosts.yml hp1-infra/playbooks/hp1_upgrade.yml --vault-password-file hp1-infra/vault/.vault_pass"
```

Verify in browser:
- Alert strip fills horizontal space between stats and API :8000
- Clicking the strip opens the grouped tray; clicking a section row navigates to Dashboard filtered to that section
- Options Min Width slider controls both DashboardCards and ServiceCards grid columns
- Options Min Height slider affects collapsed InfraCard height
