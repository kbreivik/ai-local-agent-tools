# CC PROMPT — v2.31.15 — feat(windows): real WinRM collector + auth-verified discovery test

## What this does
The Windows platform is currently a stub — the UI accepts Windows connections
and credential profiles, but the collector never actually calls WinRM and the
discovery test endpoint only checks port reachability. User verified NTLM
works end-to-end via pywinrm from the agent-01 host, so the only remaining
gap is wiring it into DEATHSTAR.

This prompt does four small things:

1. Add `pywinrm>=0.5.0` to `requirements.txt` so the runtime image can call
   WinRM.
2. Replace the `WindowsCollector._collect_sync()` stub with a real poll
   (hostname, uptime, CPU, memory, disks, critical services) modelled on
   the vm_hosts collector but in PowerShell.
3. Add a shared `_winrm_run()` helper that handles credential resolution
   (profile → inline), transport selection (ntlm | basic | kerberos),
   http/https, and logging.
4. Upgrade `/api/discovery/test` Windows branch from port-check to a real
   authenticated `hostname; Get-Date` call, so "Test" in the UI actually
   proves the credentials work.

Scope intentionally stops short of a `win_exec` agent tool — that's v2.31.16
once polling is verified in the live dashboard.

---

## Change 1 — `requirements.txt`

Open `requirements.txt`. Add one line, alphabetically near `paramiko`:

```
pywinrm>=0.5.0
```

(`pywinrm` pulls in `requests`, `requests-ntlm`, `pyspnego` transitively —
those are already supported on slim-bookworm.)

---

## Change 2 — `api/collectors/windows.py` — full rewrite

Replace the entire file with the following. The shape mirrors
`api/collectors/vm_hosts.py`: a pure-sync `_winrm_run`, a `_poll_one_host`,
and a `WindowsCollector` class that uses a ThreadPoolExecutor.

```python
"""WindowsCollector — polls all platform='windows' connections via WinRM.

Auth via a credential profile with auth_type='windows', or inline credentials
on the connection itself. Fields consumed from creds dict:
    username            — domain\\user or user@REALM or plain user
    password            — required
    winrm_auth_method   — 'ntlm' (default) | 'basic' | 'kerberos' | 'certificate'
    use_ssl             — bool; if true → port 5986 + https
"""
import asyncio
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from api.collectors.base import BaseCollector, Entity

log = logging.getLogger(__name__)

_DEFAULT_HTTP_PORT  = 5985
_DEFAULT_HTTPS_PORT = 5986

# Services we care about by default. Add more via settings later if needed.
_DEFAULT_WATCHED_SERVICES = ["WinRM", "Spooler", "W32Time", "LanmanServer", "Dnscache"]

# Single PowerShell script — results delimited by '=KEY=' lines. Keep output small.
_POLL_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'

function Emit($k, $v) { Write-Output "=$k="; Write-Output $v }

Emit HOSTNAME (hostname)
Emit UPTIME_S ([int]((Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime).TotalSeconds)
Emit OS_CAPTION ((Get-CimInstance Win32_OperatingSystem).Caption)
Emit OS_VERSION ((Get-CimInstance Win32_OperatingSystem).Version)

$mem = Get-CimInstance Win32_OperatingSystem
Emit MEM_TOTAL_KB ($mem.TotalVisibleMemorySize)
Emit MEM_FREE_KB  ($mem.FreePhysicalMemory)

$cpu = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
Emit CPU_PCT ([int]$cpu)

Emit DISKS_BEGIN ''
Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" |
    ForEach-Object {
        $pct = if ($_.Size -gt 0) { [int]((($_.Size - $_.FreeSpace) / $_.Size) * 100) } else { 0 }
        Write-Output ("{0}|{1}|{2}|{3}" -f $_.DeviceID, $_.Size, $_.FreeSpace, $pct)
    }
Emit DISKS_END ''

Emit SERVICES_BEGIN ''
$watched = 'WinRM','Spooler','W32Time','LanmanServer','Dnscache'
foreach ($s in $watched) {
    $svc = Get-Service -Name $s -ErrorAction SilentlyContinue
    if ($svc) { Write-Output ("{0}:{1}" -f $svc.Name, $svc.Status) }
    else      { Write-Output ("{0}:missing" -f $s) }
}
Emit SERVICES_END ''
"""


def _resolve_winrm_creds(conn, all_conns):
    """Return dict with username/password/transport/use_ssl from profile + overrides."""
    from api.db.credential_profiles import resolve_credentials_for_connection
    creds = resolve_credentials_for_connection(conn, all_conns) or {}
    transport = (creds.get("winrm_auth_method") or "ntlm").lower()
    # Normalise — pywinrm accepts: basic, plaintext, ntlm, kerberos, credssp, certificate
    if transport not in ("basic", "plaintext", "ntlm", "kerberos", "credssp", "certificate"):
        transport = "ntlm"
    return {
        "username":  creds.get("username", ""),
        "password":  creds.get("password", ""),
        "transport": transport,
        "use_ssl":   bool(creds.get("use_ssl", False)),
    }


def _winrm_run(host, port, username, password, script,
               transport="ntlm", use_ssl=False, read_timeout=30,
               operation_timeout=25):
    """Run a PowerShell script on a Windows host via WinRM. Returns stdout str.
    Raises RuntimeError on non-zero PS exit or auth failure.
    """
    import winrm

    scheme = "https" if use_ssl else "http"
    endpoint = f"{scheme}://{host}:{port}/wsman"

    t0 = time.monotonic()
    session = winrm.Session(
        endpoint,
        auth=(username, password),
        transport=transport,
        server_cert_validation="ignore" if use_ssl else "validate",
        read_timeout_sec=read_timeout,
        operation_timeout_sec=operation_timeout,
    )
    log.debug("WinRM exec → %s@%s:%d (%s) | cmd: %s",
              username, host, port, transport, script[:80].replace("\n", " "))

    result = session.run_ps(script)
    elapsed = int((time.monotonic() - t0) * 1000)
    stdout = result.std_out.decode("utf-8", errors="replace") if result.std_out else ""
    stderr = result.std_err.decode("utf-8", errors="replace") if result.std_err else ""

    if result.status_code != 0:
        raise RuntimeError(f"WinRM exit {result.status_code}: {stderr[:200] or stdout[:200]}")

    log.debug("WinRM exec ← %s@%s:%d | %d bytes | %dms",
              username, host, port, len(stdout), elapsed)
    return stdout


def _parse_poll_output(output, label, host):
    """Parse delimited sections from _POLL_PS into a card dict."""
    sections: dict = {}
    current = None
    lines: list = []
    for line in output.splitlines():
        s = line.strip()
        if s.startswith("=") and s.endswith("=") and len(s) > 2:
            if current is not None:
                sections[current] = lines
            current = s.strip("=")
            lines = []
        else:
            if current is not None:
                lines.append(line.rstrip())
    if current is not None:
        sections[current] = lines

    def first(k):
        v = sections.get(k) or [""]
        return v[0] if v else ""

    def _int(k, default=0):
        try:
            return int(first(k).strip())
        except (ValueError, TypeError):
            return default

    hostname    = first("HOSTNAME")
    os_caption  = first("OS_CAPTION")
    os_version  = first("OS_VERSION")
    uptime_secs = _int("UPTIME_S")

    mem_total_kb = _int("MEM_TOTAL_KB")
    mem_free_kb  = _int("MEM_FREE_KB")
    mem_used_kb  = max(0, mem_total_kb - mem_free_kb)
    mem_pct = round((mem_used_kb / mem_total_kb) * 100) if mem_total_kb else 0

    cpu_pct = _int("CPU_PCT")

    disks = []
    in_disks = False
    for line in output.splitlines():
        s = line.strip()
        if s == "=DISKS_BEGIN=":
            in_disks = True; continue
        if s == "=DISKS_END=":
            in_disks = False; continue
        if in_disks and "|" in s:
            parts = s.split("|")
            if len(parts) == 4:
                try:
                    disks.append({
                        "mountpoint":  parts[0],
                        "total_bytes": int(parts[1]),
                        "avail_bytes": int(parts[2]),
                        "used_bytes":  int(parts[1]) - int(parts[2]),
                        "usage_pct":   int(parts[3]),
                    })
                except ValueError:
                    continue

    services: dict = {}
    in_svc = False
    for line in output.splitlines():
        s = line.strip()
        if s == "=SERVICES_BEGIN=":
            in_svc = True; continue
        if s == "=SERVICES_END=":
            in_svc = False; continue
        if in_svc and ":" in s:
            name, state = s.split(":", 1)
            services[name.strip()] = state.strip()

    def _fmt_uptime(secs):
        secs = int(secs)
        d = secs // 86400; secs %= 86400
        h = secs // 3600;  secs %= 3600
        m = secs // 60
        if d: return f"{d}d {h}h"
        if h: return f"{h}h {m}m"
        return f"{m}m"

    max_disk_pct = max((d["usage_pct"] for d in disks), default=0)

    dot = "green"
    problems = []
    if max_disk_pct >= 90:
        dot = "red"; problems.append(f"disk {max_disk_pct}% full")
    elif max_disk_pct >= 80:
        dot = "amber"; problems.append(f"disk {max_disk_pct}% used")
    if mem_pct >= 90:
        dot = "red"; problems.append(f"memory {mem_pct}%")
    elif mem_pct >= 80 and dot == "green":
        dot = "amber"; problems.append(f"memory {mem_pct}%")
    if services.get("WinRM", "").lower() != "running":
        dot = "red"; problems.append("WinRM not running")

    return {
        "id": label, "label": label, "host": host,
        "hostname":    hostname,
        "os":          os_caption,
        "os_version":  os_version,
        "uptime_secs": uptime_secs,
        "uptime_fmt":  _fmt_uptime(uptime_secs),
        "cpu_pct":     cpu_pct,
        "mem_total_bytes": mem_total_kb * 1024,
        "mem_used_bytes":  mem_used_kb  * 1024,
        "mem_pct":     mem_pct,
        "disks":       disks,
        "services":    services,
        "dot":         dot,
        "problem":     problems[0] if problems else None,
    }


def _poll_one_host(conn, all_conns):
    host  = conn.get("host", "")
    label = conn.get("label") or host
    # Resolve port: explicit on conn, else 5986 if use_ssl, else 5985
    creds = _resolve_winrm_creds(conn, all_conns)
    port  = conn.get("port") or (_DEFAULT_HTTPS_PORT if creds["use_ssl"] else _DEFAULT_HTTP_PORT)

    if not creds["username"] or not creds["password"]:
        return {
            "id": label, "label": label, "host": host,
            "connection_id": str(conn.get("id", "")),
            "dot": "red",
            "problem": "missing WinRM credentials (username/password)",
            "hostname": host, "os": "", "uptime_fmt": "",
            "cpu_pct": 0, "mem_pct": 0, "disks": [], "services": {},
        }

    try:
        output = _winrm_run(
            host, port,
            creds["username"], creds["password"],
            _POLL_PS,
            transport=creds["transport"],
            use_ssl=creds["use_ssl"],
        )
        result = _parse_poll_output(output, label, host)
        result["connection_id"] = str(conn.get("id", ""))
        result["config"]        = conn.get("config") or {}
        result["entity_id"]     = label
        return result
    except Exception as e:
        log.warning("WindowsCollector: %s (%s) failed: %s", label, host, e)
        return {
            "id": label, "label": label, "host": host,
            "connection_id": str(conn.get("id", "")),
            "dot": "red",
            "problem": str(e)[:200],
            "hostname": host, "os": "", "uptime_fmt": "",
            "cpu_pct": 0, "mem_pct": 0, "disks": [], "services": {},
        }


class WindowsCollector(BaseCollector):
    component = "windows"
    platforms = ["windows"]

    def __init__(self):
        super().__init__()
        self.interval = int(os.environ.get("WINDOWS_POLL_INTERVAL", "60"))

    async def poll(self) -> dict:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict:
        from api.connections import get_all_connections_for_platform
        try:
            all_conns = get_all_connections_for_platform("windows")
        except Exception as e:
            return {"health": "error", "hosts": [], "error": str(e)}

        if not all_conns:
            return {"health": "unconfigured", "hosts": []}

        hosts = []
        with ThreadPoolExecutor(max_workers=min(len(all_conns), 8)) as pool:
            futures = {pool.submit(_poll_one_host, c, all_conns): c for c in all_conns}
            for future in as_completed(futures):
                try:
                    hosts.append(future.result())
                except Exception as e:
                    c = futures[future]
                    hosts.append({
                        "id": c.get("label", c.get("host")),
                        "label": c.get("label", c.get("host")),
                        "host": c.get("host"),
                        "dot": "red", "problem": str(e)[:200],
                    })

        total = len(hosts)
        red   = sum(1 for h in hosts if h.get("dot") == "red")
        ok    = total - red
        health = "healthy" if red == 0 else ("degraded" if ok > 0 else "error")
        return {"health": health, "hosts": hosts, "total": total, "ok": ok, "issues": red}

    def to_entities(self, state: dict):
        _DOT_STATUS = {"green": "healthy", "amber": "degraded",
                       "red": "error", "grey": "unknown"}
        entities = []
        for h in state.get("hosts", []):
            label = h.get("label") or h.get("id") or "unknown"
            disks = h.get("disks", [])
            max_disk_pct = max((d.get("usage_pct", 0) for d in disks), default=0)
            entities.append(Entity(
                id=label,
                label=label,
                component=self.component,
                platform="windows",
                section="COMPUTE",
                status=_DOT_STATUS.get(h.get("dot", "grey"), "unknown"),
                last_error=h.get("problem"),
                metadata={
                    "host":         h.get("host", ""),
                    "os":           h.get("os", ""),
                    "os_version":   h.get("os_version", ""),
                    "cpu_pct":      h.get("cpu_pct"),
                    "mem_pct":      h.get("mem_pct"),
                    "uptime_fmt":   h.get("uptime_fmt", ""),
                    "max_disk_pct": max_disk_pct,
                },
            ))
        return entities if entities else super().to_entities(state)
```

---

## Change 3 — `api/routers/discovery.py` — real WinRM auth in `/test`

Open `api/routers/discovery.py`. Find the Windows branch inside
`test_device()` — it currently does a bare `httpx.get(f"{scheme}://{host}:{winrm_port}/wsman")`.
Replace that branch with an authenticated call using the same helper the
collector uses:

Find:

```python
        elif auth_type == "windows" or platform == "windows":
            import httpx, urllib3
            urllib3.disable_warnings()
            winrm_port = port or 5985
            scheme = "https" if winrm_port == 5986 else "http"
            try:
                r = httpx.get(f"{scheme}://{host}:{winrm_port}/wsman",
                              verify=False, timeout=8)
                ok = r.status_code < 500
                message = f"WinRM HTTP {r.status_code}"
            except Exception as e:
                ok = False
                message = str(e)[:80]
```

Replace with:

```python
        elif auth_type == "windows" or platform == "windows":
            # Real auth test via pywinrm — runs hostname + Get-Date on target
            from api.collectors.windows import _winrm_run
            winrm_transport = (creds.get("winrm_auth_method") or "ntlm").lower()
            use_ssl         = bool(creds.get("use_ssl", False))
            winrm_port      = port if port else (5986 if use_ssl else 5985)
            username        = creds.get("username", "")
            password        = creds.get("password", "")
            if not username or not password:
                ok = False
                message = "missing username or password in profile"
            else:
                try:
                    out = await asyncio.to_thread(
                        _winrm_run, host, winrm_port, username, password,
                        "hostname; Get-Date -Format 'o'",
                        winrm_transport, use_ssl, 10, 8,
                    )
                    first_line = (out.splitlines() or [""])[0].strip()
                    ok = bool(first_line)
                    message = f"WinRM OK: {first_line[:40]}" if ok else "WinRM returned empty"
                except Exception as e:
                    ok = False
                    # Surface auth vs reachability distinction where possible
                    msg = str(e)
                    if "401" in msg or "unauthorized" in msg.lower():
                        message = f"WinRM auth failed: {msg[:100]}"
                    elif "refused" in msg.lower() or "timed out" in msg.lower():
                        message = f"WinRM unreachable: {msg[:100]}"
                    else:
                        message = f"WinRM error: {msg[:100]}"
```

The `asyncio` import is already at the top of the endpoint. The `_winrm_run`
import is deferred inside the branch so the rest of the discovery module
doesn't hard-fail if pywinrm is somehow missing.

---

## Change 4 — expose the CPU% + disks in the dashboard snapshot

(No file change required — the existing `ConnectionSectionCards` in
`gui/src/App.jsx` renders `hosts` with the standard InfraCard shape and will
display `cpu_pct` / `mem_pct` / `uptime_fmt` out of the box. Skip this step —
listed only so CC doesn't guess there's more frontend work to do.)

---

## Commit

```
git add -A
git commit -m "feat(windows): v2.31.15 real WinRM collector + auth-verified discovery test"
git push origin main
```

---

## How to test

After CI builds and you deploy v2.31.15 on agent-01:

1. **Verify pywinrm is in the image**:
   ```bash
   docker exec hp1_agent python -c "import winrm; print(winrm.__version__)"
   # expect: 0.5.x
   ```

2. **Run the auth-verified discovery test via UI**: Settings → Connections
   → Discovered → select your Windows host → Test. Should return
   `WinRM OK: <HOSTNAME>` (not a bare HTTP 405). If it returns
   `WinRM auth failed: 401`, the credential profile has wrong password or
   wrong transport — double-check `winrm_auth_method=ntlm` in the profile.

3. **Same test via curl** (if you prefer the backend directly):
   ```bash
   curl -s -b /tmp/hp1.cookies -X POST \
     http://192.168.199.10:8000/api/discovery/test \
     -H 'Content-Type: application/json' \
     -d '{"host":"192.168.199.51","port":5985,"platform":"windows","profile_id":"<UUID>"}' \
     | python3 -m json.tool
   ```
   Expect `"ok": true, "message": "WinRM OK: <hostname>"`.

4. **Force a collector poll and inspect the snapshot**:
   ```bash
   curl -s -b /tmp/hp1.cookies http://192.168.199.10:8000/api/collectors/windows/poll -X POST
   sleep 2
   curl -s -b /tmp/hp1.cookies http://192.168.199.10:8000/api/status \
     | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('windows',{}),indent=2))"
   ```
   Expect `health: healthy`, one entry per Windows host with real hostname,
   CPU%, memory%, disks, and services.

5. **Dashboard card**: the Windows host should now render in the COMPUTE
   section with the normal VM-card shape (green dot, uptime, CPU, memory).
   Red dot + `problem` text if anything fails.

---

## Notes

- Kerberos transport needs a working `krb5.conf` in the container. NTLM is
  recommended for LAN setups — it needs no extra config.
- If you later want to widen the watched services list, add a settings key
  `windowsWatchedServices` (seeded via `api/routers/settings.py`) and inject
  into the PS script. Not in this prompt — keep scope tight.
- No agent tool (`win_exec`) yet. That's v2.31.16 once polling is confirmed
  live.
- The change detection + metric_samples + entity_history writes that
  `vm_hosts.py` does are intentionally **not** mirrored here — they can be
  added later in a small follow-up once you decide what Windows metrics
  matter for trending. Current scope is: get a green dot in the dashboard.
