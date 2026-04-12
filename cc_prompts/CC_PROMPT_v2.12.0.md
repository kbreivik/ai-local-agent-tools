# CC PROMPT — v2.12.0 — Auth hardening: httpOnly cookies + login rate limiting

## What this does

JWT is currently stored in `localStorage` — accessible to any JavaScript on the page (XSS risk).
This moves it to an `httpOnly` cookie with `SameSite=Strict` — JavaScript can no longer read it.

Also adds `slowapi` rate limiting on the login endpoint (5 attempts per minute per IP).

Version bump: 2.11.1 → 2.12.0 (security change affecting auth flow everywhere, x.1.x)

---

## Change 1 — api/routers/auth.py — set httpOnly cookie on login

```python
from fastapi import Response

@router.post("/login")
async def login(req: LoginRequest, response: Response):
    result = authenticate(req.username, req.password)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token(result["username"], result["role"])

    # Set as httpOnly cookie — JS cannot read this
    response.set_cookie(
        key="hp1_auth",
        value=token,
        httponly=True,
        samesite="strict",
        secure=False,        # set True when behind HTTPS
        max_age=86400 * 7,   # 7 days
        path="/",
    )
    # Also return token in body for API clients that need it
    return {
        "access_token": token,
        "token_type": "bearer",
        "username": result["username"],
        "role": result["role"],
    }

@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(key="hp1_auth", path="/")
    return {"status": "ok"}
```

---

## Change 2 — api/auth.py — accept token from cookie OR Authorization header

Update `get_current_user()` dependency to check both:

```python
from fastapi import Request, HTTPException

async def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> str:
    """Accept JWT from httpOnly cookie OR Authorization: Bearer header.
    Cookie takes priority. Header is fallback for API clients/scripts.
    """
    token = None

    # 1. Check cookie first (browser sessions)
    token = request.cookies.get("hp1_auth")

    # 2. Fall back to Authorization header (API clients, scripts)
    if not token and authorization:
        scheme, _, cred = authorization.partition(" ")
        if scheme.lower() == "bearer" and cred:
            token = cred

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return decode_token(token)
```

Apply same dual-source logic to any other auth dependencies that currently
only read the Authorization header.

---

## Change 3 — api/main.py — add slowapi rate limiting on login

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

In `api/routers/auth.py`, add the rate limit decorator to login:

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@router.post("/login")
@limiter.limit("5/minute")
async def login(request: Request, req: LoginRequest, response: Response):
    ...
```

Add `slowapi` to requirements.txt.

---

## Change 4 — gui/src/api.js — stop sending Authorization header, rely on cookie

The browser sends httpOnly cookies automatically on same-origin requests.
Remove `authHeaders()` from all fetch calls that go to the same origin.

```js
// BEFORE — localStorage token in header
export function authHeaders() {
  const token = localStorage.getItem('hp1_auth_token')
  return token ? { 'Authorization': `Bearer ${token}` } : {}
}

// AFTER — keep function for backwards compat with API scripts,
// but browser fetch calls no longer need it when using cookie auth.
// The browser sends the httpOnly cookie automatically.
export function authHeaders() {
  // Still needed for programmatic API clients.
  // Browser sessions use httpOnly cookie automatically.
  const token = localStorage.getItem('hp1_auth_token')
  return token ? { 'Authorization': `Bearer ${token}` } : {}
}
```

The key change: update `LoginScreen.jsx` to no longer store the token in localStorage
after login. The cookie is set by the server; the frontend just needs the username/role:

```js
// LoginScreen.jsx — after successful login:
// BEFORE:
localStorage.setItem('hp1_auth_token', data.access_token)

// AFTER: don't store the token — cookie is set by server automatically
// Only store non-sensitive display info:
localStorage.setItem('hp1_username', data.username)
localStorage.setItem('hp1_role', data.role)
// Remove old token if present from previous sessions:
localStorage.removeItem('hp1_auth_token')
```

For the logout button: call `POST /api/auth/logout` which clears the cookie,
then clear localStorage display fields.

---

## Change 5 — CORS update for cookie support

In `api/main.py` CORS middleware, ensure cookies are allowed:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # or specific origins
    allow_credentials=True,        # REQUIRED for cookies
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Note: `allow_origins=["*"]` with `allow_credentials=True` is not allowed by browsers.
In dev, set specific origin: `allow_origins=["http://192.168.199.10:8000", "http://localhost:5173"]`.

---

## Version bump

Update VERSION: `2.11.1` → `2.12.0`

---

## Commit

```bash
git add -A
git commit -m "feat(auth): v2.12.0 httpOnly cookie auth + login rate limiting

- JWT moved from localStorage to httpOnly SameSite=Strict cookie
- get_current_user(): accepts cookie first, Authorization header fallback
- POST /api/auth/logout: clears cookie
- slowapi: 5 login attempts/minute/IP rate limit
- Frontend: no longer stores token in localStorage
- CORS: allow_credentials=True for cookie support"
git push origin main
```
