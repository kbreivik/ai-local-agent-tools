"""Ansible — inventory parsing, playbook listing, and cached facts."""
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


SKILL_META = {
    "name": "ansible_inventory",
    "description": "Parse Ansible inventory (hosts/groups), list playbooks, and read cached facts.",
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
            "action": {"type": "string", "description": "'inventory' (default), 'playbooks', or 'facts'"},
            "host": {"type": "string", "description": "Host name for action=facts"},
        },
        "required": [],
    },
    "auth_type": "none",
    "config_keys": ["ANSIBLE_INVENTORY_PATH", "ANSIBLE_PLAYBOOK_DIR"],
    "compat": {
        "service": "ansible",
        "api_version_built_for": "2.16",
        "min_version": "2.10",
        "max_version": "",
        "version_endpoint": "",
        "version_field": "",
    },
}


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ok(data, message="OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}

def _err(message, data=None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


def execute(**kwargs) -> dict:
    action = kwargs.get("action", "inventory")

    if action == "playbooks":
        return _list_playbooks()
    elif action == "facts":
        return _get_facts(kwargs.get("host", ""))
    return _get_inventory()


def _get_inventory() -> dict:
    """Parse Ansible inventory using ansible-inventory --list."""
    inv_path = os.environ.get("ANSIBLE_INVENTORY_PATH", "")
    if not inv_path:
        return _err("ANSIBLE_INVENTORY_PATH not configured")
    if not Path(inv_path).exists():
        return _err(f"Inventory file not found: {inv_path}")

    try:
        # Hardcoded command — no user/LLM input in args (subprocess policy: safe)
        result = subprocess.run(
            ["ansible-inventory", "-i", inv_path, "--list"],
            capture_output=True, text=True, timeout=30,
            shell=False,
        )
        if result.returncode != 0:
            return _err(f"ansible-inventory failed: {result.stderr[:200]}")

        data = json.loads(result.stdout)
        # Extract groups and hosts
        groups = {}
        all_hosts = set()
        for group_name, group_data in data.items():
            if group_name == "_meta":
                continue
            if isinstance(group_data, dict) and "hosts" in group_data:
                hosts = group_data["hosts"]
                groups[group_name] = hosts
                all_hosts.update(hosts)

        return _ok({
            "groups": groups,
            "group_count": len(groups),
            "host_count": len(all_hosts),
            "hosts": sorted(all_hosts),
        }, f"Ansible: {len(all_hosts)} host(s) in {len(groups)} group(s)")

    except subprocess.TimeoutExpired:
        return _err("ansible-inventory timed out (30s)")
    except json.JSONDecodeError as e:
        return _err(f"Failed to parse inventory JSON: {e}")
    except FileNotFoundError:
        return _err("ansible-inventory command not found — is Ansible installed?")
    except Exception as e:
        return _err(f"Inventory error: {e}")


def _list_playbooks() -> dict:
    """List playbook YAML files in the configured directory."""
    pb_dir = os.environ.get("ANSIBLE_PLAYBOOK_DIR", "")
    if not pb_dir:
        return _err("ANSIBLE_PLAYBOOK_DIR not configured")

    pb_path = Path(pb_dir)
    if not pb_path.is_dir():
        return _err(f"Playbook directory not found: {pb_dir}")

    playbooks = []
    for f in sorted(pb_path.glob("**/*.yml")) + sorted(pb_path.glob("**/*.yaml")):
        rel = str(f.relative_to(pb_path))
        playbooks.append({
            "name": f.stem,
            "path": rel,
            "size": f.stat().st_size,
        })

    return _ok({"playbooks": playbooks, "count": len(playbooks)},
               f"Ansible: {len(playbooks)} playbook(s) in {pb_dir}")


def _get_facts(host: str) -> dict:
    """Read cached Ansible facts for a host."""
    if not host:
        return _err("host parameter required for action=facts")

    # Check common fact cache locations
    cache_dirs = [
        os.environ.get("ANSIBLE_CACHE_DIR", ""),
        os.path.expanduser("~/.ansible/tmp/facts"),
        "/tmp/ansible_facts",
    ]

    for cache_dir in cache_dirs:
        if not cache_dir:
            continue
        fact_file = Path(cache_dir) / host
        if fact_file.exists():
            try:
                facts = json.loads(fact_file.read_text())
                # Extract key facts
                summary = {
                    "hostname": facts.get("ansible_hostname", host),
                    "os": f"{facts.get('ansible_distribution', '')} {facts.get('ansible_distribution_version', '')}".strip(),
                    "kernel": facts.get("ansible_kernel", ""),
                    "arch": facts.get("ansible_architecture", ""),
                    "cpus": facts.get("ansible_processor_vcpus", 0),
                    "memory_mb": facts.get("ansible_memtotal_mb", 0),
                    "ipv4": facts.get("ansible_default_ipv4", {}).get("address", ""),
                }
                return _ok(summary, f"Ansible facts for {host} (cached)")
            except Exception as e:
                return _err(f"Failed to parse cached facts for {host}: {e}")

    return _err(f"No cached facts found for {host} — run 'ansible -m setup {host}' first")


def check_compat(**kwargs) -> dict:
    """Check if ansible-inventory is available."""
    try:
        result = subprocess.run(
            ["ansible", "--version"],
            capture_output=True, text=True, timeout=10,
            shell=False,
        )
        if result.returncode == 0:
            version = result.stdout.split("\n")[0]
            return _ok({"compatible": True, "detected_version": version, "reason": version})
        return _ok({"compatible": None, "detected_version": None, "reason": "ansible not found"})
    except Exception as e:
        return _ok({"compatible": None, "detected_version": None, "reason": str(e)})
