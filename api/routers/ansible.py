"""Ansible / Proxmox test infrastructure reset API."""
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import get_current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ansible", tags=["ansible"])

ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = ROOT / "data" / "ansible_config.json"
ANSIBLE_DIR = ROOT / "tests" / "ansible"


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {
        "mode": "ansible",
        "ansible_host": "",
        "ansible_user": "ansible",
        "private_key_path": "",
        "public_key_path": "",
        "proxmox_host": "",
        "proxmox_api_token": "",
        "proxmox_node": "pve",
        "proxmox_vm_ids": [],
        "swarm_manager_hosts": [],
        "swarm_worker_hosts": [],
        "elastic_hosts": [],
        "ssh_port": 22,
    }


def _save_config(cfg: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


@router.get("/config")
async def get_config(user: str = Depends(get_current_user)):
    cfg = _load_config()
    # Redact sensitive values in response
    safe = dict(cfg)
    if safe.get("proxmox_api_token"):
        safe["proxmox_api_token"] = "***"
    return safe


class AnsibleConfig(BaseModel):
    mode: str = "ansible"  # "ansible" or "proxmox"
    ansible_host: str = ""
    ansible_user: str = "ansible"
    private_key_path: str = ""
    public_key_path: str = ""
    proxmox_host: str = ""
    proxmox_api_token: str = ""
    proxmox_node: str = "pve"
    proxmox_vm_ids: list = []
    swarm_manager_hosts: list = []
    swarm_worker_hosts: list = []
    elastic_hosts: list = []
    ssh_port: int = 22


@router.post("/config")
async def save_config(cfg: AnsibleConfig, user: str = Depends(get_current_user)):
    data = cfg.model_dump()
    existing = _load_config()
    # Preserve proxmox token if redacted
    if data.get("proxmox_api_token") == "***":
        data["proxmox_api_token"] = existing.get("proxmox_api_token", "")
    _save_config(data)
    return {"status": "ok", "message": "Ansible config saved"}


@router.post("/test-connection")
async def test_connection(user: str = Depends(get_current_user)):
    """Test SSH connectivity to the first manager host."""
    cfg = _load_config()
    managers = cfg.get("swarm_manager_hosts", [])
    if not managers:
        raise HTTPException(400, "No swarm_manager_hosts configured")

    host = managers[0] if isinstance(managers[0], str) else managers[0].get("host")
    ssh_user = cfg.get("ansible_user", "ansible")
    key_path = cfg.get("private_key_path", "")

    try:
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kw = {
            "hostname": host,
            "port": cfg.get("ssh_port", 22),
            "username": ssh_user,
            "timeout": 10,
        }
        if key_path and os.path.exists(key_path):
            kw["key_filename"] = key_path
        client.connect(**kw)
        _, stdout, _ = client.exec_command("echo OK")
        result = stdout.read().decode().strip()
        client.close()
        return {"status": "ok", "message": f"SSH OK to {host}: {result}"}
    except Exception as e:
        raise HTTPException(500, f"SSH connection failed: {e}")


def _run_ansible_playbook(playbook: str, cfg: dict) -> tuple[bool, str]:
    """Run an Ansible playbook, return (success, output)."""
    # Generate inventory first
    try:
        gen_script = ANSIBLE_DIR / "gen_inventory.py"
        subprocess.run(
            [sys.executable, str(gen_script)],
            check=True, capture_output=True, text=True
        )
    except subprocess.CalledProcessError as e:
        return False, f"Inventory generation failed: {e.stderr}"

    inventory = ANSIBLE_DIR / "inventory.ini"
    playbook_path = ANSIBLE_DIR / playbook

    env = os.environ.copy()
    env["ANSIBLE_HOST_KEY_CHECKING"] = "False"
    if cfg.get("private_key_path"):
        env["ANSIBLE_PRIVATE_KEY_FILE"] = cfg["private_key_path"]

    cmd = [
        "ansible-playbook",
        "-i", str(inventory),
        str(playbook_path),
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600, env=env
        )
        output = result.stdout + result.stderr
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "Playbook timed out after 600s"
    except FileNotFoundError:
        return False, "ansible-playbook not found — install with: pip install ansible"
    except Exception as e:
        return False, str(e)


def _run_proxmox_reset(cfg: dict) -> tuple[bool, str]:
    """Rollback Proxmox VMs to their latest snapshot."""
    try:
        from proxmoxer import ProxmoxAPI
    except ImportError:
        return False, "proxmoxer not installed — run: pip install proxmoxer"

    host = cfg.get("proxmox_host", "")
    token = cfg.get("proxmox_api_token", "")
    node = cfg.get("proxmox_node", "pve")
    vm_ids = cfg.get("proxmox_vm_ids", [])

    if not host or not token:
        return False, "proxmox_host and proxmox_api_token must be configured"

    try:
        # Token format: "user@realm!tokenid=secret"
        if "!" in token and "=" in token:
            token_id_part, secret = token.split("=", 1)
            user_part, token_id = token_id_part.rsplit("!", 1)
            px = ProxmoxAPI(
                host, user=user_part, token_name=token_id,
                token_value=secret, verify_ssl=False
            )
        else:
            return False, "proxmox_api_token must be in format: user@realm!tokenid=secret"

        output_lines = []
        for vmid in vm_ids:
            # Get snapshots, find most recent
            try:
                snaps = px.nodes(node).qemu(vmid).snapshot.get()
                snaps = [s for s in snaps if s.get("name") != "current"]
                if not snaps:
                    output_lines.append(f"VM {vmid}: no snapshots found — skipping")
                    continue
                # Sort by snaptime descending
                latest = sorted(snaps, key=lambda s: s.get("snaptime", 0), reverse=True)[0]
                snap_name = latest["name"]
                output_lines.append(f"VM {vmid}: rolling back to snapshot '{snap_name}'")
                # Rollback
                task = px.nodes(node).qemu(vmid).snapshot(snap_name).rollback.post()
                output_lines.append(f"VM {vmid}: rollback task started: {task}")
            except Exception as e:
                output_lines.append(f"VM {vmid}: error: {e}")

        return True, "\n".join(output_lines)
    except Exception as e:
        return False, f"Proxmox API error: {e}"


async def run_reset(mode: Optional[str] = None) -> dict:
    """Run full teardown+setup cycle. Called by test runner."""
    cfg = _load_config()
    actual_mode = mode or cfg.get("mode", "ansible")

    if actual_mode == "proxmox":
        success, output = _run_proxmox_reset(cfg)
        return {
            "status": "ok" if success else "error",
            "mode": "proxmox",
            "output": output,
        }
    else:
        # Ansible: teardown → setup → healthcheck
        steps = []
        for playbook in ["teardown.yml", "setup.yml", "healthcheck.yml"]:
            ok, out = _run_ansible_playbook(playbook, cfg)
            steps.append({"playbook": playbook, "success": ok, "output": out})
            if not ok:
                return {
                    "status": "error",
                    "mode": "ansible",
                    "failed_at": playbook,
                    "steps": steps,
                }
        return {"status": "ok", "mode": "ansible", "steps": steps}


@router.post("/reset")
async def trigger_reset(
    mode: Optional[str] = None,
    user: str = Depends(get_current_user)
):
    """Trigger a full infrastructure reset (teardown + rebuild)."""
    result = await run_reset(mode)
    return result
