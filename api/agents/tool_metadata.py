"""
Per-tool blast radius annotations.
  node    — affects a single host
  service — affects one Swarm service (potentially multi-replica on one cluster)
  cluster — affects cluster-wide behaviour (Kafka, Swarm quorum, Proxmox HA)
  fleet   — affects every tracked asset (cred rotation, connection deletion, etc.)
"""
from typing import Literal

Radius = Literal["none", "node", "service", "cluster", "fleet"]

TOOL_RADIUS: dict[str, Radius] = {
    # observe / read-only — none
    "vm_exec_read":           "none",    # if such a read-only sibling exists
    "kafka_topic_inspect":    "none",
    "kafka_consumer_lag":     "none",
    "swarm_node_status":      "none",
    "service_placement":      "none",

    # node radius
    "vm_exec":                "node",    # default; may escalate via args
    "proxmox_vm_power":       "node",

    # service radius
    "swarm_service_force_update": "service",

    # cluster radius
    "kafka_exec":             "cluster",  # by default any write action
    "connection_delete":      "fleet",
    "credential_profile_rotate": "fleet",
}

_DESTRUCTIVE_CMD_PREFIXES = ("rm ", "dd ", "mkfs", "shutdown", "reboot", "systemctl stop")


def radius_of(tool: str, args: dict | None = None) -> Radius:
    """Static lookup with arg-based escalation for vm_exec."""
    base = TOOL_RADIUS.get(tool, "none")
    if tool == "vm_exec" and args:
        cmd = (args.get("command") or "").strip()
        if any(cmd.startswith(p) for p in _DESTRUCTIVE_CMD_PREFIXES):
            return "node"   # keep at node radius — one host
        return base
    if tool == "kafka_exec" and args:
        # list/describe/show → none; writes → cluster
        cmd = (args.get("command") or "").lower()
        if any(cmd.startswith(p) for p in ("list", "describe", "show", "get")):
            return "none"
    return base


REQUIRES_EXTRA_CONFIRM = frozenset({"cluster", "fleet"})


def needs_extra_confirm(radius: Radius) -> bool:
    return radius in REQUIRES_EXTRA_CONFIRM


_RADIUS_ORDER = ["none", "node", "service", "cluster", "fleet"]


def max_radius(radii: list[str]) -> Radius:
    """Return the highest radius from a list, defaulting to 'none'."""
    if not radii:
        return "none"
    return max(radii, key=lambda r: _RADIUS_ORDER.index(r) if r in _RADIUS_ORDER else 0)


def enrich_plan_steps(steps: list) -> tuple[list, str]:
    """Given plan steps (list of strings or dicts), annotate each with radius
    and extra_confirm_required. Returns (enriched_steps, plan_radius)."""
    enriched = []
    for s in steps:
        if isinstance(s, dict):
            tool = s.get("tool") or ""
            args = s.get("args") or s.get("args_preview") or {}
            if not isinstance(args, dict):
                args = {}
            r = radius_of(tool, args) if tool else "none"
            enriched.append({
                **s,
                "radius": r,
                "extra_confirm_required": needs_extra_confirm(r),
            })
        else:
            # Plain string step — radius unknown, treat as none
            enriched.append({
                "description": str(s),
                "radius": "none",
                "extra_confirm_required": False,
            })
    plan_r = max_radius([e["radius"] for e in enriched])
    return enriched, plan_r
