# Alert Strip Tray + Unified Card Grid — Design Spec

## Goal

Three improvements to the Dashboard UI: (1) the SubBar alert strip fills all available horizontal space, (2) clicking it opens a grouped dropdown tray that links directly to the affected infra section, (3) the Options card width/height settings apply to all cards — status cards and infra cards alike.

## Architecture

The work touches four files:

- `gui/src/App.jsx` — lift `activeFilters` state to `AppShell`; add tray open/close logic to `SubBar`; wire tray item clicks to `setActiveFilters` + `setActiveTab`
- `gui/src/components/ServiceCards.jsx` — `Section` reads `cardMinWidth`/`cardMaxWidth` from `useOptions()`; `InfraCard` receives `cardMinHeight` as a `minHeight` style
- `gui/src/components/DashboardCards.jsx` — no change (already uses options)
- `gui/src/components/OptionsModal.jsx` — no change (existing fields cover all needs)

---

## Section 1 — Alert strip width

**Current:** `maxWidth: 420` on the alert button, truncates early.

**Change:** Replace with `flex: 1; min-width: 0; overflow: hidden` so the strip grows to fill all horizontal space between the stats items and the right-side controls (API :8000, WS, version). Content continues to truncate with ellipsis. When there are no issues the strip renders nothing (no empty gap).

---

## Section 2 — Issues dropdown tray

### Trigger

Clicking the alert strip toggles `alertTrayOpen` boolean state in `SubBar`. Clicking outside the tray or pressing `Escape` closes it. The tray is a sibling of the SubBar bar, positioned absolutely so it overlays the main content.

### State architecture

`activeFilters` moves from `DashboardView` up to `AppShell`. `AppShell` passes:
- `activeFilters` + `setActiveFilters` → down to `DashboardView` (for filter bar)
- `onAlertNavigate(sectionKey)` → down to `SubBar` (for tray item clicks)

`onAlertNavigate(sectionKey)`:
1. Calls `setActiveTab('Dashboard')`
2. Calls `setActiveFilters([sectionKey])` — shows only the clicked section
3. Closes the tray

The user restores the full view by clicking "All" in the filter bar. No extra reset button needed.

### Tray layout

```
┌─────────────────────────────────────────────┐
│ ⚠  14 Infrastructure Issues                  │
├─────────────────────────────────────────────┤
│ PROXMOX VMs · 14                      → go  │
│   debian12-cloud-pmox1   stopped            │
│   debian-PmoxDCM         stopped            │
│   k3-nixos               stopped            │
│   … +11 more                                │
├─────────────────────────────────────────────┤
│ CONTAINERS · agent-01 · 0             → go  │
│ SWARM SERVICES · 0                    → go  │
│ EXTERNAL SERVICES · 0                 → go  │
└─────────────────────────────────────────────┘
```

- Dark theme (`bg-[#1a1a2e]`, `border-[#2a2a4a]`) matching ServiceCards
- Sections without issues show as collapsed one-liners (label + count + arrow)
- Sections with issues expand to show up to 5 items, then "+ N more"
- Clicking a section row (or its `→`) triggers `onAlertNavigate(sectionKey)` and closes tray
- Tray is `z-50`, min-width matches the strip width, max-height scrollable

### Section → filter key mapping

| Tray section | `sectionKey` |
|---|---|
| Proxmox VMs / LXC | `vms` |
| Containers · agent-01 | `containers_local` |
| Swarm services | `containers_swarm` |
| External services | `external` |

### Coverage — all alert sources have cards

| Alert source | Section in dashboard | Filter key |
|---|---|---|
| `containers.containers[].problem` | Containers · agent-01 | `containers_local` |
| `swarm.services[].problem` | Containers · Swarm | `containers_swarm` |
| `vms.vms[].problem` + `vms.lxc[].problem` | Proxmox Cluster | `vms` |
| `external.services[].problem` | External Services | `external` |

Nothing falls through — every alert type has a corresponding InfraCard section.

---

## Section 3 — Unified card grid (Options affects all cards)

### Problem

`ServiceCards` `Section` component uses `repeat(N, minmax(0, 1fr))` — fixed column count, ignores Options entirely. `DashboardCards` already uses `repeat(auto-fill, minmax(cardMinWidth, cardMaxWidth))`.

### Change

`Section` in `ServiceCards.jsx`:
- Reads `cardMinWidth`, `cardMaxWidth` from `useOptions()`
- Grid becomes `repeat(auto-fill, minmax(${cardMinWidth ?? 300}px, ${cardMaxWidth ? cardMaxWidth+'px' : '1fr'}))`
- `cols` prop removed (no longer needed)

`InfraCard` in `ServiceCards.jsx`:
- Receives `cardMinHeight` from `useOptions()`
- Applies `style={{ minHeight: cardMinHeight }}` to the outer wrapper div (collapsed state only — expanded content is not height-capped to avoid clipping)
- `cardMaxHeight` is intentionally **not** applied to infra cards (expanded panels would be cut off)

### Result

The four Min/Max Width/Height fields in Options now govern both sections of the dashboard. No new Options fields required.

---

## Error handling

- Tray data comes from `alerts` state already computed in SubBar — no new API calls
- If `alerts` is empty the tray never renders and the strip is hidden
- Tray dismisses safely if the user navigates away via the tab bar

## Out of scope

- Per-section column overrides
- Infra card max-height (would break expanded state)
- Tray persistence across page reloads
