# CC PROMPT — v2.30.1 — fix(auth): remove token from localStorage, cookie-first auth

## What this does
The backend has set httpOnly cookies since v2.12.0 but the frontend still stores the JWT
in localStorage — XSS-accessible to any injected script. This prompt removes the token
from localStorage entirely. Auth is handled by the httpOnly cookie for browser sessions;
`Authorization: Bearer` header is preserved as fallback for API scripts/external clients.
Three SSE stream endpoints also need a `Request` parameter so they can read the cookie
when no `?token=` query param is present (EventSource sends same-origin cookies
automatically, but the current code ignores them).
Version bump: v2.30.0 → v2.30.1

---

## Change 1 — gui/src/context/AuthContext.jsx — full replacement

Replace the entire file with the version below. Key changes:
- Token is held in React state (memory) only — never written to localStorage
- On mount: call `/api/auth/me` with `credentials: 'include'` to validate the httpOnly
  cookie; restore user from localStorage if still valid (no token needed)
- On login: set token in state + write username to localStorage (not the token)
- On logout: POST to `/api/auth/logout` to clear the server-side cookie, then clear state

```jsx
import { createContext, useContext, useState, useEffect, useCallback } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE || ''
const USER_KEY = 'hp1_auth_user'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  // Token lives in memory only — never localStorage (XSS risk)
  const [token, setToken] = useState(null)
  const [user,  setUser]  = useState(() => localStorage.getItem(USER_KEY) || null)
  const [loading, setLoading] = useState(true)

  // Validate session on mount via httpOnly cookie
  useEffect(() => {
    fetch(`${API_BASE}/api/auth/me`, { credentials: 'include' })
      .then(r => {
        if (!r.ok) throw new Error('not authed')
        return r.json()
      })
      .then(data => {
        setUser(data.username)
        localStorage.setItem(USER_KEY, data.username)
        setLoading(false)
      })
      .catch(() => {
        localStorage.removeItem(USER_KEY)
        setToken(null)
        setUser(null)
        setLoading(false)
      })
  }, [])

  const login = useCallback(async (username, password) => {
    const r = await fetch(`${API_BASE}/api/auth/login`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    if (!r.ok) {
      const err = await r.json().catch(() => ({}))
      throw new Error(err.detail || 'Login failed')
    }
    const data = await r.json()
    // Store token in memory for same-session SSE fallback; never in localStorage
    setToken(data.access_token)
    setUser(data.username)
    localStorage.setItem(USER_KEY, data.username)
    return data
  }, [])

  const logout = useCallback(async () => {
    // Clear the httpOnly cookie server-side
    await fetch(`${API_BASE}/api/auth/logout`, {
      method: 'POST',
      credentials: 'include',
    }).catch(() => {})
    localStorage.removeItem(USER_KEY)
    setToken(null)
    setUser(null)
  }, [])

  return (
    <AuthContext.Provider value={{ token, user, loading, login, logout, isAuthed: !!user }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
```

---

## Change 2 — gui/src/api.js — remove localStorage token reads

`getAuthToken()` currently reads from localStorage. Remove that. `authHeaders()` returns
`{}` — same-origin requests automatically carry the httpOnly cookie, no header needed.
API scripts that pass `Authorization: Bearer` explicitly still work (backend accepts both).

Also update `createLogStream`, `createVMLogStream`, and `createUnifiedLogStream` to not
pass `?token=` in the URL — the browser sends the cookie automatically for same-origin
EventSource. If these functions don't exist by those exact names, find all places that
build SSE URLs with `?token=` in api.js and remove the token param.

Find this block:

```js
export function getAuthToken() {
  return localStorage.getItem('hp1_auth_token') || ''
}

export function authHeaders() {
  const token = getAuthToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}
```

Replace with:

```js
export function getAuthToken() {
  // Token no longer stored in localStorage — auth via httpOnly cookie.
  // Kept for API script callers that still pass Bearer headers explicitly.
  return ''
}

export function authHeaders() {
  // Same-origin requests carry the httpOnly cookie automatically.
  // External API scripts should pass Authorization: Bearer <token> explicitly.
  return {}
}
```

Then find every SSE URL in api.js that includes `token` as a query param and remove it.
For example, find any line like:

```js
const url = `${BASE}/api/dashboard/containers/${containerId}/logs/stream?tail=${tail}&token=${encodeURIComponent(token)}`
```

Remove the `&token=${encodeURIComponent(token)}` (or `?token=...&tail=...` → `?tail=...`)
so the URL no longer leaks the token. Apply the same fix to all SSE endpoint URLs in
api.js (vm logs stream, unified log stream, agent stream if present).

---

## Change 3 — api/routers/dashboard.py — cookie fallback for SSE endpoints

The three SSE stream endpoints authenticate via `?token=` query param only. Add
`request: Request` parameter and fall back to the httpOnly cookie when the token param
is empty. This allows EventSource (which sends same-origin cookies automatically) to
authenticate without a token in the URL.

Find:

```python
@router.get("/containers/{container_id}/logs/stream")
async def stream_container_logs(
    container_id: str,
    tail: int = 200,
    token: str = "",
):
    """Stream container stdout/stderr as SSE. Auth via ?token= (EventSource can't send headers)."""
    from api.auth import decode_token
    try:
        decode_token(token)
    except HTTPException:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
```

Replace with:

```python
@router.get("/containers/{container_id}/logs/stream")
async def stream_container_logs(
    container_id: str,
    tail: int = 200,
    token: str = "",
    request: Request = None,
):
    """Stream container stdout/stderr as SSE. Auth via cookie (preferred) or ?token= fallback."""
    from api.auth import decode_token
    _token = token or (request.cookies.get("hp1_auth") if request else "")
    try:
        decode_token(_token)
    except HTTPException:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
```

Apply the same `request: Request = None` + cookie fallback pattern to:

- `stream_all_logs` (`GET /logs/stream`)
- `stream_vm_logs` (`GET /vm-hosts/{host_id}/logs/stream`)

The pattern is identical for all three: add `request: Request = None` to the signature,
replace `token` with `_token = token or (request.cookies.get("hp1_auth") if request else "")`,
and pass `_token` to `decode_token`.

---

## Version bump
Update `VERSION` in `api/constants.py`: `v2.30.0` → `v2.30.1`

## Commit
```
git add -A
git commit -m "fix(auth): v2.30.1 remove token from localStorage, cookie-first auth"
git push origin main
```
