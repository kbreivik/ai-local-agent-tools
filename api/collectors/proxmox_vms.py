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

    def __init__(self):
        super().__init__()
        self.interval = int(os.environ.get("PROXMOX_POLL_INTERVAL", "30"))

    async def poll(self) -> dict:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict:
        # Resolve credentials: connections DB first, env vars fallback
        host, token_id, token_secret, port = "", "", "", 8006
        conn = None
        try:
            from api.connections import get_connection_for_platform
            conn = get_connection_for_platform("proxmox")
        except Exception:
            pass

        if conn:
            host = conn.get("host", "")
            creds = conn.get("credentials", {}) if isinstance(conn.get("credentials"), dict) else {}
            pve_user = creds.get("user", "")
            pve_token_name = creds.get("token_name", "")
            token_secret = creds.get("secret", "")
            conn_port = conn.get("port") or 8006
            port = conn_port if conn_port not in (0, None, 443) else 8006
        else:
            host = os.environ.get("PROXMOX_HOST", "")
            pve_user = os.environ.get("PROXMOX_USER", "")
            pve_token_name = os.environ.get("PROXMOX_TOKEN_NAME", "")
            token_secret = os.environ.get("PROXMOX_TOKEN_SECRET", "")
            port = int(os.environ.get("PROXMOX_PORT", "8006"))

        if not host:
            return {"health": "unconfigured", "vms": [], "lxc": [], "message": "No Proxmox connection configured"}

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

            # Auto-discover nodes from cluster
            nodes = [n["node"] for n in prox.nodes.get() if n.get("node")]
            if not nodes:
                # Fallback to env var
                nodes = [n.strip() for n in os.environ.get("PROXMOX_NODES", "").split(",") if n.strip()]
            if not nodes:
                return {"health": "error", "vms": [], "lxc": [], "error": "No nodes returned from cluster"}

            vms = []
            lxc_list = []
            nodes_ok = 0

            for node in nodes:
                try:
                    # QEMU VMs
                    for vm in prox.nodes(node).qemu.get():
                        vms.append(_build_vm_card_proxmoxer(prox, node, vm))
                    # LXC containers
                    for ct in prox.nodes(node).lxc.get():
                        lxc_list.append(_build_lxc_card(node, ct))
                    nodes_ok += 1
                except Exception as e:
                    log.warning("Proxmox node %s error: %s", node, e)

            if nodes_ok == 0:
                return {"health": "error", "vms": [], "lxc": [], "error": "No Proxmox nodes responded"}

            all_items = vms + lxc_list
            if not all_items or all(v["dot"] == "green" for v in all_items):
                overall = "healthy"
            elif all(v["dot"] == "red" for v in all_items):
                overall = "critical"
            else:
                overall = "degraded"

            return {"health": overall, "vms": vms, "lxc": lxc_list}

        except Exception as e:
            log.error("ProxmoxVMsCollector error: %s", e)
            return {"health": "error", "vms": [], "lxc": [], "error": str(e)}


def _build_vm_card_proxmoxer(prox, node: str, vm: dict) -> dict:
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
    }


def _build_lxc_card(node: str, ct: dict) -> dict:
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
