---
paths:
  - "mcp_server/tools/skills/modules/*.py"
  - "mcp_server/tools/skills/modules/**/*.py"
---
# Skill module rules

## Hard contract (enforced by validator.py AST check)
Every skill module MUST have:
- `SKILL_META` dict at module level
- `execute(**kwargs)` function — SYNC, never async
- Return value: `_ok(data)`, `_err(message)`, or `_degraded(data, message)` dict
- Import helpers: `from mcp_server.tools.skills.modules._template import _ok, _err, _degraded, _ts`

## SKILL_META required fields
```python
SKILL_META = {
    "name": "{service}_{action}",          # snake_case, matches filename
    "description": "One clear sentence.",   # shown to LLM
    "category": "compute",                  # compute|networking|monitoring|storage|orchestration
    "parameters": {
        "param_name": {
            "type": "string",               # string|integer|boolean
            "required": False,              # True only if no fallback possible
            "description": "what it does"
        }
    },
    "compat": {
        "service": "proxmox",               # lowercase service name
        "api_version_built_for": "7.4",
        "version_endpoint": "/api2/json/version",
        "version_field": "data.version",    # dot-path to version in response
    }
}
```

## execute() rules
```python
def execute(**kwargs) -> dict:
    # 1. Read config — env first, agent_settings.json fallback
    host = kwargs.get("host") or os.environ.get("PROXMOX_HOST", "")
    if not host:
        return _err("PROXMOX_HOST not configured")

    # 2. Make request — use requests library, handle exceptions
    try:
        resp = requests.get(f"https://{host}/api", timeout=10, verify=False)
        resp.raise_for_status()
    except requests.RequestException as e:
        return _err(f"Request failed: {e}")

    # 3. Return structured result
    return _ok({"vms": resp.json()["data"]})
```

## BANNED imports (validator.py will reject)
- subprocess, os.system, os.popen
- eval, exec, compile
- importlib (dynamic import)
- socket (use requests)
- Any import not in requirements.txt

## Config resolution order
1. kwargs passed by MCP caller
2. os.environ.get("SERVICE_HOST")
3. agent_settings.json key
4. Return _err("not configured") — never crash

## Return format
```python
_ok(data_dict)           # status: ok
_err("message")          # status: error
_degraded(data, "msg")   # status: degraded (partial data available)
# All include timestamp from _ts()
```
