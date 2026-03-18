"""Service fingerprints for deterministic environment discovery.

Each entry defines how to detect a service via HTTP/HTTPS probing without LLM.
"""

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
}

# Auth type and category hints per service (used by skill recommendations)
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
}
