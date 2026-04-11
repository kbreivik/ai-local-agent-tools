"""Get recent system logs from a VM host."""

SKILL_META = {
    "name": "vm_recent_logs",
    "description": "Get recent system logs from a VM host via journalctl. Supports service filter and error-level filtering.",
    "category": "compute",
    "version": "1.0.0",
    "parameters": {
        "type": "object",
        "properties": {
            "host": {"type": "string", "description": "VM host label or IP"},
            "lines": {"type": "integer", "description": "Number of log lines", "default": 50},
            "service": {"type": "string", "description": "Filter by systemd service (e.g. docker, elasticsearch)"},
            "errors_only": {"type": "boolean", "description": "Only show error-level messages", "default": False},
        },
        "required": ["host"],
    },
    "compat": {"service": "vm_host", "api_version_built_for": "1.0"},
}


def _ts():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()

def _ok(data, msg="OK"):
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": msg}

def _err(msg):
    return {"status": "error", "data": None, "timestamp": _ts(), "message": msg}


def execute(**kwargs):
    host = kwargs.get("host", "")
    lines = kwargs.get("lines", 50)
    service = kwargs.get("service", "")
    errors_only = kwargs.get("errors_only", False)
    if not host: return _err("host required")
    try:
        import httpx, os
        base = os.environ.get("HP1_API_BASE", "http://localhost:8000")
        from api.auth import create_internal_token
        headers = {"Authorization": f"Bearer {create_internal_token()}"}
        cmd = f"journalctl -n {min(lines, 500)} --no-pager"
        if service: cmd += f" -u {service}"
        if errors_only: cmd += " -p err"
        r = httpx.post(f"{base}/api/dashboard/vm-hosts/{host}/exec",
                       json={"command": cmd}, headers=headers, verify=False, timeout=15).json()
        output = r.get("output", "")
        return _ok({"logs": output, "line_count": len(output.splitlines()), "service": service or "all"},
                   f"{len(output.splitlines())} log lines from {host}")
    except Exception as e:
        return _err(f"vm_recent_logs: {e}")
