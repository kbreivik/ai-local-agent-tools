# CC PROMPT — v2.28.1 — Settings → Appearance tab + Naming entity alias editor

## What this does
Two settings UI changes:
1. Rename 'Display' tab → 'Appearance' throughout (TABS array, Sidebar.jsx, exports)
2. Add entity alias editor to NamingTab: table of known containers/services, each row
   shows origin name + editable alias field + save/reset buttons; fetches entities from
   /api/discovery/devices and /api/connections to build the entity list; persists via
   /api/display-aliases
Version bump: 2.28.0 → 2.28.1

---

## Change 1 — gui/src/components/OptionsModal.jsx: rename Display → Appearance

### 1a — TABS array

FIND (exact):
```js
export const TABS = ['General', 'Infrastructure', 'AI Services', 'Connections', 'Allowlist', 'Permissions', 'Access', 'Naming', 'Display', 'Notifications', 'Layouts']
```

REPLACE WITH:
```js
export const TABS = ['General', 'Infrastructure', 'AI Services', 'Connections', 'Allowlist', 'Permissions', 'Access', 'Naming', 'Appearance', 'Notifications', 'Layouts']
```

### 1b — Tab render condition in modal

FIND (exact):
```jsx
{tab === 'Display'        && <DisplayTab        draft={draft} update={update} />}
```

REPLACE WITH:
```jsx
{tab === 'Appearance'     && <DisplayTab        draft={draft} update={update} />}
```

### 1c — Named exports at bottom

FIND (exact):
```js
export { GeneralTab, InfrastructureTab, AIServicesTab, ConnectionsTab, AllowlistTab, PermissionsTab, AccessTab, NamingTab, DisplayTab, UpdateStatus }
```

REPLACE WITH:
```js
export { GeneralTab, InfrastructureTab, AIServicesTab, ConnectionsTab, AllowlistTab, PermissionsTab, AccessTab, NamingTab, DisplayTab, UpdateStatus }
// Alias for SettingsPage import compatibility
export { DisplayTab as AppearanceTab }
```

---

## Change 2 — gui/src/components/SettingsPage.jsx: update import + tab routing

### 2a — Import line

FIND (exact):
```js
import {
  GeneralTab, InfrastructureTab, AIServicesTab,
  ConnectionsTab, PermissionsTab, AccessTab, NamingTab,
  DisplayTab, NotificationsTab, UpdateStatus, TABS,
} from './OptionsModal'
```

REPLACE WITH:
```js
import {
  GeneralTab, InfrastructureTab, AIServicesTab,
  ConnectionsTab, PermissionsTab, AccessTab, NamingTab,
  DisplayTab, NotificationsTab, UpdateStatus, TABS,
} from './OptionsModal'
```

NOTE: No change needed in SettingsPage imports since DisplayTab is still exported.
But find the tab rendering in SettingsPage and update the condition:

FIND (exact — the tab routing in SettingsPage render):
```jsx
{tab === 'Display'    && <DisplayTab       draft={draft} update={update} />}
```

REPLACE WITH:
```jsx
{(tab === 'Appearance' || tab === 'Display') && <DisplayTab draft={draft} update={update} />}
```

---

## Change 3 — gui/src/components/Sidebar.jsx: rename Display to Appearance

FIND (exact):
```js
    { key: 'Settings',  icon: '⊞', label: 'Display', settingsTab: 'Display' },
```

REPLACE WITH:
```js
    { key: 'Settings',  icon: '⊞', label: 'Appearance', settingsTab: 'Appearance' },
```

---

## Change 4 — gui/src/components/OptionsModal.jsx: expand NamingTab with entity alias editor

Find the NamingTab function. It currently has platform name/short-code/pattern fields.
Add an entity alias editor section BELOW the existing Live Preview block.

FIND (exact — the closing div of NamingTab):
```jsx
      {/* Live preview */}
      <div style={{ marginTop: 12, padding: '10px 12px', background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 2 }}>
        <div style={{ fontSize: 8, fontFamily: 'var(--font-mono)', color: 'var(--text-3)', letterSpacing: 1, marginBottom: 6 }}>LIVE PREVIEW</div>
        {[
          ['Platform name', name],
          ['Agent #1', resolve(agentPat)],
          ['Agent #2', resolve(agentPat).replace('01', '02')],
          ['Database', resolve(dbName)],
          ['Memory store', resolve(memName)],
          ['Tagline', tagline],
        ].map(([label, val]) => (
          <div key={label} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0', fontSize: 10 }}>
            <span style={{ color: 'var(--text-3)' }}>{label}</span>
            <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--cyan)' }}>{val || '—'}</span>
          </div>
        ))}
      </div>
    </div>
```

REPLACE WITH:
```jsx
      {/* Live preview */}
      <div style={{ marginTop: 12, padding: '10px 12px', background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 2 }}>
        <div style={{ fontSize: 8, fontFamily: 'var(--font-mono)', color: 'var(--text-3)', letterSpacing: 1, marginBottom: 6 }}>LIVE PREVIEW</div>
        {[
          ['Platform name', name],
          ['Agent #1', resolve(agentPat)],
          ['Agent #2', resolve(agentPat).replace('01', '02')],
          ['Database', resolve(dbName)],
          ['Memory store', resolve(memName)],
          ['Tagline', tagline],
        ].map(([label, val]) => (
          <div key={label} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0', fontSize: 10 }}>
            <span style={{ color: 'var(--text-3)' }}>{label}</span>
            <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--cyan)' }}>{val || '—'}</span>
          </div>
        ))}
      </div>

      {/* ── Entity Display Aliases ─────────────────────────────────────────── */}
      <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
        <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 700,
          color: 'var(--text-2)', letterSpacing: 1, marginBottom: 6 }}>
          ENTITY DISPLAY ALIASES
        </div>
        <p style={{ fontSize: 9, color: 'var(--text-3)', marginBottom: 10 }}>
          Set a custom display name for any container or connection. The alias is shown in
          Platform Core and card headers. If cleared, the original name is restored automatically.
        </p>
        <EntityAliasEditor />
      </div>
      {/* ── end Entity Display Aliases ─────────────────────────────────────── */}
    </div>
```

---

## Change 5 — gui/src/components/OptionsModal.jsx: add EntityAliasEditor component

Add this component BEFORE the NamingTab function definition (or near other helper functions
in the file):

```jsx
function EntityAliasEditor() {
  const [aliases, setAliases] = useState({})    // {entity_id: alias}
  const [origins, setOrigins] = useState({})    // {entity_id: origin}
  const [entities, setEntities] = useState([])  // [{entity_id, origin, type}]
  const [edits, setEdits] = useState({})        // {entity_id: draft alias value}
  const [saving, setSaving] = useState({})
  const [loading, setLoading] = useState(true)

  const fetchAliases = async () => {
    try {
      const r = await fetch(`${BASE}/api/display-aliases`, { headers: authHeaders() })
      const d = await r.json()
      const aliasMap = {}
      const originMap = {}
      for (const a of (d.aliases || [])) {
        aliasMap[a.entity_id] = a.alias
        originMap[a.entity_id] = a.origin
      }
      setAliases(aliasMap)
      setOrigins(originMap)
    } catch { /* silent */ }
  }

  const fetchEntities = async () => {
    setLoading(true)
    const collected = []
    try {
      // Docker containers from summary
      const r = await fetch(`${BASE}/api/dashboard/containers`, { headers: authHeaders() })
      if (r.ok) {
        const d = await r.json()
        for (const c of (d.containers || [])) {
          if (c.name) collected.push({
            entity_id: `docker:${c.name}`,
            origin: c.name,
            type: 'container',
            detail: c.image?.split('/').pop() || '',
          })
        }
      }
    } catch { /* silent */ }
    try {
      // Connections (vm_host, windows)
      const r = await fetch(`${BASE}/api/connections?platform=vm_host`, { headers: authHeaders() })
      if (r.ok) {
        const d = await r.json()
        for (const c of (d.data || [])) {
          collected.push({
            entity_id: `connection:${c.id}`,
            origin: c.label || c.host,
            type: 'vm_host',
            detail: c.host,
          })
        }
      }
    } catch { /* silent */ }
    setEntities(collected)
    setLoading(false)
  }

  useEffect(() => {
    fetchAliases()
    fetchEntities()
  }, [])

  const saveAlias = async (entityId, origin) => {
    const alias = (edits[entityId] ?? aliases[entityId] ?? '').trim()
    if (!alias) return clearAlias(entityId)
    if (alias === origin) return clearAlias(entityId)  // same as origin = no alias needed
    setSaving(s => ({ ...s, [entityId]: true }))
    try {
      await fetch(`${BASE}/api/display-aliases/${encodeURIComponent(entityId)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ alias, origin }),
      })
      await fetchAliases()
      setEdits(e => { const n = { ...e }; delete n[entityId]; return n })
    } catch { /* silent */ }
    setSaving(s => ({ ...s, [entityId]: false }))
  }

  const clearAlias = async (entityId) => {
    setSaving(s => ({ ...s, [entityId]: true }))
    try {
      await fetch(`${BASE}/api/display-aliases/${encodeURIComponent(entityId)}`, {
        method: 'DELETE', headers: authHeaders(),
      })
      await fetchAliases()
      setEdits(e => { const n = { ...e }; delete n[entityId]; return n })
    } catch { /* silent */ }
    setSaving(s => ({ ...s, [entityId]: false }))
  }

  if (loading) return <div style={{ fontSize: 9, color: 'var(--text-3)' }}>Loading entities…</div>
  if (entities.length === 0) return (
    <div style={{ fontSize: 9, color: 'var(--text-3)' }}>
      No entities discovered. Run a harvest in the Discovered view or check connections.
    </div>
  )

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto auto', gap: '4px 8px',
        marginBottom: 4, fontSize: 8, fontFamily: 'var(--font-mono)', color: 'var(--text-3)',
        letterSpacing: 0.5, padding: '0 2px' }}>
        <span>ORIGINAL NAME</span><span>DISPLAY ALIAS</span><span></span><span></span>
      </div>
      {entities.map(({ entity_id, origin, type, detail }) => {
        const currentAlias = aliases[entity_id] || ''
        const draftAlias = edits[entity_id] ?? currentAlias
        const hasOverride = !!currentAlias && currentAlias !== origin
        const isDirty = draftAlias !== currentAlias
        return (
          <div key={entity_id} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto auto',
            gap: '0 8px', alignItems: 'center', marginBottom: 5 }}>
            <div>
              <div style={{ fontSize: 10, color: 'var(--text-1)', fontFamily: 'var(--font-mono)' }}>{origin}</div>
              {detail && <div style={{ fontSize: 8, color: 'var(--text-3)' }}>{type} · {detail}</div>}
            </div>
            <input
              value={draftAlias}
              onChange={e => setEdits(ed => ({ ...ed, [entity_id]: e.target.value }))}
              placeholder={origin}
              style={{ background: 'var(--bg-2)', border: `1px solid ${isDirty ? 'var(--amber)' : 'var(--border)'}`,
                borderRadius: 2, padding: '3px 8px', fontSize: 10, color: 'var(--text-1)',
                fontFamily: 'var(--font-mono)', outline: 'none' }}
            />
            <button
              onClick={() => saveAlias(entity_id, origin)}
              disabled={!isDirty || saving[entity_id]}
              style={{ fontSize: 9, padding: '3px 8px', borderRadius: 2, cursor: 'pointer',
                background: isDirty ? 'var(--accent-dim)' : 'var(--bg-3)',
                color: isDirty ? 'var(--accent)' : 'var(--text-3)',
                border: `1px solid ${isDirty ? 'var(--accent)' : 'var(--border)'}`,
                opacity: (!isDirty || saving[entity_id]) ? 0.5 : 1 }}>
              {saving[entity_id] ? '…' : 'Save'}
            </button>
            {hasOverride && (
              <button
                onClick={() => clearAlias(entity_id)}
                disabled={saving[entity_id]}
                title={`Reset to: ${origin}`}
                style={{ fontSize: 9, padding: '3px 6px', borderRadius: 2, cursor: 'pointer',
                  background: 'none', border: 'none', color: 'var(--red)', opacity: saving[entity_id] ? 0.5 : 1 }}>
                ↺
              </button>
            )}
            {!hasOverride && <span />}
          </div>
        )
      })}
    </div>
  )
}
```

---

## Version bump
Update VERSION: 2.28.0 → 2.28.1

## Commit
```bash
git add -A
git commit -m "feat(settings): v2.28.1 rename Display→Appearance, entity alias editor in Naming tab"
git push origin main
```
