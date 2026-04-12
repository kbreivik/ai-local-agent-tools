# CC PROMPT — v2.11.1 — PBS collector implementation

## What this does

PBS (Proxmox Backup Server) has a connection form and connection type in the DB
but the collector is a placeholder that returns unconfigured/empty data.

This implements a real PBS collector using the PBS API (same pattern as proxmox_vms.py):
- Authenticates with user + token_name + secret (PBSAPIToken format)
- Fetches datastores with usage stats
- Fetches recent tasks (backup jobs)
- Returns per-datastore cards with usage bars

Version bump: 2.11.0 → 2.11.1 (new collector, x.x.1)

---

## Change 1 — api/collectors/pbs.py (create or replace placeholder)

```python
"""
PBSCollector — polls Proxmox Backup Server for datastore usage and task history.

Auth: PBSAPIToken={user}!{token_name}:{secret} header
API base: https://{host}:{port}/api2/json/
"""
import asyncio
import logging
import os
from datetime import datetime, timezone

import httpx

from api.collectors.base import BaseCollector

log = logging.getLogger(__name__)


class PBSCollector(BaseCollector):
    component = "pbs"
    platforms = ["pbs"]
    interval = int(os.environ.get("PBS_POLL_INTERVAL", "60"))

    def __init__(self):
        super().__init__()

    async def poll(self) -> dict:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict:
        from api.connections import get_all_connections_for_platform
        conns = get_all_connections_for_platform("pbs")
        if not conns:
            return {"health": "unconfigured", "datastores": [],
                    "message": "No PBS connection configured"}

        all_datastores = []
        errors = []

        for conn in conns:
            try:
                result = self._poll_one(conn)
                all_datastores.extend(result.get("datastores", []))
            except Exception as e:
                label = conn.get("label", conn.get("host", "?"))
                log.warning("PBS poll failed for %s: %s", label, e)
                errors.append(f"{label}: {str(e)[:80]}")

        if not all_datastores and errors:
            return {"health": "error", "datastores": [],
                    "error": "; ".join(errors)}

        has_error = any(d.get("dot") == "red" for d in all_datastores)
        has_warn  = any(d.get("dot") == "amber" for d in all_datastores)
        health = "error" if has_error else "degraded" if has_warn else "healthy"
        return {"health": health, "datastores": all_datastores,
                "datastore_count": len(all_datastores)}

    def _poll_one(self, conn: dict) -> dict:
        host  = conn.get("host", "")
        port  = conn.get("port") or 8007
        creds = conn.get("credentials", {})
        if isinstance(creds, str):
            import json
            try: creds = json.loads(creds)
            except Exception: creds = {}

        user       = creds.get("user", "")
        token_name = creds.get("token_name", "")
        secret     = creds.get("secret", "")
        label      = conn.get("label", f"{host}:{port}")
        conn_id    = str(conn.get("id", ""))

        if not (user and token_name and secret):
            return {"health": "error", "datastores": [],
                    "error": f"{label}: missing user/token_name/secret credentials"}

        auth_header = f"PBSAPIToken={user}!{token_name}:{secret}"
        base_url = f"https://{host}:{port}/api2/json"
        headers = {"Authorization": auth_header}

        client = httpx.Client(verify=False, timeout=15, headers=headers)
        try:
            # Fetch datastores
            r = client.get(f"{base_url}/admin/datastore")
            r.raise_for_status()
            raw_stores = r.json().get("data", [])

            datastores = []
            for ds in raw_stores:
                name = ds.get("store", "unknown")

                # Fetch per-datastore usage
                try:
                    u = client.get(f"{base_url}/admin/datastore/{name}/status")
                    usage = u.json().get("data", {})
                except Exception:
                    usage = {}

                total   = usage.get("total", 0)
                used    = usage.get("used", 0)
                avail   = usage.get("avail", 0)
                pct     = round((used / total * 100) if total else 0)

                # Fetch recent tasks for this datastore
                try:
                    t = client.get(f"{base_url}/nodes/localhost/tasks",
                                   params={"store": name, "limit": 10})
                    tasks = t.json().get("data", [])
                except Exception:
                    tasks = []

                last_backup = None
                failed_tasks = 0
                for task in tasks:
                    if task.get("type") == "backup" and not last_backup:
                        ts = task.get("starttime")
                        if ts:
                            last_backup = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                    if task.get("status", "").startswith("FAILED"):
                        failed_tasks += 1

                dot = "red" if pct >= 90 or failed_tasks > 0 else \
                      "amber" if pct >= 80 else "green"

                datastores.append({
                    "connection_id":   conn_id,
                    "connection_label": label,
                    "name":            name,
                    "host":            host,
                    "total_bytes":     total,
                    "used_bytes":      used,
                    "avail_bytes":     avail,
                    "usage_pct":       pct,
                    "last_backup":     last_backup,
                    "failed_tasks":    failed_tasks,
                    "dot":             dot,
                    "problem":         f"{pct}% used" if pct >= 80 else
                                       f"{failed_tasks} failed task(s)" if failed_tasks else None,
                })

            return {"health": "healthy", "datastores": datastores}
        finally:
            client.close()

    def to_entities(self, state: dict) -> list:
        from api.collectors.base import Entity
        entities = []
        for ds in state.get("datastores", []):
            dot_to_status = {"green": "healthy", "amber": "degraded", "red": "error"}
            entities.append(Entity(
                id=f"pbs:{ds['connection_label']}:{ds['name']}",
                label=f"{ds['connection_label']}/{ds['name']}",
                component=self.component, platform="pbs", section="STORAGE",
                status=dot_to_status.get(ds.get("dot", "grey"), "unknown"),
                last_error=ds.get("problem"),
                metadata={
                    "usage_pct":   ds.get("usage_pct"),
                    "used_bytes":  ds.get("used_bytes"),
                    "total_bytes": ds.get("total_bytes"),
                    "last_backup": ds.get("last_backup"),
                    "failed_tasks": ds.get("failed_tasks", 0),
                    "connection":  ds.get("connection_label"),
                },
            ))
        return entities
```

---

## Change 2 — api/main.py — register PBSCollector

Find where other collectors are registered on startup (likely in the CollectorManager
init block). Add PBSCollector alongside the others:

```python
from api.collectors.pbs import PBSCollector
# Add to collector list:
PBSCollector(),
```

---

## Change 3 — api/routers/connections.py — trigger map

Verify that saving/deleting a `pbs` connection triggers both `pbs` and
`external_services` collectors. The trigger map should already have:

```python
"pbs": ["pbs", "external_services"],
```

If not, add it.

---

## Version bump

Update VERSION: `2.11.0` → `2.11.1`

---

## Commit

```bash
git add -A
git commit -m "feat(collector): v2.11.1 PBS collector implementation

- PBSCollector: polls PBS API with PBSAPIToken auth
- Fetches all datastores with usage % (total/used/avail bytes)
- Fetches recent tasks per datastore — flags failed backups
- Per-datastore Entity cards in STORAGE section
- Supports multiple PBS connections (get_all_connections_for_platform)
- dot: green <80%, amber 80-89%, red ≥90% or any failed tasks"
git push origin main
```
