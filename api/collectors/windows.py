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
_DEFAULT_WATCHED_SERVICES = ["Spooler", "W32Time", "LanmanServer", "Dnscache"]

# WMI-free poll script.
# Works for a non-admin Windows user who is in:
#   - Remote Management Users        (WinRM access)
#   - Performance Monitor Users      (Get-Counter / PDH)
#   - Event Log Readers              (not used yet; reserved for future)
# plus PSSessionConfiguration Read + Invoke on Microsoft.PowerShell.
#
# Intentionally avoids Get-CimInstance Win32_* — those require DCOM +
# Root\CIMV2 namespace permission which least-privilege users don't have.
_POLL_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'

function Emit($k, $v) { Write-Output "=$k="; Write-Output $v }

# --- Hostname + uptime + OS ------------------------------------------------
Emit HOSTNAME   $env:COMPUTERNAME

# TickCount64 is milliseconds since boot; available on all Windows versions
# since 2008 R2. No WMI, no admin.
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

# Registry read — no admin needed, any authenticated user can read.
$regPath = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
$prod = (Get-ItemProperty -Path $regPath -Name 'ProductName'        -ErrorAction SilentlyContinue).ProductName
$dver = (Get-ItemProperty -Path $regPath -Name 'DisplayVersion'     -ErrorAction SilentlyContinue).DisplayVersion
$curr = (Get-ItemProperty -Path $regPath -Name 'CurrentBuildNumber' -ErrorAction SilentlyContinue).CurrentBuildNumber
$ubr  = (Get-ItemProperty -Path $regPath -Name 'UBR'                -ErrorAction SilentlyContinue).UBR
# Microsoft never updated ProductName for Win11 — still says "Windows 10".
# Build 22000+ is Windows 11. Correct the display name.
if ($curr -and [int]$curr -ge 22000 -and $prod -match 'Windows 10') {
    $prod = $prod -replace 'Windows 10', 'Windows 11'
}
Emit OS_CAPTION ($prod)
Emit OS_VERSION ("$curr.$ubr" + $(if ($dver) { " ($dver)" } else { "" }))

# --- Memory total + free via VB ComputerInfo (no WMI, no admin) ------------
try {
    Add-Type -AssemblyName 'Microsoft.VisualBasic' -ErrorAction SilentlyContinue
    $ci = New-Object Microsoft.VisualBasic.Devices.ComputerInfo
    $memTotalBytes = [int64]$ci.TotalPhysicalMemory
    $memFreeBytes  = [int64]$ci.AvailablePhysicalMemory
} catch {
    $memTotalBytes = 0
    $memFreeBytes  = 0
}
Emit MEM_TOTAL_BYTES $memTotalBytes
Emit MEM_FREE_BYTES  $memFreeBytes

# --- CPU via PDH perf counter (Performance Monitor Users required) --------
try {
    $cpuSample = (Get-Counter -Counter '\Processor(_Total)\% Processor Time' `
                  -SampleInterval 1 -MaxSamples 1 -ErrorAction Stop).CounterSamples[0].CookedValue
    $cpuPct = [int]$cpuSample
} catch {
    # Fallback: read via .NET PerformanceCounter API directly
    try {
        $pc = New-Object System.Diagnostics.PerformanceCounter('Processor', '% Processor Time', '_Total')
        $null = $pc.NextValue()  # first sample is always 0
        Start-Sleep -Milliseconds 500
        $cpuPct = [int]$pc.NextValue()
        $pc.Close()
    } catch { $cpuPct = -1 }
}
Emit CPU_PCT $cpuPct

# --- Disks via Get-PSDrive (no WMI, no admin) ------------------------------
Emit DISKS_BEGIN ''
Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue |
    Where-Object { $_.Used -ne $null -and ($_.Used + $_.Free) -gt 0 } |
    ForEach-Object {
        $total = [int64]($_.Used + $_.Free)
        $free  = [int64]$_.Free
        $pct   = if ($total -gt 0) { [int]((($total - $free) / $total) * 100) } else { 0 }
        Write-Output ("{0}:|{1}|{2}|{3}" -f $_.Name, $total, $free, $pct)
    }
Emit DISKS_END ''

# --- Watched services (Get-Service, no WMI) --------------------------------
Emit SERVICES_BEGIN ''
$watched = 'Spooler','W32Time','LanmanServer','Dnscache'
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
    # Normalise — pypsrp accepts: negotiate, ntlm, kerberos, basic, certificate, credssp
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
    """Run a PowerShell script on a Windows host via PSRP (pypsrp).

    Uses the Microsoft.PowerShell endpoint, not WinRS — which means the
    target user only needs Invoke on the PSSessionConfiguration, not
    Execute on the default WinRS cmd shell SDDL.

    Returns stdout str. Raises RuntimeError on PS errors or auth failure.
    """
    from pypsrp.client import Client

    # pypsrp accepts: 'negotiate' (default), 'ntlm', 'kerberos',
    # 'basic', 'certificate', 'credssp'. Keep our accepted set in sync
    # with pypsrp's vocabulary.
    _VALID_AUTH = ("negotiate", "ntlm", "kerberos", "basic", "certificate", "credssp")
    auth = (transport or "ntlm").lower()
    if auth not in _VALID_AUTH:
        auth = "ntlm"

    t0 = time.monotonic()
    log.debug("PSRP exec → %s@%s:%d (%s, ssl=%s) | cmd: %s",
              username, host, port, auth, use_ssl,
              (script or "")[:80].replace("\n", " "))

    client = Client(
        server=host,
        port=port,
        username=username,
        password=password,
        ssl=use_ssl,
        auth=auth,
        cert_validation=False if use_ssl else True,
        read_timeout=read_timeout,
        operation_timeout=operation_timeout,
    )

    try:
        output, streams, had_errors = client.execute_ps(script)
    except Exception as e:
        # pypsrp raises WSManFaultError / AuthenticationError / etc.
        # Normalise to RuntimeError so callers (collector + discovery test)
        # don't need to import pypsrp-specific exception types.
        raise RuntimeError(str(e)) from e
    finally:
        try:
            client.close()
        except Exception:
            pass

    elapsed = int((time.monotonic() - t0) * 1000)
    if had_errors:
        # streams.error is a list of ErrorRecord objects — coerce to strings
        err_text = "\n".join(str(e) for e in (streams.error or []))
        raise RuntimeError(
            f"PowerShell errors ({elapsed}ms): {err_text[:400] or 'had_errors=True, no error records'}"
        )

    log.debug("PSRP exec ← %s@%s:%d | %d bytes | %dms",
              username, host, port, len(output or ""), elapsed)
    return output or ""


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

    mem_total_bytes = _int("MEM_TOTAL_BYTES")
    mem_free_bytes  = _int("MEM_FREE_BYTES")
    mem_used_bytes  = max(0, mem_total_bytes - mem_free_bytes)
    mem_pct = round((mem_used_bytes / mem_total_bytes) * 100) if mem_total_bytes else 0

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
    # NOTE: Do NOT check WinRM service status here. The collector already
    # proved WinRM is running by successfully connecting via PSRP to execute
    # this poll script. Get-Service -Name WinRM returns "missing" inside
    # PSRP sessions on some Windows 11 builds — a false positive.
    # WinRM health is implicitly "running" if we reached this parser.

    return {
        "id": label, "label": label, "host": host,
        "hostname":    hostname,
        "os":          os_caption,
        "os_version":  os_version,
        "uptime_secs": uptime_secs,
        "uptime_fmt":  _fmt_uptime(uptime_secs),
        "cpu_pct":     cpu_pct,
        "mem_total_bytes": mem_total_bytes,
        "mem_used_bytes":  mem_used_bytes,
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
                section="WINDOWS",
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
