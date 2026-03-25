---
paths:
  - "api/**/*.py"
  - "mcp_server/**/*.py"
  - "agent/**/*.py"
---
# Python rules (ai-local-agent-tools)

## Sync-only — non-negotiable
- NO async def anywhere — project is synchronous
- NO await, NO asyncio imports

## Return format — everywhere
```python
{"status": "ok"|"error"|"degraded", "data": ..., "timestamp": "...", "message": "..."}
# Helpers: _ok(), _err(), _degraded() — never construct dicts manually
```

## Confirmed tool signatures (live API — do not deviate)

### skill_execute (module: skill_meta_tools)
```python
# Current: skill_execute(name: str, kwargs_json: str = '')
# LLM calls with: arguments={...}  ← needs alias

# Correct wrapper in server.py:
@mcp.tool()
def skill_execute(name: str, kwargs_json: str = '', arguments: dict = None) -> dict:
    """Execute a skill. Use kwargs_json (JSON string) OR arguments (dict) — both accepted.
    Example: skill_execute(name='proxmox_vm_status', kwargs_json='{"node":"Pmox1"}')
    Example: skill_execute(name='http_health_check', arguments={"url":"http://..."})
    """
    import json
    if arguments:
        kwargs_json = json.dumps(arguments)
    from mcp_server.tools.skill_meta_tools import run_skill_execute
    return run_skill_execute(name=name, kwargs_json=kwargs_json)
```

### audit_log (module: orchestration)
```python
# Current: audit_log(action: str, result: Any)
# LLM calls with: target="..."  ← needs param

# Correct wrapper:
@mcp.tool()
def audit_log(action: str, result: str, target: str = '', details: str = '') -> dict:
    """Log agent action. action=verb, result=ok|failed|escalated, target=resource (optional).
    Called at most once per run — subsequent calls in same run are auto-skipped.
    """
    from mcp_server.tools.orchestration import write_audit_log
    return write_audit_log(action=action, result=result, target=target, details=details)
```

### discover_environment (module: skill_meta_tools)
```python
# Current: discover_environment(hosts_json: str) — required, breaks on no-arg call
# Fix: make optional with HP1 defaults

_HP1_DEFAULT_HOSTS = '[{"address":"192.168.199.10"},{"address":"192.168.199.21"},{"address":"192.168.199.22"},{"address":"192.168.199.23"},{"address":"192.168.199.31"},{"address":"192.168.199.32"},{"address":"192.168.199.33"},{"address":"192.168.199.40"},{"address":"192.168.1.5","port":8006}]'

@mcp.tool()
def discover_environment(hosts_json: str = '') -> dict:
    """Scan hosts for services. If hosts_json not provided, scans all HP1 homelab hosts.
    Example (scan HP1 defaults): discover_environment()
    Example (specific): discover_environment(hosts_json='[{"address":"192.168.199.40"}]')
    """
    from mcp_server.tools.skill_meta_tools import run_discovery
    return run_discovery(hosts_json or _HP1_DEFAULT_HOSTS)
```

### node_activate / node_drain (module: swarm)
```python
# node_id MUST be Swarm hex ID — never hostname
# Confirmed HP1 node IDs (embed in description):
# manager-01=yxm2ust947ch, manager-02=tzrptdzsvggh, manager-03=z7zscpi5dxe9
# worker-01=tyimr0p3dsow, worker-02=scdz8rfwou0i, worker-03=g7nkt24xs0oq

@mcp.tool()
def node_activate(node_id: str) -> dict:
    """Re-activate drained Swarm node. node_id = hex Swarm ID (NOT hostname).
    Always call swarm_status() first to get node_id from hostname.
    HP1 IDs: manager-01=yxm2ust947ch worker-01=tyimr0p3dsow (swarm_status for others)
    """
    ...

@mcp.tool()
def node_drain(node_id: str) -> dict:
    """Drain Swarm node. node_id = hex Swarm ID (NOT hostname). Requires plan_action() first.
    HP1 IDs: manager-01=yxm2ust947ch worker-01=tyimr0p3dsow (swarm_status for others)
    Reverse with: node_activate(node_id=<same id>)
    """
    ...
```

## Alert routing rule
```python
MUNINNDB_BLOCKED_PREFIXES = ("alert:",)
# alert:* → /api/alerts/ (persistent, dismissable, 30-min dedup)
# outcome:*, pattern:*, doc:*, infra_status:* → MuninnDB
```

## Outcome engram rule — WISC W layer
```python
# Write after EVERY agent task completion — seeds self-improvement
# concept: "outcome:<task_type>:<service>"
```

## Operations completion rule — CRITICAL
```python
# After agent loop emits "Agent finished after N steps":
# MUST write to DB: status='completed', completed_at=now(), final_answer=..., total_duration_ms=...
# Use try/except — DB failure must NEVER crash the output stream
# Pattern: UPDATE operations SET status='completed', completed_at=? WHERE session_id=? AND status='running'
```

## Error handling
- Catch specific exceptions, not bare `except:`
- Return `_err(str(e))` from tools — never raise
- `logger = logging.getLogger(__name__)` — no print() in production
- Absolute imports only
