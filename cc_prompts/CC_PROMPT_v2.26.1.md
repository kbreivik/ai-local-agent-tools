# CC PROMPT — v2.26.1 — Universal entity buttons in InfraCard + VM entity ID fix

## What this does
Moves the entity detail (›) and agent ask (⌘) buttons into InfraCard itself, driven by
an `entityId` prop. All 8 card types (VMs, LXCs, containers, swarm services, external
services, UniFi, PBS, TrueNAS, FortiGate) automatically get both buttons whenever the
card data carries entity_id (set by v2.26.0). Also fixes the VM entity ID bug (qemu→vm)
by using vm.entity_id directly instead of hand-constructing the string.
Version bump: v2.26.0 → v2.26.1

## Architecture note
InfraCard renders ⌘ and › in the header row right side (always visible, even when
expanded). Both buttons call onEntityDetail(entityId) — EntityDrawer shows entity info
and the Ask/chat section. Per-type entity buttons removed from collapsed components.

---

## Change 1 — gui/src/components/ServiceCards.jsx

### 1a — InfraCard: add entityId + onEntityDetail props, render buttons in header

FIND (exact — the InfraCard function signature):
```
function InfraCard({ cardKey, openKeys, setOpenKeys, lastOpenedKey, setLastOpenedKey, forceExpanded, dot, name, sub, net, uptime, collapsed, expanded, compareMode, compareSet, onCompareAdd, entityForCompare }) {
```

REPLACE WITH:
```
function InfraCard({ cardKey, openKeys, setOpenKeys, lastOpenedKey, setLastOpenedKey, forceExpanded, dot, name, sub, net, uptime, collapsed, expanded, compareMode, compareSet, onCompareAdd, entityForCompare, entityId, onEntityDetail }) {
```

### 1b — InfraCard: add entity buttons to header row

FIND (exact — the InfraCard header row JSX):
```
      {/* Header row — always visible, click to toggle */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 min-w-0">
          <Dot color={dot} />
          <span className="text-[12px] font-semibold truncate" style={{ color: 'var(--text-1)' }}>{name}</span>
          <span className="text-[10px]" style={{ color: 'var(--text-3)' }}>{isOpen ? '▾' : '▸'}</span>
        </div>
        {subText && <span className="text-[10px] mono shrink-0 ml-2" style={{ color: 'var(--text-3)' }}>{subText}</span>}
      </div>
```

REPLACE WITH:
```
      {/* Header row — always visible, click to toggle */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 min-w-0">
          <Dot color={dot} />
          <span className="text-[12px] font-semibold truncate" style={{ color: 'var(--text-1)' }}>{name}</span>
          <span className="text-[10px]" style={{ color: 'var(--text-3)' }}>{isOpen ? '▾' : '▸'}</span>
        </div>
        <div className="flex items-center gap-0 shrink-0 ml-1" onClick={e => e.stopPropagation()}>
          {entityId && onEntityDetail && (
            <>
              <button
                onClick={e => { e.stopPropagation(); onEntityDetail(entityId) }}
                title="Ask agent about this entity"
                style={{ color: 'var(--amber)', background: 'none', border: 'none',
                         cursor: 'pointer', fontSize: 10, padding: '1px 3px',
                         opacity: 0.65, lineHeight: 1 }}
              >⌘</button>
              <button
                onClick={e => { e.stopPropagation(); onEntityDetail(entityId) }}
                title="Entity detail"
                style={{ color: 'var(--cyan)', background: 'none', border: 'none',
                         cursor: 'pointer', fontSize: 10, padding: '1px 3px', lineHeight: 1 }}
              >›</button>
            </>
          )}
          {subText && <span className="text-[10px] mono ml-2" style={{ color: 'var(--text-3)' }}>{subText}</span>}
        </div>
      </div>
```

### 1c — ProxmoxCardCollapsed: fix entity ID (use vm.entity_id), remove old entity buttons

FIND (exact):
```
function ProxmoxCardCollapsed({ vm, onEntityDetail }) {
  const typeBadge = vm.type === 'lxc'
    ? <span className="text-[9px] px-1 py-px rounded bg-[#0a1a2a] text-cyan-600 border border-[#0d2030] mr-1">LXC</span>
    : <span className="text-[9px] px-1 py-px rounded bg-[#0d0a2a] text-violet-600 border border-[#1a1040] mr-1">VM</span>
  return (
    <>
      <div className="text-[10px] text-[#383850] mb-1">{vm.vcpus} vCPU · {vm.maxmem_gb} GB RAM</div>
      <div className="flex items-center">
        {vm.problem
          ? <div className="text-[10px] px-1.5 py-px rounded inline-flex items-center gap-1 bg-amber-950/40 text-amber-400 border border-amber-900/30">⚠ {vm.problem}</div>
          : <>{typeBadge}<span className="text-[9px] px-1.5 py-px rounded bg-[#0d1a2a] text-blue-400 border border-[#1a2a3a]">● {vm.status}</span></>}
        {vm.maintenance && (
          <span style={{
            fontSize: 7, fontFamily: 'var(--font-mono)', padding: '1px 4px',
            background: 'var(--amber-dim)', color: 'var(--amber)',
            borderRadius: 2, letterSpacing: 0.5, marginLeft: 4,
          }}>MAINT</span>
        )}
        {onEntityDetail && (
          <button
            className="text-[10px] px-1 py-px ml-auto"
            style={{ color: 'var(--cyan)', background: 'none', border: 'none', cursor: 'pointer' }}
            onClick={e => { e.stopPropagation(); onEntityDetail(`proxmox_vms:${vm.node_api}:${vm.type === 'lxc' ? 'lxc' : 'qemu'}:${vm.vmid}`) }}
            title="Entity detail"
          >›</button>
        )}
      </div>
    </>
  )
}
```

REPLACE WITH:
```
function ProxmoxCardCollapsed({ vm }) {
  const typeBadge = vm.type === 'lxc'
    ? <span className="text-[9px] px-1 py-px rounded bg-[#0a1a2a] text-cyan-600 border border-[#0d2030] mr-1">LXC</span>
    : <span className="text-[9px] px-1 py-px rounded bg-[#0d0a2a] text-violet-600 border border-[#1a1040] mr-1">VM</span>
  return (
    <>
      <div className="text-[10px] text-[#383850] mb-1">{vm.vcpus} vCPU · {vm.maxmem_gb} GB RAM</div>
      <div className="flex items-center">
        {vm.problem
          ? <div className="text-[10px] px-1.5 py-px rounded inline-flex items-center gap-1 bg-amber-950/40 text-amber-400 border border-amber-900/30">⚠ {vm.problem}</div>
          : <>{typeBadge}<span className="text-[9px] px-1.5 py-px rounded bg-[#0d1a2a] text-blue-400 border border-[#1a2a3a]">● {vm.status}</span></>}
        {vm.maintenance && (
          <span style={{
            fontSize: 7, fontFamily: 'var(--font-mono)', padding: '1px 4px',
            background: 'var(--amber-dim)', color: 'var(--amber)',
            borderRadius: 2, letterSpacing: 0.5, marginLeft: 4,
          }}>MAINT</span>
        )}
      </div>
    </>
  )
}
```

### 1d — ContainerCardCollapsed: remove entity button (InfraCard handles it now)

FIND (exact):
```
function ContainerCardCollapsed({ c, onEntityDetail }) {
  return (
    <div className="flex items-center gap-1">
      {c.problem && <div className="text-[10px] px-1.5 py-px rounded inline-flex items-center gap-1" style={{ background: 'var(--red-dim)', color: 'var(--red)' }}>⚠ {c.problem}</div>}
      {onEntityDetail && (
        <button
          className="text-[10px] px-1 py-px ml-auto"
          style={{ color: 'var(--cyan)', background: 'none', border: 'none', cursor: 'pointer' }}
          onClick={e => { e.stopPropagation(); onEntityDetail(`docker:${c.name || c.id}`) }}
          title="Entity detail"
        >›</button>
      )}
    </div>
  )
}
```

REPLACE WITH:
```
function ContainerCardCollapsed({ c }) {
  return (
    <div className="flex items-center gap-1">
      {c.problem && <div className="text-[10px] px-1.5 py-px rounded inline-flex items-center gap-1" style={{ background: 'var(--red-dim)', color: 'var(--red)' }}>⚠ {c.problem}</div>}
    </div>
  )
}
```

### 1e — ExternalCardCollapsed: remove entity button (InfraCard handles it now)

FIND (exact — the onEntityDetail button in ExternalCardCollapsed):
```
      {onEntityDetail && (
        <button
          className="text-[10px] px-1 py-px ml-auto"
          style={{ color: 'var(--cyan)', background: 'none', border: 'none', cursor: 'pointer' }}
          onClick={e => { e.stopPropagation(); onEntityDetail(`external_services:${svc.slug}`) }}
          title="Entity detail"
        >›</button>
      )}
```

REPLACE WITH (delete those lines — just remove them entirely):
```
```

Note: CC should remove the entire button block from ExternalCardCollapsed. The `onEntityDetail` prop on ExternalCardCollapsed can also be removed from the signature.

FIND (exact):
```
function ExternalCardCollapsed({ svc, onEntityDetail, compareMode, onCompareAdd }) {
```

REPLACE WITH:
```
function ExternalCardCollapsed({ svc, compareMode, onCompareAdd }) {
```

---

### 1f — ServiceCards export: add onEntityDetail to function signature (if not present)

The ServiceCards component already has `onEntityDetail` in its props. No change needed.

---

### 1g — InfraCard usages: add entityId + onEntityDetail props to every InfraCard call

For each InfraCard instantiation below, add `entityId` and `onEntityDetail` props.
Also remove `onEntityDetail` from the `collapsed` prop where it was passed to collapsed components.

#### Containers (local) — InfraCard for docker agent01 containers:

FIND (exact):
```
              collapsed={<ContainerCardCollapsed c={c} onEntityDetail={onEntityDetail} />}
              expanded={<ContainerCardExpanded
```

REPLACE WITH:
```
              collapsed={<ContainerCardCollapsed c={c} />}
              expanded={<ContainerCardExpanded
```

Also add entityId and onEntityDetail to this InfraCard call. FIND (exact — the full InfraCard props block for local containers):
```
              <InfraCard
                key={c.id} cardKey={`c-${c.id}`} openKeys={openKeys} setOpenKeys={setOpenKeys} lastOpenedKey={lastOpenedKey} setLastOpenedKey={setLastOpenedKey} forceExpanded={expandAllFlag}
                dot={c.dot} name={c.name || c.id?.slice(0, 12) || '(unknown)'} sub={_computeContainerSub(c, knownLatest)} net={_containerNet(c)} uptime={c.uptime}
                collapsed={<ContainerCardCollapsed c={c} />}
```

REPLACE WITH:
```
              <InfraCard
                key={c.id} cardKey={`c-${c.id}`} openKeys={openKeys} setOpenKeys={setOpenKeys} lastOpenedKey={lastOpenedKey} setLastOpenedKey={setLastOpenedKey} forceExpanded={expandAllFlag}
                dot={c.dot} name={c.name || c.id?.slice(0, 12) || '(unknown)'} sub={_computeContainerSub(c, knownLatest)} net={_containerNet(c)} uptime={c.uptime}
                entityId={c.entity_id} onEntityDetail={onEntityDetail}
                collapsed={<ContainerCardCollapsed c={c} />}
```

#### Swarm services — InfraCard for swarm services:

FIND (exact):
```
                collapsed={<ContainerCardCollapsed c={s} />}
                expanded={<ContainerCardExpanded c={{ ...s }} isSwarm={true} onAction={load} confirm={confirm} showToast={showToast} onTab={onTab} />}
```

No change needed for collapsed (already no onEntityDetail). Add entityId+onEntityDetail to InfraCard call.

FIND (exact — the swarm InfraCard key line):
```
              <InfraCard
                key={s.id || s.name} cardKey={`s-${s.id || s.name}`} openKeys={openKeys} setOpenKeys={setOpenKeys} lastOpenedKey={lastOpenedKey} setLastOpenedKey={setLastOpenedKey} forceExpanded={expandAllFlag}
                dot={s.dot || 'green'} name={s.name} sub={s.image} net={s.ports?.[0] ? _compactPort(s.ports[0]) : ''}
```

REPLACE WITH:
```
              <InfraCard
                key={s.id || s.name} cardKey={`s-${s.id || s.name}`} openKeys={openKeys} setOpenKeys={setOpenKeys} lastOpenedKey={lastOpenedKey} setLastOpenedKey={setLastOpenedKey} forceExpanded={expandAllFlag}
                dot={s.dot || 'green'} name={s.name} sub={s.image} net={s.ports?.[0] ? _compactPort(s.ports[0]) : ''}
                entityId={s.entity_id} onEntityDetail={onEntityDetail}
```

#### VM/LXC cards — InfraCard for Proxmox VMs:

FIND (exact):
```
                    collapsed={<ProxmoxCardCollapsed vm={vm} onEntityDetail={onEntityDetail} />}
```

REPLACE WITH:
```
                    collapsed={<ProxmoxCardCollapsed vm={vm} />}
```

Also add entityId to the Proxmox InfraCard. FIND (exact):
```
                    dot={vm.dot}
                    name={vm.name}
                    sub={`${vm.type === 'lxc' ? 'CT' : 'VM'} ${vm.vmid} · ${vm.node}${vm.pool ? ` · ${vm.pool}` : ''}`}
                    net={vm.ip || ''} uptime={vm.uptime || ''}
                    collapsed={<ProxmoxCardCollapsed vm={vm} />}
```

REPLACE WITH:
```
                    dot={vm.dot}
                    name={vm.name}
                    sub={`${vm.type === 'lxc' ? 'CT' : 'VM'} ${vm.vmid} · ${vm.node}${vm.pool ? ` · ${vm.pool}` : ''}`}
                    net={vm.ip || ''} uptime={vm.uptime || ''}
                    entityId={vm.entity_id} onEntityDetail={onEntityDetail}
                    collapsed={<ProxmoxCardCollapsed vm={vm} />}
```

#### External services — InfraCard:

FIND (exact):
```
                collapsed={<ExternalCardCollapsed svc={svc} onEntityDetail={onEntityDetail} compareMode={compareMode} onCompareAdd={onCompareAdd} />}
```

REPLACE WITH:
```
                collapsed={<ExternalCardCollapsed svc={svc} compareMode={compareMode} onCompareAdd={onCompareAdd} />}
```

Also add entityId to the External InfraCard. FIND (exact — the external InfraCard key line):
```
              <InfraCard
                key={svc.slug} cardKey={`e-${svc.slug}`} openKeys={openKeys} setOpenKeys={setOpenKeys} lastOpenedKey={lastOpenedKey} setLastOpenedKey={setLastOpenedKey} forceExpanded={expandAllFlag}
                dot={svc.dot} name={svc.name} sub={svc.service_type} net={svc.host_port}
```

REPLACE WITH:
```
              <InfraCard
                key={svc.slug} cardKey={`e-${svc.slug}`} openKeys={openKeys} setOpenKeys={setOpenKeys} lastOpenedKey={lastOpenedKey} setLastOpenedKey={setLastOpenedKey} forceExpanded={expandAllFlag}
                dot={svc.dot} name={svc.name} sub={svc.service_type} net={svc.host_port}
                entityId={svc.entity_id} onEntityDetail={onEntityDetail}
```

#### UniFi device cards — InfraCard:

FIND (exact — the unifi InfraCard key line):
```
                  <InfraCard
                    key={dev.mac || dev.name}
                    cardKey={`unifi-${dev.mac || dev.name}`}
                    openKeys={openKeys} setOpenKeys={setOpenKeys} lastOpenedKey={lastOpenedKey} setLastOpenedKey={setLastOpenedKey} forceExpanded={expandAllFlag}
                    dot={devDot}
                    name={dev.name}
                    sub={`${dev.type_label} · ${dev.model}`}
                    net={_displayIp(dev.ip) || ''}
                    uptime={uptimeFmt}
```

REPLACE WITH:
```
                  <InfraCard
                    key={dev.mac || dev.name}
                    cardKey={`unifi-${dev.mac || dev.name}`}
                    openKeys={openKeys} setOpenKeys={setOpenKeys} lastOpenedKey={lastOpenedKey} setLastOpenedKey={setLastOpenedKey} forceExpanded={expandAllFlag}
                    dot={devDot}
                    name={dev.name}
                    sub={`${dev.type_label} · ${dev.model}`}
                    net={_displayIp(dev.ip) || ''}
                    uptime={uptimeFmt}
                    entityId={dev.entity_id} onEntityDetail={onEntityDetail}
```

#### PBS datastore cards — InfraCard:

FIND (exact — the pbs InfraCard key line):
```
                  <InfraCard
                    key={ds.name}
                    cardKey={`pbs-${ds.name}`}
                    openKeys={openKeys} setOpenKeys={setOpenKeys} lastOpenedKey={lastOpenedKey} setLastOpenedKey={setLastOpenedKey} forceExpanded={expandAllFlag}
                    dot={dsDot}
                    name={ds.name}
                    sub={`${Math.round(pct)}% used`}
                    net={''}
                    uptime={`${ds.total_gb} GB`}
```

REPLACE WITH:
```
                  <InfraCard
                    key={ds.name}
                    cardKey={`pbs-${ds.name}`}
                    openKeys={openKeys} setOpenKeys={setOpenKeys} lastOpenedKey={lastOpenedKey} setLastOpenedKey={setLastOpenedKey} forceExpanded={expandAllFlag}
                    dot={dsDot}
                    name={ds.name}
                    sub={`${Math.round(pct)}% used`}
                    net={''}
                    uptime={`${ds.total_gb} GB`}
                    entityId={ds.entity_id} onEntityDetail={onEntityDetail}
```

#### TrueNAS pool cards — InfraCard:

FIND (exact — the truenas InfraCard key line):
```
                  <InfraCard
                    key={pool.name}
                    cardKey={`truenas-${pool.name}`}
                    openKeys={openKeys} setOpenKeys={setOpenKeys} lastOpenedKey={lastOpenedKey} setLastOpenedKey={setLastOpenedKey} forceExpanded={expandAllFlag}
                    dot={poolDot}
                    name={pool.name}
                    sub={`${Math.round(pct)}% used`}
                    net={''}
                    uptime={`${pool.size_gb} GB`}
```

REPLACE WITH:
```
                  <InfraCard
                    key={pool.name}
                    cardKey={`truenas-${pool.name}`}
                    openKeys={openKeys} setOpenKeys={setOpenKeys} lastOpenedKey={lastOpenedKey} setLastOpenedKey={setLastOpenedKey} forceExpanded={expandAllFlag}
                    dot={poolDot}
                    name={pool.name}
                    sub={`${Math.round(pct)}% used`}
                    net={''}
                    uptime={`${pool.size_gb} GB`}
                    entityId={pool.entity_id} onEntityDetail={onEntityDetail}
```

#### FortiGate interface cards — InfraCard:

FIND (exact — the fortigate InfraCard key line):
```
                  <InfraCard
                    key={iface.name}
                    cardKey={`fg-${iface.name}`}
                    openKeys={openKeys} setOpenKeys={setOpenKeys} lastOpenedKey={lastOpenedKey} setLastOpenedKey={setLastOpenedKey} forceExpanded={expandAllFlag}
                    dot={ifDot}
                    name={label}
                    sub={`${iface.type || ''} ${speed ? '· ' + speed : ''}`.trim()}
                    net={iface.ip || ''}
                    uptime={''}
```

REPLACE WITH:
```
                  <InfraCard
                    key={iface.name}
                    cardKey={`fg-${iface.name}`}
                    openKeys={openKeys} setOpenKeys={setOpenKeys} lastOpenedKey={lastOpenedKey} setLastOpenedKey={setLastOpenedKey} forceExpanded={expandAllFlag}
                    dot={ifDot}
                    name={label}
                    sub={`${iface.type || ''} ${speed ? '· ' + speed : ''}`.trim()}
                    net={iface.ip || ''}
                    uptime={''}
                    entityId={iface.entity_id} onEntityDetail={onEntityDetail}
```

---

## Version bump
Update VERSION: 2.26.0 → 2.26.1

---

## Commit
```bash
git add -A
git commit -m "feat(ui): v2.26.1 universal entity ⌘/› buttons in InfraCard + VM entity ID fix"
git push origin main
```
