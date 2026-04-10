"""Manage Docker Swarm services — scale, update images, drain/activate nodes."""

SKILL_META = {
    "name": "swarm_manage",
    "description": (
        "Manage Docker Swarm services and nodes. "
        "Can scale services up/down, rolling-update to a new image, "
        "list service tasks with node placement, and drain/activate nodes for maintenance."
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
                "enum": ["scale", "update_image", "get_tasks", "drain_node",
                         "activate_node", "list_services"],
                "description": "Action to perform",
            },
            "service_name": {
                "type": "string",
                "description": "Full Swarm service name (e.g. logstash_logstash)",
            },
            "replicas": {
                "type": "integer",
                "description": "Number of replicas (for scale action)",
                "minimum": 0,
            },
            "image": {
                "type": "string",
                "description": "Full image reference for update_image",
            },
            "node_id": {
                "type": "string",
                "description": "Node hostname or short ID (for drain_node / activate_node)",
            },
        },
        "required": ["action"],
    },
    "auth_type": "none",
    "config_keys": [],
    "compat": {"service": "docker_swarm", "api_version_built_for": "1.44"},
}


def _ts():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()

def _ok(data, message="OK"):
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}

def _err(message, data=None):
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


def execute(**kwargs):
    import httpx
    import os
    action = kwargs.get("action", "")
    base = os.environ.get("HP1_API_BASE", "http://localhost:8000")
    try:
        from api.auth import create_internal_token
        token = create_internal_token()
    except Exception:
        token = ""
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    try:
        if action == "list_services":
            r = httpx.get(f"{base}/api/dashboard/containers/swarm",
                          headers=headers, verify=False, timeout=10)
            data = r.json()
            services = data.get("services", [])
            summary = [{"name": s["name"], "image": s.get("image", ""),
                        "running": s.get("running_replicas", 0),
                        "desired": s.get("desired_replicas", 0)}
                       for s in services]
            return _ok({"services": summary, "count": len(summary)},
                       f"{len(summary)} Swarm service(s)")

        elif action == "scale":
            svc = kwargs.get("service_name", "")
            replicas = kwargs.get("replicas")
            if not svc: return _err("service_name required")
            if replicas is None: return _err("replicas required")
            r = httpx.post(f"{base}/api/dashboard/services/{svc}/scale",
                           json={"replicas": replicas}, headers=headers, verify=False, timeout=15)
            data = r.json()
            if not data.get("ok"): return _err(data.get("error", "Scale failed"), data)
            return _ok({"service": svc, "replicas": replicas}, f"Scaled {svc} to {replicas}")

        elif action == "update_image":
            svc = kwargs.get("service_name", "")
            image = kwargs.get("image", "")
            if not svc: return _err("service_name required")
            if not image: return _err("image required")
            r = httpx.post(f"{base}/api/dashboard/services/{svc}/update-image",
                           json={"image": image}, headers=headers, verify=False, timeout=30)
            data = r.json()
            if not data.get("ok"): return _err(data.get("error", "Update failed"), data)
            return _ok(data, f"Updated {svc}: {data.get('previous_image')} → {image}")

        elif action == "get_tasks":
            svc = kwargs.get("service_name", "")
            if not svc: return _err("service_name required")
            r = httpx.get(f"{base}/api/dashboard/services/{svc}/tasks",
                          headers=headers, verify=False, timeout=10)
            data = r.json()
            if not data.get("ok"): return _err(data.get("error", "Failed"), data)
            return _ok(data, f"{len(data.get('tasks', []))} task(s) for {svc}")

        elif action == "drain_node":
            node = kwargs.get("node_id", "")
            if not node: return _err("node_id required")
            r = httpx.post(f"{base}/api/dashboard/swarm/nodes/{node}/drain",
                           headers=headers, verify=False, timeout=10)
            data = r.json()
            if not data.get("ok"): return _err(data.get("error", "Drain failed"), data)
            return _ok(data, f"Node {node} set to drain")

        elif action == "activate_node":
            node = kwargs.get("node_id", "")
            if not node: return _err("node_id required")
            r = httpx.post(f"{base}/api/dashboard/swarm/nodes/{node}/activate",
                           headers=headers, verify=False, timeout=10)
            data = r.json()
            if not data.get("ok"): return _err(data.get("error", "Activate failed"), data)
            return _ok(data, f"Node {node} activated")

        else:
            return _err(f"Unknown action: {action!r}")
    except Exception as e:
        return _err(f"swarm_manage error: {e}")
