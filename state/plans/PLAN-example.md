# Plan: truenas-pool-status skill
Date: 2026-03-10
Status: complete

## Current state
**skill-scout**: 5 skills registered (all Proxmox/FortiGate/generic). No TrueNAS skills.
service_catalog: empty (discover_environment not yet run).
TRUENAS_HOST env var: set in docker/.env.

**service-scout**: Agent v1.10.0 build 12. TrueNAS reachable at vault_truenas_host:80.
API: TrueNAS SCALE 24.04, REST at /api/v2.0/.

## What to build
Type: new skill module

File: `mcp_server/tools/skills/modules/truenas_pool_status.py`

SKILL_META draft:
```python
{
  "name": "truenas_pool_status",
  "description": "Get ZFS pool health and usage from TrueNAS REST API.",
  "category": "storage",
  "parameters": {
    "host": {"type": "string", "required": False}
  },
  "compat": {
    "service": "truenas",
    "api_version_built_for": "24.04",
    "version_endpoint": "/api/v2.0/system/version",
    "version_field": "version"
  }
}
```

execute() outline:
1. Read host from kwargs → TRUENAS_HOST env → _err if missing
2. GET /api/v2.0/pool with Bearer token from TRUENAS_API_KEY env
3. Return pool names, status (ONLINE/DEGRADED/FAULTED), usage %
4. _degraded if any pool is DEGRADED, _err if all FAULTED

## Implementation steps
1. [x] Wrote truenas_pool_status.py
2. [x] `python -m py_compile mcp_server/tools/skills/modules/truenas_pool_status.py`
3. [x] Restarted container — skill auto-loaded by loader.py
4. [x] `skill_execute(name="truenas_pool_status")` — returned 3 pools, all ONLINE
5. [x] `skill_promote(name="truenas_pool_status")`
6. [x] `/commit`

## Vault / config
TRUENAS_API_KEY already in docker/.env (set by Ansible via vault_truenas_api_key)

## Commit
`feat(skill/truenas): add truenas_pool_status skill for ZFS pool monitoring`
