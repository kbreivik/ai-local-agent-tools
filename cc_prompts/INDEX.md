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
| CC_PROMPT_v2.20.0.md | v2.20.0 | Investigation quality: structured output + clarifying questions + evidence exhaustion | PENDING |
| CC_PROMPT_v2.20.1.md | v2.20.1 | VM card action audit trail + visual feedback | DONE (f507583) |
| CC_PROMPT_v2.20.2.md | v2.20.2 | VM card SSH log stream + live logs filter fix | RUNNING |

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

**v2.19.0** — service_placement tool: swarm service → node → vm_host bridge.

**v2.19.1** — docker logs allowlist + investigation depth rules.

**v2.20.0** — Investigation quality: 4-section output + evidence exhaustion tiers.

**v2.20.1** — VM card action audit trail + visual feedback.
New `vm_action_log` table records every VM card action (reboot, update, service restart)
with user, status, output, timestamps. vm_reboot/update/service_restart endpoints now
log to this table and broadcast `vm_action` WebSocket events. VMCard subscribes to
`ws:message` window events and shows: pulsing amber REBOOTING badge with 90s countdown,
UPDATING badge during apt, auto-refresh after reboot completes, buttons disabled during
action. AgentOutputContext dispatches ws:message for cross-component WS access.

**v2.20.2** — VM card SSH log stream + live logs filter fix.
_ssh_run_streaming() in vm_hosts.py yields SSH channel output line by line.
GET /api/dashboard/vm-hosts/{id}/logs/stream: SSE journalctl -f via SSH, service filter.
VMCard: "Live Logs" button opens 180px scrollable SSH journal panel with level coloring
and optional service filter (docker, ssh, filebeat, active systemd services).
VMCard: Recent Actions section shows last 5 actions.
Unified log generator ES reader: both container.name and host.name preserved; display_name
uses container.name when available, falls back to host.name for host-level ES events.

---

## Key file paths

```
api/db/vm_action_log.py                — vm action audit table (v2.20.1)
api/routers/dashboard.py               — VM action endpoints + SSH log stream (v2.20.1, v2.20.2)
api/collectors/vm_hosts.py             — _ssh_run_streaming helper (v2.20.2)
api/routers/logs.py                    — result-store endpoints (v2.18.0)
api/routers/entities.py                — entity list + history endpoint (v2.17.0)
api/routers/agent.py                   — synthesis on all paths (v2.18.1, v2.20.0)
api/agents/router.py                   — prompts + allowlists (v2.18.1–v2.20.0)
mcp_server/tools/vm.py                 — service_placement + docker logs (v2.19.0, v2.19.1)
mcp_server/server.py                   — service_placement registration (v2.19.0)
gui/src/components/VMHostsSection.jsx  — action state + SSH log panel (v2.20.1, v2.20.2)
gui/src/context/AgentOutputContext.jsx — ws:message window event dispatch (v2.20.1)
gui/src/components/TaskTemplates.jsx   — one-click task templates (v2.16.1)
gui/src/components/EntityDrawer.jsx    — timeline section (v2.17.0)
gui/src/components/ServiceCards.jsx    — Proxmox console URL fix (v2.17.1)
gui/src/components/LogsPanel.jsx       — Result Refs tab (v2.18.0)
```
