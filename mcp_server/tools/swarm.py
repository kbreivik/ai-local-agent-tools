"""Docker Swarm management tools."""
import os
import re
import urllib.request
import json as _json
from datetime import datetime, timezone
from typing import Any

import docker
from docker.errors import APIError, DockerException


_SEMVER3_RE    = re.compile(r"^\d+\.\d+\.\d+$")
_PRERELEASE_RE = re.compile(r"(rc|alpha|beta|snapshot|dev|preview)", re.IGNORECASE)

_VENDOR_SWITCH_PHRASES = ("switch image", "change vendor", "migrate to")


def _image_vendor(image: str) -> str:
    """
    Extract the org/vendor prefix from a Docker image reference.

    Examples:
      apache/kafka:4.2.0          → "apache"
      confluentinc/cp-kafka:7.6   → "confluentinc"
      nginx:1.25                  → ""        (Docker Hub official — no org)
      registry.example.com/org/app → "org"   (skip registry hostname)
    """
    base = image.split("@")[0].split(":")[0]   # strip digest and tag
    parts = base.split("/")
    if len(parts) == 1:
        return ""   # official Docker Hub image (e.g. "nginx")
    # If the first segment looks like a hostname (contains "." or ":"), skip it
    if "." in parts[0] or ":" in parts[0]:
        return parts[1] if len(parts) > 2 else ""
    return parts[0]


def _ver_tuple(tag: str) -> tuple:
    parts = tag.split(".")
    return tuple(int(x) for x in parts[:3])


def _stable_tags_sorted(image: str, page_size: int = 100) -> list:
    """
    Fetch Docker Hub tags for an image and return all strict stable semver (X.Y.Z)
    tags sorted descending. Excludes rc/alpha/beta/snapshot/dev/preview.
    Returns empty list on failure or no stable tags found.
    """
    repo = image.split(":")[0].split("@")[0]
    if "/" not in repo:
        repo = f"library/{repo}"
    url = (
        f"https://hub.docker.com/v2/repositories/{repo}/tags"
        f"?page_size={page_size}&ordering=last_updated"
    )
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            data = _json.loads(r.read())
        tags = [t["name"] for t in data.get("results", [])]
        stable = [
            t for t in tags
            if _SEMVER3_RE.match(t) and not _PRERELEASE_RE.search(t)
        ]
        stable.sort(key=_ver_tuple, reverse=True)
        return stable
    except Exception:
        return []


def _client() -> docker.DockerClient:
    default = (
        "npipe:////./pipe/docker_engine" if os.name == "nt"
        else "unix:///var/run/docker.sock"
    )
    host = os.environ.get("DOCKER_HOST", default)
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


def service_current_version(name: str) -> dict:
    """Return the currently running image tag for a service (digest stripped)."""
    try:
        client = _client()
        services = client.services.list(filters={"name": name})
        if not services:
            client.close()
            return _err(f"Service '{name}' not found")
        svc = services[0]
        container_spec = svc.attrs.get("Spec", {}).get("TaskTemplate", {}).get("ContainerSpec", {})
        image_full = container_spec.get("Image", "unknown")
        tag = image_full.split("@")[0] if "@" in image_full else image_full
        client.close()
        return _ok({"name": name, "image": tag, "image_with_digest": image_full},
                   f"Service '{name}' running {tag}")
    except DockerException as e:
        return _err(f"Docker connection failed: {e}")
    except Exception as e:
        return _err(f"service_current_version error: {e}")


def service_resolve_image(image: str, resolve_previous: bool = True) -> dict:
    """
    Resolve stable semver tags for an image from Docker Hub.
    When resolve_previous=True (default) also returns previous_major,
    previous_minor, and the full sorted all_stable list — useful for
    downgrade target selection.
    """
    base = image.split(":")[0].split("@")[0]
    tags = _stable_tags_sorted(base, page_size=100)
    if not tags:
        return _err(f"Could not resolve stable tags for '{base}' from Docker Hub")

    latest = tags[0]
    result: dict = {
        "image":             base,
        "latest_stable_tag": latest,
        "resolved":          f"{base}:{latest}",
    }

    if resolve_previous:
        latest_v = _ver_tuple(latest)
        prev_major = next(
            (t for t in tags if _ver_tuple(t)[0] < latest_v[0]),
            None,
        )
        prev_minor = next(
            (t for t in tags
             if _ver_tuple(t)[0] == latest_v[0] and _ver_tuple(t)[1] < latest_v[1]),
            None,
        )
        result["previous_major"] = prev_major
        result["previous_minor"] = prev_minor
        result["all_stable"]     = tags

    msg = f"Latest stable for '{base}': {latest}"
    if resolve_previous and len(tags) > 1:
        msg += f" ({len(tags)} stable versions found)"
    return _ok(result, msg)


def service_version_history(image: str, count: int = 5) -> dict:
    """
    Return the last {count} stable semver versions for an image from Docker Hub,
    sorted descending. Use when downgrading — pick the version immediately below
    the current running version from the returned list.

    IMPORTANT: If passed a service name instead of an image (no '/' in string),
    this function auto-resolves the running image via service_current_version().
    Always call service_current_version() first to confirm what is actually running.
    """
    # Auto-resolve service name → actual Docker image
    if "/" not in image and ":" not in image:
        svc_result = service_current_version(image)
        if svc_result["status"] != "ok":
            return _err(
                f"Could not resolve service '{image}' to an image: {svc_result['message']}. "
                f"Call service_current_version('{image}') directly to diagnose."
            )
        image = svc_result["data"]["image"]

    base = image.split(":")[0].split("@")[0]
    tags = _stable_tags_sorted(base, page_size=100)
    if not tags:
        return _err(f"Could not fetch version history for '{base}' from Docker Hub")
    selected = tags[:count]
    return _ok(
        {
            "image":        base,
            "count":        len(selected),
            "versions":     selected,
            "total_stable": len(tags),
        },
        f"Last {len(selected)} stable versions for '{base}': {', '.join(selected)}",
    )


def service_upgrade(name: str, image: str, task_hint: str = "") -> dict:
    """
    Rolling upgrade with health gate — verifies health before returning.

    task_hint: Optional excerpt from the user's original task. Used only to
               detect explicit vendor-switch intent ("switch image", "change
               vendor", "migrate to") which bypasses the vendor lock guardrail.
    """
    try:
        client = _client()
        services = client.services.list(filters={"name": name})
        if not services:
            client.close()
            return _err(f"Service '{name}' not found")
        svc = services[0]

        # ── Vendor lock guardrail ─────────────────────────────────────────────
        current_image = (
            svc.attrs.get("Spec", {})
               .get("TaskTemplate", {})
               .get("ContainerSpec", {})
               .get("Image", "")
        )
        current_vendor  = _image_vendor(current_image)
        proposed_vendor = _image_vendor(image)

        if (current_vendor or proposed_vendor) and current_vendor != proposed_vendor:
            # Allow bypass only when the task explicitly requests a vendor switch
            hint_lower = task_hint.lower()
            if not any(phrase in hint_lower for phrase in _VENDOR_SWITCH_PHRASES):
                client.close()
                return {
                    "status": "failed",
                    "message": (
                        f"Image vendor mismatch. Current image uses '{current_vendor or 'official'}', "
                        f"proposed image uses '{proposed_vendor or 'official'}'. Switching image vendors "
                        f"requires explicit confirmation. Use escalate() if this is intentional."
                    ),
                    "data": {
                        "current_image":  current_image,
                        "proposed_image": image,
                        "current_vendor":  current_vendor or "official",
                        "proposed_vendor": proposed_vendor or "official",
                    },
                    "timestamp": _ts(),
                }
        # ─────────────────────────────────────────────────────────────────────

        pre_check = pre_upgrade_check()
        if pre_check["status"] != "ok":
            client.close()
            return _err(f"Pre-upgrade check failed: {pre_check['message']}", pre_check["data"])
        # Docker Swarm update API rejects tag@sha256:digest format — strip digest
        clean_image = image.split("@")[0] if "@" in image else image
        desired = svc.attrs.get("Spec", {}).get("Mode", {}).get("Replicated", {}).get("Replicas", 1)
        svc.update(image=clean_image)
        import time
        # Poll task state every 5s for up to 90s.
        # Filter to tasks with DesiredState=="running" (current tasks); ignore
        # DesiredState=="shutdown" tasks — those are the old replicas being stopped.
        # Converging states (starting/preparing/pending/assigned/accepted) are not failures.
        TERMINAL_FAIL = {"failed", "rejected"}
        for _ in range(18):
            time.sleep(5)
            tasks = svc.tasks()
            current = [t for t in tasks if t.get("DesiredState") == "running"]
            if not current:
                continue  # tasks not scheduled yet
            running = [t for t in current if t.get("Status", {}).get("State") == "running"]
            failed  = [t for t in current if t.get("Status", {}).get("State") in TERMINAL_FAIL]
            if len(running) >= desired:
                client.close()
                return _ok({"name": name, "new_image": image}, f"Service '{name}' upgraded to {image}")
            if failed:
                client.close()
                rollback_result = service_rollback(name)
                return {"status": "failed",
                        "data": {"name": name, "failed_tasks": len(failed), "running": len(running)},
                        "timestamp": _ts(),
                        "message": f"Upgrade failed: {len(failed)} task(s) reached failed/rejected state — rollback attempted",
                        "rollback": {"attempted": True, "status": rollback_result.get("status"),
                                     "message": rollback_result.get("message")}}
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
            return _err(f"service_rollback fallback also failed: {inner} (original: {e})")
        return _err(f"service_rollback error: {e}")
    except Exception as e:
        return _err(f"service_rollback error: {e}")


def _node_set_availability(node_id: str, availability: str) -> dict:
    """Internal helper — set a node's availability to drain/active/pause."""
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
        spec["Availability"] = availability
        target.update(spec)
        client.close()
        return _ok({"node_id": node_id, "availability": availability},
                   f"Node '{node_id}' set to {availability}")
    except DockerException as e:
        return _err(f"Docker connection failed: {e}")
    except Exception as e:
        return _err(f"node availability update error: {e}")


def node_drain(node_id: str) -> dict:
    """Safely drain a node before maintenance. Use node_activate to reverse."""
    return _node_set_availability(node_id, "drain")


def node_activate(node_id: str) -> dict:
    """Re-activate a drained or paused node so it can accept tasks again."""
    return _node_set_availability(node_id, "active")


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
