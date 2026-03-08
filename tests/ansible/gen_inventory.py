#!/usr/bin/env python3
"""Generate inventory.ini from data/ansible_config.json."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = ROOT / "data" / "ansible_config.json"
OUT_PATH = Path(__file__).parent / "inventory.ini"


def generate():
    if not CONFIG_PATH.exists():
        print(f"Config not found: {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)

    with open(CONFIG_PATH) as f:
        cfg = json.load(f)

    lines = []

    def add_hosts(group: str, hosts: list):
        lines.append(f"\n[{group}]")
        for i, h in enumerate(hosts):
            if isinstance(h, dict):
                host_str = h.get("host", "")
                alias = h.get("alias", f"{group}{i+1}")
            else:
                host_str = h
                alias = f"{group.replace('_', '')}{i+1}"
            if host_str:
                lines.append(f"{alias} ansible_host={host_str}")

    add_hosts("swarm_managers", cfg.get("swarm_manager_hosts", []))
    add_hosts("swarm_workers", cfg.get("swarm_worker_hosts", []))
    add_hosts("elastic", cfg.get("elastic_hosts", []))

    lines.append("\n[all:vars]")
    lines.append(f"ansible_user={cfg.get('ansible_user', 'ansible')}")
    key = cfg.get("private_key_path", "")
    if key:
        lines.append(f"ansible_ssh_private_key_file={key}")
    lines.append(f"ansible_port={cfg.get('ssh_port', 22)}")
    lines.append("ansible_ssh_common_args='-o StrictHostKeyChecking=no'")

    OUT_PATH.write_text("\n".join(lines) + "\n")
    print(f"Inventory written to {OUT_PATH}")


if __name__ == "__main__":
    generate()
