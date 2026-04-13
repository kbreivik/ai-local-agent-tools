# CC PROMPT — v2.22.4 — ESLint + source maps + API version gate + Dockerfile hardening

## What this does

Four low-effort, high-value changes from the incident post-mortem:

1. **ESLint `no-use-before-define`** — would have caught the TDZ bug (`const id` used
   before declaration) at build time instead of at runtime in production.

2. **Hidden source maps** — `sourcemap: 'hidden'` generates `.map` files but doesn't
   reference them in the JS bundle. When debugging, load them manually in Chrome DevTools.
   Maps `q` → `id`, `yv` → `VMCard`, etc. in minified errors.

3. **API version gate in DashboardDataContext** — when the frontend calls
   `/api/dashboard/summary` and gets a 404 (because the backend is older than the frontend),
   show a clear "API version mismatch" banner instead of silently staying blank. Reads
   `/api/health` version on startup and compares to a `MIN_API_VERSION` constant.

4. **Dockerfile: build only committed files** — `COPY . .` copies uncommitted working-tree
   changes into the Docker image, causing frontend/backend version mismatches like the one
   that extended the incident. Use `git stash` + build + `git stash pop` pattern, or add
   a CI guard that fails the build when there are uncommitted changes.

Version bump: 2.22.3 → 2.22.4

---

## Change 1 — eslint.config.js (or .eslintrc.cjs)

Find the ESLint config file in the project root or gui/. If it's `eslint.config.js` (flat
config), add to the rules object:

```javascript
rules: {
  // ... existing rules ...
  'no-use-before-define': ['error', {
    functions: false,    // function declarations are hoisted — fine
    classes: true,       // class TDZ is a real error
    variables: true,     // catches const/let TDZ — THIS is what caused the incident
    allowNamedExports: false,
  }],
}
```

If the file is `.eslintrc.cjs` (legacy config):
```javascript
rules: {
  'no-use-before-define': ['error', { functions: false, classes: true, variables: true }],
}
```

---

## Change 2 — gui/vite.config.js

Find the `build` section in vite.config.js. Add `sourcemap: 'hidden'`:

```javascript
export default defineConfig({
  // ... existing config ...
  build: {
    sourcemap: 'hidden',  // generates .map files but doesn't link them from the bundle
    // ... existing build config ...
  },
})
```

`'hidden'` means:
- `.map` files ARE generated during `vite build`
- The JS bundle does NOT contain `//# sourceMappingURL=...` references
- Users and bots cannot auto-discover the maps
- You can load them manually in Chrome DevTools: Sources → right-click → Add source map

---

## Change 3 — gui/src/context/DashboardDataContext.jsx

### 3a — Add MIN_BACKEND_VERSION constant

At the top of the file, after imports:

```jsx
// Minimum backend version this frontend requires.
// Increment when a new required endpoint is added (e.g. /api/dashboard/summary).
// Format: major.minor — patch versions don't break API contracts.
const MIN_BACKEND_VERSION = '2.22'
```

### 3b — Add version check state

In `DashboardDataProvider`, add:

```jsx
  const [versionMismatch, setVersionMismatch] = useState(null)  // null | string message
```

### 3c — Check version on first health fetch

In `refreshHealth`, add a version check after setting health:

```jsx
  const refreshHealth = useCallback(async () => {
    try {
      const d = await fetchHealth()
      if (!mountedRef.current) return
      setHealth(d)

      // Version gate: warn if backend is older than this frontend expects
      const backendVer = d?.version || ''
      if (backendVer && MIN_BACKEND_VERSION) {
        const [majB, minB] = backendVer.split('.').map(Number)
        const [majMin, minMin] = MIN_BACKEND_VERSION.split('.').map(Number)
        if (majB < majMin || (majB === majMin && minB < minMin)) {
          setVersionMismatch(
            `Backend v${backendVer} is older than frontend requires (v${MIN_BACKEND_VERSION}+). ` +
            `Dashboard data may be missing. Rebuild and redeploy the backend.`
          )
        } else {
          setVersionMismatch(null)
        }
      }
    } catch (_) {}
  }, [])
```

### 3d — Expose versionMismatch in context value

Add to the context value:
```jsx
      versionMismatch,
```

### 3e — Handle 404 gracefully in fetchSummary

In `fetchSummary`, replace the simple error catch with a more informative one:

```jsx
  const fetchSummary = useCallback(async () => {
    try {
      const r = await fetch(`${BASE}/api/dashboard/summary`, { headers: authHeaders() })
      if (r.status === 404) {
        // Backend doesn't have this endpoint yet — version mismatch
        setVersionMismatch(
          'Backend missing /api/dashboard/summary — backend version too old. Rebuild backend.'
        )
        setSummaryLoading(false)
        return
      }
      if (!r.ok || !mountedRef.current) return
      const d = await r.json()
      setSummary(d)
      setSummaryTs(Date.now())
      setSummaryLoading(false)
      setVersionMismatch(prev => prev?.includes('summary') ? null : prev)
    } catch (_) {
      setSummaryLoading(false)
    }
  }, [])
```

---

## Change 4 — gui/src/App.jsx — show version mismatch banner

In `DashboardView`, consume `versionMismatch` from context and show a banner.

Find in DashboardView:
```jsx
  const { summaryLoading, summaryStale, refreshSummary } = useDashboardData()
```

Replace with:
```jsx
  const { summaryLoading, summaryStale, refreshSummary, versionMismatch } = useDashboardData()
```

In the DashboardView JSX, after `<EscalationBanner />`, add:

```jsx
          {versionMismatch && (
            <div style={{
              padding: '8px 12px', background: '#1a0a00', borderBottom: '1px solid var(--amber)',
              fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--amber)',
              display: 'flex', alignItems: 'center', gap: 8,
            }}>
              <span>⚠</span>
              <span style={{ flex: 1 }}>{versionMismatch}</span>
              <span style={{ color: 'var(--text-3)', fontSize: 9 }}>
                backend may need rebuild+redeploy
              </span>
            </div>
          )}
```

---

## Change 5 — Dockerfile (or docker-compose build context)

Find `docker/Dockerfile` or the file that defines the Docker build.

### 5a — Add dirty working tree guard

If there's a CI/CD script or Makefile that runs `docker build`, add before it:

In `docker/Dockerfile`, add a build-time check using a build arg:

```dockerfile
# Optionally validate clean build — set BUILD_DIRTY_OK=1 to skip
ARG BUILD_DIRTY_OK=0
```

### 5b — Add .dockerignore entries

Find or create `docker/.dockerignore` (or root `.dockerignore`):

```
# Never copy local build artifacts — always build inside Docker
gui/dist/
gui/node_modules/
**/__pycache__/
**/*.pyc
**/*.pyo
.git/
*.log
state/
cc_prompts/
```

The key entry is `gui/dist/` — this prevents a locally-built dist from being copied
in instead of building fresh.

### 5c — Add build validation comment to docker-compose

In `docker/docker-compose.yml`, add a comment near the build section (if one exists)
or in the service definition:

```yaml
# IMPORTANT: Build from a clean git checkout to prevent frontend/backend version mismatch.
# If building locally with uncommitted changes, run: git stash && docker compose build && git stash pop
# Or set an explicit version: docker build --build-arg APP_VERSION=$(git describe --tags)
```

---

## Do NOT touch

- Any collector files
- `api/agents/router.py`
- `mcp_server/`

---

## Version bump

Update `VERSION`: `2.22.3` → `2.22.4`

---

## Commit

```bash
git add -A
git commit -m "fix(hardening): v2.22.4 ESLint TDZ rule + source maps + API version gate + Dockerfile

- eslint.config.js: no-use-before-define with variables:true — catches const/let TDZ
  bugs at build time; would have caught the incident root cause during development
- vite.config.js: sourcemap: 'hidden' — generates .map files but doesn't expose them;
  makes production errors like 'q is not defined' debuggable via DevTools
- DashboardDataContext: fetchSummary handles 404 gracefully with versionMismatch state
- DashboardDataContext: refreshHealth compares backend version to MIN_BACKEND_VERSION
- DashboardView: amber banner when versionMismatch is set — visible to operator
  instead of silent blank sections (root cause of 90min outage)
- .dockerignore: excludes gui/dist/, node_modules, __pycache__, state/, cc_prompts/
- Dockerfile/compose: build validation comments documenting clean-checkout requirement"
git push origin main
```
