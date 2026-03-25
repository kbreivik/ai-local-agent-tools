# Alert Strip Tray + Unified Card Grid — Design Spec

## Goal

Three improvements to the Dashboard UI: (1) the SubBar alert strip fills all available horizontal space, (2) clicking it opens a grouped dropdown tray that links directly to the affected infra section, (3) the Options card width/height settings apply to all cards — status cards and infra cards alike.

## Current codebase state (as of this spec)

Key facts an implementer must know before reading the tasks:

- `activeFilters` state lives in `DashboardView` **inside `App.jsx`** (not in `DashboardCards.jsx` — that was refactored in a prior session and now receives `activeFilters` as a prop).
- `SubBar` **already** polls `fetchDashboardContainers/Swarm/VMs/External` every 30 s and holds `alerts[]` state. No new API calls are needed.
- `ALL_CARD_KEYS` in `CardFilterBar.jsx` already contains both status-card keys (`swarm_nodes`, `kafka_brokers`, etc.) **and** infra-section keys (`containers_local`, `containers_swarm`, `vms`, `external`). The infra-section keys were added in a prior session and are what `ServiceCards` reads via its `activeFilters` prop.
- `DashboardCards.jsx` already reads `cardMinWidth/cardMaxWidth/cardMinHeight/cardMaxHeight` from `useOptions()`. `ServiceCards.jsx` does not yet do so.

## Architecture

Changes required in three files:

| File | Change |
|---|---|
| `gui/src/App.jsx` | Lift `activeFilters` + handlers from `DashboardView` to `AppShell`; construct `onAlertNavigate` in `AppShell`; pass it to `SubBar`; add tray open/close to `SubBar` |
| `gui/src/components/ServiceCards.jsx` | `Section` uses options-driven auto-fill grid; `InfraCard` applies `cardMinHeight` when collapsed |
| `gui/src/components/DashboardCards.jsx` | No change |
| `gui/src/components/OptionsModal.jsx` | No change |

---

## Section 1 — Alert strip width

**Current:** the alert strip `<button>` has `style={{ maxWidth: 420 }}` and `className` includes `shrink`.

**Change:** remove `maxWidth` and replace shrink behaviour with `flex: 1; minWidth: 0; overflow: hidden`. The strip grows to fill all horizontal space between the stats group and the right-side controls (API :8000, WS, version). Content truncates with ellipsis as before. When `alerts.length === 0` the strip renders nothing (no empty gap).

---

## Section 2 — Issues dropdown tray

### State lift

`activeFilters`, `toggleFilter`, and `toggleAll` move from `DashboardView` up to `AppShell`. The prop chain becomes:

```
AppShell  (owns activeFilters, setActiveFilters, activeTab, setActiveTab)
  ├── SubBar
  │     props: onTab, alerts, onAlertNavigate
  └── DashboardView
        props: activeFilters, onToggleFilter, onToggleAll
          ├── CardFilterBar   (activeFilters, onToggle, onToggleAll)
          ├── DashboardCards  (activeFilters)
          └── ServiceCards    (activeFilters)
```

`AppShell` constructs `onAlertNavigate` as a closure over `setActiveTab` and `setActiveFilters`:

```js
const onAlertNavigate = useCallback((sectionKey) => {
  setActiveTab('Dashboard')
  setActiveFilters([sectionKey])
}, [])
```

`setActiveFilters([sectionKey])` sets a single-element array so the filter bar shows only the clicked section. The user restores the full view by clicking "All" in the filter bar — no separate reset button needed. localStorage is **not** updated on alert-navigate (transient state only; user's saved filter is restored on next manual toggle).

### Tray trigger

`SubBar` gains `alertTrayOpen` boolean state. The alert strip button `onClick` toggles it. A `useEffect` adds a `mousedown` listener on `document` to close the tray on outside click (same pattern as the Tools dropdown in `Header`). A second `useEffect` adds a `keydown` listener for `Escape` to close the tray. Both listeners are cleaned up on unmount.

### Tray positioning

The tray is rendered as a sibling `<div>` **inside the same parent `<div>` that wraps the alert strip button**. That parent div gets `position: relative`. The tray is `position: absolute; top: 100%; left: 0; z-index: 50`. It aligns to the left edge of the strip and is at minimum as wide as the strip (`min-width: 100%`).

### Tray layout and content

Dark theme matching ServiceCards. Structure:

```
┌─────────────────────────────────────────────────┐
│ ⚠  14 Infrastructure Issues                      │
├─────────────────────────────────────────────────┤
│ PROXMOX VMs  ·  14 stopped               [→ go] │
│   debian12-cloud-pmox1   stopped                │
│   debian-PmoxDCM         stopped                │
│   k3-nixos               stopped                │
│   … +11 more                                    │
├─────────────────────────────────────────────────┤
│ CONTAINERS · agent-01  ·  0 issues       [→ go] │
│ SWARM SERVICES  ·  0 issues              [→ go] │
│ EXTERNAL SERVICES  ·  0 issues           [→ go] │
└─────────────────────────────────────────────────┘
```

- Sections **with** issues: expand to show up to 5 item names + problem, then "+ N more"
- Sections **without** issues: one-liner (label + "0 issues" + arrow), dimmed
- Each section row (including the `→` arrow) is clickable and calls `onAlertNavigate(sectionKey)`, which closes the tray, switches to Dashboard, and sets filter to that section only
- `max-height: 400px; overflow-y: auto` on the scrollable body

### Section → filter key mapping

The `sectionKey` values passed to `onAlertNavigate` are the infra-section keys from `ALL_CARD_KEYS`:

| Tray section | `sectionKey` | Alerts source |
|---|---|---|
| Proxmox VMs / LXC | `vms` | `vms.vms[].problem` + `vms.lxc[].problem` |
| Containers · agent-01 | `containers_local` | `containers.containers[].problem` |
| Swarm services | `containers_swarm` | `swarm.services[].problem` |
| External services | `external` | `external.services[].problem` |

These keys already exist in `ALL_CARD_KEYS` (infra group). `setActiveFilters([sectionKey])` hides all other sections; the targeted section is visible because `ServiceCards` checks `activeFilters.includes(key)`.

### Coverage — all alert sources have cards

| Alert source | Dashboard section | Filter key |
|---|---|---|
| `containers.containers[].problem` | Containers · agent-01 | `containers_local` ✓ |
| `swarm.services[].problem` | Containers · Swarm | `containers_swarm` ✓ |
| `vms.vms[].problem` + `vms.lxc[].problem` | Proxmox Cluster | `vms` ✓ |
| `external.services[].problem` | External Services | `external` ✓ |

Nothing falls through.

---

## Section 3 — Unified card grid (Options affects all cards)

### Section component change

`Section` in `ServiceCards.jsx` currently accepts a `cols` prop and uses:
```js
gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`
```

**Change:** remove the `cols` prop entirely. All four `Section` callsites in `ServiceCards.jsx` that pass `cols={4}` must have that prop deleted. `Section` reads `cardMinWidth` and `cardMaxWidth` from `useOptions()` and uses:
```js
const { cardMinWidth, cardMaxWidth } = useOptions()
const _min = cardMinWidth ?? 300
const _max = cardMaxWidth ? `${cardMaxWidth}px` : '1fr'
gridTemplateColumns: `repeat(auto-fill, minmax(${_min}px, ${_max}))`
```

This is identical to the formula already used in `DashboardCards.jsx`.

### InfraCard height

`InfraCard` in `ServiceCards.jsx` reads `cardMinHeight` from `useOptions()`. The outer wrapper `<div>` gets a conditional `minHeight` style — applied only when the card is **collapsed** to avoid clipping expanded content:

```jsx
<div
  style={isOpen ? undefined : { minHeight: cardMinHeight }}
  className={`${cs.bg} border ... rounded-lg px-2.5 py-2.5 cursor-pointer`}
>
```

`cardMaxHeight` is intentionally **not** applied to `InfraCard` at any time — expanded panels contain variable-length content and would be clipped.

### Result

The four Min/Max Width/Height fields in Options now govern both the status cards (DashboardCards) and the infra tiles (ServiceCards). No new Options fields required.

---

## Out of scope

- Per-section column overrides
- Infra card `cardMaxHeight`
- Tray state persisted across reloads
- Scroll-to-specific-card behaviour (filter to section is sufficient)
