"""Find large files on a VM host."""

SKILL_META = {
    "name": "vm_large_files",
    "description": "Find files larger than a threshold on a VM host, sorted by size. Useful for diagnosing disk consumption.",
    "category": "compute",
    "version": "1.0.0",
    "parameters": {
        "type": "object",
        "properties": {
            "host": {"type": "string", "description": "VM host label or IP"},
            "min_size_mb": {"type": "integer", "description": "Minimum file size in MB", "default": 100},
            "path": {"type": "string", "description": "Path to search", "default": "/"},
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
    size = kwargs.get("min_size_mb", 100)
    path = kwargs.get("path", "/")
    if not host: return _err("host required")
    try:
        import httpx, os
        base = os.environ.get("HP1_API_BASE", "http://localhost:8000")
        from api.auth import create_internal_token
        headers = {"Authorization": f"Bearer {create_internal_token()}"}
        cmd = f"find {path} -size +{size}M -type f -printf '%s %p\\n' 2>/dev/null | sort -rn | head -20"
        r = httpx.post(f"{base}/api/dashboard/vm-hosts/{host}/exec",
                       json={"command": cmd}, headers=headers, verify=False, timeout=30).json()
        output = r.get("output", "")
        files = []
        for line in output.strip().splitlines():
            parts = line.split(" ", 1)
            if len(parts) == 2:
                files.append({"size_bytes": int(parts[0]), "size_mb": round(int(parts[0]) / 1e6, 1), "path": parts[1]})
        return _ok({"files": files, "count": len(files)}, f"{len(files)} files >{size}MB on {host}")
    except Exception as e:
        return _err(f"vm_large_files: {e}")
