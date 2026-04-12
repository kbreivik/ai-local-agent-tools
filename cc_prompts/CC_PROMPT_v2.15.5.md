# CC PROMPT — v2.15.5 — Layouts tab fix + admin menu cleanup + footer styling

## What this does

Three UI fixes found during testing:
1. Layouts tab renders blank — likely API endpoint missing or layoutState prop not passed
2. Admin user menu shows Layouts + Notifications shortcuts — these already exist in the
   Settings sidebar, so the menu should only show Log out (keep it clean)
3. Footer `admin · v2.15.4` is hard to read — needs distinct background + larger font

Version bump: 2.15.4 → 2.15.5 (UI fixes, x.x.1)

---

## Fix 1 — Layouts tab blank page

### 1a — Check if /api/layout/templates endpoint exists

In `api/routers/` or `api/main.py`, find whether there is a `layout/templates` route.
If it does NOT exist, add it. Create `api/routers/layout.py`:

```python
from fastapi import APIRouter, Depends
from api.auth import get_current_user

router = APIRouter(prefix="/api/layout", tags=["layout"])

DEFAULT_TEMPLATES = [
    {
        "name": "Default",
        "system": True,
        "description": "Standard layout — all sections vertical",
        "layout": {
            "template": "default",
            "rows": [
                {"tiles": ["PLATFORM"], "flex": [1], "heightMode": "auto"},
                {"tiles": ["COMPUTE", "CONTAINERS"], "flex": [1, 1], "heightMode": "auto"},
                {"tiles": ["NETWORK", "STORAGE"], "flex": [1, 1], "heightMode": "auto"},
                {"tiles": ["SECURITY", "VM_HOSTS"], "flex": [1, 1], "heightMode": "auto"},
            ],
            "collapsed": [],
        }
    },
    {
        "name": "Compute Focus",
        "system": True,
        "description": "Compute + VMs prominent, infra secondary",
        "layout": {
            "template": "compute_focus",
            "rows": [
                {"tiles": ["PLATFORM"], "flex": [1], "heightMode": "auto"},
                {"tiles": ["COMPUTE"], "flex": [1], "heightMode": "auto"},
                {"tiles": ["VM_HOSTS"], "flex": [1], "heightMode": "auto"},
                {"tiles": ["CONTAINERS", "NETWORK", "STORAGE", "SECURITY"], "flex": [1, 1, 1, 1], "heightMode": "auto"},
            ],
            "collapsed": [],
        }
    },
    {
        "name": "Network Focus",
        "system": True,
        "description": "Network + Security prominent",
        "layout": {
            "template": "network_focus",
            "rows": [
                {"tiles": ["PLATFORM"], "flex": [1], "heightMode": "auto"},
                {"tiles": ["NETWORK", "SECURITY"], "flex": [2, 1], "heightMode": "auto"},
                {"tiles": ["COMPUTE", "CONTAINERS", "STORAGE", "VM_HOSTS"], "flex": [1, 1, 1, 1], "heightMode": "auto"},
            ],
            "collapsed": [],
        }
    },
    {
        "name": "Wide",
        "system": True,
        "description": "All sections in one tall column",
        "layout": {
            "template": "wide",
            "rows": [
                {"tiles": ["PLATFORM", "COMPUTE"], "flex": [1, 2], "heightMode": "auto"},
                {"tiles": ["CONTAINERS", "VM_HOSTS"], "flex": [1, 2], "heightMode": "auto"},
                {"tiles": ["NETWORK", "STORAGE", "SECURITY"], "flex": [1, 1, 1], "heightMode": "auto"},
            ],
            "collapsed": [],
        }
    },
]

@router.get("/templates")
async def get_layout_templates(_: str = Depends(get_current_user)):
    """Return available layout templates."""
    return {"data": DEFAULT_TEMPLATES}

@router.get("/user")
async def get_user_layout(user: str = Depends(get_current_user)):
    """Get saved layout for the current user (from DB or default)."""
    # Try to load from DB (future enhancement)
    # For now return empty (client uses its own localStorage/default)
    return {"layout": None}

@router.post("/user")
async def save_user_layout(req: dict, user: str = Depends(get_current_user)):
    """Save layout for the current user."""
    # Future: persist to DB per-user
    return {"status": "ok", "message": "Layout saved"}
```

Register in `api/main.py`:
```python
from api.routers.layout import router as layout_router
app.include_router(layout_router)
```

### 1b — Check LayoutsTab.jsx props

In `SettingsPage.jsx`, the `LayoutsTab` is rendered as:
```jsx
{tab === 'Layouts' && <LayoutsTab layout={layoutState.layout} dirty={layoutState.dirty} saveLayout={layoutState.saveLayout} applyTemplate={layoutState.applyTemplate} setLayout={layoutState.setLayout} />}
```

The `layoutState` prop is passed from `AppShell` through `SettingsPage`. Verify:
1. `SettingsPage` receives `layoutState` as a prop — look at how it's passed in `AppShell`
2. `layoutState` has `.layout`, `.dirty`, `.saveLayout`, `.applyTemplate`, `.setLayout`
3. If any are undefined, the component crashes silently

In `App.jsx`, `AppShell` passes to `SettingsPage`:
```jsx
<SettingsPage initialTab={settingsTab} layoutState={layoutState} />
```

And `SettingsPage` must accept and pass it:
```jsx
export default function SettingsPage({ initialTab, layoutState }) {
  ...
  {tab === 'Layouts' && <LayoutsTab
    layout={layoutState?.layout}
    dirty={layoutState?.dirty}
    saveLayout={layoutState?.saveLayout}
    applyTemplate={layoutState?.applyTemplate}
    setLayout={layoutState?.setLayout}
  />}
}
```

Add null guards (`?.`) throughout LayoutsTab for the `layout` prop:
```jsx
// In LayoutsTab, guard all layout accesses:
const rows = layout?.rows || []
const collapsed = layout?.collapsed || []
```

Also in LayoutsTab, the CURRENT LAYOUT section and ACTIONS section should render
even if `templates` is empty or still loading. Wrap in try-catch if needed.

---

## Fix 2 — Admin user menu: remove Layouts + Notifications, keep only Log out

In `gui/src/components/Sidebar.jsx`, find the user menu popup items array:

```jsx
{[
  { icon: '⊞', label: 'Layouts', action: ... },
  { icon: '◈', label: 'Notifications', action: ... },
  { divider: true },
  { icon: '⏻', label: 'Log out', action: ..., style: { color: 'var(--red)' } },
].map(...)}
```

Replace with just Log out — Layouts and Notifications are already in the Settings sidebar:

```jsx
{[
  { icon: '⏻', label: 'Log out', action: () => { onLogout?.(); setUserMenuOpen(false) }, style: { color: 'var(--red)' } },
].map((item, i) => (
  <button key={i} onClick={item.action} style={{
    display: 'flex', alignItems: 'center', gap: 8, width: '100%',
    padding: '6px 12px', background: 'none', border: 'none',
    color: item.style?.color || 'var(--text-2)', cursor: 'pointer',
    fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: 0.5, textAlign: 'left',
  }}
  onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-3)'}
  onMouseLeave={e => e.currentTarget.style.background = 'none'}
  >
    <span style={{ width: 14, textAlign: 'center' }}>{item.icon}</span>
    {item.label}
  </button>
))}
```

The `onLayoutsTab` and `onNotificationsTab` props can remain on Sidebar for now
(they're harmless if unused) but remove them from the NAV in `Sidebar.jsx` if
Layouts and Notifications are already in the SETTINGS section of NAV.

---

## Fix 3 — Footer: distinct background + larger font for admin · v2.15.4

In `Sidebar.jsx`, find the footer trigger button (the `admin · v2.15.4` row):

```jsx
<button onClick={() => !collapsed && setUserMenuOpen(o => !o)} style={{
  width: '100%', display: 'flex', alignItems: 'center',
  gap: 6, padding: collapsed ? '8px 0' : '8px 12px',
  justifyContent: collapsed ? 'center' : 'flex-start',
  background: userMenuOpen ? 'var(--bg-2)' : 'none',
  border: 'none', cursor: collapsed ? 'default' : 'pointer',
}}>
```

Update with a distinct background and larger text:

```jsx
<button onClick={() => !collapsed && setUserMenuOpen(o => !o)} style={{
  width: '100%', display: 'flex', alignItems: 'center',
  gap: 6, padding: collapsed ? '10px 0' : '10px 12px',
  justifyContent: collapsed ? 'center' : 'flex-start',
  background: userMenuOpen
    ? 'var(--accent-dim)'
    : 'rgba(160,24,40,0.06)',    // subtle crimson tint — distinct from sidebar bg
  borderTop: '1px solid var(--border)',
  border: 'none', cursor: collapsed ? 'default' : 'pointer',
  transition: 'background 0.1s',
}}>
  <span style={{
    width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
    background: health?.status === 'ok' ? 'var(--green)' : 'var(--red)',
    boxShadow: health?.status === 'ok' ? '0 0 4px var(--green)' : '0 0 4px var(--red)',
  }} />
  {!collapsed && (
    <>
      <span style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 10,                    // up from 8
        color: 'var(--text-2)',          // brighter than var(--text-3)
        whiteSpace: 'nowrap', flex: 1,
        letterSpacing: 0.3,
      }}>
        {username || 'admin'} · <span style={{ color: 'var(--accent)' }}>v{health?.version || '—'}</span>
      </span>
      <span style={{ fontSize: 9, color: 'var(--text-3)' }}>{userMenuOpen ? '▾' : '▴'}</span>
    </>
  )}
</button>
```

The version number is highlighted in accent red, username in brighter text,
background has a subtle crimson tint so the footer stands out from the nav items.

---

## Version bump

Update VERSION: `2.15.4` → `2.15.5`

---

## Commit

```bash
git add -A
git commit -m "fix(ui): v2.15.5 layouts tab + admin menu + footer styling

- /api/layout/templates endpoint: 4 built-in system templates
- LayoutsTab: null guards on layout prop, survives missing layoutState
- Admin user menu: removed Layouts/Notifications shortcuts (already in sidebar)
- Footer: crimson tint background, 10px font, version highlighted in accent red"
git push origin main
```
