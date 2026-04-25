# CC PROMPT — v2.45.30 — fix(facts): vm_hosts services dict iteration + diagnostic logging

## What this does
Closes the vm_hosts fact-coverage gap from the v2.45.17 audit
("writes 2 rows but appears broken — 0 vm_host facts seen in sample").

Two concrete bugs in `api/facts/extractors.py:extract_facts_from_vm_hosts_snapshot`:

1. **`services` shape mismatch.** The vm_hosts collector produces
   `services: {name: status}` (dict — see `_parse_poll_output`). The extractor
   iterates with `for svc in vm.get("services") or []`, treating each entry
   as a `{"name", "status"}` dict. `for k in dict` yields strings, so
   `isinstance(svc, dict)` is False, both `sname` and `sstatus` end up None,
   and every per-service fact is silently dropped via the `_add(None)` skip.

2. **No visibility on empty extraction.** When the collector poll produces
   garbage (SSH cred failure, parse error), the snapshot has populated
   `vms[]` but most fields are empty strings, so `_add()` skips most facts.
   Currently this fails silently — no log line, just zero facts written.
   Adds a single info-level log on every poll showing fact count vs vm count
   so the operator can see at a glance whether extraction is working.

Version bump: 2.45.29 → 2.45.30

---

## Context

`api/collectors/vm_hosts.py:_parse_poll_output` produces:

```python
services = {}
for sline in (sections.get("SERVICES") or []):
    if ":" in sline:
        svc, state = sline.split(":", 1)
        services[svc.strip()] = state.strip()
return {
    ...
    "services": services,   # dict, e.g. {"docker": "active", "ssh": "active"}
    ...
}
```

But `api/facts/extractors.py:extract_facts_from_vm_hosts_snapshot` does:

```python
for svc in vm.get("services") or []:
    sname = svc.get("name") if isinstance(svc, dict) else None
    sstatus = svc.get("status") if isinstance(svc, dict) else None
    if sname and sstatus:
        _add(facts, f"{fkey_base}.service.{sname}", "vm_hosts_collector",
             sstatus, md)
```

`for svc in dict` iterates over keys (strings), so the guard always fires
False and zero per-service facts are written.

---

## Change 1 — `api/facts/extractors.py` — handle dict shape

In `extract_facts_from_vm_hosts_snapshot`, find the existing service-loop
block:

```python
        # Per-service systemd status (services is list of {name, status})
        for svc in vm.get("services") or []:
            sname = svc.get("name") if isinstance(svc, dict) else None
            sstatus = svc.get("status") if isinstance(svc, dict) else None
            if sname and sstatus:
                _add(facts, f"{fkey_base}.service.{sname}", "vm_hosts_collector",
                     sstatus, md)
```

Replace with:

```python
        # Per-service systemd status. Collector emits a dict {name: status}
        # (api/collectors/vm_hosts.py:_parse_poll_output). Fall back to list
        # shape for forward-compat if a future collector version changes.
        services = vm.get("services") or {}
        if isinstance(services, dict):
            for sname, sstatus in services.items():
                if sname and sstatus:
                    _add(facts, f"{fkey_base}.service.{sname}",
                         "vm_hosts_collector", sstatus, md)
        elif isinstance(services, list):
            for svc in services:
                if not isinstance(svc, dict):
                    continue
                sname = svc.get("name")
                sstatus = svc.get("status")
                if sname and sstatus:
                    _add(facts, f"{fkey_base}.service.{sname}",
                         "vm_hosts_collector", sstatus, md)
```

---

## Change 2 — `api/collectors/vm_hosts.py` — info log on extraction result

Find the existing fact-extraction block at the end of `_collect_sync`:

```python
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
```

Replace with:

```python
        # v2.39.0 + v2.45.30: best-effort fact extraction with visibility.
        try:
            from api.facts.extractors import extract_facts_from_vm_hosts_snapshot
            from api.db.known_facts import batch_upsert_facts
            from api.metrics import FACTS_UPSERTED_COUNTER
            facts = extract_facts_from_vm_hosts_snapshot(snapshot)
            n_vms = len(snapshot.get("vms") or [])
            result = batch_upsert_facts(facts, actor="collector")
            for action, count in result.items():
                if count > 0:
                    FACTS_UPSERTED_COUNTER.labels(
                        source="vm_hosts_collector", action=action
                    ).inc(count)
            # v2.45.30: log at info level so operators can see whether the
            # collector is actually populating known_facts. Surfaces the gap
            # between "ran" and "wrote useful data".
            log.info(
                "vm_hosts: extracted %d facts from %d vms (insert=%d touch=%d "
                "change=%d conflict=%d noop=%d)",
                len(facts), n_vms,
                result.get("insert", 0), result.get("touch", 0),
                result.get("change", 0), result.get("conflict", 0),
                result.get("noop", 0),
            )
            if facts and n_vms and len(facts) < (n_vms * 2):
                # Pathological: some vms have so little data that fewer than
                # 2 facts per vm are emitted (we expect ~10 per healthy vm,
                # ~5 per failed-SSH vm). Likely a credential failure —
                # surface it once per poll.
                _failed = [
                    v.get("label") or v.get("host", "?")
                    for v in (snapshot.get("vms") or [])
                    if v.get("dot") == "red"
                ]
                if _failed:
                    log.warning(
                        "vm_hosts: %d/%d hosts in 'red' state — likely SSH "
                        "credential failure. Failed: %s",
                        len(_failed), n_vms, ", ".join(_failed[:5]),
                    )
        except Exception as _fe:
            log.warning("Fact extraction failed for vm_hosts: %s", _fe,
                        exc_info=True)
```

The `exc_info=True` addition turns silent failures into traceback dumps in
the logs — useful when the extractor itself crashes mid-iteration.

---

## Verify

```bash
python -m py_compile api/facts/extractors.py api/collectors/vm_hosts.py

# After deploy, watch container logs and wait for one poll cycle (60s):
docker logs hp1_agent --since 2m 2>&1 | grep -E "vm_hosts:" | tail -10
```

Expected log entries:
```
vm_hosts: extracted N facts from M vms (insert=X touch=Y ...)
```

For a healthy 7-VM setup, `N` should be roughly 70–100 (each VM produces
~10 host-level facts plus ~6 service facts). For a setup where 6/7 VMs are
failing SSH, expect ~40 facts (1 healthy * ~16 + 6 failed * ~5).

```sql
-- Check current state in known_facts:
SELECT COUNT(*), MAX(last_verified)
FROM known_facts_current
WHERE source = 'vm_hosts_collector';
```

Should show >0 rows and a recent `last_verified` (within the poll interval).

```sql
-- Verify per-service facts are now writing:
SELECT fact_key, fact_value FROM known_facts_current
WHERE fact_key LIKE 'prod.vm_host.%.service.%'
ORDER BY last_verified DESC LIMIT 20;
```

Pre-fix: 0 rows. Post-fix: should show docker/ssh/etc service status per host.

---

## Version bump

Update `VERSION`: `2.45.29` → `2.45.30`

---

## Commit

```
git add -A
git commit -m "fix(facts): v2.45.30 vm_hosts services dict iteration + extraction visibility logging"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

After deploy, the next poll (within ~60s) will populate
`prod.vm_host.{label}.service.{name}` rows for every reachable host, and
the info log will make any future regression visible at boot.
