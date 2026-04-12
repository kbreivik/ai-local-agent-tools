# CC PROMPT — v2.6.4 — FortiGate Section+InfraCard rich card

## What to build

Add a FortiGate Section+InfraCard cluster card to `ServiceCards.jsx` following
the exact same pattern as TrueNAS (v2.6.3). The backend collector
(`api/collectors/fortigate.py`) already exists. No backend changes needed.

The card shows per-interface InfraCards (link status, speed, IP, traffic) under
a cluster header that shows system-level info (hostname, version, HA mode).

---

## Implementation

File: `gui/src/components/ServiceCards.jsx`

### 1 — State + fetch effect

Add after the TrueNAS effect block:

```js
// FortiGate interfaces
const [fgData, setFgData] = useState(null)
const [fgConn, setFgConn] = useState(null)
useEffect(() => {
  if (!show('fortigate')) return
  const loadFg = () => {
    fetchCollectorData('fortigate').then(r => r?.data ? setFgData(r.data) : null).catch(() => {})
    fetch(`${BASE}/api/connections?platform=fortigate`, { headers: { ...authHeaders() } })
      .then(r => r.json()).then(d => setFgConn((d.data || []).find(c => c.host))).catch(() => {})
  }
  loadFg()
  const id = setInterval(loadFg, 60000)
  return () => clearInterval(id)
}, []) // eslint-disable-line react-hooks/exhaustive-deps
```

### 2 — Helper: format bytes

Add this small helper near the top of the file (alongside the existing `_fmtBytes` function,
or reuse it directly — `_fmtBytes` is already defined in ServiceCards.jsx):

```js
function _fgBytes(bytes) {
  if (!bytes) return '—'
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`
  if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(0)} KB`
  return `${bytes} B`
}
```

### 3 — Section JSX

Add after the TrueNAS block (inside `{!isInitialLoad && <> ... </>}`):

```jsx
{/* FortiGate Interfaces */}
{show('fortigate') && fgConn && (() => {
  const ifaces     = fgData?.interfaces || []
  const ifacesUp   = ifaces.filter(i => i.link && !((i.rx_errors || 0) + (i.tx_errors || 0))).length
  const ifacesDown = ifaces.filter(i => !i.link).length
  const ifacesWarn = ifaces.filter(i => i.link && ((i.rx_errors || 0) + (i.tx_errors || 0)) > 0).length
  const issues     = ifacesDown + ifacesWarn
  const dot        = fgData?.health === 'healthy' ? 'green'
                   : fgData?.health === 'degraded' ? 'amber'
                   : fgData ? 'red' : 'grey'
  const hostname   = fgData?.hostname || fgConn.label || fgConn.host
  const version    = fgData?.version || ''
  const haMode     = fgData?.ha_mode || ''

  return (
    <Section
      label={hostname}
      dot={dot}
      auth="API KEY"
      host={`${fgConn.host}:${fgConn.port || 443}`}
      runningCount={ifacesUp}
      totalCount={ifaces.length}
      issueCount={issues}
      countLabels={['up', 'total', 'issues']}
      filterBar={version ? (
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)',
                      display: 'flex', gap: 12, alignItems: 'center' }}>
          <span>{version}</span>
          {haMode && haMode !== 'standalone' && (
            <span style={{ color: 'var(--amber)' }}>HA: {haMode}</span>
          )}
          {fgData?.serial && <span>{fgData.serial}</span>}
        </div>
      ) : null}
      compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd}
      entityForCompare={{
        id: `fortigate:${fgConn.label || fgConn.host}`,
        label: hostname,
        platform: 'fortigate', section: 'NETWORK',
        metadata: { host: `${fgConn.host}:${fgConn.port || 443}`, version, ha_mode: haMode, interfaces: ifaces.length }
      }}
    >
      {ifaces.filter(i => {
        const errors = (i.rx_errors || 0) + (i.tx_errors || 0)
        const ifDot = !i.link ? 'red' : errors > 0 ? 'amber' : 'green'
        const eid = `fortigate:iface:${i.name}`
        return matchesShowFilter(ifDot) || isPinned(eid)
      }).map(iface => {
        const errors = (iface.rx_errors || 0) + (iface.tx_errors || 0)
        const ifDot  = !iface.link ? 'red' : errors > 0 ? 'amber' : 'green'
        const label  = iface.alias || iface.name
        const speed  = iface.speed ? `${iface.speed >= 1000 ? `${iface.speed / 1000}G` : `${iface.speed}M`}` : ''

        return (
          <InfraCard
            key={iface.name}
            cardKey={`fg-${iface.name}`}
            openKey={openKey} setOpenKey={setOpenKey}
            dot={ifDot}
            name={label}
            sub={`${iface.type || ''} ${speed ? '· ' + speed : ''}`.trim()}
            net={iface.ip || ''}
            uptime={''}
            collapsed={
              <div style={{ marginTop: 4 }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center',
                              fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)' }}>
                  <span style={{ color: ifDot === 'green' ? 'var(--green)' : ifDot === 'amber' ? 'var(--amber)' : 'var(--red)' }}>
                    {iface.link ? '● up' : '○ down'}
                  </span>
                  {iface.ip && <span>{iface.ip}</span>}
                  {errors > 0 && <span style={{ color: 'var(--amber)' }}>{errors} errors</span>}
                </div>
              </div>
            }
            expanded={
              <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-3)' }}>
                <div>Interface: <span style={{ color: 'var(--text-1)' }}>{iface.name}</span></div>
                {iface.alias && <div>Alias: <span style={{ color: 'var(--text-1)' }}>{iface.alias}</span></div>}
                <div>Type: <span style={{ color: 'var(--text-1)' }}>{iface.type || '—'}</span></div>
                <div>IP: <span style={{ color: 'var(--text-1)' }}>{iface.ip || '—'}</span></div>
                <div>Speed: <span style={{ color: 'var(--text-1)' }}>{speed || '—'}</span></div>
                <div>Link: <span style={{ color: iface.link ? 'var(--green)' : 'var(--red)' }}>
                  {iface.link ? 'up' : 'down'}
                </span></div>
                {(iface.rx_bytes != null || iface.tx_bytes != null) && (
                  <div style={{ marginTop: 4, paddingTop: 4, borderTop: '1px solid var(--bg-3)' }}>
                    <div>RX: <span style={{ color: 'var(--text-1)' }}>{_fgBytes(iface.rx_bytes)}</span></div>
                    <div>TX: <span style={{ color: 'var(--text-1)' }}>{_fgBytes(iface.tx_bytes)}</span></div>
                    {errors > 0 && (
                      <div style={{ color: 'var(--amber)' }}>
                        Errors: RX {iface.rx_errors || 0} · TX {iface.tx_errors || 0}
                      </div>
                    )}
                  </div>
                )}
              </div>
            }
            compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd}
            entityForCompare={{
              id: `fortigate:iface:${iface.name}`,
              label: `${hostname}/${label}`, platform: 'fortigate', section: 'NETWORK',
              metadata: { interface: iface.name, alias: iface.alias, link: iface.link,
                          type: iface.type, ip: iface.ip, speed: iface.speed,
                          rx_bytes: iface.rx_bytes, tx_bytes: iface.tx_bytes, errors }
            }}
          />
        )
      })}
      {ifaces.length === 0 && fgData && (
        <div className="col-span-full text-[10px] text-gray-700 py-2">No interfaces found</div>
      )}
      {!fgData && (
        <div className="col-span-full text-[10px] text-gray-700 py-2">Loading FortiGate interfaces…</div>
      )}
    </Section>
  )
})()}
```

### 4 — Add to CardFilterBar

File: `gui/src/components/CardFilterBar.jsx`

`fortigate` is already in `INFRA_SECTION_KEYS` if v2.6.3 added it. If not, add:

```js
{ key: 'fortigate', label: 'FortiGate', group: 'infra' },
```

---

## Notes

- No backend changes. Collector returns `{ health, hostname, version, serial, uptime, ha_mode, interfaces[], latency_ms, connection_label, connection_id }`.
- Interface fields used: `name`, `alias`, `link`, `speed`, `type`, `ip`, `rx_bytes`, `tx_bytes`, `rx_errors`, `tx_errors`.
- Section goes in NETWORK accordion — place after UniFi block in JSX, before the STORAGE sections.
- `_fgBytes` is a local helper. It's intentionally separate from the existing `_fmtBytes` (which takes bytes and adds context) — keep it simple.
- The filterBar slot is used here for system metadata (version, HA mode, serial) rather than filter chips, since the interface list is usually small. This is a valid use of the filterBar prop.

---

## Commit & deploy

```bash
git add -A
git commit -m "feat(dashboard): FortiGate Section+InfraCard rich card

Per-interface InfraCards with link status, speed, IP, rx/tx bytes.
Cluster header shows hostname, version, HA mode, serial.
Polls fetchCollectorData('fortigate') every 60s."
git push origin main
# After CI green:
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env \
  up -d hp1_agent
```
