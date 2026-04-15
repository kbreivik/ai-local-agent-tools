# DEATHSTAR CC Prompt Queue

Agreed improvement phases from architecture review on 2026-04-12.
Run in version order. Each file is a standalone CC prompt.

Earlier prompts (v2.6.x–v2.7.x) archived in cc_prompts/archive/.

---

## Automated Queue Runner

```bash
# Git Bash (recommended)
cd /d/claude_code/ai-local-agent-tools
bash cc_prompts/run_queue.sh --dry-run   # preview
bash cc_prompts/run_queue.sh --one       # run next one (supervised)
bash cc_prompts/run_queue.sh             # run all
```

---

## Phase Queue

| File | Version | Theme | Status |
|---|---|---|---|
| CC_PROMPT_v2.8.0.md | v2.8.0 | AI loop: semantic tool routing + thinking memory + feedback pre-ranking | DONE (69b4e7d) |
| CC_PROMPT_v2.8.1.md | v2.8.1 | LLM temperature profile + /no_think for cheap steps | DONE (6bd67ea) |
| CC_PROMPT_v2.9.0.md | v2.9.0 | Entity state DB: change tracking + event log + image digest | DONE (8b08f17) |
| CC_PROMPT_v2.9.1.md | v2.9.1 | Entity history agent tools + context injection + GUI badge | DONE (467f949) |
| CC_PROMPT_v2.10.0.md | v2.10.0 | Lightweight coordinator pattern between agent steps | DONE (e7791ff) |
| CC_PROMPT_v2.10.1.md | v2.10.1 | Small fixes: alert transition badge + FortiGate filter bar + snapshot retention | DONE (47d0dc5) |
| CC_PROMPT_v2.11.0.md | v2.11.0 | Multi-connection collectors: all platforms use get_all_connections | DONE (2aeba18) |
| CC_PROMPT_v2.11.1.md | v2.11.1 | PBS collector implementation | DONE (e5292dc) |
| CC_PROMPT_v2.12.0.md | v2.12.0 | Auth hardening: httpOnly cookies + login rate limiting | DONE (7c84014) |
| CC_PROMPT_v2.12.1.md | v2.12.1 | Security dashboard: SSH capability map + new-host alerts UI | DONE (5a503e6) |
| CC_PROMPT_v2.13.0.md | v2.13.0 | Skill system: spec-first generation + environment discovery | DONE (c558eb6) |
| CC_PROMPT_v2.13.1.md | v2.13.1 | Skill system: skill_execute dispatcher + three-layer validation | DONE (81e86f2) |
| CC_PROMPT_v2.14.0.md | v2.14.0 | Notification system: email + webhook for critical events | DONE (ca4273e) |
| CC_PROMPT_v2.15.0.md | v2.15.0 | Credential profiles: named shared auth sets for connections | DONE (80f5eb1) |
| CC_PROMPT_v2.15.1.md | v2.15.1 | Copy connection + bulk create (IP range + name pattern) | DONE (b551045) |
| CC_PROMPT_v2.15.2.md | v2.15.2 | Kafka: KRaft controller fix + under-replicated threshold | DONE (2dea8d4) |
| CC_PROMPT_v2.15.3.md | v2.15.3 | kafka_exec agent tool + vm_exec allowlist expansion | DONE (1d26cac) |
| CC_PROMPT_v2.15.4.md | v2.15.4 | Agent loop fixes: SQL bool, plan re-approval, risk colour, final_answer | DONE (a9d27ac) |
| CC_PROMPT_v2.15.5.md | v2.15.5 | Layouts tab fix + admin menu cleanup + footer styling | DONE (12cd178) |
| CC_PROMPT_v2.15.6.md | v2.15.6 | Platform Core value-before-tag + alphabetical sorting everywhere | DONE |
| CC_PROMPT_v2.15.7.md | v2.15.7 | Container cards: name fix, real IP, networks, per-host Section | DONE |
| CC_PROMPT_v2.15.8.md | v2.15.8 | Multi-expand cards + shift-click range + toolbar expand/collapse | DONE (e516007) |
| CC_PROMPT_v2.15.9.md | v2.15.9 | Agent Swarm recovery tools + pre-flight bypass | DONE (b7f83e6) |
| CC_PROMPT_v2.15.10.md | v2.15.10 | Escalation visibility: persistent banner + acknowledge | DONE (b9e87e7) |
| CC_PROMPT_v2.16.0.md | v2.16.0 | Agent: investigate-on-degraded + halt synthesis | DONE (bd42b0c) |
| CC_PROMPT_v2.16.1.md | v2.16.1 | Agent task templates in CommandPanel | DONE (2339ba4) |
| CC_PROMPT_v2.17.0.md | v2.17.0 | Entity timeline view in EntityDrawer | DONE (20656ec) |
| CC_PROMPT_v2.17.1.md | v2.17.1 | Fix Proxmox noVNC console URL (uses actual Proxmox host) | DONE (22c9709) |
| CC_PROMPT_v2.18.0.md | v2.18.0 | Result store viewer in Logs tab | DONE (c17aec2) |
| CC_PROMPT_v2.18.1.md | v2.18.1 | Synthesis on all completion paths + Kafka diagnostic prompts | DONE (774692f) |
| CC_PROMPT_v2.19.0.md | v2.19.0 | service_placement tool: swarm service → node → vm_host | DONE (c0b964a) |
| CC_PROMPT_v2.19.1.md | v2.19.1 | docker logs allowlist + investigation depth rules | DONE (a77c6f5) |
| CC_PROMPT_v2.20.0.md | v2.20.0 | Investigation quality: structured output + clarifying questions | DONE (5a52b30) |
| CC_PROMPT_v2.20.1.md | v2.20.1 | VM card action audit trail + visual feedback | DONE (a3c0e01) |
| CC_PROMPT_v2.20.2.md | v2.20.2 | VM card SSH log stream + live logs filter fix | DONE (858b2a6) |
| CC_PROMPT_v2.21.0.md | v2.21.0 | Time-series metric_samples table + metric_trend agent tool | DONE (650a615) |
| CC_PROMPT_v2.21.1.md | v2.21.1 | Container lifecycle events + collector snapshots to Elasticsearch | DONE (1ce76c2) |
| CC_PROMPT_v2.21.2.md | v2.21.2 | Data pipeline health tab (ES doc counts, PG snapshot freshness) | DONE (638e3f1) |
| CC_PROMPT_v2.22.0.md | v2.22.0 | Dashboard summary endpoint + DashboardDataContext shared state | DONE (0012bd8) |
| CC_PROMPT_v2.22.1.md | v2.22.1 | Skeleton loading + WebSocket-driven live updates | DONE (b7680bd) |
| CC_PROMPT_v2.22.2.md | v2.22.2 | TDZ fix: move const id before useEffect hooks in VMCard | DONE (feb929d) |
| CC_PROMPT_v2.22.3.md | v2.22.3 | Root error boundary + per-section + frontend crash reporting | DONE (5acdd54) |
| CC_PROMPT_v2.22.4.md | v2.22.4 | ESLint TDZ rule + source maps + API version gate + Dockerfile | DONE (0b2e69b) |
| CC_PROMPT_v2.22.5.md | v2.22.5 | Fix GHCR tag pagination + version status display | DONE (35d8069) |
| CC_PROMPT_v2.22.6.md | v2.22.6 | agentHostIp setting + clickable container endpoints | DONE (76b9c1b) |
| CC_PROMPT_v2.23.0.md | v2.23.0 | Fix VM host reboot + Proxmox action credential bugs | DONE (bbc6039) |
| CC_PROMPT_v2.23.1.md | v2.23.1 | Entity cross-reference registry + resolve_entity tool | DONE (f5b51b7) |
| CC_PROMPT_v2.23.2.md | v2.23.2 | Fix task classifier, kubectl hallucination, escalation UI | DONE (9445cca) |
| CC_PROMPT_v2.23.3.md | v2.23.3 | DB-backed vm_exec allowlist + session/permanent approval flow | DONE (aa42441) |
| CC_PROMPT_v2.23.4.md | v2.23.4 | Session output log: retention settings, full log view, raw output tab | DONE (f11dc20) |
| CC_PROMPT_v2.24.0.md | v2.24.0 | Sub-agent proposals + manual runbook popups + runbook library | DONE (0c78bfc) |
| CC_PROMPT_v2.24.1.md | v2.24.1 | Fix propose_subtask not called + operation_log silent failures | DONE (4b2afcf) |
| CC_PROMPT_v2.24.2.md | v2.24.2 | Fix operation_log timestamp str→datetime (asyncpg DataError) | DONE (76c8073) |
| CC_PROMPT_v2.24.3.md | v2.24.3 | Fix SubtaskOfferBanner buttons clipped by overflow-hidden parent | DONE (42cc5a3) |
| CC_PROMPT_v2.24.4.md | v2.24.4 | Inline sub-task offer in AgentFeed/OutputPanel; remove dashboard banner | DONE (843a16d) |
| CC_PROMPT_v2.24.5.md | v2.24.5 | Fix exit-137 diagnosis: require dmesg before concluding OOM | DONE (5e8b61e) |
| CC_PROMPT_v2.24.6.md | v2.24.6 | ES card in Platform Core + ES/Kafka health thresholds in settings | DONE (b23f5c1) |
| CC_PROMPT_v2.25.0.md | v2.25.0 | Per-entity maintenance mode + Proxmox/dmesg allowlist | DONE (d28196a) |
| CC_PROMPT_v2.25.1.md | v2.25.1 | SUPERSEDED by v2.26.0+v2.26.1 — DO NOT RUN | SUPERSEDED |
| CC_PROMPT_v2.26.0.md | v2.26.0 | Universal entity_id on all card types + docker/swarm to_entities() | DONE (276ddfb) |
| CC_PROMPT_v2.26.1.md | v2.26.1 | InfraCard universal ⌘/› buttons + VM entity ID fix (qemu→vm) | DONE (c879f1c) |
| CC_PROMPT_v2.26.2.md | v2.26.2 | Agent routing: proxmox allowlist, node_activate, ambiguous→observe | DONE (d245508) |
| CC_PROMPT_v2.26.3.md | v2.26.3 | Prompt quality: propose_subtask priority, non-Kafka paths, observe format | DONE (288f5ca) |
| CC_PROMPT_v2.26.4.md | v2.26.4 | Seed 4 base runbooks (kafka recovery, disk cleanup, swarm, reintegration) | DONE (b5221ba) |
| CC_PROMPT_v2.26.5.md | v2.26.5 | EntityDrawer Ask: 300→600 tokens + platform-aware suggestions | DONE (4960081) |
| CC_PROMPT_v2.26.6.md | v2.26.6 | Entity detail performance: /find/{id} endpoint + 30s cache | DONE (6869ba7) |
| CC_PROMPT_v2.26.8.md  | v2.26.8  | Docker started_at + restart_count in entity metadata | DONE (f84bba1) |
| CC_PROMPT_v2.26.9.md  | v2.26.9  | DB: credential_profiles seq_id+discoverable, connection_audit_log, username_cache | DONE (f1c8971) |
| CC_PROMPT_v2.26.10.md | v2.26.10 | Backend: credential profiles API overhaul — rotation test, confirm, audit, auth types | DONE (d33dd65) |
| CC_PROMPT_v2.27.0.md  | v2.27.0  | Backend: connections credential_state, CSV import/export, Windows platform stub | DONE (cf65038) |
| CC_PROMPT_v2.27.1.md  | v2.27.1  | Backend: discovery harvest (Proxmox/UniFi/Swarm), test, link endpoints | DONE (25f3d21) |
| CC_PROMPT_v2.27.2.md  | v2.27.2  | Frontend: credential profiles tab overhaul — seq_id, all auth types, prominent section | DONE (2e3c5b0) |
| CC_PROMPT_v2.27.3.md  | v2.27.3  | Frontend: connections form — profile display, greyed fields, badges, import/export | DONE (e7532c1) |
| CC_PROMPT_v2.27.4.md  | v2.27.4  | Frontend: RotationTestModal — per-connection test, role-gated override, audit logged | DONE (2eb2867) |
| CC_PROMPT_v2.27.5.md  | v2.27.5  | Frontend: Discovered view — nav item, harvest table, test-with-profile, one-click link | DONE (1dfb47b) |
| CC_PROMPT_v2.27.6.md  | v2.27.6  | Settings: discovery scope CIDR list + rotation concurrency settings | DONE (c16142b) |
| CC_PROMPT_v2.27.7.md  | v2.27.7  | DB: card_templates + display_aliases tables + API routes | DONE (f77e434) |
| CC_PROMPT_v2.27.8.md  | v2.27.8  | Docker entity metadata: ports/networks/IPs + EntityDrawer exposed-at | DONE (8808506) |
| CC_PROMPT_v2.27.9.md  | v2.27.9  | FIELD_SCHEMA + TemplateCardRenderer + useCardTemplate hook | DONE (26317a9) |
| CC_PROMPT_v2.28.0.md  | v2.28.0  | Schema-driven ContainerCard: image line 2, version in collapsed | DONE (c26eef1) |
| CC_PROMPT_v2.28.1.md  | v2.28.1  | Settings: Display→Appearance, entity alias editor in Naming | DONE (aa62dea) |
| CC_PROMPT_v2.28.2.md  | v2.28.2  | DnD card template editor in Appearance tab (@dnd-kit) | DONE (6b3d527) |
| CC_PROMPT_v2.28.3.md  | v2.28.3  | Per-connection card template override in Connections tab | DONE (2e18b2b) |
| CC_PROMPT_v2.28.4.md  | v2.28.4  | Platform Core names+version delta+nav, ⌘/› bottom-right | DONE (4f4b77e) |
| CC_PROMPT_v2.28.5.md  | v2.28.5  | fix(build): cardSchemas JSX→createElement, Sidebar duplicate borderLeft | DONE (6680c5e) |
| CC_PROMPT_v2.28.6.md  | v2.28.6  | Collector rows link to config (same pattern as Platform Core) | DONE (32d6447) |
| CC_PROMPT_v2.28.7.md  | v2.28.7  | Theme: light mode, contrast fix, accent/font/density/radius in Appearance | DONE (3c7bd6e) |
| CC_PROMPT_v2.28.8.md  | v2.28.8  | fix(ui): version badge in Platform Core + collapsed container card | DONE (80dc67c) |
| CC_PROMPT_v2.28.9.md  | v2.28.9  | fix(ui): duplicate actions, allowlist, layouts, card templates→Layouts, Security nav | DONE (b58cf16) |
| CC_PROMPT_v2.29.0.md  | v2.29.0  | feat(docs): doc search API + Browse mode in DocsTab | DONE (ae5b654) |
| CC_PROMPT_v2.29.1.md  | v2.29.1  | feat(docs): grounded doc Q&A via LM Studio — Ask mode with streaming SSE | DONE (c5efe0b) |
| CC_PROMPT_v2.29.2.md  | v2.29.2  | fix(agent): Kafka triage-first — consumer lag path, broker path, replication path | DONE (d688cb3) |
| CC_PROMPT_v2.29.3.md  | v2.29.3  | fix(ui): Proxmox sort dropdown z-index, card alignment, expanded task templates | DONE (8c6c458) |
| CC_PROMPT_v2.29.4.md  | v2.29.4  | fix(agent): kafka_consumer_lag mandatory in triage, Swarm Shutdown events are normal | DONE (0242724) |
| CC_PROMPT_v2.29.5.md  | v2.29.5  | fix(ui): filter bar vertical centering + revert wrong ProxmoxCard centering | DONE (457397e) |
| CC_PROMPT_v2.30.0.md  | v2.30.0  | fix(proxmox): multi-connection support in Proxmox action paths | RUNNING |
| CC_PROMPT_v2.30.1.md  | v2.30.1  | fix(auth): remove token from localStorage, cookie-first auth | PENDING |
| CC_PROMPT_v2.26.7.md | v2.26.7 | VM Hosts: entity_id, to_entities(), ask/detail buttons, naming fix | DONE (11f9dc8) |

---

## Version bump rationale

| Bump | Meaning |
|---|---|
| x.x.1 | Fix, tuning, small addition |
| x.1.x | New subsystem, architectural change, multi-file feature |

---

## Phase summaries

**v2.26.0** — Universal entity_id on all collector card types.
Adds entity_id to every card dict (containers, swarm services, external services, UniFi
devices, PBS datastores, TrueNAS pools, FortiGate interfaces). Adds custom to_entities()
to DockerAgent01Collector and SwarmCollector.

**v2.26.1** — InfraCard universal ⌘/› entity buttons + VM entity ID fix.
Moves entity detail (›) and agent ask (⌘) buttons into InfraCard itself. All 8 card types
get both buttons when entity_id is present. Fixes VM entity ID bug (qemu→vm). Optimistic
maintenance toggle.

**v2.26.2** — Agent routing correctness fixes.
EXECUTE_PROXMOX_TOOLS was nearly empty — adds proxmox_vm_power, vm_exec, swarm_node_status,
service_list/health, service_placement, entity_history, entity_events, resolve_entity,
result_fetch/query, propose_subtask. EXECUTE_KAFKA_TOOLS adds vm_exec, infra_lookup,
service_list, entity_history, result_fetch, propose_subtask. EXECUTE_SWARM_TOOLS and
EXECUTE_GENERAL_TOOLS add node_activate (was missing — agents could drain but not un-drain).
All execute allowlists get propose_subtask. Ambiguous classifier result now routes to
Observe agent + STATUS_PROMPT instead of Execute agent (was wrong default).

**v2.26.3** — Prompt quality improvements.
RESEARCH_PROMPT: adds early propose_subtask reminder right after rule 8 (propose was
buried at bottom, model consistently missed it). Adds NON-KAFKA INVESTIGATION PATHS section
covering storage (TrueNAS/PBS), network (FortiGate/UniFi), and compute (Proxmox) paths
with specific tool chains and root cause formats. STATUS_PROMPT: adds REQUIRED SUMMARY FORMAT
template (STATUS / FINDINGS / ACTION NEEDED) — observe agent had no output format guide,
results were inconsistent across runs.

**v2.26.4** — Seed 4 base runbooks.
Adds BASE_RUNBOOKS constant and seed_base_runbooks() to api/db/runbooks.py, called from
init_runbooks() on startup. Seeds: kafka broker missing + worker node recovery (8 steps),
docker disk cleanup (6 steps), swarm service not converging + force update (6 steps),
worker node reintegration after reboot (7 steps). Runbooks are idempotent on title.

**v2.26.5** — EntityDrawer Ask improvements.
Increases max_tokens from 300 to 600 in /api/agent/ask. Rewrites /api/agent/ask/suggestions
to be platform-aware: accepts platform + entity_id query params, returns suggestions per
platform (proxmox/docker/kafka/unifi/truenas/pbs/fortigate) and per status.

**v2.26.9** — DB foundations for credential profiles overhaul.
Adds seq_id BIGSERIAL + discoverable to credential_profiles (migration-safe ALTER + fresh DDL). Seeds
sec_id=0 dummy profile '__no_credential__' on init. Adds username_cache TEXT to connections table.
New api/db/audit_log.py: connection_audit_log table + write_audit_event() + list_audit_events().
Updates list_profiles() to return seq_id, has_private_key, has_passphrase, has_password, discoverable,
linked_connections_count. Adds get_profile_safe(), get_profile_by_seq_id().

**v2.26.10** — Backend credential profiles API overhaul.
Full rewrite of api/routers/credential_profiles.py: adds GET /{id}/safe, POST /{id}/test-rotation
(tests new credentials without saving), POST /{id}/confirm-rotation (saves + audit log), GET /{id}/audit.
Renames auth types ssh_key→ssh, api_key→api; adds windows, token_pair, basic. Removes shared_credentials
fallback from resolve_credentials_for_connection(). update_profile() replaces credentials entirely on
rotation (no merge) + accepts discoverable param. create_profile() accepts discoverable.

**v2.27.0** — Connections API + Windows platform.
list_connections() returns credential_state per connection (source, profile_name, profile_seq_id,
username, has_private_key, has_passphrase, has_password). New GET /api/connections/export (CSV, no
secrets, profile by seq_id). New POST /api/connections/import (CSV, matches profile by seq_id, creates
connections with profile_not_found flag if seq_id missing, all input sanitised). Windows platform entry
added to PLATFORM_AUTH in OptionsModal.jsx (username/password/winrm_auth_method/account_type/use_ssl).
New api/collectors/windows.py stub collector registered in manager.

**v2.27.1** — Discovery harvest backend.
New api/routers/discovery.py: POST /harvest (Proxmox VMs + UniFi clients + Swarm nodes, passive only,
cross-referenced vs existing connections, stored in status_snapshots component=discovery_harvest).
GET /devices (last harvest, unlinked_only filter). POST /test (test IP with profile, auth-type-aware).
POST /link (create connection from discovered device). All IP/CIDR validated with ipaddress module —
no raw user strings in SQL. Discovery scopes applied from settings key discoveryScopes.

**v2.27.2** — Frontend: Credential Profiles tab overhaul.
ProfileForm rewritten: all auth types (ssh, windows, api, token_pair, basic) with appropriate fields.
SSH: private_key + passphrase + password + username; passphrase security hint. Windows: username format
detector, winrm_auth_method, account_type with lockout warning for domain/service. API: api_key +
header_name + prefix. Token pair: token_id + secret. discoverable toggle in form. Profiles section
replaces collapsible accordion with always-visible prominent block: seq_id badge, linked_connections_count,
has_private_key/has_passphrase indicators, delete warning if linked.

**v2.27.3** — Frontend: Connections form overhaul + import/export.
Profile picker added for SSH-capable platforms (vm_host, windows, fortiswitch, cisco, juniper, aruba).
When profile active: credential fields show "from profile" in cyan/greyed; username override allowed
with amber warning; private key field disabled (no override). Badge per connection list item:
⊕ CRED PROFILE, ⚠ INLINE CREDS, ⚠ PROFILE MISSING. Import CSV button (file picker, base64 encoded,
result display). Export CSV button (downloads file). vm_host fields reordered: SSH User → Private Key →
Passphrase → Password. shared_credentials removed from advancedConfigFields.

**v2.27.4** — Frontend: RotationTestModal component.
New gui/src/components/RotationTestModal.jsx: triggered when saving profile credential changes.
Calls POST /api/credential-profiles/{id}/test-rotation, shows animated per-connection results.
All pass → auto-confirms save. Failures → shows list + Save anyway button (sith_lord: one-click;
imperial_officer: requires override_reason textarea; stormtrooper: not available). Override logged
via POST /confirm-rotation. Connected to ProfileForm onSave in ConnectionsTab via rotationModal state.
OptionsModal gets userRole prop, passed down to ConnectionsTab and RotationTestModal.

**v2.27.5** — Frontend: Discovered view.
Adds 'Discovered' nav item under MONITOR in Sidebar.jsx. New gui/src/components/DiscoveredView.jsx:
harvest button + manual IP entry (add/remove list). Table: source badge (PROXMOX/UNIFI/SWARM/MANUAL),
host, platform_guess, linked indicator. Per-row: profile dropdown (discoverable profiles only) + Test
button → inline result. Create connection button appears on successful test → pre-filled modal (label,
platform, role). Filter by source + linked/unlinked. App.jsx routes 'Discovered' to DiscoveredView.

**v2.27.6** — Settings: discovery scope + rotation concurrency.
New DiscoveryScopeList component: CIDR/subnet list with add/remove, client-side validation accepting
both CIDR (192.168.0.0/24) and subnet mask notation (192.168.0.0 255.255.255.0), injection-safe.
Added to InfrastructureTab as Discovery section with discoveryEnabled toggle + discoveryScopes list.
Added to GeneralTab as Rotation Test section: rotationTestMode select, rotationTestDelayMs,
rotationWindowsDelayMs, rotationMaxParallel inputs with AD lockout warning. Six new settings keys
seeded with defaults in api/routers/settings.py.

**v2.26.6** — Entity detail performance.
Adds GET /api/entities/find/{entity_id:path} endpoint. Loads only the relevant collector's
snapshot (1 DB query, prefix-mapped). 30s in-memory cache. Falls back to full scan for
bare labels (vm_host). EntityDrawer switches to this endpoint: ~5ms vs ~300ms.

**v2.26.7** — VM Hosts entity detail + naming.
vm_hosts.py: stamps entity_id=label on every VM card; adds to_entities() to VMHostsCollector.
VMHostsSection.jsx: adds onEntityDetail prop to VMCard; adds ⌘ and › buttons in header.
App.jsx: passes onEntityDetail to VMHostsSection. DashboardLayout.jsx: adds
TILE_DISPLAY_NAMES — "VM_HOSTS" tile renders as "VM Hosts", all others cleaned up too.

**v2.29.5** — fix(ui): filter bar vertical centering + revert wrong ProxmoxCard centering.
ServiceCards.jsx Section Row 2: adds `display:flex; alignItems:center` to filterBar wrapper
so chips sit vertically centred in the row (was top-aligned). ProxmoxCardCollapsed: removes
`textAlign:center` from vCPU/RAM line and reverts `justify-center` to `justify-start` on
badges row — restores left-aligned card content consistent with all other card types.

**v2.30.0** — fix(proxmox): multi-connection support in Proxmox action paths.
`_do_proxmox_action` in api/routers/dashboard.py: loads proxmox_vms snapshot, matches the
target `node` to the cluster that contains it, uses that cluster's connection_id for
credentials — eliminates always-first-connection bug in multi-cluster setups. Falls back
to first connection when snapshot match fails. `proxmox_vm_power` in mcp_server/tools/vm.py:
iterates all Proxmox connections via get_all_connections_for_platform, tries each until the
VM matching vm_label is found — same fix for agent-driven power actions.

**v2.30.1** — fix(auth): remove token from localStorage, cookie-first auth.
AuthContext.jsx: token held in React state (memory) only — no longer written to
localStorage. Mount validates session via httpOnly cookie (credentials: include). Logout
calls POST /api/auth/logout to clear server-side cookie. api.js: authHeaders() returns {}
(cookie handles same-origin auth automatically); SSE URL builders drop ?token= param.
api/routers/dashboard.py: three SSE stream endpoints (containers, unified, vm-hosts) gain
`request: Request` param and fall back to httpOnly cookie when no ?token= supplied —
EventSource sends same-origin cookies automatically.

---

## Key file paths

```
api/routers/entities.py                   — /find/{id} fast path + cache (v2.26.6)
gui/src/components/EntityDrawer.jsx       — uses /find/{id} endpoint (v2.26.6)
api/collectors/vm_hosts.py                — entity_id + to_entities() (v2.26.7)
gui/src/components/VMHostsSection.jsx     — ask/detail buttons + onEntityDetail (v2.26.7)
gui/src/App.jsx                           — onEntityDetail passed to VMHostsSection (v2.26.7)
gui/src/components/DashboardLayout.jsx    — TILE_DISPLAY_NAMES, "VM Hosts" label (v2.26.7)
api/agents/router.py                      — allowlists, prompts, classifier (v2.26.2, v2.26.3)
api/routers/agent.py                      — loop, plan gate, ambiguous label (v2.26.2, v2.26.5)
api/db/runbooks.py                        — BASE_RUNBOOKS + seed_base_runbooks() (v2.26.4)
api/db/vm_exec_allowlist.py               — allowlist table + cache + session purge (v2.23.3)
api/routers/vm_exec_allowlist.py          — REST API for allowlist management (v2.23.3)
mcp_server/tools/vm.py                    — _validate_command DB-backed + 3 new tools (v2.23.3)
gui/src/components/OptionsModal.jsx       — Allowlist tab (v2.23.3)
api/routers/settings.py                   — agentHostIp setting key (v2.22.6)
api/collectors/docker_agent01.py          — started_at + restart_count in card + metadata (v2.26.8)
api/db/credential_profiles.py             — seq_id, discoverable, get_profile_safe, get_profile_by_seq_id (v2.26.9)
api/db/audit_log.py                       — connection_audit_log table + write/list events (v2.26.9)
api/connections.py                        — username_cache column + credential_state in list (v2.26.9, v2.27.0)
api/routers/credential_profiles.py        — rotation test/confirm, safe fields, audit (v2.26.10)
api/routers/connections.py                — CSV export/import endpoints (v2.27.0)
api/collectors/windows.py                 — Windows/WinRM stub collector (v2.27.0)
api/routers/discovery.py                  — harvest, devices, test, link endpoints (v2.27.1)
gui/src/components/RotationTestModal.jsx  — rotation test modal with role-gated override (v2.27.4)
gui/src/components/DiscoveredView.jsx     — discovered devices view (v2.27.5)
gui/src/components/Sidebar.jsx            — Discovered nav item under MONITOR (v2.27.5)
api/collectors/docker_agent01.py          — entity_id + to_entities() per container (v2.26.0)
api/collectors/swarm.py                   — entity_id + to_entities() per service (v2.26.0)
api/collectors/external_services.py      — entity_id on all probe returns (v2.26.0)
api/collectors/unifi.py                   — entity_id per device in _build_result (v2.26.0)
api/collectors/pbs.py                     — entity_id per datastore in _poll_one_conn (v2.26.0)
api/collectors/truenas.py                 — entity_id per pool in _collect_sync (v2.26.0)
api/collectors/fortigate.py               — entity_id per interface in _collect_sync (v2.26.0)
gui/src/components/ServiceCards.jsx       — InfraCard universal entity buttons (v2.26.1)
api/routers/dashboard.py                  — _vm_ssh_exec credential fix + Proxmox action fix (v2.23.0)
api/db/infra_inventory.py                 — resolve_entity + write_cross_reference (v2.23.1)
api/collectors/proxmox_vms.py             — write VMs to infra_inventory (v2.23.1)
gui/src/context/DashboardDataContext.jsx  — shared dashboard state + version gate (v2.22.0)
api/db/metric_samples.py                  — time-series metrics (v2.21.0)
mcp_server/tools/metric_tools.py          — metric_trend + list_metrics (v2.21.0)
```
