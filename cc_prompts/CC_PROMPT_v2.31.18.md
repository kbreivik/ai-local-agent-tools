# CC PROMPT — v2.31.18 — docs(windows): WINDOWS_SETUP.md + README index entry

## What this does
We spent v2.31.15 → v2.31.17 learning exactly what a least-privilege
Windows user needs to be monitored by DEATHSTAR without granting admin,
widening SDDLs, or poking WMI namespace ACLs. Capture that learning as a
permanent setup guide so the next Windows host takes 10 minutes, not 2
hours, and future operators don't have to re-derive the endpoint vs SDDL
vs library distinction.

Two files:
1. **New**: `WINDOWS_SETUP.md` at repo root — matches the existing
   `TOPIC.md` convention (AGENT_HARNESS.md, HP1_DATABASE_LAYER.md, etc.).
2. **Edit**: `README.md` — add one line under the existing doc index.

No code changes. No version-bump-gated features. Pure docs.

---

## Change 1 — create `WINDOWS_SETUP.md`

Write this file at `D:/claude_code/ai-local-agent-tools/WINDOWS_SETUP.md`
(full contents below, verbatim):

````markdown
# Windows Host Setup — DEATHSTAR Monitoring

How to prepare a Windows host so DEATHSTAR's `windows` collector can
monitor it with a **least-privilege local account** — no Administrator
membership, no SDDL widening, no WMI/DCOM grants.

Works on Windows Server 2016+, Windows 10/11 Pro/Enterprise.
DEATHSTAR 2.31.17 or later required on the server side (uses pypsrp /
PSRP; earlier versions used pywinrm which needs different Windows-side
setup).

---

## Quick summary

| Layer | What you need | Notes |
|---|---|---|
| WinRM service | Running, HTTP listener on 5985 | `winrm quickconfig` one-liner |
| Firewall | Allow inbound 5985/tcp (or 5986 for HTTPS) | From agent-01 subnet only |
| User account | Local or domain | Local is simpler; both work |
| Group membership | `Remote Management Users` (required) + `Performance Monitor Users` (for CPU%) | Both are built-in groups |
| Auth transport | NTLM (default) or Kerberos | Basic works but requires HTTPS |
| DEATHSTAR connection | Credential profile `auth_type=windows`, connection `platform=windows` | Set `winrm_auth_method=ntlm` |

**You do NOT need:**
- Local Administrator membership
- Changes to `winrm configsddl default` (the WinRS cmd shell ACL)
- `LocalAccountTokenFilterPolicy` registry tweak
- WMI namespace ACL grants via `wmimgmt.msc`
- DCOM launch/activation permissions via `dcomcnfg`

Any guide that tells you to do those was written for pywinrm (WinRS-based)
or for WMI-using collectors. DEATHSTAR uses pypsrp over the PSRP
`Microsoft.PowerShell` endpoint and a WMI-free poll script — none of the
above is relevant.

---

## Step 1 — enable WinRM on the Windows host

Open PowerShell **as Administrator** on the target box. Run:

```powershell
winrm quickconfig -Force
```

This one command:
- Starts the `WinRM` service and sets it to Automatic
- Creates a default HTTP listener on port 5985
- Opens Windows Firewall for the `Windows Remote Management (HTTP-In)`
  rule (scoped to domain + private profiles by default)

Verify:

```powershell
Get-Service WinRM            # Status: Running, StartType: Automatic
winrm enumerate winrm/config/listener
```

You should see one listener with `Transport = HTTP`, `Port = 5985`.

### Optional: HTTPS (port 5986)

For hosts on untrusted networks, add an HTTPS listener:

```powershell
# Replace with your cert thumbprint
$t = (Get-ChildItem Cert:\LocalMachine\My | Where-Object { $_.Subject -like "*YOUR-HOST*" } | Select-Object -First 1).Thumbprint
winrm create winrm/config/listener?Address=*+Transport=HTTPS '@{Hostname="YOUR-HOST";CertificateThumbprint="'$t'"}'
New-NetFirewallRule -Name "WinRM-HTTPS" -DisplayName "WinRM HTTPS" -Protocol TCP -LocalPort 5986 -Action Allow
```

Then set `use_ssl=true` and `port=5986` in the DEATHSTAR credential
profile.

---

## Step 2 — create the monitoring account

Local account (recommended for homelab / standalone boxes):

```powershell
# Adjust name + password; use a strong password manager generator
$pw = Read-Host "Password for ai-agent" -AsSecureString
New-LocalUser -Name "ai-agent" -Password $pw `
              -FullName "DEATHSTAR monitoring agent" `
              -Description "Read-only WinRM monitoring — no interactive login" `
              -AccountNeverExpires `
              -UserMayNotChangePassword
```

Domain account: create via AD Users & Computers or `New-ADUser`. Same
group-membership rules below apply.

---

## Step 3 — grant the minimum groups

```powershell
Add-LocalGroupMember -Group "Remote Management Users"   -Member "ai-agent"
Add-LocalGroupMember -Group "Performance Monitor Users" -Member "ai-agent"
Add-LocalGroupMember -Group "Event Log Readers"         -Member "ai-agent"
```

What each does:

| Group | Unlocks |
|---|---|
| Remote Management Users | Read + Invoke on the `Microsoft.PowerShell` PSSessionConfiguration — i.e. pypsrp can open a PS runspace |
| Performance Monitor Users | `Get-Counter \Processor(_Total)\% Processor Time` for the CPU% metric |
| Event Log Readers | `Get-WinEvent` for reading event logs (reserved for a future collector feature) |

Verify:

```powershell
Get-LocalGroupMember "Remote Management Users"
Get-LocalGroupMember "Performance Monitor Users"
Get-LocalGroupMember "Event Log Readers"
```

`ai-agent` should appear in all three.

---

## Step 4 — verify from the Windows side

```powershell
# Endpoint ACL (informational — do NOT modify)
(Get-Item WSMan:\localhost\Service\RootSDDL).Value

# PSSessionConfiguration — ai-agent should appear here
Get-PSSessionConfiguration Microsoft.PowerShell | Select-Object Name, Permission
```

Expected `Permission` output contains
`AI-AGENT AccessAllowed` (or your user's name).

If `Permission` does NOT show your user, the `Remote Management Users`
group membership didn't take effect — restart the WinRM service:

```powershell
Restart-Service WinRM
```

---

## Step 5 — verify from DEATHSTAR side

From agent-01 (or any host with network reach to the Windows box):

```bash
# 1. Port reachability — expect 405 Method Not Allowed
curl -v http://192.168.199.51:5985/wsman
```

A `405` response from `Microsoft-HTTPAPI/2.0` means WinRM is listening and
rejecting GET (it only accepts POST). That's the correct healthy response.

```bash
# 2. Full auth + session from DEATHSTAR container
docker exec hp1_agent python -c "
from pypsrp.client import Client
c = Client(server='192.168.199.51', port=5985, username='ai-agent',
           password='REDACTED', auth='ntlm', ssl=False)
out, streams, errs = c.execute_ps('hostname; whoami; Get-Date -Format o')
print('had_errors:', errs)
print(out)
"
```

Expected output: hostname, `DOMAIN\ai-agent` (or `HOSTNAME\ai-agent` for
local), current timestamp. `had_errors: False`.

---

## Step 6 — add the connection in DEATHSTAR

1. Settings → Connections → **Credential Profiles** → New Profile
   - Name: `windows-<host-label>` (e.g. `windows-ai-agent`)
   - Auth type: `windows`
   - Username: `ai-agent` (or `DOMAIN\ai-agent` for domain accounts)
   - Password: the password from Step 2
   - WinRM auth method: `ntlm`
   - Use SSL: off (on for HTTPS listener)
   - Account type: `Local account` (or Domain/Service/gMSA as applicable —
     this is informational, does not change behaviour)

2. Settings → Connections → **Connections** → New Connection
   - Platform: `windows`
   - Label: `MS-S1` (whatever you want in the dashboard)
   - Host: IP or hostname
   - Port: `5985` (or `5986` for HTTPS)
   - Credential Profile: the one just created

3. Click **Test** on the new connection row. Expect:
   `WinRM OK: <actual-hostname>` with a green checkmark.

4. Wait 60s for the next collector cycle, or force a poll:
   ```bash
   curl -s -b /tmp/hp1.cookies -X POST \
     http://192.168.199.10:8000/api/collectors/windows/poll
   ```

5. The WINDOWS section on the dashboard should now show a green card for
   this host with hostname, uptime, CPU%, memory%, disks, and WinRM
   service status.

---

## Troubleshooting

### `Connection refused` / `No route to host`
WinRM service not running, or firewall blocking 5985. Confirm on Windows
host: `Get-Service WinRM` and
`Get-NetFirewallRule -DisplayGroup "Windows Remote Management" | Select-Object Enabled, Profile, Direction, Action`.

### `401 Unauthorized`
One of:
- Wrong password in the credential profile
- NTLM disabled on the target host — check
  `Get-Item WSMan:\localhost\Service\Auth` — `Negotiate: true` and
  `Kerberos: true` are fine for NTLM
- Using `basic` auth over HTTP with `AllowUnencrypted=false` (default).
  Either switch to `ntlm` (recommended) or enable HTTPS

### `Access is denied. wsmanfault_code: 5`
The user authenticated but isn't permitted to open the requested endpoint.
Check:
- `Get-LocalGroupMember "Remote Management Users"` — must include the
  monitoring account
- `Get-PSSessionConfiguration Microsoft.PowerShell | fl Permission` —
  must show the account with AccessAllowed
- `Restart-Service WinRM` if group membership was just added — ACL is
  cached

### `The WS-Management service cannot process the request. The resource URI ...`
Wrong endpoint. This can happen if something on the DEATHSTAR side is
using pywinrm instead of pypsrp. Confirm:
```bash
docker exec hp1_agent python -c "import pypsrp; print(pypsrp.__version__)"
docker exec hp1_agent python -c "import winrm" 2>&1 | head -1
# expect: ModuleNotFoundError: No module named 'winrm'
```
If `winrm` imports, you're on an old image — pull the current `:latest`
and redeploy.

### Connection test green, but collector returns error
Check the specific error:
```bash
curl -s -b /tmp/hp1.cookies http://192.168.199.10:8000/api/entities \
  | python3 -c "import sys,json;[print(json.dumps(e,indent=2)) for e in json.load(sys.stdin) if e['component']=='windows']"
```
The `last_error` field names the specific cmdlet that failed. Common
cause: the user isn't in `Performance Monitor Users`, so `Get-Counter`
fails. Add the group and restart WinRM.

### Domain account lockout concerns
`Remote Management Users` membership does not by itself change lockout
risk. But: if the DEATHSTAR credential profile has a stale password, the
collector polls every 60s — that's a lot of failed logins before anyone
notices. For domain accounts:
- Rotate the password via the credential profile's RotationTestModal
  (Settings → Credential Profiles → Edit → Save triggers a pre-save
  rotation test)
- Or set `rotationMaxParallel=1` and `rotationWindowsDelayMs=5000` in
  Settings → General to slow rotation testing and avoid AD lockout
  thresholds

---

## What's not covered (yet)

- `win_exec` agent tool (run ad-hoc PowerShell against the host from the
  agent) — planned for a future release
- Remote event log tail in the card UI — planned, relies on Event Log
  Readers which this doc already adds
- Kerberos/AD integration notes — same flow applies, just use
  `winrm_auth_method=kerberos` and ensure `krb5.conf` is present in the
  container; separate doc when needed
- gMSA accounts — same as domain accounts but password rotation is
  handled by AD; credential profile should store the service account
  mapping, not a password

---

## Reference: file locations in DEATHSTAR

| File | Role |
|---|---|
| `api/collectors/windows.py` | `WindowsCollector`, `_winrm_run`, `_POLL_PS` |
| `api/routers/discovery.py` | `/api/discovery/test` — uses `_winrm_run` for the UI's Test button |
| `gui/src/components/OptionsModal.jsx` | `PLATFORM_AUTH` entry for `windows` — form fields |
| `requirements.txt` | `pypsrp>=0.8.0` (library this all depends on) |
````

---

## Change 2 — add one line to `README.md`

Open `README.md`. Find the documentation index section (there's likely a
list of `*.md` files with short descriptions — if not, find the section
that mentions other docs and extend it).

Add a row/line entry for the new doc. Pattern should match what's already
there. If the file has no doc index, add a short "Documentation" section
near the top with the existing docs + the new one:

```markdown
## Documentation

- [`README.md`](README.md) — this file
- [`HOW_TO_USE.md`](HOW_TO_USE.md) — getting-started operator guide
- [`AGENT_HARNESS.md`](AGENT_HARNESS.md) — agent loop + prompt architecture
- [`HP1_DATABASE_LAYER.md`](HP1_DATABASE_LAYER.md) — DB schema reference
- [`WINDOWS_SETUP.md`](WINDOWS_SETUP.md) — Windows host prep for the WinRM collector
- [`ROADMAP.md`](ROADMAP.md) — planned work
- [`TODO.md`](TODO.md) — active TODOs
```

Read the existing README structure first and insert the new line
consistently. Don't rewrite the whole README.

---

## Commit

```
git add -A
git commit -m "docs(windows): v2.31.18 WINDOWS_SETUP.md + README index entry"
git push origin main
```

---

## How to test

Docs-only change. Verification is just:

1. `cat WINDOWS_SETUP.md` (or GitHub rendering) — reads cleanly end to end.
2. `grep -l WINDOWS_SETUP README.md` returns a match.
3. No backend/frontend changes to regress.

---

## Notes

- Keep this file **authoritative**. When we add the `win_exec` tool,
  event-log tail, or Kerberos support, update this doc in the same
  commit that ships the feature. Stale setup docs are worse than missing
  ones.
- Don't duplicate this content into a Bookstack page yet — the Bookstack
  sync (v2.31.0) pulls content INTO DEATHSTAR, not the other way. If we
  later want this visible inside the Docs tab for operators, a separate
  prompt can mirror it into the `doc_chunks` table via the bookstack
  path, or we add a markdown-file ingestion hook.
