# CC PROMPT — v2.29.5 — fix(ui): filter bar vertical centering + revert wrong ProxmoxCard centering

## What this does
Two targeted fixes in `gui/src/components/ServiceCards.jsx`. Vertically centres the
filter bar chips inside the Section header Row 2. Reverts the incorrect centering applied
to the collapsed Proxmox VM/LXC card content (vCPU/RAM line and badges row) in a prior
commit. Version bump: v2.29.4 → v2.29.5

## Change 1 — gui/src/components/ServiceCards.jsx — Section filterBar row vertical centering

In the `Section` component, Row 2 renders the filterBar inside a plain div that has no
vertical flex alignment, causing the chips to sit at the top of the row instead of the
middle. Add `display: 'flex'` and `alignItems: 'center'` to that wrapper div.

Find this exact line:

```jsx
          <div style={{ flex: 1, overflow: 'visible', padding: '6px 10px', position: 'relative' }}>{filterBar}</div>
```

Replace with:

```jsx
          <div style={{ flex: 1, overflow: 'visible', padding: '6px 10px', position: 'relative', display: 'flex', alignItems: 'center' }}>{filterBar}</div>
```

## Change 2 — gui/src/components/ServiceCards.jsx — revert wrong ProxmoxCardCollapsed centering

A previous commit added `textAlign: 'center'` to the vCPU/RAM line and `justify-center`
to the badges row inside `ProxmoxCardCollapsed`. This is wrong — every other card type is
left-aligned. Revert both.

Find this exact block:

```jsx
      <div style={{
        textAlign: 'center', fontSize: 10,
        color: 'var(--text-3)', marginBottom: 4,
        fontFamily: 'var(--font-mono)',
      }}>
        {vm.vcpus} vCPU · {vm.maxmem_gb} GB RAM
      </div>
      <div className="flex items-center justify-center gap-1.5">
```

Replace with:

```jsx
      <div style={{
        fontSize: 10,
        color: 'var(--text-3)', marginBottom: 4,
        fontFamily: 'var(--font-mono)',
      }}>
        {vm.vcpus} vCPU · {vm.maxmem_gb} GB RAM
      </div>
      <div className="flex items-center justify-start gap-1.5">
```

## Version bump
Update `VERSION` in `api/constants.py`: `v2.29.4` → `v2.29.5`

## Commit
```
git add -A
git commit -m "fix(ui): v2.29.5 filter bar vertical centering + revert wrong ProxmoxCard centering"
git push origin main
```
