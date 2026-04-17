"""
pbs_last_backup(vm_id) — return freshest successful backup for a Proxmox VM/CT.

Reads from infra_inventory rows written by the PBS collector (platform='pbs_backup').
Sync-only, no external calls — safe for observe-agent allowlist.
"""
import logging
import time

log = logging.getLogger(__name__)


def pbs_last_backup(vm_id) -> dict:
    """Return the freshest backup for a VMID.

    vm_id accepts: numeric VMID ("120"), "qemu/120", or "lxc/9221".
    Returns {status: 'PASS'|'FAIL'|'UNKNOWN', age_hours, last_success_ts, datastore, entity_id}.
    PASS when most recent backup is < 25h old, FAIL when older, UNKNOWN when missing.
    """
    try:
        vid = str(vm_id).replace("qemu/", "").replace("lxc/", "").strip()
        if not vid:
            return {"status": "UNKNOWN", "reason": "empty vm_id"}

        from api.db.infra_inventory import list_inventory
        rows = list_inventory(platform="pbs_backup") or []
        hits = []
        for r in rows:
            meta = r.get("meta") or {}
            if str(meta.get("vmid", "")) == vid:
                hits.append(r)

        if not hits:
            return {"status": "UNKNOWN", "reason": "no pbs backup found for vmid"}

        best = max(hits, key=lambda e: (e.get("meta") or {}).get("last_backup_ts", 0))
        meta = best.get("meta") or {}
        ts = int(meta.get("last_backup_ts", 0) or 0)
        if not ts:
            return {"status": "UNKNOWN", "reason": "no timestamp"}

        age_h = (time.time() - ts) / 3600
        return {
            "status": "PASS" if age_h < 25 else "FAIL",
            "age_hours": round(age_h, 1),
            "last_success_ts": ts,
            "datastore": meta.get("datastore"),
            "backup_type": meta.get("backup_type"),
            "entity_id": best.get("connection_id"),
        }
    except Exception as e:
        log.debug("pbs_last_backup failed: %s", e)
        return {"status": "UNKNOWN", "reason": f"lookup error: {str(e)[:80]}"}
