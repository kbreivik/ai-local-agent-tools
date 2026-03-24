"""
ProxmoxVMsCollector — polls all VMs across all Proxmox nodes every 30s.

Env vars: PROXMOX_HOST, PROXMOX_TOKEN_ID, PROXMOX_TOKEN_SECRET
Writes component="proxmox_vms" to status_snapshots.
State shape: { health, vms: [VMCard] }
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
# Node names happen to match the display labels in this cluster.
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
            return {"health": "unconfigured", "vms": [], "message": "PROXMOX_HOST not set"}

        headers = {"Authorization": f"PVEAPIToken={token_id}={token_secret}"}
        base = f"https://{host}:8006/api2/json"
        nodes = [n.strip() for n in os.environ.get("PROXMOX_NODES", ",".join(NODES)).split(",") if n.strip()]

        vms = []
        nodes_ok = 0
        try:
            for node in nodes:
                try:
                    r = httpx.get(f"{base}/nodes/{node}/qemu",
                                  headers=headers, verify=False, timeout=8)
                    if r.status_code != 200:
                        log.warning("Proxmox node %s returned HTTP %s", node, r.status_code)
                        continue
                    nodes_ok += 1
                    for vm in r.json().get("data", []):
                        vmid = vm["vmid"]
                        status = vm.get("status", "unknown")
                        cpu_pct = round(vm.get("cpu", 0) * 100, 1) if status == "running" else None
                        mem_used = vm.get("mem")
                        maxmem = vm.get("maxmem")
                        mem_used_gb = round(mem_used / 1e9, 1) if mem_used else None
                        maxmem_gb = round(maxmem / 1e9, 1) if maxmem else None

                        disks = _get_disk_usage(base, headers, node, vmid) if status == "running" else []
                        dot, problem = _classify_vm(status, disks)

                        vms.append({
                            "vmid": vmid,
                            "name": vm.get("name", f"vm-{vmid}"),
                            "node": NODE_DISPLAY.get(node, node),   # display label e.g. "Pmox1"
                            "node_api": node,                        # Proxmox API hostname e.g. "pve"
                            "status": status,
                            "ip": VM_IP_MAP.get(vmid, ""),
                            "vcpus": vm.get("cpus", 0),
                            "maxmem_gb": maxmem_gb,
                            "cpu_pct": cpu_pct,
                            "mem_used_gb": mem_used_gb,
                            "disks": disks,
                            "dot": dot,
                            "problem": problem,
                        })
                except Exception as e:
                    log.warning("Proxmox node %s error: %s", node, e)

            if nodes_ok == 0 and not vms:
                return {"health": "error", "vms": [], "error": "No Proxmox nodes responded"}
            if not vms or all(v["dot"] == "green" for v in vms):
                overall = "healthy"
            elif all(v["dot"] == "red" for v in vms):
                overall = "critical"
            else:
                overall = "degraded"
            return {"health": overall, "vms": vms}

        except Exception as e:
            return {"health": "error", "error": str(e), "vms": []}


def _get_disk_usage(base: str, headers: dict, node: str, vmid: int) -> list:
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


def _classify_vm(status: str, disks: list) -> tuple[str, str | None]:
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
