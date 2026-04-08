# Plan: discover-environment-baseline
Date: 2026-03-24
Status: code-fix-done — discovery run needed on hp1-prod

## Objective
Seed the service catalog with real detected versions for all HP1 services.
Fix the discover_environment invocation in all docs (requires hosts_json param).

## Root cause
`discover_environment()` called with no args → fails with:
`"missing 1 required positional argument: 'hosts_json'"`

Tool signature:
```python
discover_environment(hosts_json: str)
# hosts_json = JSON array of {"address": "...", "port": ...} objects
```

## HP1 hosts to discover
```json
[
  {"address": "192.168.199.10"},
  {"address": "192.168.199.10", "port": 8006},
  {"address": "192.168.199.21"},
  {"address": "192.168.199.22"},
  {"address": "192.168.199.23"},
  {"address": "192.168.199.31"},
  {"address": "192.168.199.32"},
  {"address": "192.168.199.33"},
  {"address": "192.168.199.40"},
  {"address": "192.168.1.5", "port": 8006},
  {"address": "192.168.1.6", "port": 8006},
  {"address": "192.168.1.7", "port": 8006}
]
```

---

## Step 1 — Run discover_environment with correct hosts_json  (NO REBUILD)
**Risk**: NONE — read-only scan
**Rebuild**: NO

### Execute via agent Commands panel or API:
```
Task: Run discover_environment with hosts_json for all HP1 hosts:
[{"address":"192.168.199.10"},{"address":"192.168.199.10","port":8006},
 {"address":"192.168.199.21"},{"address":"192.168.199.22"},{"address":"192.168.199.23"},
 {"address":"192.168.199.31"},{"address":"192.168.199.32"},{"address":"192.168.199.33"},
 {"address":"192.168.199.40"},{"address":"192.168.1.5","port":8006}]
Report every service found with its version.
```

### Verify
```bash
curl -s http://192.168.199.10:8000/api/status/services | \
  python3 -c "import sys,json; d=json.load(sys.stdin); \
  [print(s['service_id'], s.get('detected_version','?')) for s in d.get('services',[])]"
# Expected: kafka, elasticsearch, docker, proxmox with detected versions
```

---

## Step 2 — Update service catalog with detected versions  (NO REBUILD)
**Risk**: NONE — catalog update only

For each discovered service, run `service_catalog_update`:
```
service_catalog_update(
    service_id="kafka",
    detected_version="3.x.x",   # from discover output
    known_latest="3.9.0",        # check Docker Hub
    notes="3 brokers on workers 199.31/32/33 ports 9092/9093/9094"
)
```

---

## Step 3 — Fix discover_environment docs (NO REBUILD)
**Risk**: NONE — docs only

Update `.claude/docs/agent-tools-reference.md`:
- discover_environment entry: add `hosts_json` param documentation
- Add the HP1 hosts_json template as a ready-to-use example

Update `.claude/agents/service-scout.md`:
- Add correct discover_environment invocation with HP1 hosts

---

## Step 4 — Ingest changelogs for discovered services  (NO REBUILD)
**Risk**: NONE — read/write to MuninnDB only

For each service with a detected version, ingest recent changelog:
```
knowledge_ingest_changelog(
    content="<paste Kafka 3.x release notes>",
    service="kafka"
)
```

This seeds MuninnDB `doc:kafka:*` engrams so pre_upgrade_check step 5
has real historical context.

## Rebuild schedule
None required. All steps are agent task executions.

## Session plan
Single session — run steps sequentially, verify after each.
Expected time: 15-30 minutes (mostly waiting for discovery scan).
