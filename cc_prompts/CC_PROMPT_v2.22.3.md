# CC PROMPT — v2.22.3 — Root error boundary + per-section boundaries + frontend error reporting

## What this does

Incident 2026-04-13: a single JS crash in VMHostsSection blanked the entire GUI for 90
minutes because there was no root-level error boundary. The user saw a white screen with
no message. There was also no pipeline to report the crash to the backend — the error
existed only in the browser console which was inaccessible.

This adds:
1. **RootErrorBoundary** around `<AppShell />` — any unhandled crash shows an error screen
   with the message and a "Clear state & reload" button instead of a blank page
2. **SectionErrorBoundary** in `DashboardLayout` — each section (COMPUTE, NETWORK etc.)
   gets its own boundary; a VM_HOSTS crash shows "Section unavailable" while other
   sections remain functional
3. **Frontend error reporting** — `componentDidCatch` POSTs the error to
   `/api/errors/frontend` so the backend logs it and it appears in the audit trail.
   This closes the gap where production JS errors are invisible to the operator.

Version bump: 2.22.2 → 2.22.3

---

## Change 1 — NEW ENDPOINT: api/routers/errors.py

```python
"""Frontend error reporting endpoint — receives client-side crash reports."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/errors", tags=["errors"])


class FrontendError(BaseModel):
    message: str = ""
    stack: str = ""
    component_stack: str = ""
    url: str = ""
    version: str = ""
    user_agent: str = ""


@router.post("/frontend")
async def report_frontend_error(err: FrontendError):
    """Receive a JS crash report from the browser.

    No auth required — the crash may have destroyed the auth state.
    Rate-limited by the browser (one report per crash event).
    Logs to server log + audit_log.
    """
    log.error(
        "FRONTEND CRASH | version=%s | %s | url=%s\n%s\n%s",
        err.version or "unknown",
        err.message[:200],
        err.url,
        err.stack[:500] if err.stack else "(no stack)",
        err.component_stack[:500] if err.component_stack else "(no component stack)",
    )
    try:
        from api.db import queries as q
        from api.db.base import get_engine
        async with get_engine().begin() as conn:
            await q.create_audit_entry(
                conn,
                event_type="frontend_crash",
                entity_id="browser",
                entity_type="frontend",
                detail={
                    "message": err.message[:500],
                    "stack": err.stack[:1000],
                    "component_stack": err.component_stack[:500],
                    "url": err.url,
                    "version": err.version,
                },
                source="browser",
            )
    except Exception as e:
        log.debug("frontend error audit write failed: %s", e)
    return {"received": True, "ts": datetime.now(timezone.utc).isoformat()}
```

### Register in api/main.py

Find where other routers are included (e.g., `app.include_router(status.router)`) and add:

```python
from api.routers.errors import router as errors_router
app.include_router(errors_router)
```

---

## Change 2 — gui/src/App.jsx

### 2a — Add RootErrorBoundary class

Add this class **before** the `AppShell` function definition:

```jsx
class RootErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null, reported: false }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, info) {
    console.error('[DEATHSTAR] Root crash:', error, info?.componentStack)

    if (this.state.reported) return

    // Report to backend — no auth header needed, crash may have killed auth state
    const BASE = import.meta.env.VITE_API_BASE ?? ''
    const version = document.querySelector('[data-version]')?.dataset?.version || ''
    fetch(`${BASE}/api/errors/frontend`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message:          error?.message   || String(error),
        stack:            error?.stack     || '',
        component_stack:  info?.componentStack || '',
        url:              window.location.href,
        version,
      }),
    }).catch(() => {}) // fire-and-forget, never throws

    this.setState({ reported: true })
  }

  render() {
    if (!this.state.hasError) return this.props.children

    const msg = this.state.error?.message || 'Unknown error'

    return (
      <div style={{
        minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: '#05060a', padding: 40,
      }}>
        <div style={{
          maxWidth: 540, width: '100%', background: '#09090f',
          border: '1px solid #a01828', borderRadius: 2, padding: '32px 36px',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
            <span style={{ color: '#cc2828', fontSize: 18 }}>✕</span>
            <span style={{
              fontFamily: 'Share Tech Mono, monospace', fontSize: 13,
              color: '#e8e8f0', letterSpacing: '0.06em',
            }}>DASHBOARD ERROR</span>
          </div>
          <p style={{ color: '#828aa0', fontSize: 11, fontFamily: 'Share Tech Mono, monospace', marginBottom: 8 }}>
            A component crashed. The error has been logged.
          </p>
          <pre style={{
            color: '#cc4444', fontSize: 10, fontFamily: 'Share Tech Mono, monospace',
            background: '#0d0f1a', padding: '10px 12px', borderRadius: 2,
            border: '1px solid #2a0a0a', overflow: 'auto', maxHeight: 120,
            marginBottom: 20, whiteSpace: 'pre-wrap', wordBreak: 'break-all',
          }}>
            {msg}
          </pre>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={() => window.location.reload()}
              style={{
                padding: '7px 16px', fontSize: 10, fontFamily: 'Share Tech Mono, monospace',
                background: 'var(--accent, #a01828)', color: '#fff',
                border: 'none', borderRadius: 2, cursor: 'pointer', letterSpacing: '0.05em',
              }}
            >↺ RELOAD</button>
            <button
              onClick={() => { localStorage.clear(); window.location.reload() }}
              style={{
                padding: '7px 16px', fontSize: 10, fontFamily: 'Share Tech Mono, monospace',
                background: 'transparent', color: '#828aa0',
                border: '1px solid #2a2a3a', borderRadius: 2, cursor: 'pointer', letterSpacing: '0.05em',
              }}
            >⊘ CLEAR STATE & RELOAD</button>
          </div>
        </div>
      </div>
    )
  }
}
```

### 2b — Wrap AppShell in RootErrorBoundary

Find in `AppWithPanelProvider`:
```jsx
  return (
    <CommandPanelProvider defaultOpen={commandsPanelDefault === 'visible'}>
      <DashboardDataProvider>
        <AgentProvider>
          <AppShell />
        </AgentProvider>
      </DashboardDataProvider>
    </CommandPanelProvider>
  )
```

Replace with:
```jsx
  return (
    <RootErrorBoundary>
      <CommandPanelProvider defaultOpen={commandsPanelDefault === 'visible'}>
        <DashboardDataProvider>
          <AgentProvider>
            <AppShell />
          </AgentProvider>
        </DashboardDataProvider>
      </CommandPanelProvider>
    </RootErrorBoundary>
  )
```

---

## Change 3 — gui/src/components/DashboardLayout.jsx

Add a `SectionErrorBoundary` class at the top of the file and wrap each rendered section.

Find the DashboardLayout component (or wherever sections are rendered). Add this class:

```jsx
class SectionErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false }
  }
  static getDerivedStateFromError() {
    return { hasError: true }
  }
  componentDidCatch(error) {
    console.error(`[DEATHSTAR] Section '${this.props.sectionName}' crashed:`, error)
  }
  render() {
    if (!this.state.hasError) return this.props.children
    return (
      <div style={{
        padding: '12px 14px', background: 'var(--bg-2)',
        border: '1px solid var(--border)', borderLeft: '3px solid var(--red)',
        borderRadius: 2, fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--red)',
      }}>
        ✕ {this.props.sectionName || 'Section'} unavailable — check browser console
      </div>
    )
  }
}
```

Then in the DashboardLayout render, find where it maps over sections/tiles and wraps each
child section. Add `SectionErrorBoundary` around each section's content:

The exact location depends on DashboardLayout's implementation, but the pattern is:

```jsx
// Wherever sections are rendered, add:
<SectionErrorBoundary key={key} sectionName={key}>
  {sectionContent}
</SectionErrorBoundary>
```

If DashboardLayout renders children directly from a `children` prop (like `children[key]`),
wrap each at that point.

---

## Do NOT touch

- `api/agents/router.py`
- Any collector files
- `mcp_server/`

---

## Version bump

Update `VERSION`: `2.22.2` → `2.22.3`

---

## Commit

```bash
git add -A
git commit -m "fix(resilience): v2.22.3 root error boundary + per-section + frontend crash reporting

- RootErrorBoundary wraps AppShell — any unhandled JS crash shows error screen
  with message + RELOAD + CLEAR STATE buttons instead of blank page
- componentDidCatch POSTs crash to /api/errors/frontend for backend logging
- POST /api/errors/frontend: no auth required, logs to server log + audit_log
- SectionErrorBoundary in DashboardLayout: each section isolated; one crash
  shows 'Section unavailable' while other sections stay functional
- Closes gap: production JS errors were invisible to operator for 90min in incident"
git push origin main
```
