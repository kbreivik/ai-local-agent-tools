# CC PROMPT — v2.7.0 — Multiple Proxmox connections → multiple COMPUTE cluster cards

## Problem

`get_connection_for_platform('proxmox')` uses `LIMIT 1` — only the first
Proxmox connection is ever polled. A second cluster connection is ignored.
The frontend renders a single hardcoded COMPUTE cluster card regardless.

## Solution

4-file change. Keep backward compat throughout (existing single-cluster setups
must work identically after the change).

---

## Change 1 — api/connections.py

Add a new helper below `get_connection_for_platform()`:

```python
def get_all_connections_for_platform(platform: str) -> list[dict]:
    """Get ALL enabled connections for a platform with decrypted credentials.

    Used by collectors that support multiple connections (e.g. multiple
    Proxmox clusters). Works with both PostgreSQL and SQLite.
    """
    # PostgreSQL
    conn = _get_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM connections WHERE platform = %s AND enabled = true "
                "AND host != '' ORDER BY created_at",
                (platform,),
            )
            cols = [desc[0] for desc in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
            cur.close()
            conn.close()
            return [_decode_creds(r) for r in rows]
        except Exception:
            return []

    # SQLite fallback
    try:
        from sqlalchemy import text as _text
        sa = _get_sa_conn()
        if not sa:
            return []
        rows = sa.execute(
            _text("SELECT * FROM connections WHERE platform=:p AND enabled=1 "
                  "AND host!='' ORDER BY created_at"),
            {"p": platform},
        ).mappings().fetchall()
        sa.close()
        return [_decode_creds(dict(r)) for r in rows]
    except Exception:
        return []
```

---

## Change 2 — api/collectors/proxmox_vms.py

Replace `_collect_sync()` to iterate ALL Proxmox connections and poll each
independently. State shape gains a `clusters` list; flat `vms`/`lxc` lists
are kept for backward compat with `to_entities()` and anything else reading
the snapshot.

```python
def _collect_sync(self) -> dict:
    from api.connections import get_all_connections_for_platform
    connections = get_all_connections_for_platform("proxmox")

    # Env var fallback when no DB connections configured
    if not connections:
        host = os.environ.get("PROXMOX_HOST", "")
        if not host:
            return {"health": "unconfigured", "vms": [], "lxc": [], "clusters": [],
                    "message": "No Proxmox connection configured"}
        connections = [{
            "id": "", "label": host, "host": host,
            "port": int(os.environ.get("PROXMOX_PORT", "8006")),
            "credentials": {
                "user": os.environ.get("PROXMOX_USER", ""),
                "token_name": os.environ.get("PROXMOX_TOKEN_NAME", ""),
                "secret": os.environ.get("PROXMOX_TOKEN_SECRET", ""),
            },
        }]

    clusters = []
    all_vms = []
    all_lxc = []

    for conn in connections:
        result = _poll_single_connection(conn)
        clusters.append(result)
        all_vms.extend(result.get("vms", []))
        all_lxc.extend(result.get("lxc", []))

    # Overall health: worst of all clusters
    healths = [c.get("health", "unknown") for c in clusters]
    if any(h in ("error", "critical") for h in healths):
        overall = "critical"
    elif any(h == "degraded" for h in healths):
        overall = "degraded"
    elif all(h == "healthy" for h in healths):
        overall = "healthy"
    else:
        overall = "unknown"

    # Backward compat: expose first cluster's label/id at top level
    first = clusters[0] if clusters else {}
    return {
        "health": overall,
        "clusters": clusters,
        # Flat merged lists — used by to_entities() and legacy code
        "vms": all_vms,
        "lxc": all_lxc,
        "connection_label": first.get("connection_label", ""),
        "connection_id": first.get("connection_id", ""),
    }
```

Add this new helper function (replaces the old inline logic):

```python
def _poll_single_connection(conn: dict) -> dict:
    """Poll one Proxmox connection and return a cluster result dict."""
    host = conn.get("host", "")
    creds = conn.get("credentials", {}) if isinstance(conn.get("credentials"), dict) else {}
    pve_user = creds.get("user", "")
    pve_token_name = creds.get("token_name", "")
    token_secret = creds.get("secret", "")
    conn_port = conn.get("port") or 8006
    port = conn_port if conn_port not in (0, None, 443) else 8006
    conn_label = conn.get("label", host)
    conn_id = str(conn.get("id", ""))
    conn_host = f"{host}:{port}"

    if not host:
        return {"health": "unconfigured", "vms": [], "lxc": [],
                "connection_label": conn_label, "connection_id": conn_id,
                "connection_host": conn_host}

    try:
        from proxmoxer import ProxmoxAPI
        prox = ProxmoxAPI(
            host, port=port,
            user=pve_user,
            token_name=pve_token_name,
            token_value=token_secret,
            verify_ssl=False,
            timeout=10,
        )

        nodes = [n["node"] for n in prox.nodes.get() if n.get("node")]
        if not nodes:
            nodes = [n.strip() for n in os.environ.get("PROXMOX_NODES", "").split(",") if n.strip()]
        if not nodes:
            return {"health": "error", "vms": [], "lxc": [],
                    "error": "No nodes returned from cluster",
                    "connection_label": conn_label, "connection_id": conn_id,
                    "connection_host": conn_host}

        vms = []
        lxc_list = []
        nodes_ok = 0

        for node in nodes:
            try:
                for vm in prox.nodes(node).qemu.get():
                    vms.append(_build_vm_card_proxmoxer(prox, node, vm))
                for ct in prox.nodes(node).lxc.get():
                    lxc_list.append(_build_lxc_card(node, ct))
                nodes_ok += 1
            except Exception as e:
                log.warning("Proxmox node %s error: %s", node, e)

        if nodes_ok == 0:
            return {"health": "error", "vms": [], "lxc": [],
                    "error": f"{conn_label} ({host}): No nodes responded",
                    "connection_label": conn_label, "connection_id": conn_id,
                    "connection_host": conn_host}

        all_items = vms + lxc_list
        if not all_items or all(v["dot"] == "green" for v in all_items):
            health = "healthy"
        elif all(v["dot"] == "red" for v in all_items):
            health = "critical"
        else:
            health = "degraded"

        return {
            "health": health,
            "vms": vms,
            "lxc": lxc_list,
            "connection_label": conn_label,
            "connection_id": conn_id,
            "connection_host": conn_host,
        }

    except Exception as e:
        log.error("ProxmoxVMsCollector error for %s: %s", conn_label, e)
        return {"health": "error", "vms": [], "lxc": [],
                "error": f"{conn_label} ({host}): {e}",
                "connection_label": conn_label, "connection_id": conn_id,
                "connection_host": conn_host}
```

Also update `to_entities()` to use the flat `vms`/`lxc` lists — it already
does this, so no change needed there.

---

## Change 3 — api/routers/dashboard.py: /vms endpoint

Update `get_vms()` to return `clusters` from the snapshot and per-cluster
connection metadata:

```python
@router.get("/vms")
async def get_vms(user: str = Depends(get_current_user)):
    """Proxmox VM and LXC list from latest snapshot. Supports multiple clusters."""
    async with get_engine().connect() as conn:
        snap = await q.get_latest_snapshot(conn, "proxmox_vms")

    state = _parse_state(snap)
    clusters = state.get("clusters", [])

    # If snapshot predates multi-cluster support (no clusters key),
    # synthesise a single-cluster response from the flat fields for compat.
    if not clusters and (state.get("vms") or state.get("lxc")):
        conn_label = state.get("connection_label", "Proxmox Cluster")
        conn_host = ""
        try:
            from api.connections import get_connection_for_platform
            pconn = get_connection_for_platform("proxmox")
            if pconn:
                conn_label = pconn.get("label", conn_label)
                conn_host = f"{pconn.get('host', '')}:{pconn.get('port', 8006)}"
        except Exception:
            pass
        clusters = [{
            "health": state.get("health", "unknown"),
            "connection_label": conn_label,
            "connection_id": state.get("connection_id", ""),
            "connection_host": conn_host,
            "vms": state.get("vms", []),
            "lxc": state.get("lxc", []),
        }]

    return {
        "clusters": clusters,
        # Keep flat lists for any code still using vms/lxc directly
        "vms": state.get("vms", []),
        "lxc": state.get("lxc", []),
        "health": state.get("health", "unknown"),
        # Legacy single-cluster fields — first cluster's values
        "connection_label": clusters[0].get("connection_label", "") if clusters else "",
        "connection_host": clusters[0].get("connection_host", "") if clusters else "",
        "last_updated": snap.get("timestamp") if snap else None,
    }
```

---

## Change 4 — gui/src/components/ServiceCards.jsx

Replace the single VMs Section block with a multi-cluster renderer.

Find the existing VMs block (starts with `{show('vms') && (() => {`).

Replace it entirely with:

```jsx
{/* VMs + LXC · Proxmox — one Section per cluster */}
{show('vms') && (() => {
  const clusters = vms?.clusters || []

  // Backward compat: if no clusters array, fall back to flat vms/lxc
  const clusterList = clusters.length > 0 ? clusters : (
    (vms?.vms?.length || vms?.lxc?.length)
      ? [{
          health: vms?.health,
          connection_label: vms?.connection_label || 'Proxmox Cluster',
          connection_host: vms?.connection_host || '',
          connection_id: '',
          vms: vms?.vms || [],
          lxc: vms?.lxc || [],
        }]
      : []
  )

  if (!clusterList.length) return null

  return clusterList.map((cluster, clusterIdx) => {
    const allItems = [...(cluster.vms || []), ...(cluster.lxc || [])]
    const filtered = applyProxmoxFilters(allItems, proxmoxFilters)
    const sorted   = sortProxmoxItems(filtered, sortBy, sortDir)
    const connLabel = cluster.connection_label || 'Proxmox Cluster'
    const connHost  = cluster.connection_host || ''
    const runningCount = allItems.filter(v => v.status === 'running').length
    const issues = allItems.filter(v => v.dot === 'red' || v.dot === 'amber').length
    const clusterDot = cluster.health === 'healthy' ? 'green'
                     : cluster.health === 'critical' ? 'red'
                     : cluster.health === 'error' ? 'red'
                     : issues > 0 ? 'amber' : 'green'

    return (
      <Section
        key={cluster.connection_id || clusterIdx}
        label={connLabel}
        dot={clusterDot}
        auth="API"
        host={connHost}
        runningCount={runningCount}
        totalCount={allItems.length}
        issueCount={issues}
        compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd}
        entityForCompare={{
          id: `cluster:proxmox:${connLabel}`,
          label: connLabel, platform: 'proxmox', section: 'COMPUTE',
          metadata: { host: connHost, running: runningCount, total: allItems.length, issues }
        }}
        filterBar={clusterIdx === 0 ? (
          <ProxmoxFilterBar
            items={allItems}
            filters={proxmoxFilters}
            setFilters={setProxmoxFilters}
            sort={{ sortBy, sortDir }}
            onSort={(by, dir) => { setSortBy(by); setSortDir(dir) }}
          />
        ) : null}
      >
        {sorted.length === 0 && allItems.length > 0 && (
          <div className="col-span-full text-[10px] text-gray-700 py-2">no items match filter</div>
        )}
        {sorted.filter(vm =>
          matchesShowFilter(vm.dot) || isPinned(`proxmox:${vm.name}:${vm.vmid}`)
        ).map(vm => (
          <InfraCard
            key={`${vm.type}-${vm.vmid}`}
            cardKey={`v-${cluster.connection_id || clusterIdx}-${vm.type}-${vm.vmid}`}
            openKey={openKey} setOpenKey={setOpenKey}
            dot={vm.dot}
            name={vm.name}
            sub={`${vm.type === 'lxc' ? 'CT' : 'VM'} ${vm.vmid} · ${vm.node}${vm.pool ? ` · ${vm.pool}` : ''}`}
            net={vm.ip || ''} uptime={vm.uptime || ''}
            collapsed={<ProxmoxCardCollapsed vm={vm} onEntityDetail={onEntityDetail} />}
            expanded={<ProxmoxCardExpanded vm={vm} onAction={load} confirm={confirm} showToast={showToast} />}
            compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd}
            entityForCompare={{
              id: `proxmox:${vm.name}:${vm.vmid}`,
              label: vm.name, platform: 'proxmox', section: 'COMPUTE',
              metadata: { vmid: vm.vmid, node: vm.node_api, type: vm.type, status: vm.status,
                          vcpus: vm.vcpus, maxmem_gb: vm.maxmem_gb, cpu_pct: vm.cpu_pct, dot: vm.dot }
            }}
          />
        ))}
      </Section>
    )
  })
})()}
```

Note: `ProxmoxFilterBar` only renders on the first cluster (`clusterIdx === 0`)
since all clusters share the same filter state. If you want per-cluster filters
in future, each cluster needs its own filter state — defer that.

---

## Commit & deploy

```bash
git add -A
git commit -m "feat(compute): multiple Proxmox connections → multiple COMPUTE cluster cards

- connections.py: add get_all_connections_for_platform() returning all enabled
  connections with decrypted creds (no LIMIT 1)
- proxmox_vms.py: _collect_sync() iterates all Proxmox connections, polls each
  via new _poll_single_connection(). State gains 'clusters' list; flat vms/lxc
  kept for backward compat with to_entities() and legacy readers
- dashboard.py /vms: returns 'clusters' array + synthesises single-cluster
  response from flat fields when snapshot predates this change
- ServiceCards.jsx: VMs section iterates clusters array, renders one Section
  per cluster. Falls back to flat vms/lxc for old snapshots"
git push origin main
# After CI green:
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env \
  up -d hp1_agent
```

---

## Test after deploy

Single-cluster case (current setup): COMPUTE section should look identical to
before — one PMOX CLUSTER KB card with all VMs.

Multi-cluster case (add a second Proxmox connection in Settings → Connections):
two separate cluster cards should appear under COMPUTE, each with their own
cluster header, VM grid, and dot color.
