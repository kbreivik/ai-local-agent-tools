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
             jump_host=None, _log_meta=None, passphrase=None):
    """Run script on remote host via paramiko. If jump_host dict provided,
    connect via ProxyJump: transport to bastion, direct-tcpip channel to target.

    jump_host = { 'host', 'port', 'username', 'password', 'private_key' }

    Note: AutoAddPolicy is acceptable for known LAN hosts. For internet-facing
    hosts, switch to RejectPolicy + known_hosts verification.
    Transitive jumps (A→B→C) are not supported — only one level deep.
    """
    import paramiko
    import io

    def _make_pkey(key_str, passphrase=None):
        pw = passphrase if passphrase else None
        for cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
            try:
                return cls.from_private_key(io.StringIO(key_str), password=pw)
            except Exception:
                continue
        raise ValueError("Could not parse private key (tried RSA, Ed25519, ECDSA)")

    import time as _time
    t0 = _time.monotonic()
    log.debug("SSH exec → %s@%s:%d%s | cmd: %s",
              username, host, port,
              f" via {jump_host['host']}" if jump_host else "",
              script[:80].replace('\n', ' '))

    # Dynamic timeout: write/cleanup commands need longer than reads
    _WRITE_INDICATORS = ('prune', 'vacuum', 'autoremove', 'autoclean', 'upgrade')
    _exec_timeout = 180 if any(w in script.lower() for w in _WRITE_INDICATORS) else 30

    if jump_host:
        # Step 1: connect to bastion
        j_transport = paramiko.Transport((jump_host["host"], jump_host["port"]))
        j_transport.connect()
        if jump_host.get("private_key"):
            j_transport.auth_publickey(jump_host["username"], _make_pkey(jump_host["private_key"], jump_host.get("passphrase")))
        elif jump_host.get("password"):
            j_transport.auth_password(jump_host["username"], jump_host["password"])

        # Step 2: open direct-tcpip channel through bastion to target
        chan = j_transport.open_channel("direct-tcpip", dest_addr=(host, port), src_addr=("127.0.0.1", 0))

        # Step 3: layer target SSH on the channel
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(hostname=host, port=port, username=username, sock=chan,
                       timeout=15, look_for_keys=False, allow_agent=False,
                       **({"pkey": _make_pkey(private_key, passphrase)} if private_key else
                          {"password": password} if password else
                          {"look_for_keys": True, "allow_agent": True}))
        try:
            _, stdout, stderr = client.exec_command(script, timeout=_exec_timeout)
            output = stdout.read().decode("utf-8", errors="replace")
            err_out = stderr.read().decode("utf-8", errors="replace").strip()
            if not output.strip() and err_out:
                output = f"[stderr]: {err_out}"
        finally:
            client.close()
            j_transport.close()
        elapsed = int((_time.monotonic() - t0) * 1000)
        log.debug("SSH exec ← %s@%s:%d | %d bytes | %dms", username, host, port, len(output), elapsed)
        try:
            from api.db.ssh_log import write_log as _wl
            _wl(target_host=host, target_port=port, username=username or "", outcome="success",
                duration_ms=elapsed, bytes_received=len(output),
                connection_id=(_log_meta or {}).get("connection_id", ""),
                credential_source_id=(_log_meta or {}).get("credential_source_id", ""),
                jump_host=jump_host["host"] if jump_host else "",
                resolved_label=(_log_meta or {}).get("resolved_label", ""),
                triggered_by=(_log_meta or {}).get("triggered_by", "collector"),
                operation_id=(_log_meta or {}).get("operation_id", ""),
                command_preview=script[:120] if script else "")
        except Exception:
            pass
        return output
    else:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kw = dict(hostname=host, port=port, username=username,
                  timeout=15, look_for_keys=False, allow_agent=False)
        if private_key:
            kw["pkey"] = _make_pkey(private_key, passphrase)
        elif password:
            kw["password"] = password
        else:
            kw["look_for_keys"] = True
            kw["allow_agent"] = True
        client.connect(**kw)
        try:
            _, stdout, stderr = client.exec_command(script, timeout=_exec_timeout)
            output = stdout.read().decode("utf-8", errors="replace")
            err_out = stderr.read().decode("utf-8", errors="replace").strip()
            if not output.strip() and err_out:
                output = f"[stderr]: {err_out}"
        except Exception as e:
            log.debug("SSH exec FAILED %s@%s:%d: %s", username, host, port, e, exc_info=True)
            try:
                from api.db.ssh_log import write_log as _wl
                _outcome = "timeout" if "timed out" in str(e).lower() else \
                           "auth_fail" if "authentication" in str(e).lower() else \
                           "refused" if "refused" in str(e).lower() else "error"
                _wl(target_host=host, target_port=port, username=username or "", outcome=_outcome,
                    duration_ms=int((_time.monotonic() - t0) * 1000), error_message=str(e),
                    connection_id=(_log_meta or {}).get("connection_id", ""),
                    credential_source_id=(_log_meta or {}).get("credential_source_id", ""),
                    jump_host=jump_host["host"] if jump_host else "",
                    resolved_label=(_log_meta or {}).get("resolved_label", ""),
                    triggered_by=(_log_meta or {}).get("triggered_by", "collector"),
                    operation_id=(_log_meta or {}).get("operation_id", ""),
                    command_preview=script[:120] if script else "")
            except Exception:
                pass
            raise
        finally:
            client.close()
        elapsed = int((_time.monotonic() - t0) * 1000)
        log.debug("SSH exec ← %s@%s:%d | %d bytes | %dms", username, host, port, len(output), elapsed)
        try:
            from api.db.ssh_log import write_log as _wl
            _wl(target_host=host, target_port=port, username=username or "", outcome="success",
                duration_ms=elapsed, bytes_received=len(output),
                connection_id=(_log_meta or {}).get("connection_id", ""),
                credential_source_id=(_log_meta or {}).get("credential_source_id", ""),
                jump_host=jump_host["host"] if jump_host else "",
                resolved_label=(_log_meta or {}).get("resolved_label", ""),
                triggered_by=(_log_meta or {}).get("triggered_by", "collector"),
                operation_id=(_log_meta or {}).get("operation_id", ""),
                command_preview=script[:120] if script else "")
        except Exception:
            pass
        return output


def _resolve_credentials(conn, all_conns):
    """Return (username, password, private_key) for a connection.
    Priority: own creds → credential profile → shared_credentials fallback."""
    from api.db.credential_profiles import resolve_credentials_for_connection
    creds = resolve_credentials_for_connection(conn, all_conns)
    username = creds.get('username', 'ubuntu')
    password = creds.get('password')
    private_key = creds.get('private_key')
    return username, password, private_key


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
                          script, jump_host=jump_host,
                          _log_meta={"connection_id": str(conn.get("id", "")),
                                     "resolved_label": label, "triggered_by": "collector"})
        result = _parse_poll_output(output, label, host)
        result["connection_id"] = str(conn.get("id", ""))
        result["config"] = cfg
        result["entity_id"] = label  # bare label — matches entity_history records
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
        # ── Change detection ──────────────────────────────────────────────────
        try:
            from api.db.entity_history import write_change, write_event, get_last_known_values

            _TRACKED_FIELDS = ["os", "kernel", "docker_version", "hostname"]
            last = get_last_known_values(label, _TRACKED_FIELDS)

            for field in _TRACKED_FIELDS:
                new_val = result.get(field, "")
                if not new_val:
                    continue
                old_val = last.get(field)
                if old_val and old_val != new_val:
                    write_change(
                        entity_id=label,
                        entity_type="vm_host",
                        field_name=field,
                        old_value=old_val,
                        new_value=new_val,
                        connection_id=str(conn.get("id", "")),
                        source_collector="vm_hosts",
                    )
                    # Version changes fire an event
                    if field in ("os", "kernel", "docker_version"):
                        write_event(
                            entity_id=label,
                            entity_type="vm_host",
                            event_type="version_change",
                            severity="warning",
                            description=f"{field} changed: {old_val} → {new_val}",
                            connection_id=str(conn.get("id", "")),
                            source_collector="vm_hosts",
                            metadata={"field": field, "old": old_val, "new": new_val},
                        )

            # Disk threshold events
            max_disk = max((d.get("usage_pct", 0) for d in result.get("disks", [])), default=0)
            if max_disk >= 90:
                write_event(
                    entity_id=label, entity_type="vm_host",
                    event_type="disk_threshold_crossed", severity="critical",
                    description=f"Disk usage at {max_disk}% on {label}",
                    connection_id=str(conn.get("id", "")),
                    source_collector="vm_hosts",
                    metadata={"usage_pct": max_disk},
                )
            elif max_disk >= 80:
                write_event(
                    entity_id=label, entity_type="vm_host",
                    event_type="disk_threshold_crossed", severity="warning",
                    description=f"Disk usage at {max_disk}% on {label}",
                    connection_id=str(conn.get("id", "")),
                    source_collector="vm_hosts",
                    metadata={"usage_pct": max_disk},
                )
        except Exception as _he:
            log.debug("entity_history write failed (non-fatal): %s", _he)
        # ── Metric samples (time-series) ──────────────────────────────────────
        try:
            from api.db.metric_samples import write_samples
            metrics: dict = {}
            if result.get("mem_pct") is not None:
                metrics["mem.pct"] = float(result["mem_pct"])
            if result.get("load_1") is not None:
                metrics["load.1m"] = float(result["load_1"])
            if result.get("load_5") is not None:
                metrics["load.5m"] = float(result["load_5"])
            for disk in result.get("disks", []):
                mp = disk.get("mountpoint", "").replace("/", "_").strip("_") or "root"
                if disk.get("usage_pct") is not None:
                    metrics[f"disk.{mp}.pct"] = float(disk["usage_pct"])
                if disk.get("used_bytes") is not None:
                    metrics[f"disk.{mp}.used_gb"] = round(disk["used_bytes"] / 1e9, 3)
            if metrics:
                write_samples(label, metrics)
        except Exception as _me:
            log.debug("metric_samples write failed (non-fatal): %s", _me)
        return result
    except Exception as e:
        log.warning("VMHostsCollector: %s (%s) failed: %s", label, host, e, exc_info=True)
        return {
            "id": label, "label": label, "host": host,
            "entity_id": label,
            "connection_id": str(conn.get("id", "")),
            "config": cfg,
            "dot": "red", "problem": str(e)[:120],
            "hostname": host, "os": "", "kernel": "",
            "uptime_fmt": "", "mem_pct": 0, "disks": [],
            "services": {}, "docker_version": "",
        }


def _ssh_run_streaming(host, port, username, password, private_key, command):
    """Run a long-running command via SSH and yield output lines as they arrive.

    Unlike _ssh_run() which waits for completion, this generator yields each line
    as soon as it's received. Suitable for journalctl -f, tail -f, etc.
    The caller should iterate and stop when done (e.g. via threading stop event).
    """
    import paramiko
    import time as _t

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs = {
        "hostname": host,
        "port": port,
        "username": username,
        "timeout": 15,
        "banner_timeout": 20,
    }
    if private_key:
        import io as _io
        pkey = paramiko.RSAKey.from_private_key(_io.StringIO(private_key))
        connect_kwargs["pkey"] = pkey
    elif password:
        connect_kwargs["password"] = password

    try:
        client.connect(**connect_kwargs)
        chan = client.get_transport().open_session()
        chan.set_combine_stderr(True)
        chan.exec_command(command)

        remainder = ""
        while True:
            if chan.recv_ready():
                chunk = chan.recv(4096).decode("utf-8", errors="replace")
                text = remainder + chunk
                lines = text.splitlines(keepends=True)
                remainder = lines.pop() if lines and not lines[-1].endswith("\n") else ""
                for line in lines:
                    yield line.rstrip("\n")
            elif chan.exit_status_ready():
                if remainder.strip():
                    yield remainder.strip()
                break
            else:
                _t.sleep(0.05)
    finally:
        client.close()


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
        snapshot = {"health": health, "vms": vms, "total": total, "ok": ok, "issues": red}

        # v2.39.0: best-effort fact extraction
        try:
            from api.facts.extractors import extract_facts_from_vm_hosts_snapshot
            from api.db.known_facts import batch_upsert_facts
            from api.metrics import FACTS_UPSERTED_COUNTER
            facts = extract_facts_from_vm_hosts_snapshot(snapshot)
            result = batch_upsert_facts(facts, actor="collector")
            for action, count in result.items():
                if count > 0:
                    FACTS_UPSERTED_COUNTER.labels(
                        source="vm_hosts_collector", action=action
                    ).inc(count)
        except Exception as _fe:
            log.warning("Fact extraction failed for vm_hosts: %s", _fe)

        return snapshot

    def to_entities(self, state: dict):
        """Return one Entity per polled VM host.

        entity_id = bare label (e.g. 'ds-docker-worker-01') — intentionally no prefix,
        kept consistent with entity_history records written by the collector.
        """
        from api.collectors.base import Entity
        _DOT_STATUS = {"green": "healthy", "amber": "degraded", "red": "error", "grey": "unknown"}
        entities = []
        for vm in state.get("vms", []):
            label = vm.get("label") or vm.get("id") or "unknown"
            disks = vm.get("disks", [])
            max_disk_pct = max((d.get("usage_pct", 0) for d in disks), default=0)
            entities.append(Entity(
                id=label,
                label=label,
                component=self.component,
                platform="vm_host",
                section="COMPUTE",
                status=_DOT_STATUS.get(vm.get("dot", "grey"), "unknown"),
                last_error=vm.get("problem"),
                metadata={
                    "host":           vm.get("host", ""),
                    "os":             vm.get("os", ""),
                    "kernel":         vm.get("kernel", ""),
                    "mem_pct":        vm.get("mem_pct"),
                    "load_1":         vm.get("load_1"),
                    "docker_version": vm.get("docker_version", ""),
                    "uptime_fmt":     vm.get("uptime_fmt", ""),
                    "max_disk_pct":   max_disk_pct,
                }
            ))
        return entities if entities else super().to_entities(state)
