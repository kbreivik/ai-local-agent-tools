# api/collectors/docker_agent01.py
"""
DockerAgent01Collector — polls Docker containers on agent-01 every 30s.

Writes component="docker_agent01" to status_snapshots.
State shape: { health, containers: [ContainerCard], agent01_ip }
"""
import asyncio
import logging
import os

from api.collectors.base import BaseCollector

log = logging.getLogger(__name__)

VM_IP = "192.168.199.10"


class DockerAgent01Collector(BaseCollector):
    component = "docker_agent01"

    def __init__(self):
        super().__init__()
        self.interval = int(os.environ.get("DOCKER_POLL_INTERVAL", "30"))

    async def poll(self) -> dict:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict:
        import docker
        from docker.errors import DockerException

        docker_host = os.environ.get("AGENT01_DOCKER_HOST", "unix:///var/run/docker.sock")
        try:
            client = docker.DockerClient(base_url=docker_host, timeout=10)
        except Exception as e:
            return {"health": "error", "error": str(e), "containers": [], "agent01_ip": VM_IP}

        try:
            containers = client.containers.list(all=True)
            volume_usage = _get_volume_usage(client)
            last_digests = _load_last_digests()

            cards = []
            for c in containers:
                attrs = c.attrs
                name = (attrs.get("Name") or "").lstrip("/")
                image = attrs.get("Config", {}).get("Image", "")
                state_str = (attrs.get("State") or {}).get("Status", "unknown")
                health_obj = (attrs.get("State") or {}).get("Health", {})
                health_str = health_obj.get("Status", "none") if health_obj else "none"
                ports = _parse_ports(attrs.get("NetworkSettings", {}).get("Ports", {}))
                mounts = [
                    m for m in (attrs.get("Mounts") or []) if m.get("Type") == "volume"
                ]
                volumes = [
                    {
                        "name": m["Name"],
                        "used_bytes": volume_usage.get(m["Name"], {}).get("used_bytes"),
                        "total_bytes": volume_usage.get(m["Name"], {}).get("total_bytes"),
                    }
                    for m in mounts
                ]

                image_id = c.image.id if c.image else None
                last_pull_at = _check_digest(c.id, image, image_id, last_digests)

                dot, problem = _classify_container(state_str, health_str)
                first_port = ports[0].split("→")[0] if ports else ""
                ip_port = f"{VM_IP}:{first_port}" if first_port else ""

                cards.append({
                    "id": c.short_id,
                    "name": name,
                    "image": image,
                    "state": state_str,
                    "health": health_str,
                    "ip_port": ip_port,
                    "uptime": attrs.get("Status", ""),
                    "ports": ports,
                    "volumes": volumes,
                    "last_pull_at": last_pull_at,
                    "dot": dot,
                    "problem": problem,
                })

            if not cards or all(c["dot"] == "green" for c in cards):
                overall = "healthy"
            elif all(c["dot"] == "red" for c in cards):
                overall = "critical"
            else:
                overall = "degraded"
            return {"health": overall, "containers": cards, "agent01_ip": VM_IP}

        except DockerException as e:
            return {"health": "error", "error": str(e), "containers": [], "agent01_ip": VM_IP}
        finally:
            try:
                client.close()
            except Exception:
                pass


def _parse_ports(ports_dict: dict) -> list[str]:
    result = []
    for container_port, bindings in ports_dict.items():
        if not bindings:
            continue
        for b in bindings:
            host_port = b.get("HostPort", "")
            cp = container_port.split("/")[0]
            if host_port:
                result.append(f"{host_port}→{cp}")
    return result


def _get_volume_usage(client) -> dict:
    """Returns {volume_name: {used_bytes, total_bytes}} from docker df."""
    try:
        df = client.df()
        result = {}
        for v in df.get("Volumes") or []:
            name = v.get("Name", "")
            usage = v.get("UsageData", {})
            result[name] = {
                "used_bytes": usage.get("Size"),
                "total_bytes": None,
            }
        return result
    except Exception:
        return {}


def _load_last_digests() -> dict:
    """Load stored image digests from status_snapshots."""
    import json
    try:
        from api.db.base import _engine
        from sqlalchemy import text
        with _engine.connect() as conn:
            rows = conn.execute(
                text("SELECT component, state, timestamp FROM status_snapshots "
                     "WHERE component LIKE 'image_digest:%' "
                     "ORDER BY timestamp DESC LIMIT 500")
            ).fetchall()
        result = {}
        for row in rows:
            comp = row[0]
            state = row[1] if isinstance(row[1], dict) else json.loads(row[1] or "{}")
            ts = row[2]
            if comp not in result:
                state["_ts"] = str(ts) if ts else None
                result[comp] = state
        return result
    except Exception:
        return {}


def _check_digest(container_id: str, image: str, image_id: str | None, last_digests: dict) -> str | None:
    """Compare current image_id to stored. If changed or new, write new snapshot."""
    if not image_id:
        return None
    key = f"image_digest:{image}"
    stored = last_digests.get(key, {})
    if stored.get("digest") != image_id:
        import json
        from datetime import datetime, timezone
        from api.db.base import _engine
        from sqlalchemy import text
        now = datetime.now(timezone.utc).isoformat()
        try:
            with _engine.begin() as conn:
                conn.execute(
                    text("INSERT INTO status_snapshots (component, state, is_healthy, timestamp) "
                         "VALUES (:comp, :state, true, :ts)"),
                    {"comp": key, "state": json.dumps({"digest": image_id, "image": image}), "ts": now}
                )
        except Exception as e:
            log.warning("Failed to write image digest snapshot for %s: %s", key, e)
        return now
    return stored.get("_ts")  # timestamp from DB row


def _classify_container(state: str, health: str) -> tuple[str, str | None]:
    if state == "running":
        if health in ("healthy", "none"):
            return "green", None
        if health in ("starting",):
            return "amber", "starting"
        if health == "unhealthy":
            return "red", "health check failing"
    return "red", "exited"
