# CC PROMPT — v2.31.21 — fix(windows): OS name, uptime, and WinRM false-positive in collector

## What this does
Three bugs in `api/collectors/windows.py`, all visible on the MS-S1 card
right now:

1. **"Windows 10 Pro" instead of "Windows 11 Pro"** — the registry key
   `ProductName` at `HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion`
   was never updated by Microsoft for Windows 11. Build 22000+ is
   Windows 11, but `ProductName` still says "Windows 10". Need to check
   `CurrentBuildNumber` and correct the name in the poll script.

2. **Uptime "0m"** — `[Environment]::TickCount64` returns 0 inside a PSRP
   remote session (constrained .NET host). Need a fallback that works in
   the remote context.

3. **"WinRM not running" (false positive)** — `Get-Service -Name WinRM`
   returns nothing inside the PSRP session on this Win11 25H2 build
   (also missing: W32Time, LanmanServer). The collector then marks
   `dot = "red"` and `problem = "WinRM not running"`. But the collector
   just *connected via WinRM* to run the script — WinRM is provably
   running. The health check is wrong.

All three fixes are in `api/collectors/windows.py` — one in `_POLL_PS`
(the PowerShell script) and one in `_parse_poll_output` (the Python
parser).

Version bump: 2.31.20 → 2.31.21

---

## Change 1 — `_POLL_PS` PowerShell script fixes (OS name + uptime)

Open `api/collectors/windows.py`. Find the `_POLL_PS` string.

### Fix 1a: Windows 11 detection

Find this block inside `_POLL_PS`:

```powershell
Emit OS_CAPTION ($prod)
```

Replace with:

```powershell
# Microsoft never updated ProductName for Win11 — still says "Windows 10".
# Build 22000+ is Windows 11. Correct the display name.
if ($curr -and [int]$curr -ge 22000 -and $prod -match 'Windows 10') {
    $prod = $prod -replace 'Windows 10', 'Windows 11'
}
Emit OS_CAPTION ($prod)
```

### Fix 1b: Uptime fallback

Find this block inside `_POLL_PS`:

```powershell
try { $uptimeMs = [Environment]::TickCount64 } catch { $uptimeMs = 0 }
Emit UPTIME_S   ([int]([int64]$uptimeMs / 1000))
```

Replace with:

```powershell
# Primary: [Environment]::TickCount64 (works locally, may return 0 in PSRP)
# Fallback: parse net stats workstation for "Statistics since" date
$uptimeMs = 0
try { $uptimeMs = [int64][Environment]::TickCount64 } catch {}
if ($uptimeMs -le 0) {
    try {
        $bootLine = (net stats workstation 2>$null | Select-String 'Statistics since')
        if ($bootLine) {
            $bootStr = ($bootLine -replace 'Statistics since\s*', '').Trim()
            $bootDt  = [datetime]::Parse($bootStr)
            $uptimeMs = [int64](([datetime]::Now - $bootDt).TotalMilliseconds)
        }
    } catch {}
}
Emit UPTIME_S   ([int]([math]::Max(0, [int64]$uptimeMs / 1000)))
```

---

## Change 2 — `_parse_poll_output` Python fix (WinRM false-positive)

Find this block in the `_parse_poll_output` function:

```python
    if services.get("WinRM", "").lower() != "running":
        dot = "red"; problems.append("WinRM not running")
```

Replace with:

```python
    # NOTE: Do NOT check WinRM service status here. The collector already
    # proved WinRM is running by successfully connecting via PSRP to execute
    # this poll script. Get-Service -Name WinRM returns "missing" inside
    # PSRP sessions on some Windows 11 builds — a false positive.
    # WinRM health is implicitly "running" if we reached this parser.
```

This means if the poll succeeded, WinRM status is always implicitly
healthy. If WinRM were actually down, `_winrm_run` would raise before we
ever get to parsing, and `_poll_one_host` catches that in its except
block and sets `dot = "red"` with the actual connection error.

Also find the `_DEFAULT_WATCHED_SERVICES` constant near the top:

```python
_DEFAULT_WATCHED_SERVICES = ["WinRM", "Spooler", "W32Time", "LanmanServer", "Dnscache"]
```

This constant isn't actually used in the PS script (the script has its
own hardcoded `$watched` list). But update it for consistency:

```python
_DEFAULT_WATCHED_SERVICES = ["Spooler", "W32Time", "LanmanServer", "Dnscache"]
```

And in `_POLL_PS`, update the `$watched` list too — remove WinRM from
the service query since we don't need it:

Find in `_POLL_PS`:
```powershell
$watched = 'WinRM','Spooler','W32Time','LanmanServer','Dnscache'
```

Replace with:
```powershell
$watched = 'Spooler','W32Time','LanmanServer','Dnscache'
```

---

## Version bump

Update VERSION: 2.31.20 → 2.31.21

---

## Commit

```
git add -A
git commit -m "fix(windows): v2.31.21 OS name Win11 detection, uptime fallback, remove WinRM false-positive"
git push origin main
```

---

## How to test

After deploy on agent-01, wait one collector cycle (60s) then:

```bash
curl -s -b /tmp/hp1.cookies http://192.168.199.10:8000/api/dashboard/summary \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
h = d['windows']['hosts'][0]
print('OS:     ', h.get('os'))
print('Uptime: ', h.get('uptime_fmt'), '(secs:', h.get('uptime_secs'), ')')
print('Dot:    ', h.get('dot'))
print('Problem:', h.get('problem'))
print('Svc:    ', h.get('services'))
"
```

Expected:
- OS: `Windows 11 Pro` (not "Windows 10 Pro")
- Uptime: real value like `4d 2h` (not "0m")
- Dot: `green` (not "red") — assuming mem/disk are fine; MEM was 21% last
  check so should be green
- Problem: `None`
- Services: WinRM no longer in the list; remaining services may still
  show "missing" for W32Time/LanmanServer (PSRP session limitation) but
  those don't affect health

Dashboard card should show a green dot with real uptime and "Windows 11 Pro".
