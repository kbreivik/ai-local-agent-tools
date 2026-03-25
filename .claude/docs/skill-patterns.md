# Skill Patterns Reference

> Scout-loaded only. Use when adding or debugging skills.
> Read H2 headers first to determine which section you need.

---

## Current skills inventory (v1.10.0)

| Name | Category | Service | Compat version | Status |
|------|----------|---------|---------------|--------|
| `proxmox_vm_monitor` | compute | proxmox | 1.0 | built-in |
| `proxmox_vm_monitoring` | compute | proxmox | 1.0 | built-in |
| `proxmox_vm_status` | compute | proxmox | 1.0 | built-in |
| `fortigate_system_status` | networking | fortigate | — | built-in |
| `http_health_check` | monitoring | generic | — | built-in |

Built-in skills cannot be scrapped or promoted. They live in modules/ and are loaded by loader.py.

---

## Skill categories

| Category | Use for |
|----------|---------|
| `compute` | VM status, resource usage, provisioning checks |
| `networking` | FortiGate, VLANs, firewall rules, connectivity |
| `monitoring` | Health checks, alerting, metrics |
| `storage` | TrueNAS, disk usage, volume status |
| `orchestration` | Docker Swarm, Kafka, Elasticsearch management |

---

## SKILL_META compat field patterns by service

### Proxmox
```python
"compat": {
    "service": "proxmox",
    "api_version_built_for": "7.4",
    "version_endpoint": "/api2/json/version",
    "version_field": "data.version",
    "min_version": "7.0",
    "max_version": None
}
```
Auth: token in header `Authorization: PVEAPIToken=user@realm!tokenid=secret`
Base URL from: `os.environ.get("PROXMOX_HOST")` → `https://{host}:8006`

### FortiGate
```python
"compat": {
    "service": "fortigate",
    "api_version_built_for": "7.4",
    "version_endpoint": "/api/v2/monitor/system/firmware",
    "version_field": "current.version",
}
```
Auth: API key in header `Authorization: Bearer {token}`
Base URL from: `os.environ.get("FORTIGATE_HOST")` → `https://{host}`

### Elasticsearch
```python
"compat": {
    "service": "elasticsearch",
    "api_version_built_for": "8.12",
    "version_endpoint": "/",
    "version_field": "version.number",
}
```
Base URL from: `os.environ.get("ELASTIC_URL")` → `http://{host}:9200`

### Kafka
```python
"compat": {
    "service": "kafka",
    "api_version_built_for": "3.6",
    "version_endpoint": "/v3/clusters",    # Kafka REST Proxy
    "version_field": "data[0].cluster_id", # Use broker_version from metadata
}
```
Bootstrap servers from: `os.environ.get("KAFKA_BOOTSTRAP_SERVERS")`

### TrueNAS
```python
"compat": {
    "service": "truenas",
    "api_version_built_for": "24.04",
    "version_endpoint": "/api/v2.0/system/version",
    "version_field": "version",
}
```
Auth: API key in header `Authorization: Bearer {token}`
Base URL from: `os.environ.get("TRUENAS_HOST")` → `http://{host}`

### Docker (local socket or remote)
```python
"compat": {
    "service": "docker",
    "api_version_built_for": "27.0",
    "version_endpoint": None,  # Use docker SDK
    "version_field": None,
}
```
Use `import docker; client = docker.from_env()` — Docker SDK, not requests.
Note: Docker SDK calls are still sync — `docker.from_env()` returns sync client.

---

## Full skill template with all patterns

```python
"""
<service>_<action>.py — <one-line description>
"""
import os
import requests

from mcp_server.tools.skills.modules._template import _ok, _err, _degraded, _ts

SKILL_META = {
    "name": "<service>_<action>",
    "description": "<clear one-line description>",
    "category": "<compute|networking|monitoring|storage|orchestration>",
    "parameters": {
        "host": {
            "type": "string",
            "required": False,
            "description": "Override host (uses env var if not provided)"
        }
    },
    "compat": {
        "service": "<service>",
        "api_version_built_for": "<version>",
        "version_endpoint": "<endpoint>",
        "version_field": "<dot.path.to.version>",
    }
}


def execute(**kwargs) -> dict:
    """
    <What this does and what it returns.>
    Returns degraded if partial data available.
    """
    # 1. Config resolution: kwargs → env → error
    host = kwargs.get("host") or os.environ.get("<SERVICE>_HOST", "")
    if not host:
        return _err("<SERVICE>_HOST not configured — set in environment or pass as param")

    token = os.environ.get("<SERVICE>_API_KEY", "")
    # No error on missing token if service allows unauthenticated — adjust as needed

    # 2. Build request
    url = f"https://{host}/api/endpoint"
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    # 3. Execute with error handling
    try:
        resp = requests.get(url, headers=headers, timeout=10, verify=False)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.ConnectionError:
        return _err(f"Cannot connect to {host} — is the service running?")
    except requests.exceptions.Timeout:
        return _err(f"Timeout connecting to {host}")
    except requests.exceptions.HTTPError as e:
        return _err(f"HTTP {e.response.status_code} from {host}: {e}")
    except Exception as e:
        return _err(f"Unexpected error: {e}")

    # 4. Process and return
    # Return _degraded if partial data
    items = data.get("data", [])
    failed = [x for x in items if x.get("status") != "ok"]

    if failed and len(failed) == len(items):
        return _err(f"All {len(items)} items failed")

    if failed:
        return _degraded(
            {"items": items, "failed_count": len(failed)},
            f"{len(failed)} of {len(items)} items have issues"
        )

    return _ok({"items": items, "count": len(items)})
```

---

## Spec-first generation (how skill_create works internally)

When `skill_create(description, service)` is called:

1. `spec_generator.py` — LLM generates `SKILL_SPEC` (JSON, not code):
```json
{
  "name": "kafka_consumer_lag",
  "service": "kafka",
  "endpoint": "/v3/clusters/{cluster}/consumer-groups",
  "auth": "none",
  "response_field": "data[].lag_sum",
  "category": "monitoring"
}
```

2. `live_validator.py` — probes the real endpoint to verify it exists and returns expected shape

3. `generator.py` — generates Python from the validated spec (near-deterministic)

4. `validator.py` — AST check: no dangerous imports, SKILL_META present, execute() is sync

5. Saved to `modules/`, registered in DB with `status: generated`

6. Must be `skill_promote`d to become permanent

---

## Common failure modes

### validator.py rejects the skill
- `async def execute` — remove async
- `import subprocess` — replace with requests or docker SDK
- Missing `SKILL_META` — add it
- Missing `execute(**kwargs)` signature — fix signature

### live_validator fails
- Service not reachable from agent container — check ELASTIC_URL, PROXMOX_HOST env vars
- Wrong version_endpoint — verify manually with curl from agent-01
- SSL errors — add `verify=False` to requests call (homelab self-signed certs)

### Compat check fails after upgrade
- `api_version_built_for` is stale — run `skill_update_compat(name, new_version)`
- Endpoint moved in new version — run `skill_regenerate(name)`
- Field path changed — update `version_field` in SKILL_META
