# CC PROMPT — v2.6.3 — TrueNAS rich card (Section + InfraCard)

## What to build

Add a TrueNAS Section+InfraCard cluster card to `ServiceCards.jsx` following the
exact same pattern as the PBS datastores card. The backend collector
(`api/collectors/truenas.py`) already exists and returns pool data — no backend
changes needed.

---

## Implementation

File: `gui/src/components/ServiceCards.jsx`

### 1 — State + fetch effect

Add alongside the existing `unifiData`/`pbsData` blocks (after the PBS effect):

```js
// TrueNAS pools
const [truenasData, setTruenasData] = useState(null)
const [truenasConn, setTruenasConn] = useState(null)
useEffect(() => {
  if (!show('truenas')) return
  const loadTruenas = () => {
    fetchCollectorData('truenas').then(r => r?.data ? setTruenasData(r.data) : null).catch(() => {})
    fetch(`${BASE}/api/connections?platform=truenas`, { headers: { ...authHeaders() } })
      .then(r => r.json()).then(d => setTruenasConn((d.data || []).find(c => c.host))).catch(() => {})
  }
  loadTruenas()
  const id = setInterval(loadTruenas, 60000)
  return () => clearInterval(id)
}, []) // eslint-disable-line react-hooks/exhaustive-deps
```

### 2 — Section JSX

Add after the PBS datastores block (inside `{!isInitialLoad && <> ... </>}`),
before the closing `</>`):

```jsx
{/* TrueNAS Pools */}
{show('truenas') && truenasConn && (() => {
  const pools   = truenasData?.pools || []
  const poolsOk = pools.filter(p => p.healthy && p.status === 'ONLINE' && p.usage_pct <= 85).length
  const issues  = pools.filter(p => !p.healthy || p.status !== 'ONLINE' || p.usage_pct > 85).length
  const dot     = truenasData?.health === 'healthy' ? 'green'
                : truenasData?.health === 'degraded' ? 'amber'
                : truenasData ? 'red' : 'grey'
  return (
    <Section
      label={truenasConn.label || truenasConn.host}
      dot={dot}
      auth="API KEY"
      host={`${truenasConn.host}:${truenasConn.port || 443}`}
      runningCount={poolsOk}
      totalCount={pools.length}
      issueCount={issues}
      countLabels={['ok', 'total', 'issues']}
      compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd}
      entityForCompare={{
        id: `truenas:${truenasConn.label || truenasConn.host}`,
        label: truenasConn.label || truenasConn.host,
        platform: 'truenas', section: 'STORAGE',
        metadata: { host: `${truenasConn.host}:${truenasConn.port || 443}`, pools: pools.length }
      }}
    >
      {pools.filter(pool => {
        const poolDot = !pool.healthy || pool.status !== 'ONLINE' ? 'red'
                      : pool.usage_pct > 85 ? 'amber' : 'green'
        return matchesShowFilter(poolDot) || isPinned(`truenas:pool:${pool.name}`)
      }).map(pool => {
        const pct      = pool.usage_pct ?? 0
        const healthy  = pool.healthy && pool.status === 'ONLINE'
        const poolDot  = !healthy ? 'red' : pct > 85 ? 'amber' : 'green'
        const barColor = !healthy ? 'var(--red)' : pct > 85 ? 'var(--amber)' : 'var(--green)'
        return (
          <InfraCard
            key={pool.name}
            cardKey={`truenas-${pool.name}`}
            openKey={openKey} setOpenKey={setOpenKey}
            dot={poolDot}
            name={pool.name}
            sub={`${Math.round(pct)}% used`}
            net={''}
            uptime={`${pool.size_gb} GB`}
            collapsed={
              <div style={{ marginTop: 4 }}>
                <div style={{ height: 3, borderRadius: 2, background: 'var(--bg-3)', overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${pct}%`, background: barColor, borderRadius: 2 }} />
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, marginTop: 2, fontFamily: 'var(--font-mono)', color: 'var(--text-3)' }}>
                  <span>{pool.allocated_gb} GB used</span>
                  <span>{pool.size_gb} GB total</span>
                </div>
              </div>
            }
            expanded={
              <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-3)' }}>
                <div style={{ marginBottom: 6 }}>
                  <div style={{ height: 4, borderRadius: 2, background: 'var(--bg-3)', overflow: 'hidden', marginBottom: 4 }}>
                    <div style={{ height: '100%', width: `${pct}%`, background: barColor, borderRadius: 2 }} />
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span>{pool.allocated_gb} GB used</span>
                    <span style={{ color: 'var(--text-1)' }}>{Math.round(pct)}%</span>
                    <span>{pool.size_gb} GB total</span>
                  </div>
                </div>
                <div>Status: <span style={{ color: poolDot === 'green' ? 'var(--green)' : 'var(--red)' }}>{pool.status}</span></div>
                <div>Free: <span style={{ color: 'var(--text-1)' }}>{pool.free_gb} GB</span></div>
                <div>vDevs: <span style={{ color: 'var(--text-1)' }}>{pool.vdev_count}</span></div>
                <div>Scan: <span style={{ color: 'var(--text-1)' }}>{pool.scan_state || '—'}{pool.scan_errors > 0 ? ` (${pool.scan_errors} errors)` : ''}</span></div>
              </div>
            }
            compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd}
            entityForCompare={{
              id: `truenas:pool:${pool.name}`,
              label: pool.name, platform: 'truenas', section: 'STORAGE',
              metadata: { status: pool.status, healthy: pool.healthy, usage_pct: pct, allocated_gb: pool.allocated_gb, size_gb: pool.size_gb, free_gb: pool.free_gb, scan_state: pool.scan_state }
            }}
          />
        )
      })}
      {pools.length === 0 && truenasData && (
        <div className="col-span-full text-[10px] text-gray-700 py-2">No pools found</div>
      )}
      {!truenasData && (
        <div className="col-span-full text-[10px] text-gray-700 py-2">Loading TrueNAS pools…</div>
      )}
    </Section>
  )
})()}
```

---

## Required fix — CardFilterBar.jsx

`show(key)` in `ServiceCards.jsx` checks `activeFilters.includes(key)`. The filter
array is initialised from `ALL_CARD_KEYS` in `CardFilterBar.jsx`. Currently
`unifi`, `pbs`, and `truenas` are not in that array, so `show('unifi')`,
`show('pbs')`, and `show('truenas')` always return `false` — those sections are
never rendered.

File: `gui/src/components/CardFilterBar.jsx`

Replace `INFRA_SECTION_KEYS`:

```js
// Infra detail sections (ServiceCards bottom section)
const INFRA_SECTION_KEYS = [
  { key: 'containers_local', label: 'Docker',   group: 'infra' },
  { key: 'containers_swarm', label: 'Swarm',    group: 'infra' },
  { key: 'vms',              label: 'VMs',      group: 'infra' },
  { key: 'external',         label: 'External', group: 'infra' },
  { key: 'unifi',            label: 'UniFi',    group: 'infra' },
  { key: 'pbs',              label: 'PBS',      group: 'infra' },
  { key: 'truenas',          label: 'TrueNAS',  group: 'infra' },
]
```

Note: `App.jsx` initialises `activeFilters` from `ALL_CARD_KEYS` and also merges
any new keys not present in `localStorage` (the `newKeys` logic). So existing
users with a cached filter will automatically get `unifi`, `pbs`, `truenas`
added as enabled on next load — no manual migration needed.

---

## Other notes

- No backend changes. Collector is live, returns `{ health, pools[], pool_count, latency_ms, connection_label, connection_id }`.
- Pool fields used: `name`, `status`, `healthy`, `usage_pct`, `size_gb`, `allocated_gb`, `free_gb`, `vdev_count`, `scan_state`, `scan_errors`.
- Section goes after PBS in the JSX (both are STORAGE platforms).

---

## Commit & deploy

```bash
git add -A
git commit -m "feat(dashboard): TrueNAS Section+InfraCard rich card

Adds TrueNAS pool cluster card following UniFi/PBS pattern.
Per-pool InfraCard with usage bar, scan state, vdev count.
Polls fetchCollectorData('truenas') every 60s."
git push origin main
# After CI green:
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env \
  up -d hp1_agent
```
