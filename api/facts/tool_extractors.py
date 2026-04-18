"""Tool-result fact extractors (v2.35.2).

Complementary to api.facts.extractors (collector-side): these functions read a
tool invocation's args + result dict and emit structured facts at the
``agent_observation`` source tier. Used both for:

- in-run cross-tool contradiction detection (compare values across tool calls
  within a single agent run)
- agent_observation fact writes (successfully-completed runs persist facts to
  known_facts with source=agent_observation)

Each extractor MUST NOT raise. The dispatcher wraps them in try/except and
logs + returns [] on any failure, so a broken extractor cannot take down the
agent loop.

Coverage: the ~7 most-used tools in recent trace data. Extend by adding a new
extractor function + registry entry.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def extract_facts_from_service_placement(args: dict, result: dict) -> list[dict]:
    """service_placement(service_name=...) → placement + container→service + container→host facts."""
    facts: list[dict] = []
    if not isinstance(result, dict) or result.get("status") != "ok":
        return facts
    svc_name = (args or {}).get("service_name")
    if not svc_name:
        return facts

    data = result.get("data") or {}
    containers = data.get("containers") or []
    if not isinstance(containers, list):
        return facts

    nodes = [c.get("node") for c in containers if isinstance(c, dict) and c.get("node")]
    if nodes:
        facts.append({
            "fact_key": f"prod.swarm.service.{svc_name}.placement",
            "source":   "agent_observation",
            "value":    sorted(set(nodes)),
        })
    for c in containers:
        if not isinstance(c, dict):
            continue
        cid = c.get("container_id") or ""
        if not cid:
            continue
        short = cid[:12]
        facts.append({
            "fact_key": f"prod.container.{short}.service_name",
            "source":   "agent_observation",
            "value":    svc_name,
        })
        host = c.get("vm_host_label")
        if host:
            facts.append({
                "fact_key": f"prod.container.{short}.host",
                "source":   "agent_observation",
                "value":    host,
            })
    return facts


def extract_facts_from_container_discover_by_service(args: dict, result: dict) -> list[dict]:
    """Same shape as service_placement for our purposes."""
    return extract_facts_from_service_placement(args, result)


def extract_facts_from_kafka_broker_status(args: dict, result: dict) -> list[dict]:
    """kafka_broker_status → host + port for each broker."""
    facts: list[dict] = []
    if not isinstance(result, dict):
        return facts
    if result.get("status") not in ("ok", "degraded"):
        return facts
    data = result.get("data") or {}
    brokers = data.get("brokers") or []
    if not isinstance(brokers, list):
        return facts
    for b in brokers:
        if not isinstance(b, dict):
            continue
        bid = b.get("id")
        if bid is None or bid == -1:
            continue
        fkey_base = f"prod.kafka.broker.{bid}"
        if b.get("host"):
            facts.append({
                "fact_key": f"{fkey_base}.host",
                "source":   "agent_observation",
                "value":    b.get("host"),
            })
        if b.get("port") is not None:
            facts.append({
                "fact_key": f"{fkey_base}.port",
                "source":   "agent_observation",
                "value":    b.get("port"),
            })
    return facts


def extract_facts_from_container_networks(args: dict, result: dict) -> list[dict]:
    """container_networks(container_id=...) → network attachments for that container."""
    facts: list[dict] = []
    if not isinstance(result, dict) or result.get("status") != "ok":
        return facts
    container_id = ((args or {}).get("container_id") or "")[:12]
    if not container_id:
        return facts
    data = result.get("data") or {}
    networks = data.get("networks")
    if networks:
        facts.append({
            "fact_key": f"prod.container.{container_id}.networks",
            "source":   "agent_observation",
            "value":    networks,
        })
    return facts


def extract_facts_from_container_tcp_probe(args: dict, result: dict) -> list[dict]:
    """container_tcp_probe → reachability boolean (volatile — short half-life)."""
    facts: list[dict] = []
    if not isinstance(result, dict) or result.get("status") != "ok":
        return facts
    a = args or {}
    container_id = (a.get("container_id") or "")[:12]
    target_host = a.get("target_host")
    target_port = a.get("target_port")
    if not container_id or not target_host:
        return facts
    target = f"{target_host}:{target_port}"
    data = result.get("data") or {}
    facts.append({
        "fact_key": f"prod.container.{container_id}.reachability.{target}",
        "source":   "agent_observation",
        "value":    bool(data.get("reachable", False)),
        "metadata": {"volatile": True},
    })
    return facts


def extract_facts_from_proxmox_vm_power(args: dict, result: dict) -> list[dict]:
    """proxmox_vm_power(action='status', vm_label=...) → VM status."""
    facts: list[dict] = []
    a = args or {}
    if a.get("action") != "status":
        return facts
    if not isinstance(result, dict) or result.get("status") != "ok":
        return facts
    vm_label = a.get("vm_label")
    if not vm_label:
        return facts
    data = result.get("data") or {}
    status = data.get("status")
    if status:
        facts.append({
            "fact_key": f"prod.proxmox.vm.{vm_label}.status",
            "source":   "agent_observation",
            "value":    status,
        })
    return facts


def extract_facts_from_swarm_node_status(args: dict, result: dict) -> list[dict]:
    """swarm_node_status → per-node availability."""
    facts: list[dict] = []
    if not isinstance(result, dict) or result.get("status") != "ok":
        return facts
    data = result.get("data") or {}
    nodes = data.get("nodes") or []
    if not isinstance(nodes, list):
        return facts
    for node in nodes:
        if not isinstance(node, dict):
            continue
        nm = node.get("hostname") or node.get("name")
        if not nm:
            continue
        availability = node.get("availability")
        if availability:
            facts.append({
                "fact_key": f"prod.swarm.node.{nm}.status",
                "source":   "agent_observation",
                "value":    availability,
            })
    return facts


TOOL_EXTRACTORS = {
    "service_placement":              extract_facts_from_service_placement,
    "container_discover_by_service":  extract_facts_from_container_discover_by_service,
    "kafka_broker_status":            extract_facts_from_kafka_broker_status,
    "container_networks":             extract_facts_from_container_networks,
    "container_tcp_probe":            extract_facts_from_container_tcp_probe,
    "proxmox_vm_power":               extract_facts_from_proxmox_vm_power,
    "swarm_node_status":              extract_facts_from_swarm_node_status,
}


def extract_facts_from_tool_result(tool_name: str, args: dict, result: dict) -> list[dict]:
    """Dispatcher. Unknown tools return []; extractor errors are swallowed."""
    fn = TOOL_EXTRACTORS.get(tool_name or "")
    if not fn:
        return []
    try:
        out = fn(args or {}, result or {})
        return out if isinstance(out, list) else []
    except Exception as e:
        log.warning("tool fact extraction failed for %s: %s", tool_name, e)
        return []
