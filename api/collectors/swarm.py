"""
SwarmCollector — polls Docker Swarm every SWARM_POLL_INTERVAL seconds.

Collects: node list (id, hostname, role, state, availability),
service list (name, desired vs running replicas, image, update_state),
and derives an overall health signal:
  healthy  — all nodes active, all services at desired replicas
  degraded — 1+ nodes drain/pause OR 1+ services under-replicated
  critical — manager quorum at risk OR majority services failed
  error    — cannot reach Docker daemon
"""
import asyncio
import logging
import os

from api.collectors.base import BaseCollector

log = logging.getLogger(__name__)


def _build_docker_client_for_conn(conn):
    """Build a Docker client for a single docker_host connection.
    Supports tcp (plain), tls (mutual auth), and ssh (tunnel) modes.
    TLS/SSH keys written to tempfile with chmod 600, deleted in finally."""
    import docker
    import tempfile

    host  = conn.get("host", "")
    port  = conn.get("port") or 2375
    mode  = conn.get("auth_type", "tcp")
    creds = conn.get("credentials") or {}
    cfg   = conn.get("config") or {}

    if host.startswith("unix://") or host.startswith("/"):
        return docker.DockerClient(base_url=host, timeout=10)

    if mode == "ssh":
        # Profile-first credential resolution (v2.33.17). Profile is authoritative
        # when linked via config.credential_profile_id; inline creds are override-only.
        try:
            from api.db.credential_profiles import resolve_credentials_for_connection
            resolved = resolve_credentials_for_connection(conn, []) or {}
        except Exception as _re:
            log.debug("profile resolve failed for docker_host %s: %s", conn.get("label"), _re)
            resolved = creds
        ssh_user = creds.get("username") or resolved.get("username") or "ubuntu"
        pkey     = resolved.get("private_key") or creds.get("private_key")
        if pkey:
            tf = tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False)
            tf.write(pkey); tf.flush(); tf.close()
            os.chmod(tf.name, 0o600)
            try:
                return docker.DockerClient(
                    base_url=f"ssh://{ssh_user}@{host}",
                    use_ssh_client=True, timeout=15)
            finally:
                os.unlink(tf.name)
        # Password SSH not supported by Docker SDK SSH transport
        log.warning("docker_host SSH: no private key for %s, falling back to TCP", conn.get("label"))
        return docker.DockerClient(base_url=f"tcp://{host}:{port}", timeout=10)

    elif mode == "tls":
        ca   = creds.get("ca_cert", "")
        cert = creds.get("client_cert", "")
        key  = creds.get("client_key", "")
        if ca and cert and key:
            paths = []
            for content, suffix in [(ca, "-ca.pem"), (cert, "-cert.pem"), (key, "-key.pem")]:
                tf = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False)
                tf.write(content); tf.flush(); tf.close()
                paths.append(tf.name)
            try:
                tls_config = docker.tls.TLSConfig(
                    client_cert=(paths[1], paths[2]), ca_cert=paths[0], verify=True)
                return docker.DockerClient(base_url=f"tcp://{host}:{port}", tls=tls_config, timeout=10)
            finally:
                for p in paths:
                    try: os.unlink(p)
                    except Exception: pass
        log.warning("docker_host TLS: missing certs for %s, falling back to TCP", conn.get("label"))

    # tcp — plain, no auth. Port 2375 is unauthenticated —
    # secure only on private LANs. Use TLS or SSH for internet-facing hosts.
    return docker.DockerClient(base_url=f"tcp://{host}:{port}", timeout=10)


def _build_swarm_docker_client():
    """Build a Docker client for the Swarm manager connection.
    Falls back to DOCKER_HOST env var if no DB connection found."""
    import docker

    try:
        from api.connections import get_all_connections_for_platform
        conns = get_all_connections_for_platform("docker_host")
        managers = [c for c in conns
                    if (c.get("config") or {}).get("role") in ("swarm_manager", "manager")
                    or "manager" in c.get("label", "").lower()]
        if managers:
            return _build_docker_client_for_conn(managers[0])
    except Exception:
        pass

    fallback = os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")
    return docker.DockerClient(base_url=fallback, timeout=10)


class SwarmCollector(BaseCollector):
    component = "swarm"

    def __init__(self):
        super().__init__()
        self.interval = int(os.environ.get("SWARM_POLL_INTERVAL", "30"))

    def to_entities(self, state: dict) -> list:
        from api.collectors.base import Entity
        entities = []
        for svc in state.get("services", []):
            name = svc.get("name", "unknown")
            running = svc.get("running_replicas", 0)
            desired = svc.get("desired_replicas", 0)
            if desired == 0:
                status = "unknown"
            elif running == 0:
                status = "error"
            elif running < desired:
                status = "degraded"
            else:
                status = "healthy"
            entities.append(Entity(
                id=f"swarm:service:{name}",
                label=name,
                component=self.component,
                platform="docker",
                section="COMPUTE",
                status=status,
                last_error=None if status == "healthy" else f"{running}/{desired} replicas",
                metadata={
                    "image": svc.get("image", ""),
                    "running_replicas": running,
                    "desired_replicas": desired,
                    "update_state": svc.get("update_state", ""),
                },
            ))
        return entities if entities else super().to_entities(state)

    async def poll(self) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._collect_sync)

    def _collect_sync(self) -> dict:
        import docker
        from docker.errors import DockerException

        try:
            client = _build_swarm_docker_client()
        except Exception as e:
            return {
                "health": "error",
                "error": str(e),
                "message": f"Cannot connect to Docker: {e}",
                "nodes": [], "services": [],
                "node_count": 0, "service_count": 0,
            }

        try:
            # ── Nodes ──────────────────────────────────────────────────────────
            nodes = client.nodes.list()
            node_data = []
            manager_count = 0
            active_managers = 0
            degraded_nodes = []

            for node in nodes:
                attrs = node.attrs
                spec = attrs.get("Spec", {})
                st = attrs.get("Status", {})
                mgr = attrs.get("ManagerStatus", {})
                desc = attrs.get("Description", {})
                engine = desc.get("Engine", {})
                platform = desc.get("Platform", {})

                role = spec.get("Role", "unknown")
                state = st.get("State", "unknown")
                avail = spec.get("Availability", "active")

                if role == "manager":
                    manager_count += 1
                    if state == "ready" and avail == "active":
                        active_managers += 1

                if state != "ready" or avail not in ("active",):
                    node_name = spec.get("Name") or desc.get("Hostname", "unknown")
                    degraded_nodes.append(node_name)

                node_data.append({
                    "id": attrs.get("ID", "")[:12],
                    "hostname": spec.get("Name", desc.get("Hostname", "unknown")),
                    "role": role,
                    "state": state,
                    "availability": avail,
                    "leader": mgr.get("Leader", False),
                    "addr": st.get("Addr", ""),
                    "engine_version": engine.get("EngineVersion", ""),
                    "os": f"{platform.get('OS','')}/{platform.get('Architecture','')}",
                })

            # ── Services ───────────────────────────────────────────────────────
            services = client.services.list()
            svc_data = []
            degraded_services = []
            failed_services = []

            for svc in services:
                attrs = svc.attrs
                spec = attrs.get("Spec", {})
                task_tmpl = spec.get("TaskTemplate", {})
                container_spec = task_tmpl.get("ContainerSpec", {})
                replicated = spec.get("Mode", {}).get("Replicated", {})
                desired = replicated.get("Replicas", 0) if replicated else 0

                tasks = svc.tasks(filters={"desired-state": "running"})
                running = sum(
                    1 for t in tasks
                    if t.get("Status", {}).get("State") == "running"
                )

                name = spec.get("Name", "unknown")
                update_st = attrs.get("UpdateStatus", {})

                if desired > 0:
                    if running == 0:
                        failed_services.append(name)
                    elif running < desired:
                        degraded_services.append(name)

                # Separate tag from digest for change tracking
                image_full = container_spec.get("Image", "unknown")
                log.debug("[Swarm] %s image from spec: %s", name, image_full)
                image = image_full.split("@")[0]    # strip digest for display
                image_digest = ""
                if "@sha256:" in image_full:
                    image_digest = "sha256:" + image_full.split("@sha256:")[1][:16]

                # Service networks from task template
                svc_networks = [
                    net.get("Target") or net.get("NetworkID", "")[:12]
                    for net in task_tmpl.get("Networks", [])
                ]

                svc_data.append({
                    "id": attrs.get("ID", "")[:12],
                    "name": name,
                    "image": image,
                    "image_digest": image_digest,
                    "desired_replicas": desired,
                    "running_replicas": running,
                    "mode": "replicated" if replicated else "global",
                    "update_state": update_st.get("State", ""),
                    "networks": svc_networks,
                    "entity_id": f"swarm:service:{name}",
                })

            # v2.43.2 — Resolve overlay network IDs to human-readable names.
            # Build a map once using the already-open Docker client.
            net_id_to_name: dict[str, str] = {}
            try:
                for net in client.networks.list(filters={"driver": "overlay"}):
                    nid  = net.attrs.get("Id", "")
                    name = net.attrs.get("Name", "")
                    if nid and name:
                        net_id_to_name[nid]       = name   # full ID
                        net_id_to_name[nid[:12]]  = name   # short ID used in svc_networks
            except Exception as _ne:
                log.debug("[Swarm] network name resolution failed: %s", _ne)

            # Patch svc_data entries with resolved network names
            for svc in svc_data:
                raw_nets = svc.get("networks") or []
                svc["network_names"] = [
                    net_id_to_name.get(nid, nid)   # fall back to raw ID if unresolved
                    for nid in raw_nets
                ]

            # v2.43.4: stash full overlay network list for cluster-level fact
            overlay_networks_list = sorted(set(net_id_to_name.values()))

            client.close()

            # ── Image digest change detection ─────────────────────────────────
            try:
                from api.db.entity_history import write_change, write_event, get_last_known_values
                for svc in svc_data:
                    name = svc.get("name", "")
                    digest = svc.get("image_digest", "")
                    if not digest or not name:
                        continue
                    entity_id = f"swarm:service:{name}"
                    last = get_last_known_values(entity_id, ["image_digest", "image_tag"])
                    old_digest = last.get("image_digest")
                    old_tag = last.get("image_tag")
                    new_tag = svc.get("image", "")

                    if old_digest and old_digest != digest:
                        write_change(
                            entity_id=entity_id, entity_type="swarm_service",
                            field_name="image_digest",
                            old_value=old_digest, new_value=digest,
                            source_collector="swarm",
                        )
                        severity = "info" if old_tag == new_tag else "warning"
                        description = (
                            f"Service {name}: image digest changed"
                            + (f" (tag unchanged: {new_tag})" if old_tag == new_tag else f" ({old_tag} → {new_tag})")
                        )
                        write_event(
                            entity_id=entity_id, entity_type="swarm_service",
                            event_type="image_digest_change",
                            severity=severity,
                            description=description,
                            source_collector="swarm",
                            metadata={"old_digest": old_digest, "new_digest": digest,
                                      "tag": new_tag, "silent": old_tag == new_tag},
                        )

                    # First-time digest record
                    if not old_digest and digest:
                        write_change(
                            entity_id=entity_id, entity_type="swarm_service",
                            field_name="image_digest",
                            old_value=None, new_value=digest,
                            source_collector="swarm",
                        )

                    if old_tag and old_tag != new_tag:
                        write_change(
                            entity_id=entity_id, entity_type="swarm_service",
                            field_name="image_tag",
                            old_value=old_tag, new_value=new_tag,
                            source_collector="swarm",
                        )
            except Exception as _de:
                log.debug("image digest tracking failed (non-fatal): %s", _de)

            # ── Replica count event tracking ─────────────────────────────────
            try:
                from api.db.entity_history import write_event, get_last_known_values
                for svc in svc_data:
                    name = svc.get("name", "")
                    if not name:
                        continue
                    entity_id = f"swarm:service:{name}"
                    running = svc.get("running_replicas", 0)
                    desired = svc.get("desired_replicas", 0)
                    last = get_last_known_values(entity_id, ["running_replicas"])
                    old_running_str = last.get("running_replicas")
                    old_running = int(old_running_str) if old_running_str is not None else None

                    if old_running is not None and old_running != running:
                        if running == 0 and desired > 0:
                            severity = "critical"
                            event_type = "service_all_replicas_down"
                            desc = f"{name}: all replicas down (was {old_running}/{desired})"
                        elif running < old_running:
                            severity = "warning"
                            event_type = "service_replica_lost"
                            desc = f"{name}: replicas dropped {old_running} → {running} (desired {desired})"
                        elif running > old_running:
                            severity = "info"
                            event_type = "service_replica_recovered"
                            desc = f"{name}: replicas restored {old_running} → {running} (desired {desired})"
                        else:
                            continue
                        write_event(
                            entity_id=entity_id, entity_type="swarm_service",
                            event_type=event_type, severity=severity,
                            description=desc, source_collector="swarm",
                            metadata={"old_running": old_running, "new_running": running,
                                      "desired": desired},
                        )

                    # Record current running count for next poll comparison
                    if old_running_str is None or old_running != running:
                        from api.db.entity_history import write_change
                        write_change(
                            entity_id=entity_id, entity_type="swarm_service",
                            field_name="running_replicas",
                            old_value=old_running_str,
                            new_value=str(running),
                            source_collector="swarm",
                            metadata={"desired": desired},
                        )
            except Exception as _re:
                log.debug("replica tracking failed (non-fatal): %s", _re)

            # ── Metric samples ────────────────────────────────────────────────
            try:
                from api.db.metric_samples import write_samples
                swarm_metrics: dict = {
                    "nodes.total": float(len(node_data)),
                    "nodes.active_managers": float(active_managers),
                    "services.total": float(len(svc_data)),
                    "services.degraded": float(len(degraded_services)),
                    "services.failed": float(len(failed_services)),
                }
                write_samples("swarm_cluster", swarm_metrics)
            except Exception as _me:
                log.debug("swarm metric_samples write failed: %s", _me)

            # ── Health determination ────────────────────────────────────────────
            quorum = (manager_count // 2) + 1 if manager_count else 1
            if active_managers < quorum:
                health = "critical"
                message = (
                    f"Manager quorum at risk: {active_managers}/{manager_count} active "
                    f"(need {quorum})"
                )
            elif failed_services:
                health = "critical"
                message = f"Services with 0 replicas: {', '.join(failed_services)}"
            elif degraded_nodes or degraded_services:
                health = "degraded"
                parts = []
                if degraded_nodes:
                    parts.append(f"nodes not active: {', '.join(degraded_nodes)}")
                if degraded_services:
                    parts.append(f"under-replicated: {', '.join(degraded_services)}")
                message = "; ".join(parts)
            else:
                health = "healthy"
                message = (
                    f"{len(node_data)} nodes ({manager_count} mgr), "
                    f"{len(svc_data)} services — all healthy"
                )

            snapshot = {
                "health": health,
                "message": message,
                "nodes": node_data,
                "services": svc_data,
                "overlay_networks": overlay_networks_list,   # v2.43.4
                "node_count": len(node_data),
                "service_count": len(svc_data),
                "manager_count": manager_count,
                "active_managers": active_managers,
                "degraded_nodes": degraded_nodes,
                "degraded_services": degraded_services,
                "failed_services": failed_services,
            }
            # v2.35.0: best-effort fact extraction
            try:
                from api.facts.extractors import extract_facts_from_swarm_snapshot
                from api.db.known_facts import batch_upsert_facts
                from api.metrics import FACTS_UPSERTED_COUNTER
                facts = extract_facts_from_swarm_snapshot(snapshot)
                result = batch_upsert_facts(facts, actor="collector")
                for action, count in result.items():
                    if count > 0:
                        FACTS_UPSERTED_COUNTER.labels(
                            source="swarm_collector", action=action
                        ).inc(count)
            except Exception as _fe:
                log.warning("Fact extraction failed for swarm: %s", _fe)
            return snapshot

        except DockerException as e:
            try:
                client.close()
            except Exception:
                pass
            return {
                "health": "error",
                "error": str(e),
                "message": f"Docker error: {e}",
                "nodes": [], "services": [],
                "node_count": 0, "service_count": 0,
            }
        except Exception as e:
            try:
                client.close()
            except Exception:
                pass
            log.warning("SwarmCollector._collect_sync error: %s", e)
            return {
                "health": "error",
                "error": str(e),
                "message": f"Swarm collection error: {e}",
                "nodes": [], "services": [],
                "node_count": 0, "service_count": 0,
            }
