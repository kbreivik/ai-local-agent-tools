"""
VMHostsCollector — polls all vm_host connections via SSH.
Writes component="vm_hosts" snapshot for the dashboard.
"""
import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from api.collectors.base import BaseCollector

log = logging.getLogger(__name__)

_POLL_SCRIPT = """
echo "=HOSTNAME=" && hostname
echo "=UPTIME=" && cat /proc/uptime | awk '{print $1}'
echo "=LOAD=" && cat /proc/loadavg
echo "=MEM=" && free -b | grep Mem
echo "=DISK=" && df -B1 --output=target,size,used,avail,pcent | tail -n +2
echo "=KERNEL=" && uname -r
echo "=OS=" && cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2 | tr -d '"'
echo "=DOCKER_VERSION=" && docker --version 2>/dev/null || echo "not installed"
echo "=APT_UPDATED=" && stat -c %Y /var/lib/apt/lists 2>/dev/null || echo "0"
echo "=SERVICES=" && for s in docker elasticsearch logstash kibana filebeat kafka ssh ufw; do
  status=$(systemctl is-active $s 2>/dev/null || echo "inactive")
  echo "$s:$status"
done
"""


def _ssh_run(host, port, username, password, private_key, script):
    """Run a shell script on remote host via paramiko. Returns stdout.

    Note: AutoAddPolicy is acceptable for known LAN hosts. For internet-facing
    hosts, switch to RejectPolicy + known_hosts verification.
    """
    import paramiko
    import io

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs = dict(
        hostname=host, port=port, username=username,
        timeout=15, look_for_keys=False, allow_agent=False,
    )
    if private_key:
        pkey = paramiko.RSAKey.from_private_key(io.StringIO(private_key))
        connect_kwargs["pkey"] = pkey
    elif password:
        connect_kwargs["password"] = password
    else:
        connect_kwargs["look_for_keys"] = True
        connect_kwargs["allow_agent"] = True

    client.connect(**connect_kwargs)
    try:
        _, stdout, _ = client.exec_command(script, timeout=20)
        output = stdout.read().decode("utf-8", errors="replace")
    finally:
        client.close()
    return output


def _parse_poll_output(output, label, host):
    """Parse the structured output from _POLL_SCRIPT into a VM card dict."""
    sections = {}
    current = None
    lines = []
    for line in output.splitlines():
        if line.startswith("=") and line.endswith("="):
            if current:
                sections[current] = lines
            current = line.strip("=")
            lines = []
        else:
            lines.append(line.strip())
    if current:
        sections[current] = lines

    def first(key):
        return (sections.get(key) or [""])[0]

    # Memory
    mem_line = first("MEM").split()
    mem_total = int(mem_line[1]) if len(mem_line) > 1 else 0
    mem_used  = int(mem_line[2]) if len(mem_line) > 2 else 0
    mem_pct   = round((mem_used / mem_total) * 100) if mem_total else 0

    # Disk mounts
    disks = []
    skip_prefixes = ("/dev", "/sys", "/proc", "/run", "/snap/")
    for dline in (sections.get("DISK") or []):
        parts = dline.split()
        if len(parts) < 5:
            continue
        mountpoint = parts[0]
        if any(mountpoint.startswith(s) for s in skip_prefixes):
            continue
        disks.append({
            "mountpoint": mountpoint,
            "total_bytes": int(parts[1]),
            "used_bytes": int(parts[2]),
            "avail_bytes": int(parts[3]),
            "usage_pct": int(parts[4].rstrip("%")) if parts[4] != "-" else 0,
        })

    # Services
    services = {}
    for sline in (sections.get("SERVICES") or []):
        if ":" in sline:
            svc, state = sline.split(":", 1)
            services[svc.strip()] = state.strip()

    # Load avg
    load_parts = first("LOAD").split()
    load1  = float(load_parts[0]) if load_parts else 0.0
    load5  = float(load_parts[1]) if len(load_parts) > 1 else 0.0
    load15 = float(load_parts[2]) if len(load_parts) > 2 else 0.0

    try:
        uptime_secs = float(first("UPTIME"))
    except ValueError:
        uptime_secs = 0

    def _fmt_uptime(secs):
        secs = int(secs)
        d = secs // 86400; secs %= 86400
        h = secs // 3600;  secs %= 3600
        m = secs // 60
        if d: return f"{d}d {h}h"
        if h: return f"{h}h {m}m"
        return f"{m}m"

    # Health
    max_disk_pct = max((d["usage_pct"] for d in disks), default=0)
    dot = "green"
    problems = []
    if max_disk_pct >= 90:
        dot = "red"; problems.append(f"disk {max_disk_pct}% full")
    elif max_disk_pct >= 80:
        dot = "amber"; problems.append(f"disk {max_disk_pct}% used")
    if mem_pct >= 90:
        dot = "red"; problems.append(f"memory {mem_pct}% used")
    elif mem_pct >= 80 and dot == "green":
        dot = "amber"; problems.append(f"memory {mem_pct}% used")

    return {
        "id": label, "label": label, "host": host,
        "hostname": first("HOSTNAME"),
        "os": first("OS"), "kernel": first("KERNEL"),
        "uptime_secs": uptime_secs, "uptime_fmt": _fmt_uptime(uptime_secs),
        "load_1": load1, "load_5": load5, "load_15": load15,
        "mem_total_bytes": mem_total, "mem_used_bytes": mem_used, "mem_pct": mem_pct,
        "disks": disks, "services": services,
        "docker_version": first("DOCKER_VERSION"),
        "apt_updated_ts": int(first("APT_UPDATED") or 0),
        "dot": dot, "problem": problems[0] if problems else None,
    }


def _poll_one_vm(conn):
    """Poll a single VM connection. Returns a vm card dict."""
    host  = conn.get("host", "")
    port  = conn.get("port") or 22
    label = conn.get("label") or host
    creds = conn.get("credentials", {}) or {}
    if isinstance(creds, str):
        import json
        try: creds = json.loads(creds)
        except Exception: creds = {}

    username    = creds.get("username", "ubuntu")
    password    = creds.get("password") or None
    private_key = creds.get("private_key") or None

    try:
        output = _ssh_run(host, port, username, password, private_key, _POLL_SCRIPT)
        result = _parse_poll_output(output, label, host)
        result["connection_id"] = str(conn.get("id", ""))
        result["config"] = conn.get("config") or {}
        return result
    except Exception as e:
        log.warning("VMHostsCollector: %s (%s) failed: %s", label, host, e)
        return {
            "id": label, "label": label, "host": host,
            "connection_id": str(conn.get("id", "")),
            "config": conn.get("config") or {},
            "dot": "red", "problem": str(e)[:120],
            "hostname": host, "os": "", "kernel": "",
            "uptime_fmt": "", "mem_pct": 0, "disks": [],
            "services": {}, "docker_version": "",
        }


class VMHostsCollector(BaseCollector):
    component = "vm_hosts"

    def __init__(self):
        super().__init__()
        self.interval = int(os.environ.get("VM_HOSTS_POLL_INTERVAL", "60"))

    async def poll(self):
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self):
        from api.connections import get_all_connections_for_platform
        try:
            conns = get_all_connections_for_platform("vm_host")
        except Exception as e:
            return {"health": "error", "vms": [], "error": str(e)}

        if not conns:
            return {"health": "unconfigured", "vms": [],
                    "message": "No VM connections configured"}

        vms = []
        with ThreadPoolExecutor(max_workers=min(len(conns), 10)) as pool:
            futures = {pool.submit(_poll_one_vm, c): c for c in conns}
            for future in as_completed(futures):
                try:
                    vms.append(future.result())
                except Exception as e:
                    c = futures[future]
                    vms.append({
                        "id": c.get("label", c.get("host")),
                        "label": c.get("label", c.get("host")),
                        "host": c.get("host"), "dot": "red",
                        "problem": str(e)[:120],
                    })

        total = len(vms)
        ok    = sum(1 for v in vms if v.get("dot") in ("green", "amber"))
        red   = sum(1 for v in vms if v.get("dot") == "red")
        health = "healthy" if red == 0 else ("degraded" if ok > 0 else "error")

        return {"health": health, "vms": vms, "total": total, "ok": ok, "issues": red}
