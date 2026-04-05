# Plugins

Human-written tools that extend the agent's capabilities. Auto-discovered at startup.

## Contract

Every plugin is a single `.py` file in this directory with two required exports:

### PLUGIN_META (dict)

```python
PLUGIN_META = {
    "name": "pihole_dns_stats",           # snake_case, globally unique
    "description": "Query Pi-hole DNS statistics and top blocked domains.",
    "platform": "pihole",                 # target platform (used for RAG scoping)
    "category": "monitoring",             # monitoring | networking | storage | compute | general
    "agent_types": ["investigate", "execute"],  # which agent types can call this tool
    "requires_plan": False,               # True = added to DESTRUCTIVE_TOOLS (needs plan_action)
    "params": {
        "host": {"type": "string", "required": False, "description": "Pi-hole host (default: env PIHOLE_HOST)"},
    },
}
```

### execute(**kwargs) -> dict

```python
def execute(**kwargs) -> dict:
    host = kwargs.get("host") or os.environ.get("PIHOLE_HOST", "")
    if not host:
        return _err("PIHOLE_HOST not configured")
    # ... do the work ...
    return _ok({"queries_today": 12345, "blocked_today": 678})
```

## Rules

- **Sync only** — no `async def`, no `await`
- **Return format** — always `_ok(data)`, `_err(message)`, or `_degraded(data, message)`
- **Config** — env vars first, kwargs override. Never hardcode IPs/secrets.
- **No dangerous imports** — no subprocess, eval, exec, os.system
- **Error handling** — catch exceptions, return `_err()`. Never raise.

## Response helpers

Include these at the top of every plugin (or import from the template):

```python
from datetime import datetime, timezone

def _ts(): return datetime.now(timezone.utc).isoformat()
def _ok(data, message="OK"): return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}
def _err(message, data=None): return {"status": "error", "data": data, "timestamp": _ts(), "message": message}
def _degraded(data, message): return {"status": "degraded", "data": data, "timestamp": _ts(), "message": message}
```

## File naming

`{platform}_{action}.py` — e.g. `pihole_dns_stats.py`, `truenas_pool_status.py`

The filename must match `PLUGIN_META["name"]`.

## Docker

The `plugins/` directory is mounted as a volume so plugins persist across container rebuilds.
Drop a `.py` file here and restart the agent to load it.
