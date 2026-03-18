"""List all VMs on a Proxmox node with status, CPU, memory, and uptime."""
import json
import os
from datetime import datetime, timezone


SKILL_META = {
    "name": "proxmox_vm_status",
    "description": "List all VMs on a Proxmox node with status, CPU, memory, and uptime. Returns degraded if any VMs are stopped.",
    "category": "compute",
    "version": "1.0.0",
    "annotations": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "parameters": {
        "type": "object",
        "properties": {
            "node": {"type": "string", "description": "Proxmox node name"},
        },
        "required": ["node"],
    },
    "auth_type": "token",
    "config_keys": ["PROXMOX_HOST", "PROXMOX_USER", "PROXMOX_TOKEN_ID", "PROXMOX_TOKEN_SECRET"],
}


# ── Response helpers ───────────────────────────────────────────────────────────
def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ok(data, message="OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}

def _err(message, data=None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}

def _degraded(data, message) -> dict:
    return {"status": "degraded", "data": data, "timestamp": _ts(), "message": message}


# ── Config ─────────────────────────────────────────────────────────────────────
def _proxmox_config() -> dict:
    settings_path = os.path.join(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(
                        os.path.dirname(__file__)
                    )
                )
            )
        ),
        "data", "agent_settings.json"
    )
    file_cfg = {}
    try:
        if os.path.exists(settings_path):
            with open(settings_path) as f:
                cfg = json.load(f)
                file_cfg = cfg.get("proxmox", {})
    except Exception:
        pass

    return {
        "host": os.environ.get("PROXMOX_HOST", file_cfg.get("host", "")),
        "user": os.environ.get("PROXMOX_USER", file_cfg.get("user", "root@pam")),
        "token_id": os.environ.get("PROXMOX_TOKEN_ID", file_cfg.get("token_id", "")),
        "token_secret": os.environ.get("PROXMOX_TOKEN_SECRET", file_cfg.get("token_secret", "")),
    }


# ── Execute ────────────────────────────────────────────────────────────────────
try:
    from proxmoxer import ProxmoxAPI

    def execute(**kwargs) -> dict:
        node = kwargs.get("node", "")
        if not node:
            return _err("node is required")

        cfg = _proxmox_config()
        if not cfg["host"]:
            return _err("PROXMOX_HOST not set. Configure via Settings or env var.")
        if not cfg["token_id"] or not cfg["token_secret"]:
            return _err("PROXMOX_TOKEN_ID / PROXMOX_TOKEN_SECRET not set. Configure via Settings or env var.")

        try:
            prox = ProxmoxAPI(
                cfg["host"],
                user=cfg["user"],
                token_name=cfg["token_id"],
                token_value=cfg["token_secret"],
                verify_ssl=False,
            )
            vms_raw = prox.nodes(node).qemu.get()

            vms = []
            stopped_count = 0
            for vm in vms_raw:
                status = vm.get("status", "unknown")
                if status == "stopped":
                    stopped_count += 1
                vms.append({
                    "vmid": vm.get("vmid"),
                    "name": vm.get("name", ""),
                    "status": status,
                    "cpu": vm.get("cpu", 0),
                    "maxmem": vm.get("maxmem", 0),
                    "uptime": vm.get("uptime", 0),
                })

            result = {"node": node, "vms": vms, "total": len(vms), "stopped": stopped_count}

            if stopped_count > 0:
                return _degraded(result,
                                 f"{stopped_count}/{len(vms)} VM(s) stopped on node '{node}'")
            return _ok(result, f"All {len(vms)} VM(s) running on node '{node}'")

        except Exception as e:
            return _err(f"proxmox_vm_status error: {e}")

except ImportError:
    def execute(**kwargs) -> dict:
        return _err("proxmoxer not installed — run: pip install proxmoxer")
