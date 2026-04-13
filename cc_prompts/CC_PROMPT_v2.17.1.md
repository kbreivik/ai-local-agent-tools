# CC PROMPT — v2.17.1 — Fix Proxmox noVNC console URL

## What this does

The Proxmox VM card already has "Open Console" and "View in Proxmox" buttons in
`ProxmoxCardExpanded`. Both use `location.hostname` to build the URL, which resolves
to the DEATHSTAR host (192.168.199.10) — not the Proxmox host. The URL ends up as
`https://192.168.199.10:8006/?console=kvm&...` which is wrong and fails silently.

This passes the actual Proxmox connection host and port down to `ProxmoxCardExpanded`
so both buttons open the correct Proxmox UI.

Version bump: 2.17.0 → 2.17.1

---

## Change 1 — gui/src/components/ServiceCards.jsx

### 1a — Update ProxmoxCardExpanded signature

Find:
```jsx
function ProxmoxCardExpanded({ vm, onAction, confirm, showToast }) {
```

Replace with:
```jsx
function ProxmoxCardExpanded({ vm, proxmoxHost, proxmoxPort, onAction, confirm, showToast }) {
```

### 1b — Add console helper and fix button URLs

Inside `ProxmoxCardExpanded`, before the `return (` statement, find the line:
```jsx
  const isLxc = vm.type === 'lxc'
```

After that line, add:
```jsx
  const _pxHost = proxmoxHost || location.hostname
  const _pxPort = proxmoxPort || 8006
  const _pxBase = `https://${_pxHost}:${_pxPort}`
  const openConsole = (type) =>
    window.open(`${_pxBase}/?console=${type}&vmid=${vm.vmid}&node=${vm.node_api}&novnc=1`, '_blank')
```

### 1c — Fix the console and "View in Proxmox" button onClick handlers

Find:
```jsx
        vm.status === 'stopped'
          ? [
            <ActionBtn key="start" label={isLxc ? 'Start Container' : 'Start VM'} variant="urgent" loading={loading.start} onClick={() => act('start', 'start', null)} />,
            <ActionBtn key="proxmox" label="View in Proxmox" onClick={() => window.open(`https://${location.hostname}:8006`, '_blank')} />,
          ]
          : [
            !isLxc && <ActionBtn key="console" label="Open Console" onClick={() => window.open(`https://${location.hostname}:8006/?console=kvm&vmid=${vm.vmid}&node=${vm.node_api}&novnc=1`, '_blank')} />,
            isLxc && <ActionBtn key="console" label="Open Console" onClick={() => window.open(`https://${location.hostname}:8006/?console=lxc&vmid=${vm.vmid}&node=${vm.node_api}&novnc=1`, '_blank')} />,
            <ActionBtn key="proxmox" label="View in Proxmox" onClick={() => window.open(`https://${location.hostname}:8006`, '_blank')} />,
```

Replace with:
```jsx
        vm.status === 'stopped'
          ? [
            <ActionBtn key="start" label={isLxc ? 'Start Container' : 'Start VM'} variant="urgent" loading={loading.start} onClick={() => act('start', 'start', null)} />,
            <ActionBtn key="proxmox" label="View in Proxmox" onClick={() => window.open(_pxBase, '_blank')} />,
          ]
          : [
            !isLxc && <ActionBtn key="console" label="Open Console" onClick={() => openConsole('kvm')} />,
            isLxc && <ActionBtn key="console" label="Open Console" onClick={() => openConsole('lxc')} />,
            <ActionBtn key="proxmox" label="View in Proxmox" onClick={() => window.open(_pxBase, '_blank')} />,
```

### 1d — Pass proxmoxHost and proxmoxPort from the cluster render loop

In the cluster map (the `clusterList.map((cluster, clusterIdx) => {` block), find
the existing `<ProxmoxCardExpanded ...>` render:

```jsx
                    expanded={<ProxmoxCardExpanded vm={vm} onAction={load} confirm={confirm} showToast={showToast} />}
```

Replace with:
```jsx
                    expanded={<ProxmoxCardExpanded vm={vm} proxmoxHost={cluster.connection_host} proxmoxPort={cluster.connection_port || 8006} onAction={load} confirm={confirm} showToast={showToast} />}
```

---

## Do NOT touch

- `ProxmoxCardCollapsed` — no changes
- `InfraCard` — no changes  
- Any backend files
- Any other component

---

## Version bump

Update `VERSION`: `2.17.0` → `2.17.1`

---

## Commit

```bash
git add -A
git commit -m "fix(ui): v2.17.1 Proxmox noVNC console URL uses actual Proxmox host

- ProxmoxCardExpanded: accept proxmoxHost + proxmoxPort props
- _pxBase built from proxmoxHost:proxmoxPort, falls back to location.hostname:8006
- openConsole() helper uses correct host for kvm and lxc console URLs
- View in Proxmox button also corrected to use _pxBase
- Props passed from cluster.connection_host + cluster.connection_port in cluster map"
git push origin main
```
