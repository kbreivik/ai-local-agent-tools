"""Fact extractors — collector snapshot → list of fact dicts.

Each function returns a list of dicts suitable for
api.db.known_facts.batch_upsert_facts():

    {"fact_key": str, "source": str, "value": any, "metadata": dict}

Extractors MUST NOT raise on missing/unexpected fields. The collector caller
wraps them in a try/except that never fails the poll.
"""
from __future__ import annotations


def _add(facts: list, key: str, source: str, value, metadata: dict | None = None) -> None:
    if value is None:
        return
    entry: dict = {"fact_key": key, "source": source, "value": value}
    if metadata:
        entry["metadata"] = metadata
    facts.append(entry)


def extract_facts_from_proxmox_vm_snapshot(snapshot: dict, connection_label: str = "") -> list[dict]:
    """From proxmox_vms collector snapshot → fact list."""
    facts: list[dict] = []
    if not isinstance(snapshot, dict):
        return facts
    for vm in snapshot.get("vms", []) or []:
        name = vm.get("name")
        if not name:
            continue
        fkey_base = f"prod.proxmox.vm.{name}"
        md = {"vmid": vm.get("vmid"), "connection": connection_label}
        _add(facts, f"{fkey_base}.status", "proxmox_collector", vm.get("status"), md)
        _add(facts, f"{fkey_base}.node", "proxmox_collector", vm.get("node"), md)
        if vm.get("ip"):
            _add(facts, f"{fkey_base}.ip", "proxmox_collector", vm["ip"], md)
        if vm.get("vcpus") is not None:
            _add(facts, f"{fkey_base}.cpu_count", "proxmox_collector", vm["vcpus"], md)
        if vm.get("maxmem_gb") is not None:
            _add(facts, f"{fkey_base}.memory_gb", "proxmox_collector", vm["maxmem_gb"], md)
    for ct in snapshot.get("lxc", []) or []:
        name = ct.get("name")
        if not name:
            continue
        fkey_base = f"prod.proxmox.lxc.{name}"
        md = {"vmid": ct.get("vmid"), "connection": connection_label}
        _add(facts, f"{fkey_base}.status", "proxmox_collector", ct.get("status"), md)
        _add(facts, f"{fkey_base}.node", "proxmox_collector", ct.get("node"), md)
    return facts


def extract_facts_from_swarm_snapshot(snapshot: dict) -> list[dict]:
    """Docker Swarm manager snapshot → fact list.

    v2.39.2: adds service convergence flag, health, engine version, cluster counts.
    v2.43.0: adds service network names (prod.swarm.service.{name}.networks).
    """
    facts: list[dict] = []
    if not isinstance(snapshot, dict):
        return facts

    services_total = 0
    services_converged = 0

    for svc in snapshot.get("services", []) or []:
        name = svc.get("name")
        if not name:
            continue
        fkey_base = f"prod.swarm.service.{name}"
        md = {"service_id": svc.get("id")}
        desired = svc.get("replicas_desired")
        if desired is None:
            desired = svc.get("desired_replicas")
        running = svc.get("replicas_running")
        if running is None:
            running = svc.get("running_replicas")
        _add(facts, f"{fkey_base}.replicas.desired", "swarm_collector", desired, md)
        _add(facts, f"{fkey_base}.replicas.running", "swarm_collector", running, md)
        # v2.39.2: convergence
        if desired is not None and running is not None:
            converged = int(running) >= int(desired) > 0
            _add(facts, f"{fkey_base}.converged", "swarm_collector", converged, md)
            services_total += 1
            if converged:
                services_converged += 1
        placement = svc.get("placement")
        if placement is not None:
            _add(facts, f"{fkey_base}.placement", "swarm_collector", placement, md)
        if svc.get("image"):
            _add(facts, f"{fkey_base}.image", "swarm_collector", svc["image"], md)
        if svc.get("image_digest"):
            _add(facts, f"{fkey_base}.image_digest", "swarm_collector",
                 svc["image_digest"], md)
        # v2.39.2: health field if collector provides it
        if svc.get("health"):
            _add(facts, f"{fkey_base}.health", "swarm_collector", svc["health"], md)
        # v2.43.0: overlay network names — collector already captures these,
        # just wasn't written to facts. Enables preflight/external-AI to answer
        # "which overlay network is this service on?" without a tool call.
        if svc.get("networks"):
            _add(facts, f"{fkey_base}.networks", "swarm_collector",
                 svc["networks"], md)

    # Cluster summary
    if services_total:
        _add(facts, "prod.swarm.cluster.services_total", "swarm_collector",
             services_total)
        _add(facts, "prod.swarm.cluster.services_converged", "swarm_collector",
             services_converged)

    nodes_ready = 0
    nodes_total = 0
    for node in snapshot.get("nodes", []) or []:
        hostname = node.get("hostname")
        if not hostname:
            continue
        fkey_base = f"prod.swarm.node.{hostname}"
        _add(facts, f"{fkey_base}.state", "swarm_collector", node.get("state"))
        _add(facts, f"{fkey_base}.availability", "swarm_collector",
             node.get("availability"))
        _add(facts, f"{fkey_base}.role", "swarm_collector", node.get("role"))
        # v2.39.2: engine version + node ip
        if node.get("engine_version"):
            _add(facts, f"{fkey_base}.engine_version", "swarm_collector",
                 node["engine_version"])
        if node.get("addr") or node.get("ip"):
            _add(facts, f"{fkey_base}.addr", "swarm_collector",
                 node.get("addr") or node.get("ip"))
        nodes_total += 1
        if str(node.get("state", "")).lower() == "ready":
            nodes_ready += 1

    if nodes_total:
        _add(facts, "prod.swarm.cluster.nodes_total", "swarm_collector", nodes_total)
        _add(facts, "prod.swarm.cluster.nodes_ready", "swarm_collector", nodes_ready)

    return facts


def extract_facts_from_docker_agent_snapshot(snapshot: dict) -> list[dict]:
    """Local agent-01 docker collector → fact list.

    Uses the short container id (first 12 chars) as the entity key because that's
    the stable identifier we already use across the rest of the platform.
    """
    facts: list[dict] = []
    if not isinstance(snapshot, dict):
        return facts
    for c in snapshot.get("containers", []) or []:
        cid = c.get("id", "")
        if not cid:
            continue
        short = cid[:12]
        fkey_base = f"prod.container.{short}"
        md = {"name": c.get("name")}
        _add(facts, f"{fkey_base}.service_name", "docker_agent_collector",
             c.get("name") or c.get("service_name"), md)
        if c.get("image"):
            _add(facts, f"{fkey_base}.image", "docker_agent_collector",
                 c["image"], md)
        if c.get("state"):
            _add(facts, f"{fkey_base}.state", "docker_agent_collector",
                 c["state"], md)
        # Both spec and snapshot shapes: networks can be a list or a dict
        if c.get("networks"):
            _add(facts, f"{fkey_base}.networks", "docker_agent_collector",
                 c["networks"], md)
        if c.get("ip_addresses"):
            _add(facts, f"{fkey_base}.ip", "docker_agent_collector",
                 c["ip_addresses"], md)
    return facts


def extract_facts_from_kafka_snapshot(snapshot: dict) -> list[dict]:
    """Kafka collector → fact list.

    v2.39.2: enriched with broker online status, ISR-missing flag,
    cluster-level under-replicated count, and per-topic under-replicated
    partition count.
    """
    facts: list[dict] = []
    if not isinstance(snapshot, dict):
        return facts

    brokers_online = 0
    for b in snapshot.get("brokers", []) or []:
        bid = b.get("id")
        if bid is None or bid == -1:
            continue
        fkey_base = f"prod.kafka.broker.{bid}"
        _add(facts, f"{fkey_base}.host", "kafka_collector", b.get("host"))
        _add(facts, f"{fkey_base}.port", "kafka_collector", b.get("port"))
        _add(facts, f"{fkey_base}.is_controller", "kafka_collector",
             bool(b.get("is_controller", False)))
        # v2.39.2 additions
        online = b.get("online", b.get("connected", b.get("reachable")))
        if online is not None:
            _add(facts, f"{fkey_base}.online", "kafka_collector", bool(online))
            if online:
                brokers_online += 1
        rack = b.get("rack")
        if rack:
            _add(facts, f"{fkey_base}.rack", "kafka_collector", rack)

    # Cluster-level summary
    broker_count = len([b for b in (snapshot.get("brokers") or [])
                        if b.get("id") not in (None, -1)])
    if broker_count:
        _add(facts, "prod.kafka.cluster.broker_count", "kafka_collector",
             broker_count)
    if brokers_online:
        _add(facts, "prod.kafka.cluster.brokers_online", "kafka_collector",
             brokers_online)

    # Under-replicated summary from snapshot top-level if present
    ur = snapshot.get("under_replicated_partitions")
    if ur is not None:
        _add(facts, "prod.kafka.cluster.under_replicated_partitions",
             "kafka_collector", int(ur))

    for t in snapshot.get("topics", []) or []:
        name = t.get("name")
        if not name:
            continue
        _add(facts, f"prod.kafka.topic.{name}.partitions", "kafka_collector",
             t.get("partition_count"))
        _add(facts, f"prod.kafka.topic.{name}.replication_factor",
             "kafka_collector", t.get("replication_factor"))
        # v2.39.2: per-topic under-replicated count
        t_ur = t.get("under_replicated_partitions", t.get("under_replicated"))
        if t_ur is not None:
            _add(facts, f"prod.kafka.topic.{name}.under_replicated_partitions",
                 "kafka_collector", int(t_ur))

    return facts


def extract_facts_from_pbs_snapshot(snapshot: dict) -> list[dict]:
    """PBS collector → fact list.

    PBS collector produces `last_backups: [{backup_type, backup_id,
    last_backup_ts, datastore}]`. Flatten each entry into facts.
    """
    facts: list[dict] = []
    if not isinstance(snapshot, dict):
        return facts
    for backup in snapshot.get("last_backups", []) or []:
        btype = backup.get("backup_type", "vm")
        bid = backup.get("backup_id")
        if bid is None:
            continue
        fkey_base = f"prod.pbs.backup.{btype}-{bid}"
        md = {"datastore": backup.get("datastore")}
        if backup.get("last_backup_ts"):
            _add(facts, f"{fkey_base}.last_success_ts", "pbs_collector",
                 backup["last_backup_ts"], md)
        _add(facts, f"{fkey_base}.vm_id", "pbs_collector", bid, md)
    # Datastore facts as well
    for ds in snapshot.get("datastores", []) or []:
        name = ds.get("name")
        if not name:
            continue
        fkey_base = f"prod.pbs.datastore.{name}"
        _add(facts, f"{fkey_base}.usage_pct", "pbs_collector",
             ds.get("usage_pct"))
        _add(facts, f"{fkey_base}.total_gb", "pbs_collector",
             ds.get("total_gb"))
    return facts


def extract_facts_from_fortiswitch_snapshot(snapshot: dict) -> list[dict]:
    """FortiSwitch collector → fact list.

    The project ships a fortigate collector (not fortiswitch) today; the spec
    anticipates a fortiswitch collector landing later and this extractor is
    reserved for when it does. Safe no-op against an absent collector.
    """
    facts: list[dict] = []
    if not isinstance(snapshot, dict):
        return facts
    for sw in snapshot.get("switches", []) or []:
        serial = sw.get("serial")
        if not serial:
            continue
        fkey_base = f"prod.fortiswitch.{serial}"
        _add(facts, f"{fkey_base}.model", "fortiswitch_collector",
             sw.get("model"))
        _add(facts, f"{fkey_base}.firmware", "fortiswitch_collector",
             sw.get("firmware"))
        if sw.get("mac_addresses"):
            _add(facts, f"{fkey_base}.mac_addresses", "fortiswitch_collector",
                 sw["mac_addresses"])
    return facts


def extract_facts_from_external_services_snapshot(snapshot: dict) -> list[dict]:
    """external_services collector snapshot → fact list.

    Snapshot shape: {health, services: [{name, slug, service_type, host_port,
    reachable, latency_ms, dot, problem, connection_id, entity_id}]}

    Writes one fact per probed service: reachability, latency, status, host.
    Key format: prod.svc.{slug}.{attr}
    """
    facts: list[dict] = []
    if not isinstance(snapshot, dict):
        return facts
    for svc in snapshot.get("services", []) or []:
        slug = svc.get("slug") or svc.get("service_type")
        if not slug:
            continue
        fkey_base = f"prod.svc.{slug}"
        md = {"connection_id": svc.get("connection_id"), "name": svc.get("name")}
        _add(facts, f"{fkey_base}.reachable", "external_services_collector",
             bool(svc.get("reachable", False)), md)
        _add(facts, f"{fkey_base}.status", "external_services_collector",
             svc.get("dot", "grey"), md)
        if svc.get("latency_ms") is not None:
            _add(facts, f"{fkey_base}.latency_ms", "external_services_collector",
                 svc["latency_ms"], md)
        if svc.get("problem"):
            _add(facts, f"{fkey_base}.problem", "external_services_collector",
                 svc["problem"], md)
        if svc.get("host_port"):
            _add(facts, f"{fkey_base}.host_port", "external_services_collector",
                 svc["host_port"], md)
    return facts


def extract_facts_from_vm_hosts_snapshot(snapshot: dict) -> list[dict]:
    """vm_hosts collector snapshot → fact list.

    Snapshot shape: {health, vms: [{id, label, host, hostname, os, kernel,
    uptime_secs, load_1, load_5, load_15, mem_pct, disks, services,
    docker_version, dot, problem}]}

    Writes per-host: reachability (dot!=red), IP, hostname, OS, load,
    memory pct, disk max pct, docker version.
    Key format: prod.vm_host.{label}.{attr}
    """
    facts: list[dict] = []
    if not isinstance(snapshot, dict):
        return facts
    for vm in snapshot.get("vms", []) or []:
        label = vm.get("label") or vm.get("id")
        if not label:
            continue
        fkey_base = f"prod.vm_host.{label}"
        md = {"host": vm.get("host")}
        # Reachability derived from dot
        reachable = vm.get("dot", "grey") in ("green", "amber")
        _add(facts, f"{fkey_base}.ssh_reachable", "vm_hosts_collector",
             reachable, md)
        _add(facts, f"{fkey_base}.status", "vm_hosts_collector",
             vm.get("dot", "grey"), md)
        if vm.get("problem"):
            _add(facts, f"{fkey_base}.problem", "vm_hosts_collector",
                 vm["problem"], md)
        if vm.get("host"):
            _add(facts, f"{fkey_base}.ip", "vm_hosts_collector",
                 vm["host"], md)
        if vm.get("hostname"):
            _add(facts, f"{fkey_base}.hostname", "vm_hosts_collector",
                 vm["hostname"], md)
        if vm.get("os"):
            _add(facts, f"{fkey_base}.os", "vm_hosts_collector",
                 vm["os"], md)
        if vm.get("load_1") is not None:
            _add(facts, f"{fkey_base}.load_1", "vm_hosts_collector",
                 vm["load_1"], md)
        if vm.get("mem_pct") is not None:
            _add(facts, f"{fkey_base}.mem_pct", "vm_hosts_collector",
                 vm["mem_pct"], md)
        # Max disk usage across all disks
        disks = vm.get("disks") or []
        if disks:
            max_disk = max((d.get("usage_pct", 0) for d in disks
                           if isinstance(d, dict)), default=None)
            if max_disk is not None:
                _add(facts, f"{fkey_base}.max_disk_pct", "vm_hosts_collector",
                     max_disk, md)
        if vm.get("docker_version"):
            _add(facts, f"{fkey_base}.docker_version", "vm_hosts_collector",
                 vm["docker_version"], md)
        # Per-service systemd status (services is list of {name, status})
        for svc in vm.get("services") or []:
            sname = svc.get("name") if isinstance(svc, dict) else None
            sstatus = svc.get("status") if isinstance(svc, dict) else None
            if sname and sstatus:
                _add(facts, f"{fkey_base}.service.{sname}", "vm_hosts_collector",
                     sstatus, md)
    return facts


def extract_facts_from_unifi_snapshot(snapshot: dict,
                                       connection_label: str = "") -> list[dict]:
    """UniFi collector snapshot → fact list.

    Snapshot shape varies by collector version — look for common fields:
    devices: [{mac, name, model, state, ip, ap_count}]
    clients: count or list
    health: str
    Key format: prod.unifi.{label}.{attr}
    """
    facts: list[dict] = []
    if not isinstance(snapshot, dict):
        return facts
    label = connection_label or "default"
    fkey_base = f"prod.unifi.{label}"
    md = {"connection": label}

    # Overall health
    _add(facts, f"{fkey_base}.health", "unifi_collector",
         snapshot.get("health", snapshot.get("status")), md)

    # Client count (may be int or len of list)
    clients = snapshot.get("clients") or snapshot.get("client_count")
    if isinstance(clients, list):
        _add(facts, f"{fkey_base}.client_count", "unifi_collector", len(clients), md)
    elif isinstance(clients, int):
        _add(facts, f"{fkey_base}.client_count", "unifi_collector", clients, md)

    # Device states
    devices = snapshot.get("devices") or []
    total = len(devices)
    connected = sum(1 for d in devices
                    if isinstance(d, dict) and d.get("state") in (1, "connected", "online"))
    if total:
        _add(facts, f"{fkey_base}.device_count", "unifi_collector", total, md)
        _add(facts, f"{fkey_base}.devices_connected", "unifi_collector", connected, md)

    # Per-device facts (APs and switches by MAC)
    for dev in devices:
        if not isinstance(dev, dict):
            continue
        mac = (dev.get("mac") or "").replace(":", "").lower()
        dname = dev.get("name") or mac
        if not mac and not dname:
            continue
        key = mac or dname.replace(" ", "_").lower()
        dfkey = f"prod.unifi.device.{key}"
        dmd = {"name": dname, "model": dev.get("model"), "connection": label}
        state_raw = dev.get("state")
        state_str = "connected" if state_raw in (1, "connected", "online") else "disconnected"
        _add(facts, f"{dfkey}.state", "unifi_collector", state_str, dmd)
        if dev.get("ip"):
            _add(facts, f"{dfkey}.ip", "unifi_collector", dev["ip"], dmd)
        if dev.get("model"):
            _add(facts, f"{dfkey}.model", "unifi_collector", dev["model"], dmd)

    return facts


def extract_facts_from_fortigate_snapshot(snapshot: dict,
                                           connection_label: str = "") -> list[dict]:
    """FortiGate collector snapshot → fact list.

    Snapshot shape: {health, hostname, version, interfaces: [{name, status,
    ip, speed, rx_errors, tx_errors}], policies_count, vpn_tunnels, ...}
    Key format: prod.fortigate.{label}.{attr}
    """
    facts: list[dict] = []
    if not isinstance(snapshot, dict):
        return facts
    label = connection_label or snapshot.get("hostname") or "default"
    fkey_base = f"prod.fortigate.{label}"
    md = {"connection": label}

    _add(facts, f"{fkey_base}.health", "fortigate_collector",
         snapshot.get("health", snapshot.get("status")), md)
    if snapshot.get("hostname"):
        _add(facts, f"{fkey_base}.hostname", "fortigate_collector",
             snapshot["hostname"], md)
    if snapshot.get("version"):
        _add(facts, f"{fkey_base}.version", "fortigate_collector",
             snapshot["version"], md)
    if snapshot.get("serial"):
        _add(facts, f"{fkey_base}.serial", "fortigate_collector",
             snapshot["serial"], md)

    # Interface status — most useful for agent network tasks
    for iface in snapshot.get("interfaces") or []:
        if not isinstance(iface, dict):
            continue
        iname = iface.get("name")
        if not iname:
            continue
        ifkey = f"prod.fortigate.{label}.iface.{iname}"
        imd = {"connection": label}
        _add(facts, f"{ifkey}.status", "fortigate_collector",
             iface.get("status") or iface.get("link"), imd)
        if iface.get("ip"):
            _add(facts, f"{ifkey}.ip", "fortigate_collector", iface["ip"], imd)
        rx_err = iface.get("rx_errors") or iface.get("rx_error")
        if rx_err is not None:
            _add(facts, f"{ifkey}.rx_errors", "fortigate_collector", rx_err, imd)

    # VPN tunnel count
    vpn = snapshot.get("vpn_tunnels")
    if isinstance(vpn, list):
        _add(facts, f"{fkey_base}.vpn_tunnel_count", "fortigate_collector",
             len(vpn), md)
    elif isinstance(vpn, int):
        _add(facts, f"{fkey_base}.vpn_tunnel_count", "fortigate_collector",
             vpn, md)

    return facts
