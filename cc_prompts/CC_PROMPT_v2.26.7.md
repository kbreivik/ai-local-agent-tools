# CC PROMPT — v2.26.7 — VM Hosts: entity_id, to_entities(), ⌘/› buttons, naming fix, onEntityDetail threading

## What this does
Four coordinated changes that wire VM Hosts into the entity detail + ask system:
1. `vm_hosts.py`: stamp `entity_id = label` on every VM card dict; add `to_entities()` to
   `VMHostsCollector` so the entity-by-ID endpoint can find vm_host entities (uses bare label
   as entity_id — consistent with existing entity_history records)
2. `VMHostsSection.jsx`: add `⌘` (ask) and `›` (entity detail) buttons to `VMCard` header;
   thread `onEntityDetail` prop from `VMHostsSection` down to each `VMCard`
3. `App.jsx`: pass `onEntityDetail={onEntityClick}` to `VMHostsSection`
4. `DashboardLayout.jsx`: add `TILE_DISPLAY_NAMES` map; render "VM Hosts" instead of "VM_HOSTS"
   (and clean up other tile names: "PLATFORM" → "Platform" etc.)
Version bump: v2.26.6 → v2.26.7

---

## Change 1 — api/collectors/vm_hosts.py

### 1a — Stamp entity_id on each VM card (success path)

FIND (exact):
```
        result = _parse_poll_output(output, label, host)
        result["connection_id"] = str(conn.get("id", ""))
        result["config"] = cfg
        result["jump_via_label"] = next(
```

REPLACE WITH:
```
        result = _parse_poll_output(output, label, host)
        result["connection_id"] = str(conn.get("id", ""))
        result["config"] = cfg
        result["entity_id"] = label  # bare label — matches entity_history records
        result["jump_via_label"] = next(
```

### 1b — Stamp entity_id on error return

FIND (exact):
```
        return {
            "id": label, "label": label, "host": host,
            "connection_id": str(conn.get("id", "")),
            "config": cfg,
            "dot": "red", "problem": str(e)[:120],
```

REPLACE WITH:
```
        return {
            "id": label, "label": label, "host": host,
            "entity_id": label,
            "connection_id": str(conn.get("id", "")),
            "config": cfg,
            "dot": "red", "problem": str(e)[:120],
```

### 1c — Add to_entities() to VMHostsCollector

FIND (exact — the end of _collect_sync, last two lines):
```
        health = "healthy" if red == 0 else ("degraded" if ok > 0 else "error")
        return {"health": health, "vms": vms, "total": total, "ok": ok, "issues": red}
```

REPLACE WITH:
```
        health = "healthy" if red == 0 else ("degraded" if ok > 0 else "error")
        return {"health": health, "vms": vms, "total": total, "ok": ok, "issues": red}

    def to_entities(self, state: dict):
        """Return one Entity per polled VM host.

        entity_id = bare label (e.g. 'ds-docker-worker-01') — intentionally no prefix,
        kept consistent with entity_history records written by the collector.
        """
        from api.collectors.base import Entity
        _DOT_STATUS = {"green": "healthy", "amber": "degraded", "red": "error", "grey": "unknown"}
        entities = []
        for vm in state.get("vms", []):
            label = vm.get("label") or vm.get("id") or "unknown"
            disks = vm.get("disks", [])
            max_disk_pct = max((d.get("usage_pct", 0) for d in disks), default=0)
            entities.append(Entity(
                id=label,
                label=label,
                component=self.component,
                platform="vm_host",
                section="COMPUTE",
                status=_DOT_STATUS.get(vm.get("dot", "grey"), "unknown"),
                last_error=vm.get("problem"),
                metadata={
                    "host":           vm.get("host", ""),
                    "os":             vm.get("os", ""),
                    "kernel":         vm.get("kernel", ""),
                    "mem_pct":        vm.get("mem_pct"),
                    "load_1":         vm.get("load_1"),
                    "docker_version": vm.get("docker_version", ""),
                    "uptime_fmt":     vm.get("uptime_fmt", ""),
                    "max_disk_pct":   max_disk_pct,
                }
            ))
        return entities if entities else super().to_entities(state)
```

---

## Change 2 — gui/src/components/VMHostsSection.jsx

### 2a — Add onEntityDetail to VMCard signature

FIND (exact):
```
function VMCard({ vm, onAction }) {
```

REPLACE WITH:
```
function VMCard({ vm, onAction, onEntityDetail }) {
```

### 2b — Add ⌘ and › buttons in VMCard header (before the collapse arrow)

FIND (exact — the collapse arrow at the end of the header row):
```
        <span style={{ fontSize: 8, color: 'var(--text-3)', transform: open ? 'rotate(90deg)' : 'none', display: 'inline-block', transition: 'transform 0.1s' }}>▶</span>
```

REPLACE WITH:
```
        {entityId && onEntityDetail && (
          <>
            <button
              onClick={e => { e.stopPropagation(); onEntityDetail(entityId) }}
              title="Ask agent about this host"
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                fontSize: 10, padding: '1px 3px', color: 'var(--amber)',
                opacity: 0.65, lineHeight: 1, flexShrink: 0,
              }}
            >⌘</button>
            <button
              onClick={e => { e.stopPropagation(); onEntityDetail(entityId) }}
              title="Entity detail"
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                fontSize: 10, padding: '1px 3px', color: 'var(--cyan)',
                opacity: 0.65, lineHeight: 1, flexShrink: 0,
              }}
            >›</button>
          </>
        )}
        <span style={{ fontSize: 8, color: 'var(--text-3)', transform: open ? 'rotate(90deg)' : 'none', display: 'inline-block', transition: 'transform 0.1s' }}>▶</span>
```

### 2c — Add onEntityDetail to VMHostsSection signature

FIND (exact):
```
export default function VMHostsSection({ showFilter }) {
```

REPLACE WITH:
```
export default function VMHostsSection({ showFilter, onEntityDetail }) {
```

### 2d — Pass onEntityDetail to each VMCard

FIND (exact):
```
      {visible.map(vm => <VMCard key={vm.label || vm.host} vm={vm} onAction={refreshSummary} />)}
```

REPLACE WITH:
```
      {visible.map(vm => <VMCard key={vm.label || vm.host} vm={vm} onAction={refreshSummary} onEntityDetail={onEntityDetail} />)}
```

---

## Change 3 — gui/src/App.jsx

### 3a — Pass onEntityDetail to VMHostsSection in DashboardView

FIND (exact):
```
    VM_HOSTS: showSection('COMPUTE') ? (
      summaryLoading ? <SkeletonGrid count={5} /> :
      <VMHostsSection showFilter={showFilter} />
    ) : null,
```

REPLACE WITH:
```
    VM_HOSTS: showSection('COMPUTE') ? (
      summaryLoading ? <SkeletonGrid count={5} /> :
      <VMHostsSection showFilter={showFilter} onEntityDetail={onEntityClick} />
    ) : null,
```

---

## Change 4 — gui/src/components/DashboardLayout.jsx

### 4a — Add TILE_DISPLAY_NAMES map

FIND (exact):
```
const TILE_META = {
  PLATFORM:   { icon: '⬡', badge: 'INTERNAL' },
  COMPUTE:    { icon: '◈', badge: 'HYPERVISORS' },
  CONTAINERS: { icon: '⊟', badge: 'DOCKER' },
  NETWORK:    { icon: '◉', badge: 'INFRA' },
  STORAGE:    { icon: '⊠', badge: 'DATA' },
  SECURITY:   { icon: '⊛', badge: 'SOC' },
  VM_HOSTS:   { icon: '⬢', badge: 'NODES' },
}
```

REPLACE WITH:
```
const TILE_META = {
  PLATFORM:   { icon: '⬡', badge: 'INTERNAL' },
  COMPUTE:    { icon: '◈', badge: 'HYPERVISORS' },
  CONTAINERS: { icon: '⊟', badge: 'DOCKER' },
  NETWORK:    { icon: '◉', badge: 'INFRA' },
  STORAGE:    { icon: '⊠', badge: 'DATA' },
  SECURITY:   { icon: '⊛', badge: 'SOC' },
  VM_HOSTS:   { icon: '⬢', badge: 'NODES' },
}

// Human-readable display names for tile headers (key → label)
const TILE_DISPLAY_NAMES = {
  PLATFORM:   'Platform',
  COMPUTE:    'Compute',
  CONTAINERS: 'Containers',
  NETWORK:    'Network',
  STORAGE:    'Storage',
  SECURITY:   'Security',
  VM_HOSTS:   'VM Hosts',
}
```

### 4b — Use TILE_DISPLAY_NAMES in Tile header render

FIND (exact):
```
        <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 11, color: 'var(--text-1)', letterSpacing: 0.5 }}>
          {name}
        </span>
```

REPLACE WITH:
```
        <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 11, color: 'var(--text-1)', letterSpacing: 0.5 }}>
          {TILE_DISPLAY_NAMES[name] || name}
        </span>
```

---

## Version bump
Update VERSION: 2.26.6 → 2.26.7

## Commit
```bash
git add -A
git commit -m "feat(vm-hosts): v2.26.7 entity_id, to_entities(), ask/detail buttons, naming fix"
git push origin main
```
