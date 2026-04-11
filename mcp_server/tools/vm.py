"""VM host SSH execution tool — Tier 2 connection tool."""
import re
from datetime import datetime, timezone


def _ts():
    return datetime.now(timezone.utc).isoformat()


# Read-only command allowlist — enforced regardless of agent type.
_READ_ALLOWLIST = [
    r'^df\b',
    r'^du\b',
    r'^free\b',
    r'^uptime$',
    r'^uname\b',
    r'^journalctl\b',
    r'^find\b',
    r'^ps\b',
    r'^docker system df',
    r'^apt list',
    r'^apt-cache\b',
    r'^systemctl list',
    r'^systemctl status\b',
    r'^cat /etc/os-release$',
    r'^cat /proc/\w+$',
    r'^hostname$',
    r'^whoami$',
    r'^ls\b',
    r'^stat\b',
    r'^wc\b',
    r'^sort\b',
    r'^head\b',
    r'^tail\b',
    r'^grep\b',
]


def vm_exec(host: str, command: str) -> dict:
    """Execute a read-only command on a registered VM host via SSH.

    Resolves credentials, shared keys, and jump hosts automatically
    from the connections database. No manual credential management needed.

    Use for: disk usage (df -h), large files (find / -size +100M -type f),
    memory (free -m), recent logs (journalctl -n 50),
    Docker storage (docker system df), package updates (apt list --upgradable),
    process list (ps aux --sort=-%mem | head -20).

    Args:
        host: VM host label (e.g. "agent-01") or IP address.
              Call without a specific host first if unsure — the error
              message will list available VM hosts.
        command: Read-only shell command from the allowlist. Shell
                 metacharacters (;|><&`) are stripped before execution.
    """
    safe_cmd = re.sub(r'[;&|><`$]', '', command).strip()

    if not any(re.match(p, safe_cmd) for p in _READ_ALLOWLIST):
        return {
            "status": "error",
            "message": (
                f"Command not in read-only allowlist: {safe_cmd!r}. "
                "Allowed prefixes: df, du, free, uptime, uname, journalctl, "
                "find, ps, docker system df, apt list, systemctl list/status, "
                "cat /etc/os-release, hostname, whoami, ls, stat, wc, sort, "
                "head, tail, grep."
            ),
            "data": None, "timestamp": _ts(),
        }

    try:
        from api.connections import get_all_connections_for_platform
        all_conns = get_all_connections_for_platform("vm_host")
    except Exception as e:
        return {"status": "error", "message": f"Failed to load vm_host connections: {e}",
                "data": None, "timestamp": _ts()}

    if not all_conns:
        return {"status": "error",
                "message": "No vm_host connections configured. Add in Settings → Connections → vm_host.",
                "data": None, "timestamp": _ts()}

    conn = None
    host_lower = host.lower().strip()
    for c in all_conns:
        label = c.get("label", "").lower()
        ip    = c.get("host", "")
        if label == host_lower or ip == host or host_lower in label:
            conn = c
            break

    if not conn:
        labels = [f"{c.get('label', '?')} ({c.get('host', '?')})" for c in all_conns]
        return {"status": "error",
                "message": f"No vm_host connection found for {host!r}. Available: {', '.join(labels)}",
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
                "host": label, "ip": conn["host"],
                "command": safe_cmd,
                "output": output.strip()[:4000],
                "truncated": len(output) > 4000,
            },
            "timestamp": _ts(),
        }
    except Exception as e:
        return {"status": "error",
                "message": f"SSH failed on {conn.get('label', host)} ({conn['host']}): {e}",
                "data": None, "timestamp": _ts()}
