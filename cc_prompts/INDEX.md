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

# PowerShell (Windows Terminal)
cd D:\claude_code\ai-local-agent-tools
.\cc_prompts\run_queue.ps1 -DryRun
.\cc_prompts\run_queue.ps1 -One
.\cc_prompts\run_queue.ps1
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
| CC_PROMPT_v2.15.6.md | v2.15.6 | Platform Core value-before-tag + alphabetical sorting everywhere | DONE (050b865) |
| CC_PROMPT_v2.15.7.md | v2.15.7 | Container cards: name fix, real IP, networks, per-host Section | DONE (55ab911) |
| CC_PROMPT_v2.15.8.md | v2.15.8 | Multi-expand cards + shift-click range + toolbar expand/collapse | PENDING |

---

## Version bump rationale

| Bump | Meaning |
|---|---|
| x.x.1 | Fix, tuning, small addition |
| x.1.x | New subsystem, architectural change, multi-file feature |

---

## Phase summaries

**v2.15.5** — Layouts tab blank page fixed (missing `/api/layout/templates` endpoint + null
guards on layout prop). Admin user menu stripped to Log out only (Layouts/Notifications
already in Settings sidebar). Footer `admin · v2.15.x`: crimson tint background, 10px
font, version highlighted in accent red for visual distinction.

**v2.15.6** — Platform Core rows: value (v2.15.4, pg16) now appears before the status
tag (ONLINE, HEALTHY) — information then state, both right-aligned. VM sort default
changed to name ascending. Container and connection lists sorted alphabetically.

**v2.15.7** — Container card name is primary label (was showing image URL). Image string
shortened to `repo:tag` only. Compact card shows real IP:port (loopback filtered, port-
only fallback). Expanded card shows Docker networks + all IPs. Containers section gets
cluster-style Section header per docker_host connection (like Proxmox clusters).
Backend: connection_id/label/host added to container collector response.

**v2.15.8** — `openKeys` Set replaces `openKey` single value — multiple cards can be
expanded simultaneously. Shift+click expands range between last-opened and clicked card
using DOM data-card-key attributes within the section. DrillDownBar gets two new buttons:
EXPAND/COLLAPSE ALL cards and EXPAND/COLLAPSE ALL sections, using window custom events
to signal ServiceCards and Section components. VM cards narrower at 240px default.

---

## Key file paths

```
api/routers/layout.py               — layout templates endpoint (v2.15.5)
gui/src/components/Sidebar.jsx      — user menu + footer (v2.15.5)
gui/src/components/LayoutsTab.jsx   — null guards (v2.15.5)
gui/src/App.jsx                     — Platform Core row order, DrillDownBar (v2.15.6, v2.15.8)
gui/src/components/ServiceCards.jsx — sort defaults, container cards, openKeys (v2.15.6–8)
api/collectors/swarm.py             — connection metadata in container response (v2.15.7)
```
