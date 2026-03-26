"""
ProxmoxVMsCollector — polls all VMs and LXC containers across all Proxmox nodes every 30s.

Env vars: PROXMOX_HOST, PROXMOX_TOKEN_ID, PROXMOX_TOKEN_SECRET, PROXMOX_NODES
Writes component="proxmox_vms" to status_snapshots.
State shape: { health, vms: [VMCard], lxc: [LXCCard] }
Each item carries: type ("vm"|"lxc"), node, node_api, pool, status, dot, problem, ...
"""
import asyncio
import logging
import os

import httpx

from api.collectors.base import BaseCollector

log = logging.getLogger(__name__)

# Proxmox API node hostnames — override all three via PROXMOX_NODES env (comma-separated)
# These must match what `pvesh get /nodes` returns (the "node" field).
NODES = ["Pmox1", "Pmox2", "Pmox3"]

# Display label for each node API name — shown in the GUI header and VM cards.
NODE_DISPLAY = {
    "Pmox1": "Pmox1",
    "Pmox2": "Pmox2",
    "Pmox3": "Pmox3",
}

VM_IP_MAP = {
    9200: "192.168.199.10",
    9211: "192.168.199.21",
    9212: "192.168.199.22",
    9213: "192.168.199.23",
    9221: "192.168.199.31",
    9222: "192.168.199.32",
    9223: "192.168.199.33",
    9230: "192.168.199.40",
}


class ProxmoxVMsCollector(BaseCollector):
    component = "proxmox_vms"

    def __init__(self):
        super().__init__()
        self.interval = int(os.environ.get("PROXMOX_POLL_INTERVAL", "30"))

    async def poll(self) -> dict:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict:
        host = os.environ.get("PROXMOX_HOST", "")
        token_id = os.environ.get("PROXMOX_TOKEN_ID", "")
        token_secret = os.environ.get("PROXMOX_TOKEN_SECRET", "")

        if not host:
            return {"health": "unconfigured", "vms": [], "lxc": [], "message": "PROXMOX_HOST not set"}

        headers = {"Authorization": f"PVEAPIToken={token_id}={token_secret}"}
        base = f"https://{host}:8006/api2/json"
        nodes = [n.strip() for n in os.environ.get("PROXMOX_NODES", ",".join(NODES)).split(",") if n.strip()]

        vms = []
        lxc_list = []
        nodes_ok = 0
        try:
            for node in nodes:
                try:
                    # ── QEMU VMs ──────────────────────────────────────────────
                    r = httpx.get(f"{base}/nodes/{node}/qemu",
                                  headers=headers, verify=False, timeout=8)
                    if r.status_code == 200:
                        nodes_ok += 1
                        for vm in r.json().get("data", []):
                            vms.append(_build_vm_card(base, headers, node, vm))
                    else:
                        log.warning("Proxmox node %s /qemu returned HTTP %s", node, r.status_code)

                    # ── LXC containers ────────────────────────────────────────
                    r2 = httpx.get(f"{base}/nodes/{node}/lxc",
                                   headers=headers, verify=False, timeout=8)
                    if r2.status_code == 200:
                        for ct in r2.json().get("data", []):
                            lxc_list.append(_build_lxc_card(node, ct))
                    else:
                        log.warning("Proxmox node %s /lxc returned HTTP %s", node, r2.status_code)

                except Exception as e:
                    log.warning("Proxmox node %s error: %s", node, e)

            all_items = vms + lxc_list
            if nodes_ok == 0 and not all_items:
                return {"health": "error", "vms": [], "lxc": [], "error": "No Proxmox nodes responded"}

            if not all_items or all(v["dot"] == "green" for v in all_items):
                overall = "healthy"
            elif all(v["dot"] == "red" for v in all_items):
                overall = "critical"
            else:
                overall = "degraded"

            return {"health": overall, "vms": vms, "lxc": lxc_list}

        except Exception as e:
            return {"health": "error", "error": str(e), "vms": [], "lxc": []}


def _build_vm_card(base: str, headers: dict, node: str, vm: dict) -> dict:
    vmid = vm["vmid"]
    status = vm.get("status", "unknown")
    cpu_pct = round(vm.get("cpu", 0) * 100, 1) if status == "running" else None
    mem_used = vm.get("mem")
    maxmem = vm.get("maxmem")
    mem_used_gb = round(mem_used / 1e9, 1) if mem_used else None
    maxmem_gb = round(maxmem / 1e9, 1) if maxmem else None

    disks = _get_vm_disk_usage(base, headers, node, vmid) if status == "running" else []
    # Fallback: use list-level disk info when guest agent is unavailable or VM stopped
    if not disks and vm.get("maxdisk"):
        disks = [{"mountpoint": "/", "used_bytes": vm.get("disk") or 0, "total_bytes": vm["maxdisk"]}]
    dot, problem = _classify(status, disks)

    return {
        "type": "vm",
        "vmid": vmid,
        "name": vm.get("name", f"vm-{vmid}"),
        "node": NODE_DISPLAY.get(node, node),
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

    # LXC disk usage comes directly from the list response (no guest agent needed)
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
        "node": NODE_DISPLAY.get(node, node),
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


def _get_vm_disk_usage(base: str, headers: dict, node: str, vmid: int) -> list:
    try:
        r = httpx.get(f"{base}/nodes/{node}/qemu/{vmid}/agent/get-fsinfo",
                      headers=headers, verify=False, timeout=5)
        if r.status_code != 200:
            return []
        data = r.json().get("data", {})
        result_data = data.get("result", []) if isinstance(data, dict) else []
        disks = []
        for fs in result_data:
            total = fs.get("total-bytes", 0)
            used = fs.get("used-bytes", 0)
            mp = fs.get("mountpoint", "")
            if total and mp:
                disks.append({"mountpoint": mp, "used_bytes": used, "total_bytes": total})
        return disks
    except Exception:
        return []


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
