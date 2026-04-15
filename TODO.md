# DEATHSTAR — TODO
*State at end of session — v2.29.4 live*

---

## 🔴 Immediate

Nothing pending.

---

## 🟡 Known issues

### Kafka DEGRADED
`worker-03` (192.168.199.33) is Down in `docker node ls`.
`kafka_broker-3` Swarm service is unscheduled (no suitable node).
Partition 0 on `hp1-logs` is under-replicated (ISR: 1,3 — broker 2 missing).
`KAFKA_UNDER_REPLICATED_THRESHOLD=1` in `.env` → dashboard shows DEGRADED, not CRITICAL.
Fix: reboot `worker-03` VM from Proxmox → broker-3 self-schedules → cluster reforms.

### Prox Cluster FIN — VPN dependency
Connection routed via `netsh portproxy` on Windows dev PC
(192.168.199.51:18006 → 10.10.11.11:8006).
Unavailable when OpenVPN is disconnected.
Permanent fix: run WireGuard/OpenVPN directly on agent-01.

---

## 🟢 Implemented — live as of v2.29.4

### Queue v2.8.0 – v2.14.0

| Version | Feature | Commit |
|---|---|---|
| v2.8.0 | Semantic tool routing + thinking memory + feedback pre-ranking | 69b4e7d |
| v2.8.1 | LLM temperature profiles + /no_think for cheap steps | 6bd67ea |
| v2.9.0 | entity_changes + entity_events DB tables + image digest tracking | 8b08f17 |
| v2.9.1 | entity_history() + entity_events() agent tools + GUI badge | 467f949 |
| v2.10.0 | Lightweight coordinator pattern between agent steps | e7791ff |
| v2.10.1 | Alert health-transition badge + FortiGate filter bar + snapshot TTL | 47d0dc5 |
| v2.11.0 | Multi-connection collectors (get_all_connections_for_platform) | 2aeba18 |
| v2.11.1 | PBS collector — real implementation with PBSAPIToken auth | e5292dc |
| v2.12.0 | httpOnly cookie auth + slowapi login rate limiting | 7c84014 |
| v2.12.1 | SSH capability map security dashboard | 5a503e6 |
| v2.13.0 | Spec-first skill generation + environment discovery + fingerprints | c558eb6 |
| v2.13.1 | skill_execute dispatcher + 3-layer validation | 81e86f2 |
| v2.14.0 | Email + webhook notification system | ca4273e |

### Queue v2.15.0 – v2.29.4

| Version | Feature | Commit |
|---|---|---|
| v2.15.0 | Credential profiles: named shared auth sets for connections | 80f5eb1 |
| v2.15.1 | Copy connection + bulk create (IP range + name pattern) | b551045 |
| v2.15.2 | Kafka: KRaft controller fix + under-replicated threshold | 2dea8d4 |
| v2.15.3 | kafka_exec agent tool + vm_exec allowlist expansion | 1d26cac |
| v2.15.4 | Agent loop fixes: SQL bool, plan re-approval, risk colour, final_answer | a9d27ac |
| v2.15.5 | Layouts tab fix + admin menu cleanup + footer styling | 12cd178 |
| v2.15.6 | Platform Core value-before-tag + alphabetical sorting everywhere | — |
| v2.15.7 | Container cards: name fix, real IP, networks, per-host Section | — |
| v2.15.8 | Multi-expand cards + shift-click range + toolbar expand/collapse | e516007 |
| v2.15.9 | Agent Swarm recovery tools + pre-flight bypass | b7f83e6 |
| v2.15.10 | Escalation visibility: persistent banner + acknowledge | b9e87e7 |
| v2.16.0 | Agent: investigate-on-degraded + halt synthesis | bd42b0c |
| v2.16.1 | Agent task templates in CommandPanel | 2339ba4 |
| v2.17.0 | Entity timeline view in EntityDrawer | 20656ec |
| v2.17.1 | Fix Proxmox noVNC console URL (uses actual Proxmox host) | 22c9709 |
| v2.18.0 | Result store viewer in Logs tab | c17aec2 |
| v2.18.1 | Synthesis on all completion paths + Kafka diagnostic prompts | 774692f |
| v2.19.0 | service_placement tool: swarm service → node → vm_host | c0b964a |
| v2.19.1 | docker logs allowlist + investigation depth rules | a77c6f5 |
| v2.20.0 | Investigation quality: structured output + clarifying questions | 5a52b30 |
| v2.20.1 | VM card action audit trail + visual feedback | a3c0e01 |
| v2.20.2 | VM card SSH log stream + live logs filter fix | 858b2a6 |
| v2.21.0 | Time-series metric_samples table + metric_trend agent tool | 650a615 |
| v2.21.1 | Container lifecycle events + collector snapshots to Elasticsearch | 1ce76c2 |
| v2.21.2 | Data pipeline health tab (ES doc counts, PG snapshot freshness) | 638e3f1 |
| v2.22.0 | Dashboard summary endpoint + DashboardDataContext shared state | 0012bd8 |
| v2.22.1 | Skeleton loading + WebSocket-driven live updates | b7680bd |
| v2.22.2 | TDZ fix: move const id before useEffect hooks in VMCard | feb929d |
| v2.22.3 | Root error boundary + per-section + frontend crash reporting | 5acdd54 |
| v2.22.4 | ESLint TDZ rule + source maps + API version gate + Dockerfile | 0b2e69b |
| v2.22.5 | Fix GHCR tag pagination + version status display | 35d8069 |
| v2.22.6 | agentHostIp setting + clickable container endpoints | 76b9c1b |
| v2.23.0 | Fix VM host reboot + Proxmox action credential bugs | bbc6039 |
| v2.23.1 | Entity cross-reference registry + resolve_entity tool | f5b51b7 |
| v2.23.2 | Fix task classifier, kubectl hallucination, escalation UI | 9445cca |
| v2.23.3 | DB-backed vm_exec allowlist + session/permanent approval flow | aa42441 |
| v2.23.4 | Session output log: retention settings, full log view, raw output tab | f11dc20 |
| v2.24.0 | Sub-agent proposals + manual runbook popups + runbook library | 0c78bfc |
| v2.24.1 | Fix propose_subtask not called + operation_log silent failures | 4b2afcf |
| v2.24.2 | Fix operation_log timestamp str→datetime (asyncpg DataError) | 76c8073 |
| v2.24.3 | Fix SubtaskOfferBanner buttons clipped by overflow-hidden parent | 42cc5a3 |
| v2.24.4 | Inline sub-task offer in AgentFeed/OutputPanel; remove dashboard banner | 843a16d |
| v2.24.5 | Fix exit-137 diagnosis: require dmesg before concluding OOM | 5e8b61e |
| v2.24.6 | ES card in Platform Core + ES/Kafka health thresholds in settings | b23f5c1 |
| v2.25.0 | Per-entity maintenance mode + Proxmox/dmesg allowlist | d28196a |
| v2.26.0 | Universal entity_id on all card types + docker/swarm to_entities() | 276ddfb |
| v2.26.1 | InfraCard universal ⌘/› buttons + VM entity ID fix (qemu→vm) | c879f1c |
| v2.26.2 | Agent routing: proxmox allowlist, node_activate, ambiguous→observe | d245508 |
| v2.26.3 | Prompt quality: propose_subtask priority, non-Kafka paths, observe format | 288f5ca |
| v2.26.4 | Seed 4 base runbooks (kafka recovery, disk cleanup, swarm, reintegration) | b5221ba |
| v2.26.5 | EntityDrawer Ask: 300→600 tokens + platform-aware suggestions | 4960081 |
| v2.26.6 | Entity detail performance: /find/{id} endpoint + 30s cache | 6869ba7 |
| v2.26.7 | VM Hosts: entity_id, to_entities(), ask/detail buttons, naming fix | 11f9dc8 |
| v2.26.8 | Docker started_at + restart_count in entity metadata | f84bba1 |
| v2.26.9 | DB: credential_profiles seq_id+discoverable, connection_audit_log, username_cache | f1c8971 |
| v2.26.10 | Backend: credential profiles API — rotation test, confirm, audit, auth types | d33dd65 |
| v2.27.0 | Connections: credential_state, CSV import/export, Windows platform stub | cf65038 |
| v2.27.1 | Discovery harvest: Proxmox/UniFi/Swarm passive scan + link endpoints | 25f3d21 |
| v2.27.2 | Frontend: credential profiles tab overhaul — all auth types, seq_id, rotation | 2e3c5b0 |
| v2.27.3 | Frontend: connections form — profile display, greyed fields, badges, import/export | e7532c1 |
| v2.27.4 | Frontend: RotationTestModal — per-connection test, role-gated override, audit logged | 2eb2867 |
| v2.27.5 | Frontend: Discovered view — harvest table, test-with-profile, one-click link | 1dfb47b |
| v2.27.6 | Settings: discovery scope CIDR list + rotation concurrency settings | c16142b |
| v2.27.7 | DB: card_templates + display_aliases tables + API routes | f77e434 |
| v2.27.8 | Docker entity metadata: ports/networks/IPs + EntityDrawer exposed-at | 8808506 |
| v2.27.9 | FIELD_SCHEMA + TemplateCardRenderer + useCardTemplate hook | 26317a9 |
| v2.28.0 | Schema-driven ContainerCard: image line 2, version in collapsed | c26eef1 |
| v2.28.1 | Settings: Display→Appearance, entity alias editor in Naming | aa62dea |
| v2.28.2 | DnD card template editor in Appearance tab (@dnd-kit) | 6b3d527 |
| v2.28.3 | Per-connection card template override in Connections tab | 2e18b2b |
| v2.28.4 | Platform Core names+version delta+nav, ⌘/› bottom-right | 4f4b77e |
| v2.28.5 | fix(build): cardSchemas JSX→createElement, Sidebar duplicate borderLeft | 6680c5e |
| v2.28.6 | Collector rows link to config (same pattern as Platform Core) | 32d6447 |
| v2.28.7 | Theme: light mode, contrast fix, accent/font/density/radius in Appearance | 3c7bd6e |
| v2.28.8 | fix(ui): version badge in Platform Core + collapsed container card | 80dc67c |
| v2.28.9 | fix(ui): duplicate actions, allowlist, layouts, card templates→Layouts, Security nav | b58cf16 |
| v2.29.0 | feat(docs): doc search API + Browse mode in DocsTab | ae5b654 |
| v2.29.1 | feat(docs): grounded doc Q&A via LM Studio — Ask mode with streaming SSE | c5efe0b |
| v2.29.2 | fix(agent): Kafka triage-first — consumer lag path, broker path, replication path | d688cb3 |
| v2.29.3 | fix(ui): Proxmox sort dropdown z-index, card alignment, expanded task templates | 8c6c458 |
| v2.29.4 | fix(agent): kafka_consumer_lag mandatory in triage, Swarm Shutdown events are normal | 0242724 |

### Pre-queue (v2.6.x – v2.7.x)

| Version | Feature |
|---|---|
| v2.6.2 | test_connection() delegates to _probe_connection() |
| v2.6.3 | TrueNAS rich card + CardFilterBar fix |
| v2.6.4 | FortiGate rich card |
| v2.6.5 | Dynamic postgres row + section wiring |
| v2.6.6 | PBS snapshot count + debug endpoint fix |
| v2.7.0 | Multiple Proxmox connections → multiple COMPUTE cards |
| v2.7.1 | Per-cluster Proxmox filter bars |
| v2.7.2 | Generic ConnectionFilterBar + UniFi filtering |
| v2.7.3 | Compare per-entity chat suggestions |

---

## 🔵 Deferred / next ideas

### Reboot worker-03 via Proxmox
- VM 199.33 is Down in `docker node ls`
- Proxmox action: reboot VM → broker-3 self-schedules → Kafka cluster reforms
- Can be done via agent (proxmox_vm_power) or Proxmox UI

### Multi-connection fix in get_connection_for_platform()
- `api/connections.py` `get_connection_for_platform()` still uses `LIMIT 1`
- Callers that need first-match (single result) are fine; but any path that should
  iterate all connections of a platform will silently miss extras
- Deferred from this session — needs audit of all call sites before changing

### Auth hardening checklist (v2.12.0 shipped, not fully tested)
- Verify httpOnly cookie present in DevTools (Application → Cookies → hp1_auth → HttpOnly flag)
- Verify localStorage no longer has `hp1_auth_token`
- Test logout clears cookie
- Test rate limiting (6 bad logins → 429)
- Test API scripts still work with `Authorization: Bearer` header
- localStorage XSS risk still open if token still dual-written

### Bookstack sync (Option 3)
- Doc search (v2.29.0–v2.29.1) uses local filesystem docs only
- Option 3: periodic sync from Bookstack API → local markdown files → indexed
- Backend: scheduled harvest task + Bookstack API client
- Deferred from this session

### Test v2.14.0 notifications
- Add an email or webhook channel in Settings → Notifications
- Trigger a critical alert and verify delivery
- Check notification_log for sent/failed records

### Proxmox Cluster FIN VPN
- Move WireGuard/OpenVPN to agent-01 so Proxmox FIN is always reachable
- Currently only accessible when Windows dev PC OpenVPN is connected

### v2.30.x ideas (discuss before writing prompts)
- Multi-agent parallel execution — two sub-agents on different hosts simultaneously
- Windows collector — WinRM stub is in place (v2.27.0), needs real implementation
- Notification delivery hardening — real email/webhook end-to-end test beyond webhook.site
- Doc search Bookstack sync (see above)

---

## 🏗 Architecture reference

### CC prompt queue system
All future changes go through cc_prompts/ queue:
```bash
# Write new prompts in cc_prompts/CC_PROMPT_vX.Y.Z.md
# Update INDEX.md with PENDING status
# Run from Git Bash:
bash cc_prompts/run_queue.sh --dry-run   # preview
bash cc_prompts/run_queue.sh --one       # supervised
bash cc_prompts/run_queue.sh             # full auto
```

### Deploy after CC push
```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env \
  up -d hp1_agent
docker logs hp1_agent --tail 30
```

### Entity ID format
- `proxmox:{name}:{vmid}` — e.g. `proxmox:graylog:119`
- `cluster:proxmox:Pmox Cluster KB`
- `unifi:device:{mac}`
- `pbs:{label}:{datastore}`
- `truenas:pool:{name}`
- `fortigate:iface:{name}`
- `swarm:service:{name}`
- `external_services:{slug}`
- `vm_host:{label}`
- `docker:{label}:{container_name}`

### Key paths
```
api/routers/agent.py                — agent loop, safety gates
api/agents/router.py                — classifier, allowlists, prompts
api/agents/orchestrator.py          — coordinator, step planner
api/db/entity_history.py            — change + event tables
api/db/result_store.py              — large result refs
api/db/ssh_log.py                   — SSH audit log
api/db/ssh_capabilities.py          — credential→host map
api/db/notifications.py             — notification channels/rules
api/notifications.py                — SMTP + webhook delivery
api/db/credential_profiles.py       — named shared auth sets
api/db/audit_log.py                 — connection_audit_log
api/db/infra_inventory.py           — entity cross-reference registry
api/db/vm_exec_allowlist.py         — DB-backed command allowlist
api/db/runbooks.py                  — runbook library + seeded base runbooks
api/db/metric_samples.py            — time-series metrics
api/routers/credential_profiles.py  — rotation test/confirm, audit
api/routers/connections.py          — CRUD + CSV import/export
api/routers/discovery.py            — harvest, devices, test, link
api/routers/entities.py             — /find/{id} fast path + cache
api/collectors/                     — all platform collectors
mcp_server/tools/                   — built-in tools
mcp_server/tools/metric_tools.py    — metric_trend + list_metrics
plugins/                            — per-platform plugins
cc_prompts/                         — improvement queue
gui/src/components/EntityDrawer.jsx — timeline, ask, entity detail
gui/src/components/ServiceCards.jsx — all infra cards + InfraCard universal buttons
gui/src/context/DashboardDataContext.jsx — shared state + version gate
```
