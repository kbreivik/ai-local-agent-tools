# CC PROMPT — v2.28.6 — Collector rows link to their config (same as Platform Core)

## What this does
Collector rows in the COLLECTORS card now navigate to their relevant config when clicked,
using the same clickable `_row` pattern already in Platform Core.

Two changes in `gui/src/App.jsx` only:

1. AppShell: add `ds:navigate-settings` event listener so any component can navigate to
   Settings + a specific sub-tab without prop drilling
2. PlatformCoreCards: add `COLLECTOR_NAV` map + wire onClick to each collector row
   Also updates the existing ES row (in Platform Core) to use the new cleaner event

Collector → destination mapping:
  docker_agent01    → Dashboard (containers visible there)
  swarm             → Cluster tab
  kafka             → Cluster tab
  proxmox_vms       → Settings → Connections
  external_services → Settings → Connections
  vm_hosts          → Settings → Connections
  elasticsearch     → Settings → Connections
  pbs               → Settings → Connections
  truenas           → Settings → Connections
  unifi             → Settings → Connections
  fortigate         → Settings → Connections
  fortiswitch       → Settings → Connections
  windows           → Settings → Connections
  discovery_harvest → Discovered tab
Version bump: 2.28.5 → 2.28.6

---

## Change 1 — gui/src/App.jsx: add ds:navigate-settings listener in AppShell

Find the block of useEffect listeners in AppShell (near the "navigate-to-logs" handlers).
Add a new useEffect for `ds:navigate-settings`:

FIND (exact):
```jsx
  // "Full log →" link in AgentFeed navigates to Output tab
  useEffect(() => {
    const handler = () => setActiveTab('Output')
    window.addEventListener('navigate-to-output', handler)
    return () => window.removeEventListener('navigate-to-output', handler)
  }, [])
```

REPLACE WITH:
```jsx
  // "Full log →" link in AgentFeed navigates to Output tab
  useEffect(() => {
    const handler = () => setActiveTab('Output')
    window.addEventListener('navigate-to-output', handler)
    return () => window.removeEventListener('navigate-to-output', handler)
  }, [])

  // Programmatic navigation to Settings + specific sub-tab
  // Usage: window.dispatchEvent(new CustomEvent('ds:navigate-settings', { detail: { settingsTab: 'Connections' } }))
  useEffect(() => {
    const handler = (e) => {
      const { settingsTab: subTab } = e.detail || {}
      setActiveTab('Settings')
      if (subTab) setSettingsTab(subTab)
    }
    window.addEventListener('ds:navigate-settings', handler)
    return () => window.removeEventListener('ds:navigate-settings', handler)
  }, [])
```

---

## Change 2 — gui/src/App.jsx: add COLLECTOR_NAV map to PlatformCoreCards

Find the `COLLECTOR_NAV` constant location — add it INSIDE the `PlatformCoreCards` function,
just before `sortedCollectors` is used (near the top of the function, after the helper fns).

FIND (exact):
```jsx
  const sortedCollectors = Object.entries(collectorsData || {}).sort(([a], [b]) => a.localeCompare(b))
  const apiOk = health?.status === 'ok'
```

REPLACE WITH:
```jsx
  const sortedCollectors = Object.entries(collectorsData || {}).sort(([a], [b]) => a.localeCompare(b))
  const apiOk = health?.status === 'ok'

  // Collector name → navigation intent
  // 'tab' navigates to a top-level tab; 'settings' navigates to Settings → Connections
  const COLLECTOR_NAV = {
    docker_agent01:    { type: 'tab',      tab: 'Dashboard'   },
    swarm:             { type: 'tab',      tab: 'Cluster'     },
    kafka:             { type: 'tab',      tab: 'Cluster'     },
    proxmox_vms:       { type: 'settings', settingsTab: 'Connections' },
    external_services: { type: 'settings', settingsTab: 'Connections' },
    vm_hosts:          { type: 'settings', settingsTab: 'Connections' },
    elasticsearch:     { type: 'settings', settingsTab: 'Connections' },
    pbs:               { type: 'settings', settingsTab: 'Connections' },
    truenas:           { type: 'settings', settingsTab: 'Connections' },
    unifi:             { type: 'settings', settingsTab: 'Connections' },
    fortigate:         { type: 'settings', settingsTab: 'Connections' },
    fortiswitch:       { type: 'settings', settingsTab: 'Connections' },
    windows:           { type: 'settings', settingsTab: 'Connections' },
    discovery_harvest: { type: 'tab',      tab: 'Discovered'  },
  }

  const _collectorClick = (name) => {
    const nav = COLLECTOR_NAV[name]
    if (!nav) return undefined
    if (nav.type === 'tab') {
      return () => onTab?.(nav.tab)
    }
    return () => window.dispatchEvent(
      new CustomEvent('ds:navigate-settings', { detail: { settingsTab: nav.settingsTab } })
    )
  }
```

---

## Change 3 — gui/src/App.jsx: wire onClick to collector rows

FIND (exact):
```jsx
        {sortedCollectors.map(([name, c]) => {
          const h = c.last_health || 'unknown'
          return _row(_healthDot(h), name, h.toUpperCase(), _healthTag(h), c.running ? '' : 'stopped')
        })}
```

REPLACE WITH:
```jsx
        {sortedCollectors.map(([name, c]) => {
          const h = c.last_health || 'unknown'
          return _row(
            _healthDot(h), name, h.toUpperCase(), _healthTag(h),
            c.running ? '' : 'stopped',
            _collectorClick(name)
          )
        })}
```

---

## Change 4 — gui/src/App.jsx: clean up ES row in Platform Core to use ds:navigate-settings

The ES row in Platform Core currently uses the old `onTab('Settings') + setTimeout(ds:settings-tab)`
pattern. Update it to use the cleaner `ds:navigate-settings` event:

FIND (exact):
```jsx
          onTab ? () => {
            // Navigate to Settings → Connections, pre-selecting elasticsearch platform
            onTab('Settings')
            // Dispatch event to pre-filter connections to elasticsearch
            setTimeout(() => window.dispatchEvent(new CustomEvent('ds:settings-tab', {
              detail: { tab: 'Connections', filterPlatform: 'elasticsearch' }
            })), 100)
          } : undefined
```

REPLACE WITH:
```jsx
          () => window.dispatchEvent(
            new CustomEvent('ds:navigate-settings', { detail: { settingsTab: 'Connections' } })
          )
```

---

## Version bump
Update VERSION: 2.28.5 → 2.28.6

## Commit
```bash
git add -A
git commit -m "feat(platform): v2.28.6 collector rows link to config — same pattern as Platform Core"
git push origin main
```
