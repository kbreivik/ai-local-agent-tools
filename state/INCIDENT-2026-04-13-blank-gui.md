# Incident Report: GUI Blank Page Crash (2026-04-13)

## Summary

Production GUI rendered briefly after login then went completely blank. No error displayed to the user — just a white/dark screen with no interactive elements. The dashboard was unreachable for approximately 30 minutes across container rebuilds.

**Root cause**: JavaScript temporal dead zone (TDZ) error in `VMHostsSection.jsx` — a `const` variable was declared after the `useEffect` hooks that referenced it in their dependency arrays.

**Fix**: Commit `feb929d` (v2.22.2) — moved `const id` declaration before the hooks that depend on it.

---

## Timeline

| Time (CEST) | Event |
|---|---|
| ~12:04 | Docker image built from v2.21.1 code, but working tree had uncommitted v2.22.0 GUI changes (DashboardDataContext). Image frontend/backend version mismatch. |
| ~12:08 | Container started. Frontend called `/api/dashboard/summary` which didn't exist in v2.21.1 backend → 404. Dashboard data stayed null. |
| ~12:25 | Image rebuilt from v2.21.2 (now includes summary endpoint + DashboardDataContext). Still had the TDZ bug from v2.20.2's VMCard changes. |
| ~12:33 | Image rebuilt again from v2.22.1 (skeleton loading). TDZ bug still present. |
| ~14:07 | Debugging session started. |
| ~14:35 | Root cause identified: `const id` used in useEffect dep array before declaration. |
| ~14:40 | Fix committed (v2.22.2), image rebuilt, container redeployed. |
| ~14:42 | GUI operational. |

---

## Root Cause: Temporal Dead Zone

In `gui/src/components/VMHostsSection.jsx`, the `VMCard` component had:

```javascript
function VMCard({ vm, onAction }) {
  // ... state declarations ...

  // Line 97: useEffect references 'id' in dependency array
  useEffect(() => {
    if (!open || !id) return
    fetch(`/api/dashboard/vm-hosts/${id}/actions?limit=5`, ...)
  }, [open, id])    // ← 'id' evaluated HERE during render

  // ... 80 more lines of hooks and handlers ...

  // Line 178: 'id' declared here — AFTER it's used above
  const id = vm.connection_id || vm.label
}
```

React evaluates `useEffect` dependency arrays **during render**, not when the effect fires. Since `const` and `let` are block-scoped and not hoisted like `var`, referencing `id` before its declaration triggers:

```
Uncaught ReferenceError: Cannot access 'id' before initialization
```

In the minified bundle this appeared as `Cannot access 'q' before initialization` (where `q` is the minified name for `id`).

### Why it wasn't caught earlier

- **v2.20.1** (Apr 13, 13:37) added the action audit trail with `const id` at line 178 and `useEffect` referencing `id` at line 97. This was the commit that introduced the bug.
- **v2.20.2** (Apr 13, 13:43) added SSH log streaming, also using `id` — compounded the problem but didn't introduce it.
- The bug wasn't caught because:
  1. `Vite build` succeeded — this is a runtime error, not a compile error
  2. No ESLint rule catches TDZ violations (it's a valid syntax pattern — the error is semantic)
  3. The `VMCard` component only crashes when data arrives and React evaluates the dep array — the initial skeleton/loading state renders fine
  4. The `ServiceCardsErrorBoundary` only wraps `ServiceCards`, not `VMHostsSection` — so the crash propagated to the root and blanked the entire page

### Contributing factor: Dirty working tree in Docker builds

The Docker image build at 12:04 used `COPY . .` which copied the entire working tree including uncommitted v2.22.0 GUI changes. This meant:
- Backend: v2.21.1 (from git)
- Frontend: v2.22.0 (from uncommitted files)

The frontend called `/api/dashboard/summary` which didn't exist in the v2.21.1 backend. Even after fixing the version mismatch, the TDZ bug persisted because it was present in all versions from v2.20.1 onward.

---

## Impact

- Full GUI outage — dashboard completely blank after login
- No error message visible to the user
- Backend was fully operational throughout (all API endpoints returned 200)
- Data collection, agent tasks, and WebSocket connections were unaffected

---

## What Went Wrong in Debugging

1. **Assumed auth/JWT first** — container restart changed the hostname-derived JWT secret, which was a real issue but a red herring for the blank page
2. **Container was rebuilt mid-investigation** — the running version changed from v2.21.1 → v2.21.2 → v2.22.1 while debugging, making it hard to pin down which code was actually running
3. **No browser console access** — had to infer the JS error from server logs and code inspection rather than seeing the actual error message
4. **Minified error was opaque** — `Cannot access 'q' before initialization` doesn't map to any source variable without source maps

---

## Improvements to Prevent Recurrence

### 1. Top-Level React Error Boundary (HIGH — prevents blank page)

**Problem**: Only `ServiceCards` has an error boundary. Any crash in `DashboardView`, `Sidebar`, `AppShell`, or any provider blanks the entire page.

**Fix**: Add a root-level error boundary around `<AppShell />` in `App.jsx`:

```jsx
class RootErrorBoundary extends React.Component {
  state = { hasError: false, error: null }
  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }
  componentDidCatch(error, info) {
    console.error('Root crash:', error, info.componentStack)
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 40, color: '#e8e8f0', background: '#05060a',
                       fontFamily: 'monospace', minHeight: '100vh' }}>
          <h2 style={{ color: '#cc2828' }}>Dashboard Error</h2>
          <p>The dashboard crashed. This has been logged.</p>
          <pre style={{ color: '#828aa0', fontSize: 11, marginTop: 16 }}>
            {this.state.error?.message}
          </pre>
          <button onClick={() => { localStorage.clear(); window.location.reload() }}
                  style={{ marginTop: 16, padding: '8px 16px', cursor: 'pointer',
                           background: '#a01828', color: '#fff', border: 'none' }}>
            Clear State & Reload
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
```

This ensures the user ALWAYS sees something instead of a blank page.

### 2. ESLint Rule for Variable Ordering (MEDIUM — catches TDZ at dev time)

**Problem**: No linting rule catches `const` variables used before declaration in the same scope.

**Fix**: Add `no-use-before-define` to ESLint config:

```javascript
// eslint.config.js
rules: {
  'no-use-before-define': ['error', {
    functions: false,    // function hoisting is fine
    classes: true,
    variables: true,     // catches const/let TDZ bugs
    allowNamedExports: false,
  }],
}
```

This would have caught the bug at `npx vite build` time.

### 3. Source Maps in Production (MEDIUM — faster debugging)

**Problem**: Minified errors like `Cannot access 'q'` are unreadable without source maps.

**Fix**: Generate source maps in the Docker build but don't serve them publicly:

```javascript
// vite.config.js
export default defineConfig({
  build: {
    sourcemap: 'hidden',  // generates .map files but doesn't reference them in JS
  },
})
```

Store the `.map` files as build artifacts. When debugging, load them into Chrome DevTools manually. This maps `q` back to `id` and `yv` back to `VMCard`.

### 4. Git-Clean Docker Builds (MEDIUM — prevents version mismatch)

**Problem**: `COPY . .` in Dockerfile copies uncommitted/untracked files, causing frontend/backend version mismatches.

**Fix**: Add a `.dockerignore` entry or build from a clean checkout:

```dockerfile
# Option A: Use git archive to get only committed files
RUN git archive HEAD | tar -x -C /app

# Option B: Add to .dockerignore
# gui/dist/          # never copy local dist — always build in Docker
# *.pyc
# __pycache__/
# .git/
```

Or enforce in CI: `git diff --quiet || (echo "ERROR: uncommitted changes" && exit 1)`

### 5. Error Boundaries Per Dashboard Section (LOW — graceful degradation)

**Problem**: One crashing section (VM_HOSTS) takes down the entire dashboard.

**Fix**: Wrap each section in `DashboardLayout` with its own error boundary:

```jsx
// In DashboardLayout, wrap each tile:
{Object.entries(children).map(([key, content]) => (
  <SectionErrorBoundary key={key} sectionName={key}>
    {content}
  </SectionErrorBoundary>
))}
```

A crashing VM_HOSTS section would show "Section unavailable" while COMPUTE, NETWORK, STORAGE continue working.

### 6. Stable JWT_SECRET (LOW — prevents auth disruption on restart)

**Problem**: JWT_SECRET is derived from container hostname. Every container restart generates a new hostname, invalidating all browser tokens.

**Fix**: Set `JWT_SECRET` in `/opt/hp1-agent/docker/.env` (Ansible-managed):

```yaml
# In hp1-infra ansible vault:
hp1_jwt_secret: "{{ lookup('password', '/dev/null length=64 chars=ascii_letters,digits') }}"
```

This is not related to the crash but caused additional confusion during debugging.

---

## Priority Order

| # | Improvement | Effort | Impact |
|---|---|---|---|
| 1 | Top-level error boundary | 15 min | Prevents blank page — shows error + reload button |
| 2 | ESLint `no-use-before-define` | 5 min | Catches TDZ bugs at build time |
| 3 | Source maps (hidden) | 5 min | Makes production errors readable |
| 4 | Git-clean Docker builds | 30 min | Prevents frontend/backend version mismatch |
| 5 | Per-section error boundaries | 30 min | Graceful degradation — one section crash doesn't kill all |
| 6 | Stable JWT_SECRET | 10 min | Sessions survive container restarts |
