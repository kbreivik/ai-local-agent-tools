"""Check disk usage on a VM host."""

SKILL_META = {
    "name": "vm_disk_check",
    "description": "Check disk usage on a VM host. Returns df output and top directories consuming space.",
    "category": "compute",
    "version": "1.0.0",
    "parameters": {
        "type": "object",
        "properties": {
            "host": {"type": "string", "description": "VM host label or IP"},
            "path": {"type": "string", "description": "Path to check (default: /)", "default": "/"},
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
    path = kwargs.get("path", "/")
    if not host: return _err("host required")
    try:
        import httpx, os
        base = os.environ.get("HP1_API_BASE", "http://localhost:8000")
        from api.auth import create_internal_token
        headers = {"Authorization": f"Bearer {create_internal_token()}"}
        df = httpx.post(f"{base}/api/dashboard/vm-hosts/{host}/exec",
                        json={"command": "df -h"}, headers=headers, verify=False, timeout=15).json()
        du = httpx.post(f"{base}/api/dashboard/vm-hosts/{host}/exec",
                        json={"command": f"du -sh {path}/*"}, headers=headers, verify=False, timeout=15).json()
        return _ok({"df": df.get("output", ""), "du": du.get("output", "")},
                   f"Disk usage on {host}")
    except Exception as e:
        return _err(f"vm_disk_check: {e}")
