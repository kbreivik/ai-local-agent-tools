# CC PROMPT — v2.7.1 — Per-cluster filter bars with dynamic node/type/status chips

## Problem

In v2.7.0, `filterBar` only renders on the first cluster (`clusterIdx === 0`),
and all clusters share one `proxmoxFilters` state object. So PROX CLUSTER FIN
shows no filter bar, and filtering one cluster would affect all others.

## Fix — gui/src/components/ServiceCards.jsx only

### 1 — Change filter state from single object to per-cluster map

Find:
```js
const [proxmoxFilters, setProxmoxFilters] = useState({})
```

Replace with:
```js
// Per-cluster filter state keyed by connection_id (or cluster index fallback)
const [proxmoxFilterMap, setProxmoxFilterMap] = useState({})

const getClusterFilters = (key) => proxmoxFilterMap[key] || {}
const setClusterFilters = (key, updater) => setProxmoxFilterMap(prev => ({
  ...prev,
  [key]: typeof updater === 'function' ? updater(prev[key] || {}) : updater,
}))
```

### 2 — Remove the clusterIdx === 0 restriction and pass per-cluster state

In the multi-cluster render block, find the `filterBar` prop:

```jsx
filterBar={clusterIdx === 0 ? (
  <ProxmoxFilterBar
    items={allItems}
    filters={proxmoxFilters}
    setFilters={setProxmoxFilters}
    sort={{ sortBy, sortDir }}
    onSort={(by, dir) => { setSortBy(by); setSortDir(dir) }}
  />
) : null}
```

Replace with:

```jsx
filterBar={
  <ProxmoxFilterBar
    items={allItems}
    filters={getClusterFilters(cluster.connection_id || clusterIdx)}
    setFilters={(updater) => setClusterFilters(cluster.connection_id || clusterIdx, updater)}
    sort={{ sortBy, sortDir }}
    onSort={(by, dir) => { setSortBy(by); setSortDir(dir) }}
  />
}
```

### 3 — Use per-cluster filters when applying filters and rendering cards

In the same cluster render block, find:

```js
const filtered = applyProxmoxFilters(allItems, proxmoxFilters)
```

Replace with:

```js
const clusterFilters = getClusterFilters(cluster.connection_id || clusterIdx)
const filtered = applyProxmoxFilters(allItems, clusterFilters)
```

That's the only change — `sorted` derives from `filtered` so it picks up automatically.

### 4 — Update the "no items match filter" empty state

Find in the same block:

```jsx
{sorted.length === 0 && allItems.length > 0 && (
  <div className="col-span-full text-[10px] text-gray-700 py-2">no items match filter</div>
)}
```

No change needed — already correct.

---

## Notes

- Sort order (`sortBy`/`sortDir`) stays shared across all clusters — same sort
  logic for all makes sense since you'd typically want VMs sorted consistently.
- `ProxmoxFilterBar` already derives node chips dynamically from `items` via
  `[...new Set(items.map(v => v.node_api))].sort()` — so FIN cluster will
  automatically show its own nodes (pve1, pve3, etc.) and KB cluster shows
  Pmox1/Pmox2/Pmox3. No changes needed to `ProxmoxFilterBar` itself.
- Max nodes shown is already handled by the filter bar (renders all discovered
  nodes). For 5+ nodes the chips wrap naturally on the filter row.
- Filters are not persisted to localStorage per-cluster — they reset on page
  reload which is fine (sort preference is persisted, that's the important one).

---

## Commit & deploy

```bash
git add -A
git commit -m "fix(compute): per-cluster Proxmox filter bars with dynamic node chips

Each cluster now gets its own independent filter state keyed by connection_id.
ProxmoxFilterBar renders for every cluster (not just index 0) and derives node
chips from that cluster's own nodes. Sort state remains shared across clusters."
git push origin main
# After CI green:
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env \
  up -d hp1_agent
```
