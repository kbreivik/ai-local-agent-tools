"""
VMHostsCollector — polls all vm_host connections via SSH.
Supports shared credentials, jump host routing, and OS-aware commands.
Writes component="vm_hosts" snapshot for the dashboard.
"""
import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from api.collectors.base import BaseCollector

log = logging.getLogger(__name__)

# OS type → (init_system, pkg_manager) defaults
OS_DEFAULTS = {
    "debian":  ("systemd", "apt"),
    "rhel":    ("systemd", "dnf"),
    "alpine":  ("openrc",  "apk"),
    "coreos":  ("systemd", None),
    "windows": ("windows", None),
}

# Role → allowed command set defaults
ROLE_COMMANDS = {
    "swarm_manager": {"apt", "systemctl", "docker", "journalctl"},
    "swarm_worker":  {"apt", "systemctl", "docker", "journalctl"},
    "storage":       {"apt", "systemctl", "journalctl"},
    "monitoring":    {"apt", "systemctl", "journalctl"},
    "general":       {"systemctl", "journalctl"},
}

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


def _ssh_run(host, port, username, password, private_key, script,
             jump_host=None):
    """Run script on remote host via paramiko. If jump_host dict provided,
    connect via ProxyJump: transport to bastion, direct-tcpip channel to target.

    jump_host = { 'host', 'port', 'username', 'password', 'private_key' }

    Note: AutoAddPolicy is acceptable for known LAN hosts. For internet-facing
    hosts, switch to RejectPolicy + known_hosts verification.
    Transitive jumps (A→B→C) are not supported — only one level deep.
    """
    import paramiko
    import io

    def _make_pkey(key_str):
        for cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
            try:
                return cls.from_private_key(io.StringIO(key_str))
            except Exception:
                continue
        raise ValueError("Could not parse private key (tried RSA, Ed25519, ECDSA)")

    import time as _time
    t0 = _time.monotonic()
    log.debug("SSH exec → %s@%s:%d%s | cmd: %s",
              username, host, port,
              f" via {jump_host['host']}" if jump_host else "",
              script[:80].replace('\n', ' '))

    if jump_host:
        # Step 1: connect to bastion
        j_transport = paramiko.Transport((jump_host["host"], jump_host["port"]))
        j_transport.connect()
        if jump_host.get("private_key"):
            j_transport.auth_publickey(jump_host["username"], _make_pkey(jump_host["private_key"]))
        elif jump_host.get("password"):
            j_transport.auth_password(jump_host["username"], jump_host["password"])

        # Step 2: open direct-tcpip channel through bastion to target
        chan = j_transport.open_channel("direct-tcpip", dest_addr=(host, port), src_addr=("127.0.0.1", 0))

        # Step 3: layer target SSH on the channel
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(hostname=host, port=port, username=username, sock=chan,
                       timeout=15, look_for_keys=False, allow_agent=False,
                       **({"pkey": _make_pkey(private_key)} if private_key else
                          {"password": password} if password else
                          {"look_for_keys": True, "allow_agent": True}))
        try:
            _, stdout, _ = client.exec_command(script, timeout=30)
            output = stdout.read().decode("utf-8", errors="replace")
        finally:
            client.close()
            j_transport.close()
        elapsed = int((_time.monotonic() - t0) * 1000)
        log.debug("SSH exec ← %s@%s:%d | %d bytes | %dms", username, host, port, len(output), elapsed)
        return output
    else:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kw = dict(hostname=host, port=port, username=username,
                  timeout=15, look_for_keys=False, allow_agent=False)
        if private_key:
            kw["pkey"] = _make_pkey(private_key)
        elif password:
            kw["password"] = password
        else:
            kw["look_for_keys"] = True
            kw["allow_agent"] = True
        client.connect(**kw)
        try:
            _, stdout, _ = client.exec_command(script, timeout=30)
            output = stdout.read().decode("utf-8", errors="replace")
        except Exception as e:
            log.debug("SSH exec FAILED %s@%s:%d: %s", username, host, port, e, exc_info=True)
            raise
        finally:
            client.close()
        elapsed = int((_time.monotonic() - t0) * 1000)
        log.debug("SSH exec ← %s@%s:%d | %d bytes | %dms", username, host, port, len(output), elapsed)
        return output


def _resolve_credentials(conn, all_conns):
    """Return (username, password, private_key) for a connection.
    Falls back to shared connections if this conn has no own credentials.
    Shared connections are those with config.shared_credentials == True."""
    creds = conn.get("credentials", {}) or {}
    if isinstance(creds, str):
        import json
        try: creds = json.loads(creds)
        except Exception: creds = {}

    username    = creds.get("username") or None
    password    = creds.get("password") or None
    private_key = creds.get("private_key") or None

    if private_key or password:
        return username or "ubuntu", password, private_key

    # Fall back to shared connections
    shared = [c for c in all_conns
              if c.get("id") != conn.get("id")
              and (c.get("config") or {}).get("shared_credentials")]
    for sc in shared:
        sc_creds = sc.get("credentials", {}) or {}
        if isinstance(sc_creds, str):
            import json
            try: sc_creds = json.loads(sc_creds)
            except Exception: sc_creds = {}
        sc_key  = sc_creds.get("private_key") or None
        sc_pass = sc_creds.get("password") or None
        sc_user = sc_creds.get("username") or "ubuntu"
        if sc_key or sc_pass:
            log.debug("Using shared credentials from %s for %s",
                      sc.get("label"), conn.get("label"))
            return sc_user, sc_pass, sc_key

    return username or "ubuntu", None, None


def _resolve_jump_host(conn, all_conns):
    """Return jump_host dict or None. Only one level deep — no transitive jumps.
    conn.config.jump_via is the UUID of the jump host connection.
    Ignored if this connection is itself a jump host (mutual exclusion)."""
    cfg = conn.get("config") or {}
    if cfg.get("is_jump_host"):
        return None
    jump_via = cfg.get("jump_via") or ""
    if not jump_via:
        return None
    jconn = next((c for c in all_conns if str(c.get("id")) == jump_via), None)
    if not jconn:
        log.warning("Jump host %s not found for %s", jump_via, conn.get("label"))
        return None
    jcreds = jconn.get("credentials", {}) or {}
    if isinstance(jcreds, str):
        import json
        try: jcreds = json.loads(jcreds)
        except Exception: jcreds = {}
    return {
        "host": jconn["host"],
        "port": jconn.get("port") or 22,
        "username": jcreds.get("username", "ubuntu"),
        "password": jcreds.get("password") or None,
        "private_key": jcreds.get("private_key") or None,
    }


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

    mem_line = first("MEM").split()
    mem_total = int(mem_line[1]) if len(mem_line) > 1 else 0
    mem_used  = int(mem_line[2]) if len(mem_line) > 2 else 0
    mem_pct   = round((mem_used / mem_total) * 100) if mem_total else 0

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

    services = {}
    for sline in (sections.get("SERVICES") or []):
        if ":" in sline:
            svc, state = sline.split(":", 1)
            services[svc.strip()] = state.strip()

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


def _poll_one_vm(conn, all_conns):
    """Poll a single VM connection. Returns a vm card dict."""
    host  = conn.get("host", "")
    port  = conn.get("port") or 22
    label = conn.get("label") or host
    cfg   = conn.get("config") or {}

    if cfg.get("is_jump_host"):
        return None  # jump hosts are relays, not polled as compute nodes

    username, password, private_key = _resolve_credentials(conn, all_conns)
    jump_host = _resolve_jump_host(conn, all_conns)

    # Adjust poll script for OS type
    os_type = cfg.get("os_type", "")
    script = _POLL_SCRIPT
    if os_type == "rhel":
        script = script.replace("stat -c %Y /var/lib/apt/lists", "stat -c %Y /var/cache/dnf")
    elif os_type == "alpine":
        script = script.replace("stat -c %Y /var/lib/apt/lists", "stat -c %Y /var/cache/apk")

    try:
        output = _ssh_run(host, port, username, password, private_key,
                          script, jump_host=jump_host)
        result = _parse_poll_output(output, label, host)
        result["connection_id"] = str(conn.get("id", ""))
        result["config"] = cfg
        result["jump_via_label"] = next(
            (c.get("label") for c in all_conns if str(c.get("id")) == cfg.get("jump_via", "")),
            None
        )
        # Write discovered facts to infra_inventory (non-blocking)
        try:
            from api.db.infra_inventory import upsert_entity
            upsert_entity(
                connection_id=str(conn.get("id", "")),
                platform="vm_host", label=label,
                hostname=result.get("hostname", ""),
                ips=[conn.get("host", "")] if conn.get("host") else [],
                meta={"os": result.get("os", ""), "kernel": result.get("kernel", ""),
                      "role": cfg.get("role", ""), "os_type": cfg.get("os_type", ""),
                      "docker_version": result.get("docker_version", "")},
            )
        except Exception:
            pass
        return result
    except Exception as e:
        log.warning("VMHostsCollector: %s (%s) failed: %s", label, host, e, exc_info=True)
        return {
            "id": label, "label": label, "host": host,
            "connection_id": str(conn.get("id", "")),
            "config": cfg,
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
            all_conns = get_all_connections_for_platform("vm_host")
        except Exception as e:
            return {"health": "error", "vms": [], "error": str(e)}

        if not all_conns:
            return {"health": "unconfigured", "vms": [],
                    "message": "No VM connections configured"}

        targets = [c for c in all_conns if not (c.get("config") or {}).get("is_jump_host")]

        if not targets:
            return {"health": "unconfigured", "vms": [],
                    "message": "All vm_host connections are jump hosts — add target VMs"}

        vms = []
        with ThreadPoolExecutor(max_workers=min(len(targets), 10)) as pool:
            futures = {pool.submit(_poll_one_vm, c, all_conns): c for c in targets}
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result is not None:
                        vms.append(result)
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
