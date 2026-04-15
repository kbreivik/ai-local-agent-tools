# CC PROMPT — v2.27.2 — Frontend: Credential Profiles tab overhaul

## What this does
Rewrites the credential profiles section in OptionsModal.jsx:
- Prominent top-level section (not collapsed accordion)
- seq_id badge on each profile
- Full ProfileForm with all auth types: ssh, windows, api, token_pair, basic
- Shows linked_connections_count with delete warning if N > 0
- discoverable toggle
- SSH: private key + passphrase fields; hint towards passphrase-protected keys
- Windows: username format helper, account_type, winrm_auth_method
- api/token_pair/basic: appropriate fields
Version bump: 2.27.1 → 2.27.2

---

## Change 1 — gui/src/components/OptionsModal.jsx

### 1a — Replace the ProfileForm function entirely

FIND (exact):
```
function ProfileForm({ form, setForm, onSave, onCancel }) {
  const AUTH_TYPES = [
    ['ssh_key', 'SSH Key'],
    ['password', 'Password'],
    ['api_key', 'API Key'],
    ['token', 'Token'],
  ]
  const update = (k, v) => setForm(f => ({ ...f, [k]: v }))
  const updateCred = (k, v) => setForm(f => ({ ...f, credentials: { ...f.credentials, [k]: v } }))

  return (
    <div className="mt-3 p-3 border rounded" style={{ borderColor: 'var(--border)', background: 'var(--bg-2)' }}>
      <Field label="Profile name">
        <TextInput value={form.name} onChange={v => update('name', v)} placeholder="ubuntu-ssh-key" />
      </Field>
      <Field label="Auth type">
        <Select value={form.auth_type} onChange={v => update('auth_type', v)}
          options={AUTH_TYPES} />
      </Field>
      {(form.auth_type === 'ssh_key' || form.auth_type === 'password') && (
        <>
          <Field label="Username">
            <TextInput value={form.credentials.username || ''} onChange={v => updateCred('username', v)} placeholder="ubuntu" />
          </Field>
          {form.auth_type === 'ssh_key' && (
            <Field label="Private key (PEM)">
              <Textarea value={form.credentials.private_key || ''} onChange={v => updateCred('private_key', v)}
                placeholder="-----BEGIN OPENSSH PRIVATE KEY-----" rows={5} />
            </Field>
          )}
          {form.auth_type === 'password' && (
            <Field label="Password">
              <TextInput type="password" value={form.credentials.password || ''} onChange={v => updateCred('password', v)} />
            </Field>
          )}
        </>
      )}
      {form.auth_type === 'api_key' && (
        <Field label="API Key">
          <TextInput type="password" value={form.credentials.api_key || ''} onChange={v => updateCred('api_key', v)} />
        </Field>
      )}
      <div className="flex gap-2 mt-3">
        <button onClick={onSave} className="px-3 py-1 text-xs rounded bg-blue-600 text-white">Save</button>
        <button onClick={onCancel} className="px-3 py-1 text-xs rounded" style={{ background: 'var(--bg-3)', color: 'var(--text-2)' }}>Cancel</button>
      </div>
    </div>
  )
}
```

REPLACE WITH:
```
const PROFILE_AUTH_TYPES = [
  ['ssh',        'SSH (key / password)'],
  ['windows',    'Windows (WinRM)'],
  ['api',        'API Key'],
  ['token_pair', 'Token Pair (ID + Secret)'],
  ['basic',      'HTTP Basic'],
]

const WINRM_AUTH_METHODS = [
  ['ntlm',        'NTLM (recommended)'],
  ['kerberos',    'Kerberos (domain)'],
  ['basic',       'Basic (HTTPS only)'],
  ['certificate', 'Certificate'],
]

const ACCOUNT_TYPES = [
  ['local',           'Local account'],
  ['domain',          'Domain account'],
  ['service',         'Service account'],
  ['managed_service', 'Managed service account (gMSA)'],
]

function _detectWindowsFormat(raw) {
  if (!raw) return null
  if (raw.includes('@') && raw.includes('.')) return 'UPN (user@domain.com)'
  if (raw.startsWith('local\\') || raw.startsWith('LOCAL\\')) return 'Local (local\\user)'
  if (raw.includes('\\')) return 'NetBIOS (DOMAIN\\user)'
  return 'Local (no prefix — will use local\\)'
}

function ProfileForm({ form, setForm, onSave, onCancel, isEdit }) {
  const update = (k, v) => setForm(f => ({ ...f, [k]: v }))
  const updateCred = (k, v) => setForm(f => ({ ...f, credentials: { ...f.credentials, [k]: v } }))
  const winFmt = _detectWindowsFormat(form.credentials?.username)

  return (
    <div className="mt-3 p-3 border rounded" style={{ borderColor: 'var(--border)', background: 'var(--bg-2)' }}>
      <div className="text-[10px] font-semibold mb-3" style={{ color: 'var(--text-2)', fontFamily: 'var(--font-mono)', letterSpacing: 1 }}>
        {isEdit ? 'EDIT PROFILE' : 'NEW CREDENTIAL PROFILE'}
      </div>

      <Field label="Profile name">
        <TextInput value={form.name} onChange={v => update('name', v)} placeholder="ubuntu-ssh-key" />
      </Field>

      <Field label="Auth type">
        <Select value={form.auth_type} onChange={v => { update('auth_type', v); setForm(f => ({ ...f, credentials: {} })) }}
          options={PROFILE_AUTH_TYPES} />
      </Field>

      {/* SSH */}
      {form.auth_type === 'ssh' && (<>
        <Field label="Username">
          <TextInput value={form.credentials.username || ''} onChange={v => updateCred('username', v)} placeholder="ubuntu" />
        </Field>
        <Field label="Private Key (PEM)" hint={
          <span>
            PEM format — paste full key including BEGIN/END lines. Stored encrypted.
            <span style={{ color: 'var(--amber)', marginLeft: 4 }}>
              ⚠ Use passphrase-protected keys for security — unprotected keys are a risk if the server is compromised.
            </span>
          </span>
        }>
          <Textarea value={form.credentials.private_key || ''} onChange={v => updateCred('private_key', v)}
            placeholder="-----BEGIN OPENSSH PRIVATE KEY-----" rows={5} />
        </Field>
        <Field label="Key Passphrase" hint="Passphrase for the private key. Strongly recommended.">
          <TextInput type="password" value={form.credentials.passphrase || ''} onChange={v => updateCred('passphrase', v)} placeholder="passphrase (recommended)" />
        </Field>
        <Field label="Password" hint="Fallback if private key auth fails. Not recommended — prefer key-only.">
          <TextInput type="password" value={form.credentials.password || ''} onChange={v => updateCred('password', v)} placeholder="leave blank to require key auth" />
        </Field>
      </>)}

      {/* Windows */}
      {form.auth_type === 'windows' && (<>
        <Field label="Username" hint="Accepts: local\\user · DOMAIN\\user · user@domain.com">
          <TextInput value={form.credentials.username || ''} onChange={v => updateCred('username', v)}
            placeholder="Administrator or DOMAIN\\user or user@domain.com" />
          {winFmt && (
            <div style={{ fontSize: 9, color: 'var(--cyan)', marginTop: 3, fontFamily: 'var(--font-mono)' }}>
              Detected format: {winFmt}
            </div>
          )}
        </Field>
        <Field label="Password">
          <TextInput type="password" value={form.credentials.password || ''} onChange={v => updateCred('password', v)} />
        </Field>
        <Field label="WinRM Auth Method">
          <Select value={form.credentials.winrm_auth_method || 'ntlm'}
            onChange={v => updateCred('winrm_auth_method', v)} options={WINRM_AUTH_METHODS} />
        </Field>
        <Field label="Account Type" hint="Informational — affects lockout risk display and agent behaviour">
          <Select value={form.credentials.account_type || 'local'}
            onChange={v => updateCred('account_type', v)} options={ACCOUNT_TYPES} />
        </Field>
        {form.credentials.account_type === 'domain' || form.credentials.account_type === 'service' ? (
          <div style={{ fontSize: 9, padding: '4px 8px', borderRadius: 2, border: '1px solid var(--amber)', color: 'var(--amber)', marginBottom: 8 }}>
            ⚠ Domain/service accounts may lock out across all linked devices if credentials change — test rotation carefully.
          </div>
        ) : null}
      </>)}

      {/* API Key */}
      {form.auth_type === 'api' && (<>
        <Field label="API Key">
          <TextInput type="password" value={form.credentials.api_key || ''} onChange={v => updateCred('api_key', v)} placeholder="sk-..." />
        </Field>
        <Field label="Header Name" hint='Default: Authorization'>
          <TextInput value={form.credentials.header_name || ''} onChange={v => updateCred('header_name', v)} placeholder="Authorization" />
        </Field>
        <Field label="Prefix" hint='Default: Bearer (use X-Api-Key for header-key style)'>
          <TextInput value={form.credentials.prefix || ''} onChange={v => updateCred('prefix', v)} placeholder="Bearer" />
        </Field>
      </>)}

      {/* Token Pair */}
      {form.auth_type === 'token_pair' && (<>
        <Field label="Token ID">
          <TextInput value={form.credentials.token_id || ''} onChange={v => updateCred('token_id', v)} placeholder="terraform@pve!my-token" />
        </Field>
        <Field label="Token Secret">
          <TextInput type="password" value={form.credentials.secret || ''} onChange={v => updateCred('secret', v)} />
        </Field>
      </>)}

      {/* HTTP Basic */}
      {form.auth_type === 'basic' && (<>
        <Field label="Username">
          <TextInput value={form.credentials.username || ''} onChange={v => updateCred('username', v)} placeholder="admin" />
        </Field>
        <Field label="Password">
          <TextInput type="password" value={form.credentials.password || ''} onChange={v => updateCred('password', v)} />
        </Field>
      </>)}

      <Field label="">
        <Toggle value={!!form.discoverable} onChange={v => update('discoverable', v)}
          label="Available for discovery (use this profile when testing unlinked devices)" />
      </Field>

      <div className="flex gap-2 mt-3">
        <button onClick={onSave} className="px-3 py-1 text-xs rounded bg-blue-600 text-white">
          {isEdit ? 'Update Profile' : 'Save Profile'}
        </button>
        <button onClick={onCancel} className="px-3 py-1 text-xs rounded"
          style={{ background: 'var(--bg-3)', color: 'var(--text-2)' }}>Cancel</button>
      </div>
    </div>
  )
}
```

### 1b — Replace the profiles accordion section in ConnectionsTab with a prominent profiles section

FIND (exact):
```
      <div className="mb-4 border rounded" style={{ borderColor: 'var(--border)' }}>
        <button
          onClick={() => setProfilesOpen(o => !o)}
          className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold"
          style={{ color: 'var(--text-1)', background: 'none', border: 'none', cursor: 'pointer' }}
        >
          <span>CREDENTIAL PROFILES ({profiles.length})</span>
          <span>{profilesOpen ? '\u25B2' : '\u25BC'}</span>
        </button>
        {profilesOpen && (
          <div className="px-3 pb-3">
            <p className="text-[10px] mb-2" style={{ color: 'var(--text-3)' }}>
              Named auth sets shared across multiple connections. Select a profile when adding vm_host or docker_host connections instead of re-entering credentials each time.
            </p>
            {profiles.map(p => (
              <div key={p.id} className="flex items-center justify-between py-1 border-b" style={{ borderColor: 'var(--border)' }}>
                <span className="text-xs" style={{ color: 'var(--text-1)' }}>{p.name}</span>
                <span className="text-[10px] px-2 py-0.5 rounded" style={{ background: 'var(--bg-3)', color: 'var(--text-3)' }}>{p.auth_type}</span>
              </div>
            ))}
            <button
              onClick={() => setShowProfileForm(true)}
              className="mt-2 text-xs px-3 py-1 rounded"
              style={{ background: 'var(--accent-dim)', color: 'var(--accent)' }}
            >+ New profile</button>
            {showProfileForm && <ProfileForm
              form={profileForm}
              setForm={setProfileForm}
              onSave={async () => {
                await fetch(`${BASE}/api/credential-profiles`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json', ...authHeaders() },
                  body: JSON.stringify(profileForm),
                })
                setShowProfileForm(false)
                setProfileForm({ name: '', auth_type: 'ssh_key', credentials: {} })
                fetchProfiles()
              }}
              onCancel={() => setShowProfileForm(false)}
            />}
          </div>
        )}
      </div>
```

REPLACE WITH:
```
      {/* ── Credential Profiles — prominent section ───────────────────────── */}
      <div className="mb-5">
        <div className="flex items-center justify-between mb-2">
          <div>
            <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 700,
              color: 'var(--text-2)', letterSpacing: 1 }}>
              CREDENTIAL PROFILES
            </span>
            <span style={{ fontSize: 9, color: 'var(--text-3)', marginLeft: 8 }}>
              Shared auth sets — link to connections instead of storing credentials per-connection
            </span>
          </div>
          <button onClick={() => { setShowProfileForm(true); setEditingProfileId(null); setProfileForm({ name: '', auth_type: 'ssh', credentials: {}, discoverable: false }) }}
            style={{ fontSize: 9, padding: '3px 10px', borderRadius: 2, background: 'var(--accent-dim)',
              color: 'var(--accent)', border: '1px solid var(--accent)', cursor: 'pointer', fontFamily: 'var(--font-mono)' }}>
            + NEW PROFILE
          </button>
        </div>

        {showProfileForm && (
          <ProfileForm
            form={profileForm}
            setForm={setProfileForm}
            isEdit={!!editingProfileId}
            onSave={async () => {
              const url = editingProfileId
                ? `${BASE}/api/credential-profiles/${editingProfileId}`
                : `${BASE}/api/credential-profiles`
              const method = editingProfileId ? 'PUT' : 'POST'
              await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json', ...authHeaders() },
                body: JSON.stringify(profileForm),
              })
              setShowProfileForm(false)
              setEditingProfileId(null)
              setProfileForm({ name: '', auth_type: 'ssh', credentials: {}, discoverable: false })
              fetchProfiles()
            }}
            onCancel={() => { setShowProfileForm(false); setEditingProfileId(null) }}
          />
        )}

        <div className="space-y-1 mt-2">
          {profiles.filter(p => p.name !== '__no_credential__').map(p => {
            const isLinked = (p.linked_connections_count || 0) > 0
            return (
              <div key={p.id} className="flex items-center justify-between px-2 py-1.5 rounded"
                style={{ background: 'var(--bg-2)', border: '1px solid var(--border)' }}>
                <div className="flex items-center gap-2 min-w-0">
                  {/* seq_id badge */}
                  <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 2, fontFamily: 'var(--font-mono)',
                    background: 'var(--bg-3)', color: 'var(--text-3)', flexShrink: 0 }}>
                    #{p.seq_id ?? '?'}
                  </span>
                  <span style={{ fontSize: 11, color: 'var(--text-1)', fontWeight: 600, truncate: true }}>
                    {p.name}
                  </span>
                  <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 2,
                    background: 'var(--bg-3)', color: 'var(--cyan)' }}>
                    {p.auth_type}
                  </span>
                  {p.username && (
                    <span style={{ fontSize: 9, color: 'var(--text-3)' }}>{p.username}</span>
                  )}
                  {p.has_private_key && (
                    <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2,
                      background: 'rgba(0,200,238,0.1)', color: 'var(--cyan)' }}>⚿ KEY</span>
                  )}
                  {p.has_passphrase && (
                    <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2,
                      background: 'rgba(0,170,68,0.1)', color: 'var(--green)' }}>🔒 PASS</span>
                  )}
                  {p.discoverable && (
                    <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2,
                      background: 'rgba(204,136,0,0.12)', color: 'var(--amber)' }}>◎ DISCOVERABLE</span>
                  )}
                  {isLinked && (
                    <span style={{ fontSize: 8, color: 'var(--text-3)' }}>
                      {p.linked_connections_count} connection{p.linked_connections_count !== 1 ? 's' : ''}
                    </span>
                  )}
                </div>
                <div className="flex gap-1 flex-shrink-0">
                  <button
                    onClick={() => {
                      setEditingProfileId(p.id)
                      setProfileForm({ name: p.name, auth_type: p.auth_type, credentials: {}, discoverable: p.discoverable })
                      setShowProfileForm(true)
                    }}
                    style={{ fontSize: 9, color: 'var(--text-3)', background: 'none', border: '1px solid var(--border)',
                      borderRadius: 2, padding: '2px 6px', cursor: 'pointer' }}>
                    Edit
                  </button>
                  <button
                    onClick={async () => {
                      if (isLinked) {
                        if (!window.confirm(`This profile is used by ${p.linked_connections_count} connection(s). Deleting it will unlink them. Continue?`)) return
                      }
                      await fetch(`${BASE}/api/credential-profiles/${p.id}`, {
                        method: 'DELETE', headers: { ...authHeaders() }
                      })
                      fetchProfiles()
                    }}
                    style={{ fontSize: 9, color: 'var(--red)', background: 'none', border: 'none', cursor: 'pointer', padding: '2px 4px' }}>
                    ✕
                  </button>
                </div>
              </div>
            )
          })}
          {profiles.filter(p => p.name !== '__no_credential__').length === 0 && !showProfileForm && (
            <div style={{ fontSize: 10, color: 'var(--text-3)', padding: '8px 0' }}>
              No profiles yet — create one above, then link it to connections instead of entering credentials per-connection.
            </div>
          )}
        </div>
      </div>
      {/* ── end Credential Profiles ─────────────────────────────────────── */}
```

### 1c — Add editingProfileId state to ConnectionsTab state declarations

FIND (exact):
```
  const [showProfileForm, setShowProfileForm] = useState(false)
  const [profileForm, setProfileForm] = useState({ name: '', auth_type: 'ssh_key', credentials: {} })
  const [profilesOpen, setProfilesOpen] = useState(false)
```

REPLACE WITH:
```
  const [showProfileForm, setShowProfileForm] = useState(false)
  const [editingProfileId, setEditingProfileId] = useState(null)
  const [profileForm, setProfileForm] = useState({ name: '', auth_type: 'ssh', credentials: {}, discoverable: false })
```

(Remove the `profilesOpen` state — the section is now always visible.)

---

## Version bump
Update VERSION: 2.27.1 → 2.27.2

## Commit
```bash
git add -A
git commit -m "feat(ui): v2.27.2 credential profiles tab overhaul — seq_id, all auth types, prominent section"
git push origin main
```
