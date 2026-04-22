# CC PROMPT — v2.39.0 — feat(facts): external_services + vm_hosts fact extractors

## What this does

Fact coverage gap — external_services and vm_hosts are the two highest-traffic
collectors but neither writes to known_facts. Every probe result is discarded
after the dashboard updates. Preflight and external AI prerun context get zero
data for FortiGate, UniFi, TrueNAS, Proxmox, etc.

Two-part change:
1. Add `extract_facts_from_external_services_snapshot()` in `api/facts/extractors.py`
2. Wire it into `api/collectors/external_services.py` (same pattern as kafka)
3. Add `extract_facts_from_vm_hosts_snapshot()` in `api/facts/extractors.py`
4. Wire it into `api/collectors/vm_hosts.py`

Version bump: 2.38.9 → 2.39.0.

---

## Change 1 — `api/facts/extractors.py` — add two new extractors at end of file

Append after the last function (`extract_facts_from_fortiswitch_snapshot`):

```python
def extract_facts_from_external_services_snapshot(snapshot: dict) -> list[dict]:
    """external_services collector snapshot → fact list.

    Snapshot shape: {health, services: [{name, slug, service_type, host_port,
    reachable, latency_ms, dot, problem, connection_id, entity_id}]}

    Writes one fact per probed service: reachability, latency, status, host.
    Key format: prod.svc.{slug}.{attr}
    """
    facts: list[dict] = []
    if not isinstance(snapshot, dict):
        return facts
    for svc in snapshot.get("services", []) or []:
        slug = svc.get("slug") or svc.get("service_type")
        if not slug:
            continue
        fkey_base = f"prod.svc.{slug}"
        md = {"connection_id": svc.get("connection_id"), "name": svc.get("name")}
        _add(facts, f"{fkey_base}.reachable", "external_services_collector",
             bool(svc.get("reachable", False)), md)
        _add(facts, f"{fkey_base}.status", "external_services_collector",
             svc.get("dot", "grey"), md)
        if svc.get("latency_ms") is not None:
            _add(facts, f"{fkey_base}.latency_ms", "external_services_collector",
                 svc["latency_ms"], md)
        if svc.get("problem"):
            _add(facts, f"{fkey_base}.problem", "external_services_collector",
                 svc["problem"], md)
        if svc.get("host_port"):
            _add(facts, f"{fkey_base}.host_port", "external_services_collector",
                 svc["host_port"], md)
    return facts


def extract_facts_from_vm_hosts_snapshot(snapshot: dict) -> list[dict]:
    """vm_hosts collector snapshot → fact list.

    Snapshot shape: {health, vms: [{id, label, host, hostname, os, kernel,
    uptime_secs, load_1, load_5, load_15, mem_pct, disks, services,
    docker_version, dot, problem}]}

    Writes per-host: reachability (dot!=red), IP, hostname, OS, load,
    memory pct, disk max pct, docker version.
    Key format: prod.vm_host.{label}.{attr}
    """
    facts: list[dict] = []
    if not isinstance(snapshot, dict):
        return facts
    for vm in snapshot.get("vms", []) or []:
        label = vm.get("label") or vm.get("id")
        if not label:
            continue
        fkey_base = f"prod.vm_host.{label}"
        md = {"host": vm.get("host")}
        # Reachability derived from dot
        reachable = vm.get("dot", "grey") in ("green", "amber")
        _add(facts, f"{fkey_base}.ssh_reachable", "vm_hosts_collector",
             reachable, md)
        _add(facts, f"{fkey_base}.status", "vm_hosts_collector",
             vm.get("dot", "grey"), md)
        if vm.get("problem"):
            _add(facts, f"{fkey_base}.problem", "vm_hosts_collector",
                 vm["problem"], md)
        if vm.get("host"):
            _add(facts, f"{fkey_base}.ip", "vm_hosts_collector",
                 vm["host"], md)
        if vm.get("hostname"):
            _add(facts, f"{fkey_base}.hostname", "vm_hosts_collector",
                 vm["hostname"], md)
        if vm.get("os"):
            _add(facts, f"{fkey_base}.os", "vm_hosts_collector",
                 vm["os"], md)
        if vm.get("load_1") is not None:
            _add(facts, f"{fkey_base}.load_1", "vm_hosts_collector",
                 vm["load_1"], md)
        if vm.get("mem_pct") is not None:
            _add(facts, f"{fkey_base}.mem_pct", "vm_hosts_collector",
                 vm["mem_pct"], md)
        # Max disk usage across all disks
        disks = vm.get("disks") or []
        if disks:
            max_disk = max((d.get("usage_pct", 0) for d in disks
                           if isinstance(d, dict)), default=None)
            if max_disk is not None:
                _add(facts, f"{fkey_base}.max_disk_pct", "vm_hosts_collector",
                     max_disk, md)
        if vm.get("docker_version"):
            _add(facts, f"{fkey_base}.docker_version", "vm_hosts_collector",
                 vm["docker_version"], md)
        # Per-service systemd status (services is list of {name, status})
        for svc in vm.get("services") or []:
            sname = svc.get("name") if isinstance(svc, dict) else None
            sstatus = svc.get("status") if isinstance(svc, dict) else None
            if sname and sstatus:
                _add(facts, f"{fkey_base}.service.{sname}", "vm_hosts_collector",
                     sstatus, md)
    return facts
```

---

## Change 2 — `api/collectors/external_services.py` — wire extractor after poll

Locate the `_collect_sync` method. It ends with:

```python
        has_error = any(s["dot"] == "red" for s in cards if s["dot"] != "grey")
        has_warn = any(s["dot"] == "amber" for s in cards if s["dot"] != "grey")
        health = "critical" if has_error else "degraded" if has_warn else "healthy"
        return {"health": health, "services": cards}
```

Replace with:

```python
        has_error = any(s["dot"] == "red" for s in cards if s["dot"] != "grey")
        has_warn = any(s["dot"] == "amber" for s in cards if s["dot"] != "grey")
        health = "critical" if has_error else "degraded" if has_warn else "healthy"
        snapshot = {"health": health, "services": cards}

        # v2.39.0: best-effort fact extraction
        try:
            from api.facts.extractors import extract_facts_from_external_services_snapshot
            from api.db.known_facts import batch_upsert_facts
            from api.metrics import FACTS_UPSERTED_COUNTER
            facts = extract_facts_from_external_services_snapshot(snapshot)
            result = batch_upsert_facts(facts, actor="collector")
            for action, count in result.items():
                if count > 0:
                    FACTS_UPSERTED_COUNTER.labels(
                        source="external_services_collector", action=action
                    ).inc(count)
        except Exception as _fe:
            log.warning("Fact extraction failed for external_services: %s", _fe)

        return snapshot
```

---

## Change 3 — `api/collectors/vm_hosts.py` — wire extractor after _collect_sync

Locate the `_collect_sync` method. It ends with:

```python
        health = "healthy" if red == 0 else ("degraded" if ok > 0 else "error")
        return {"health": health, "vms": vms, "total": total, "ok": ok, "issues": red}
```

Replace with:

```python
        health = "healthy" if red == 0 else ("degraded" if ok > 0 else "error")
        snapshot = {"health": health, "vms": vms, "total": total, "ok": ok, "issues": red}

        # v2.39.0: best-effort fact extraction
        try:
            from api.facts.extractors import extract_facts_from_vm_hosts_snapshot
            from api.db.known_facts import batch_upsert_facts
            from api.metrics import FACTS_UPSERTED_COUNTER
            facts = extract_facts_from_vm_hosts_snapshot(snapshot)
            result = batch_upsert_facts(facts, actor="collector")
            for action, count in result.items():
                if count > 0:
                    FACTS_UPSERTED_COUNTER.labels(
                        source="vm_hosts_collector", action=action
                    ).inc(count)
        except Exception as _fe:
            log.warning("Fact extraction failed for vm_hosts: %s", _fe)

        return snapshot
```

---

## Version bump

Update `VERSION` file: `2.38.9` → `2.39.0`

---

## Commit

```
git add -A
git commit -m "feat(facts): v2.39.0 external_services + vm_hosts fact extractors wired"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
