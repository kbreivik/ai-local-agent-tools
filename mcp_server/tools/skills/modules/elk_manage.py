"""Upgrade and manage the ELK stack running as Docker Swarm services."""

SKILL_META = {
    "name": "elk_manage",
    "description": (
        "Upgrade and manage ELK stack components (Elasticsearch, Logstash, Kibana, Filebeat) "
        "running as Docker Swarm services. "
        "Can check current versions, upgrade to a new version, restart a component, "
        "or show which nodes each replica is running on. "
        "ALWAYS check current version before upgrading. "
        "Upgrade order for major versions: Elasticsearch first, then Kibana, then Logstash/Filebeat."
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
                "enum": ["status", "upgrade", "restart", "placement"],
                "description": "Action to perform on ELK components",
            },
            "component": {
                "type": "string",
                "enum": ["elasticsearch", "logstash", "kibana", "filebeat", "all"],
                "description": "ELK component to act on",
            },
            "version": {
                "type": "string",
                "description": "Target version for upgrade e.g. '8.14.0'",
            },
        },
        "required": ["action"],
    },
    "auth_type": "none",
    "config_keys": [],
    "compat": {"service": "docker_swarm", "api_version_built_for": "1.44"},
}

ELK_SERVICES = {
    "elasticsearch": {"service_pattern": "elasticsearch", "image_base": "docker.elastic.co/elasticsearch/elasticsearch"},
    "logstash":      {"service_pattern": "logstash",      "image_base": "docker.elastic.co/logstash/logstash"},
    "kibana":        {"service_pattern": "kibana",        "image_base": "docker.elastic.co/kibana/kibana"},
    "filebeat":      {"service_pattern": "filebeat",      "image_base": "docker.elastic.co/beats/filebeat"},
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
        r = httpx.get(f"{base}/api/dashboard/{path}", headers=headers, verify=False, timeout=15)
    else:
        r = httpx.post(f"{base}/api/dashboard/{path}", json=body or {},
                       headers=headers, verify=False, timeout=60)
    r.raise_for_status()
    return r.json()


def _get_swarm_services():
    return _api("containers/swarm").get("services", [])


def _find_service(services, pattern):
    for s in services:
        if pattern in s["name"].lower():
            return s
    return None


def _current_version(image):
    bare = image.split("@")[0]
    return bare.split(":")[-1] if ":" in bare else "unknown"


def execute(**kwargs):
    action    = kwargs.get("action", "")
    component = kwargs.get("component", "all")
    version   = kwargs.get("version", "")

    try:
        services = _get_swarm_services()

        if action == "status":
            components = list(ELK_SERVICES.keys()) if component == "all" else [component]
            result = []
            for comp in components:
                cfg = ELK_SERVICES.get(comp)
                if not cfg: continue
                svc = _find_service(services, cfg["service_pattern"])
                if not svc:
                    result.append({"component": comp, "found": False})
                else:
                    result.append({
                        "component": comp, "found": True, "service": svc["name"],
                        "image": svc.get("image", ""),
                        "version": _current_version(svc.get("image", "")),
                        "running": svc.get("running_replicas", 0),
                        "desired": svc.get("desired_replicas", 0),
                    })
            found = [r for r in result if r.get("found")]
            versions = list({r["version"] for r in found if r.get("version") != "unknown"})
            ver_str = versions[0] if len(versions) == 1 else f"mixed ({', '.join(versions)})"
            return _ok({"components": result}, f"ELK stack version: {ver_str}" if found else "No ELK services found")

        elif action == "upgrade":
            if not version: return _err("version required for upgrade")
            components = list(ELK_SERVICES.keys()) if component == "all" else [component]
            results = []
            for comp in components:
                cfg = ELK_SERVICES.get(comp)
                if not cfg:
                    results.append({"component": comp, "ok": False, "error": "Unknown"}); continue
                svc = _find_service(services, cfg["service_pattern"])
                if not svc:
                    results.append({"component": comp, "ok": False, "error": "Not found"}); continue
                new_image = f"{cfg['image_base']}:{version}"
                old_ver = _current_version(svc.get("image", ""))
                r = _api(f"services/{svc['name']}/update-image", "POST", {"image": new_image})
                results.append({"component": comp, "service": svc["name"],
                                "ok": r.get("ok", False), "from": old_ver, "to": version,
                                "error": r.get("error") if not r.get("ok") else None})
            ok_count = sum(1 for r in results if r.get("ok"))
            return _ok({"upgrades": results, "version": version},
                       f"Upgraded {ok_count}/{len(results)} ELK component(s) to {version}")

        elif action == "restart":
            components = list(ELK_SERVICES.keys()) if component == "all" else [component]
            results = []
            for comp in components:
                cfg = ELK_SERVICES.get(comp)
                if not cfg: continue
                svc = _find_service(services, cfg["service_pattern"])
                if not svc:
                    results.append({"component": comp, "ok": False, "error": "Not found"}); continue
                desired = svc.get("desired_replicas", 1)
                r0 = _api(f"services/{svc['name']}/scale", "POST", {"replicas": 0})
                import time; time.sleep(3)
                r1 = _api(f"services/{svc['name']}/scale", "POST", {"replicas": desired})
                results.append({"component": comp, "service": svc["name"],
                                "ok": r0.get("ok") and r1.get("ok"), "replicas": desired})
            ok_count = sum(1 for r in results if r.get("ok"))
            return _ok({"restarts": results}, f"Restarted {ok_count}/{len(results)} ELK component(s)")

        elif action == "placement":
            components = list(ELK_SERVICES.keys()) if component == "all" else [component]
            result = []
            for comp in components:
                cfg = ELK_SERVICES.get(comp)
                if not cfg: continue
                svc = _find_service(services, cfg["service_pattern"])
                if not svc: continue
                data = _api(f"services/{svc['name']}/tasks")
                tasks = data.get("tasks", [])
                result.append({"component": comp, "service": svc["name"],
                               "tasks": [{"node": t["node"], "state": t["state"]}
                                         for t in tasks if t.get("state") == "running"]})
            return _ok({"placement": result}, f"Task placement for {component}")

        else:
            return _err(f"Unknown action: {action!r}")
    except Exception as e:
        return _err(f"elk_manage error: {e}")
