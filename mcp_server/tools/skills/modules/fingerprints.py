"""Service fingerprints — identify services by probing known API paths."""
import httpx

SERVICE_FINGERPRINTS = {
    "proxmox":       {"paths": ["/api2/json/version"],          "fields": ["repoid", "version"],          "port": 8006},
    "pbs":           {"paths": ["/api2/json/version"],          "fields": ["repoid", "version"],          "port": 8007},
    "fortigate":     {"paths": ["/api/v2/monitor/system/status"], "fields": ["serial", "version"],        "port": 443},
    "truenas":       {"paths": ["/api/v2.0/system/version"],    "fields": ["TrueNAS"],                    "port": 443},
    "synology":      {"paths": ["/webapi/query.cgi?api=SYNO.API.Info&version=1&method=query"], "fields": ["SYNO."], "port": 5001},
    "unifi":         {"paths": ["/api/s/default/stat/health"],  "fields": ["subsystem"],                  "port": 8443},
    "opnsense":      {"paths": ["/api/core/firmware/status"],   "fields": ["product_version"],            "port": 443},
    "docker":        {"paths": ["/version"],                    "fields": ["ApiVersion"],                 "port": 2375, "scheme": "http"},
    "elasticsearch": {"paths": ["/_cluster/health"],            "fields": ["cluster_name"],               "port": 9200, "scheme": "http"},
    "pihole":        {"paths": ["/admin/api.php?summary"],      "fields": ["domains_being_blocked"],      "port": 80, "scheme": "http"},
    "grafana":       {"paths": ["/api/health"],                 "fields": ["database"],                   "port": 3000, "scheme": "http"},
    "portainer":     {"paths": ["/api/status"],                 "fields": ["Version"],                    "port": 9443},
    "adguard":       {"paths": ["/control/status"],             "fields": ["dns_addresses"],              "port": 3000, "scheme": "http"},
    "technitium":    {"paths": ["/api/user/session/get"],       "fields": ["status"],                     "port": 5380, "scheme": "http"},
}


def fingerprint_host(address: str, port: int = None) -> dict:
    """Try all fingerprints against a host. Returns first match or None.

    Args:
        address: IP or hostname
        port:    Override port (if None, tries each fingerprint's default)

    Returns: {"service": "proxmox", "version": "8.1", "port": 8006} or None
    """
    for service, fp in SERVICE_FINGERPRINTS.items():
        try_port = port or fp.get("port", 443)
        scheme = fp.get("scheme", "https")
        for path in fp["paths"]:
            url = f"{scheme}://{address}:{try_port}{path}"
            try:
                r = httpx.get(url, verify=False, timeout=4, follow_redirects=True)
                if r.status_code >= 500:
                    continue
                text = r.text
                # Check if any fingerprint field appears in response
                if any(field in text for field in fp["fields"]):
                    version = None
                    try:
                        data = r.json()
                        version = (data.get("data", {}).get("version") or
                                   data.get("version") or
                                   data.get("Release"))
                    except Exception:
                        pass
                    return {
                        "service": service,
                        "version": str(version) if version else "unknown",
                        "port": try_port,
                        "scheme": scheme,
                        "fingerprint_path": path,
                    }
            except Exception:
                continue
    return None
