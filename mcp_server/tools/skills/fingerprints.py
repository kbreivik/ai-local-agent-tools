"""Service fingerprints for deterministic environment discovery.

Each entry defines how to detect a service via HTTP/HTTPS probing without LLM.
"""
import logging

import httpx

log = logging.getLogger(__name__)

_PROBE_TIMEOUT = 5.0

SERVICE_FINGERPRINTS: dict = {
    "proxmox": {
        "https_paths": ["/api2/json/version"],
        "response_contains": ["repoid", "version"],
        "default_port": 8006,
        "verify_ssl": False,
    },
    "fortigate": {
        "https_paths": ["/api/v2/monitor/system/status"],
        "response_contains": ["serial", "version"],
        "default_port": 443,
        "verify_ssl": False,
    },
    "truenas": {
        "https_paths": ["/api/v2.0/system/version"],
        "response_contains": ["TrueNAS"],
        "default_port": 443,
        "verify_ssl": False,
    },
    "synology": {
        "https_paths": ["/webapi/query.cgi?api=SYNO.API.Info&version=1&method=query"],
        "response_contains": ["SYNO."],
        "default_port": 5001,
        "verify_ssl": False,
    },
    "unifi": {
        "https_paths": ["/api/s/default/stat/health"],
        "response_contains": ["subsystem"],
        "default_port": 8443,
        "verify_ssl": False,
    },
    "opnsense": {
        "https_paths": ["/api/core/firmware/status"],
        "response_contains": ["product_version"],
        "default_port": 443,
        "verify_ssl": False,
    },
    "docker": {
        "http_paths": ["/version"],
        "response_contains": ["ApiVersion"],
        "default_port": 2375,
        "ssh_command": "docker version --format '{{.Server.Version}}'",
    },
    "elasticsearch": {
        "http_paths": ["/"],
        "response_contains": ["cluster_name", "tagline"],
        "default_port": 9200,
    },
    "pihole": {
        "http_paths": ["/admin/api.php?summary"],
        "response_contains": ["domains_being_blocked"],
        "default_port": 80,
    },
    "grafana": {
        "http_paths": ["/api/health"],
        "response_contains": ["database"],
        "default_port": 3000,
    },
    "portainer": {
        "https_paths": ["/api/status"],
        "response_contains": ["Version"],
        "default_port": 9443,
        "verify_ssl": False,
    },
    "kibana": {
        "http_paths": ["/api/status"],
        "response_contains": ["version", "status"],
        "default_port": 5601,
    },
    "nginx": {
        "http_paths": ["/"],
        "response_contains": ["nginx"],
        "default_port": 80,
    },
    "traefik": {
        "http_paths": ["/api/rawdata", "/ping"],
        "response_contains": ["routers", "OK"],
        "default_port": 8080,
    },
    "adguard": {
        "http_paths": ["/control/status"],
        "response_contains": ["dns_addresses", "running"],
        "default_port": 3000,
    },
    "fortiswitch": {
        "https_paths": ["/api/v2/monitor/system/status"],
        "response_contains": ["serial", "version"],
        "default_port": 443,
        "verify_ssl": False,
    },
}

# Auth type and category hints per service (used by skill recommendations)
# Also used for display_name in service catalog seeding
SERVICE_DISPLAY: dict = {
    "proxmox":       "Proxmox VE",
    "fortigate":     "FortiGate Firewall",
    "fortiswitch":   "FortiSwitch",
    "truenas":       "TrueNAS SCALE",
    "synology":      "Synology NAS",
    "unifi":         "UniFi Controller",
    "opnsense":      "OPNsense Firewall",
    "docker":        "Docker Engine",
    "elasticsearch": "Elasticsearch",
    "kibana":        "Kibana",
    "grafana":       "Grafana",
    "portainer":     "Portainer",
    "pihole":        "Pi-hole",
    "adguard":       "AdGuard Home",
    "nginx":         "NGINX",
    "traefik":       "Traefik",
}

SERVICE_HINTS: dict = {
    "proxmox":       {"auth_type": "bearer",  "category": "compute"},
    "fortigate":     {"auth_type": "api_key", "category": "networking"},
    "truenas":       {"auth_type": "api_key", "category": "storage"},
    "synology":      {"auth_type": "session", "category": "storage"},
    "unifi":         {"auth_type": "bearer",  "category": "networking"},
    "opnsense":      {"auth_type": "api_key", "category": "networking"},
    "docker":        {"auth_type": "none",    "category": "compute"},
    "elasticsearch": {"auth_type": "basic",   "category": "monitoring"},
    "pihole":        {"auth_type": "api_key", "category": "networking"},
    "grafana":       {"auth_type": "bearer",  "category": "monitoring"},
    "portainer":     {"auth_type": "bearer",  "category": "compute"},
    "kibana":        {"auth_type": "basic",   "category": "monitoring"},
    "nginx":         {"auth_type": "none",    "category": "networking"},
    "traefik":       {"auth_type": "none",    "category": "networking"},
    "adguard":       {"auth_type": "api_key", "category": "networking"},
    "fortiswitch":   {"auth_type": "api_key", "category": "networking"},
}


def probe_service(host: str, port: int = None, proto: str = "https", verify_ssl: bool = False) -> dict:
    """Probe a single host against all known fingerprints. Returns best match or unknown.

    Args:
        host: IP or hostname (no scheme)
        port: override port (if None, use each fingerprint's default_port)
        proto: "https" or "http" (tries this first, then the opposite)
        verify_ssl: whether to verify TLS certificates

    Returns:
        {"service_id", "display_name", "detected_version", "confidence", "api_base"}
    """
    result = {
        "service_id": "unknown",
        "display_name": "Unknown",
        "detected_version": None,
        "confidence": "none",
        "api_base": None,
    }

    # Build candidate (proto, port) pairs to try
    def _candidates(fp: dict) -> list:
        default = fp.get("default_port", 443 if proto == "https" else 80)
        p = port or default
        protos = [proto, "http" if proto == "https" else "https"]
        seen = set()
        pairs = []
        for pr in protos:
            for pt in [p, default]:
                key = (pr, pt)
                if key not in seen:
                    seen.add(key)
                    pairs.append(key)
        return pairs

    for service_id, fp in SERVICE_FINGERPRINTS.items():
        paths = fp.get("https_paths", []) if proto == "https" else []
        paths += fp.get("http_paths", []) if proto == "http" else []
        # If proto mismatch, still try both path sets
        if not paths:
            paths = fp.get("https_paths", []) + fp.get("http_paths", [])
        if not paths:
            continue

        required = fp.get("response_contains", [])
        fp_verify = fp.get("verify_ssl", verify_ssl)

        for path in paths:
            for pr, pt in _candidates(fp):
                url = f"{pr}://{host}:{pt}{path}"
                try:
                    r = httpx.get(url, timeout=_PROBE_TIMEOUT, verify=fp_verify, follow_redirects=True)
                    if r.status_code not in (200, 401, 403):
                        continue

                    content = r.text
                    if r.status_code == 200 and required and all(kw in content for kw in required):
                        confidence = "high"
                    elif r.status_code in (401, 403):
                        confidence = "medium"
                    else:
                        continue

                    # Extract version
                    detected_version = None
                    if r.status_code == 200:
                        import re, json as _json
                        try:
                            data = _json.loads(content)
                            for key in ("version", "Version", "data"):
                                val = data.get(key)
                                if isinstance(val, str) and re.search(r"\d+\.\d+", val):
                                    detected_version = val
                                    break
                                if isinstance(val, dict):
                                    for sub in ("version", "Version", "system_version"):
                                        sv = val.get(sub)
                                        if isinstance(sv, str) and re.search(r"\d+\.\d+", sv):
                                            detected_version = sv
                                            break
                        except Exception:
                            m = re.search(r'"version"\s*:\s*"([^"]+)"', content, re.IGNORECASE)
                            if m:
                                detected_version = m.group(1)

                    result.update({
                        "service_id": service_id,
                        "display_name": SERVICE_DISPLAY.get(service_id, service_id.title()),
                        "detected_version": detected_version,
                        "confidence": confidence,
                        "api_base": f"{pr}://{host}:{pt}",
                    })
                    log.debug("Identified %s at %s (confidence: %s)", service_id, url, confidence)
                    return result

                except Exception:
                    continue

    return result
