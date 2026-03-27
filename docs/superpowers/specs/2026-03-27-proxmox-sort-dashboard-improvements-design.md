# Proxmox Sort + Dashboard Improvements — Design Spec

**Date:** 2026-03-27
**Status:** Approved

---

## Overview

Four small improvements to the Dashboard tab:

1. Sort control for the Proxmox VMs·LXC section
2. Item count in the Proxmox section header
3. SwarmServicesCard alphabetical sort (no UI)
4. Remove dead `nodeCardSize` setting

---

## 1. Proxmox Sort Control

### State

Two new state variables alongside `proxmoxFilters` in the Proxmox section of `ServiceCards.jsx`:

```js
const [sortBy,  setSortBy]  = useState('vmid')   // 'vmid'|'name'|'status'|'cpu'|'ram'
const [sortDir, setSortDir] = useState('asc')     // 'asc'|'desc'
```

Persisted to `localStorage` under key `hp1_proxmox_sort` as `{ sortBy, sortDir }`. Loaded on mount, same pattern as `hp1_cardFilter`.

### Sort function

Applied after `applyProxmoxFilters()`, before render:

```js
function sortProxmoxItems(items, sortBy, sortDir) {
  const dir = sortDir === 'asc' ? 1 : -1
  return [...items].sort((a, b) => {
    switch (sortBy) {
      case 'vmid':
        return (a.vmid - b.vmid) * dir
      case 'name':
        return a.name.localeCompare(b.name) * dir
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
        if (aPct == null) return 1
        if (bPct == null) return -1
        return (aPct - bPct) * dir
      }
      default:
        return 0
    }
  })
}
```

### UI — sort chip in ProxmoxFilterBar

The `ProxmoxFilterBar` component receives two new props: `sort` (`{ sortBy, sortDir }`) and `onSort` (`(sortBy, sortDir) => void`).

A chip is added at the right end of the filter row:

```
[node] [pool] [vm] [lxc] [running] [stopped] [name___]    [Sort: vmid ↑]
```

The chip label shows `Sort: <field> ↑/↓`. Behaviour:
- Clicking the **direction arrow** toggles `sortDir` between `asc`/`desc`.
- Clicking the **field label** opens a small inline dropdown listing the five fields. Selecting a field sets `sortBy` and closes the dropdown. If the same field is selected, direction toggles instead.

Dropdown fields:
- `vmid` — "vmid"
- `name` — "Name"
- `status` — "Status"
- `cpu` — "CPU %"
- `ram` — "RAM %"

Visual style: same chip style as other filter buttons (`text-[9px] px-1.5 py-px rounded border`). Active sort chip uses violet accent (`bg-violet-600/30 text-violet-300 border-violet-500/40`) to distinguish it from filter chips.

The dropdown is a small `absolute`-positioned panel below the chip, `z-10`, dark background matching the card theme.

---

## 2. Item Count in Section Header

The `Section` component in `ServiceCards.jsx` accepts a `label` prop. After filtering (and sorting), pass the filtered length into the label:

```jsx
<Section label={`VMs·Proxmox (${sorted.length})`} ...>
```

This shows the currently-visible count after filters are applied, e.g. `VMs·Proxmox (8)` when 4 are hidden by a filter.

---

## 3. SwarmServicesCard Alphabetical Sort

In `DashboardCards.jsx`, the `SwarmServicesCard` component renders `data?.services`. Add a single sort before render:

```js
const services = [...(data?.services ?? [])].sort((a, b) =>
  (a.name || '').localeCompare(b.name || '')
)
```

No UI, no state, no persistence needed. Alphabetical ascending, stable across polls.

---

## 4. Remove Dead `nodeCardSize` Setting

- **`OptionsContext.jsx`**: remove `nodeCardSize` from `DEFAULTS` and from the `options` object shape.
- **`OptionsModal.jsx`**: remove the `nodeCardSize` select/input from the Display tab.
- No other files reference this setting.

---

## Files Changed

| File | Change |
|---|---|
| `gui/src/components/ServiceCards.jsx` | Add `sortBy`/`sortDir` state, `sortProxmoxItems()`, updated `ProxmoxFilterBar` with sort chip, item count in section label |
| `gui/src/components/DashboardCards.jsx` | Sort services array in `SwarmServicesCard` |
| `gui/src/context/OptionsContext.jsx` | Remove `nodeCardSize` from DEFAULTS |
| `gui/src/components/OptionsModal.jsx` | Remove `nodeCardSize` UI |

---

## Out of Scope

- Sort for Containers·agent-01 section (different scope)
- VM/LXC type visual separator
- Sort for External Services section
