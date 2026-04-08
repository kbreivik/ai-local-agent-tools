import { useState, useEffect } from 'react'
import { useAuth } from '../context/AuthContext'

const BASE = import.meta.env.VITE_API_BASE ?? ''

function DeathStarOrb({ size = 80 }) {
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%', margin: '0 auto',
      background: 'radial-gradient(circle at 38% 32%, #c44 0%, #700 40%, #200 70%, #100 100%)',
      boxShadow: '0 0 40px rgba(160,24,40,0.4), inset -8px -8px 20px rgba(0,0,0,0.6)',
      position: 'relative', overflow: 'hidden',
    }}>
      {/* Superlaser dish */}
      <div style={{
        position: 'absolute', top: '28%', left: '22%',
        width: size * 0.28, height: size * 0.28, borderRadius: '50%',
        background: 'radial-gradient(circle at 45% 40%, #444 0%, #222 50%, #111 100%)',
        border: '1px solid #555', boxShadow: 'inset 0 0 6px rgba(0,0,0,0.8)',
      }} />
      {/* Equatorial trench */}
      <div style={{
        position: 'absolute', top: '48%', left: 0, right: 0,
        height: 2, background: 'linear-gradient(90deg, transparent 5%, #444 20%, #666 50%, #444 80%, transparent 95%)',
      }} />
    </div>
  )
}

export default function LoginScreen() {
  const { login } = useAuth()
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [error,    setError]    = useState('')
  const [loading,  setLoading]  = useState(false)
  const [version,  setVersion]  = useState(null)

  useEffect(() => {
    fetch(`${BASE}/api/health`)
      .then(r => r.json())
      .then(d => setVersion(d.version))
      .catch(() => {})
  }, [])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(username, password)
    } catch (err) {
      setError(err.message || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-0, #0a0a14)' }}>
      <div style={{ width: '100%', maxWidth: 360 }}>
        {/* Logo */}
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <DeathStarOrb size={80} />
          <div style={{
            fontFamily: 'var(--font-sans, Rajdhani, sans-serif)', fontWeight: 700,
            fontSize: 22, letterSpacing: 3, color: 'var(--text-1, #e8e8f0)',
            marginTop: 12,
          }}>DEATHSTAR</div>
          <div style={{
            fontFamily: 'var(--font-mono, "Share Tech Mono", monospace)',
            fontSize: 9, color: 'var(--accent, #a01828)', letterSpacing: 2, marginTop: 2,
          }}>IMPERIAL OPS</div>
        </div>

        <form onSubmit={handleSubmit} style={{
          background: 'var(--bg-1, #111122)', border: '1px solid var(--border, #1e1e3a)',
          borderRadius: 4, padding: 24,
        }}>
          <h1 style={{
            color: 'var(--text-1, #e8e8f0)', fontSize: 14, fontWeight: 600,
            fontFamily: 'var(--font-sans, Rajdhani, sans-serif)',
            letterSpacing: 1, marginBottom: 20,
          }}>AUTHENTICATE</h1>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div>
              <label style={{
                fontSize: 9, color: 'var(--text-3, #555)', letterSpacing: 1,
                fontFamily: 'var(--font-mono)', textTransform: 'uppercase',
                display: 'block', marginBottom: 4,
              }}>Username</label>
              <input
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                style={{
                  width: '100%', background: 'var(--bg-2, #0d0d1a)',
                  border: '1px solid var(--border, #1e1e3a)', borderRadius: 2,
                  padding: '8px 12px', color: 'var(--text-1, #e8e8f0)',
                  fontSize: 13, fontFamily: 'var(--font-mono)',
                  outline: 'none', boxSizing: 'border-box',
                }}
                placeholder="admin"
                autoFocus
                autoComplete="username"
              />
            </div>

            <div>
              <label style={{
                fontSize: 9, color: 'var(--text-3, #555)', letterSpacing: 1,
                fontFamily: 'var(--font-mono)', textTransform: 'uppercase',
                display: 'block', marginBottom: 4,
              }}>Password</label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                style={{
                  width: '100%', background: 'var(--bg-2, #0d0d1a)',
                  border: '1px solid var(--border, #1e1e3a)', borderRadius: 2,
                  padding: '8px 12px', color: 'var(--text-1, #e8e8f0)',
                  fontSize: 13, fontFamily: 'var(--font-mono)',
                  outline: 'none', boxSizing: 'border-box',
                }}
                placeholder="........"
                autoComplete="current-password"
              />
            </div>
          </div>

          {error && (
            <div style={{
              marginTop: 16, color: 'var(--red, #e44)', fontSize: 11,
              background: 'var(--red-dim, #1a0808)', border: '1px solid var(--red, #e44)',
              borderRadius: 2, padding: '6px 10px', fontFamily: 'var(--font-mono)',
            }}>
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || !username || !password}
            style={{
              marginTop: 20, width: '100%',
              background: loading || !username || !password ? 'var(--bg-3, #222)' : 'var(--accent, #a01828)',
              color: 'var(--text-1, #e8e8f0)', fontWeight: 600, borderRadius: 2,
              padding: '10px 0', fontSize: 12, border: 'none', cursor: 'pointer',
              fontFamily: 'var(--font-sans, Rajdhani, sans-serif)', letterSpacing: 1,
              opacity: loading || !username || !password ? 0.5 : 1,
            }}
          >
            {loading ? 'AUTHENTICATING...' : 'AUTHORIZE'}
          </button>
        </form>

        <div style={{
          textAlign: 'center', marginTop: 16,
          color: 'var(--text-3, #555)', fontSize: 10,
          fontFamily: 'var(--font-mono, "Share Tech Mono", monospace)',
        }}>
          {version ? `v${version}` : '...'}
        </div>
      </div>
    </div>
  )
}
