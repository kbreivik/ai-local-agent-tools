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
| CC_PROMPT_v2.30.0.md  | v2.30.0  | fix(proxmox): multi-connection support in Proxmox action paths | DONE (00e7d36) |
| CC_PROMPT_v2.30.1.md  | v2.30.1  | fix(auth): remove token from localStorage, cookie-first auth | DONE (733745b) |
| CC_PROMPT_v2.31.0.md  | v2.31.0  | feat(docs): Bookstack sync — periodic harvest into RAG doc_chunks | DONE (4da63fd) |
| CC_PROMPT_v2.26.7.md | v2.26.7 | VM Hosts: entity_id, to_entities(), ask/detail buttons, naming fix | DONE (11f9dc8) |
| CC_PROMPT_v2.31.1.md  | v2.31.1  | fix(security): crypto boot-safety + key fingerprint + canary | DONE (3c6feb7) |
| CC_PROMPT_v2.31.2.md  | v2.31.2  | feat(security): agent_actions audit table for destructive tool calls | DONE (7380084) |
| CC_PROMPT_v2.31.3.md  | v2.31.3  | fix(auth): WebSocket cookie-based auth — restore live output | DONE (e04d729) |
| CC_PROMPT_v2.31.4.md  | v2.31.4  | feat(ops): deathstar-backup.sh + verify-bundle.sh with key fingerprint | DONE (e54941a) |
| CC_PROMPT_v2.31.5.md  | v2.31.5  | feat(security): encryption key rotation CLI | DONE (207bc0e) |
| CC_PROMPT_v2.31.6.md  | v2.31.6  | feat(ui): Recent Actions audit tab in Logs | DONE (de4df45) |
| CC_PROMPT_v2.31.7.md  | v2.31.7  | feat(security): prompt injection sanitiser for LLM-bound content | DONE (7221633) |
| CC_PROMPT_v2.31.8.md  | v2.31.8  | feat(security): agent loop hard caps (wall-clock, tokens, destructive, failures) | DONE (d265f82) |
| CC_PROMPT_v2.31.9.md  | v2.31.9  | feat(templates): reboot_proxmox_vm agent task template | DONE (5111f02) |
| CC_PROMPT_v2.31.10.md | v2.31.10 | feat(security): maintenance / blackout windows | DONE (eea4399) |
| CC_PROMPT_v2.31.11.md | v2.31.11 | feat(tests): regression tests for tool safety + frontend sync | DONE (9f4995f) |
| CC_PROMPT_v2.31.12.md | v2.31.12 | feat(ci): Dockerfile at repo root + queue runner builds and pushes image | DONE (9c56b54) |
| CC_PROMPT_v2.31.13.md | v2.31.13 | fix(ci): unbreak CI — lockfile sync + workflow version step + undo v2.31.12 duplicates | DONE (930efa7) |
| CC_PROMPT_v2.31.14.md | v2.31.14 | fix(ui): empty plan modal + Logs default tab + Full-log to Operations | DONE (ed31225) |
| CC_PROMPT_v2.31.15.md | v2.31.15 | feat(windows): real WinRM collector + auth-verified discovery test | DONE (972a23a) |
| CC_PROMPT_v2.31.16.md | v2.31.16 | fix(windows): WMI-free POLL script + dedicated WINDOWS dashboard section | DONE (c3f67c8) |
| CC_PROMPT_v2.31.17.md | v2.31.17 | fix(windows): swap pywinrm→pypsrp (PSRP over Microsoft.PowerShell endpoint) | DONE (f88f6b7) |
| CC_PROMPT_v2.31.18.md | v2.31.18 | docs(windows): WINDOWS_SETUP.md + README index entry | DONE (14a4951) |
| CC_PROMPT_v2.31.19.md | v2.31.19 | chore(ci): paths-ignore cc_prompts/** + docs/** to skip redundant builds | DONE (aa51dda) |
| CC_PROMPT_v2.31.20.md | v2.31.20 | fix(windows): WindowsSection reads from DashboardDataContext | DONE (ed65266) |
| CC_PROMPT_v2.31.21.md | v2.31.21 | fix(windows): OS name Win11, uptime fallback, WinRM false-positive | DONE (22f7c73) |
| CC_PROMPT_v2.31.22.md | v2.31.22 | fix(auth): profile-first credential resolution + passphrase kwarg | DONE (11684c9) |
| CC_PROMPT_v2.32.0.md  | v2.32.0  | refactor(agents): structured system prompts for observe + investigate | DONE (5e2465f) |
| CC_PROMPT_v2.32.1.md  | v2.32.1  | refactor(agents): structured system prompts for execute + build | DONE (cf60ded) |
| CC_PROMPT_v2.32.2.md  | v2.32.2  | feat(agents): post-action verify step | DONE (c580c48) |
| CC_PROMPT_v2.32.3.md  | v2.32.3  | feat(agents): attempt history table + context injection | DONE (4a71334) |
| CC_PROMPT_v2.32.4.md  | v2.32.4  | fix(agents): final_answer truncation at 300 chars | DONE (306044f) |
| CC_PROMPT_v2.32.5.md  | v2.32.5  | feat(agents): enforced tool call budgets per agent type | DONE (e3ce56c) |
| CC_PROMPT_v2.32.6.md  | v2.32.6  | feat(infra): version-check refresh button + configurable timers | DONE (d1449e4) |
| CC_PROMPT_v2.33.0.md  | v2.33.0  | feat(tools): kafka_topic_inspect — structured cluster state in one call | DONE (8802c92) |
| CC_PROMPT_v2.33.1.md  | v2.33.1  | feat(templates): drain_swarm_node task template | DONE (d62c7c7) |
| CC_PROMPT_v2.33.2.md  | v2.33.2  | feat(templates): diagnose_kafka_under_replicated fixed 4-step RCA | DONE (47638f1) |
| CC_PROMPT_v2.33.3.md  | v2.33.3  | feat(agents): mandatory sub-agent proposal near budget exhaustion | DONE (363a774) |
| CC_PROMPT_v2.33.4.md  | v2.33.4  | feat(skills): auto-promoter for repeated vm_exec patterns | DONE (d7e0c0f) |
| CC_PROMPT_v2.33.5.md  | v2.33.5  | feat(ops): Prometheus /metrics endpoint | DONE (010ddbd) |
| CC_PROMPT_v2.33.6.md  | v2.33.6  | feat(security): blast radius tagging + tiered plan confirmation | DONE (e1edcae) |
| CC_PROMPT_v2.33.7.md  | v2.33.7  | feat(ui): Kafka inspection tab — brokers, topics, partitions, lag | DONE (323a342) |
| CC_PROMPT_v2.33.8.md  | v2.33.8  | feat(templates): verify_backup_job + PBS last-success tracking | DONE (21a7a0b) |
| CC_PROMPT_v2.33.9.md  | v2.33.9  | feat(security): drift detection — config_hash reconciliation + badge | DONE (636cf2f) |
| CC_PROMPT_v2.33.10.md | v2.33.10 | feat(ui): container pull — in-card progress + eager version controls | DONE (0b3255b) |
| CC_PROMPT_v2.33.11.md | v2.33.11 | fix(tools): elastic_search_logs level kwarg + aliases | DONE (5808505) |
| CC_PROMPT_v2.33.12.md | v2.33.12 | feat(agents): zero-result pivot detection — 3-in-a-row nudge | DONE (41398f2) |
| CC_PROMPT_v2.33.13.md | v2.33.13 | feat(agents): contradiction detection in synthesis | DONE (f0e84b4) |
| CC_PROMPT_v2.33.14.md | v2.33.14 | feat(tools): elastic_search_logs rich query metadata + hint | DONE (cba6198) |
| CC_PROMPT_v2.33.15.md | v2.33.15 | feat(ui): live agent diagnostics overlay | DONE (d575a1a) |
| CC_PROMPT_v2.33.16.md | v2.33.16 | fix(ui): smoother pull bar — phase-weighted monotonic percent + matched transition | DONE (59ee72c) |
| CC_PROMPT_v2.33.17.md | v2.33.17 | fix(security): docker_host SSH credentials from profiles, not other connections | DONE (18c3ea4) |
| CC_PROMPT_v2.33.18.md | v2.33.18 | feat(templates): recover_worker_node composite task template | DONE (8e09718) |
| CC_PROMPT_v2.33.19.md | v2.33.19 | feat(tools): log_timeline — unified cross-source timeline per entity | PENDING |
| CC_PROMPT_v2.33.20.md | v2.33.20 | feat(security): Gates dashboard + drift/maintenance-window suppression | PENDING |
| CC_PROMPT_v2.34.0.md  | v2.34.0  | feat(agents): sub-agent execution in isolated sub-context | PENDING |

---

## Version bump rationale

| Bump | Meaning |
|---|---|
| x.x.1 | Fix, tuning, small addition |
| x.1.x | New subsystem, architectural change, multi-file feature |

---

## Phase summaries

**v2.32.0–v2.32.3** — Harness Tightening phase (representation + runtime).
See individual entries below.

**v2.32.0** — refactor(agents): structured system prompts for observe + investigate.
Restructures STATUS_PROMPT and RESEARCH_PROMPT into labeled ═══ SECTION ═══ sections.
No logic changes. Representation-only, based on Tsinghua NLH research.

**v2.32.1** — refactor(agents): structured system prompts for execute + build.
Completes prompt restructuring for all 4 agent types. Same ═══ SECTION ═══ pattern.

**v2.32.2** — feat(agents): post-action verify step.
Harness auto-calls verification tool after destructive ops succeed (force-update →
service_health, proxmox_power → swarm_node_status, upgrade → post_upgrade_verify).

**v2.32.3** — feat(agents): attempt history table + context injection.
New agent_attempts table. Injects last 3 attempts per entity into system prompt.

**v2.32.4** — fix(agents): final_answer truncation at 300 chars.
verdict_from_text() truncated summary to text[:300], and _stream_agent used
prior_verdict["summary"] as last_reasoning → final_answer always cut to 300 chars.
Fix: preserve full step output in verdict dict via "full_output" key, use it for
final_answer. Also increases verdict summary from 300→1500 chars for better
coordinator context.

**v2.32.5** — feat(agents): enforced tool call budgets per agent type.
Adds _MAX_TOOL_CALLS_BY_TYPE: observe=8, investigate=16, execute=14, build=12.
Checked at start of each LLM step — when exhausted, harness forces a summary with
no further tool calls. Previously only max_steps (LLM rounds) was enforced but one
step can fire multiple tool calls.

**v2.32.6** — feat(infra): version-check refresh button + configurable timers.
Fixes stale-cache issue where a new image push could take up to 10 min to appear
in the expanded ghcr container card. Adds `?force=1` on `/containers/{id}/tags`
to bypass `_GHCR_TAG_CACHE`, a "↻ Refresh versions" button in the expanded card,
and two new DB-backed Settings → Infrastructure knobs: `ghcrTagCacheTTL` (default
600s) and `autoUpdateInterval` (default 300s).

---

## Phase: v2.33.x — Test-Fix-Verify expansion (10 cycles)

Paired with `reports/test_cycles.html` — a paged HTML report with per-cycle
status (Discovered / Planned Fix / Post-Fix Verify) saved to localStorage.
Each version below has one matching cycle in the report. Open the report,
run the pre-fix test plan, mark status as `testing`, then run the prompt,
then mark `verified` after the post-fix verify passes.

**v2.33.0** — feat(tools): kafka_topic_inspect — structured cluster state in one call.
New MCP tool returning `{brokers[], topics[{partitions[{leader,replicas,isr,under_replicated}]}], summary}` via `KafkaAdminClient`. Added to OBSERVE + INVESTIGATE allowlists. Triage order updated so kafka_topic_inspect is the first call for any kafka query, then kafka_consumer_lag, then kafka_exec for deep dives. Replaces the 4-5 call chain agents currently use to reconstruct ISR.

**v2.33.1** — feat(templates): drain_swarm_node task template.
Agent template in SWARM group, inputs: node_name + timeout_s. Sequence: swarm_node_status → plan_action for `docker node update --availability drain` → poll `docker node ps` until zero running tasks. Execute-agent, blast_radius=node, destructive=True. Closes the manual drain step before worker-03 reboots.

**v2.33.2** — feat(templates): diagnose_kafka_under_replicated fixed 4-step RCA.
Investigate-agent template chaining kafka_topic_inspect (v2.33.0) → service_placement → swarm_node_status → optional proxmox_vm_power(status). Uses `prompt_override` to enforce STRICT output shape: MISSING_BROKERS / IMPACT / ROOT_CAUSE / RESPONSIBLE_NODE / RECOMMENDED_FIX. Router gains prompt_override support keeping Role+Environment sections while replacing body.

**v2.33.3** — feat(agents): mandatory sub-agent proposal near budget exhaustion.
Strengthens propose_subtask (v2.24.0). When tools_used >= 70% of budget without a `DIAGNOSIS:` section, harness injects a nudge and agent MUST call propose_subtask next. OutputPanel renders a clickable inline sub-task offer card (accent border), emits WS `subtask_proposed` + `budget_nudge` events. agent_attempts gains was_proposal column for measurement.

**v2.33.4** — feat(skills): auto-promoter for repeated vm_exec patterns.
New background worker auto_promoter scans agent_actions weekly: `(tool, args_shape)` with count ≥ 5 across ≥ 2 tasks becomes a skill_candidates row. SHAPE_RULES normalises vm_exec to (host, first_command_token). Skills tab gains Candidates subtab with Approve/Reject/Scan-now buttons. Approved candidates flow through existing skill_create (v2.13.0).

**v2.33.5** — feat(ops): Prometheus /metrics endpoint.
New `api/metrics.py` module with stable `deathstar_*` metric families: collector poll histogram, agent task counter, tool-call counter, agent wall-time histogram, escalation counter, kafka under-replicated gauge, build info. Mounted at unauthenticated GET /metrics. CollectorManager.trigger_poll wrapped, agent loop counts tool calls + terminal status, escalations increment on record.

**v2.33.6** — feat(security): blast radius tagging + tiered plan confirmation.
New `api/agents/tool_metadata.py` with `BLAST_RADIUS = {none, node, service, cluster, fleet}`. Each destructive tool annotated. `radius_of(tool, args)` does arg-based escalation for vm_exec/kafka_exec. Plan payload enriched with radius per step + plan_radius. PlanModal renders colored pills (green/amber/red/violet) + extra-confirm checkbox required for cluster+ radii. Plans with >1 fleet-radius step rejected at backend.

**v2.33.7** — feat(ui): Kafka inspection tab — brokers, topics, partitions, lag.
New sidebar entry under MONITOR. Backend `/api/kafka/overview` aggregates v2.33.0 kafka_topic_inspect + kafka_consumer_lag, cached 30s (configurable kafkaOverviewCacheTTL setting). UI: 3-pane grid — broker list (left), topic grid with under-replicated + max-lag columns (centre), partition drill-in with ISR vs Replicas (right). Polls every 15s client-side. Amber rows for under-replicated topics.

**v2.33.8** — feat(templates): verify_backup_job + PBS last-success tracking.
PBS collector extended to enumerate `/admin/datastore/{s}/snapshots` and record last_success_ts per (backup_type, backup_id). Cross-reference written so VMCard can join. New MCP tool pbs_last_backup(vm_id) returns {status, age_hours, last_success_ts, datastore}. Task template verify_backup_job in STORAGE group, default max_age_hours=25. VMCard gets green/amber freshness dot.

**v2.33.9** — feat(security): drift detection — config_hash reconciliation + badge.
entity_history gains config_hash + prev_config_hash columns; `compute_config_hash` ignores volatile keys (uptime, cpu_usage, etc.). New `drift_events` view flags hash changes without a sanctioned agent_action within ±60s. `/api/entity/{id}/drift` + `/api/drift/recent` endpoints. Cards get ⚠ DRIFT badge (amber) — clicking opens investigate_drift template pre-scoped to the entity. Enforces DEATHSTAR as the single source of truth for changes.

**v2.33.10** — feat(ui): container pull — in-card progress + eager version controls.
Three coordinated fixes for the ghcr container update flow. (1) New async pull API: `POST /containers/{id}/pull-start` returns a job_id; `GET /pull-jobs/{id}` reports layer-aggregated bytes_done/bytes_total + phase (downloading/extracting/recreating/done/error). Uses `client.api.pull(stream=True, decode=True)` for live Docker events. (2) Frontend lifts full tags list from ContainerCardExpanded to ServiceCards parent — Choose version + Refresh buttons render instantly on expand, no fetch-on-mount delay. Full tags cached, not just `[0]`. (3) In-card progress block with phase label, percent bar, message, layer byte counter, DISMISS button; replaces the bottom-right "Done" toast for pull success. Errors remain inline too. Self-container (hp1_agent) preserves the sidecar-recreate path.

---

## Phase: v2.33.11–v2.33.15 — Agent Reasoning Quality

Surfaced by live investigate trace on 2026-04-17 09:39 (`Search Elasticsearch for error-level log entries in the last 1 hour`). The trace confirmed v2.33.3 works correctly (budget nudge fired at 11/16, propose_subtask called at step 12) but surfaced three concrete bugs: (1) `elastic_search_logs` rejected `level=` kwarg with `TypeError`, (2) agent issued 7 consecutive zero-result calls without pivoting, (3) final answer concluded "no errors found" despite step 3 returning 90 log entries. This phase fixes all three and adds live observability into the harness.

**v2.33.11** — fix(tools): elastic_search_logs level kwarg + aliases.
Add `level: Union[str, Sequence[str], None]` parameter with case-insensitive normalisation (err↔error, warn↔warning, crit↔critical). Silent aliases `severity=` and `log_level=` map to the same filter. Response envelope gains `applied_filters`, `total_in_window`, `index`. Updates MCP manifest + RESEARCH_PROMPT ELK section. Regression test locks in that `level=` kwarg is permanently accepted.

**v2.33.12** — feat(agents): zero-result pivot detection — 3-in-a-row nudge.
Harness tracks `_zero_streaks` + `_nonzero_seen` per tool per task. When the same tool returns 0 results 3 consecutive times AFTER having returned non-zero earlier, injects a system nudge instructing the agent to (a) synthesize from the non-zero call, (b) broaden the filter, or (c) switch tools. Also nudges at 4 consecutive zeros even without prior non-zero (likely wrong tool). Emits WS `zero_result_pivot` event; OutputPanel shows amber PIVOT NUDGE banner. `_result_count()` helper handles hits[]/total/count/"Found N" summary shapes.

**v2.33.13** — feat(agents): contradiction detection in synthesis.
Before emitting final_answer, harness scans the draft for negative claims (`no X`, `zero X`, `not found`, `nothing detected`) and cross-references tool history. If any prior call returned non-zero results for a related query, emits WS `contradiction_detected` event, red OutputPanel banner, and injects a system message asking the agent to reconcile (acknowledge the earlier data) or revise. One reconciliation attempt per task; unresolved contradictions surface as a `[HARNESS WARNING]` prefix on final_answer.

**v2.33.14** — feat(tools): elastic_search_logs rich query metadata + hint.
Extends v2.33.11 response envelope with `total_relation`, `query_lucene` (serialised ES query body for debugging), and an auto-generated `hint` string when `total == 0 and total_in_window > 0`. Hint names the active filters and suggests which to drop first (host → service → level → query). Same envelope applied to `elastic_log_pattern`. Prompt updated so the agent is told to read and respond to `hint` when present.

**v2.33.15** — feat(ui): live agent diagnostics overlay.
New `AgentDiagnostics` component rendered at top of OutputPanel during investigate runs. Compact horizontal bar shows: tool budget (N/max with coloured progress bar), DIAGNOSIS emitted (· not yet / ✓ emitted), per-tool zero-streak badges (e.g. `e_search×4`), pivot nudge count, SUBTASK PROPOSED indicator. Backend emits periodic `agent_diagnostics` WS events after each tool call. Makes harness state visible to operator in real-time — they can see the agent struggling before budget exhaustion.

**v2.33.16** — fix(ui): smoother pull bar — phase-weighted monotonic percent + matched transition.
Follow-up to v2.33.10. Observed in live use: percent text advanced but the bar appeared bumpy — stalling or stepping backward. Three root causes in `api/routers/dashboard.py::_update_pull_job`: (1) `bytes_total` was recomputed as the sum of all discovered layers, so as Docker streamed new layer headers the denominator grew faster than `bytes_done`, making raw `int(done/total*100)` *decrease* between polls; (2) the `done` callsite passed `percent=100` via kwargs but the function applied kwargs first and then overwrote percent with the layer recomputation; (3) CSS `transition: 0.3s ease` with a 600 ms poll interval left the bar idle for 300 ms per cycle. Fix replaces raw byte math with fixed phase bands (starting 0–5%, downloading 5–70%, extracting 70–92%, recreating 92–98%, done 100%), scales within each band by bytes (download) or layer completions (extract), and enforces `max(prev, pct)` monotonicity per job. Explicit percent only raises, never lowers. `error` freezes at last-seen percent rather than resetting. Frontend transition bumped to `650ms linear` so the bar interpolates continuously across poll boundaries instead of finishing early and pausing.

**v2.33.17** — fix(security): docker_host SSH credentials from profiles, not other connections.
The docker_host platform form was the last holdout using a different credential source pattern from every other SSH-capable platform. Its SSH-tunnel mode exposed a "Credentials from" dropdown (`_ssh_source`) that let the user inherit credentials from another vm_host connection, creating invisible cross-connection dependencies, breaking rotation test coverage (profile rotation tests don't follow `_ssh_source` chains), and making the `credential_state` audit field inaccurate. Fix removes `_ssh_source` entirely and wires docker_host into the same `credential_profile_id` picker used by vm_host/windows/fortiswitch/cisco/juniper/aruba, filtered to SSH-typed profiles. Backend credential resolution switches to the standard profile-first resolver from v2.31.22. Alembic migration rewrites existing `_ssh_source` values — if the source vm_host had a profile, the docker_host inherits its `credential_profile_id`; otherwise `_ssh_source` is stripped and a warning is logged. New `credential_state.source = needs_profile` plus a red ⚠ NEEDS PROFILE badge surface rows that require manual relinking. Establishes credential profiles as the single source of truth for all connection credentials.

---

## Phase: v2.33.18–v2.33.20 + v2.34.0 — Operations Maturity

Four prompts that close the remaining gaps in the tasks/tools/gates/sub-agents stack. The first three stay within 2.33.x as iterative additions to existing subsystems. The fourth bumps to 2.34.0 because it introduces the sub-agent runtime — a new subsystem and multi-file architectural change. Rule: once v2.34.0 ships, no further 2.33.x prompts are written.

**v2.33.18** — feat(templates): recover_worker_node composite task template.
First composite task template that includes verification as part of its own chain rather than relying only on v2.32.2's post-action verify. Sequence: swarm_node_status (pre-check) → service_placement (inventory) → plan_action + proxmox_vm_power(reboot) → poll swarm_node_status until Ready or timeout → swarm_service_force_update for each service that didn't auto-reschedule → swarm_node_status + kafka_topic_inspect for verification. Closes the worker-03 manual loop that's been running the same sequence by hand for weeks. Execute-agent, blast_radius=node, destructive=True, always shows plan modal. Required inputs: node_name, proxmox_vm_label; optional ready_timeout_s (default 180).

**v2.33.19** — feat(tools): log_timeline — unified cross-source timeline per entity.
New MCP tool returning a chronologically merged timeline for an entity, drawing from operation_log (agent tool calls), agent_actions (destructive audit v2.31.2), entity_history (status transitions + drift v2.33.9), and Elasticsearch logs (filtered to entity's host/service in the window). Single call replaces the 4-5 separate lookups agents currently use to reconstruct "what happened to X". Normalised event schema: `{ts, source, kind, actor, summary, detail}`. Added to observe and investigate allowlists. RESEARCH_PROMPT updated so the agent reaches for log_timeline first on "what happened" questions and only falls back to raw elastic_search_logs for regex/field-specific needs.

**v2.33.20** — feat(security): Gates dashboard + drift/maintenance-window suppression.
Two coupled changes: (1) New Gates view under MONITOR aggregates plan-confirmation rate by blast radius, escalations (open vs acknowledged), drift events (open/acknowledged/suppressed), agent hard-cap triggers (wall-clock, token, failure, destructive from v2.31.8), top-20 tool refusals, and active maintenance windows. GET /api/gates/overview endpoint with configurable window_hours (6/24/72/168, capped at 168). 30s client poll. (2) Drift events fired on entities inside an active maintenance window auto-mark `suppressed_by_maintenance = true` and emit a different WS event (`drift_suppressed` vs `drift_detected`) so the card doesn't show amber DRIFT during planned work. drift_events gains the column via Alembic migration. Closes the gap where the safety machinery runs but has no single operator-visible health view.

**v2.34.0** — feat(agents): sub-agent execution in isolated sub-context.
Architectural completion of the sub-agent story. Since v2.24.0 the parent could propose a sub-task and v2.33.3 nudged it near budget exhaustion, but proposals only rendered as clickable cards the operator had to run manually. This change makes the harness intercept propose_subtask and spawn an actual sub-agent with its own context window, its own tool budget, and its own depth counter. Parent awaits completion, receives the sub-agent's final_answer + diagnosis as the tool_result of propose_subtask, and resumes with the summary in hand. Sub-agents can themselves spawn sub-sub-agents up to `subagentMaxDepth` (default 2). Budget cap: sub cannot exceed parent's remaining minus `subagentMinParentReserve` (default 2). Tree-wide wall-clock cap `subagentTreeWallClockS` (default 1800) prevents runaway chains. Destructive operations forbidden in sub-agents unless explicit `allow_destructive=true` AND parent is execute-type AND depth=1. Fresh context rule: sub-agent receives only the objective, a 3-line parent summary, and its scope entity — **not** the parent's full tool history. Refactor `_stream_agent` into a reusable `drive_agent(AgentTask) → AgentResult` driver so both top-level and sub-agents share the same loop. New `subagent_runs` table links parent and sub task IDs + terminal outcome. New `SubAgentPanel` React component renders indented under the parent's OutputPanel with its own collapsible WS stream. Closes the biggest remaining architectural gap in the agent design.

---

## Key file paths

```
api/routers/entities.py                   — /find/{id} fast path + cache (v2.26.6)
gui/src/components/EntityDrawer.jsx       — uses /find/{id} endpoint (v2.26.6)
api/collectors/vm_hosts.py                — entity_id + to_entities() (v2.26.7)
gui/src/components/VMHostsSection.jsx     — ask/detail buttons + onEntityDetail (v2.26.7)
gui/src/App.jsx                           — onEntityDetail passed to VMHostsSection (v2.26.7)
gui/src/components/DashboardLayout.jsx    — TILE_DISPLAY_NAMES, "VM Hosts" label (v2.26.7)
api/agents/router.py                      — allowlists, prompts, classifier (v2.26.2, v2.26.3, v2.32.0, v2.32.1)
api/agents/orchestrator.py                — verdict_from_text, coordinator (v2.10.0, v2.32.4)
api/routers/agent.py                      — loop, plan gate, verify, budgets (v2.32.2, v2.32.3, v2.32.4, v2.32.5)
api/db/agent_attempts.py                  — attempt history table (v2.32.3)
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
