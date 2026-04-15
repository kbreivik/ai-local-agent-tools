# api/collectors/docker_agent01.py
"""
DockerAgent01Collector — polls Docker containers on agent-01 every 30s.

Writes component="docker_agent01" to status_snapshots.
State shape: { health, containers: [ContainerCard], agent01_ip }
"""
import asyncio
import logging
import os
import re

from api.collectors.base import BaseCollector

log = logging.getLogger(__name__)

def _get_agent01_ip() -> str:
    """Resolve the LAN IP of agent-01.

    Priority:
      1. Settings DB key 'agentHostIp' (set via UI Infrastructure tab)
      2. AGENT01_IP env var
      3. docker_host connection's host field (if it's a plain IP, not unix://)
      4. '127.0.0.1' fallback
    """
    # 1. Settings DB
    try:
        from mcp_server.tools.skills.storage import get_backend
        val = get_backend().get_setting("agentHostIp")
        if val and str(val).strip() and str(val).strip() not in ("", "127.0.0.1"):
            return str(val).strip()
    except Exception:
        pass
    # 2. Env var
    env_val = os.environ.get("AGENT01_IP", "")
    if env_val and env_val not in ("", "127.0.0.1"):
        return env_val
    # 3. docker_host connection host
    try:
        from api.connections import get_all_connections_for_platform
        conns = get_all_connections_for_platform("docker_host")
        local = [c for c in conns
                 if (c.get("config") or {}).get("role") == "standalone"
                 or c.get("label", "").lower() in ("agent-01", "local", "self")]
        if local:
            h = local[0].get("host", "")
            # Only use if it looks like a plain IP (not unix://)
            if h and not h.startswith("unix://") and not h.startswith("/"):
                # Strip tcp:// prefix if present
                h = h.replace("tcp://", "").split(":")[0]
                if h and h != "127.0.0.1":
                    return h
    except Exception:
        pass
    # 4. Fallback
    return os.environ.get("AGENT01_IP", "127.0.0.1")


def _get_agent01_docker_host() -> str:
    """Get Docker host URL for agent-01. DB first, env var fallback."""
    try:
        from api.connections import get_all_connections_for_platform
        conns = get_all_connections_for_platform('docker_host')
        local = [c for c in conns
                 if (c.get('config') or {}).get('role') == 'standalone'
                 or c.get('label', '').lower() in ('agent-01', 'local', 'self')]
        if local:
            c = local[0]
            host = c['host']
            if host.startswith('unix://') or host.startswith('/'):
                return host
            return f"tcp://{host}:{c.get('port', 2375)}"
    except Exception:
        pass
    return os.environ.get("AGENT01_DOCKER_HOST", "unix:///var/run/docker.sock")


class DockerAgent01Collector(BaseCollector):
    component = "docker_agent01"

    def __init__(self):
        super().__init__()
        self.interval = int(os.environ.get("DOCKER_POLL_INTERVAL", "30"))

    def to_entities(self, state: dict) -> list:
        from api.collectors.base import Entity
        dot_to_status = {"green": "healthy", "amber": "degraded", "red": "error", "grey": "unknown"}
        entities = []
        for c in state.get("containers", []):
            name = c.get("name") or c.get("id", "unknown")
            entities.append(Entity(
                id=f"docker:{name}",
                label=name,
                component=self.component,
                platform="docker",
                section="COMPUTE",
                status=dot_to_status.get(c.get("dot", "grey"), "unknown"),
                last_error=c.get("problem"),
                metadata={
                    "image": c.get("image", ""),
                    "state": c.get("state", ""),
                    "uptime": c.get("uptime", ""),
                    "ip_port": c.get("ip_port", ""),
                    "started_at": c.get("started_at"),
                    "restart_count": c.get("restart_count"),
                },
            ))
        return entities if entities else super().to_entities(state)

    async def poll(self) -> dict:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict:
        import docker
        from docker.errors import DockerException

        vm_ip = _get_agent01_ip()
        docker_host = _get_agent01_docker_host()
        try:
            client = docker.DockerClient(base_url=docker_host, timeout=10)
        except Exception as e:
            return {"health": "error", "error": str(e), "containers": [], "agent01_ip": vm_ip}

        try:
            containers = client.containers.list(all=True)
            volume_usage = _get_volume_usage(client)
            last_digests = _load_last_digests()

            cards = []
            for c in containers:
                attrs = c.attrs
                name = (attrs.get("Name") or "").lstrip("/")
                # Strip hash prefix Docker adds on naming conflicts: "abc123ef_hp1_agent" → "hp1_agent"
                name = re.sub(r'^[0-9a-f]{12}_', '', name)
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

                # OCI image labels — only extracted for GHCR images
                running_version = None
                built_at = None
                if image.startswith("ghcr.io/") and c.image:
                    try:
                        labels = c.image.labels or {}
                    except Exception:
                        labels = {}
                    raw_ver = labels.get("org.opencontainers.image.version", "")
                    if raw_ver:
                        running_version = raw_ver.lstrip("v")
                    built_at = labels.get("org.opencontainers.image.created") or None

                dot, problem = _classify_container(state_str, health_str)
                first_port = ports[0].split("→")[0] if ports else ""
                ip_port = f"{vm_ip}:{first_port}" if first_port else ""

                # Docker networks and container IP addresses
                net_settings = attrs.get("NetworkSettings", {})
                networks_dict = net_settings.get("Networks", {})
                network_names = list(networks_dict.keys())
                ip_addresses = [
                    net_data.get("IPAddress")
                    for net_data in networks_dict.values()
                    if net_data.get("IPAddress")
                ]

                state_obj = attrs.get("State") or {}
                started_at = state_obj.get("StartedAt") or None
                # Normalise Docker's zero value ("0001-01-01T00:00:00Z") → None
                if started_at and started_at.startswith("0001-"):
                    started_at = None
                restart_count = state_obj.get("RestartCount")  # int, may be 0

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
                    "running_version": running_version,
                    "built_at": built_at,
                    "dot": dot,
                    "problem": problem,
                    "networks": network_names,
                    "ip_addresses": ip_addresses,
                    "entity_id": f"docker:{name}",
                    "started_at": started_at,
                    "restart_count": restart_count,
                })

            if not cards or all(c["dot"] == "green" for c in cards):
                overall = "healthy"
            elif all(c["dot"] == "red" for c in cards):
                overall = "critical"
            else:
                overall = "degraded"

            # Connection metadata for frontend Section header
            connection_id = ""
            connection_label = "agent-01"
            connection_host = vm_ip
            try:
                from api.connections import get_connection_for_platform
                docker_conn = get_connection_for_platform("docker_host")
                if docker_conn:
                    connection_id = str(docker_conn.get("id", ""))
                    connection_label = docker_conn.get("label", "agent-01")
                    connection_host = docker_conn.get("host", vm_ip)
            except Exception:
                pass

            return {
                "health": overall,
                "containers": cards,
                "agent01_ip": vm_ip,
                "connection_id": connection_id,
                "connection_label": connection_label,
                "connection_host": connection_host,
            }

        except DockerException as e:
            return {"health": "error", "error": str(e), "containers": [], "agent01_ip": vm_ip}
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
        from api.db.base import get_sync_engine
        from sqlalchemy import text
        with get_sync_engine().connect() as conn:
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
        from api.db.base import get_sync_engine
        from sqlalchemy import text
        now = datetime.now(timezone.utc).isoformat()
        try:
            with get_sync_engine().begin() as conn:
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
