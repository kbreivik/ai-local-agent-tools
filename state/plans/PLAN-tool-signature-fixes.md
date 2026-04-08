# Plan: tool-signature-fixes
Date: 2026-03-24 (v2 — confirmed exact signatures from live API)
Priority: #2 — batch with node-activate-fix, one rebuild
Status: complete

## Confirmed tool signatures (from /api/tools)

| Tool | Module | Current params | LLM calls with | Error |
|------|--------|---------------|----------------|-------|
| `skill_execute` | skill_meta_tools | `name` (req), `kwargs_json` (opt, str) | `arguments={...}` | unexpected kwarg 'arguments' |
| `audit_log` | orchestration | `action` (req), `result` (req, Any) | `target="..."` | unexpected kwarg 'target' |
| `discover_environment` | skill_meta_tools | `hosts_json` (req, str) | `()` no args | missing required argument |
| `node_activate` | swarm | `node_id` (req, str) | `node_id="manager-01"` | wrong value (hostname not hex) |
| `node_drain` | swarm | `node_id` (req, str) | `node_id="manager-01"` | wrong value |

Note: `skill_execute` already has `kwargs_json` — the LLM doesn't know and passes `arguments`.
The MCP description says "Pass skill parameters as a JSON object string in kwargs_json."
Fix: accept `arguments` as an alias, OR improve description so LLM stops passing `arguments`.

---

## Step 1 — Locate (impl-scout, no rebuild)
```bash
# skill_execute and discover_environment — same file (skill_meta_tools)
grep -rn "def skill_execute\|def discover_environment\|kwargs_json\|hosts_json" \
  /app/mcp_server/tools/ --include="*.py" | head -20

# audit_log — orchestration module  
grep -rn "def audit_log" /app/mcp_server/tools/ --include="*.py"

# node_activate and node_drain — swarm module
grep -rn "def node_activate\|def node_drain" /app/mcp_server/tools/ --include="*.py"

# Where are these registered in server.py?
grep -n "audit_log\|skill_execute\|discover_environment\|node_activate\|node_drain" \
  /app/mcp_server/server.py
```

---

## Step 2 — Fix skill_execute: accept `arguments` alias
**Risk**: LOW — additive parameter with fallback
**Rebuild**: YES (batch all steps into one rebuild)

### Approach A — Add `arguments` param to MCP tool wrapper in server.py:
```python
# In mcp_server/server.py
@mcp.tool()
def skill_execute(name: str, kwargs_json: str = '', arguments: dict = None) -> dict:
    """Execute a dynamic skill by name. Call skill_search first to find skills.
    Pass skill parameters as:
    - kwargs_json: JSON string e.g. '{"host": "192.168.1.5"}' (preferred)
    - arguments: dict e.g. {"host": "192.168.1.5"} (also accepted)
    Example: skill_execute(name='proxmox_vm_status', kwargs_json='{"node":"Pmox1"}')
    """
    from mcp_server.tools.skill_meta_tools import run_skill_execute
    import json
    # Merge: arguments dict takes precedence if provided, else parse kwargs_json
    if arguments:
        kwargs_json = json.dumps(arguments)
    return run_skill_execute(name=name, kwargs_json=kwargs_json)
```

### Approach B — Improve description only (no param change):
If the function has `**kwargs` internally and just doesn't expose `arguments`:
Update description to be explicit: "Do NOT pass arguments= — use kwargs_json= only."

**Prefer Approach A** (additive, handles both calling styles).

---

## Step 3 — Fix audit_log: add `target` and `details` params
**Risk**: LOW — additive, existing calls unaffected
**Rebuild**: Same rebuild

```python
# In orchestration module (or server.py wrapper)
@mcp.tool()
def audit_log(action: str, result: str, target: str = '', details: str = '') -> dict:
    """Log agent decision to audit table. Called automatically — only use manually
    for significant operations not covered by automatic logging.
    action: verb (upgrade, drain, create, delete, restart)
    result: ok | failed | escalated | skipped | error
    target: resource acted on (kafka, manager-01, proxmox_vm_status) — optional
    details: additional context — optional
    Note: Called at most once per run (subsequent calls in same run are skipped).
    """
    from mcp_server.tools.orchestration import write_audit_log
    return write_audit_log(action=action, result=result, target=target, details=details)
```

Also update `write_audit_log` in orchestration.py to accept and store `target` and `details`.

---

## Step 4 — Fix discover_environment: optional hosts_json with HP1 defaults
**Risk**: LOW — additive default, existing calls unaffected

```python
_HP1_DEFAULT_HOSTS = (
    '[{"address":"192.168.199.10"},'
    '{"address":"192.168.199.21"},{"address":"192.168.199.22"},{"address":"192.168.199.23"},'
    '{"address":"192.168.199.31"},{"address":"192.168.199.32"},{"address":"192.168.199.33"},'
    '{"address":"192.168.199.40"},'
    '{"address":"192.168.1.5","port":8006},'
    '{"address":"192.168.1.6","port":8006},'
    '{"address":"192.168.1.7","port":8006}]'
)

@mcp.tool()
def discover_environment(hosts_json: str = '') -> dict:
    """Scan hosts for services via fingerprinting. Returns skill coverage gaps.
    hosts_json: JSON array of {"address":..., "port":...} objects.
    If not provided, scans the default HP1 homelab hosts automatically.
    Example (scan all HP1 hosts): discover_environment()
    Example (specific host): discover_environment(hosts_json='[{"address":"192.168.199.40"}]')
    """
    from mcp_server.tools.skill_meta_tools import run_discovery
    if not hosts_json:
        hosts_json = _HP1_DEFAULT_HOSTS
    return run_discovery(hosts_json)
```

---

## Step 5 — Fix node_activate / node_drain: clarify hex node_id requirement
**Risk**: NONE — description change only

```python
@mcp.tool()
def node_activate(node_id: str) -> dict:
    """Re-activate a drained Swarm node. IMPORTANT: node_id must be the
    Docker Swarm hex node ID, NOT the hostname.
    
    Always call swarm_status() FIRST to get the node_id from the hostname:
      swarm_status() → find node where hostname=='manager-01' → use its 'id' field
    
    HP1 node IDs (pre-resolved):
      manager-01: yxm2ust947ch  manager-02: tzrptdzsvggh  manager-03: z7zscpi5dxe9
      worker-01:  tyimr0p3dsow  worker-02:  scdz8rfwou0i  worker-03:  g7nkt24xs0oq
    
    Example: node_activate(node_id='yxm2ust947ch')  # activates manager-01
    """
    from mcp_server.tools.swarm import activate_node
    return activate_node(node_id)

@mcp.tool()
def node_drain(node_id: str) -> dict:
    """Drain a Swarm node before maintenance. IMPORTANT: node_id must be the
    Docker Swarm hex node ID, NOT the hostname. Use swarm_status() first.
    Reverse with node_activate(node_id=<same hex id>).
    Requires plan_action() approval before calling.
    
    HP1 node IDs: manager-01=yxm2ust947ch, worker-01=tyimr0p3dsow (see node_activate for full list)
    """
    from mcp_server.tools.swarm import drain_node
    return drain_node(node_id)
```

---

## Verify all fixes
```bash
# After rebuild — run an agent task that exercises all fixed tools:
# "Run audit_log with action='test', result='ok', target='test-fix'. 
#  Then run skill_execute with name='http_health_check', arguments={'url':'http://127.0.0.1:8000/api/health'}.
#  Then run discover_environment with no arguments."

# Check tool logs for errors:
curl -s "http://192.168.199.10:8000/api/logs?limit=20" | \
  python3 -c "
import sys,json; d=json.load(sys.stdin)
errors = [l for l in d.get('logs',[]) if l['result'].get('status')=='error']
print(f'Tool errors: {len(errors)}')
for e in errors[:5]: print(f'  {e[\"tool_name\"]}: {e[\"result\"].get(\"message\",\"\")[:80]}')
"
# Expected: 0 errors on audit_log, skill_execute, discover_environment
```

---

## Rebuild schedule
```
Step 1: No rebuild (impl-scout)
Rebuild 1: Steps 2+3+4+5 — all 5 fixes in one rebuild
  ~3min downtime
  Verify: test task with all 4 tools → 0 errors
```

## Session plan
**Single session**: impl-scout → implement all steps → rebuild → verify → `/commit`
Batch this rebuild with PLAN-node-activate-fix.md (same module — swarm) = saves one rebuild.
