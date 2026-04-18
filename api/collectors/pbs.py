"""
Proxmox Backup Server collector.
Polls datastore usage and recent task health from PBS API.
Reads connection from DB (platform='pbs'); falls back to env vars PBS_HOST / PBS_USER /
PBS_TOKEN_NAME / PBS_TOKEN_SECRET.
"""
import asyncio
import logging
import os
import time

import httpx

from api.collectors.base import BaseCollector

log = logging.getLogger(__name__)


class PBSCollector(BaseCollector):
    component = "pbs"
    platforms = ["pbs"]
    interval = int(os.environ.get("PBS_POLL_INTERVAL", "60"))

    def __init__(self):
        super().__init__()

    def mock(self) -> dict:
        return {
            "health": "healthy",
            "connection_label": "mock-pbs",
            "connection_id": "mock-pbs-id",
            "datastores": [
                {
                    "name": "mock-store",
                    "usage_pct": 42.0,
                    "total_gb": 2000.0,
                    "used_gb": 840.0,
                    "gc_status": "ok",
                },
            ],
            "tasks": {
                "recent_count": 10,
                "failed_count": 0,
                "last_failed": None,
            },
        }

    def to_entities(self, state: dict) -> list:
        from api.collectors.base import Entity, PLATFORM_SECTION

        label = state.get("connection_label", "pbs")
        health_map = {
            "healthy": "healthy",
            "degraded": "degraded",
            "critical": "error",
            "error": "error",
            "unconfigured": "unknown",
        }
        status = health_map.get(state.get("health", "unknown"), "unknown")
        last_error = state.get("error") if status == "error" else None

        datastores = state.get("datastores", [])
        entities = []

        for ds in datastores:
            ds_name = ds.get("name", "unknown")
            pct = ds.get("usage_pct", 0)
            ds_status = "error" if pct > 95 else "degraded" if pct > 85 else status
            entities.append(Entity(
                id=f"pbs:{label}:datastore:{ds_name}",
                label=f"{label}/{ds_name}",
                component=self.component,
                platform="pbs",
                section="STORAGE",
                status=ds_status,
                last_error=last_error,
                metadata={
                    "usage_pct": pct,
                    "total_gb": ds.get("total_gb"),
                    "used_gb": ds.get("used_gb"),
                    "gc_status": ds.get("gc_status", ""),
                    "connection": label,
                },
            ))

        if not entities:
            entities.append(Entity(
                id=f"pbs:{label}",
                label=label,
                component=self.component,
                platform="pbs",
                section="STORAGE",
                status=status,
                last_error=last_error,
                metadata={"connection": label},
            ))

        return entities

    async def poll(self) -> dict:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict:
        from api.connections import get_all_connections_for_platform
        conns = get_all_connections_for_platform("pbs")

        # Env-var fallback for backward compat
        if not conns:
            host = os.environ.get("PBS_HOST", "")
            if host:
                conns = [{
                    "host": host,
                    "port": int(os.environ.get("PBS_PORT", "8007")),
                    "label": host,
                    "id": "",
                    "credentials": {
                        "user": os.environ.get("PBS_USER", "root@pam"),
                        "token_name": os.environ.get("PBS_TOKEN_NAME", ""),
                        "secret": os.environ.get("PBS_TOKEN_SECRET", ""),
                    },
                }]

        if not conns:
            return {"health": "unconfigured", "datastores": [], "tasks": {},
                    "message": "No PBS connection configured"}

        # Poll each connection separately, aggregate results
        all_results = []
        for conn in conns:
            result = self._poll_one_conn(conn)
            all_results.append(result)

        # Merge all datastores and tasks
        merged_datastores = []
        merged_tasks = {"recent_count": 0, "failed_count": 0, "last_failed": None}
        worst_health = "healthy"
        health_priority = {"healthy": 0, "degraded": 1, "critical": 2, "error": 3}

        for r in all_results:
            merged_datastores.extend(r.get("datastores", []))
            rt = r.get("tasks", {})
            merged_tasks["recent_count"] += rt.get("recent_count", 0)
            merged_tasks["failed_count"] += rt.get("failed_count", 0)
            if rt.get("last_failed") and not merged_tasks["last_failed"]:
                merged_tasks["last_failed"] = rt["last_failed"]
            h = r.get("health", "error")
            if health_priority.get(h, 3) > health_priority.get(worst_health, 0):
                worst_health = h

        # Collect last_backups from per-connection results so the fact extractor
        # can flatten them into prod.pbs.backup.* keys.
        merged_last_backups = []
        for r in all_results:
            merged_last_backups.extend(r.get("last_backups") or [])

        snapshot = {
            "health": worst_health,
            "datastores": merged_datastores,
            "tasks": merged_tasks,
            "connection_count": len(conns),
            "last_backups": merged_last_backups,
        }
        # v2.35.0: best-effort fact extraction
        try:
            from api.facts.extractors import extract_facts_from_pbs_snapshot
            from api.db.known_facts import batch_upsert_facts
            from api.metrics import FACTS_UPSERTED_COUNTER
            facts = extract_facts_from_pbs_snapshot(snapshot)
            result = batch_upsert_facts(facts, actor="collector")
            for action, count in result.items():
                if count > 0:
                    FACTS_UPSERTED_COUNTER.labels(
                        source="pbs_collector", action=action
                    ).inc(count)
        except Exception as _fe:
            log.warning("Fact extraction failed for pbs: %s", _fe)
        return snapshot

    def _poll_one_conn(self, conn: dict) -> dict:
        host = conn.get("host", "")
        creds = conn.get("credentials", {}) if isinstance(conn.get("credentials"), dict) else {}
        user = creds.get("user", "")
        token_name = creds.get("token_name", "")
        secret = creds.get("secret", "")
        port = conn.get("port") or 8007
        conn_label = conn.get("label", host)
        conn_id = conn.get("id", "")

        if not (user and token_name and secret):
            return {"health": "error", "datastores": [], "tasks": {},
                    "error": "PBS credentials incomplete — need user, token_name, secret",
                    "connection_label": conn_label, "connection_id": conn_id}

        headers = {"Authorization": f"PBSAPIToken={user}!{token_name}:{secret}"}
        base = f"https://{host}:{port}/api2/json"

        try:
            t0 = time.monotonic()
            r = httpx.get(f"{base}/version", headers=headers, verify=False, timeout=8)
            latency_ms = round((time.monotonic() - t0) * 1000)
            if r.status_code == 401:
                return {"health": "error", "datastores": [], "tasks": {},
                        "error": "PBS auth failed — check token credentials",
                        "connection_label": conn_label, "connection_id": conn_id}
            r.raise_for_status()

            datastores = _collect_datastores(base, headers)
            # Stamp entity_id using this connection's label
            for ds in datastores:
                ds["entity_id"] = f"pbs:{conn_label}:datastore:{ds['name']}"
            tasks = _collect_tasks(base, headers)

            # Per-VM/CT last successful backup timestamps across all datastores
            last_backups = {}
            for ds in datastores:
                ds_name = ds.get("name")
                if not ds_name:
                    continue
                snaps = _fetch_group_snapshots(base, headers, ds_name)
                for (btype, bid), ts in snaps.items():
                    prev = last_backups.get((btype, bid), (0, ""))
                    if ts > prev[0]:
                        last_backups[(btype, bid)] = (ts, ds_name)
            # Record cross-reference rows per VM/CT so pbs_last_backup() can resolve them
            try:
                from api.db.infra_inventory import write_cross_reference
                for (btype, bid), (ts, ds_name) in last_backups.items():
                    write_cross_reference(
                        connection_id=f"pbs:{conn_label}:{btype}/{bid}",
                        platform="pbs_backup",
                        label=f"{btype}/{bid}",
                        hostname="",
                        ips=[],
                        aliases=[str(bid)],
                        meta={
                            "last_backup_ts": ts,
                            "datastore": ds_name,
                            "vmid": str(bid),
                            "backup_type": btype,
                            "pbs_connection": conn_label,
                        },
                    )
            except Exception as e:
                log.debug("PBS cross-reference write failed: %s", e)

            has_full = any(ds["usage_pct"] > 95 for ds in datastores)
            has_warn = any(ds["usage_pct"] > 85 for ds in datastores)
            has_task_failures = tasks.get("failed_count", 0) > 0

            if has_full:
                health = "critical"
            elif has_warn or has_task_failures:
                health = "degraded"
            else:
                health = "healthy"

            return {
                "health": health,
                "datastores": datastores,
                "tasks": tasks,
                "latency_ms": latency_ms,
                "connection_label": conn_label,
                "connection_id": conn_id,
                "last_backups": [
                    {
                        "backup_type": btype,
                        "backup_id": bid,
                        "last_backup_ts": ts,
                        "datastore": ds_name,
                    }
                    for (btype, bid), (ts, ds_name) in last_backups.items()
                ],
            }

        except httpx.HTTPStatusError as e:
            log.warning("PBSCollector HTTP error %s: %s", conn_label, e)
            return {"health": "error", "datastores": [], "tasks": {},
                    "error": f"HTTP {e.response.status_code}",
                    "connection_label": conn_label, "connection_id": conn_id}
        except Exception as e:
            log.error("PBSCollector error %s: %s", conn_label, e)
            return {"health": "error", "datastores": [], "tasks": {},
                    "error": f"Connection failed: {str(e)[:80]}",
                    "connection_label": conn_label, "connection_id": conn_id}


def _collect_datastores(base: str, headers: dict) -> list:
    """Fetch all datastores and their usage stats."""
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
            "snapshot_count": snapshot_count,
        })
    return result


def _fetch_group_snapshots(base: str, headers: dict, datastore: str) -> dict:
    """Return {(backup_type, backup_id): last_success_ts_unix} for a datastore.

    Skips snapshots whose verification state is not 'ok' when present.
    Hits /admin/datastore/{store}/snapshots.
    """
    try:
        r = httpx.get(f"{base}/admin/datastore/{datastore}/snapshots",
                      headers=headers, verify=False, timeout=10)
    except Exception as e:
        log.debug("PBS snapshots fetch for %s failed: %s", datastore, e)
        return {}
    if r.status_code != 200:
        return {}
    out: dict = {}
    for snap in r.json().get("data", []):
        btype = snap.get("backup-type")
        bid = str(snap.get("backup-id"))
        if not btype or not bid:
            continue
        ts = int(snap.get("backup-time") or 0)
        verification = snap.get("verification")
        if isinstance(verification, dict) and verification.get("state") not in (None, "ok"):
            continue  # skip failed verifications
        prev = out.get((btype, bid), 0)
        if ts > prev:
            out[(btype, bid)] = ts
    return out


def _collect_tasks(base: str, headers: dict) -> dict:
    """Fetch recent tasks and count failures."""
    try:
        r = httpx.get(f"{base}/system/tasks", headers=headers,
                      verify=False, timeout=10, params={"limit": 20})
        r.raise_for_status()
        tasks = r.json().get("data", [])
    except Exception as e:
        log.debug("PBS task list failed: %s", e)
        return {"recent_count": 0, "failed_count": 0, "last_failed": None}

    failed = [t for t in tasks if t.get("status") and t["status"] != "OK"]
    last_failed = failed[0] if failed else None

    return {
        "recent_count": len(tasks),
        "failed_count": len(failed),
        "last_failed": {
            "type": last_failed.get("worker_type", ""),
            "status": last_failed.get("status", ""),
            "starttime": last_failed.get("starttime", 0),
        } if last_failed else None,
    }
