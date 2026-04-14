"""
ProxmoxVMsCollector — polls all VMs and LXC containers across all Proxmox nodes every 30s.

Uses proxmoxer library for native PVE API access with token auth.
Credentials: connections DB (platform=proxmox) or env vars (PROXMOX_HOST, etc.)
Writes component="proxmox_vms" to status_snapshots.
State shape: { health, vms: [VMCard], lxc: [LXCCard] }
"""
import asyncio
import logging
import os

from api.collectors.base import BaseCollector

log = logging.getLogger(__name__)


def _load_vm_ip_map() -> dict:
    """Load VMID→IP mapping from PROXMOX_VM_IP_MAP env var (JSON object with string keys)."""
    import json
    raw = os.environ.get("PROXMOX_VM_IP_MAP", "")
    if raw:
        try:
            parsed = json.loads(raw)
            return {int(k): v for k, v in parsed.items()}
        except (ValueError, TypeError, AttributeError):
            pass
    return {}


VM_IP_MAP = _load_vm_ip_map()


class ProxmoxVMsCollector(BaseCollector):
    component = "proxmox_vms"
    platforms = ["proxmox", "pbs"]

    def __init__(self):
        super().__init__()
        self.interval = int(os.environ.get("PROXMOX_POLL_INTERVAL", "30"))

    def mock(self) -> dict:
        return {
            "health": "healthy", "connection_label": "mock-proxmox", "connection_id": "mock-id",
            "vms": [
                {"vmid": 100, "name": "mock-vm-100", "node": "pve1", "status": "running", "dot": "green", "type": "qemu", "mem": 2048, "maxmem": 4096, "cpus": 2},
                {"vmid": 101, "name": "mock-vm-101", "node": "pve1", "status": "stopped", "dot": "amber", "type": "qemu", "mem": 0, "maxmem": 2048, "cpus": 1},
            ],
            "lxc": [{"vmid": 200, "name": "mock-lxc-200", "node": "pve1", "status": "running", "dot": "green", "type": "lxc"}],
        }

    def to_entities(self, state: dict) -> list:
        from api.collectors.base import Entity
        dot_to_status = {"green": "healthy", "amber": "degraded", "red": "error", "grey": "unknown"}
        label = state.get("connection_label", "proxmox")
        entities = []
        for vm in state.get("vms", []):
            entities.append(Entity(
                id=f"proxmox_vms:{vm.get('node','?')}:vm:{vm.get('vmid','?')}",
                label=vm.get("name", str(vm.get("vmid", "?"))),
                component=self.component, platform="proxmox", section="COMPUTE",
                status=dot_to_status.get(vm.get("dot", "grey"), "unknown"),
                metadata={"node": vm.get("node"), "type": "qemu", "vmid": vm.get("vmid"),
                          "connection": label, "mem": vm.get("mem"), "maxmem": vm.get("maxmem"), "cpus": vm.get("cpus")},
            ))
        for ct in state.get("lxc", []):
            entities.append(Entity(
                id=f"proxmox_vms:{ct.get('node','?')}:lxc:{ct.get('vmid','?')}",
                label=ct.get("name", str(ct.get("vmid", "?"))),
                component=self.component, platform="proxmox", section="COMPUTE",
                status=dot_to_status.get(ct.get("dot", "grey"), "unknown"),
                metadata={"node": ct.get("node"), "type": "lxc", "vmid": ct.get("vmid"), "connection": label},
            ))
        return entities if entities else super().to_entities(state)

    async def poll(self) -> dict:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict:
        from api.connections import get_all_connections_for_platform
        connections = get_all_connections_for_platform("proxmox")

        # Env var fallback when no DB connections configured
        if not connections:
            host = os.environ.get("PROXMOX_HOST", "")
            if not host:
                return {"health": "unconfigured", "vms": [], "lxc": [], "clusters": [],
                        "message": "No Proxmox connection configured"}
            connections = [{
                "id": "", "label": host, "host": host,
                "port": int(os.environ.get("PROXMOX_PORT", "8006")),
                "credentials": {
                    "user": os.environ.get("PROXMOX_USER", ""),
                    "token_name": os.environ.get("PROXMOX_TOKEN_NAME", ""),
                    "secret": os.environ.get("PROXMOX_TOKEN_SECRET", ""),
                },
            }]

        clusters = []
        all_vms = []
        all_lxc = []

        for conn in connections:
            result = _poll_single_connection(conn)
            clusters.append(result)
            all_vms.extend(result.get("vms", []))
            all_lxc.extend(result.get("lxc", []))

        # Overall health: worst of all clusters
        healths = [c.get("health", "unknown") for c in clusters]
        if any(h in ("error", "critical") for h in healths):
            overall = "critical"
        elif any(h == "degraded" for h in healths):
            overall = "degraded"
        elif all(h == "healthy" for h in healths):
            overall = "healthy"
        else:
            overall = "unknown"

        # Backward compat: expose first cluster's label/id at top level
        first = clusters[0] if clusters else {}
        return {
            "health": overall,
            "clusters": clusters,
            # Flat merged lists — used by to_entities() and legacy code
            "vms": all_vms,
            "lxc": all_lxc,
            "connection_label": first.get("connection_label", ""),
            "connection_id": first.get("connection_id", ""),
        }


def _poll_single_connection(conn: dict) -> dict:
    """Poll one Proxmox connection and return a cluster result dict."""
    host = conn.get("host", "")
    creds = conn.get("credentials", {}) if isinstance(conn.get("credentials"), dict) else {}
    pve_user = creds.get("user", "")
    pve_token_name = creds.get("token_name", "")
    token_secret = creds.get("secret", "")
    conn_port = conn.get("port") or 8006
    port = conn_port if conn_port not in (0, None, 443) else 8006
    conn_label = conn.get("label", host)
    conn_id = str(conn.get("id", ""))
    conn_host = f"{host}:{port}"

    if not host:
        return {"health": "unconfigured", "vms": [], "lxc": [],
                "connection_label": conn_label, "connection_id": conn_id,
                "connection_host": conn_host}

    try:
        from proxmoxer import ProxmoxAPI
        prox = ProxmoxAPI(
            host, port=port,
            user=pve_user,
            token_name=pve_token_name,
            token_value=token_secret,
            verify_ssl=False,
            timeout=10,
        )

        # Load maintenance flags once per poll — used by _classify_with_maint()
        try:
            from api.db.entity_maintenance import get_maintenance_set
            _maint = get_maintenance_set()
        except Exception:
            _maint = set()

        nodes = [n["node"] for n in prox.nodes.get() if n.get("node")]
        if not nodes:
            nodes = [n.strip() for n in os.environ.get("PROXMOX_NODES", "").split(",") if n.strip()]
        if not nodes:
            return {"health": "error", "vms": [], "lxc": [],
                    "error": "No nodes returned from cluster",
                    "connection_label": conn_label, "connection_id": conn_id,
                    "connection_host": conn_host}

        vms = []
        lxc_list = []
        nodes_ok = 0

        for node in nodes:
            try:
                for vm in prox.nodes(node).qemu.get():
                    vms.append(_build_vm_card_proxmoxer(prox, node, vm, conn_id, _maint))
                for ct in prox.nodes(node).lxc.get():
                    lxc_list.append(_build_lxc_card(node, ct, conn_id, _maint))
                nodes_ok += 1
            except Exception as e:
                log.warning("Proxmox node %s error: %s", node, e)

        # Write each discovered VM/LXC to infra_inventory for cross-reference
        try:
            from api.db.infra_inventory import write_cross_reference
            for vm in vms:
                vmid = vm.get("vmid")
                vm_name = vm.get("name", "")
                vm_node = vm.get("node", "")
                vm_ip = vm.get("ip", "")
                aliases = [f"vmid-{vmid}", vm_name] if vmid else [vm_name]
                # Common name patterns: hp1-worker-01 → worker-01, worker-1
                if vm_name:
                    # Strip common prefixes to create short aliases
                    for prefix in ("hp1-", "ds-", "prod-", "dev-"):
                        if vm_name.startswith(prefix):
                            short = vm_name[len(prefix):]
                            if short not in aliases:
                                aliases.append(short)
                write_cross_reference(
                    connection_id=f"proxmox:{conn_id}:vm:{vmid}",
                    platform="proxmox_vm",
                    label=vm_name,
                    hostname="",
                    ips=[vm_ip] if vm_ip else [],
                    aliases=aliases,
                    meta={
                        "vmid": vmid,
                        "node": vm_node,
                        "proxmox_connection_id": conn_id,
                        "proxmox_label": conn_label,
                        "type": "qemu",
                    },
                )
            for ct in lxc_list:
                vmid = ct.get("vmid")
                ct_name = ct.get("name", "")
                ct_node = ct.get("node", "")
                aliases = [f"vmid-{vmid}", ct_name] if vmid else [ct_name]
                write_cross_reference(
                    connection_id=f"proxmox:{conn_id}:lxc:{vmid}",
                    platform="proxmox_lxc",
                    label=ct_name,
                    hostname="",
                    ips=[],
                    aliases=aliases,
                    meta={
                        "vmid": vmid,
                        "node": ct_node,
                        "proxmox_connection_id": conn_id,
                        "proxmox_label": conn_label,
                        "type": "lxc",
                    },
                )
        except Exception as _inv_err:
            log.debug("infra_inventory write failed (non-fatal): %s", _inv_err)

        if nodes_ok == 0:
            return {"health": "error", "vms": [], "lxc": [],
                    "error": f"{conn_label} ({host}): No nodes responded",
                    "connection_label": conn_label, "connection_id": conn_id,
                    "connection_host": conn_host}

        all_items = vms + lxc_list
        # Exclude maintained entities from health calculation
        active = [v for v in all_items if not v.get("maintenance")]
        if not active or all(v["dot"] == "green" for v in active):
            health = "healthy"
        elif all(v["dot"] in ("red", "amber") for v in active):
            health = "critical" if all(v["dot"] == "red" for v in active) else "degraded"
        else:
            health = "degraded"

        return {
            "health": health,
            "vms": vms,
            "lxc": lxc_list,
            "connection_label": conn_label,
            "connection_id": conn_id,
            "connection_host": conn_host,
        }

    except Exception as e:
        log.error("ProxmoxVMsCollector error for %s: %s", conn_label, e)
        return {"health": "error", "vms": [], "lxc": [],
                "error": f"{conn_label} ({host}): {e}",
                "connection_label": conn_label, "connection_id": conn_id,
                "connection_host": conn_host}


def _build_vm_card_proxmoxer(prox, node: str, vm: dict, conn_id: str = "", maint: set | None = None) -> dict:
    """Build a VM card dict from proxmoxer data. Matches _build_vm_card output shape."""
    vmid = vm["vmid"]
    status = vm.get("status", "unknown")
    cpu_pct = round(vm.get("cpu", 0) * 100, 1) if status == "running" else None
    mem_used = vm.get("mem")
    maxmem = vm.get("maxmem")
    mem_used_gb = round(mem_used / 1e9, 1) if mem_used else None
    maxmem_gb = round(maxmem / 1e9, 1) if maxmem else None

    # Disk usage via guest agent (if running)
    disks = []
    if status == "running":
        try:
            fs_data = prox.nodes(node).qemu(vmid).agent("get-fsinfo").get()
            result_data = fs_data.get("result", []) if isinstance(fs_data, dict) else []
            for fs in result_data:
                total = fs.get("total-bytes", 0)
                used = fs.get("used-bytes", 0)
                mp = fs.get("mountpoint", "")
                if total and mp:
                    disks.append({"mountpoint": mp, "used_bytes": used, "total_bytes": total})
        except Exception:
            pass

    # Fallback: use list-level disk info when guest agent unavailable
    if not disks and vm.get("maxdisk"):
        disks = [{"mountpoint": "/", "used_bytes": vm.get("disk") or 0, "total_bytes": vm["maxdisk"]}]

    dot, problem = _classify(status, disks)
    entity_id = f"proxmox_vms:{node}:vm:{vmid}"
    in_maintenance = maint is not None and entity_id in maint
    if in_maintenance:
        dot, problem = "grey", None

    return {
        "type": "vm",
        "vmid": vmid,
        "name": vm.get("name", f"vm-{vmid}"),
        "node": node,
        "node_api": node,
        "pool": vm.get("pool", ""),
        "status": status,
        "ip": VM_IP_MAP.get(vmid, ""),
        "vcpus": vm.get("cpus", 0),
        "maxmem_gb": maxmem_gb,
        "cpu_pct": cpu_pct,
        "mem_used_gb": mem_used_gb,
        "disks": disks,
        "dot": dot,
        "problem": problem,
        "maintenance": in_maintenance,
        "entity_id": entity_id,
    }


def _build_lxc_card(node: str, ct: dict, conn_id: str = "", maint: set | None = None) -> dict:
    vmid = ct["vmid"]
    status = ct.get("status", "unknown")
    cpu_pct = round(ct.get("cpu", 0) * 100, 1) if status == "running" else None
    mem_used = ct.get("mem")
    maxmem = ct.get("maxmem")
    mem_used_gb = round(mem_used / 1e9, 1) if mem_used else None
    maxmem_gb = round(maxmem / 1e9, 1) if maxmem else None

    disk_used = ct.get("disk")
    disk_max = ct.get("maxdisk")
    disk_used_gb = round(disk_used / 1e9, 1) if disk_used else None
    disk_max_gb = round(disk_max / 1e9, 1) if disk_max else None
    disks = []
    if disk_max:
        disks = [{"mountpoint": "/", "used_bytes": disk_used or 0, "total_bytes": disk_max}]

    dot, problem = _classify(status, disks)
    entity_id = f"proxmox_vms:{node}:lxc:{vmid}"
    in_maintenance = maint is not None and entity_id in maint
    if in_maintenance:
        dot, problem = "grey", None

    return {
        "type": "lxc",
        "vmid": vmid,
        "name": ct.get("name", f"ct-{vmid}"),
        "node": node,
        "node_api": node,
        "pool": ct.get("pool", ""),
        "status": status,
        "ip": "",
        "vcpus": ct.get("cpus", 0),
        "maxmem_gb": maxmem_gb,
        "cpu_pct": cpu_pct,
        "mem_used_gb": mem_used_gb,
        "disk_used_gb": disk_used_gb,
        "disk_max_gb": disk_max_gb,
        "disks": disks,
        "dot": dot,
        "problem": problem,
        "maintenance": in_maintenance,
        "entity_id": entity_id,
    }


def _classify(status: str, disks: list) -> tuple[str, str | None]:
    if status == "running":
        for d in disks:
            if d["total_bytes"] and (d["used_bytes"] / d["total_bytes"]) > 0.70:
                pct = round(d["used_bytes"] / d["total_bytes"] * 100)
                return "amber", f"disk {pct}% full"
        return "green", None
    if status == "paused":
        return "amber", "paused"
    if status == "stopped":
        return "red", "stopped"
    return "grey", None
