# Plan: operations-complete-fix
Date: 2026-03-24 (v2 — updated with confirmed DB schema and tool patterns)
Priority: #1
Status: complete

## Confirmed facts

From live API inspection:
- operations table fields: id, session_id, label, started_at, **completed_at**, **status**,
  triggered_by, **model_used**, **total_duration_ms**, feedback, feedback_at, **final_answer**, owner_user
- Output page: `✓ Agent finished after N steps.` emitted in green — loop IS completing
- DB: operations.status stays `'running'`, completed_at stays null — **write never happens**
- Stop API: sends signal (`status: ok`) but also never updates DB
- 14 operations total, 0 completed, 0% success rate

The loop has 3 phases visible in Output: **Build → Execute → Observe**.
Each phase calls `[memory] N relevant engram(s) activated` before tool calls.
Final step always: `✓ Agent finished after N steps.` — this is the target insertion point.

---

## Step 1 — Locate (spawn impl-scout, no rebuild)

Run ALL grep patterns from impl-scout. Must return before Step 2.

**Critical questions for impl-scout:**
1. What file emits "finished after"? What line?
2. What DB pattern is used in that file? (sqlite3 / SQLAlchemy / storage module)
3. What is the DB path or connection getter?
4. What file handles `/api/agent/stop`?
5. What is the session→operation relationship? (Does session object hold operation_id?)

---

## Step 2 — Fix A: agent loop completion DB write
**Risk**: LOW — 5-10 lines added after existing emit, no logic change
**Rebuild**: YES (batch with Step 3)

### The fix pattern (adapt to DB pattern found by impl-scout)

Immediately after the line that emits/logs "Agent finished after N steps":

#### If SQLAlchemy (most likely given FastAPI project):
```python
# After emitting "Agent finished after N steps."
try:
    with get_db() as db:
        op = db.query(Operation).filter(
            Operation.session_id == session_id
        ).first()
        if op and op.status == 'running':
            op.status = 'completed'
            op.completed_at = datetime.utcnow()
            op.final_answer = final_answer_text
            op.model_used = model_name or ''
            op.total_duration_ms = int((time.time() - _start_time) * 1000)
            db.commit()
except Exception as e:
    logger.error(f"Failed to mark operation complete: {e}")
    # Never let DB failure crash the agent output
```

#### If raw sqlite3:
```python
try:
    import sqlite3, datetime as _dt, time as _time
    _conn = sqlite3.connect(DB_PATH)
    _conn.execute(
        """UPDATE operations SET
           status='completed', completed_at=?, final_answer=?,
           model_used=?, total_duration_ms=?
           WHERE session_id=? AND status='running'""",
        (_dt.datetime.utcnow().isoformat(), final_answer_text,
         model_name or '', int((_time.time() - _start_time) * 1000),
         session_id)
    )
    _conn.commit()
    _conn.close()
except Exception as e:
    logger.error(f"Failed to mark operation complete: {e}")
```

#### If storage module pattern:
```python
try:
    from mcp_server.tools.skills.storage import get_backend
    backend = get_backend()
    backend.complete_operation(
        session_id=session_id,
        final_answer=final_answer_text,
        model_used=model_name or '',
        duration_ms=int((time.time() - _start_time) * 1000)
    )
except Exception as e:
    logger.error(f"Failed to mark operation complete: {e}")
```

### Verify
Run a simple task ("Run swarm_status and report nodes"), then immediately:
```bash
curl -s "http://192.168.199.10:8000/api/logs/operations?limit=3" | \
  python3 -c "
import sys,json; d=json.load(sys.stdin)
for o in d.get('operations',[])[:3]:
  print(o['status'], '|', o.get('completed_at','None')[:19] if o.get('completed_at') else 'None', '|', o['label'][:30])
"
# Expected: most recent op shows 'completed' with timestamp
curl -s "http://192.168.199.10:8000/api/logs/stats" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print('success_rate:', d['success_rate'])"
# Expected: > 0
```

---

## Step 3 — Fix B: stop handler marks operation stopped
**Risk**: LOW — 3 lines added to existing stop handler
**Rebuild**: Same rebuild as Step 2

In `/app/api/routers/agent.py` (or wherever `/api/agent/stop` is handled):

```python
@router.post("/stop")
def stop_agent(req: StopRequest, db: Session = Depends(get_db)):
    session_id = req.session_id
    
    # Existing: send stop signal to the running session
    _send_stop_signal(session_id)  # or however it's done
    
    # ADD: also mark the operation as stopped in DB
    op = db.query(Operation).filter(
        Operation.session_id == session_id,
        Operation.status == 'running'
    ).first()
    if op:
        op.status = 'stopped'
        op.completed_at = datetime.utcnow()
        db.commit()
    
    return {"status": "ok", "message": f"Stop signal sent for session '{session_id}'"}
```

---

## Step 4 — Clean up existing stuck operations (no rebuild)
**Risk**: LOW — only touches operations older than 10 minutes

After rebuild, do this once via docker exec:
```bash
docker exec hp1-agent python3 << 'PYEOF'
import sqlite3, datetime, os

# Find DB — try common paths
for path in ['/app/data/agent.db', '/app/data/hp1.db', '/app/data/app.db']:
    if os.path.exists(path):
        print(f"Found DB: {path}")
        conn = sqlite3.connect(path)
        
        rows = conn.execute(
            "SELECT id, label FROM operations WHERE status='running'"
        ).fetchall()
        print(f"Stuck operations: {len(rows)}")
        for r in rows[:5]:
            print(f"  {r[0][:8]} | {str(r[1])[:40]}")
        
        cutoff = (datetime.datetime.utcnow() - datetime.timedelta(minutes=10)).isoformat()
        conn.execute(
            "UPDATE operations SET status='stopped', completed_at=? WHERE status='running' AND started_at < ?",
            (datetime.datetime.utcnow().isoformat(), cutoff)
        )
        conn.commit()
        print(f"Cleaned up {conn.total_changes} operations")
        conn.close()
        break
else:
    print("DB not found at expected paths — check with: find /app/data -name '*.db'")
PYEOF
```

### Verify
```bash
curl -s "http://192.168.199.10:8000/api/logs/operations" | \
  python3 -c "
import sys,json; d=json.load(sys.stdin)
by_s={}
for o in d.get('operations',[]): by_s[o['status']] = by_s.get(o['status'],0)+1
print(by_s)
"
# Expected: {"stopped": 14} or similar — zero "running"
```

---

## Rebuild schedule
```
Step 1: No rebuild (impl-scout — find files)
Rebuild 1: Steps 2+3 (completion write + stop handler)
  ~3min downtime
  Verify: run task → check operations table → success_rate > 0

Step 4: No rebuild (docker exec DB cleanup)
  Verify: zero 'running' operations
```

## Session plan
**Session A**: impl-scout → implement Steps 2+3 → one rebuild → verify  
**Session B**: Step 4 docker exec cleanup → verify → `/commit`
