# Plan: node-activate-tool-fix
Date: 2026-03-24
Status: complete

## Objective
1. Fix `node_activate` and `node_drain` tool descriptions so agent passes Swarm node IDs, not hostnames
2. Clean up 10 stuck "running" operations (no API to close them — needs DB update or agent restart)
3. Add Swarm node ID lookup to the pre-task context so agent always resolves hostname → node_id

## Root cause

`node_activate(node_id="manager-01")` fails silently or returns wrong result.
The tool requires the Docker Swarm node ID (e.g. `tyimr0p3dsow`), not the hostname.
The agent passed hostname every time → operation escalated → got stuck.

Current tool description:
```
node_activate: "Re-activate a drained or paused node so it can accept tasks again."
node_drain:    "Safely drain a node before maintenance. Use node_activate to reverse."
```

Neither description mentions node_id format. `swarm_status` returns node IDs alongside hostnames.

## Live node ID map (from /api/status)
| Hostname | Swarm node ID | Role |
|----------|--------------|------|
| manager-01 | check via swarm_status | manager |
| manager-02 | check via swarm_status | manager |
| manager-03 | check via swarm_status | manager (★ leader) |
| worker-01 | tyimr0p3dsow | worker |
| worker-02 | scdz8rfwou0i | worker |
| worker-03 | g7nkt24xs0oq | worker |

---

## Step 1 — Fix tool descriptions  ✦ BACKEND
**Risk**: LOW — description change only, behaviour unchanged
**Rebuild**: YES (one rebuild for Steps 1+2 together)

### Locate
```bash
grep -rn "node_activate\|node_drain\|Re-activate\|Safely drain" \
  /app/mcp_server/ --include="*.py" -l
```

### Change: node_activate description
```python
@mcp.tool()
def node_activate(node_id: str) -> dict:
    """
    Re-activate a drained node. node_id = Docker Swarm node ID (hex string),
    NOT the hostname. Use swarm_status() first to get the node ID from hostname.
    Example: swarm_status() → find node with hostname='manager-01' → use its 'id' field.
    """
```

### Change: node_drain description
```python
@mcp.tool()
def node_drain(node_id: str) -> dict:
    """
    Drain a node before maintenance. node_id = Docker Swarm node ID (hex string),
    NOT the hostname. Use swarm_status() first to resolve hostname → node ID.
    Reverse with node_activate(node_id=<same id>).
    """
```

### Verify
```bash
curl -s http://192.168.199.10:8000/api/tools | python3 -c "
import sys,json; d=json.load(sys.stdin)
for t in d['tools']:
  if t['name'] in ('node_activate','node_drain'):
    print(t['name'],':', t['description'][:120])
"
# Expected: descriptions mention 'swarm_status()' and 'hex string'
```

---

## Step 2 — Clean up stuck operations  ✦ BACKEND + optional DB fix
**Risk**: MEDIUM — touching operation state, need to be precise
**Rebuild**: YES (same rebuild as Step 1)

### Locate the operations table
```bash
grep -rn "operations\|operation_id\|status.*running" \
  /app/api/routers/ /app/mcp_server/tools/skills/storage/ --include="*.py" | grep -i "update\|status" | head -20
find /app/data -name "*.db" 2>/dev/null
```

### Option A — Add API endpoint to mark operation complete/failed (preferred)
```python
# api/routers/logs.py — add PATCH endpoint
@router.patch("/operations/{op_id}")
def update_operation_status(op_id: str, status: str, final_answer: str = ""):
    """Mark a stuck operation as failed or completed. Internal use only."""
    db.execute(
        "UPDATE operations SET status=?, completed_at=?, final_answer=? WHERE id=?",
        (status, datetime.utcnow().isoformat(), final_answer, op_id)
    )
    return {"status": "ok", "op_id": op_id, "new_status": status}
```

### Option B — Direct SQLite update (if Option A is too risky)
```bash
# Inside container:
docker exec hp1-agent python3 -c "
import sqlite3, datetime
db = sqlite3.connect('/app/data/agent.db')  # check actual path
db.execute(\"UPDATE operations SET status='failed', completed_at=? WHERE status='running'\",
           (datetime.datetime.utcnow().isoformat(),))
db.commit()
print('Updated', db.total_changes, 'operations')
db.close()
"
```

**Use Option B only if the DB path is confirmed — run impl-scout first.**

### Verify
```bash
curl -s http://192.168.199.10:8000/api/logs/operations | \
  python3 -c "import sys,json; d=json.load(sys.stdin); \
  by_status={}; \
  [by_status.__setitem__(o['status'], by_status.get(o['status'],0)+1) for o in d['operations']]; \
  print(by_status)"
# Expected: {"failed": 10} or {"completed": 10} — nothing "running"
```

---

## Step 3 — Add node ID lookup to swarm-facing agent context  ✦ WISC S layer
**Risk**: LOW — additive context, no behaviour change
**Rebuild**: NO — this is a CLAUDE.md/.claude/docs update only

Update the upgrade-workflow.md and service-scout to always resolve hostname → node_id:

```bash
# Always run this before any node_drain or node_activate:
swarm_status()
# Returns nodes with both 'hostname' and 'id' fields
# Map: hostname → id before calling node_drain/node_activate
```

Add to `.claude/docs/upgrade-workflow.md` under "Node operations":
```
# ALWAYS resolve node_id from swarm_status() first
# Never pass hostname directly to node_drain or node_activate

node_resolution_pattern = """
1. swarm_status()  → find node where hostname == "manager-01"  → get .id
2. node_drain(node_id=.id)   # hex string like "tyimr0p3dsow"
3. [maintenance]
4. node_activate(node_id=.id)  # same hex string
"""
```

---

## Rebuild schedule
```
Rebuild 1: Steps 1+2 (description fix + operations cleanup)
  Agent down ~3min.
  Verify: tool descriptions updated, operations no longer "running"
  
Step 3: No rebuild needed (docs update only)
```

## Session splits
**Session A**: impl-scout → fix tool descriptions + cleanup operations → rebuild → verify → /commit
**Session B** (no rebuild): Update upgrade-workflow.md and service-scout docs → /commit
