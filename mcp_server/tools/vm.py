"""VM host SSH execution + infrastructure lookup tools."""
import re
from datetime import datetime, timezone


def _ts():
    return datetime.now(timezone.utc).isoformat()


def _validate_command(command):
    """Validate a command against the read-only allowlist.

    Allows pipes (cmd1 | cmd2 | cmd3) where ALL segments match the allowlist.
    Allows '2>/dev/null' (stderr discard only — not file writes).
    Blocks semicolons, backticks, $(), stdout redirects, file writes.
    Returns (is_valid, cleaned_command_or_error_message).
    """
    # Strip '2>/dev/null' before metachar check — safe stderr discard,
    # extremely common in disk/find commands to suppress permission errors.
    sanitized = re.sub(r'\s*2>/dev/null', '', command).strip()

    # Block remaining shell injection chars (stdout redirects, chaining, subshells)
    if any(c in sanitized for c in [';', '`', '$', '>', '<', '&&', '||']):
        return False, f"Shell metacharacters not allowed: {command!r}"

    # Split on pipe — allow up to 3 segments (e.g. du -sh /* | sort -hr | head -20)
    parts = [p.strip() for p in sanitized.split('|')]
    if len(parts) > 3:
        return False, "Maximum two pipes allowed (e.g. cmd | sort -hr | head -20)"

    _READ_ALLOWLIST = [
        r'^df\b', r'^du\b', r'^free\b', r'^uptime$', r'^uname\b',
        r'^journalctl\b', r'^find\b', r'^ps\b',
        r'^docker system df', r'^docker volume ls', r'^docker ps\b', r'^docker images\b',
        r'^apt list', r'^apt-cache\b',
        r'^systemctl list', r'^systemctl status\b',
        r'^cat /etc/os-release$', r'^cat /proc/[\w/]+$',
        r'^hostname$', r'^whoami$',
        r'^ls\b', r'^stat\b', r'^wc\b', r'^sort\b',
        r'^head\b', r'^tail\b', r'^grep\b', r'^awk\b', r'^cut\b',
        r'^xargs\b',
    ]

    for part in parts:
        if not any(re.match(p, part) for p in _READ_ALLOWLIST):
            return False, (
                f"Command segment not in allowlist: {part!r}. "
                "Allowed: df, du, free, uptime, journalctl, find, ps, "
                "docker system df, docker volume ls, docker ps, apt list, "
                "systemctl, cat /etc/os-release, ls, stat, sort, head, tail, "
                "grep, awk, cut. Pipes and '2>/dev/null' are supported."
            )

    return True, sanitized  # return sanitized (2>/dev/null stripped)


def _resolve_connection(host, all_conns):
    """Resolve a host name/IP/alias to a vm_host connection.
    Resolution order: infra_inventory -> label exact -> IP exact -> label partial.
    """
    q = host.lower().strip()

    # 1. Infra inventory (hostname, aliases, IPs, partial label)
    try:
        from api.db.infra_inventory import resolve_host
        entry = resolve_host(host)
        if entry:
            conn_id = entry.get("connection_id")
            for c in all_conns:
                if str(c.get("id")) == conn_id:
                    return c
    except Exception:
        pass

    # 2. Direct connection match -- label exact -> IP exact -> label partial
    for c in all_conns:
        if c.get("label", "").lower() == q:
            return c
    for c in all_conns:
        if c.get("host", "") == host:
            return c
    for c in all_conns:
        if q in c.get("label", "").lower():
            return c

    return None


def vm_exec(host: str, command: str) -> dict:
    """Execute a read-only command on a registered VM host via SSH.

    Resolves credentials, shared keys, and jump hosts automatically from
    the connections database. No manual credential management needed.

    Use for: disk usage (df -h), large dirs (du -sh /* | sort -hr | head -20),
    memory (free -m), logs (journalctl -n 50), Docker storage (docker system df),
    large files (find / -size +100M -type f 2>/dev/null | head -20),
    package updates (apt list --upgradable).

    Args:
        host: VM host label, discovered hostname, or IP address.
              The error message lists available hosts if not found.
        command: Read-only shell command. Up to two pipes supported.
                 '2>/dev/null' is allowed to suppress permission errors.
    """
    valid, result_or_error = _validate_command(command)
    if not valid:
        return {"status": "error", "message": result_or_error, "data": None, "timestamp": _ts()}

    safe_cmd = result_or_error

    try:
        from api.connections import get_all_connections_for_platform
        all_conns = get_all_connections_for_platform("vm_host")
    except Exception as e:
        return {"status": "error", "message": f"Failed to load vm_host connections: {e}",
                "data": None, "timestamp": _ts()}

    if not all_conns:
        return {"status": "error",
                "message": "No vm_host connections configured. Add in Settings -> Connections -> vm_host.",
                "data": None, "timestamp": _ts()}

    conn = _resolve_connection(host, all_conns)
    if not conn:
        labels = [f"{c.get('label', '?')} ({c.get('host', '?')})" for c in all_conns]
        return {"status": "error",
                "message": (
                    f"No vm_host connection found for {host!r}. "
                    f"Available: {', '.join(labels)}. "
                    "Tip: use the connection label exactly, or call infra_lookup() "
                    "to see discovered hostnames."
                ),
                "data": None, "timestamp": _ts()}

    try:
        from api.collectors.vm_hosts import _resolve_credentials, _resolve_jump_host, _ssh_run
        username, password, private_key = _resolve_credentials(conn, all_conns)
        jump_host = _resolve_jump_host(conn, all_conns)
    except Exception as e:
        return {"status": "error", "message": f"Credential resolution failed: {e}",
                "data": None, "timestamp": _ts()}

    try:
        output = _ssh_run(
            conn["host"], conn.get("port") or 22,
            username, password, private_key,
            safe_cmd, jump_host=jump_host,
        )
        label = conn.get("label", host)
        jump_note = f" (via {jump_host['host']})" if jump_host else ""
        return {
            "status": "ok",
            "message": f"Executed on {label}{jump_note}",
            "data": {
                "host":      label,
                "ip":        conn["host"],
                "command":   safe_cmd,
                "output":    output.strip()[:4000],
                "truncated": len(output) > 4000,
            },
            "timestamp": _ts(),
        }
    except Exception as e:
        return {"status": "error",
                "message": f"SSH failed on {conn.get('label', host)} ({conn['host']}): {e}",
                "data": None, "timestamp": _ts()}


def infra_lookup(query: str = "", platform: str = "") -> dict:
    """Look up infrastructure entities by hostname, IP, alias, or label.

    Searches the infra_inventory automatically populated by collectors
    (vm_hosts, proxmox, swarm). Use to resolve user-provided names to
    actual connections, find IPs, or list all known hosts.

    Args:
        query: hostname, IP address, alias, or partial label to search.
               Leave blank to list all known entities.
        platform: optional filter -- vm_host, proxmox, docker_host, etc.
    """
    try:
        from api.db.infra_inventory import resolve_host, list_inventory

        if query:
            entry = resolve_host(query)
            if entry:
                return {
                    "status": "ok",
                    "message": f"Found: {entry['label']} ({entry.get('hostname') or '?'})",
                    "data": {
                        "connection_id": entry["connection_id"],
                        "platform":      entry["platform"],
                        "label":         entry["label"],
                        "hostname":      entry.get("hostname", ""),
                        "ips":           entry.get("ips", []),
                        "aliases":       entry.get("aliases", []),
                        "meta":          entry.get("meta", {}),
                        "last_discovered": str(entry.get("last_discovered", "")),
                    },
                    "timestamp": _ts(),
                }
            return {"status": "error",
                    "message": f"No infrastructure entity found for {query!r}",
                    "data": None, "timestamp": _ts()}
        else:
            entries = list_inventory(platform=platform)
            summary = [
                {
                    "label":    e["label"],
                    "hostname": e.get("hostname", ""),
                    "ips":      e.get("ips", []),
                    "platform": e["platform"],
                    "meta":     {k: v for k, v in (e.get("meta") or {}).items()
                                 if k in ("os", "role", "os_type")},
                }
                for e in entries
            ]
            return {
                "status": "ok",
                "message": f"{len(summary)} infrastructure entities known",
                "data": {"entities": summary},
                "timestamp": _ts(),
            }
    except Exception as e:
        return {"status": "error", "message": f"infra_lookup error: {e}",
                "data": None, "timestamp": _ts()}
