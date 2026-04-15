# CC PROMPT — v2.27.6 — Settings: discovery scopes + rotation concurrency settings

## What this does
Adds two new settings sections to OptionsModal.jsx:

**Infrastructure tab — Discovery:**
- `discoveryEnabled` toggle (bool, default: false)
- `discoveryScopes` — CIDR/subnet list with add/remove, accepts both CIDR (192.168.0.0/24)
  and subnet mask notation (192.168.0.0 255.255.255.0); validated client-side and server-side;
  stored as JSON array of canonical CIDR strings

**General tab — Rotation Test:**
- `rotationTestMode` — select: parallel | sequential | adaptive (default: adaptive)
- `rotationTestDelayMs` — number input, ms between sequential tests (default: 500)
- `rotationMaxParallel` — number input, max parallel connections (default: 10)
- `rotationWindowsDelayMs` — number input, delay for Windows profiles (default: 2000)

All keys seeded via settings API on first load with defaults if not set.
Version bump: 2.27.5 → 2.27.6

---

## Change 1 — api/routers/settings.py: seed new setting keys

NOTE for CC: Read api/routers/settings.py first to find the seeded_defaults dict or equivalent pattern, then add the new keys using the same pattern.

Add these key-value pairs to the settings defaults (wherever other defaults are seeded):

```python
# Discovery settings
"discoveryEnabled":       "false",
"discoveryScopes":        "[]",         # JSON array of CIDR strings

# Rotation test settings
"rotationTestMode":       "adaptive",   # parallel | sequential | adaptive
"rotationTestDelayMs":    "500",        # ms between tests in sequential mode
"rotationMaxParallel":    "10",         # max concurrent parallel tests
"rotationWindowsDelayMs": "2000",       # extra delay for Windows profiles (lockout risk)
```

---

## Change 2 — gui/src/components/OptionsModal.jsx: add discovery scope UI to Infrastructure tab

NOTE for CC: Read OptionsModal.jsx and find the InfrastructureTab function (or the infrastructure settings section). Add the following Discovery section block near the top of that tab's content.

Add this complete Discovery section as a new subsection inside InfrastructureTab, before any existing content:

```jsx
{/* ── Discovery Settings ─────────────────────────────────────────────── */}
<div className="mb-5 pb-4" style={{ borderBottom: '1px solid var(--border)' }}>
  <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 700,
    color: 'var(--text-2)', letterSpacing: 1, marginBottom: 8 }}>
    DEVICE DISCOVERY
  </div>
  <p style={{ fontSize: 9, color: 'var(--text-3)', marginBottom: 10 }}>
    Passive harvest from Proxmox, UniFi, and Swarm. Scope limits which IPs appear in the Discovered view.
    Active network scanning is not performed — only devices already visible from integrated sources are harvested.
  </p>

  <Field label="Enable Discovery">
    <Toggle
      value={settings.discoveryEnabled === 'true' || settings.discoveryEnabled === true}
      onChange={v => saveSetting('discoveryEnabled', String(v))}
      label="Allow harvest from Proxmox / UniFi / Swarm"
    />
  </Field>

  <Field label="Discovery Scopes"
    hint="Only IPs within these ranges will appear in Discovered. Leave empty to show all. Accepts CIDR (192.168.0.0/24) or subnet mask (192.168.0.0 255.255.255.0).">
    <DiscoveryScopeList
      value={settings.discoveryScopes}
      onChange={v => saveSetting('discoveryScopes', v)}
    />
  </Field>
</div>
{/* ── end Discovery Settings ─────────────────────────────────────────── */}
```

---

## Change 3 — gui/src/components/OptionsModal.jsx: add DiscoveryScopeList component

Add this component BEFORE the InfrastructureTab function definition (or near other helper components):

```jsx
/**
 * DiscoveryScopeList — editable list of CIDR/subnet strings with validation.
 * value: JSON string or array of scope strings
 * onChange: called with new JSON string
 */
function DiscoveryScopeList({ value, onChange }) {
  // Parse existing scopes from JSON string or array
  const _parse = (v) => {
    if (!v) return []
    if (Array.isArray(v)) return v
    try { return JSON.parse(v) } catch { return [] }
  }
  const scopes = _parse(value)

  const [input, setInput] = useState('')
  const [inputError, setInputError] = useState('')

  // Client-side CIDR/subnet validation
  const _validate = (raw) => {
    const s = raw.trim()
    if (!s) return { ok: false, error: 'Empty input' }
    // Reject any characters that could be SQL/injection attempts
    if (/['";\\\n\r\x00-\x1f]/.test(s)) return { ok: false, error: 'Invalid characters' }
    if (s.length > 50) return { ok: false, error: 'Too long' }
    // CIDR notation: x.x.x.x/n
    const cidrMatch = s.match(/^(\d{1,3}\.){3}\d{1,3}\/(\d{1,2})$/)
    if (cidrMatch) {
      const parts = s.split('/')[0].split('.').map(Number)
      const prefix = parseInt(s.split('/')[1])
      if (parts.every(p => p >= 0 && p <= 255) && prefix >= 0 && prefix <= 32) {
        return { ok: true, canonical: s }
      }
      return { ok: false, error: 'Invalid CIDR range' }
    }
    // Subnet mask: x.x.x.x y.y.y.y
    const maskMatch = s.match(/^(\d{1,3}\.){3}\d{1,3}\s+(\d{1,3}\.){3}\d{1,3}$/)
    if (maskMatch) {
      const [ipPart, maskPart] = s.split(/\s+/)
      const ipOctets = ipPart.split('.').map(Number)
      const maskOctets = maskPart.split('.').map(Number)
      if (ipOctets.every(p => p >= 0 && p <= 255) && maskOctets.every(p => p >= 0 && p <= 255)) {
        // Convert to CIDR notation
        const maskBits = maskOctets.map(o => o.toString(2).padStart(8, '0')).join('')
        const prefixLen = maskBits.split('').filter(b => b === '1').length
        return { ok: true, canonical: `${ipPart}/${prefixLen}` }
      }
      return { ok: false, error: 'Invalid subnet mask' }
    }
    return { ok: false, error: 'Format must be CIDR (192.168.0.0/24) or subnet mask (192.168.0.0 255.255.255.0)' }
  }

  const add = () => {
    const { ok, canonical, error } = _validate(input)
    if (!ok) { setInputError(error); return }
    if (scopes.includes(canonical)) { setInputError('Already in list'); return }
    setInputError('')
    const updated = [...scopes, canonical]
    onChange(JSON.stringify(updated))
    setInput('')
  }

  const remove = (scope) => {
    onChange(JSON.stringify(scopes.filter(s => s !== scope)))
  }

  return (
    <div>
      {/* Existing scopes */}
      <div style={{ marginBottom: 6 }}>
        {scopes.length === 0 ? (
          <div style={{ fontSize: 9, color: 'var(--text-3)', fontStyle: 'italic' }}>
            No scope restrictions — all discovered IPs will be shown
          </div>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {scopes.map((s, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '2px 8px',
                borderRadius: 2, background: 'var(--bg-3)', border: '1px solid var(--border)' }}>
                <span style={{ fontSize: 9, color: 'var(--cyan)', fontFamily: 'var(--font-mono)' }}>{s}</span>
                <button onClick={() => remove(s)}
                  style={{ background: 'none', border: 'none', color: 'var(--red)', cursor: 'pointer',
                    fontSize: 9, padding: 0, lineHeight: 1 }}>✕</button>
              </div>
            ))}
          </div>
        )}
      </div>
      {/* Add input */}
      <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
        <div style={{ flex: 1 }}>
          <input
            value={input}
            onChange={e => { setInput(e.target.value); setInputError('') }}
            onKeyDown={e => e.key === 'Enter' && add()}
            placeholder="192.168.199.0/24  or  10.0.0.0 255.0.0.0"
            style={{ width: '100%', background: 'var(--bg-2)', border: `1px solid ${inputError ? 'var(--red)' : 'var(--border)'}`,
              borderRadius: 2, padding: '3px 8px', fontSize: 9, color: 'var(--text-1)',
              fontFamily: 'var(--font-mono)', outline: 'none' }}
          />
          {inputError && (
            <div style={{ fontSize: 8, color: 'var(--red)', marginTop: 2 }}>{inputError}</div>
          )}
        </div>
        <button onClick={add}
          style={{ fontSize: 9, padding: '3px 10px', borderRadius: 2, cursor: 'pointer', flexShrink: 0,
            background: 'var(--bg-3)', border: '1px solid var(--border)', color: 'var(--text-2)' }}>
          + Add
        </button>
      </div>
    </div>
  )
}
```

---

## Change 4 — gui/src/components/OptionsModal.jsx: add Rotation Test settings to General tab

NOTE for CC: Read OptionsModal.jsx and find the GeneralTab function (or the general settings section). Add this Rotation Test section block as a new subsection inside GeneralTab.

Add this complete Rotation Test section inside GeneralTab, near other operational settings:

```jsx
{/* ── Rotation Test Settings ─────────────────────────────────────────── */}
<div className="mb-5 pb-4" style={{ borderBottom: '1px solid var(--border)' }}>
  <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 700,
    color: 'var(--text-2)', letterSpacing: 1, marginBottom: 8 }}>
    CREDENTIAL ROTATION TESTING
  </div>
  <p style={{ fontSize: 9, color: 'var(--text-3)', marginBottom: 10 }}>
    Controls how credential rotation tests run against linked connections.
    Use sequential mode or higher delays for Windows accounts to prevent domain lockouts.
  </p>

  <Field label="Test mode"
    hint="Adaptive: sequential for Windows profiles (lockout risk), parallel for SSH/API.">
    <Select
      value={settings.rotationTestMode || 'adaptive'}
      onChange={v => saveSetting('rotationTestMode', v)}
      options={[
        ['adaptive',   'Adaptive (recommended — auto per auth type)'],
        ['parallel',   'Parallel (fastest — all connections at once)'],
        ['sequential', 'Sequential (safest — one at a time with delay)'],
      ]}
    />
  </Field>

  <Field label="Sequential delay (ms)"
    hint="Time between tests in sequential mode or between Windows tests. Default: 500ms.">
    <input
      type="number" min="0" max="30000" step="100"
      value={settings.rotationTestDelayMs ?? 500}
      onChange={e => saveSetting('rotationTestDelayMs', e.target.value)}
      style={{ width: 100, background: 'var(--bg-2)', border: '1px solid var(--border)',
        borderRadius: 2, padding: '3px 8px', fontSize: 10, color: 'var(--text-1)', outline: 'none' }}
    />
    <span style={{ fontSize: 9, color: 'var(--text-3)', marginLeft: 6 }}>ms</span>
  </Field>

  <Field label="Windows profile delay (ms)"
    hint="Additional delay between tests for Windows profiles. Prevents AD lockout. Default: 2000ms.">
    <input
      type="number" min="0" max="60000" step="500"
      value={settings.rotationWindowsDelayMs ?? 2000}
      onChange={e => saveSetting('rotationWindowsDelayMs', e.target.value)}
      style={{ width: 100, background: 'var(--bg-2)', border: '1px solid var(--border)',
        borderRadius: 2, padding: '3px 8px', fontSize: 10, color: 'var(--text-1)', outline: 'none' }}
    />
    <span style={{ fontSize: 9, color: 'var(--text-3)', marginLeft: 6 }}>ms</span>
  </Field>

  <Field label="Max parallel tests"
    hint="Maximum concurrent SSH/API connections during parallel rotation tests. Default: 10.">
    <input
      type="number" min="1" max="100"
      value={settings.rotationMaxParallel ?? 10}
      onChange={e => saveSetting('rotationMaxParallel', e.target.value)}
      style={{ width: 80, background: 'var(--bg-2)', border: '1px solid var(--border)',
        borderRadius: 2, padding: '3px 8px', fontSize: 10, color: 'var(--text-1)', outline: 'none' }}
    />
  </Field>

  <div style={{ fontSize: 9, color: 'var(--text-3)', padding: '6px 8px', borderRadius: 2,
    background: 'rgba(204,136,0,0.06)', border: '1px solid rgba(204,136,0,0.2)', marginTop: 4 }}>
    ⚠ Windows/domain accounts: use sequential mode with ≥2000ms delay. Most AD environments
    lock accounts after 5–10 failed attempts within a window. Test on one connection manually first.
  </div>
</div>
{/* ── end Rotation Test Settings ─────────────────────────────────────── */}
```

---

## Version bump
Update VERSION: 2.27.5 → 2.27.6

## Commit
```bash
git add -A
git commit -m "feat(settings): v2.27.6 discovery scope list + rotation concurrency settings"
git push origin main
```
