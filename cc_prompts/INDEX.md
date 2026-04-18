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
| CC_PROMPT_v2.33.19.md | v2.33.19 | feat(tools): log_timeline — unified cross-source timeline per entity | DONE (1ffac60) |
| CC_PROMPT_v2.33.20.md | v2.33.20 | feat(security): Gates dashboard + drift/maintenance-window suppression | DONE (2934788) |
| CC_PROMPT_v2.34.0.md  | v2.34.0  | feat(agents): sub-agent execution in isolated sub-context | DONE (ebd5810) |
| CC_PROMPT_v2.34.1.md  | v2.34.1  | feat(agents): coordinator uses agent_attempts for starting-tool selection | DONE (1019f7f) |
| CC_PROMPT_v2.34.2.md  | v2.34.2  | feat(skills): execution observability + adoption metrics | DONE (03e1149) |
| CC_PROMPT_v2.34.3.md  | v2.34.3  | fix(ui): pull-bar UPDATING label + self-recreate hard-refresh instructions | DONE (3258866) |
| CC_PROMPT_v2.34.4.md  | v2.34.4  | fix(agents): verify v2.34.0 sub-agent wiring — spawn path confirmed working in 15:42 trace | PENDING · VERIFY ONLY |
| CC_PROMPT_v2.34.5.md  | v2.34.5  | fix(agents): propose_subtask math unreachable — earlier nudge + dynamic reserve | DONE (6fe25b5) |
| CC_PROMPT_v2.34.6.md  | v2.34.6  | feat(tools): elastic_search_logs auto-samples schema on filter miss | DONE (41b55c8) |
| CC_PROMPT_v2.34.7.md  | v2.34.7  | fix(ui): restore running-version marker in container tag dropdown | DONE (36d4b62) |
| CC_PROMPT_v2.34.8.md  | v2.34.8  | fix(agents): hallucination guard — require N substantive tool calls before final_answer | DONE (45ae853) |
| CC_PROMPT_v2.34.9.md  | v2.34.9  | feat(agents): inject MCP tool signatures into system prompt — stop kwarg hallucination | DONE (00c6090) |
| CC_PROMPT_v2.34.10.md | v2.34.10 | feat(vm_exec): read-only network diagnostics + safe pipe passthrough | DONE (70e6bcc) |
| CC_PROMPT_v2.34.11.md | v2.34.11 | fix(agents): classifier hard-routes investigative starters to research | DONE (b76839f) |
| CC_PROMPT_v2.34.12.md | v2.34.12 | feat(tools): container-introspection tools (config_read, env, networks, tcp_probe, discover) | DONE (8e7adaa) |
| CC_PROMPT_v2.34.13.md | v2.34.13 | fix(agents): retarget prompts to prefer container_introspect over raw docker exec | DONE (d3c14b8) |
| CC_PROMPT_v2.34.14.md | v2.34.14 | fix(agents): hallucination hardening + fabrication detection + LLM trace persistence | DONE (ba1a04f) |
| CC_PROMPT_v2.34.15.md | v2.34.15 | fix(agents): prompt signature rendering + sanitizer scope + budget off-by-one + prompt snapshots | DONE (793248a) |
| CC_PROMPT_v2.34.16.md | v2.34.16 | feat(ui): trace viewer + gates-fired digest + propose_subtask idempotency + service_placement signature | DONE (4dab532) |
| CC_PROMPT_v2.34.17.md | v2.34.17 | fix(agents): boot-time sanitizer scope + forced synthesis on budget cap | PENDING |

---

## Version bump rationale

| Bump | Meaning |
|---|---|
| x.x.1 | Fix, tuning, small addition |
| x.1.x | New subsystem, architectural change, multi-file feature |

---

## Phase summaries

**v2.32.0–v2.32.3** — Harness Tightening phase (representation + runtime).

**v2.32.0** — refactor(agents): structured system prompts for observe + investigate.
Restructures STATUS_PROMPT and RESEARCH_PROMPT into labeled ═══ SECTION ═══ sections. Representation-only, based on Tsinghua NLH research.

**v2.32.1** — refactor(agents): structured system prompts for execute + build.
Completes prompt restructuring for all 4 agent types. Same ═══ SECTION ═══ pattern.

**v2.32.2** — feat(agents): post-action verify step.
Harness auto-calls verification tool after destructive ops succeed (force-update → service_health, proxmox_power → swarm_node_status, upgrade → post_upgrade_verify).

**v2.32.3** — feat(agents): attempt history table + context injection.
New agent_attempts table. Injects last 3 attempts per entity into system prompt.

**v2.32.4** — fix(agents): final_answer truncation at 300 chars.
verdict_from_text() truncated summary to text[:300], and _stream_agent used prior_verdict["summary"] as last_reasoning → final_answer always cut to 300 chars. Fix preserves full step output via "full_output" key, raises verdict summary from 300 to 1500 chars.

**v2.32.5** — feat(agents): enforced tool call budgets per agent type.
Adds _MAX_TOOL_CALLS_BY_TYPE: observe=8, investigate=16, execute=14, build=12.

**v2.32.6** — feat(infra): version-check refresh button + configurable timers.
?force=1 on /containers/{id}/tags, Refresh versions button, ghcrTagCacheTTL + autoUpdateInterval settings.

---

## Phase: v2.33.x — Test-Fix-Verify expansion (paired with reports/test_cycles.html)

**v2.33.0** — feat(tools): kafka_topic_inspect — structured cluster state in one call.
New MCP tool returning {brokers, topics, partitions with ISR/under_replicated, summary}. OBSERVE + INVESTIGATE allowlists.

**v2.33.1** — feat(templates): drain_swarm_node task template.
Inputs node_name + timeout_s. swarm_node_status → plan_action drain → poll docker node ps.

**v2.33.2** — feat(templates): diagnose_kafka_under_replicated fixed 4-step RCA.
Chains kafka_topic_inspect → service_placement → swarm_node_status → optional proxmox_vm_power(status). Enforces STRICT output shape.

**v2.33.3** — feat(agents): mandatory sub-agent proposal near budget exhaustion.
When tools_used >= 70% without DIAGNOSIS, nudges agent to propose_subtask.

**v2.33.4** — feat(skills): auto-promoter for repeated vm_exec patterns.
Weekly scan of agent_actions: (tool, args_shape) count >= 5 across >= 2 tasks becomes a skill_candidate.

**v2.33.5** — feat(ops): Prometheus /metrics endpoint.
api/metrics.py with deathstar_* metric families. Unauthenticated /metrics.

**v2.33.6** — feat(security): blast radius tagging + tiered plan confirmation.
BLAST_RADIUS = {none, node, service, cluster, fleet}. PlanModal coloured pills + extra-confirm for cluster+.

**v2.33.7** — feat(ui): Kafka inspection tab — brokers, topics, partitions, lag.
MONITOR sidebar. /api/kafka/overview aggregates inspect + consumer_lag, 30s cache.

**v2.33.8** — feat(templates): verify_backup_job + PBS last-success tracking.
PBS collector records last_success_ts per (backup_type, backup_id). pbs_last_backup(vm_id) tool + STORAGE template.

**v2.33.9** — feat(security): drift detection — config_hash reconciliation + badge.
entity_history gains config_hash. drift_events view flags changes without sanctioned agent_action within ±60s.

**v2.33.10** — feat(ui): container pull — in-card progress + eager version controls.
POST /containers/{id}/pull-start, GET /pull-jobs/{id}, in-card progress block with DISMISS.

**v2.33.11** — fix(tools): elastic_search_logs level kwarg + aliases.
level: Union[str, Sequence[str], None] with case-insensitive normalisation. severity= and log_level= aliases.

**v2.33.12** — feat(agents): zero-result pivot detection — 3-in-a-row nudge.
Tracks _zero_streaks + _nonzero_seen. Nudges on 3 consecutive zeros after non-zero, or 4 consecutive zeros.

**v2.33.13** — feat(agents): contradiction detection in synthesis.
Before final_answer, scans for negative claims, cross-references tool history. Reconciliation attempt once per task.

**v2.33.14** — feat(tools): elastic_search_logs rich query metadata + hint.
total_relation, query_lucene, auto hint when total==0 and total_in_window>0.

**v2.33.15** — feat(ui): live agent diagnostics overlay.
AgentDiagnostics component: tool budget, DIAGNOSIS status, zero-streak badges, pivot nudge count, SUBTASK PROPOSED indicator.

**v2.33.16** — fix(ui): smoother pull bar — phase-weighted monotonic percent + matched transition.
Fixed phase bands (starting 0-5%, downloading 5-70%, extracting 70-92%, recreating 92-98%, done 100%), max(prev, pct) monotonicity, 650ms linear CSS transition matched to 600ms poll.

**v2.33.17** — fix(security): docker_host SSH credentials from profiles, not other connections.
Removes _ssh_source dropdown, wires docker_host into credential_profile_id picker. Migration + needs_profile badge.

**v2.33.18** — feat(templates): recover_worker_node composite task template.
6-step chain: swarm_node_status → service_placement → plan_action + proxmox_vm_power(reboot) → poll until Ready → swarm_service_force_update → verify (incl kafka_topic_inspect).

**v2.33.19** — feat(tools): log_timeline — unified cross-source timeline per entity.
Merges operation_log + agent_actions + entity_history + Elasticsearch logs. Normalised {ts, source, kind, actor, summary, detail}.

**v2.33.20** — feat(security): Gates dashboard + drift/maintenance-window suppression.
MONITOR Gates view aggregating plan-confirmations, escalations, drift events, hard-caps, refusals. Drift during maintenance auto-suppresses.

---

## Phase: v2.34.x — Sub-agent runtime + follow-ups

**v2.34.0** — feat(agents): sub-agent execution in isolated sub-context.
Harness intercepts propose_subtask and spawns a sub-agent with fresh context, own budget, depth counter. Parent awaits rendezvous. subagentMaxDepth=2, subagentMinParentReserve=2, subagentTreeWallClockS=1800. New subagent_runs table + SubAgentPanel React component. Refactored _stream_agent → reusable drive_agent(AgentTask) → AgentResult.

**v2.34.1** — feat(agents): coordinator uses agent_attempts for starting-tool selection.
Injects ═══ PRIOR ATTEMPTS ON THIS ENTITY ═══ section showing last 3 attempts in 7 days with outcome, tool sequence, diagnosis, and GUIDANCE. coordinatorPriorAttemptsEnabled opt-out. Routine-success skip avoids prompt bloat.

**v2.34.2** — feat(skills): execution observability + adoption metrics.
skill_executions + auto_promoter_scans tables. Skills view gains Metrics subtab (promoter health banner, candidate pipeline, per-skill run table). Prometheus counters.

**v2.34.3** — fix(ui): pull-bar UPDATING label + self-recreate hard-refresh instructions.
Header collapses all in-flight statuses into ⟳ UPDATING so it stops disagreeing with phase subtitle. Self-recreate path sets is_self_recreate=True and shows Ctrl+Shift+R + re-login instructions in an amber callout.

**v2.34.4** — fix(agents): verify v2.34.0 sub-agent wiring — spawn path confirmed working in 15:42 trace. **PENDING · VERIFY ONLY.**
Originally critical regression fix. Subsequent traces (15:42, 16:19) confirmed spawn + refuse branches both work. Keep prompt as documentation + canary counter, but downgrade to verification-only: CC greps, confirms wiring is correct, adds SUBAGENT_SPAWN_COUNTER with proposal_only label for future regression detection.

**v2.34.5** — fix(agents): propose_subtask math unreachable — earlier nudge + dynamic reserve.
Nudge threshold 0.70 → 0.60. Dynamic reserve: parent with no DIAGNOSIS at >=60% usage → reserve=0. For budget=16 this makes spawn viable: fires at used=10, remaining=5 after propose call, max sub=3.

**v2.34.6** — feat(tools): elastic_search_logs auto-samples schema on filter miss.
When total==0 AND total_in_window>0, runs no-filter sample, extracts top 20 field names via dict flattening, heuristically maps {service, host, level} candidates against shipper patterns (service.name, container.name, kubernetes.labels.app, log.level, etc). Returns sample_docs, available_fields, suggested_filters.

**v2.34.7** — fix(ui): restore running-version marker in container tag dropdown.
Regression: tag-dropdown lost the ▶ prefix + (running) suffix on the current version. Fix restores both with bold + accent styling, threads runningTag prop from parent.

**v2.34.8** — fix(agents): hallucination guard — require N substantive tool calls before final_answer.
Trace 15:42 showed sub-agent emitting a confident final_answer with fabricated numbers after one audit_log call. Tracks substantive_tool_calls separately (META_TOOLS set: audit_log, runbook_search, memory_recall, propose_subtask, engram_activate, plan_action does not count). Blocks final_answer when substantive < MIN_SUBSTANTIVE_BY_TYPE (observe=1, investigate=2, execute=2, build=1). Guard fires once per task. Also adds agent_type guidance to propose_subtask prompt (deep-dive/why/diagnose → investigate, not observe). substantive_tool_calls column in subagent_runs for post-hoc audit.

**v2.34.9** — feat(agents): inject MCP tool signatures into system prompt — stop kwarg hallucination.
Recurring bug: agent calls tools with wrong kwargs (service_name= vs name=, since_minutes= vs minutes_ago=, pattern= vs query=). 16:21 sub-agent lost its last call to kafka_consumer_lag() missing 1 required positional argument: 'group'. Fix extracts real signatures via inspect.signature() at startup, caches per-process, renders ═══ TOOL SIGNATURES ═══ section into system prompt with only the allowlist's signatures. Prometheus deathstar_tool_signature_errors_total tracks TypeError rate.

**v2.34.10** — feat(vm_exec): read-only network diagnostics + safe pipe passthrough.
16:21 sub-agent tried nc -zv + 2>&1 + | head -5 to verify Kafka broker 3 connectivity — blocked by metachar check and allowlist. Adds network_diagnostics allowlist group (nc -zv, netstat, ss, curl --head, ping -c, dig, host, traceroute -m, mtr -r -c, plus docker-exec variants) with blast_radius=none. Replaces _validate_command: pipe safelist (head, tail, grep, wc, sort, uniq, awk, sed, cut, tr) and redirect safelist (2>&1, > /dev/null). Dangerous chars still blocked.

**v2.34.11** — fix(agents): classifier hard-routes investigative starters to research.
Sessions 2f2dae36 + 5107bfa7 (same Logstash investigate prompt, both runs) classified as Observe not Investigate. Root cause in `classify_task`: status_score=5 (check/network/port/health/lag) beat research_score=3 (investigate/why/correlate) even though the task literally opens with "Investigate". Adds _RESEARCH_STARTERS frozenset {investigate, diagnose, troubleshoot, analyse, analyze, correlate, why, deepdive} and _RESEARCH_STARTER_BIGRAMS {deep dive, find out, root cause, what caused}. Short-circuits to 'research' when first word/bigram matches AND action_score==0 (so "investigate and restart X" still routes to action). New `deathstar_agent_classifier_decisions_total` Prometheus counter with trigger labels. New tests/test_task_classifier.py covers today's prompt, all starters, action-precedence, and existing behaviour regression.

**v2.34.12** — feat(tools): container-introspection read-only tools.
Session 2bd88acb hit token cap (123k > 120k) after 16 tool calls with 5 blocked `docker exec … cat/curl/nc` attempts (container_id hash-check, /etc/resolv.conf, /etc/hosts, logstash.yml, in-container curl). Adds mcp_server/tools/container_introspect.py with 5 typed tools, all blast_radius=none: container_config_read (path regex safelist for /etc/*, /opt/*/config/*, /usr/share/*/pipeline/*, /var/log/*), container_env (env dump with PASSWORD/SECRET/TOKEN regex redaction), container_networks (structured docker inspect → {networks, published_ports}), container_tcp_probe (bash </dev/tcp/> — works without nc installed in-container), container_discover_by_service (Swarm service → [{node, vm_host_label, container_id, container_name}]). Added to observe/investigate/execute allowlists (NOT build). Prompt gets a CONTAINER INTROSPECTION block teaching the overlay-diagnosis pattern (discover → networks ×2 → tcp_probe → config_read). Seeds diagnose_container_overlay_reachability runbook. Tests cover arg validation, shell-injection rejection, secret redaction, and router allowlist presence.

**v2.34.13** — fix(agents): retarget prompts to prefer container_introspect over raw docker exec.
v2.34.12 shipped the five container_* tools correctly registered, allowlisted, and mentioned in RESEARCH_PROMPT, but session a69fd96d made 9 vm_exec calls and 0 container_* calls. Prometheus confirms: counter declared, zero series. Root cause: the KAFKA TRIAGE block at the top of RESEARCH_PROMPT is prescriptive with vm_exec/kafka_exec step lists, while the CONTAINER INTROSPECTION block sits 400 lines further down after STORAGE/NETWORK/COMPUTE/SECURITY branches — by the time the LLM reaches it the top-of-prompt playbook has committed it to vm_exec. Fix inserts a CONTAINER INTROSPECT FIRST block immediately before KAFKA TRIAGE ORDER with a `docker exec <x> → container_* tool` mapping table and the canonical overlay-diagnosis sequence (discover ×2 → networks ×2 → tcp_probe → config_read). Replaces the "vm_exec docker ps --filter name=" step in CONSUMER LAG PATH and BROKER MISSING PATH with container_discover_by_service. Tightens docstring first-lines for semantic-rank readiness. Adds PROMPT_TOOL_MENTION_COUNTER smoke-test Prometheus metric so prompt regressions are spottable. No new code, no new tools — pure prompt retargeting.

**v2.34.14** — fix(agents): hallucination hardening + fabrication detection + LLM trace persistence.
Session c97014a8 (parent, 10 tools, "completed" but WRONG) + bf3a71ea (sub-agent, 0 tools, emitted fabricated EVIDENCE block with invented container IDs x7k9a/y8m2b, invented IPs, invented hostname `elastic-ingress.internal`). v2.34.8 hallucination guard fired but its "fire once + accept with [HARNESS WARNING] prefix" design let the sub-agent win on re-emit. Parent then TRUSTED the fabrication and reversed its own earlier service_placement evidence (worker-03 → "actually worker-01 and worker-02"). Operation status "completed" + confidently wrong answer = worst failure mode. Fix: (1) hallucination guard rewritten to reject up to N times then status=failed/reason=hallucination_guard_exhausted, no [HARNESS WARNING] escape hatch; (2) new fabrication_detector scans final_answer for tool-call-shaped citations against actual tool_calls, rejects when ≥3 cited tools don't match; (3) parent-side distrust: sub-agent output flagged by guard/detector triggers `[harness] do NOT synthesise from this` injection to parent; (4) new agent_llm_traces + agent_llm_system_prompts tables persist full LLM messages + response for every step (system prompt stored once per operation, Postgres TOAST handles compression), 7-day retention default; (5) new `/api/logs/operations/{id}/trace?format=structured|digest` endpoint for debugging. New tests anchor on canonical bf3a71ea fabrication. Marks kafka_consumer_lag kwarg error (v2.34.9 regression) as known issue for v2.34.15.

**v2.34.15** — fix(agents): prompt signature rendering + sanitizer scope + budget off-by-one + prompt snapshots.
The v2.34.14 /trace endpoint let us inspect the exact system prompt of operation 828c07ba and prove three bugs were all prompt-layer. (1) kafka_consumer_lag({}) regression is NOT a signature-injection gap — signatures ARE present at char 27374. Root cause: KAFKA TRIAGE section at char 9591 shows the LLM `Call 2: kafka_consumer_lag()` (bare parens) as a prescriptive example, and the example wins over the reference section 18000 chars later. Fix: Option B — extract render_call_example() helper from v2.34.9 signature code and use f-strings to generate all TRIAGE call examples from the real tool signatures at prompt build time. Also scan STATUS/ACTION prompts for `tool_name()` shorthand on tools that have required args. (2) Budget off-by-one: investigate budget=16 but op 828c07ba ran 17 tool calls because step 6 dispatched a 2-call batch when only 1 slot remained. Fix: truncate proposed tool_calls to remaining budget, inject harness message naming dropped tools, add BUDGET_TRUNCATE_COUNTER. (3) Sanitizer false positives: v2.31.7 sanitizer runs on outbound API response bodies (wrong scope) with patterns loose enough to match `2.34.14` as JWT, `10403` as "Sensitive key", and any UUID in URL path. Fix: restrict sanitizer to LLM-inbound paths only via explicit sanitize_for_llm() calls at boundaries, tighten JWT to `eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}`, tighten UUID to context-gated (preceded by `token|secret|key|auth` within 40 chars), remove bare-integer and version-string patterns entirely. Add SANITIZER_BLOCKS_COUNTER with {pattern, site} labels. (4) Prompt snapshot CI guard: new tests/test_prompt_snapshots.py renders STATUS/RESEARCH/ACTION/BUILD prompts at test time, diffs against committed tests/snapshots/prompts/*.txt files, fails on divergence with unified diff. Reviewers see exactly what the LLM will now see when prompt-touching PRs come in. New PROMPT_SNAPSHOT_DIVERGED_COUNTER canary at startup.

**v2.34.16** — feat(ui): trace viewer + gates-fired digest + propose_subtask idempotency + service_placement signature.
v2.34.15 verification run (op 00379abc) surfaced three more findings via the now-working /trace endpoint. (1) service_placement has the same signature regression as kafka_consumer_lag: position 9313 of RESEARCH_PROMPT shows `service_placement(kafka_broker-N)` — positional-arg-style, no quotes. Agent hit TypeError 2×. Fix: expand v2.34.15 render_call_example() pass to cover ALL prescriptive examples across RESEARCH/STATUS/ACTION prompts. (2) Parent called propose_subtask 4× with identical args in 3 consecutive steps (op 00379abc, steps 4/5/6/6). No harness dedup; no immediate feedback when sub-agent terminates. Fix: SHA1-hash (task, executable_steps, manual_steps) as dedup key within parent run; reject duplicates with a harness message offering 4 clear next options. Also: when a sub-agent reaches terminal state (completed/escalated/failed), queue an immediate harness system message for the parent's next turn so it sees the outcome + any fabrication/halluc-guard findings. New PROPOSE_DUPLICATE_COUNTER + SUBAGENT_TERMINAL_FEEDBACK_COUNTER. (3) New Trace subtab under Logs: step-list + selected-step detail (assistant text, tool_calls with parsed args, tool_results collapsible, harness injections). Gates Fired summary in sidebar aggregates halluc_guard_attempts, fabrication_detected, subagent_distrust_injected, budget_nudges, budget_truncate, sanitizer_blocks. Copy system prompt + Download full JSON buttons. Server-side /trace?format=digest gets a matching "Gates fired" section at top. (4) Celebration note: v2.34.14's fabrication detector + parent-side distrust fired end-to-end in production on op 00379abc's sub-agent c32d2fe2 (fabricated broker IP 10.0.4.17 / port 9092). Parent correctly ignored the fabrication and synthesised from its own step 1-4 evidence (overlay hairpin NAT on 192.168.199.33:9094). No code change for this — it already works.

**v2.34.17** — fix(agents): boot-time sanitizer scope + forced synthesis on budget cap.
Closeout of the v2.34.14-16 observability cluster. Two tight fixes surfaced during v2.34.16 verification. (1) /api/health `version` field still shows `[BLOCKED: JWT token]` — v2.34.15 restricted the sanitizer to LLM-inbound paths but missed a call site that runs at application startup before LLM traffic begins. Fix: grep every `sanitize_for_llm` call site, confirm each runs only on strings about to be added to LLM messages, remove any call in startup / settings / response construction. New regression test in tests/test_health_endpoint.py asserting `version` field has no BLOCKED/REDACTED content. (2) Op 557f9ee1 (v2.34.16 verification, investigate task) hit status=capped with tc=16/16 and final_answer=null. Parent had the smoking gun by step 3 (container_tcp_probe reachable=false) but kept drilling until the budget cap silently ended the run with no output. Fix: on budget-cap (and other hard-cap exits — wall-clock, token-cap, consecutive-failures), run ONE forced-synthesis completion with no tools available and a prompt instructing EVIDENCE/ROOT CAUSE/UNRESOLVED/NEXT STEPS format from gathered evidence. Preserves run output; operator sees what the agent learned. Fabrication detector still applies; flagged outputs prefixed with DRAFT warning but kept. New FORCED_SYNTHESIS_COUNTER{reason, agent_type} + FORCED_SYNTHESIS_FABRICATED_COUNTER{agent_type}. Trace viewer Gates Fired sidebar gains `forced_synthesis` row.

---

### ✓ Phase milestone — Harness observability (v2.34.14 – v2.34.16)

Trace persistence → UI viewer → server digest, combined with fabrication
detection and propose_subtask idempotency, closes the harness observability
loop. Every agent run is inspectable, fact-checkable, and diff-able.
Future bugs become grep-and-fix instead of mystery hallucinations.

Tagged as `harness-observability-v2.34.16` at commit `4dab532`.

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
api/agents/orchestrator.py                — verdict_from_text, coordinator (v2.10.0, v2.32.4, v2.34.1)
api/routers/agent.py                      — loop, plan gate, verify, budgets (v2.32.2, v2.32.3, v2.32.4, v2.32.5, v2.34.0)
api/db/agent_attempts.py                  — attempt history table (v2.32.3)
api/db/subagent_runs.py                   — sub-agent runs table (v2.34.0, v2.34.8 adds substantive_tool_calls)
api/db/runbooks.py                        — BASE_RUNBOOKS + seed_base_runbooks() (v2.26.4)
api/db/vm_exec_allowlist.py               — allowlist table + cache + session purge (v2.23.3, v2.34.10)
api/routers/vm_exec_allowlist.py          — REST API for allowlist management (v2.23.3)
mcp_server/tools/vm.py                    — _validate_command DB-backed + 3 new tools (v2.23.3, v2.34.10)
gui/src/components/OptionsModal.jsx       — Allowlist tab (v2.23.3)
api/routers/settings.py                   — agentHostIp setting key (v2.22.6)
api/collectors/docker_agent01.py          — started_at + restart_count in card + metadata (v2.26.8)
api/db/credential_profiles.py             — seq_id, discoverable, get_profile_safe (v2.26.9)
api/db/audit_log.py                       — connection_audit_log table + write/list events (v2.26.9)
api/connections.py                        — username_cache column + credential_state in list (v2.26.9, v2.27.0)
api/routers/credential_profiles.py        — rotation test/confirm, safe fields, audit (v2.26.10)
api/routers/connections.py                — CSV export/import endpoints (v2.27.0)
api/collectors/windows.py                 — Windows/WinRM stub collector (v2.27.0)
api/routers/discovery.py                  — harvest, devices, test, link endpoints (v2.27.1)
gui/src/components/RotationTestModal.jsx  — rotation test modal with role-gated override (v2.27.4)
gui/src/components/DiscoveredView.jsx     — discovered devices view (v2.27.5)
gui/src/components/Sidebar.jsx            — Discovered nav item under MONITOR (v2.27.5)
gui/src/components/ServiceCards.jsx       — InfraCard universal entity buttons (v2.26.1), tag dropdown (v2.34.7)
api/routers/dashboard.py                  — _vm_ssh_exec credential fix + Proxmox action fix (v2.23.0), _update_pull_job (v2.33.16, v2.34.3)
api/db/infra_inventory.py                 — resolve_entity + write_cross_reference (v2.23.1)
api/collectors/proxmox_vms.py             — write VMs to infra_inventory (v2.23.1)
gui/src/context/DashboardDataContext.jsx  — shared dashboard state + version gate (v2.22.0)
api/db/metric_samples.py                  — time-series metrics (v2.21.0)
mcp_server/tools/metric_tools.py          — metric_trend + list_metrics (v2.21.0)
api/metrics.py                            — Prometheus metrics (v2.33.5, v2.34.2, v2.34.5, v2.34.8, v2.34.9, v2.34.10, v2.34.14, v2.34.15, v2.34.16)
api/agents/fabrication_detector.py        — citation extraction + fabrication scoring (v2.34.14)
api/db/llm_trace_retention.py             — nightly purge (v2.34.14)
tests/snapshots/prompts/*.txt             — committed rendered agent prompts, CI-diffed (v2.34.15)
tests/test_prompt_snapshots.py            — snapshot CI guard (v2.34.15)
api/agents/gate_detection.py              — shared gate detection logic for /trace digest + UI (v2.34.16)
gui/src/components/TraceView.jsx          — Logs → Trace tab, step list + detail + Gates Fired (v2.34.16)
gui/src/utils/gateDetection.js            — JS mirror of api/agents/gate_detection.py (v2.34.16)
```
