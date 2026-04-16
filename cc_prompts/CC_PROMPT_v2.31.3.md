# CC PROMPT — v2.31.3 — fix(auth): WebSocket cookie-based auth (live output regression)

## What this does
Fixes a regression introduced by v2.30.1 (token-out-of-localStorage). The
WebSocket URL builder in `AgentOutputContext.jsx` still reads the token from
`localStorage.getItem('hp1_auth_token')` — which v2.30.1 removed. Result: the
WS connects without a `?token=` param, the backend closes it with code 1008
(auth error), the reconnect-on-auth-error path intentionally stops retrying,
and the Output panel never shows live agent events. Tasks still complete
(that's why they appear in Logs → Operations afterwards), but streaming is
dead.

This prompt matches the pattern v2.30.1 applied to SSE:
  * Backend: accept the JWT from the httpOnly auth cookie when `?token=` is
    absent — browsers send same-origin cookies on the WS handshake automatically.
  * Frontend: drop the `?token=` param. Drop the `Authorization` headers on
    the replay fetches; use `credentials: 'include'` instead.

Three changes. Version bump: v2.31.2 → v2.31.3.

---

## Before editing — confirm the cookie name

The existing cookie-based auth path already used by SSE endpoints (per v2.30.1)
is the canonical source of truth. Look at `api/auth.py` and the auth router
(`api/routers/auth.py`) to confirm the exact cookie name set on login — it is
expected to be either `auth_token` or `access_token`. Use whatever name
`api/auth.py` already reads in `get_current_user()`'s cookie fallback path.

Also inspect `api/websocket.py` → `manager.connect(ws, token=...)` to confirm
how it validates the token, so the new cookie extraction feeds the same
validation path without duplicating logic.

If the existing `manager.connect` already accepts any JWT-valid token, no
change is needed there — the fix is purely about *getting* the token to it.

---

## Change 1 — api/main.py — accept cookie on the WebSocket handshake

Find the existing handler in `api/main.py`:

```python
@app.websocket("/ws/output")
async def websocket_output(ws: WebSocket, token: Optional[str] = Query(default=None)):
    """WebSocket endpoint — streams agent output to GUI in real time.
    Pass ?token=<jwt> to authenticate. Invalid token closes with code 1008.
    """
    await manager.connect(ws, token=token)
```

Replace with:

```python
@app.websocket("/ws/output")
async def websocket_output(ws: WebSocket, token: Optional[str] = Query(default=None)):
    """WebSocket endpoint — streams agent output to GUI in real time.

    Auth priority:
      1. ?token=<jwt> query param (legacy)
      2. httpOnly auth cookie (preferred since v2.30.1 / v2.31.3)

    Invalid or missing token closes with code 1008.
    """
    if not token:
        # Browsers send same-origin cookies on the WS handshake. Read the
        # same cookie name used by the HTTP auth path so both flows validate
        # via the exact same manager.connect(token=...) path.
        token = (
            ws.cookies.get("auth_token")
            or ws.cookies.get("access_token")
            or ""
        )
    await manager.connect(ws, token=token)
```

Leave the rest of the handler (receive loop, disconnect handling) unchanged.

If inspection of `api/routers/auth.py` shows a different cookie name, use
that name instead — the two fallbacks above are defensive in case the name
varies across environments.

---

## Change 2 — gui/src/context/AgentOutputContext.jsx — drop token from WS URL

**2a.** Find the WebSocket URL builder inside `AgentOutputProvider`:

```js
  useEffect(() => {
    const token = localStorage.getItem('hp1_auth_token')
    const wsProto = location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${wsProto}://${location.host}/ws/output${token ? `?token=${token}` : ''}`
    _ensureWS(url)
```

Replace with:

```js
  useEffect(() => {
    // v2.31.3: cookie-based auth. The WS handshake automatically sends same-origin
    // cookies, so no ?token= param is needed. Keeps the URL clean of secrets in
    // server logs and browser history.
    const wsProto = location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${wsProto}://${location.host}/ws/output`
    _ensureWS(url)
```

**2b.** In the same file inside `_ensureWS()`, find the replay fetch block
inside `ws.onopen`:

```js
    const token = localStorage.getItem('hp1_auth_token')
    if (token) {
      fetch(`${API_BASE}/api/agent/sessions/active`, {
        headers: { Authorization: `Bearer ${token}` },
      })
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          const sessions = data?.sessions || []
          if (sessions.length > 0) {
            const latestSession = sessions[0]
            return fetch(`${API_BASE}/api/agent/session/${latestSession.session_id}/replay`, {
              headers: { Authorization: `Bearer ${token}` },
            })
          }
          return null
        })
```

Replace with (no token gate, use `credentials: 'include'` so the cookie flows):

```js
    // v2.31.3: cookie-based auth — no localStorage token to check
    fetch(`${API_BASE}/api/agent/sessions/active`, {
      credentials: 'include',
    })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        const sessions = data?.sessions || []
        if (sessions.length > 0) {
          const latestSession = sessions[0]
          return fetch(`${API_BASE}/api/agent/session/${latestSession.session_id}/replay`, {
            credentials: 'include',
          })
        }
        return null
      })
```

Leave the rest of the `_ensureWS` body (the `.then(data => data?.lines)`
chunk, the error catch, the listener notification logic) unchanged.

---

## Change 3 — gui/src/context/AgentOutputContext.jsx — defensive reconnect on 1008

Today `ws.onclose` handles code 1008 by calling `_notifyState('auth_error')`
and returning — no further reconnect. That's correct policy when the token
is actually expired, but with the new cookie-based flow a 1008 likely means
either (a) the user really did lose their session, or (b) the backend restarted
and the new instance doesn't trust the cookie for some reason (rare). Give
the user a clearer signal: after 1008, try **one** reconnect after a longer
delay before giving up, so a transient restart doesn't leave the Output panel
silent until a page refresh.

Find this block inside `_ensureWS`:

```js
  ws.onclose = (event) => {
    clearInterval(_pingTimer)
    _pingTimer = null
    _notifyState('disconnected')
    if (event.code === 1008) {
      // Auth rejection — token expired or invalid. Stop retrying and signal re-login.
      _notifyState('auth_error')
      return
    }
    if (_ws === ws) _scheduleReconnect()
  }
```

Replace with:

```js
  ws.onclose = (event) => {
    clearInterval(_pingTimer)
    _pingTimer = null
    _notifyState('disconnected')
    if (event.code === 1008) {
      // Auth rejection. Under cookie-based auth (v2.31.3) this can fire on
      // a transient backend restart before the cookie is re-validated. Try
      // one retry after a longer delay; if it fails again the onclose will
      // re-enter this branch and settle on auth_error.
      if (!_authRetried) {
        _authRetried = true
        setTimeout(() => _ensureWS(_wsUrl), 6000)
        return
      }
      _notifyState('auth_error')
      return
    }
    _authRetried = false  // successful connection clears the one-shot flag
    if (_ws === ws) _scheduleReconnect()
  }
```

And add a new module-level flag near the other singletons at the top of
the file (next to `let _ws = null` etc.):

```js
let _authRetried = false
```

---

## Version bump
- Update `VERSION` in `api/constants.py`: `v2.31.2` → `v2.31.3`
- Update root `/VERSION` file: `2.31.2` → `2.31.3`

## Commit
```
git add -A
git commit -m "fix(auth): v2.31.3 WebSocket cookie-based auth — restore live output"
git push origin main
```

---

## How to test after deploy

After `docker compose pull hp1_agent && docker compose up -d hp1_agent`:

1. **Clear any stale WS state** — hard refresh the DEATHSTAR UI
   (`Ctrl+Shift+R`) to discard the cached WebSocket instance, then log in
   again if prompted.

2. **WS connects without ?token=** — DevTools → Network → WS filter. The
   request URL should be plain `ws://192.168.199.10:8000/ws/output` with
   no query string. The connection should show status 101 (Switching Protocols)
   and stay open.

3. **WS indicator turns green** — the SubBar `WS ●` indicator at the top-right
   should be green (not yellow/connecting, not grey/disconnected).

4. **Live output streams during a task** — open the Commands panel, run
   any observe task (e.g. "check swarm status"). The Output tab should
   show step headers, tool calls, reasoning, and the final answer in
   real time — not only after the task completes.

5. **Replay on reconnect** — run a task, then kill the WS in DevTools
   (Network → WS → right-click → close). The frontend should auto-reconnect
   within ~3 s, and on reconnect the replay path should backfill the
   session log into the Output panel.

6. **Backend cookie extraction confirmed** — check logs on a fresh session:
   ```bash
   docker logs --tail 200 hp1_agent 2>&1 | grep -iE "websocket|ws_output|auth_error"
   ```
   Expect normal connect/disconnect lines, no repeated auth rejections.

If the WS still fails after these steps, inspect the cookie name mismatch:
```bash
# From DevTools → Application → Cookies — find the cookie set by POST /api/auth/login
# If the name is neither auth_token nor access_token, the cookie fallback in
# Change 1 needs to use that exact name.
```
