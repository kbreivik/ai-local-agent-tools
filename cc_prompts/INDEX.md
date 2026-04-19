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
| CC_PROMPT_v2.34.17.md | v2.34.17 | fix(agents): boot-time sanitizer scope + forced synthesis on budget cap | DONE (7628b84) |
| CC_PROMPT_v2.35.0.md | v2.35.0 | feat(facts): known_facts schema + collector writers + /api/facts + Settings + Prometheus | DONE (a34bd4f) |
| CC_PROMPT_v2.35.0.1.md | v2.35.0.1 | feat(ui): Facts tab + Dashboard widget + diff viewer + permission-gated admin | DONE (d927f81) |
| CC_PROMPT_v2.35.1.md | v2.35.1 | feat(agents): entity preflight + three-tier extractor + Preflight Panel + PREFLIGHT FACTS | DONE (e0ac5ec) |
| CC_PROMPT_v2.35.2.md | v2.35.2 | feat(agents): in-run cross-tool contradiction detection + agent_observation fact writer | DONE (0c6311f) |
| CC_PROMPT_v2.35.3.md | v2.35.3 | feat(agents): fact-age rejection on tool results (Medium mode) | DONE (b8b93f7) |
| CC_PROMPT_v2.35.4.md | v2.35.4 | feat(agents): runbook-based TRIAGE injection + UI editor (augment default) | DONE (057d594) |
| CC_PROMPT_v2.35.5.md | v2.35.5 | fix(agents): preflight fact injection on zero-inventory-match (v2.35.1 fix) | DONE (1366611) |
| CC_PROMPT_v2.35.6.md | v2.35.6 | fix(security): remove legacy [BLOCKED:...] egress sanitiser rewriting operations.final_answer | DONE (b40289b) |
| CC_PROMPT_v2.35.7.md | v2.35.7 | fix(agents): disambiguate PREFLIGHT FACTS entity_ids from vm_exec host names | DONE (5962196) |
| CC_PROMPT_v2.35.8.md | v2.35.8 | feat(templates): five new non-destructive templates + catalogue CI tests | DONE (3cf80a2) |
| CC_PROMPT_v2.35.9.md | v2.35.9 | fix(vm_exec): hostname resolution hardening + safe boolean chaining + DNS template fix | DONE (23dd5d6) |
| CC_PROMPT_v2.35.10.md | v2.35.10 | fix(agents): forced_synthesis XML-drift defense + programmatic fallback | DONE (39372ed) |
| CC_PROMPT_v2.35.11.md | v2.35.11 | fix(agents): forced_synthesis placeholder defence + fabrication regex tightening + attempt-1 cleaned-history promotion | DONE (c780daf) |
| CC_PROMPT_v2.35.12.md | v2.35.12 | fix(agents): drop drifted messages entirely + enrich programmatic fallback with per-tool result snippets | DONE (bcb9568) |
| CC_PROMPT_v2.35.13.md | v2.35.13 | fix(agents): DB-sourced fallback + per-host dedup + best_snippet + pbs_datastore_health + agent_performance_summary tools | DONE (46e2836) |
| CC_PROMPT_v2.35.14.md | v2.35.14 | fix(agents): forced synthesis on empty-completion path (status=completed + final_answer='') | DONE (c6afc70) |
| CC_PROMPT_v2.35.15.md | v2.35.15 | fix(agents): near-empty / preamble-only final_answer detection + PBS+perf tool event-loop safety | DONE (3ca8409) |
| CC_PROMPT_v2.35.16.md | v2.35.16 | STRATEGY-MEMO + recommended: last-step final_answer assignment (root-cause fix for preamble bug) | DONE (0eddcfc) |
| CC_PROMPT_v2.35.17.md | v2.35.17 | fix(agents): final_answer only from finish_reason='stop' + no tool_calls (root-cause fix, supersedes v2.35.14+15 rescue dependence) | RUNNING |

---

## Phase v2.35 — Facts, not just tools

**Design spec:** `PHASE_v2.35_SPEC.md`  (doc-coauthored before any CC prompt is written)

| Prompt | Theme | Status |
|---|---|---|
| v2.35.0 | DB: known_facts schema + collector writers + /api/facts + Settings + Prometheus | PENDING |
| v2.35.0.1 | UI: Facts tab + Dashboard widget + diff viewer + permission-gated admin | PENDING |
| v2.35.1 | Entity preflight: three-tier extractor + Preflight Panel + PREFLIGHT FACTS | PENDING |
| v2.35.2 | In-run cross-tool contradiction detection + agent_observation fact writer | PENDING |
| v2.35.3 | Fact-age rejection on tool results (Medium mode) | PENDING |
| v2.35.4 | Runbook-based TRIAGE injection + UI editor (augment default) | PENDING |

**All 6 CC prompts drafted and ready for queue execution.** Sequence: v2.35.0 → v2.35.0.1 → v2.35.1 → v2.35.2 → v2.35.3 → v2.35.4. Each independently deployable, each verifiable via `/metrics`, `/api/facts*`, and the Trace viewer.

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

## Phase: v2.35.x — Facts, not just tools

Full spec in `PHASE_v2.35_SPEC.md`. Shifts the agent from "rediscover the world on every task" to "start from facts, verify only what's uncertain." Introduces persistent, weighted, contradiction-aware knowledge store (`known_facts`) with collector-sourced writes, preflight resolution of task references, in-run contradiction detection, fact-age rejection on tool results, and runbook-based TRIAGE injection. All behaviour gated via Settings → Facts & Knowledge group.

**v2.35.0** — feat(facts): known_facts schema + collector writers + /api/facts + Settings group + Prometheus.
Foundation of the phase. New tables: known_facts_current (live value per (fact_key, source)), known_facts_history (append-only, only on value change — deduplicates identical polls), known_facts_locks (admin-asserted "don't overwrite"), known_facts_conflicts (collector contradicts lock), known_facts_permissions (user + role grants, sith_lord implicit full, expires_at + revoked), known_facts_refresh_schedule (per-pattern cadence, seeded: proxmox.vm.*.status=60s, swarm.service.*.placement=30s, kafka.broker.*.host=3600s, container.*.ip=300s, manual.*=86400s, default 300s), facts_audit_log. Confidence formula: base × age_factor + verify_boost − contradiction_penalty, clamped [0,1]; 5-level ladder (Very High 0.9-1.0 / High 0.7-0.89 INJECTION THRESHOLD / Medium 0.5-0.69 / Low 0.3-0.49 / Reject 0.0-0.29). Source weights: manual=1.0, collectors=0.8-0.9, agent_observation=0.5, rag=0.4 — all tunable. Manual facts never expire; decay phased (30d full, 60d→0.7, 60d+ slow fade). Fact keys use `prod.` scope prefix. Array values for multi-valued facts. Collector fact extractors in api/facts/extractors.py for Proxmox, Swarm, docker_agent, Kafka, PBS, FortiSwitch — wired into existing poll loops as best-effort (try/except). Change-detection via change_detected + change_flagged_at. /api/facts/ read endpoints + /settings/preview for live-scored sample. New Settings group "Facts & Knowledge" with all weights, thresholds, half-lives, verify cap. Prometheus: known_facts_total, _confident_total, _conflicts_total, facts_upserted_total{source,action}, _contradictions_total, _lock_events_total, _refresh_stale_total. No agent behaviour change.

**v2.35.0.1** — feat(ui): Facts tab + Dashboard widget + diff viewer + permission-gated admin.
Consumes v2.35.0 API. New api/security/facts_permissions.py implements user_has_permission with sith_lord=all, user-revoke overrides role-allow, expiry support. Extends /api/facts with /locks POST DELETE, /conflicts/{id}/resolve POST (keep_lock/accept_collector/edit_lock), /permissions CRUD (sith_lord only), /key/{key}/refresh POST, /audit. New MONITOR sidebar → Facts tab: two-pane list+detail, confidence pills, freshness indicators, conflict/lock/refresh icons. FactDiffViewer with string character-diff + JSON tree diff (extensible to switch/firewall config diffs later). FactLockModal + ConflictResolveModal both permission-gated. Dashboard FACTS & KNOWLEDGE card: total + per-tier counts, last refresh, stale count (amber), pending admin reviews (red pulse), recently changed. Settings page gains Facts Permissions admin table (sith_lord only).

**v2.35.1** — feat(agents): entity preflight + three-tier extractor + Preflight Panel + PREFLIGHT FACTS injection.
First behaviour change. New api/agents/preflight.py with three-tier pipeline: Tier 1 regex (kafka_broker-N, ds-docker-worker-N, hp1-prod-*, service names, container short IDs), Tier 2 keyword+time-window DB lookup (KEYWORD_RESOLVERS maps restarted/rebooted/degraded/failing/offline/crashed/alerting/deployed/scaled to DB functions against agent_actions/entity_history/alerts/logs, TIME_HINTS maps just/recently/today/last hour to minutes), Tier 3 bounded LLM fallback (~200 tokens, gated by preflightLLMFallbackEnabled). New known_facts_keywords table (DB-editable, seeded from defaults) + known_facts_keyword_suggestions (auto-propose when Tier 3 catches what Tier 1+2 missed). Resolver results merge with infra_inventory matches. Ambiguous tasks (>1 candidate) block agent loop with status='awaiting_clarification' — new /api/agent/operations/{id}/clarify endpoint resumes with selected_entity_id or refined_task. Background task auto-cancels idle clarifications after preflightDisambiguationTimeout (default 300s). System prompt gains ═══ PREFLIGHT FACTS ═══ section before RELEVANT PAST OUTCOMES, capped at factInjectionMaxRows, sorted by confidence desc. PreflightPanel.jsx: always-visible panel (collapsed when no ambiguity), shows classifier + extracted entities + time-window + keywords + candidate matches (radio-pick UI) + facts-to-inject count; auto-cancel countdown visible; Pick/Edit/Cancel buttons. Prometheus: preflight_resolutions_total{outcome}, _disambiguation_outcome_total{result}, _facts_injected_count histogram. Prompt snapshots regenerated.

**v2.35.2** — feat(agents): in-run cross-tool contradiction detection + agent_observation fact writer.
Shared infrastructure. New api/facts/tool_extractors.py with per-tool extractors for service_placement, container_discover_by_service, kafka_broker_status, container_networks, container_tcp_probe, proxmox_vm_power, swarm_node_status — dispatcher returns [] for unknown tools. Agent loop tool-result handler extended: state.run_facts dict caches per-run extracted facts; when same fact_key emerges with a different value across steps, inject `[harness] Contradiction detected within this run` message listing step/tool/value for both, agent must reconcile before concluding. Terminal handler on status='completed' upserts state.run_facts to known_facts at source='agent_observation'. Guardrails: never write if fabrication_detected_count>0, halluc_guard_exhausted, status!=completed; cap 80 rows/run; volatile metadata flag (e.g. tcp_probe reachability) gets 2h half-life via new factHalfLifeHours_agent_volatile setting. gate_detection gains inrun_contradiction + shown in Trace viewer Gates Fired sidebar. /trace?format=digest appends "Facts written to known_facts" section. Prometheus: inrun_contradictions_total{fact_key_prefix} (3-segment prefix for cardinality safety), agent_observation_facts_written_total{wrote_or_skipped}.

**v2.35.3** — feat(agents): fact-age rejection on tool results (Medium mode).
New api/agents/fact_age_rejection.py with 4 modes: off (pass-through), soft (advisory harness only), medium (strip conflicting value, add _rejected_by_fact_age transparency field, harness advisory — DEFAULT), hard (mark tool call failed, error_type=fact_age_rejection). Fires when tool result extracts a fact disagreeing with known_facts_current row where source≠agent_observation, confidence≥factAgeRejectionMinConfidence (0.85), age≤factAgeRejectionMaxAgeMin (5). Medium-mode stripping is best-effort per-tool via structured-shape knowledge; unknown shapes fall back to advisory-only. Wired before on_tool_result so v2.35.2 contradiction detection sees the modified result (rejected facts don't pollute run_facts). gate_detection gains fact_age_rejection. Trace viewer tool-result pane shows "Why was this stripped?" banner when _rejected_by_fact_age present. Prometheus: fact_age_rejections_total{mode, source_rejected}. All three thresholds in Settings → Facts & Knowledge, already declared in v2.35.0, first enforced here.

**v2.35.4** — feat(agents): runbook-based TRIAGE injection + UI editor (augment default).
Final item of the phase. Extends runbooks table: triage_keywords TEXT[], applies_to_agent_types TEXT[], is_active BOOL, priority INT, body_md TEXT, last_edited_by/at. seed_triage_runbooks() extracts KAFKA TRIAGE, CONSUMER LAG PATH, BROKER MISSING PATH, OVERLAY DIAGNOSIS, CONTAINER INTROSPECT FIRST verbatim from api/agents/router.py into DB rows at first init (programmatic extraction, not duplication). New api/agents/runbook_classifier.py with v1 keyword match (score=matched-keywords-count, tiebreak by priority asc); _semantic_select and _llm_select stubbed for v2.35.5+. System prompt builder gains runbookInjectionMode switch: off (pre-v2.35.4 behaviour), augment (DEFAULT — inject after existing TRIAGE section with ═══ ACTIVE RUNBOOK: <name> ═══ header), replace (replace matching section), replace+shrink (thin framework + runbook). Rollout plan: 2-3 weeks on augment, promote to replace via Settings flip when trace diffs show no regression, then replace+shrink after 2 more weeks. Runbooks view gains editor: fields for title/body_md/keywords/agent_types/priority/active, markdown preview, Test Match feature (input task → shows classifier score + matched keywords). Writes require sith_lord. gate_detection gains runbook_injected (per-operation, 0 or 1). Prometheus: runbook_matches_total{runbook_name, mode}, runbook_selection_decisions_total{classifier_mode, outcome}. Prompt snapshots regenerated; diff should show only the ACTIVE RUNBOOK addition.

**v2.35.5** — fix(agents): preflight fact injection on zero-inventory-match.
Patch to v2.35.1. `resolve_against_inventory()` gated fact lookup on `len(matches) == 1`, so entities with zero inventory rows never got facts injected even when confident facts existed. This is the common case: `infra_inventory` is populated mostly by proxmox_vms / vm_hosts collectors — Kafka brokers, Swarm services, containers, and most other platform entities have zero rows there. User test with `logstash_logstash` + `kafka_broker-3` produced trace lines like `'logstash': 0 inventory matches` and zero facts reached the agent despite 199 confident rows in `known_facts`. Fix: on zero inventory match, fall back to direct fact lookup against the regex-extracted entity_id (`get_confident_facts_for_entity` already does dot-stem conversion so `broker-3` matches `prod.kafka.broker.3.host`); on >1 matches still skip (preserves v2.35.1 ambiguity behaviour); on exactly 1 match, behaviour unchanged. Trace lines now include entity_type for clearer diagnosis. Adds `deathstar_preflight_fact_source_total{source}` counter with labels `inventory_match | direct_entity | ambiguous_skip | no_facts_found` so the two zero-fact outcomes (no lookup attempted vs lookup-but-empty) are distinguishable in metrics. Adds 4 regression tests: parametric tier-1 regex preservation (locks in that the regex does NOT truncate full hyphen/underscore names — that was a misdiagnosis during rollout), zero-match-falls-back-to-direct, ambiguous-skips-direct, single-match-uses-canonical-id.

**v2.35.6** — fix(security): eliminate legacy `[BLOCKED:...]` egress sanitiser rewriting `operations.final_answer` in the DB.
The v2.31.7 sanitiser (format `[BLOCKED: <Category>]`) was supposed to be retired by v2.34.15 in favour of `api/security/prompt_sanitiser.py` (format `[REDACTED:<lowercase>]`, tight patterns). v2.34.15 added the new module but left the old one on disk, and at least one background task still invoked it — silently rewriting `operations.final_answer` rows **in the DB** to `[BLOCKED: Cookie/query string data]` whenever content matched `key=value` / XML-tag patterns, `[BLOCKED: JWT token]` on dotted identifiers, `[BLOCKED: Sensitive key]` on UUIDs. Observed on agent-01 on 2026-04-18: op `2f287593`'s `<parameter=host>ds-docker-worker-03</parameter>` content was clean at 20:03 UTC and `[BLOCKED: Cookie/query string data]` at 20:19 UTC with no other writes in between — smoking-gun evidence of a background job rewriting completed rows. Agent output was thus PERMANENTLY LOST (only the sanitised string remained in DB), making the product unusable for operators despite the agent loop itself generating good answers. Also affected intermittently: `/api/health` version field, `/api/agent/run` session_id, `/api/elastic/logs` responses. Fix: `git grep 'BLOCKED:'` locates the legacy module, remove the offending call sites (deleting the whole module if no legitimate callers remain — `prompt_sanitiser.py` is the only sanitiser this codebase should have). One-shot recovery migration in `lifespan()` restores nuked `operations.final_answer` rows from v2.34.14's `agent_llm_traces` persistence (replays last step's `response_raw.choices[0].message.content`). Adds `tests/test_response_egress.py` with round-trip tests covering every affected endpoint + a structural guard (`test_no_legacy_sanitiser_module_imports`) that fails CI if the `[BLOCKED:` literal ever reappears anywhere under `api/`. Triaged live during v2.35.5 verification using the harness observability stack (metrics → WebSocket live broadcast → /trace → DB diff across time), exactly the debug pattern documented for v2.34.13-17.

**v2.35.7** — fix(agents): disambiguate PREFLIGHT FACTS entity_ids from vm_exec host names.
Smoke test of v2.35.5 on template 'VM host overview' (op `a7e146a1`) revealed a name-space collision between two parts of the system prompt. `format_preflight_facts_section()` (v2.35.1) renders fact keys like `prod.proxmox.vm.hp1-prod-worker-03.memory_gb` where `hp1-prod-worker-03` is Proxmox's name for the VM; the `AVAILABLE VM HOSTS` capability hint (`_stream_agent`, vm_host domain) renders real vm_host connection labels like `ds-docker-worker-03`. Same physical box, different identifiers. Agent pulled the Proxmox name from PREFLIGHT FACTS and passed it as `vm_exec(host="hp1-prod-worker-03", command="df -h /")` — 6 consecutive errors before recovering via `infra_lookup` → `result_query`. Status ended `capped` at 8/8 observe budget, template failed for operators. Fix has three layers: (1) `format_preflight_facts_section()` now appends a disambiguation note stating that fact keys encode per-collector entity_ids and may NOT be valid `vm_exec host=` targets, directing the agent to the `AVAILABLE VM HOSTS` section instead; (2) the `AVAILABLE VM HOSTS` capability hint now claims sole authority over `vm_exec host=` parameters with explicit wording "AUTHORITATIVE — use ONLY these names"; (3) five `all hosts`‑style templates (`VM host overview`, `Disk usage — all hosts`, `Memory and load — all hosts`, `Storage capacity overview`, `SSH access audit`) gain a trailing sentence telling the agent to use the authoritative list / `list_connections` / `infra_lookup`. Regression test `tests/test_preflight_hostname_disambiguation.py` locks in both the disambiguation clause and the authority claim so future collector additions can't re-introduce the ambiguity.

**v2.35.8** — feat(templates): five new non-destructive templates + catalogue CI tests.
Adds five read-only, broadly-useful templates to cover operational gaps the existing catalogue missed. INFRASTRUCTURE gains `Container restart loop diagnosis` (>3 restarts/h or >10/24h flap detection with exit-code + journal correlation). SECURITY gains `Certificate expiry check` (openssl cert enumeration across nginx/caddy/traefik hosts, flags <30d expiry). NETWORK gains `DNS resolver consistency` (dig/nslookup against every configured resolver, split-brain detection). SWARM gains `Docker overlay network health` (ingress + overlay network inspection, peer-count vs node-count check). A new PLATFORM group adds `Agent success rate audit` (meta — agent reflects on /api/logs/operations?limit=100, reports completion rate per agent_type, top-failing task labels, hallucination_guard_exhausted / fabrication_detected firings). All five are strictly read-only — no destructive tools, no state changes, all using tools already in existing allowlists (container_config_read / container_env / vm_exec with openssl/dig/nslookup in the read-only network_diagnostics allowlist from v2.34.10 / swarm_node_status / `docker network inspect`). Also ships `tests/test_task_templates.py` with 7 catalogue-integrity tests: parseability, label-uniqueness within group, task-string substantiveness, placeholder discipline (only `Drain Swarm node` and `Reboot Proxmox VM` may contain `{...}`), destructive-labels manifest (reviewers must update the test if they rename/remove a destructive template), no `plan_action` mentions in non-destructive tasks, and a v2.35.7 regression guard ensuring any template text mentioning 'all hosts' / 'every host' cites the authoritative host source (`AVAILABLE VM HOSTS`, `list_connections`, or `infra_lookup`). Tests are entirely static — no LM Studio dependency, <1s runtime — and will catch the v2.35.7 regression in CI if anyone adds a new 'all hosts' template without the authority line.

**v2.35.9** — fix(vm_exec): hostname resolution hardening + safe boolean chaining + DNS template fix.
Surfaced during v2.35.8 template smoke tests (ops `7f1fb061`, `d6f52901`, `27b5be44`, `7660a0de`). Three tight fixes. (1) `_resolve_connection` in `mcp_server/tools/vm.py` used an unqualified `for c in all_conns: if q in c.get("label").lower(): return c` loop — any substring match wins by iteration order. Works today (only one connection contains `manager-01`) but silently dispatches to arbitrary hosts the moment two labels share a substring. Replaced with unique-suffix-match → unique-substring-match → None, and vm_exec formats a useful error naming all ambiguous candidates. (2) `_validate_command` blocked the `&` metachar wholesale, forcing the agent to make separate calls for `free -m && uptime` (observed in VM host overview) and `ls ... || echo missing` (observed in Certificate expiry check). New `_split_chain()` handles `&&` / `||` by splitting on them BEFORE the metachar scan and recursively validating each segment; only allows the chain when every segment independently passes. Max 3 segments, single `&` (background) still blocked, `$()`/`` ` ``/redirects still blocked. New `deathstar_vm_exec_chain_operators_total{op}` counter. (3) The `AVAILABLE VM HOSTS` capability hint (v2.35.7) gains a paragraph telling the agent to USE THE COMPLETE LABEL STRING with a concrete example (`'manager-01' NOT valid, 'ds-docker-manager-01' correct`) and a heads-up that vm_exec will do unique-suffix matching as a fallback but reject ambiguous abbreviations. (4) The DNS resolver consistency template (v2.35.8, authored by me) contained literal `agent-01` references — no such vm_host connection exists — replaced with `hp1-ai-agent-lab` plus `list_connections` hint. Eight regression tests in `tests/test_vm_exec_hardening.py` cover all three code paths plus a template-text guard.

**v2.35.10** — fix(agents): forced_synthesis XML-drift defense + programmatic fallback.
Every single one of 4 consecutive v2.35.8 `status=capped` runs persisted a `final_answer` that was raw XML instead of structured synthesis — e.g. `<tool_call>\n<function=vm_exec>\n<parameter=host>\nds-docker-worker-03\n<\/parameter>\n<\/function>\n<\/tool_call>`. v2.34.17's `forced_synthesis` was firing (correct code path on budget-cap) but Qwen3-Coder-Next, having spent 8+ turns emitting tool calls in the conversation history, continued the pattern when asked to synthesise — pure LLM drift. Fabrication detector didn't catch it because it scans for *cited tool names*, not *tool-call syntax*. Three-layer fix: (1) `build_harness_message()` gains an explicit CRITICAL FORMAT RULE paragraph prohibiting `<tool_call>`, `<function=...>`, `<parameter=...>`, and ```` ```json ```` fencing, with a concrete alternative (`[UNRESOLVED: would have called <tool>(<args>) next]`); (2) `run_forced_synthesis` now checks output for drift using `_is_drift()` (prefix match on `<tool_call>/<function=/<parameter=/```json`, overall XML tag density >30%, `<parameter=` or `<function=` in the first 500 chars). On first-attempt drift, reformulates with an even stronger anti-XML harness message AND a cleaned messages history where prior XML-drift assistant messages are replaced with `[prior step: tool call attempt, see tool_calls]` so the model isn't primed to continue the pattern; (3) if retry also drifts, falls back to `_programmatic_fallback()` — built from the actual tool call names, the cap reason, and static prose — guaranteeing the operator ALWAYS sees structured EVIDENCE / UNRESOLVED / NEXT STEPS output prefixed `[HARNESS FALLBACK]`. Two new Prometheus counters: `deathstar_forced_synthesis_drift_total{reason, attempt}` (reason = `tool_call_prefix|xml_density|parameter_tag_in_head|empty`, attempt = `1|2`) and `deathstar_forced_synthesis_fallback_total{reason}` surface how often each layer fires in production. 8 regression tests cover drift detection positive/negative cases (including prose with legitimate `<` / `>` comparison operators), the fallback's readability + tool-deduplication, message-stripping integrity, and an end-to-end integration test with a mock client that always drifts — confirms 2 attempts are made and the fallback output contains no angle brackets.

**v2.35.11** — fix(agents): forced_synthesis placeholder defence + fabrication regex tightening + attempt-1 cleaned-history promotion.
Three fixes surfaced during v2.35.10 verification (4 capped runs, ops `e8a625ad`, `e442810b`, `c21565be`, `234e828e`, 2026-04-19 against commit `39372ed`). (1) Placeholder echo leak: `_strip_xml_drift_from_messages()` replaced drifted assistant messages with the human-readable string `"[prior step: tool call attempt, see tool_calls]"`. On op `e8a625ad`, the retry LLM echoed that placeholder verbatim as its "prose" output. `_is_drift()` returned False (plain text, 0% XML density, no `<tool_call>` prefix) so the programmatic fallback was NOT triggered — the 47-char placeholder was persisted as `final_answer`, leaving the operator with no useful output. Fixed by replacing the string with a module-level sentinel `_DRIFT_STRIPPED_PLACEHOLDER = "[__FORCED_SYNTHESIS_STRIPPED_DRIFT_PLACEHOLDER__]"` and adding a `placeholder_echo` drift reason in `_is_drift` that matches the sentinel whether returned alone or as majority-content (>50%) of the output. Long clean prose that merely mentions the sentinel (e.g. in a debug note) still passes because of the majority-content guard. (2) Fabrication detector false positives on failure reports: `_PROSE_CITE_RE = r"\b([a-z][a-z0-9_]{2,40})\s*\("` and `_TOOL_CITE_RE` both allowed whitespace between the identifier and `(`, which matched natural-language parenthetical patterns like `unavailable (tool not registered)` and `hp1-ai-agent-lab (agent-01, 192.168.199.10)` — extracting `unavailable` and `lab` as "cited tools" that weren't in the agent's actual tool history. Score 2/3 triggered the detector, prepending `[HARNESS: ... DRAFT]` to genuinely correct synthesis on op `e442810b`. Tightened both regexes to require an IMMEDIATE `(` after the identifier (real tool calls are always `name(args)` with no space) and expanded `_CITE_DENYLIST` with common English words (`see`, `via`, `with`, `unavailable`, `reachable`, `lab`, `tool`, `call`, `docker`, `swarm`, ...) as belt-and-suspenders. (3) Attempt-1 drifted 4/4 times on Qwen3-Coder-Next: the long tool-call history primes the model to continue emitting XML tool calls even when `tools=None`. The v2.35.10 retry path already applies the mitigation (`_strip_xml_drift_from_messages` + strong anti-XML prompt). Promoted the cleaned-history + strong-prompt path to attempt 1, eliminating the systematic wasted LLM call (~2-3s latency + tokens per capped run). Attempt 2 retained as last-chance retry with an even stronger prompt that explicitly warns against echoing prior messages. Four new tests cover placeholder-echo detection (alone, majority-content, minority-mention-in-prose), plus `tests/test_fabrication_detector_regex.py` with 5 tests — including an exact regression for op `e442810b`'s synthesis (must NOT fire) AND the canonical `bf3a71ea` fabrication (must still fire).

**v2.35.12** — fix(agents): drop drifted messages entirely + enrich programmatic fallback with per-tool result snippets.
v2.35.11 verification run produced all 3 defence layers working as designed but revealed a **100% fallback rate** across 3 capped runs — every attempt drifted via either `placeholder_echo` or `xml_density>0.30`. Root cause: `_DRIFT_STRIPPED_PLACEHOLDER = "[__FORCED_SYNTHESIS_STRIPPED_DRIFT_PLACEHOLDER__]"` in the cleaned retry context became an attractor pattern. The model, pressed to output "plain text only", saw several sentinels repeated in recent assistant history and echoed one verbatim as its output — a seemingly safe plain-text fallback. Pre-v2.35.11 data showed ~50% of capped runs produced genuine LLM synthesis (ops `e442810b`, `234e828e`); v2.35.12 aims to restore that without undoing the v2.35.11 wins (no `tool_call_prefix` drift, no fabrication false positives). Two surgical fixes: (1) `_strip_xml_drift_from_messages()` now **drops** drifted assistant turns entirely (and their paired tool responses, which are orphaned once the parent assistant message is gone — pairing is already broken because drifted assistant messages never had real `tool_calls`, only text-embedded XML). Removes the sentinel attractor without losing context the model actually needs. The sentinel constant + `placeholder_echo` drift detection are retained as belt-and-suspenders for the rare case where the model types out the sentinel from training memory. (2) `_programmatic_fallback()` enriched with per-tool result snippets — accepts an optional `actual_tool_calls` parameter (list of `{name, status, result}` dicts), deduplicates per tool name (preferring successful over errored results), and emits `- tool_name() status=ok: <120-char snippet>` per unique tool. Operators now see inline what each tool returned instead of just the tool names, making the fallback useful even when the LLM provides nothing. Backward-compatible: `actual_tool_names` parameter still works. 5 new tests cover the names-only compat path, the enriched-with-results path (including dict serialisation), snippet truncation at 120 chars, drop-entirely behaviour for drift messages, and preservation of valid tool-response pairings.

**v2.35.13** — fix(agents): DB-sourced fallback + per-host dedup + best_snippet + pbs_datastore_health + agent_performance_summary tools.
v2.35.12 verification (commit `bcb9568`, 2 capped runs ops `e5df1b7c`, `606bd235` + 1 errored `886afe7c`, 2026-04-19) confirmed the v2.35.12 wiring was fragile. Enriched fallback paths fired but produced `status=None` and 12-char mystery snippets; 8 `vm_exec` calls across 8 different hosts collapsed to 1 snippet row. Also re-surfaced `tool_call_prefix` drift (v2.35.11 win lost) — the dropped-messages strategy removed the sentinel attractor but also removed the anti-example signal that had suppressed XML tool_call emission on attempt 1. v2.35.13 keeps the architecture (forced synthesis + 3-layer defence + always-fallback-on-drift) and lands three enrichment fixes plus two template-gap-closing MCP tools. (1) **DB-sourced fallback:** `_programmatic_fallback()` gains an optional `operation_id` parameter and a new `_load_tool_calls_for_op()` helper that queries the `tool_calls` table directly for canonical rows (`tool_name`, `status`, `params` dict, `result` dict). Caller-side `actual_tool_calls` kept as secondary, `actual_tool_names` kept as tertiary legacy path. Removes all dependency on whatever CC wired up in the caller's local scope. Source choice logged at INFO level for post-hoc debugging. (2) **Per-host dedup:** new `_first_arg_value()` helper extracts a primary-arg value from `params` using priority keys (`host`, `service_name`, `entity_id`, `container_id`, `vm_name`, `node`, `broker_id`, `pool`, `datastore`, `topic`, `group`, `key`, `name`, `label`), truncated to 40 chars. Dedup key becomes `(tool_name, first_arg_value)` so `vm_exec(host='worker-01')` and `vm_exec(host='worker-02')` produce two rows instead of one. On duplicate key, prefer the successful call over the errored one. Snippet rendering shows `- vm_exec(ds-docker-worker-01) status=ok: /dev/sda1 42G used` instead of bare `- vm_exec()`. (3) **`_best_snippet()` helper:** extracts a useful 120-char summary from the canonical `{status, message, data}` result envelope. Preference order: `message` field → first line of `data.summary` → top-level keys of `data` rendered as `key=value, key=[N items], key={N keys}` → json.dumps fallback → str() fallback. No more mystery 12-char outputs — every snippet is either a real author-written message, a structured data summary, or an explicit indication of what was returned. (4) **`pbs_datastore_health()` MCP tool:** queries `infra_inventory` for rows with `platform='pbs' AND entity_type='datastore'`, enriches each with used/total/pct plus a HEALTHY/DEGRADED/CRITICAL flag (pct >= 95 critical, >= 85 degraded), returns `{status, message, data: {datastores: [...], summary}}` envelope. Registered with `blast_radius='none'` and added to observe + investigate allowlists. Closes the PBS datastore health template (previously `hallucination_guard_exhausted`). (5) **`agent_performance_summary(hours_back=24)` MCP tool:** queries the `operations` table directly for per-(agent_type, status) buckets with median wall-clock, plus top-10 failing task labels. Returns `{total, success_rate_pct, buckets: [...], top_failing: [...], summary}`. Closes the Agent success rate audit template (previously empty `final_answer` because agent had no HTTP-fetch tool for the `/api/logs/operations` endpoint the template referenced). Templates in `TaskTemplates.jsx` updated to explicitly call the new tools. 6 new tests cover the monkey-patched DB source path, `(tool_name, first_arg)` dedup with success-wins behaviour, `_best_snippet` preference order, and `_first_arg_value` priority ordering + truncation.

**v2.35.14** — fix(agents): forced synthesis on empty-completion path.
v2.35.13 verification on op `1ebb7047-1211-4c5d-8fb7-86c1852abcd2` (Agent success rate audit against commit `46e2836`, 2026-04-19) surfaced a silent product failure mode that had been lurking since v2.34.17. The agent made 5 successful substantive tool calls (`agent_performance_summary`, `swarm_status`, `agent_status`, `skill_health_summary`, `audit_log`), the orchestrator marked `status=completed`, but `final_answer` was 0 bytes. The trace viewer confirmed `gates_fired: {}` — no guard, no forced synthesis, no drift, no fabrication fired. Every step emitted `finish_reason=tool_calls` with zero content length: the LLM chose tool calls on its final turn too, the agent loop exited 'naturally' after `audit_log`, and v2.34.17's `run_forced_synthesis` was never invoked because that code path only fires on HARD caps (budget, wall-clock, token, destructive, consecutive-tool-failures). The empty-completion path had no owner. This is a generalisable failure mode: any observe/investigate run where the LLM keeps picking tool calls until the loop exits 'cleanly' will exit with empty `final_answer` unless the loop itself forces a synthesis. Fix wires the existing `run_forced_synthesis` into the terminal happy-path branch of `_stream_agent` / `drive_agent`: before writing the terminal status to the operations table, check if `final_answer` is empty AND at least one substantive tool call was made (META_TOOLS set already defined elsewhere) AND the exit isn't an explicit error. If so, invoke `run_forced_synthesis` with new reason `"empty_completion"` and thread `operation_id` for v2.35.13's DB-sourced enrichment. Same code path as budget-cap fallback — same 3-layer drift defence, same per-tool snippet rendering, same HARNESS FALLBACK output. The v2.35.13 `pbs_datastore_health` / `agent_performance_summary` tools now work end-to-end because a successful tool call that doesn't get natural LLM synthesis still produces useful operator-facing output. Guards against re-invocation: skip if `final_answer` already has content, skip if 0 substantive tool calls (let hallucination guard handle), skip on explicit error/cancelled/escalated statuses (those have their own handling), idempotent on multiple terminal passes. `_REASON_LABELS` extended with `empty_completion -> "natural completion with empty final_answer"`. `gate_detection.py` extended to surface `empty_completion_rescued` in the Trace viewer's Gates Fired sidebar so operators can see which path rescued the run. Prometheus counters auto-extend — no metric changes needed because `FORCED_SYNTHESIS_COUNTER{reason,agent_type}` already accepts arbitrary reason labels. 2 new unit tests lock in the reason label round-trip through `build_harness_message` and `_programmatic_fallback`, plus a new integration test file `tests/test_empty_completion_path.py` with a scaffold for end-to-end assertion of the wiring (exact seam depends on how CC adapts the `_stream_agent` terminal write — test may fall back to mechanism assertion if no clean testable seam exists). The structural import of this fix: after v2.35.14, any agent run that produces status=completed MUST have non-empty `final_answer`, or it means the agent failed to make even one substantive tool call (which is a different failure mode handled by v2.34.8's hallucination guard). Previously operators had to guess whether an empty `final_answer` meant "agent had nothing to say" or "agent said something that got stripped" or "agent never got a chance to speak" — v2.35.14 closes the third case deterministically.

**v2.35.15** — fix(agents): near-empty / preamble-only final_answer detection + PBS+perf tool event-loop safety.
v2.35.14 verification run `07d326a1` (UniFi regression check against commit `c6afc70`, 2026-04-19) exposed a new shape of the same failure: `status=completed`, `final_answer_len=53`, chars decoded to `"I'll check the UniFi network device stat..."`. The LLM emitted a thinking preamble on step 1 before making any tool calls, then chose only tool calls on subsequent steps and never got back to a synthesis. The loop aggregated step 1's preamble text as `final_answer` and exited. v2.35.14's `len(final_answer) == 0` check correctly did NOT fire (53 > 0) — but operators still got a useless stub instead of a real synthesis. Fix generalises v2.35.14's single-trigger rescue into a three-way dispatch in the agent-loop terminal-write branch: `empty_completion` (v2.35.14, len==0), `too_short_completion` (v2.35.15, len < 60 chars — below the minimum plausible synthesis length, any real answer has at least a STATUS + a finding), `preamble_only_completion` (v2.35.15, starts with one of `i'll/let me/let's/sure/okay/first/i'm going to/to answer/to check/going to` AND no verdict marker like `STATUS:/FINDINGS:/ROOT CAUSE:/EVIDENCE:/CONCLUSION:/SUMMARY:/UNRESOLVED:/NEXT STEPS:` AND either len<200 or ends with ellipsis or ends without proper punctuation). Each reason gets its own Prometheus series via `FORCED_SYNTHESIS_COUNTER{reason}` (auto-extends, no metric schema change) and its own Gates Fired entry in the Trace viewer. The detector `_is_preamble_only()` is carefully scoped to avoid false positives on real short answers — `"STATUS: HEALTHY. All nodes Ready"` (33 chars) would still be caught by `too_short_completion` rather than `preamble_only_completion`, and `"I'll note that STATUS: HEALTHY based on the tool results"` passes both checks because of the verdict marker. Strengthens the v2.35.14 invariant from `status=completed ⇒ non-empty` to `status=completed ⇒ substantive`. Separately, v2.35.13's PBS and agent_perf tools showed `status=error` under agent invocation (op `2c0cb236`) despite direct-invoke returning `status=ok` moments earlier. Root cause: `asyncio.get_event_loop().run_until_complete(_q())` raises `RuntimeError: This event loop is already running` when called from inside the agent loop's active event loop. Replaced with synchronous engine pattern (same approach as v2.35.13's `_load_tool_calls_for_op`) — `create_engine()` + `conn.execute()` — no async wrapper needed because `invoke_tool()` is already synchronous from the agent's perspective. No latency regression, no event-loop entanglement. Tests: `tests/test_preamble_detection.py` with 4 cases (positive detection of 6 preamble variants, negative detection of 5 real short answers including tricky "I'll note that STATUS:" case, long-but-unfinished preamble detection, empty-text guard), extensions to `test_forced_synthesis_drift.py` validating the two new `_REASON_LABELS` entries and their round-trip through `_programmatic_fallback()`. Structural invariant after v2.35.15: every `status=completed` run either has a substantive final_answer (>=60 chars, no preamble shape) or the trace records exactly which rescue reason fired to produce it — no silent failures, no ambiguous empty-ish outcomes.

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
api/agents/gate_detection.py              — shared gate detection logic for /trace digest + UI (v2.34.16, v2.35.2, v2.35.3, v2.35.4)
gui/src/components/TraceView.jsx          — Logs → Trace tab, step list + detail + Gates Fired (v2.34.16)
gui/src/utils/gateDetection.js            — JS mirror of api/agents/gate_detection.py (v2.34.16)
api/db/known_facts.py                     — schema, upsert_fact, batch_upsert_facts, confidence formula, gauge snapshot (v2.35.0)
api/facts/extractors.py                   — collector-side fact extractors per platform (v2.35.0)
api/facts/tool_extractors.py              — per-tool fact extractors for in-run contradiction + agent_observation (v2.35.2)
api/routers/facts.py                      — /api/facts/* endpoints (v2.35.0 read paths, v2.35.0.1 admin paths)
api/security/facts_permissions.py         — user + role permission model, sith_lord implicit (v2.35.0.1)
api/agents/preflight.py                   — three-tier entity resolver (regex + keyword-DB + LLM fallback) (v2.35.1)
api/agents/fact_age_rejection.py          — soft/medium/hard rejection engine (v2.35.3)
api/agents/runbook_classifier.py          — keyword match v1 (semantic/LLM stubbed) (v2.35.4)
gui/src/components/FactsView.jsx          — Facts tab main view (v2.35.0.1)
gui/src/components/FactsCard.jsx          — Dashboard FACTS & KNOWLEDGE widget (v2.35.0.1)
gui/src/components/FactDiffViewer.jsx     — character / JSON-tree diff, extensible to config diffs (v2.35.0.1)
gui/src/components/FactLockModal.jsx      — lock creation (permission-gated) (v2.35.0.1)
gui/src/components/ConflictResolveModal.jsx — three-button conflict resolution (v2.35.0.1)
gui/src/components/PreflightPanel.jsx     — always-visible preflight with disambiguation UI (v2.35.1)
```
