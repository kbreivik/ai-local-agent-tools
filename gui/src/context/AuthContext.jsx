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
