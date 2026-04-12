# CC PROMPT — v2.15.8 — Multi-expand cards + shift-click range + toolbar toggles

## What this does

Currently only one card can be open at a time (`openKey` single value).
This implements:
1. Multiple cards expanded simultaneously — `openKeys` Set replaces `openKey` string
2. Shift+click range expand — click one card, shift+click another, all between expand
3. VM cards narrower default min-width (240px instead of 300px)
4. Drill bar: "expand all / collapse all" toggle for cards
5. Drill bar: "expand all / collapse all" toggle for sections

Version bump: 2.15.7 → 2.15.8 (feature, x.x.1)

---

## Change 1 — ServiceCards.jsx: openKeys Set replaces openKey string

### 1a — Replace state

```jsx
// BEFORE:
const [openKey, setOpenKey] = useState(null)

// AFTER:
const [openKeys, setOpenKeys] = useState(new Set())
const [lastOpenedKey, setLastOpenedKey] = useState(null)  // for shift-click range
const [orderedKeys, setOrderedKeys] = useState([])        // rendered order for range
```

### 1b — Update all InfraCard usages

Every `InfraCard` call currently passes `openKey` and `setOpenKey`.
Replace with:

```jsx
// Pass to InfraCard:
openKeys={openKeys}
setOpenKeys={setOpenKeys}
lastOpenedKey={lastOpenedKey}
setLastOpenedKey={setLastOpenedKey}
orderedKeys={orderedKeys}
cardOrder={/* index of this card in the rendered list */}
```

For each Section render loop, pass the index:
```jsx
{sorted.map((vm, idx) => (
  <InfraCard
    key={...}
    cardKey={`v-...`}
    openKeys={openKeys}
    setOpenKeys={setOpenKeys}
    lastOpenedKey={lastOpenedKey}
    setLastOpenedKey={setLastOpenedKey}
    cardIndex={idx}
    sectionKey={`cluster-${cluster.connection_id || clusterIdx}`}
    ...
  />
))}
```

### 1c — Update InfraCard component signature

```jsx
function InfraCard({
  cardKey, openKeys, setOpenKeys, lastOpenedKey, setLastOpenedKey,
  cardIndex, sectionKey,
  dot, name, sub, net, uptime, collapsed, expanded,
  compareMode, compareSet, onCompareAdd, entityForCompare
}) {
  const isOpen = (openKeys || new Set()).has(cardKey)
  const anyOpen = (openKeys || new Set()).size > 0
  const dimmed = false  // No dimming when multiple can be open

  const toggle = (e) => {
    if ((e.ctrlKey || e.metaKey) && compareMode && entityForCompare && onCompareAdd) {
      e.stopPropagation()
      onCompareAdd(entityForCompare)
      return
    }

    if (e.shiftKey && lastOpenedKey && sectionKey) {
      // Shift+click: expand range between lastOpenedKey and this cardKey
      // Find the rendered order from the DOM data-card-order attributes
      const section = e.currentTarget.closest('[data-section-key]')
      if (section) {
        const cards = [...section.querySelectorAll('[data-card-key]')]
        const keys = cards.map(el => el.getAttribute('data-card-key'))
        const lastIdx = keys.indexOf(lastOpenedKey)
        const thisIdx = keys.indexOf(cardKey)
        if (lastIdx >= 0 && thisIdx >= 0) {
          const [from, to] = lastIdx < thisIdx ? [lastIdx, thisIdx] : [thisIdx, lastIdx]
          const rangeKeys = keys.slice(from, to + 1)
          setOpenKeys(prev => {
            const next = new Set(prev)
            rangeKeys.forEach(k => next.add(k))
            return next
          })
          return
        }
      }
    }

    // Normal click: toggle this card
    setOpenKeys(prev => {
      const next = new Set(prev)
      if (next.has(cardKey)) {
        next.delete(cardKey)
      } else {
        next.add(cardKey)
        setLastOpenedKey?.(cardKey)
      }
      return next
    })
  }

  return (
    <div
      data-card-key={cardKey}
      data-section-key={sectionKey}
      className={`border rounded-lg cursor-pointer transition-all ${isOpen ? 'border-violet-500 ...' : ''}`}
      ...
      onClick={toggle}
    >
      ...
    </div>
  )
}
```

### 1d — Wrap each Section's grid in a data-section-key div

In the `Section` component's children grid:
```jsx
<div
  className="grid gap-2"
  data-section-key={label}   // or pass sectionKey prop
  style={{ ... }}
>
  {children}
</div>
```

---

## Change 2 — DrillDownBar: expand/collapse all toggles

In `App.jsx`, update `DrillDownBar` to accept expand/collapse callbacks and add
two new toggle buttons after the COMPARE toggle.

### 2a — Add props to DrillDownBar

```jsx
function DrillDownBar({
  ...existing props...,
  onExpandAllCards, onCollapseAllCards,      // NEW
  onExpandAllSections, onCollapseAllSections, // NEW
  allCardsExpanded, allSectionsExpanded,     // NEW
}) {
```

### 2b — Add buttons in DrillDownBar render

After the COMPARE toggle block, add:

```jsx
{/* Card expand/collapse toggle */}
<div style={{ width: 1, height: 20, background: 'var(--border)', flexShrink: 0 }} />
<button
  onClick={allCardsExpanded ? onCollapseAllCards : onExpandAllCards}
  title={allCardsExpanded ? 'Collapse all cards' : 'Expand all cards'}
  style={{
    padding: '2px 8px', fontSize: 9, fontFamily: 'var(--font-mono)', flexShrink: 0,
    background: allCardsExpanded ? 'var(--accent-dim)' : 'transparent',
    color: allCardsExpanded ? 'var(--accent)' : 'var(--text-3)',
    border: `1px solid ${allCardsExpanded ? 'var(--accent)' : 'var(--border)'}`,
    borderRadius: 2, cursor: 'pointer',
  }}
>
  {allCardsExpanded ? '⊟ COLLAPSE' : '⊞ EXPAND'}
</button>

{/* Section expand/collapse toggle */}
<button
  onClick={allSectionsExpanded ? onCollapseAllSections : onExpandAllSections}
  title={allSectionsExpanded ? 'Collapse all sections' : 'Expand all sections'}
  style={{
    padding: '2px 8px', fontSize: 9, fontFamily: 'var(--font-mono)', flexShrink: 0,
    background: allSectionsExpanded ? 'rgba(0,200,238,0.1)' : 'transparent',
    color: allSectionsExpanded ? 'var(--cyan)' : 'var(--text-3)',
    border: `1px solid ${allSectionsExpanded ? 'var(--cyan)' : 'var(--border)'}`,
    borderRadius: 2, cursor: 'pointer',
  }}
>
  {allSectionsExpanded ? '⊟ SECTIONS' : '⊞ SECTIONS'}
</button>
```

### 2c — Wire expand/collapse in DashboardView

In `DashboardView`, add state and pass event emitters to both DrillDownBar and
ServiceCards via a shared context or event system.

The simplest approach: use window custom events so DrillDownBar can signal ServiceCards
without prop drilling through DashboardLayout.

In `DashboardView`:
```jsx
const [allCardsExpanded, setAllCardsExpanded] = useState(false)
const [allSectionsExpanded, setAllSectionsExpanded] = useState(true)

const onExpandAllCards = () => {
  setAllCardsExpanded(true)
  window.dispatchEvent(new CustomEvent('ds:expand-all-cards'))
}
const onCollapseAllCards = () => {
  setAllCardsExpanded(false)
  window.dispatchEvent(new CustomEvent('ds:collapse-all-cards'))
}
const onExpandAllSections = () => {
  setAllSectionsExpanded(true)
  window.dispatchEvent(new CustomEvent('ds:expand-all-sections'))
}
const onCollapseAllSections = () => {
  setAllSectionsExpanded(false)
  window.dispatchEvent(new CustomEvent('ds:collapse-all-sections'))
}
```

In `ServiceCards.jsx`, listen for the events:
```jsx
useEffect(() => {
  const expandAll = () => {
    // Collect all current card keys and open them all
    // We don't know all keys ahead of time, so we use a flag
    setExpandAllFlag(true)
    setOpenKeys(new Set())  // will be filled by flag
  }
  const collapseAll = () => {
    setOpenKeys(new Set())
    setExpandAllFlag(false)
  }
  window.addEventListener('ds:expand-all-cards', expandAll)
  window.addEventListener('ds:collapse-all-cards', collapseAll)
  return () => {
    window.removeEventListener('ds:expand-all-cards', expandAll)
    window.removeEventListener('ds:collapse-all-cards', collapseAll)
  }
}, [])
```

Add `expandAllFlag` state — when true, every InfraCard renders expanded regardless
of `openKeys`. Pass it as `forceExpanded` prop to InfraCard:

```jsx
// In InfraCard:
const isOpen = forceExpanded || (openKeys || new Set()).has(cardKey)
```

For sections, `Section` component already manages its own `expanded` state.
Listen for the section events in `Section`:
```jsx
useEffect(() => {
  const onExpand = () => setSectionExpanded(true)
  const onCollapse = () => setSectionExpanded(false)
  window.addEventListener('ds:expand-all-sections', onExpand)
  window.addEventListener('ds:collapse-all-sections', onCollapse)
  return () => {
    window.removeEventListener('ds:expand-all-sections', onExpand)
    window.removeEventListener('ds:collapse-all-sections', onCollapse)
  }
}, [])
```

---

## Change 3 — Narrower VM card default

In `useOptions` / `OptionsContext`, the default `cardMinWidth` is 300. VMs look
better at a narrower default. Change the default to 240px specifically for VM cards.

In `ServiceCards.jsx`, pass a narrower minWidth for VM/Proxmox cards:

```jsx
// In Section for VMs, override the min width via inline style or a prop:
<Section
  label={connLabel}
  ...
  cardMinWidth={240}  // NEW prop — overrides global setting for this section
>
```

In `Section` component, accept and apply:
```jsx
function Section({ ..., cardMinWidth }) {
  const { cardMinWidth: globalMin, cardMaxWidth } = useOptions()
  const _min = cardMinWidth ?? globalMin ?? 240  // VM sections default to 240
  ...
}
```

---

## Version bump

Update VERSION: `2.15.7` → `2.15.8`

---

## Commit

```bash
git add -A
git commit -m "feat(ui): v2.15.8 multi-expand cards + shift-click range + toolbar toggles

- openKeys Set replaces openKey single value — multiple cards open simultaneously
- Shift+click: expands range between last-opened and clicked card (within section)
- DrillDownBar: EXPAND/COLLAPSE ALL cards button + EXPAND/COLLAPSE ALL sections button
- Window custom events: ds:expand-all-cards, ds:collapse-all-sections etc
- forceExpanded prop on InfraCard for expand-all mode
- VM card min-width: 240px default (was 300px) — more cards visible per row
- Section component listens for expand/collapse section events"
git push origin main
```
