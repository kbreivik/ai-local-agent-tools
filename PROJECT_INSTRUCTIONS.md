# DEATHSTAR — Imperial Ops Platform
## Claude Project Instructions

You are assisting with active development of the DEATHSTAR platform, a self-hosted infrastructure
monitoring and AI agent orchestration platform built with FastMCP + FastAPI + React.

---

## Core Facts

| Item | Value |
|------|-------|
| Repo | https://github.com/kbreivik/ai-local-agent-tools (public, MIT) |
| Current version | See `VERSION` file — read it, never assume |
| Stack | FastMCP + FastAPI (Python) + React (Vite) |
| Deploy target | agent-01 at 192.168.199.10:8000 |
| Docker image | ghcr.io/kbreivik/hp1-ai-agent:latest |
| LM Studio | MS-S1 at 192.168.199.51:1234 (Qwen3-Coder-30B, 256k context) |
| Database | Postgres (pgvector/pg16) at 127.0.0.1:5433 |
| Memory store | MuninnDB at ghcr.io/scrypster/muninndb:latest, plus pg_engrams backend |
| Repo root (local) | `D:\claude_code\ai-local-agent-tools\` |

---

## VERSION DISCIPLINE — INVIOLABLE

**Before any operation on a `cc_prompts/CC_PROMPT_v*.md` file, read `cc_prompts/INDEX.md` first.**

Status semantics:
- **PENDING** — not yet executed by CC. Editing is allowed.
- **DONE (sha)** — committed to main. The file is **historical record** and must NOT be modified, ever.

Rules:
1. Never reuse a version. Always bump to the next ascending version.
2. If a request would alter a DONE prompt's content: restore the DONE prompt to its committed state and queue the change as the next ascending version.
3. Never assume a version is "yours" because the file exists locally. INDEX.md status is the source of truth.
4. When in doubt: read VERSION, read INDEX.md tail, then act.
5. Exhaust `x.y.N` before starting `x.(y+1).0`. No backfilling once a minor ships.

If I (Claude) ever propose editing a DONE prompt, push back hard. The user will, but the burden is on me to not propose it in the first place.

---

## Development Workflow — CC Prompt Queue

All code changes go through Claude Code (CC) via structured prompt files.
**One prompt = one version bump = one git commit.**
Claude in chat (architect) writes the prompts; CC (executor) implements them.

### File structure
```
cc_prompts/
  INDEX.md              ← queue table + phase summaries (source of truth for status)
  QUEUE_RUNNER.md       ← project context injected into every CC run
  run_queue.sh          ← queue runner (Git Bash)
  CC_PROMPT_vX.Y.Z.md   ← one file per version bump
```

### Prompt file format
```markdown
# CC PROMPT — vX.Y.Z — Title

## What this does
2-3 sentences. Version bump: X.Y.Z-1 → X.Y.Z

## Change 1 — path/to/file.py
[exact code with context]

## Verify
[grep / py_compile / curl checks]

## Version bump
Update VERSION: X.Y.Z-1 → X.Y.Z

## Commit
git add -A
git commit -m "type(scope): vX.Y.Z description"
git push origin main
```

### Adding to the queue
1. Write `cc_prompts/CC_PROMPT_vX.Y.Z.md`
2. Append row to INDEX.md Phase Queue table:
   `| CC_PROMPT_vX.Y.Z.md | vX.Y.Z | Short description | PENDING |`

### Running the queue
```bash
bash cc_prompts/run_queue.sh          # all pending, streams output live
bash cc_prompts/run_queue.sh --one    # one at a time
bash cc_prompts/run_queue.sh --dry-run
```
CC implements, commits, pushes, then updates INDEX.md PENDING → DONE (SHA) and commits that too.

### Settings-driven feature pattern (4 layers)
A new tunable variable requires changes in **all four** layers, or it won't appear in the GUI:
1. Backend `SETTINGS_KEYS` in `api/routers/settings.py` — registry entry with default/min/max/group
2. Frontend `DEFAULTS` in `gui/src/context/OptionsContext.jsx` — initial value
3. Frontend `SERVER_KEYS` set in same file — marks key as persisted via API
4. Frontend render in `gui/src/components/OptionsModal.jsx` — input field in the relevant tab

Skipping any layer leaves the variable invisible to operators.

### Version bump convention
| Bump | When |
|------|------|
| x.x.1 | Fix, tuning, small addition |
| x.1.x | New subsystem, multi-file architectural change |
| 1.x.x | Major architectural shift |

### After CC pushes
```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
Always force-refresh browser after deploy to clear stale JS bundles.

---

## Architecture Overview

### Backend (FastAPI)
- `api/main.py` — app startup, mounts routers, initialises collectors
- `api/auth.py` — JWT (HS256) + httpOnly cookie + bearer fallback, role-gated
- `api/connections.py` — connections DB, Fernet encryption, `get_connection_for_platform()`
- `api/collectors/manager.py` — CollectorManager, BaseCollector auto-discovery, `trigger_poll()`
- `api/agents/router.py` — task classifier, tool allowlists, 4 agent system prompts
- `api/agents/preflight.py` — entity disambiguation; runs before agent loop
- `api/agents/external_ai_confirmation.py` — gate before external AI calls (v2.36+)
- `api/routers/agent.py` — `POST /api/agent/run`, `_stream_agent`, `_token_cap_for`, gates
- `api/routers/tests_api.py` — test harness; exports `test_run_active` flag
- `api/routers/settings.py` — `SETTINGS_KEYS` registry (the source of truth for tunables)
- `api/db/known_facts.py` — facts store (DDL in module, separate from migrations.py)
- `api/db/result_store.py` — large tool result storage (2h TTL)
- `api/memory/feedback.py` — MuninnDB engram writes (record_outcome)
- `mcp_server/tools/vm.py` — vm_exec, kafka_exec, swarm_node_status, swarm_service_force_update, proxmox_vm_power

### Frontend (React + Vite)
- `gui/src/index.css` — V3a Imperial theme (Share Tech Mono + Rajdhani, crimson accent)
- `gui/src/App.jsx` — sidebar nav, routing, DashboardView, DrillDownBar
- `gui/src/components/ServiceCards.jsx` — Section + InfraCard pattern; standard rich card
- `gui/src/components/Sidebar.jsx` — navigation + user menu
- `gui/src/components/OptionsModal.jsx` — exports `TABS` and all settings tab components
- `gui/src/components/SettingsPage.jsx` — wraps OptionsModal tabs as full-page view
- `gui/src/components/ComparePanel.jsx` — exports SLOT_COLORS
- `gui/src/components/EscalationBanner.jsx` — persistent amber banner
- `gui/src/components/PreflightPanel.jsx` — disambiguation modal
- `gui/src/components/CardFilterBar.jsx` — must stay in sync with ServiceCards.jsx
- `gui/src/context/OptionsContext.jsx` — `DEFAULTS`, `SERVER_KEYS`, persistence

### Key file paths (verbatim)
- VERSION: `D:\claude_code\ai-local-agent-tools\VERSION`
- INDEX: `cc_prompts\INDEX.md`
- Spec docs: `PHASE_v2.35_SPEC.md`, `docs/REFERENCE.md` (auto-generated, drift-checked in CI)
- Architecture reference: `CLAUDE.md`

---

## Critical Architecture Notes

### Entity ID format
`platform:name:id` — e.g. `proxmox:hp1-agent:9200`, `external_services:unifi`, `connection:42`

### NETWORK/STORAGE/SECURITY cards
Rendered via `ConnectionSectionCards` in `App.jsx` (~line 808), bypassing `InfraCard`.
Ctrl+click/compare support is absent there unless explicitly added.

### CardFilterBar / ServiceCards sync
New platform types need explicit addition to `INFRA_SECTION_KEYS` in `CardFilterBar.jsx` or sections silently won't render.

### Collector trigger map
| Platform saved/deleted | Collectors triggered |
|------------------------|----------------------|
| proxmox, pbs           | proxmox_vms + external_services |
| fortiswitch, cisco, juniper, aruba | network_ssh + external_services |
| anything else          | external_services |

### Agent system — 4 types
| Type | When | Key rule |
|------|------|----------|
| observe | status checks, read-only | tool budget 8 |
| investigate | why/diagnose/logs | budget 16; elastic + correlation |
| execute | fix/restart/deploy | plan_action required before destructive ops; budget 14 |
| build | skill management | skill_create, skill_regenerate; budget 12 |

### Hallucination guard
Critical. Agent must call `dmesg` before any OOM conclusion (exit 137 ≠ OOM).
Agent must not call `final_answer` when substantive tool calls are below threshold.

### Sub-agent pattern
Budget nudge at 60% → sub-agent spawned with fresh `StepState` → real tool calls → grounded diagnosis → parent synthesises.
Each sub-agent has its own fresh token-cap counter (no shared cap across the tree).
Tree-wide wall-clock cap: `SUBAGENT_TREE_WALL_CLOCK_S=1800s`. Depth cap: 2.

### Test isolation (v2.47.9 — v2.47.11)
When `test_run_active=True`:
- External AI routing skipped entirely
- `agent_observation` fact writes skipped
- MuninnDB `record_outcome` writes skipped
- `agent_attempts` writes skipped
- Un-pre-armed clarification gates auto-cancel
- Un-pre-armed plan gates auto-reject
This isolates test runs from cross-test contamination and prevents zombie modal popups.

### Token caps (v2.47.12 + v2.47.13)
Settings-driven via `_token_cap_for(agent_type)`. Lookup: per-type → global → env → hardcoded.
GUI: Settings → AI Services → Agent Budgets section.

### Escalation visibility
`agent_escalations` table. Persistent amber `EscalationBanner` with ACK button.
WebSocket `escalation_recorded` event for immediate update.

---

## Connections as Universal Registry

The connections DB is the single source of truth for all external services.

| Section | Platforms |
|---------|-----------|
| COMPUTE | proxmox, pbs |
| NETWORK | fortigate, fortiswitch, opnsense, cisco, juniper, aruba, unifi, pihole, technitium, nginx, caddy, traefik |
| STORAGE | truenas, pbs, synology, syncthing |
| SECURITY | security_onion, wazuh, grafana, kibana |

Proxmox token fields split at `!`:
`terraform@pve!terraform-token` → `user=terraform@pve`, `token_name=terraform-token`

---

## Infrastructure (Current State)

### Swarm cluster
- 3 managers: ds-docker-manager-01..03 (199.21..23)
- 3 workers: ds-docker-worker-01..03 (199.31..33)
- agent-01: hp1-ai-agent-lab (199.10)
- All 7 registered as vm_host connections
- worker-03 historically unstable → kafka_broker-3 unscheduled when down

### Kafka
- 3-broker KRaft cluster (kafka_broker-1/2/3 Swarm services on workers)
- hp1-logs: 3 partitions, RF=3, min.insync.replicas=2
- `KAFKA_UNDER_REPLICATED_THRESHOLD=1` in `.env`
- Recovery: reboot worker-03 VM from Proxmox → broker-3 self-schedules → cluster reforms

### Credential profiles
Named shared auth sets. One "ubuntu-ssh-key" profile shared across all 6 worker/manager connections.

---

## CSS Theme (V3a Imperial)
```css
--font-sans: 'Rajdhani', sans-serif;
--font-mono: 'Share Tech Mono', monospace;
--bg-0: #05060a;  --bg-1: #09090f;  --bg-2: #0d0f1a;
--accent: #a01828;  --accent-dim: rgba(160,24,40,0.12);
--cyan: #00c8ee;  --green: #00aa44;  --amber: #cc8800;  --red: #cc2828;
--radius-card: 2px;  --radius-btn: 2px;
```
Always use CSS vars. Never hardcode colours.

## Auth System
Roles: `sith_lord` (full admin) | `imperial_officer` (ops) | `stormtrooper` (monitoring) | `droid` (read-only API)

---

## Hard-Won Operational Patterns

### Verification per build
1. Check `/api/health` for version/build (force `cache:'no-store'` + random query param + `Cache-Control: no-cache` header — all three required, two of three is insufficient)
2. Poll session log stats
3. Trigger agent run via Commands page
4. Inspect operation details via `/api/logs/operations/{id}`
5. Force-refresh browser to clear stale JS bundles

### Chrome MCP patterns
- Auth token: `localStorage.getItem('hp1_auth_token')` as `Authorization: Bearer ${token}`
- Async fetch: store result in `window.__varname`, read in follow-up `javascript_exec`
- Scroll: `div.scrollTop = div.scrollHeight` on `.flex-1.overflow-auto.min-h-0`
- Click by `ref` from `find` more reliable than coordinate clicks
- Background polling: `setInterval` stored on `window.__pollTimer`, `clearInterval` to stop
- 503 on JS bundle = Docker mid-restart, wait 8s
- JWT token content in API responses appears as `[BLOCKED: JWT token]` — sanitization artifact, read source files directly

### Filesystem MCP
- `read_text_file` with `head`/`tail` to avoid context bloat
- `read_multiple_files` for batching (~5 files per call)
- `jcodemunch` indexes Python only — use direct filesystem reads for JSX/JS

### Bash on Git Bash
- `grep -c` returns values like `"3\r"` — strip with `tr -dc '0-9'` for arithmetic comparisons
- npm rejects four-segment versions — translate `X.Y.Z.N` to `X.Y.Z` for npm only (handled in `.github/workflows/build.yml`)

### Settings backend caveats
- Settings registry read at lookup time (no module-load caching)
- `_coerce_token_cap` returns hardcoded default for 0/invalid (does not fall through to global)
- Per-type keys with non-zero values always win over global

### Diagnostic data sources
- `[harness]` log lines do NOT appear in `docker logs` — they go to `operation_log` PG table via `manager.send_line`
- `/metrics` endpoint is auth-gated since v2.45.21 (Bearer token required)
- `operations.label` carries task text (NOT `operations.task`)
- `operations.session_id` ≠ `operations.id`
- Counter names exist in metrics.py but appear in `/metrics` only after first `.inc()`

### Communication style with the user
- Brief and technically direct
- Confirms builds with commit hashes
- Advances with "continue" or "next todo"
- Expects me to verify live deployments via Chrome MCP before moving on
- Never type passwords into forms or place them in URLs; user authenticates, I drive from authenticated session
- Networking, Proxmox, Fortinet, Python, SQL, C# are user's favourite tech

---

## Known Deferred Items
- worker-03 stability issues
- Proxmox Cluster FIN — VPN dependency on dev PC, move WireGuard to agent-01
- Entity timeline view (click card → change history inline)
- Agent task templates (one-click common ops)
- Proxmox VM noVNC console link from card
- Real notification delivery test (not webhook.site)
- TLS reverse proxy (no nginx/traefik config in repo)
- `/metrics` localhost-only restriction or auth tightening
- Tree-wide token cap for sub-agent trees

---

## Tools & Resources
- Chrome MCP, Filesystem MCP, jcodemunch (Python only)
- Key env file: `/opt/hp1-agent/docker/.env` — never print `SETTINGS_ENCRYPTION_KEY`
- Design mockups: `docs/mockups/vX.Y.Z_<slug>_roundN.html` (NOT in cc_prompts)
- CC prompts: `cc_prompts/`

---

## Pre-flight checklist before writing a CC prompt
1. Read `VERSION` — confirm current version
2. Read `cc_prompts/INDEX.md` tail — find next available version
3. Read the file(s) being modified — confirm current state matches assumptions
4. Write prompt as `CC_PROMPT_v{next}.md`
5. Append PENDING row to INDEX.md
6. Stop. Do NOT execute. CC owns execution.
