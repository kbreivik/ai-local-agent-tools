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

Use `--dangerously-skip-permissions` (already in run_queue.sh) so CC runs without
per-file approval prompts. The prompts are reviewed — git is the safety net.

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

---

## Version bump rationale

| Bump | Meaning |
|---|---|
| x.x.1 | Fix, tuning, small addition |
| x.1.x | New subsystem, architectural change, multi-file feature |

---

## Phase summaries

**v2.16.0–v2.16.1** — Agent investigate-on-degraded + task templates.
**v2.17.0–v2.17.1** — Entity timeline + Proxmox console URL fix.
**v2.18.0–v2.18.1** — Result store viewer + synthesis on all completion paths.
**v2.19.0–v2.19.1** — service_placement tool + docker logs allowlist.
**v2.20.0–v2.20.2** — Investigation quality + VM card feedback + SSH log stream.
**v2.21.0–v2.21.2** — Time-series metrics + ES indexing + data pipeline health tab.
**v2.22.0–v2.22.1** — Dashboard summary endpoint + DashboardDataContext + skeleton loading.
**v2.22.2** (DONE feb929d) — TDZ hotfix.
**v2.22.3** — Root error boundary + per-section + frontend crash reporting.
**v2.22.4** — ESLint TDZ rule + source maps + API version gate + Dockerfile hardening.

**v2.23.0** — Fix VM host reboot + Proxmox action silent failures.
_vm_ssh_exec used raw credentials dict instead of _resolve_credentials — broke reboot/update
on any connection using a credential profile. _do_proxmox_action imported non-existent
NODES constant (ImportError on every call) — rewritten with proxmoxer + connection DB.
VMCard act() now shows error text when ok=false.

**v2.23.1** — Entity cross-reference registry + resolve_entity agent tool.
infra_inventory extended with resolve_entity (multi-source: infra_inventory + connections
table + IP overlap merge). Proxmox collector writes VM name/vmid/node/aliases to inventory
on every poll. New resolve_entity MCP tool resolves ambiguous names like 'worker 2' across
all systems. Registered in all agent allowlists.

**v2.22.6** — agentHostIp setting (Infrastructure tab) + clickable container endpoints.
Collector reads LAN IP from settings DB (priority over env var). Container card expanded
view gains a clickable `endpoint` link from `ip_port`. Internal Docker IPs demoted to
dimmed `int.ips` row.

**v2.22.5** — Fix GHCR tag pagination + version status display.
_fetch_ghcr_tags() stopped pagination as soon as it accumulated 20 semver-matching tags.
GHCR returns tags alphabetically so the first 20 matches were always the oldest ones
(2.14.0 → 2.19.1). Versions 2.20.x–2.22.x exist on GHCR (CI pushes them correctly)
but were on a later page never fetched. Fix: remove early-exit, increase max pages
to 10. Frontend: when running_version > tags[0] (severity='ahead') and update-status
reports update_available=false, status badge shows '✓ latest' instead of '—'. Pull
Latest button hidden when update_available=false (digests match, no pull needed).

---

## Key file paths

```
api/db/vm_exec_allowlist.py               — allowlist table + cache + session purge (v2.23.3)
api/routers/vm_exec_allowlist.py          — REST API for allowlist management (v2.23.3)
mcp_server/tools/vm.py                    — _validate_command DB-backed + 3 new tools (v2.23.3)
api/agents/router.py                      — new allowlist tools in all allowlists (v2.23.3)
api/routers/agent.py                      — session purge on cleanup (v2.23.3)
gui/src/components/OptionsModal.jsx       — Allowlist tab (v2.23.3)
api/routers/settings.py                   — agentHostIp setting key (v2.22.6)
api/collectors/docker_agent01.py         — _get_agent01_ip() reads settings DB (v2.22.6)
gui/src/components/OptionsModal.jsx      — Agent Host IP field in Infrastructure tab (v2.22.6)
gui/src/components/ServiceCards.jsx      — clickable endpoint + dimmed int.ips (v2.22.6)
api/routers/dashboard.py                 — _vm_ssh_exec credential fix + Proxmox action fix (v2.23.0)
gui/src/components/VMHostsSection.jsx    — act() error feedback (v2.23.0)
api/db/infra_inventory.py                — resolve_entity + write_cross_reference (v2.23.1)
api/collectors/proxmox_vms.py            — write VMs to infra_inventory (v2.23.1)
mcp_server/tools/vm.py                   — resolve_entity tool (v2.23.1)
api/agents/router.py                     — resolve_entity in allowlists (v2.23.1)
gui/src/components/ServiceCards.jsx      — GHCR version status + pull button fix (v2.22.5)
api/routers/dashboard.py                 — _fetch_ghcr_tags pagination fix (v2.22.5)
gui/src/context/DashboardDataContext.jsx — shared dashboard state + version gate (v2.22.0, v2.22.4)
gui/src/components/SkeletonCard.jsx      — shimmer skeleton components (v2.22.1)
gui/src/components/DashboardLayout.jsx   — SectionErrorBoundary (v2.22.3)
gui/src/App.jsx                          — RootErrorBoundary (v2.22.3)
api/routers/errors.py                    — /api/errors/frontend crash reporting (v2.22.3)
api/alerts.py                            — health_change WS broadcast (v2.22.1)
eslint.config.js                         — no-use-before-define rule (v2.22.4)
gui/vite.config.js                       — sourcemap: hidden (v2.22.4)
.dockerignore                            — excludes build artifacts (v2.22.4)
api/db/metric_samples.py                 — time-series metrics (v2.21.0)
mcp_server/tools/metric_tools.py         — metric_trend + list_metrics (v2.21.0)
api/collectors/base.py                   — ES snapshot indexing (v2.21.1)
api/db/vm_action_log.py                  — vm action audit table (v2.20.1)
api/agents/router.py                     — prompts + allowlists (v2.18.1–v2.21.0)
mcp_server/tools/vm.py                   — service_placement + docker logs (v2.19.0, v2.19.1)
```
