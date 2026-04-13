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
| CC_PROMPT_v2.16.1.md | v2.16.1 | Agent task templates in CommandPanel | PENDING |
| CC_PROMPT_v2.17.0.md | v2.17.0 | Entity timeline view in EntityDrawer | PENDING |
| CC_PROMPT_v2.17.1.md | v2.17.1 | Fix Proxmox noVNC console URL (uses actual Proxmox host) | PENDING |
| CC_PROMPT_v2.18.0.md | v2.18.0 | Result store viewer in Logs tab | PENDING |
| CC_PROMPT_v2.18.1.md | v2.18.1 | Synthesis on all completion paths + Kafka diagnostic prompts | PENDING |
| CC_PROMPT_v2.19.0.md | v2.19.0 | service_placement tool: swarm service → node → vm_host | PENDING |
| CC_PROMPT_v2.19.1.md | v2.19.1 | docker logs allowlist + investigation depth rules | PENDING |
| CC_PROMPT_v2.20.0.md | v2.20.0 | Investigation quality: structured output + clarifying questions | PENDING |
| CC_PROMPT_v2.20.1.md | v2.20.1 | VM card action audit trail + visual feedback | PENDING |
| CC_PROMPT_v2.20.2.md | v2.20.2 | VM card SSH log stream + live logs filter fix | PENDING |
| CC_PROMPT_v2.21.0.md | v2.21.0 | Time-series metric_samples table + metric_trend agent tool | PENDING |
| CC_PROMPT_v2.21.1.md | v2.21.1 | Container lifecycle events + collector snapshots to Elasticsearch | PENDING |
| CC_PROMPT_v2.21.2.md | v2.21.2 | Data pipeline health tab (ES doc counts, PG snapshot freshness) | DONE (bf6bae3) |
| CC_PROMPT_v2.22.0.md | v2.22.0 | Dashboard summary endpoint + DashboardDataContext shared state | DONE (676fa82) |
| CC_PROMPT_v2.22.1.md | v2.22.1 | Skeleton loading + WebSocket-driven live updates | PENDING |

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

**v2.22.0** — Dashboard summary endpoint + DashboardDataContext.
Root cause of slow GUI: ~12 simultaneous API calls on load; 5 components independently
polling the same data every 30s. Fix: GET /api/dashboard/summary returns all dashboard
data in one call (5 parallel PG snapshot reads). DashboardDataContext is a shared React
context owning all fetches. Tiered intervals: external=30s, summary=60s, stats=60s,
health=90s, connections=once. Staggered initial load (200ms between each). SubBar drops
6-call-per-30s cycle to zero (derives alert list from context). ConnectionSectionCards
drops 30s interval. VMHostsSection reads from context.
Net: 12 simultaneous calls on load → 5 staggered; 30s duty cycle from ~20 calls → 2.

**v2.22.1** — Skeleton loading + WebSocket-driven live updates.
SkeletonCard/SkeletonGrid shimmer components; ds-shimmer CSS keyframe. COMPUTE,
CONTAINERS, VM_HOSTS sections show skeleton grids while summaryLoading=true — layout
visible instantly, data fills in progressively. DashboardDataContext WS listener:
health_change/vm_action/alert events trigger immediate refreshSummary(). DrillDownBar
stale badge (>90s) with click-to-refresh. api/alerts.py check_transition() broadcasts
health_change WS event — frontend responds in seconds not minutes.

---

## Key file paths

```
gui/src/context/DashboardDataContext.jsx — shared dashboard state (v2.22.0)
gui/src/components/SkeletonCard.jsx      — shimmer skeleton components (v2.22.1)
api/routers/dashboard.py                — /summary endpoint (v2.22.0)
api/alerts.py                           — health_change WS broadcast (v2.22.1)
api/db/metric_samples.py               — time-series metrics table (v2.21.0)
mcp_server/tools/metric_tools.py       — metric_trend + list_metrics tools (v2.21.0)
api/collectors/base.py                 — ES snapshot indexing (v2.21.1)
api/collectors/swarm.py                — replica lifecycle events (v2.21.1)
api/collectors/external_services.py   — latency samples (v2.21.1)
api/db/vm_action_log.py                — vm action audit table (v2.20.1)
api/collectors/vm_hosts.py             — metric samples + _ssh_run_streaming (v2.20.2, v2.21.0)
api/agents/router.py                   — prompts + allowlists (v2.18.1–v2.21.0)
mcp_server/tools/vm.py                 — service_placement + docker logs (v2.19.0, v2.19.1)
gui/src/components/VMHostsSection.jsx  — action state + SSH log panel (v2.20.1, v2.20.2)
gui/src/context/AgentOutputContext.jsx — ws:message window event (v2.20.1)
```
