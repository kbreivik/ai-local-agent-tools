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
| CC_PROMPT_v2.15.9.md | v2.15.9 | Agent Swarm recovery tools + pre-flight bypass | PENDING |
| CC_PROMPT_v2.15.10.md | v2.15.10 | Escalation visibility: persistent banner + acknowledge | PENDING |

---

## Version bump rationale

| Bump | Meaning |
|---|---|
| x.x.1 | Fix, tuning, small addition |
| x.1.x | New subsystem, architectural change, multi-file feature |

---

## Phase summaries

**v2.15.9** — Three new agent tools for Swarm/infra recovery:
`swarm_node_status()` — `docker node ls` + failed task list from a manager (read-only, always allowed).
`swarm_service_force_update(service_name)` — SSH to manager, runs `docker service update --force`, requires plan_action.
`proxmox_vm_power(vm_label, action)` — start/stop/reboot Proxmox VM when a worker node is completely down.
Pre-flight bypass: `pre_kafka_check` skipped when task is explicitly a remediation/fix/restart.
Recovery workflow added to ACTION_PROMPT with node-down → Proxmox reboot path.
Blocked tool rule: agent must provide exact manual SSH command instead of escalating.

**v2.15.10** — Escalations now visible outside the output panel.
`agent_escalations` table stores all escalations with reason, session ID, severity.
`record_escalation()` called when agent escalates or halts on degraded tool result.
REST endpoints: list, acknowledge, acknowledge-all.
`EscalationBanner` component: persistent amber banner in dashboard between drill bar and content.
Pulsing dot, reason text, ACK button, ACK ALL button.
WebSocket `escalation_recorded` event triggers immediate banner update.
Zero height when no escalations — no layout impact on normal operation.

---

## Key file paths

```
api/routers/escalations.py          — escalation table + endpoints (v2.15.10)
api/routers/agent.py                — record_escalation calls + WS broadcast (v2.15.10)
gui/src/components/EscalationBanner.jsx — persistent amber banner (v2.15.10)
mcp_server/tools/vm.py              — swarm_node_status, swarm_service_force_update, proxmox_vm_power (v2.15.9)
mcp_server/server.py                — tool registration (v2.15.9)
api/agents/router.py                — allowlists + ACTION_PROMPT recovery workflow (v2.15.9)
api/routers/layout.py               — layout templates endpoint (v2.15.5)
gui/src/components/Sidebar.jsx      — user menu + footer (v2.15.5)
gui/src/App.jsx                     — EscalationBanner mount, Platform Core row order (v2.15.6, v2.15.10)
gui/src/components/ServiceCards.jsx — sort defaults, container cards, openKeys (v2.15.6–8)
```
