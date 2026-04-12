# CC PROMPT — v2.15.1 — Copy connection + bulk create (IP range + name pattern)

## What this does

Two features that make registering many similar connections fast:

1. **Copy/duplicate** — copy button on each connection row, pre-fills form
   with all non-credential fields. Change label + host, save. Done.

2. **Bulk create** — "Bulk add" mode: enter a name pattern, IP range, and
   credential profile → generates N connections in one click with preview.
   Target use case: registering 3 managers + 3 workers in 30 seconds.

Version bump: 2.15.0 → 2.15.1 (UI feature, x.x.1)

---

## Change 1 — gui/src/components/OptionsModal.jsx — Copy button

In the connection list rows (where Edit and Delete buttons appear),
add a Copy button:

```jsx
<button
  onClick={() => duplicateConn(c)}
  title="Duplicate connection"
  className="px-2 py-1 text-[10px] rounded"
  style={{ background: 'var(--bg-3)', color: 'var(--text-3)' }}
>⧉ Copy</button>
```

Add `duplicateConn` function in `ConnectionsTab`:

```js
const duplicateConn = (c) => {
  const pa = PLATFORM_AUTH[c.platform] || { auth_type: 'apikey', defaultPort: 443 }
  setForm({
    platform: c.platform,
    label: `${c.label} (copy)`,
    host: c.host || '',
    port: c.port || pa.defaultPort || 443,
    auth_type: c.auth_type || pa.auth_type || 'token',
    credentials: {},   // never copy credentials — user must re-enter or pick profile
    config: { ...(c.config || {}), credential_profile_id: c.config?.credential_profile_id },
  })
  setEditingId(null)   // new connection, not edit
  setShowForm(true)
  setFormError('')
  // Scroll form into view
  setTimeout(() => document.getElementById('conn-form-top')?.scrollIntoView({ behavior: 'smooth' }), 100)
}
```

Add `id="conn-form-top"` to the top of the connection form div so the scroll target works.

---

## Change 2 — gui/src/components/OptionsModal.jsx — Bulk create mode

### 2a — Add "Bulk add" button next to "Add connection"

```jsx
<div className="flex gap-2 mb-4">
  <button onClick={startAdd} className="px-3 py-1.5 text-xs rounded ..." >
    + Add connection
  </button>
  <button onClick={() => { setShowBulk(true); setShowForm(false) }}
    className="px-3 py-1.5 text-xs rounded"
    style={{ background: 'var(--bg-3)', color: 'var(--text-2)' }}>
    ⊞ Bulk add
  </button>
</div>
```

### 2b — Bulk add state

```js
const [showBulk, setShowBulk] = useState(false)
const [bulk, setBulk] = useState({
  platform: 'vm_host',
  namePattern: 'ds-docker-worker-%N%',
  startN: 1,
  padWidth: 2,        // "01" = 2, "001" = 3
  ipStart: '192.168.199.31',
  ipEnd: '192.168.199.33',
  port: 22,
  role: 'swarm_worker',
  credential_profile_id: '',
  jump_via: '',
})
const [bulkPreview, setBulkPreview] = useState([])
const [bulkSaving, setBulkSaving] = useState(false)
const [bulkResult, setBulkResult] = useState(null)
```

### 2c — IP range expansion helper

```js
const expandIpRange = (ipStart, ipEnd) => {
  const parse = ip => ip.split('.').map(Number)
  const toNum = parts => parts[0]*16777216 + parts[1]*65536 + parts[2]*256 + parts[3]
  const fromNum = n => [(n>>24)&255, (n>>16)&255, (n>>8)&255, n&255].join('.')
  const start = toNum(parse(ipStart))
  const end = toNum(parse(ipEnd))
  if (end < start || end - start > 255) return []  // safety cap 256 IPs
  return Array.from({ length: end - start + 1 }, (_, i) => fromNum(start + i))
}

const buildBulkPreview = () => {
  const ips = expandIpRange(bulk.ipStart, bulk.ipEnd)
  return ips.map((ip, i) => {
    const n = bulk.startN + i
    const nStr = String(n).padStart(bulk.padWidth, '0')
    const label = bulk.namePattern.replace('%N%', nStr)
    return { label, host: ip, port: bulk.port }
  })
}
```

### 2d — BulkForm component

```jsx
function BulkForm({ bulk, setBulk, profiles, onSave, onCancel }) {
  const [preview, setPreview] = useState([])

  const update = (k, v) => setBulk(b => ({ ...b, [k]: v }))

  const expandIpRange = (ipStart, ipEnd) => {
    const parse = ip => ip.split('.').map(Number)
    const toNum = p => p[0]*16777216 + p[1]*65536 + p[2]*256 + p[3]
    const fromNum = n => [(n>>24)&255,(n>>16)&255,(n>>8)&255,n&255].join('.')
    try {
      const s = toNum(parse(ipStart)), e = toNum(parse(ipEnd))
      if (e < s || e - s > 255) return []
      return Array.from({ length: e - s + 1 }, (_, i) => fromNum(s + i))
    } catch { return [] }
  }

  const buildPreview = () => {
    const ips = expandIpRange(bulk.ipStart, bulk.ipEnd)
    return ips.map((ip, i) => {
      const n = bulk.startN + i
      const nStr = String(n).padStart(bulk.padWidth, '0')
      return { label: bulk.namePattern.replace('%N%', nStr), host: ip, port: bulk.port }
    })
  }

  // Rebuild preview whenever inputs change
  useEffect(() => { setPreview(buildPreview()) }, [bulk])

  const ROLES = [
    ['swarm_manager', 'Swarm Manager'],
    ['swarm_worker', 'Swarm Worker'],
    ['storage', 'Storage'],
    ['monitoring', 'Monitoring'],
    ['general', 'General'],
  ]

  return (
    <div className="border rounded p-4 mb-4" style={{ borderColor: 'var(--border)', background: 'var(--bg-2)' }}>
      <h3 className="text-xs font-semibold mb-3" style={{ color: 'var(--text-1)' }}>Bulk add connections</h3>

      <Field label="Platform">
        <select value={bulk.platform} onChange={e => update('platform', e.target.value)}
          className="w-full bg-[color:var(--bg-3)] border border-[color:var(--border)] rounded px-3 py-1.5 text-xs">
          <option value="vm_host">VM Host (SSH)</option>
          <option value="docker_host">Docker Host</option>
        </select>
      </Field>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Name pattern">
          <TextInput value={bulk.namePattern} onChange={v => update('namePattern', v)} placeholder="ds-docker-worker-%N%" />
          <p className="text-[10px] mt-0.5" style={{ color: 'var(--text-3)' }}>%N% = counter</p>
        </Field>
        <Field label="Start number">
          <div className="flex gap-2">
            <TextInput value={bulk.startN} onChange={v => update('startN', Number(v))} placeholder="1" />
            <select value={bulk.padWidth} onChange={e => update('padWidth', Number(e.target.value))}
              className="bg-[color:var(--bg-3)] border border-[color:var(--border)] rounded px-2 py-1.5 text-xs">
              <option value={1}>1 (1,2,3…)</option>
              <option value={2}>2 (01,02…)</option>
              <option value={3}>3 (001…)</option>
            </select>
          </div>
        </Field>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="IP start">
          <TextInput value={bulk.ipStart} onChange={v => update('ipStart', v)} placeholder="192.168.199.31" />
        </Field>
        <Field label="IP end">
          <TextInput value={bulk.ipEnd} onChange={v => update('ipEnd', v)} placeholder="192.168.199.33" />
        </Field>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Port">
          <TextInput value={bulk.port} onChange={v => update('port', Number(v))} placeholder="22" />
        </Field>
        <Field label="Role">
          <select value={bulk.role} onChange={e => update('role', e.target.value)}
            className="w-full bg-[color:var(--bg-3)] border border-[color:var(--border)] rounded px-3 py-1.5 text-xs">
            {ROLES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
      </div>

      <Field label="Credential profile">
        <select value={bulk.credential_profile_id} onChange={e => update('credential_profile_id', e.target.value)}
          className="w-full bg-[color:var(--bg-3)] border border-[color:var(--border)] rounded px-3 py-1.5 text-xs">
          <option value="">— none —</option>
          {profiles.map(p => <option key={p.id} value={p.id}>{p.name} ({p.auth_type})</option>)}
        </select>
      </Field>

      {/* Preview table */}
      {preview.length > 0 && (
        <div className="mt-3">
          <p className="text-[10px] font-semibold mb-1" style={{ color: 'var(--text-2)' }}>
            Preview — {preview.length} connection{preview.length !== 1 ? 's' : ''} will be created:
          </p>
          <div className="border rounded overflow-hidden" style={{ borderColor: 'var(--border)' }}>
            {preview.map((row, i) => (
              <div key={i} className="flex gap-4 px-3 py-1.5 border-b text-[11px]"
                style={{ borderColor: 'var(--border)', background: i % 2 ? 'var(--bg-2)' : 'var(--bg-1)', color: 'var(--text-1)' }}>
                <span className="font-mono w-52 truncate">{row.label}</span>
                <span className="font-mono text-[color:var(--text-3)]">{row.host}:{row.port}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {preview.length === 0 && (bulk.ipStart && bulk.ipEnd) && (
        <p className="text-xs mt-2" style={{ color: 'var(--red)' }}>
          Invalid IP range — check start/end addresses (max 256 IPs)
        </p>
      )}

      <div className="flex gap-2 mt-4">
        <button onClick={() => onSave(preview)} disabled={preview.length === 0}
          className="px-3 py-1 text-xs rounded bg-blue-600 text-white disabled:opacity-40">
          Create {preview.length} connection{preview.length !== 1 ? 's' : ''}
        </button>
        <button onClick={onCancel} className="px-3 py-1 text-xs rounded"
          style={{ background: 'var(--bg-3)', color: 'var(--text-2)' }}>Cancel</button>
      </div>
    </div>
  )
}
```

### 2e — Bulk save handler in ConnectionsTab

```js
const saveBulk = async (preview) => {
  setBulkSaving(true)
  setBulkResult(null)
  const results = []
  for (const row of preview) {
    const body = {
      platform: bulk.platform,
      label: row.label,
      host: row.host,
      port: row.port,
      auth_type: 'ssh',
      credentials: {},
      config: {
        role: bulk.role,
        ...(bulk.credential_profile_id ? { credential_profile_id: bulk.credential_profile_id } : {}),
        ...(bulk.jump_via ? { jump_via: bulk.jump_via } : {}),
      }
    }
    try {
      const r = await fetch(`${BASE}/api/connections`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(body),
      })
      const d = await r.json()
      results.push({ label: row.label, ok: d.status === 'ok', msg: d.message })
    } catch (e) {
      results.push({ label: row.label, ok: false, msg: e.message })
    }
  }
  setBulkSaving(false)
  setBulkResult(results)
  const allOk = results.every(r => r.ok)
  if (allOk) {
    setTimeout(() => { setShowBulk(false); setBulkResult(null); fetchConns() }, 1500)
  } else {
    fetchConns()
  }
}
```

Show `bulkResult` as a simple success/error list below the form after save.

---

## Version bump

Update VERSION: `2.15.0` → `2.15.1`

---

## Commit

```bash
git add -A
git commit -m "feat(connections): v2.15.1 copy connection + bulk create

- Copy button on each connection row — pre-fills form, credentials excluded
- Bulk add mode: name pattern (%N% counter with configurable pad) + IP range
- Preview table shows all connections before creation
- Saves sequentially, reports per-row success/failure
- Supports credential profile assignment for all bulk-created connections"
git push origin main
```
