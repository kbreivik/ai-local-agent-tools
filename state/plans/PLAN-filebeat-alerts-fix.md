# Plan: filebeat-alerts-fix
Date: 2026-03-24 (revised after full GUI audit)
Status: complete

## Objective
1. Route `alert:*` writes away from MuninnDB → `/api/alerts/` (persistent, dismissable)
2. Feed filebeat stale events into the Live Logs stream (service=filebeat, level=warning)
3. Filter `alert:` engrams from Memory page default view
4. Add alert deduplication (30-min window)

## What already exists — don't re-build
- **Toast system**: already fires `alert:filebeat` as amber toast (top-right, live WebSocket)
- **`/api/alerts/` system**: `GET /api/alerts/recent`, `POST /api/alerts/{id}/dismiss`, `POST /api/alerts/dismiss-all` — backend exists, just unused
- **Live Logs page**: service/level/keyword filters, WebSocket stream — ideal target for filebeat events
- **Memory page**: shows engrams with tabs (recent/search/activate/patterns/docs)

## Architecture after fix
```
Filebeat stale detected (every 60s)
  │
  ├─→ /api/alerts/ system  (persistent, dismissable, deduped 30min)
  │     └─→ Dashboard alerts widget
  │
  ├─→ Live Logs stream (service="filebeat", level="warning", one per event)
  │     └─→ Logs page → Live Logs tab → filterable by service=filebeat
  │
  └─→ MuninnDB  ← BLOCKED (alert: prefix never written here)
```

## Dependency map
```
Collector (writes alert) → currently → MuninnDB  [CHANGE THIS]
                        → should be → alerts system + log stream (NOT MuninnDB)

Memory page → currently shows all engrams → needs alert: filter toggle
```

No services currently depend on `alert:filebeat` being in MuninnDB.
The `pre_upgrade_check` step 5 queries MuninnDB for `outcome:` and `pattern:` only.

---

## Step 1 — Gate MuninnDB writes for alert: prefix  ✦ BACKEND
**Risk**: LOW — additive gate, no data removed, rollback = revert one function
**Rebuild**: YES (one rebuild at end of Steps 1+2 together)

### Locate first (impl-scout)
```bash
grep -rn "concept.*alert:\|alert:filebeat\|write.*engram\|muninndb\.store\|muninndb\.write" \
  /app/agent/ /app/mcp_server/ --include="*.py" -l
```

### Change
In the engram write function, add prefix gate:
```python
MUNINNDB_BLOCKED_PREFIXES = ("alert:",)

def write_engram(concept: str, content: str, tags: list = None):
    if any(concept.startswith(p) for p in MUNINNDB_BLOCKED_PREFIXES):
        _route_alert(concept, content, tags or [])
        return
    _muninndb_write(concept=concept, content=content, tags=tags or [])
```

### Verify
After rebuild, wait 2 minutes:
```bash
curl -s http://192.168.199.10:8000/api/memory/recent | \
  python3 -c "import sys,json; d=json.load(sys.stdin); \
  alerts=[e for e in d.get('engrams',[]) if e['concept'].startswith('alert:')]; \
  print(f'alert: engrams in MuninnDB: {len(alerts)} (expected 0)')"
```

---

## Step 2 — Route to /api/alerts/ with 30-min dedup  ✦ BACKEND (same rebuild as Step 1)
**Risk**: LOW — new write path, nothing removed

### Locate first (impl-scout)
```bash
find /app/api/routers -name "alert*" | xargs grep -n "def \|router\."
```

### Change A — alerts router: add internal create endpoint
```python
# api/routers/alerts.py — add internal create/update path
def create_or_update_alert(concept: str, content: str, tags: list, severity: str = "warning"):
    """Internal — called by write path, not exposed to users."""
    existing = _get_active_by_concept(concept)
    if existing:
        age_s = time.time() - existing.created_at
        if age_s < 1800:  # 30-min dedup window
            _update_content(existing.id, content)
            return
    _insert_alert(concept=concept, content=content, tags=tags, severity=severity)
```

### Change B — implement _route_alert in write path
```python
def _route_alert(concept: str, content: str, tags: list):
    from api.routers.alerts import create_or_update_alert
    severity = "error" if "error" in tags else "warning" if "warning" in tags else "info"
    create_or_update_alert(concept=concept, content=content, tags=tags, severity=severity)
```

### Verify
```bash
curl -s "http://192.168.199.10:8000/api/alerts/recent?limit=5" | python3 -m json.tool
# Expected: 1 alert:filebeat entry (not one per minute)
# Wait 2 more minutes — still 1 entry (dedup working, content updates with new age)
```

---

## Step 3 — Feed filebeat events into Live Logs stream  ✦ BACKEND (separate rebuild)
**Risk**: LOW — additive, Live Logs already streams via WebSocket
**Rebuild**: YES (one rebuild for this step alone)

### How Live Logs works (confirm with impl-scout first)
```bash
grep -rn "live_log\|log_stream\|websocket.*log\|broadcast.*log" \
  /app/api/ /app/agent/ --include="*.py" -l
```

### Change
When filebeat stale is detected, publish a log event to the live stream:
```python
def _route_alert(concept: str, content: str, tags: list):
    # 1. Alert system (Step 2)
    create_or_update_alert(...)
    
    # 2. Live log stream — so Logs page shows filebeat events
    _publish_log_event(
        service=concept.split(":")[1] if ":" in concept else "system",  # "filebeat"
        level="warning" if "warning" in tags else "error" if "error" in tags else "info",
        message=content,
        source="collector"
    )
```

### Verify
1. Open Logs page → Live Logs tab
2. Set service filter to "filebeat"
3. Within 60s a "warning" entry should appear
4. Test the keyword filter with "stale" — should find it

---

## Step 4 — Memory page: alert: filter toggle  ✦ FRONTEND (separate rebuild)
**Risk**: LOW — display only, no data changes
**Rebuild**: YES (one rebuild for Steps 4 alone, or batch with Step 5)

### Locate first (impl-scout)
```bash
grep -rn "memory/recent\|engrams\|concept" /app/gui/src --include="*.jsx" --include="*.vue" -l
```

### Change
In the Memory page component, add filter:
```jsx
const [showAlerts, setShowAlerts] = useState(false);
const alertCount = engrams.filter(e => e.concept?.startsWith('alert:')).length;
const visible = showAlerts ? engrams : engrams.filter(e => !e.concept?.startsWith('alert:'));

// In render, add toggle button near the tab bar:
{alertCount > 0 && (
  <button onClick={() => setShowAlerts(v => !v)} className="alert-toggle">
    {showAlerts ? 'Hide alerts' : `+${alertCount} suppressed alerts`}
  </button>
)}
```

### Verify
Memory page loads without `alert:filebeat` entries in default view.
Toggle shows them. Existing `doc:*`, `infra_status:*` engrams still visible.

---

## Step 5 — Outcome engram writer  ✦ BACKEND (separate rebuild)
**Risk**: LOW — additive, no existing logic changed
**Rebuild**: YES (one rebuild)

### Locate first (impl-scout)
```bash
grep -rn "operation.*complete\|status.*ok\|audit_log\|session.*end\|task.*finish" \
  /app/agent/ --include="*.py" -l
```

### Change
After every agent task completion, write `outcome:*`:
```python
def write_outcome(task: str, tools_used: list, result: str, steps: int):
    service = _extract_service(task)   # kafka / elastic / proxmox / swarm / generic
    task_type = _classify_task(task)   # health_check / upgrade / investigation
    write_engram(
        concept=f"outcome:{task_type}:{service}",
        content=f"Task: {task[:80]}. Tools: {','.join(tools_used[:5])}. Result: {result}. Steps: {steps}.",
        tags=["outcome", task_type, service, result]
    )
```

### Verify
Run a task via Commands panel, then:
```bash
curl -s "http://192.168.199.10:8000/api/memory/search?q=outcome" | python3 -m json.tool
# Expected: one outcome: engram per completed task
```

---

## Rebuild schedule (total ~8-10 min downtime, split across 3 rebuilds)

```
Rebuild 1: Steps 1+2 (MuninnDB gate + alert routing)
  Agent down ~3min. Verify before proceeding.

Rebuild 2: Step 3 (Live Logs stream)
  Agent down ~3min. Verify on Logs page before proceeding.

Rebuild 3: Steps 4+5 (Memory filter + outcome writer) — batch: same frontend+backend rebuild
  Agent down ~3min. Verify both.
```

## Session splits

**Session A** (find + implement Steps 1+2): `/prime` → spawn `impl-scout` → implement → rebuild → verify
**Session B** (Step 3 - Live Logs): `/prime` reads HANDOFF.md → `impl-scout` → implement → rebuild → verify  
**Session C** (Steps 4+5 - frontend + outcome): `/prime` → implement both → rebuild → verify → `/commit`
