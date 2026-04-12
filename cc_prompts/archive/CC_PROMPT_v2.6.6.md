# CC PROMPT — v2.6.6 — PBS snapshot count per datastore + debug endpoint fix

## Two changes, one commit.

---

## Fix 1 — api/routers/status.py: stale debug path

File: `api/routers/status.py` — `collector_debug()` function

The PBS debug endpoint tests `/nodes/localhost/tasks` which doesn't exist on PBS.
The correct path (fixed in the collector in an earlier build) is `/system/tasks`.

```python
# Before:
paths_to_test = (
    ["/version", "/config/datastore", "/admin/datastore", "/nodes/localhost/tasks"]
    if component == "pbs"
    else ["/version", "/nodes"]
)

# After:
paths_to_test = (
    ["/version", "/config/datastore", "/system/tasks"]
    if component == "pbs"
    else ["/version", "/nodes"]
)
```

Note: `/admin/datastore` without a store name returns 404 on most PBS versions — removed it too.
The useful paths to debug are `/version` (auth check), `/config/datastore` (list stores), and `/system/tasks` (recent task history).

---

## Fix 2 — api/collectors/pbs.py: add snapshot count per datastore

File: `api/collectors/pbs.py` — `_collect_datastores()` function

The PBS API exposes `/api2/json/admin/datastore/{store}/groups` which returns backup
groups. Summing `snap-count` across all groups gives the total snapshot count for a
datastore.

### Update the `result.append(...)` block in `_collect_datastores()` to add `snapshot_count`:

```python
def _collect_datastores(base: str, headers: dict) -> list:
    """Fetch all datastores with capacity, scan data, and snapshot counts."""
    try:
        r = httpx.get(f"{base}/config/datastore", headers=headers, verify=False, timeout=10)
        r.raise_for_status()
        stores = r.json().get("data", [])
    except Exception as e:
        log.debug("PBS datastore list failed: %s", e)
        return []

    result = []
    for ds in stores:
        name = ds.get("store", ds.get("name", "unknown"))

        # Usage stats
        try:
            sr = httpx.get(f"{base}/admin/datastore/{name}/status",
                           headers=headers, verify=False, timeout=8)
            usage = sr.json().get("data", {}) if sr.status_code == 200 else {}
        except Exception:
            usage = {}

        total = usage.get("total", 0)
        used = usage.get("used", 0)
        pct = round(used / total * 100, 1) if total > 0 else 0

        # Snapshot count — sum snap-count across all backup groups
        snapshot_count = None
        try:
            gr = httpx.get(f"{base}/admin/datastore/{name}/groups",
                           headers=headers, verify=False, timeout=10)
            if gr.status_code == 200:
                groups = gr.json().get("data", [])
                snapshot_count = sum(int(g.get("backup-count", g.get("snap-count", 0)) or 0)
                                     for g in groups)
        except Exception as e:
            log.debug("PBS snapshot count for %s failed: %s", name, e)

        result.append({
            "name": name,
            "usage_pct": pct,
            "total_gb": round(total / (1024 ** 3), 1) if total else 0,
            "used_gb": round(used / (1024 ** 3), 1) if used else 0,
            "gc_status": usage.get("gc-status", {}).get("state", "") if isinstance(usage.get("gc-status"), dict) else str(usage.get("gc-status", "")),
            "snapshot_count": snapshot_count,   # NEW — None if unavailable
        })
    return result
```

Note: PBS uses `backup-count` in some versions, `snap-count` in others — the `or` fallback handles both.

---

## Fix 3 — gui/src/components/ServiceCards.jsx: show snapshot count in PBS InfraCard

File: `gui/src/components/ServiceCards.jsx` — PBS datastores section, expanded InfraCard content.

Find the PBS InfraCard `expanded` prop. Currently the tasks block looks like this:

```jsx
{tasks.recent_count != null && (
  <div style={{ marginTop: 4, paddingTop: 4, borderTop: '1px solid var(--bg-3)' }}>
    Tasks (last 20): <span style={{ color: 'var(--green)' }}>{tasks.recent_count - (tasks.failed_count || 0)} OK</span>
    {tasks.failed_count > 0 && <span style={{ color: 'var(--red)', marginLeft: 6 }}>{tasks.failed_count} failed</span>}
  </div>
)}
```

Add the snapshot count line immediately before the tasks block:

```jsx
{ds.snapshot_count != null && (
  <div>Snapshots: <span style={{ color: 'var(--text-1)' }}>{ds.snapshot_count}</span></div>
)}
{tasks.recent_count != null && (
  <div style={{ marginTop: 4, paddingTop: 4, borderTop: '1px solid var(--bg-3)' }}>
    Tasks (last 20): <span style={{ color: 'var(--green)' }}>{tasks.recent_count - (tasks.failed_count || 0)} OK</span>
    {tasks.failed_count > 0 && <span style={{ color: 'var(--red)', marginLeft: 6 }}>{tasks.failed_count} failed</span>}
  </div>
)}
```

---

## Commit & deploy

```bash
git add -A
git commit -m "fix(pbs): snapshot count per datastore + debug endpoint path

- status.py: fix PBS debug endpoint paths (remove /admin/datastore, fix
  /nodes/localhost/tasks → /system/tasks)
- pbs.py: _collect_datastores() fetches snapshot count via /admin/datastore/{name}/groups
  (sums backup-count/snap-count across all groups; None if endpoint unavailable)
- ServiceCards.jsx: PBS InfraCard expanded view shows snapshot count above task summary"
git push origin main
# After CI green:
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env \
  up -d hp1_agent
```
