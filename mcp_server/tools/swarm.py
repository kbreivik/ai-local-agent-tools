"""Docker Swarm management tools."""
import os
from datetime import datetime, timezone
from typing import Any

import docker
from docker.errors import APIError, DockerException


def _client() -> docker.DockerClient:
    host = os.environ.get("DOCKER_HOST", "npipe:////./pipe/docker_engine")
    return docker.DockerClient(base_url=host)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ok(data: Any, message: str = "OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}


def _err(message: str, data: Any = None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


def _degraded(data: Any, message: str) -> dict:
    return {"status": "degraded", "data": data, "timestamp": _ts(), "message": message}


def swarm_status() -> dict:
    """Return node health, manager/worker state."""
    try:
        client = _client()
        nodes = client.nodes.list()
        node_data = []
        all_ready = True
        for node in nodes:
            attrs = node.attrs
            spec = attrs.get("Spec", {})
            status = attrs.get("Status", {})
            manager_status = attrs.get("ManagerStatus", {})
            state = status.get("State", "unknown")
            if state != "ready":
                all_ready = False
            node_data.append({
                "id": attrs.get("ID", "")[:12],
                "hostname": spec.get("Name", attrs.get("Description", {}).get("Hostname", "unknown")),
                "role": spec.get("Role", "unknown"),
                "state": state,
                "availability": spec.get("Availability", "unknown"),
                "manager_leader": manager_status.get("Leader", False),
            })
        client.close()
        if not all_ready:
            return _degraded(node_data, "One or more nodes not in ready state")
        return _ok({"nodes": node_data, "count": len(node_data)}, f"Swarm healthy: {len(node_data)} nodes")
    except DockerException as e:
        return _err(f"Docker connection failed: {e}")
    except Exception as e:
        return _err(f"swarm_status error: {e}")


def service_list() -> dict:
    """List all services with replicas and image versions."""
    try:
        client = _client()
        services = client.services.list()
        svc_data = []
        for svc in services:
            attrs = svc.attrs
            spec = attrs.get("Spec", {})
            task_tmpl = spec.get("TaskTemplate", {})
            container_spec = task_tmpl.get("ContainerSpec", {})
            replicated = spec.get("Mode", {}).get("Replicated", {})
            desired = replicated.get("Replicas", 0) if replicated else None
            tasks = svc.tasks(filters={"desired-state": "running"})
            running = sum(1 for t in tasks if t.get("Status", {}).get("State") == "running")
            svc_data.append({
                "id": attrs.get("ID", "")[:12],
                "name": spec.get("Name", "unknown"),
                "image": container_spec.get("Image", "unknown"),
                "desired_replicas": desired,
                "running_replicas": running,
                "mode": "replicated" if replicated else "global",
            })
        client.close()
        return _ok({"services": svc_data, "count": len(svc_data)})
    except DockerException as e:
        return _err(f"Docker connection failed: {e}")
    except Exception as e:
        return _err(f"service_list error: {e}")


def service_health(name: str) -> dict:
    """Check specific service ready/degraded/failed state."""
    try:
        client = _client()
        services = client.services.list(filters={"name": name})
        if not services:
            client.close()
            return _err(f"Service '{name}' not found")
        svc = services[0]
        attrs = svc.attrs
        spec = attrs.get("Spec", {})
        task_tmpl = spec.get("TaskTemplate", {})
        container_spec = task_tmpl.get("ContainerSpec", {})
        replicated = spec.get("Mode", {}).get("Replicated", {})
        desired = replicated.get("Replicas", 1) if replicated else 1
        tasks = svc.tasks()
        running = [t for t in tasks if t.get("Status", {}).get("State") == "running"
                   and t.get("DesiredState") == "running"]
        failed = [t for t in tasks if t.get("Status", {}).get("State") == "failed"]
        client.close()
        data = {
            "name": name,
            "image": container_spec.get("Image", "unknown"),
            "desired": desired,
            "running": len(running),
            "failed_tasks": len(failed),
        }
        if len(running) == desired and desired > 0:
            return _ok(data, f"Service '{name}' healthy: {len(running)}/{desired} replicas running")
        if len(running) == 0:
            return {"status": "failed", "data": data, "timestamp": _ts(),
                    "message": f"Service '{name}' has 0/{desired} replicas running"}
        return _degraded(data, f"Service '{name}' degraded: {len(running)}/{desired} replicas running")
    except DockerException as e:
        return _err(f"Docker connection failed: {e}")
    except Exception as e:
        return _err(f"service_health error: {e}")


def service_upgrade(name: str, image: str) -> dict:
    """Rolling upgrade with health gate — verifies health before returning."""
    try:
        client = _client()
        services = client.services.list(filters={"name": name})
        if not services:
            client.close()
            return _err(f"Service '{name}' not found")
        svc = services[0]
        pre_check = pre_upgrade_check()
        if pre_check["status"] != "ok":
            client.close()
            return _err(f"Pre-upgrade check failed: {pre_check['message']}", pre_check["data"])
        svc.update(image=image)
        import time
        for _ in range(30):
            time.sleep(2)
            health = service_health(name)
            if health["status"] == "ok":
                client.close()
                return _ok({"name": name, "new_image": image}, f"Service '{name}' upgraded to {image}")
            if health["status"] == "failed":
                client.close()
                return {"status": "failed", "data": health["data"], "timestamp": _ts(),
                        "message": f"Upgrade failed: service went to failed state"}
        client.close()
        return _degraded({"name": name, "image": image}, "Upgrade timed out waiting for healthy state")
    except DockerException as e:
        return _err(f"Docker connection failed: {e}")
    except Exception as e:
        return _err(f"service_upgrade error: {e}")


def service_rollback(name: str) -> dict:
    """Revert service to previous image."""
    try:
        client = _client()
        services = client.services.list(filters={"name": name})
        if not services:
            client.close()
            return _err(f"Service '{name}' not found")
        svc = services[0]
        svc.update(rollback_config={})
        client.api.update_service(
            svc.id,
            version=svc.version["Index"],
            rollback_config={"Order": "start-first"},
        )
        # Trigger rollback
        client.api.post(f"/services/{svc.id}/rollback")
        import time
        time.sleep(3)
        health = service_health(name)
        client.close()
        return _ok({"name": name, "rollback": True}, f"Rollback initiated for '{name}'") if health["status"] in ("ok", "degraded") \
            else _err(f"Rollback may have failed: {health['message']}")
    except (DockerException, APIError) as e:
        # Try simpler rollback approach
        try:
            client2 = _client()
            services2 = client2.services.list(filters={"name": name})
            if services2:
                svc2 = services2[0]
                client2.api.post(f"/services/{svc2.id}/rollback")
                client2.close()
                return _ok({"name": name, "rollback": True}, f"Rollback triggered for '{name}'")
            client2.close()
        except Exception as inner:
            pass
        return _err(f"service_rollback error: {e}")
    except Exception as e:
        return _err(f"service_rollback error: {e}")


def node_drain(node_id: str) -> dict:
    """Safely drain a node before maintenance."""
    try:
        client = _client()
        nodes = client.nodes.list()
        target = None
        for n in nodes:
            if n.attrs.get("ID", "").startswith(node_id) or \
               n.attrs.get("Description", {}).get("Hostname", "") == node_id:
                target = n
                break
        if not target:
            client.close()
            return _err(f"Node '{node_id}' not found")
        spec = target.attrs.get("Spec", {})
        spec["Availability"] = "drain"
        target.update(spec)
        client.close()
        return _ok({"node_id": node_id, "availability": "drain"}, f"Node '{node_id}' set to drain")
    except DockerException as e:
        return _err(f"Docker connection failed: {e}")
    except Exception as e:
        return _err(f"node_drain error: {e}")


def pre_upgrade_check() -> dict:
    """Full swarm readiness gate — blocks if not ready."""
    try:
        swarm = swarm_status()
        if swarm["status"] != "ok":
            return _err(f"Swarm not healthy: {swarm['message']}", swarm["data"])
        svcs = service_list()
        if svcs["status"] == "error":
            return _err(f"Cannot list services: {svcs['message']}")
        degraded = []
        for svc in svcs["data"].get("services", []):
            desired = svc.get("desired_replicas")
            running = svc.get("running_replicas", 0)
            if desired is not None and running < desired:
                degraded.append(svc["name"])
        if degraded:
            return _degraded({"degraded_services": degraded},
                             f"Services not fully healthy: {degraded}")
        return _ok({"nodes": swarm["data"]["count"],
                    "services": svcs["data"]["count"]},
                   "Swarm ready for upgrade")
    except Exception as e:
        return _err(f"pre_upgrade_check error: {e}")
