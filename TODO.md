# DEATHSTAR — TODO

> The shipped-feature changelog lives in `cc_prompts/QUEUE_STATUS.md`.
> The current platform state lives in the most recent `docs/STATUS_REPORT_*.md`.
> This file lists open operational and ideation items only.

---

## 🟡 Known operational issues

### Kafka DEGRADED — worker-03 down
`worker-03` (192.168.199.33) is Down in `docker node ls`.
`kafka_broker-3` Swarm service is unscheduled (no suitable node).
Partition 0 on `hp1-logs` is under-replicated.
**Fix:** reboot `worker-03` VM from Proxmox → broker-3 self-schedules → cluster reforms.
Pure ops; no code change required. Tools available: `proxmox_vm_power` agent tool, or Proxmox UI.

### Proxmox Cluster FIN — VPN dependency on dev PC
Connection routed via `netsh portproxy` on Windows dev PC
(`192.168.199.51:18006 → 10.10.11.11:8006`).
Unavailable when OpenVPN on dev PC is disconnected.
**Fix:** run WireGuard/OpenVPN endpoint directly on agent-01.

---

## 🔵 Open ideas

### Real notification delivery test
Notification code (SMTP + webhook) shipped at v2.14.0, exercised against webhook.site only.
Add a real SMTP recipient + a real webhook target, trigger a critical alert, confirm delivery,
and verify `notification_log` rows. The dispatch code is fully wired — this is operator validation.

### Auth hardening — v2.12.0 / v2.30.1 / v2.45.29 verification checklist
Cookie-first auth and TLS reverse proxy have shipped, but the operator-side smoke
checklist was never run end-to-end:
- Inspect cookies (`hp1_auth` → HttpOnly + Secure when `HP1_BEHIND_HTTPS=true`)
- Confirm localStorage has no `hp1_auth_token`
- Logout clears the cookie
- Rate limit fires (6 bad logins → 429)
- API scripts work with `Authorization: Bearer <api-token>`

### Multi-connection scope audit
v2.30.0 added multi-connection support in Proxmox action paths, but
`api/connections.py:get_connection_for_platform()` still uses `LIMIT 1`.
Audit all call sites: confirm each one wants single-result semantics, or
migrate to `get_all_connections_for_platform()` where appropriate.

### Multi-agent parallel execution
Two sub-agents on different hosts simultaneously. Currently sub-agents run
in-band (one at a time) per `_spawn_and_wait_subagent`. Concurrency would help
on multi-host investigations. Discuss before queuing prompts — needs a design
pass on shared state, plan-lock semantics, and budget reservation.

### `runbookInjectionMode=augment` real implementation
Default was realigned to `replace` at v2.45.26 because `augment` and `replace+shrink`
silently fall back. Implementing real `augment` (prepend runbook to existing prompt
rather than replacing it) is queued as a future v2.46+ design item.

### External AI output modes — `augment` / `side-by-side`
Same situation as above: only `replace` is implemented. Settings accept the other
values; runtime falls back to replace. Real implementations would need a design pass.

### Entity timeline view
Click an entity card → inline change history (entity_changes + entity_events).
Schema and data are live; the UI surface is missing.

### Agent task templates — expand library
v2.31.9 added `reboot_proxmox_vm`. v2.33.1/2/8/18 added `drain_swarm_node`,
`diagnose_kafka_under_replicated`, `verify_backup_job`, `recover_worker_node`.
More common ops (rolling kafka restart, swarm service rollback, drain-and-cordon)
would shorten the path for routine work.

### FortiSwitch + external_services known_facts writes
Of 9 collectors, 7 now write facts (proxmox, pbs, swarm, docker_agent, kafka,
elastic, network_ssh, vm_hosts, unifi+fortigate via v2.39.x). FortiSwitch and
`external_services` are the remaining gaps. Pattern is well-established
(`api/facts/extractors.py` + `batch_upsert_facts` from collector).
