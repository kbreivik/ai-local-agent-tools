"""4-phase deterministic environment discovery pipeline.

Phase 1 ENUMERATE  — probe each host for open ports and connection methods
Phase 2 IDENTIFY   — fingerprint each reachable host against SERVICE_FINGERPRINTS
Phase 3 CATALOG    — upsert identified services into service_catalog
Phase 4 RECOMMEND  — generate skill_create suggestions for uncovered services

The agent calls ONE tool: discover_environment([...]).
Phases execute deterministically inside this function — no LLM decisions between phases.
"""
import logging
import re
import socket
from datetime import datetime, timezone
from typing import Optional

import httpx

from mcp_server.tools.skills.fingerprints import SERVICE_FINGERPRINTS, SERVICE_HINTS

log = logging.getLogger(__name__)

_PROBE_TIMEOUT = 5.0
_SSH_PORT = 22
_COMMON_HTTP_PORTS = [80, 8080]
_COMMON_HTTPS_PORTS = [443, 8443, 8006, 9443, 5001]
_OTHER_PORTS = [2375, 9200, 3000]


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ok(data, message: str = "OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}


def _err(message: str, data=None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


# ── Phase 1: ENUMERATE ────────────────────────────────────────────────────────

def probe_host(address: str, port: Optional[int] = None) -> dict:
    """Check connectivity for a host. Returns open ports and connection methods."""
    result = {
        "address": address,
        "reachable": False,
        "open_ports": [],
        "connection_methods": [],
    }

    all_ports = (
        [port] if port else
        [_SSH_PORT] + _COMMON_HTTP_PORTS + _COMMON_HTTPS_PORTS + _OTHER_PORTS
    )

    for p in all_ports:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(_PROBE_TIMEOUT)
            connected = s.connect_ex((address, p)) == 0
            s.close()
            if connected:
                result["open_ports"].append(p)
                result["reachable"] = True
                if p == _SSH_PORT:
                    result["connection_methods"].append("ssh")
                elif p in _COMMON_HTTP_PORTS:
                    result["connection_methods"].append(f"http:{p}")
                elif p in _COMMON_HTTPS_PORTS:
                    result["connection_methods"].append(f"https:{p}")
                else:
                    result["connection_methods"].append(f"tcp:{p}")
        except OSError:
            pass

    return result


# ── Phase 2: IDENTIFY ─────────────────────────────────────────────────────────

def identify_service(address: str, connection_info: dict) -> dict:
    """Fingerprint a reachable host. Returns service_type, version, api_base."""
    identified = {
        "address": address,
        "service_type": "unknown",
        "version": None,
        "api_base": None,
        "confidence": "none",
    }

    open_ports = connection_info.get("open_ports", [])

    for service_name, fp in SERVICE_FINGERPRINTS.items():
        # Try HTTPS fingerprint paths
        for path in fp.get("https_paths", []):
            ports_to_try = _candidate_ports(fp.get("default_port", 443), open_ports, _COMMON_HTTPS_PORTS)
            for p in ports_to_try:
                match = _probe_url(f"https://{address}:{p}{path}", fp)
                if match:
                    identified.update({
                        "service_type": service_name,
                        "api_base": f"https://{address}:{p}",
                        "confidence": match["confidence"],
                        "version": _extract_version(match["content"]),
                    })
                    return identified

        # Try HTTP fingerprint paths
        for path in fp.get("http_paths", []):
            ports_to_try = _candidate_ports(fp.get("default_port", 80), open_ports, _COMMON_HTTP_PORTS + _OTHER_PORTS)
            for p in ports_to_try:
                match = _probe_url(f"http://{address}:{p}{path}", fp)
                if match:
                    identified.update({
                        "service_type": service_name,
                        "api_base": f"http://{address}:{p}",
                        "confidence": match["confidence"],
                        "version": _extract_version(match["content"]),
                    })
                    return identified

    return identified


def _candidate_ports(default_port: int, open_ports: list, common_pool: list) -> list:
    """Build ordered list of ports to try: default first, then any open matching the pool."""
    candidates = [default_port]
    for p in open_ports:
        if p in common_pool and p not in candidates:
            candidates.append(p)
    return candidates


def _probe_url(url: str, fp: dict) -> Optional[dict]:
    """Probe a URL against a fingerprint. Returns match dict or None."""
    try:
        verify = fp.get("verify_ssl", False)
        r = httpx.get(url, timeout=_PROBE_TIMEOUT, verify=verify, follow_redirects=True)
        if r.status_code not in (200, 401, 403):
            return None

        content = r.text
        required = fp.get("response_contains", [])

        if all(kw in content for kw in required):
            confidence = "high"
        elif r.status_code in (401, 403):
            confidence = "medium"  # endpoint exists but auth-gated
        else:
            return None

        return {"confidence": confidence, "content": content}
    except Exception:
        return None


def _extract_version(content: str) -> Optional[str]:
    """Try to extract a version string from response content."""
    import json as _json
    try:
        data = _json.loads(content)
        for key in ("version", "Version", "data"):
            val = data.get(key)
            if isinstance(val, str) and re.search(r"\d+\.\d+", val):
                return val
            if isinstance(val, dict):
                for sub in ("version", "Version", "system_version", "repoid"):
                    sv = val.get(sub)
                    if isinstance(sv, str) and re.search(r"\d+\.\d+", sv):
                        return sv
    except Exception:
        pass
    m = re.search(r'"version"\s*:\s*"([^"]+)"', content, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


# ── Phase 4: RECOMMEND ────────────────────────────────────────────────────────

def recommend_skills(uncovered_services: list) -> dict:
    """Generate skill_create call suggestions for services without skill coverage."""
    recommendations = []
    for svc in uncovered_services:
        service_type = svc.get("service_type", "unknown")
        if service_type == "unknown":
            continue
        api_base = svc.get("api_base", "")
        address = svc.get("address", "")
        hints = SERVICE_HINTS.get(service_type, {"auth_type": "none", "category": "general"})

        recommendations.append({
            "service_type": service_type,
            "address": address,
            "api_base": api_base,
            "skill_create_call": {
                "description": f"Check {service_type} system status and health",
                "category": hints["category"],
                "api_base": api_base,
                "auth_type": hints["auth_type"],
            },
        })
    return {"recommendations": recommendations, "count": len(recommendations)}


# ── Main pipeline ─────────────────────────────────────────────────────────────

def discover_environment(hosts: list) -> dict:
    """Run the 4-phase environment discovery pipeline.

    Each host dict: {"address": "192.168.1.1", "port": 443}  (port is optional)
    Returns: full catalog + skill recommendations.
    """
    from mcp_server.tools.skills import registry

    if not hosts:
        return _err("No hosts provided")

    # Phase 1: ENUMERATE
    log.info("Discovery Phase 1: ENUMERATE — probing %d host(s)", len(hosts))
    probe_results = []
    for host in hosts:
        address = host.get("address") or host.get("host") or str(host)
        port = host.get("port")
        probe_results.append(probe_host(address, port))

    reachable = [r for r in probe_results if r["reachable"]]
    unreachable = [r for r in probe_results if not r["reachable"]]

    if not reachable:
        return _err(
            f"No reachable hosts found out of {len(hosts)} probed. "
            "Check addresses, firewall rules, or specify explicit ports.",
            data={"probe_results": probe_results},
        )

    # Phase 2: IDENTIFY
    log.info("Discovery Phase 2: IDENTIFY — fingerprinting %d host(s)", len(reachable))
    identified = []
    for probe in reachable:
        svc = identify_service(probe["address"], probe)
        svc["open_ports"] = probe["open_ports"]
        identified.append(svc)

    # Phase 3: CATALOG
    log.info("Discovery Phase 3: CATALOG — upserting %d service(s)", len(identified))
    for svc in identified:
        if svc["service_type"] != "unknown":
            service_id = f"{svc['service_type']}_{svc['address'].replace('.', '_').replace(':', '_')}"
            try:
                registry.upsert_service(
                    service_id=service_id,
                    display_name=f"{svc['service_type'].title()} @ {svc['address']}",
                    service_type=svc["service_type"],
                    detected_version=svc.get("version") or "",
                    notes=f"Auto-discovered. API base: {svc.get('api_base', '')}",
                )
                existing = registry.search_skills(svc["service_type"])
                svc["has_skills"] = len(existing) > 0
                svc["existing_skill_count"] = len(existing)
            except Exception as e:
                log.warning("Catalog upsert failed for %s: %s", svc["address"], e)
                svc["has_skills"] = False
                svc["existing_skill_count"] = 0
        else:
            svc["has_skills"] = False
            svc["existing_skill_count"] = 0

    # Phase 4: RECOMMEND
    log.info("Discovery Phase 4: RECOMMEND")
    uncovered = [s for s in identified if not s.get("has_skills") and s["service_type"] != "unknown"]
    recs = recommend_skills(uncovered)

    known = [s for s in identified if s["service_type"] != "unknown"]
    unknown_hosts = [s["address"] for s in identified if s["service_type"] == "unknown"]

    return _ok({
        "summary": {
            "hosts_probed": len(hosts),
            "reachable": len(reachable),
            "unreachable": len(unreachable),
            "identified": len(known),
            "unknown": len(unknown_hosts),
            "with_skills": len([s for s in known if s.get("has_skills")]),
            "without_skills": len(uncovered),
        },
        "services": identified,
        "unreachable_hosts": [r["address"] for r in unreachable],
        "unknown_hosts": unknown_hosts,
        "skill_recommendations": recs["recommendations"],
    }, (
        f"Discovery complete: {len(reachable)}/{len(hosts)} reachable, "
        f"{len(known)} identified, "
        f"{recs['count']} skill recommendation(s)"
    ))
