"""Fact-age rejection (v2.35.3).

When a tool result reports a value for a fact key that contradicts a
high-confidence recently-verified known_fact, the tool result is filtered
per the configured aggression mode.

Modes:
  off     — no rejection (pass-through)
  soft    — advisory harness message only, tool result untouched
  medium  — strip the conflicting value, add ``_rejected_by_fact_age``
            marker, inject a harness advisory
  hard    — signal the tool call as failed so the caller can replace it
            with an error sentinel

Sync-only. Never raises into callers.
"""
from __future__ import annotations

import copy
import json
import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


_REJECTED_SENTINEL = "[REJECTED_BY_FACT_AGE]"


def check_and_apply_rejection(
    tool_name: str,
    args: dict,
    result: dict,
    settings: dict,
) -> tuple[Any, list, str | None]:
    """Apply fact-age rejection to a tool result.

    Returns ``(possibly-modified result, harness_messages_to_inject, failure_reason)``.

    - mode ``off``: ``(result, [], None)`` pass-through.
    - mode ``soft``: ``(result, [advisory], None)``.
    - mode ``medium``: ``(modified_result, [advisory], None)``.
    - mode ``hard`` with rejection: ``(None, [failure_msg], 'fact_age_rejection')``.
    - No rejection fires: ``(result, [], None)``.

    ``settings`` is the facts-related settings dict (see
    ``_get_facts_settings``). Missing keys fall back to spec defaults.
    """
    mode = str((settings or {}).get("factAgeRejectionMode", "medium") or "medium").lower()
    if mode == "off":
        return result, [], None

    try:
        max_age_min = float((settings or {}).get("factAgeRejectionMaxAgeMin", 5) or 5)
    except (TypeError, ValueError):
        max_age_min = 5.0
    try:
        min_conf = float((settings or {}).get("factAgeRejectionMinConfidence", 0.85) or 0.85)
    except (TypeError, ValueError):
        min_conf = 0.85

    try:
        from api.facts.tool_extractors import extract_facts_from_tool_result
        proposed = extract_facts_from_tool_result(
            tool_name, args or {}, result or {},
        )
    except Exception as e:
        log.debug("fact extraction inside rejection check failed: %s", e)
        proposed = []

    if not proposed:
        return result, [], None

    try:
        from api.db.known_facts import get_fact
    except Exception as e:
        log.debug("known_facts import failed inside rejection check: %s", e)
        return result, [], None

    rejections: list[dict] = []
    for p in proposed:
        fk = p.get("fact_key")
        if not fk:
            continue
        try:
            known_rows = get_fact(fk) or []
        except Exception as e:
            log.debug("get_fact failed for %s: %s", fk, e)
            continue

        recent = []
        for r in known_rows:
            if not isinstance(r, dict):
                continue
            if r.get("source") == "agent_observation":
                continue
            try:
                conf = float(r.get("confidence") or 0.0)
            except (TypeError, ValueError):
                conf = 0.0
            if conf < min_conf:
                continue
            age = _age_minutes(r.get("last_verified"))
            if age is None or age > max_age_min:
                continue
            recent.append((conf, age, r))

        if not recent:
            continue

        # Highest confidence row wins, tiebreaker: freshest
        recent.sort(key=lambda t: (-t[0], t[1]))
        _best_conf, _best_age, best = recent[0]
        known_value = best.get("fact_value")
        tool_value = p.get("value")
        if _values_equal(known_value, tool_value):
            continue

        rejections.append({
            "fact_key":         fk,
            "tool_value":       tool_value,
            "known_value":      known_value,
            "known_source":     best.get("source"),
            "known_confidence": round(float(best.get("confidence") or 0.0), 4),
            "known_age_min":    round(_best_age, 2),
        })

    if not rejections:
        return result, [], None

    if mode == "soft":
        return result, [_format_advisory(tool_name, rejections)], None

    if mode == "hard":
        return None, [_format_failure(tool_name, rejections)], "fact_age_rejection"

    # Medium (default): strip conflicting values, inject sentinel, emit advisory
    try:
        modified = copy.deepcopy(result) if isinstance(result, dict) else result
    except Exception:
        modified = result

    if isinstance(modified, dict):
        _strip_conflicting_values(tool_name, modified, rejections)
        marker = modified.setdefault("_rejected_by_fact_age", [])
        if isinstance(marker, list):
            marker.extend(rejections)

    return modified, [_format_medium_advisory(tool_name, rejections)], None


# ── Internals ──────────────────────────────────────────────────────────────


def _values_equal(a, b) -> bool:
    """Compare JSON-serialisable values, tolerant of key ordering."""
    try:
        return json.dumps(a, default=str, sort_keys=True) == \
               json.dumps(b, default=str, sort_keys=True)
    except Exception:
        return a == b


def _age_minutes(last_verified) -> float | None:
    """Return age of ``last_verified`` in minutes, or None if unparseable."""
    if last_verified is None:
        return None
    if isinstance(last_verified, str):
        try:
            last_verified = datetime.fromisoformat(
                last_verified.replace("Z", "+00:00")
            )
        except Exception:
            return None
    if isinstance(last_verified, datetime):
        if last_verified.tzinfo is None:
            last_verified = last_verified.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - last_verified
        return delta.total_seconds() / 60.0
    return None


def _short(v, n: int = 60) -> str:
    try:
        s = v if isinstance(v, str) else json.dumps(v, default=str, sort_keys=True)
    except Exception:
        s = str(v)
    if len(s) > n:
        return s[:n] + "…"
    return s


def _format_medium_advisory(tool_name: str, rejections: list) -> str:
    lines = [
        f"[harness] Fact-age rejection fired on `{tool_name}` results. "
        f"The tool reported values that contradict high-confidence facts "
        f"verified within the last few minutes. The conflicting values "
        f"have been stripped from the tool output you see."
    ]
    for r in rejections[:5]:
        lines.append(
            "  - {fk}: tool said {tv}, known_facts says {kv} "
            "(source {src}, conf {c:.2f}, age {a}min)".format(
                fk=r["fact_key"],
                tv=_short(r["tool_value"]),
                kv=_short(r["known_value"]),
                src=r["known_source"],
                c=float(r["known_confidence"]),
                a=r["known_age_min"],
            )
        )
    lines.append(
        "If you believe the known fact is stale (e.g. something just "
        "changed), call the verification tool specifically for that "
        "entity. Do NOT cite the rejected value in your final answer."
    )
    return "\n".join(lines)


def _format_advisory(tool_name: str, rejections: list) -> str:
    lines = [
        f"[harness] Fact-age rejection advisory on `{tool_name}`: the "
        f"tool reported values that conflict with high-confidence recent "
        f"facts. Tool output is unchanged — verify before citing:"
    ]
    for r in rejections[:5]:
        lines.append(
            "  - {fk}: tool says {tv}, known says {kv} "
            "(source {src}, conf {c:.2f}, age {a}min)".format(
                fk=r["fact_key"],
                tv=_short(r["tool_value"]),
                kv=_short(r["known_value"]),
                src=r["known_source"],
                c=float(r["known_confidence"]),
                a=r["known_age_min"],
            )
        )
    return "\n".join(lines)


def _format_failure(tool_name: str, rejections: list) -> str:
    return (
        f"[harness] Hard fact-age rejection on `{tool_name}`. "
        f"{len(rejections)} fact(s) contradicted by high-confidence "
        f"recent data. Tool result not returned. Either accept the "
        f"known_facts values or call a different verification path."
    )


def _strip_conflicting_values(tool_name: str, result: dict, rejections: list) -> None:
    """Replace tool-reported values with a sentinel where we know the shape.

    Best-effort: unknown shapes are left untouched and rely on the harness
    advisory message to warn the agent.
    """
    if not isinstance(result, dict):
        return
    data = result.get("data")
    if not isinstance(data, dict):
        return

    strippers = _STRIPPERS.get(tool_name)
    if not strippers:
        return
    for fn in strippers:
        try:
            fn(data, rejections)
        except Exception as e:
            log.debug("strip fn failed for %s: %s", tool_name, e)


def _strip_service_placement(data: dict, rejections: list) -> None:
    containers = data.get("containers")
    if not isinstance(containers, list):
        return
    # Identify per-fact-key targets
    bad_nodes = _values_for_suffix(rejections, ".placement")
    bad_hosts = _values_for_suffix(rejections, ".host")
    bad_services = _values_for_suffix(rejections, ".service_name")
    for c in containers:
        if not isinstance(c, dict):
            continue
        if bad_nodes:
            for bn_list in bad_nodes:
                if isinstance(bn_list, list) and c.get("node") in bn_list:
                    c["node"] = _REJECTED_SENTINEL
                    break
        if bad_hosts and c.get("vm_host_label") in bad_hosts:
            c["vm_host_label"] = _REJECTED_SENTINEL
        if bad_services and c.get("service_name") in bad_services:
            c["service_name"] = _REJECTED_SENTINEL


def _strip_kafka_broker_status(data: dict, rejections: list) -> None:
    brokers = data.get("brokers")
    if not isinstance(brokers, list):
        return
    bad_hosts = _values_for_suffix(rejections, ".host")
    bad_ports = _values_for_suffix(rejections, ".port")
    for b in brokers:
        if not isinstance(b, dict):
            continue
        if bad_hosts and b.get("host") in bad_hosts:
            b["host"] = _REJECTED_SENTINEL
        if bad_ports and b.get("port") in bad_ports:
            b["port"] = _REJECTED_SENTINEL


def _strip_container_networks(data: dict, rejections: list) -> None:
    # Networks dicts are hard to compare element-wise; remove the networks
    # field entirely if the whole-value got rejected.
    for r in rejections:
        if not str(r.get("fact_key", "")).endswith(".networks"):
            continue
        if _values_equal(data.get("networks"), r.get("tool_value")):
            data["networks"] = _REJECTED_SENTINEL


def _strip_proxmox_vm_power(data: dict, rejections: list) -> None:
    bad_statuses = _values_for_suffix(rejections, ".status")
    if bad_statuses and data.get("status") in bad_statuses:
        data["status"] = _REJECTED_SENTINEL


def _strip_swarm_node_status(data: dict, rejections: list) -> None:
    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        return
    bad_statuses = _values_for_suffix(rejections, ".status")
    for n in nodes:
        if not isinstance(n, dict):
            continue
        if bad_statuses and n.get("availability") in bad_statuses:
            n["availability"] = _REJECTED_SENTINEL


def _strip_container_tcp_probe(data: dict, rejections: list) -> None:
    for r in rejections:
        fk = str(r.get("fact_key", ""))
        if ".reachability." in fk:
            data["reachable"] = _REJECTED_SENTINEL
            break


def _values_for_suffix(rejections: list, suffix: str) -> list:
    return [
        r.get("tool_value")
        for r in rejections
        if str(r.get("fact_key", "")).endswith(suffix)
    ]


_STRIPPERS: dict[str, list] = {
    "service_placement":             [_strip_service_placement],
    "container_discover_by_service": [_strip_service_placement],
    "kafka_broker_status":           [_strip_kafka_broker_status],
    "container_networks":            [_strip_container_networks],
    "proxmox_vm_power":              [_strip_proxmox_vm_power],
    "swarm_node_status":             [_strip_swarm_node_status],
    "container_tcp_probe":           [_strip_container_tcp_probe],
}
