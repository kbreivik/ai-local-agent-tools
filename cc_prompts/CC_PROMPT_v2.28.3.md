# CC PROMPT — v2.28.3 — Per-connection card template override

## What this does
Adds per-connection card template override in the Connections tab:
- "Customize card ▸" button on each vm_host/docker_host connection list item
- Opens CardTemplateEditor in a slide-down panel below the connection row
- Save → PUT /api/card-templates/connection/{connection_id}
- Reset → DELETE /api/card-templates/connection/{connection_id}
- Shows "◈ CUSTOM CARD" badge on connection list items with overrides
- Wires useCardTemplate hook to read per-connection override in ServiceCards
Version bump: 2.28.2 → 2.28.3

---

## Change 1 — gui/src/components/OptionsModal.jsx: per-connection template editor

### 1a — Add CardTemplateEditor import at top of OptionsModal.jsx (if not already added in v2.28.2)

Find the import block. If not already present, add:
```js
import CardTemplateEditor from './CardTemplateEditor'
import { CONTAINER_SCHEMA, SWARM_SERVICE_SCHEMA, DEFAULT_TEMPLATES } from '../schemas/cardSchemas'
```

### 1b — Add cardTemplate state to ConnectionsTab

FIND (exact — last state declaration in ConnectionsTab before the fetching code):
```js
  const [rotationModal, setRotationModal] = useState(null)  // {profileId, profileName, newCreds}
```

REPLACE WITH:
```js
  const [rotationModal, setRotationModal] = useState(null)  // {profileId, profileName, newCreds}
  const [templateEditId, setTemplateEditId] = useState(null)       // connection id being edited
  const [connectionTemplates, setConnectionTemplates] = useState({}) // {conn_id: {has_override, template}}
```

### 1c — Add fetchConnectionTemplates function in ConnectionsTab

Find the `fetchProfiles` function in ConnectionsTab. Add after it:

```js
  const fetchConnectionTemplates = async (connIds) => {
    const results = {}
    await Promise.allSettled(
      connIds.map(async id => {
        try {
          const r = await fetch(`${BASE}/api/card-templates/connection/${id}`, { headers: authHeaders() })
          if (r.ok) results[id] = await r.json()
        } catch { /* silent */ }
      })
    )
    setConnectionTemplates(results)
  }
```

And update the useEffect that calls fetchConns/fetchProfiles to also call fetchConnectionTemplates:

FIND (exact):
```js
  useEffect(() => { fetchConns(); fetchProfiles() }, [])
```

REPLACE WITH:
```js
  useEffect(() => {
    fetchConns().then?.(all => {
      if (all) {
        const templateTargets = all.filter(c => ['vm_host', 'docker_host', 'windows'].includes(c.platform)).map(c => c.id)
        fetchConnectionTemplates(templateTargets)
      }
    })
    fetchProfiles()
  }, [])
```

NOTE for CC: fetchConns currently doesn't return a value. Add `return all` to fetchConns so the
chaining works. If that's too complex, alternatively call fetchConnectionTemplates inside fetchConns
after the setConns call.

### 1d — Add "Customize card" button to connection list items

Find the connection list item action buttons row in ConnectionsTab. Currently has Edit/Copy/Test/⏸/✕.

FIND (exact — the right-side action buttons for each connection):
```jsx
              <div className="flex gap-1" style={{ flexShrink: 0 }}>
                <button className="btn text-[9px] px-1.5 py-0.5" onClick={() => startEdit(c)}>Edit</button>
                <button onClick={() => duplicateConn(c)} title="Duplicate connection" className="btn text-[9px] px-1.5 py-0.5" style={{ color: 'var(--text-3)' }}>Copy</button>
```

REPLACE WITH:
```jsx
              <div className="flex gap-1" style={{ flexShrink: 0 }}>
                <button className="btn text-[9px] px-1.5 py-0.5" onClick={() => startEdit(c)}>Edit</button>
                <button onClick={() => duplicateConn(c)} title="Duplicate connection" className="btn text-[9px] px-1.5 py-0.5" style={{ color: 'var(--text-3)' }}>Copy</button>
                {['vm_host', 'docker_host', 'windows'].includes(c.platform) && (
                  <button
                    onClick={() => setTemplateEditId(templateEditId === c.id ? null : c.id)}
                    title="Customize card template for this connection"
                    className="btn text-[9px] px-1.5 py-0.5"
                    style={{ color: connectionTemplates[c.id]?.has_override ? 'var(--cyan)' : 'var(--text-3)' }}>
                    ◈
                  </button>
                )}
```

### 1e — Add CUSTOM CARD badge to connection list items

Find the badge row in the connection list item (where BASTION, INLINE CREDS etc. badges show).
Add a badge for connections with template overrides:

FIND (exact — last badge before the closing div of the badge row):
```jsx
                {c.config?.os_type && <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2, background: 'var(--bg-3)', color: 'var(--text-3)' }}>{c.config.os_type}</span>}
```

REPLACE WITH:
```jsx
                {c.config?.os_type && <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2, background: 'var(--bg-3)', color: 'var(--text-3)' }}>{c.config.os_type}</span>}
                {connectionTemplates[c.id]?.has_override && (
                  <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2,
                    background: 'rgba(0,200,238,0.1)', color: 'var(--cyan)' }}>◈ CUSTOM CARD</span>
                )}
```

### 1f — Render CardTemplateEditor inline when templateEditId matches

Find the connection list rendering map. After each connection item's closing `</div>`, add
the inline template editor:

The connection list renders items inside `{items.map(c => { ... return <div key={c.id} ...>...</div> })}`.

After the closing `</div>` of each connection item but before the map closing `})}`, add:

```jsx
            {/* Inline card template editor for this connection */}
            {templateEditId === c.id && (() => {
              const cardType = c.platform === 'docker_host' ? 'container' : 'vm_host'
              // Map cardType to schema — both use container schema for now
              const schema = CONTAINER_SCHEMA
              const connTemplate = connectionTemplates[c.id]
              const initialTemplate = connTemplate?.template || DEFAULT_TEMPLATES['container'] || {}

              return (
                <div style={{ margin: '4px 0 8px 0', padding: '10px', background: 'var(--bg-2)',
                  border: '1px solid var(--cyan)', borderRadius: 2 }}>
                  <div style={{ fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--cyan)',
                    marginBottom: 8, letterSpacing: 0.5 }}>
                    CUSTOM CARD TEMPLATE — {c.label || c.host}
                  </div>
                  <CardTemplateEditor
                    cardType="container"
                    schema={schema}
                    initialTemplate={initialTemplate}
                    onSave={async (template) => {
                      const r = await fetch(`${BASE}/api/card-templates/connection/${c.id}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json', ...authHeaders() },
                        body: JSON.stringify({ template }),
                      })
                      if (r.ok) {
                        setTemplateEditId(null)
                        fetchConnectionTemplates([c.id])
                        // Invalidate the hook cache for this connection
                        const { invalidateCardTemplateCache } = await import('../hooks/useCardTemplate')
                        invalidateCardTemplateCache(c.id)
                      }
                    }}
                    onCancel={() => setTemplateEditId(null)}
                  />
                  {connTemplate?.has_override && (
                    <button
                      onClick={async () => {
                        await fetch(`${BASE}/api/card-templates/connection/${c.id}`, {
                          method: 'DELETE', headers: authHeaders(),
                        })
                        setTemplateEditId(null)
                        fetchConnectionTemplates([c.id])
                        const { invalidateCardTemplateCache } = await import('../hooks/useCardTemplate')
                        invalidateCardTemplateCache(c.id)
                      }}
                      style={{ marginTop: 8, fontSize: 9, color: 'var(--red)', background: 'none',
                        border: '1px solid var(--red)', borderRadius: 2, padding: '3px 10px', cursor: 'pointer' }}>
                      ↺ Reset to type default
                    </button>
                  )}
                </div>
              )
            })()}
```

---

## Change 2 — gui/src/components/ServiceCards.jsx: wire useCardTemplate for containers

This wires the per-connection template from the hook so that cards with a connection override
actually use the custom template.

NOTE for CC: The container card currently uses `DEFAULT_TEMPLATES.container` directly (added in v2.28.0).
Replace with `useCardTemplate` where each container card is rendered.

The approach: since hooks can't be called in map callbacks, create a wrapper component
`ConnectedContainerCard` that calls `useCardTemplate` for its specific connection:

Add before the containers_local map:

```jsx
function ConnectedContainerCard({ c, isSwarm, onAction, confirm, showToast, onTagsLoaded, onTab, openKeys, setOpenKeys, lastOpenedKey, setLastOpenedKey, expandAllFlag, entityId, onEntityDetail, compareMode, compareSet, onCompareAdd, entityForCompare }) {
  const template = useCardTemplate('container', c.connection_id || null)
  return (
    <InfraCard
      cardKey={`c-${c.id}`}
      openKeys={openKeys} setOpenKeys={setOpenKeys}
      lastOpenedKey={lastOpenedKey} setLastOpenedKey={setLastOpenedKey}
      forceExpanded={expandAllFlag}
      dot={c.dot}
      name={c.name || c.id?.slice(0, 12) || '(unknown)'}
      headerSub={(() => { const parts = (c.image || '').split('/'); return parts[parts.length - 1] || '' })()}
      entityId={entityId}
      onEntityDetail={onEntityDetail}
      collapsed={<ContainerCardCollapsed c={c} template={template} state={{ tags: [] }} />}
      expanded={<ContainerCardExpanded
        c={c} isSwarm={isSwarm} onAction={onAction} confirm={confirm} showToast={showToast}
        onTagsLoaded={onTagsLoaded} onTab={onTab} template={template}
      />}
      compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd}
      entityForCompare={entityForCompare}
    />
  )
}
```

Then FIND in the containers_local map where InfraCard is rendered for each container and
replace with `<ConnectedContainerCard key={c.id} c={c} ... />` passing all the same props.

---

## Version bump
Update VERSION: 2.28.2 → 2.28.3

## Commit
```bash
git add -A
git commit -m "feat(ui): v2.28.3 per-connection card template override in Connections tab"
git push origin main
```
