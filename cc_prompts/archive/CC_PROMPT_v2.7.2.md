# CC PROMPT — v2.7.2 — Generic ConnectionFilterBar + UniFi filtering

## Goal

Add a generic filter bar component that derives chips dynamically from any
collection of items. Wire it to UniFi first (type/status/name). Same component
drops into FortiGate interfaces, PBS datastores, TrueNAS pools with one line.

---

## Change 1 — Add ConnectionFilterBar component to ServiceCards.jsx

Add this component near the existing `ProxmoxFilterBar` function:

```jsx
/**
 * Generic filter bar for any InfraCard collection.
 * Derives chip options dynamically from the items array.
 *
 * fields: [{ key: 'type_label', label: 'type' }, { key: 'state', label: 'status' }]
 * filters: { type_label: null, state: null, name: '' }
 * setFilters: (updater) => void
 */
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
        // Derive unique values for this field from actual items
        const values = [...new Set(items.map(i => i[key]).filter(Boolean))].sort()
        if (values.length < 2) return null  // only show if there's something to filter
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

      {/* Name search */}
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

/**
 * Apply ConnectionFilterBar filters to a list of items.
 * fields: array of field keys to filter on (e.g. ['type_label', 'state'])
 */
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
```

---

## Change 2 — Add filter state to the UniFi section

### 2a — Add state variable

In the `ServiceCards` component body, alongside the existing
`unifiData`/`unifiConn` state, add:

```js
const [unifiFilters, setUnifiFilters] = useState({})
```

### 2b — Define UniFi filter fields (constant, outside component)

Add near the top of the file alongside other constants:

```js
const UNIFI_FILTER_FIELDS = [
  { key: 'type_label', label: 'type' },
  { key: 'state',      label: 'status' },
]
```

### 2c — Apply filters and add filterBar to the UniFi Section

Find the UniFi Section block. Currently the devices are filtered like:
```jsx
{devices.filter(d => {
  const devDot = d.state === 'connected' ? 'green' : 'amber'
  const eid = `unifi:device:${d.mac || d.name}`
  return matchesShowFilter(devDot) || isPinned(eid)
}).map(dev => { ... })}
```

Make three changes inside the UniFi Section block:

**1. Apply connection filters before the showFilter:**
```jsx
const filteredDevices = applyConnectionFilters(devices, unifiFilters, UNIFI_FILTER_FIELDS)
```

**2. Add `filterBar` prop to `<Section>`:**
```jsx
filterBar={
  <ConnectionFilterBar
    items={devices}
    filters={unifiFilters}
    setFilters={setUnifiFilters}
    fields={UNIFI_FILTER_FIELDS}
  />
}
```

**3. Render `filteredDevices` instead of `devices`:**
```jsx
{filteredDevices.filter(d => {
  const devDot = d.state === 'connected' ? 'green' : 'amber'
  const eid = `unifi:device:${d.mac || d.name}`
  return matchesShowFilter(devDot) || isPinned(eid)
}).map(dev => { ... })}
```

Also update the empty-state guard:
```jsx
// Before:
{devices.length === 0 && unifiData && (

// After:
{filteredDevices.length === 0 && unifiData && (
```

---

## How to add filtering to other sections (pattern)

For **FortiGate** (filter by type + link status):
```js
const FG_FILTER_FIELDS = [
  { key: 'type',  label: 'type' },   // physical, aggregate, vlan
]
// plus use filters on link: true/false (extend applyConnectionFilters if needed)
```

For **PBS** datastores — small list (1-3), probably not needed.

For **TrueNAS** pools — small list, probably not needed.

For **future UniFi networks** (if multiple connections) — extend
`unifiFilters` to a map keyed by connection label, same pattern as
Proxmox per-cluster filters in v2.7.1.

---

## Commit & deploy

```bash
git add -A
git commit -m "feat(dashboard): generic ConnectionFilterBar + UniFi type/status/name filtering

- Add ConnectionFilterBar component: derives chip options dynamically from
  any field on any items array; shows only fields with 2+ distinct values
- Add applyConnectionFilters() helper alongside existing applyProxmoxFilters()
- Wire to UniFi section: type_label chips (Switch/AP/UDM), state chips
  (connected/disconnected when mixed), name search
- UNIFI_FILTER_FIELDS constant makes it trivial to add fields or reuse for
  other platforms (FortiGate interfaces next candidate)"
git push origin main
# After CI green:
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env \
  up -d hp1_agent
```
