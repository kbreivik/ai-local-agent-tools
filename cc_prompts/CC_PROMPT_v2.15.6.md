# CC PROMPT — v2.15.6 — Platform Core row order + alphabetical sorting everywhere

## What this does

1. Platform Core rows: swap order so value (v2.15.4, pg16) appears BEFORE the status
   tag (ONLINE, HEALTHY), both pushed to the right
2. All sorting defaults to alphabetical by name — VMs, containers, collectors, connections

Version bump: 2.15.5 → 2.15.6 (UI fixes, x.x.1)

---

## Fix 1 — App.jsx: Platform Core _row() — value before tag

Find `_row` in `PlatformCoreCards` in `App.jsx`:

```jsx
const _row = (dot, label, tag, tagColor, value) => (
  <div style={{ display: 'flex', alignItems: 'center', padding: '4px 0',
                borderTop: '1px solid var(--bg-3)', fontSize: 10, gap: 6 }}>
    <span style={{ width: 6, height: 6, borderRadius: '50%', background: dot, flexShrink: 0 }} />
    <span style={{ flex: 1, color: 'var(--text-2)', fontFamily: 'var(--font-mono)' }}>{label}</span>
    {tag && <span style={{ fontSize: 7, fontFamily: 'var(--font-mono)', padding: '1px 4px',
                           background: _tagBg(tagColor), color: _tagFg(tagColor),
                           borderRadius: 2 }}>{tag}</span>}
    {value && <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-3)',
                              fontSize: 9 }}>{value}</span>}
  </div>
)
```

Swap the value and tag so value comes BEFORE tag, both right-aligned:

```jsx
const _row = (dot, label, tag, tagColor, value) => (
  <div style={{ display: 'flex', alignItems: 'center', padding: '4px 0',
                borderTop: '1px solid var(--bg-3)', fontSize: 10, gap: 6 }}>
    <span style={{ width: 6, height: 6, borderRadius: '50%', background: dot, flexShrink: 0 }} />
    <span style={{ flex: 1, color: 'var(--text-2)', fontFamily: 'var(--font-mono)' }}>{label}</span>
    {/* Value BEFORE tag — pushed to the right */}
    {value && <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-3)',
                              fontSize: 9 }}>{value}</span>}
    {tag && <span style={{ fontSize: 7, fontFamily: 'var(--font-mono)', padding: '1px 4px',
                           background: _tagBg(tagColor), color: _tagFg(tagColor),
                           borderRadius: 2, letterSpacing: 0.5 }}>{tag}</span>}
  </div>
)
```

Result: `DS-agent-01   v2.15.4  [ONLINE]`
        `hp1-postgres  pg16     [HEALTHY]`

---

## Fix 2 — App.jsx: sortedCollectors already alphabetical — verify

The existing code:
```js
const sortedCollectors = Object.entries(collectors).sort(([a], [b]) => a.localeCompare(b))
```
This is correct. No change needed here.

---

## Fix 3 — ServiceCards.jsx: VM sort default = name ascending

Find the sortBy/sortDir useState initialization:

```js
const [sortBy, setSortBy] = useState(() => {
  try {
    const s = JSON.parse(localStorage.getItem('hp1_proxmox_sort') || '{}')
    return s.sortBy || 'vmid'   // ← change to 'name'
  } catch { return 'vmid' }    // ← change to 'name'
})
const [sortDir, setSortDir] = useState(() => {
  try {
    const s = JSON.parse(localStorage.getItem('hp1_proxmox_sort') || '{}')
    return s.sortDir || 'asc'
  } catch { return 'asc' }
})
```

Change both `'vmid'` defaults to `'name'`:

```js
const [sortBy, setSortBy] = useState(() => {
  try {
    const s = JSON.parse(localStorage.getItem('hp1_proxmox_sort') || '{}')
    return s.sortBy || 'name'
  } catch { return 'name' }
})
```

---

## Fix 4 — ServiceCards.jsx: container cards sorted alphabetically

For the local containers section, containers render in API order. Sort by name:

Find:
```jsx
{(containers?.containers || []).filter(c => ...).map(c => (
```

Change to:
```jsx
{[...(containers?.containers || [])].sort((a, b) => (a.name || '').localeCompare(b.name || ''))
  .filter(c => ...).map(c => (
```

For swarm services:
```jsx
{(swarm?.services || []).filter(s => ...).map(s => (
```

Change to:
```jsx
{[...(swarm?.services || [])].sort((a, b) => (a.name || '').localeCompare(b.name || ''))
  .filter(s => ...).map(s => (
```

---

## Fix 5 — OptionsModal.jsx: connections list sorted alphabetically

In `ConnectionsTab`, after `setConns`:
```js
.then(d => {
  const all = d.data || []
  setConns(all)
  ...
})
```

Change to:
```js
.then(d => {
  const all = (d.data || []).sort((a, b) =>
    (a.label || a.host || '').localeCompare(b.label || b.host || '')
  )
  setConns(all)
  ...
})
```

---

## Fix 6 — App.jsx: ConnectionSectionCards sorted alphabetically

In `ConnectionSectionCards`, the `conns` state is set from the API response.
Sort after filtering:

```js
.then(d => setConns(
  (d.data || [])
    .filter(c => platforms.includes(c.platform) && c.host)
    .sort((a, b) => (a.label || a.host || '').localeCompare(b.label || b.host || ''))
))
```

---

## Version bump

Update VERSION: `2.15.5` → `2.15.6`

---

## Commit

```bash
git add -A
git commit -m "fix(ui): v2.15.6 Platform Core value-before-tag + alphabetical sorting

- Platform Core rows: value (v2.15.4, pg16) now appears before status tag (ONLINE, HEALTHY)
- VM sort default: 'name' ascending instead of 'vmid'
- Container cards: sorted alphabetically by name (local + swarm)
- Connections list: sorted alphabetically by label
- ConnectionSectionCards: sorted alphabetically by label"
git push origin main
```
