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
| CC_PROMPT_v2.16.1.md | v2.16.1 | Agent task templates in CommandPanel | DONE (f20e94e) |
| CC_PROMPT_v2.17.0.md | v2.17.0 | Entity timeline view in EntityDrawer | DONE (39ab8dd) |
| CC_PROMPT_v2.17.1.md | v2.17.1 | Fix Proxmox noVNC console URL (uses actual Proxmox host) | DONE (f7b118b) |
| CC_PROMPT_v2.18.0.md | v2.18.0 | Result store viewer in Logs tab | DONE (22c9709) |
| CC_PROMPT_v2.18.1.md | v2.18.1 | Synthesis on all completion paths + Kafka diagnostic prompts | DONE (09119c4) |
| CC_PROMPT_v2.19.0.md | v2.19.0 | service_placement tool: swarm service → node → vm_host | PENDING |

---

## Version bump rationale

| Bump | Meaning |
|---|---|
| x.x.1 | Fix, tuning, small addition |
| x.1.x | New subsystem, architectural change, multi-file feature |

---

## Phase summaries

**v2.16.0** — Agent investigate-on-degraded + halt synthesis.

**v2.16.1** — Agent task templates in CommandPanel (18 pre-built tasks, 5 domain groups).

**v2.17.0** — Entity timeline view in EntityDrawer (field changes + events, lazy-loaded).

**v2.17.1** — Fix Proxmox noVNC console URL to use actual Proxmox host.

**v2.18.0** — Result store viewer in Logs tab (browse active rs-* refs + rows).

**v2.18.1** — Synthesis fires on all completion paths + Kafka diagnostic chain in prompts.
audit_log completion path and finish=stop path now trigger synthesis when _degraded_findings
are present. Synthesis output: root cause + what was checked + numbered fix steps + which
steps agent can automate. STATUS_PROMPT and RESEARCH_PROMPT: Kafka diagnostic chain
(kafka_broker_status → swarm_node_status → docker service ps via vm_exec → kafka_exec).
infra_lookup kwarg corrected to 'query=' in both prompts. 'run_ssh' does not exist note added.

**v2.19.0** — service_placement tool: swarm service → node → vm_host bridge.
service_placement(service_name) SSHes to a manager, runs docker service ps, cross-references
node hostnames to vm_host connections. Returns: task state, error, vm_host_label, vm_host_ip,
ssh_ready flag. Partial service name supported. Added to OBSERVE and INVESTIGATE allowlists.
STATUS_PROMPT and RESEARCH_PROMPT: topology shortcut section with example 3-step workflow
(service_placement → vm_exec → kafka_exec). Closes the gap between Kafka cluster visibility
and node-level SSH diagnosis.

---

## Key file paths

```
api/routers/logs.py                    — result-store endpoints (v2.18.0)
api/routers/entities.py                — entity list + history endpoint (v2.17.0)
api/routers/agent.py                   — synthesis on all paths (v2.18.1)
api/agents/router.py                   — prompts + allowlists (v2.18.1, v2.19.0)
mcp_server/tools/vm.py                 — service_placement tool (v2.19.0)
mcp_server/server.py                   — tool registration (v2.19.0)
gui/src/components/TaskTemplates.jsx   — one-click task templates (v2.16.1)
gui/src/components/EntityDrawer.jsx    — timeline section (v2.17.0)
gui/src/components/ServiceCards.jsx    — Proxmox console URL fix (v2.17.1)
gui/src/components/CommandPanel.jsx    — mounts TaskTemplates (v2.16.1)
gui/src/components/LogsPanel.jsx       — Result Refs tab (v2.18.0)
gui/src/api.js                         — fetchEntityHistory, fetchResultRefs, fetchResultRef
```
