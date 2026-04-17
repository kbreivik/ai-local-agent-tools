# CC PROMPT — v2.33.8 — verify_backup_job template + PBS last-success age

## What this does
Extends the PBS collector to capture `last_success_ts` per VM/CT, adds a
`pbs_last_backup(vm_id)` MCP tool, a `verify_backup_job` task template
(PASS/FAIL against an SLO), and a subtle freshness dot on VMCard.

Version bump: 2.33.7 → 2.33.8

## Change 1 — api/collectors/pbs.py — extract last_success_ts per VM/CT

The existing collector (v2.11.1) pulls datastore info. Extend it to also
enumerate group snapshots per datastore and record the most recent successful
backup per `(backup_type, backup_id)`.

Add/extend inside `_poll_one_conn`:

```python
async def _fetch_group_snapshots(self, client, datastore):
    """
    Return {(backup_type, backup_id): last_success_ts_unix} for a datastore.
    Hits /api2/json/admin/datastore/{store}/snapshots.
    """
    url = f"/api2/json/admin/datastore/{datastore}/snapshots"
    r = await client.get(url)
    if r.status_code != 200:
        return {}
    out = {}
    for snap in r.json().get("data", []):
        key = (snap.get("backup-type"), str(snap.get("backup-id")))
        ts = int(snap.get("backup-time") or 0)
        if snap.get("verification") and snap["verification"].get("state") != "ok":
            continue  # skip failed verifications
        prev = out.get(key, 0)
        if ts > prev:
            out[key] = ts
    return out
```

Merge the resulting map into the per-VM entity metadata as
`last_backup_ts` (unix seconds). In `to_entities()` emit it:

```python
for (btype, bid), ts in snapshots.items():
    entity_id = f"pbs:{conn['label']}:{btype}:{bid}"
    yield Entity(
        id=entity_id,
        platform="pbs",
        section="STORAGE",
        label=f"{btype}/{bid}",
        metadata={
            "last_backup_ts": ts,
            "age_hours": (time.time() - ts) / 3600,
            "datastore": datastore,
        },
    )
```

Also register a cross-reference so VMCard can look up its backup status by
matching `vmid` → `qemu/<vmid>` or `lxc/<vmid>`:

```python
# at end of collector cycle, write cross-reference row
from api.db.infra_inventory import write_cross_reference
for (btype, bid), ts in snapshots.items():
    write_cross_reference(
        ref_type="pbs_backup",
        ref_key=f"{btype}/{bid}",
        target_entity=f"proxmox:*:{bid}",   # fuzzy; resolver handles match
        metadata={"last_backup_ts": ts},
    )
```

## Change 2 — mcp_server/tools/pbs.py — new tool

```python
"""
pbs_last_backup(vm_id) — return freshest backup for a Proxmox VM/CT.
"""
import time
from api.db.infra_inventory import resolve_entity

def pbs_last_backup(vm_id: str | int) -> dict:
    """
    vm_id: numeric VMID, or "qemu/120", or "lxc/9221".
    Returns {status: 'PASS'|'FAIL'|'UNKNOWN', age_hours, last_success_ts, datastore?}
    """
    vid = str(vm_id).replace("qemu/", "").replace("lxc/", "")
    # search most recent pbs entity whose backup-id matches
    hits = resolve_entity(platform="pbs", match=f"/{vid}")
    if not hits:
        return {"status": "UNKNOWN", "reason": "no pbs backup found for vmid"}
    best = max(hits, key=lambda e: e["metadata"].get("last_backup_ts", 0))
    ts = best["metadata"].get("last_backup_ts", 0)
    if not ts:
        return {"status": "UNKNOWN", "reason": "no timestamp"}
    age_h = (time.time() - ts) / 3600
    return {
        "status": "PASS" if age_h < 25 else "FAIL",
        "age_hours": round(age_h, 1),
        "last_success_ts": ts,
        "datastore": best["metadata"].get("datastore"),
        "entity_id": best["id"],
    }
```

Register it in the MCP tool registry (observe-agent allowlist as read-only).

## Change 3 — api/agents/task_templates.py — verify_backup_job

Append:

```python
{
    "name": "verify_backup_job",
    "label": "Verify Backup Job",
    "group": "STORAGE",
    "agent_type": "observe",
    "inputs": [
        {"name": "vm_id", "label": "VM ID (e.g. 120 or qemu/120)", "required": True},
        {"name": "max_age_hours", "label": "Max age (h)", "default": 25, "type": "number"},
    ],
    "prompt_template": (
        "Call pbs_last_backup(vm_id={vm_id!r}). "
        "If status is PASS and age_hours <= {max_age_hours}, emit:\n"
        "  STATUS: PASS\n  VM: {vm_id}\n  AGE_HOURS: <n>\n  DATASTORE: <x>\n"
        "If status is FAIL or UNKNOWN or age_hours > {max_age_hours}, emit:\n"
        "  STATUS: FAIL\n  VM: {vm_id}\n  AGE_HOURS: <n>\n  REASON: <text>\n"
        "Do not call any other tool."
    ),
    "blast_radius": "none",
    "destructive": False,
}
```

## Change 4 — gui/src/components/ServiceCards.jsx — VMCard freshness dot

In `ProxmoxCardExpanded` (or collapsed card), add a small dot near the VM
title that shows backup freshness when metadata exposes it:

```jsx
{vm.metadata?.pbs_backup_age_hours != null && (
  <span
    title={`Last backup ${vm.metadata.pbs_backup_age_hours.toFixed(1)}h ago`}
    style={{
      display: 'inline-block', width: 6, height: 6, borderRadius: '50%',
      marginLeft: 6,
      background: vm.metadata.pbs_backup_age_hours > 25 ? 'var(--amber)' : 'var(--green)'
    }}
  />
)}
```

To populate `vm.metadata.pbs_backup_age_hours`, enrich the proxmox collector
or the dashboard summary endpoint to join against the PBS cross-reference
when building VM cards. Simplest path: in `api/routers/dashboard.py` where
VM cards are shaped, look up `pbs_last_backup(vmid)` and merge into metadata
(with an in-process 5-minute cache to avoid hammering).

## Change 5 — tests

```python
def test_pbs_last_backup_shape():
    from mcp_server.tools.pbs import pbs_last_backup
    # Should return a dict with 'status' key
    r = pbs_last_backup("nonexistent-99999")
    assert r["status"] in ("UNKNOWN", "FAIL")

def test_verify_backup_template():
    from api.agents.task_templates import TASK_TEMPLATES
    t = next(x for x in TASK_TEMPLATES if x["name"] == "verify_backup_job")
    assert t["agent_type"] == "observe"
    assert "pbs_last_backup" in t["prompt_template"]
```

## Version bump
Update `VERSION`: 2.33.7 → 2.33.8

## Commit
```
git add -A
git commit -m "feat(templates): v2.33.8 verify_backup_job + PBS last-success tracking"
git push origin main
```

## How to test after push
1. Redeploy.
2. Trigger a PBS poll → check entity_history for `pbs:*` rows with `last_backup_ts` metadata.
3. Agent panel → templates → STORAGE → verify_backup_job → enter a VMID that has a recent backup → expect PASS + age.
4. VMCard of that VMID shows a green dot; pick a VMID missing from PBS → amber dot.
