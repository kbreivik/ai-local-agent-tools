# Proxmox Sort + Dashboard Improvements — Design Spec

**Date:** 2026-03-27
**Status:** Approved (v2 — post spec-review fixes)

---

## Overview

Three improvements to the Dashboard tab:

1. Sort control for the Proxmox VMs·LXC section
2. Item count in the Proxmox section header
3. SwarmServicesCard — verify existing alphabetical sort (already implemented with stack-prefix stripping; no code change needed)

Note: `nodeCardSize` is actively used by `NodeMap.jsx` and is NOT dead — removed from scope.

---

## 1. Proxmox Sort Control

### State

Two new state variables in the Proxmox section of `ServiceCards.jsx`, alongside the existing `proxmoxFilters` state. Both are initialised from `localStorage` via lazy initialiser:

```js
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
```

Write-back on change (mirroring the `hp1_cardFilter` pattern in `App.jsx`):

```js
useEffect(() => {
  localStorage.setItem('hp1_proxmox_sort', JSON.stringify({ sortBy, sortDir }))
}, [sortBy, sortDir])
```

### Sort function

Defined at module level in `ServiceCards.jsx`, applied after `applyProxmoxFilters()`:

```js
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
        if (a.cpu_pct == null) return 1   // nulls always last
        if (b.cpu_pct == null) return -1
        return (a.cpu_pct - b.cpu_pct) * dir
      }
      case 'ram': {
        const aPct = a.maxmem_gb ? (a.mem_used_gb ?? 0) / a.maxmem_gb : null
        const bPct = b.maxmem_gb ? (b.mem_used_gb ?? 0) / b.maxmem_gb : null
        if (aPct == null && bPct == null) return 0
        if (aPct == null) return 1   // nulls always last
        if (bPct == null) return -1
        return (aPct - bPct) * dir
      }
      default:
        return 0
    }
  })
}
```

Usage at render time:

```js
const filtered = applyProxmoxFilters(allItems, proxmoxFilters)
const sorted   = sortProxmoxItems(filtered, sortBy, sortDir)
// render sorted, pass sorted.length to section header
```

### UI — sort chip in ProxmoxFilterBar

`ProxmoxFilterBar` receives two new props:

```js
// sort: { sortBy: string, sortDir: 'asc'|'desc' }
// onSort: (sortBy: string, sortDir: 'asc'|'desc') => void
```

A sort chip is added at the right end of the filter row:

```
[node] [pool] [vm] [lxc] [running] [stopped] [name___]    [Sort: vmid ↑]
```

**Dropdown open/close state** is a local `useState` inside `ProxmoxFilterBar` (not in the parent):

```js
const [dropOpen, setDropOpen] = useState(false)
```

The dropdown closes when a field is selected. Outside-click and Escape handling are deferred — the current filter bar has no such behaviour either.

**Chip behaviour:**
- Clicking the **field label** part toggles `dropOpen`.
- Clicking the **arrow** (↑/↓) toggles `sortDir` without opening the dropdown.
- Selecting a field in the dropdown sets `sortBy` and closes the dropdown. If the same field is selected, `sortDir` toggles instead.

**Dropdown content** (five options):

| Key | Label |
|-----|-------|
| `vmid` | vmid |
| `name` | Name |
| `status` | Status |
| `cpu` | CPU % |
| `ram` | RAM % |

**Visual style:** same chip pattern as filter chips (`text-[9px] px-1.5 py-px rounded border`). Sort chip always uses the violet active style (`bg-violet-600/30 text-violet-300 border-violet-500/40`) to distinguish it from filter chips. Dropdown panel: `absolute` positioned below chip, `z-10`, `bg-[#0a0a15] border border-[#2a2440] rounded-md p-1`.

---

## 2. Item Count in Section Header

After filtering and sorting, pass the count into the section label. The current label string is `"Proxmox Cluster"`:

```jsx
<Section label={`Proxmox Cluster (${sorted.length})`} ...>
```

This reflects the post-filter count — if filters hide 4 of 12, the header shows `Proxmox Cluster (8)`.

---

## 3. SwarmServicesCard Sort — Verify Only

`DashboardCards.jsx` already sorts services alphabetically with stack-prefix stripping (e.g. `hp1-stack_kafka` → sorts as `kafka`). **No code change needed.** Implementer should verify this sort is present and functioning.

---

## Files Changed

| File | Change |
|---|---|
| `gui/src/components/ServiceCards.jsx` | Add `sortBy`/`sortDir` state with localStorage init/write-back, `sortProxmoxItems()` function, updated `ProxmoxFilterBar` call with sort props, item count in section label |
| `gui/src/components/ServiceCards.jsx` (ProxmoxFilterBar) | Add `sort` + `onSort` props, sort chip with inline dropdown, local `dropOpen` state |

---

## Out of Scope

- `nodeCardSize` removal — setting is actively used by `NodeMap.jsx` (`NodeCard size` prop)
- Container·agent-01 sort
- VM/LXC type visual separator
- External Services sort
