"""Run allowlisted operations on VM hosts via SSH connections."""

SKILL_META = {
    "name": "vm_ssh",
    "description": (
        "Perform operations on VM hosts registered in DEATHSTAR connections. "
        "Read-only: get disk/memory/load status. "
        "Actions: run apt updates, restart services, reboot. "
        "Use list_hosts first to see available VMs."
    ),
    "category": "compute",
    "version": "1.0.0",
    "annotations": {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list_hosts", "status", "update", "reboot",
                         "restart_service", "apt_upgradable"],
                "description": "Action to perform on VM hosts",
            },
            "host": {
                "type": "string",
                "description": "VM host label or connection ID. Use 'all' for status/apt_upgradable.",
            },
            "service": {
                "type": "string",
                "description": "Service name for restart_service",
            },
        },
        "required": ["action"],
    },
    "auth_type": "none",
    "config_keys": [],
    "compat": {"service": "vm_host", "api_version_built_for": "1.0"},
}


def _ts():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()

def _ok(data, message="OK"):
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}

def _err(message, data=None):
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


def _api(path, method="GET", body=None):
    import httpx
    import os
    base = os.environ.get("HP1_API_BASE", "http://localhost:8000")
    try:
        from api.auth import create_internal_token
        token = create_internal_token()
    except Exception:
        token = ""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if method == "GET":
        r = httpx.get(f"{base}/api/dashboard/{path}", headers=headers, verify=False, timeout=60)
    else:
        r = httpx.post(f"{base}/api/dashboard/{path}", json=body or {},
                       headers=headers, verify=False, timeout=60)
    r.raise_for_status()
    return r.json()


def execute(**kwargs):
    action  = kwargs.get("action", "")
    host    = kwargs.get("host", "")
    service = kwargs.get("service", "")

    try:
        if action == "list_hosts":
            data = _api("vm-hosts")
            vms = data.get("vms", [])
            summary = [{"label": v["label"], "host": v.get("host", ""),
                        "os": v.get("os", ""), "uptime": v.get("uptime_fmt", ""),
                        "status": v.get("dot", "grey"), "problem": v.get("problem")}
                       for v in vms]
            return _ok({"vms": summary, "count": len(summary)},
                       f"{len(summary)} VM host(s) registered")

        elif action == "status":
            data = _api("vm-hosts")
            vms = data.get("vms", [])
            if host and host != "all":
                vms = [v for v in vms if v.get("label") == host or v.get("host") == host]
                if not vms: return _err(f"VM host {host!r} not found")
            result = []
            for v in vms:
                result.append({
                    "label": v["label"], "os": v.get("os", ""),
                    "uptime": v.get("uptime_fmt", ""),
                    "load_1m": v.get("load_1", 0), "mem_pct": v.get("mem_pct", 0),
                    "mem_gb": f"{round(v.get('mem_used_bytes', 0) / 1e9, 1)}/{round(v.get('mem_total_bytes', 0) / 1e9, 1)}",
                    "disks": [{"mount": d["mountpoint"], "pct": d["usage_pct"]}
                              for d in v.get("disks", [])],
                    "services": v.get("services", {}),
                    "dot": v.get("dot", "grey"), "problem": v.get("problem"),
                })
            return _ok({"hosts": result}, f"Status for {host or 'all VMs'}")

        elif action == "apt_upgradable":
            if not host: return _err("host required")
            data = _api(f"vm-hosts/{host}/exec", "POST", {"command": "apt list --upgradable"})
            output = data.get("output", "")
            lines = [l for l in output.splitlines() if "/" in l]
            return _ok({"upgradable": lines, "count": len(lines)},
                       f"{len(lines)} upgradable package(s) on {host}")

        elif action == "update":
            if not host: return _err("host required")
            data = _api(f"vm-hosts/{host}/update", "POST")
            return _ok({"output": data.get("output", "")[:500]},
                       f"apt update + upgrade complete on {host}")

        elif action == "reboot":
            if not host: return _err("host required")
            data = _api(f"vm-hosts/{host}/reboot", "POST")
            return _ok({"host": host}, data.get("message", f"Reboot triggered for {host}"))

        elif action == "restart_service":
            if not host: return _err("host required")
            if not service: return _err("service required")
            data = _api(f"vm-hosts/{host}/service/{service}/restart", "POST")
            if not data.get("ok"): return _err(data.get("error", "Failed"), data)
            return _ok({"host": host, "service": service}, f"{service} restarted on {host}")

        else:
            return _err(f"Unknown action: {action!r}")
    except Exception as e:
        return _err(f"vm_ssh error: {e}")
