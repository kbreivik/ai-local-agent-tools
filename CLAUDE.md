# DEATHSTAR — Claude Code Guide
## Version: 2.46.0

Self-hosted infrastructure monitoring and AI agent orchestration platform.
FastMCP + FastAPI backend, React (Vite) frontend, Docker Swarm deployment.

---

## Core Facts

| Item | Value |
|---|---|
| Repo | github.com/kbreivik/ai-local-agent-tools (public, MIT) |
| Current version | v2.46.0 (see `VERSION` — single source of truth) |
| Stack | FastMCP + FastAPI (Python 3.13) + React (Vite/JSX) |
| Deploy target | agent-01 at `192.168.199.10:8000` (standalone container) |
| Docker image | `ghcr.io/kbreivik/hp1-ai-agent:latest` |
| LM Studio | MS-S1 at `192.168.199.51:1234` (Qwen3-Coder-30B) |
| Database | Postgres (pgvector/pg16) at `127.0.0.1:5433` |
| Memory store | MuninnDB at `ghcr.io/scrypster/muninndb:latest` |

---

## WISC Context Protocol
- **Always read `state/HANDOFF.md`** at session start if it exists
- **Always run `/handoff`** before ending a session
- **Use subagents** — don't load full skill modules or service state directly
- Context >60%: run `/compact`

---

## Development Workflow — CC Prompt Queue

All code changes go through Claude Code (CC) via structured prompt files.
**One prompt = one version bump = one git commit.**
Claude in chat writes the prompts; CC implements them.

### File structure
```
cc_prompts/
  INDEX.md              ← queue table + phase summaries (source of truth, Claude Desktop owns)
  QUEUE_RUNNER.md       ← project context injected into every CC run
  QUEUE_STATE.json      ← runner internal state (machine-readable)
  QUEUE_STATUS.md       ← runner live progress view (auto-generated)
  run_queue.py          ← canonical queue runner (Python, persistent watcher)
  run_queue.sh          ← legacy Git Bash runner (still works, prefer .py)
  run_queue.ps1         ← PowerShell variant
  logs/                 ← per-prompt run logs
  CC_PROMPT_vX.Y.Z.md   ← one file per version bump
```

### Prompt file format
```markdown
# CC PROMPT — vX.Y.Z — Title

## What this does
2-3 sentences. Version bump: X.Y.Z-1 → X.Y.Z

## Change 1 — path/to/file.py
[exact code with context]

## Version bump
Update VERSION: X.Y.Z-1 → X.Y.Z

## Commit
git add -A
git commit -m "type(scope): vX.Y.Z description"
git push origin main
```

### Adding to the queue
1. Write `cc_prompts/CC_PROMPT_vX.Y.Z.md`
2. Add row to `INDEX.md` Phase Queue table:
   `| CC_PROMPT_vX.Y.Z.md | vX.Y.Z | Short description | PENDING |`
3. Add summary paragraph under `## Phase summaries`

### Running the queue
```bash
python cc_prompts/run_queue.py            # persistent watcher, 3 min poll
python cc_prompts/run_queue.py --poll 60  # poll every 60s
python cc_prompts/run_queue.py --one      # run next pending, then exit
python cc_prompts/run_queue.py --dry-run  # show current status
```
CC implements the prompt, commits, pushes, then updates `INDEX.md`
changing `PENDING` → `DONE (SHA)` and commits that too.
Runner verifies git hash changed before moving to next prompt.
`QUEUE_STATE.json` / `QUEUE_STATUS.md` track live runner state across restarts.

### Version bump convention
| Bump | When |
|---|---|
| `x.x.1` | Fix, tuning, small addition |
| `x.1.x` | New subsystem, multi-file architectural change |

### After CC pushes a commit
```bash
# Pull and restart on agent-01
#docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
#  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent

# Verify
#curl -s http://192.168.199.10:8000/api/health
#docker logs hp1_agent --tail 50
```

---

## Architecture

High-level layout. Use `ls` / `Glob` for an authoritative file list — the tree
is illustrative, not exhaustive.

```
ai-local-agent-tools/
├── api/
│   ├── main.py                       ← App entry, startup, router mounts
│   ├── auth.py                       ← JWT + API token fallback
│   ├── users.py                      ← User CRUD, bcrypt password hashing
│   ├── connections.py                ← Connections DB, Fernet encryption
│   ├── crypto.py / settings_manager.py
│   ├── session_store.py / lock.py / logger.py / metrics.py
│   ├── scheduler.py                  ← APScheduler-driven jobs (collectors, tests, retention)
│   ├── correlator.py / clarification.py / confirmation.py
│   ├── elastic_alerter.py / notifications.py / alerts.py
│   ├── analysis_templates.py / constants.py
│   ├── plugin_loader.py / tool_registry.py / websocket.py
│   ├── facts/                        ← known_facts pipeline (current+history+rejection)
│   ├── memory/                       ← MuninnDB integration
│   ├── rag/                          ← Document ingest + retrieval
│   ├── security/                     ← Secure cookie / TLS / CORS guardrails
│   ├── skills/                       ← Self-improving skill runtime (server side)
│   ├── agents/
│   │   ├── router.py                 ← Task classifier, tool allowlists, prompts
│   │   ├── orchestrator.py           ← Multi-step agent orchestration
│   │   ├── pipeline.py               ← _stream_agent setup (extracted v2.45.17)
│   │   ├── preflight.py              ← Pre-action validation (e.g. pre_kafka_check)
│   │   ├── gates.py / gate_rules.py / gate_detection.py
│   │   ├── context.py                ← Per-task context assembly
│   │   ├── step_state.py / step_facts.py / step_llm.py
│   │   │     step_tools.py / step_synth.py / step_guard.py / step_persist.py
│   │   ├── propose_dedup.py          ← Subtask proposal de-dup
│   │   ├── runbook_classifier.py
│   │   ├── fabrication_detector.py   ← Detects hallucinated facts
│   │   ├── fact_age_rejection.py     ← Rejects stale facts
│   │   ├── forced_synthesis.py
│   │   ├── external_ai_client.py / external_ai_confirmation.py / external_router.py
│   │   ├── tool_metadata.py
│   │   └── task_templates/           ← Task template definitions
│   ├── collectors/
│   │   ├── manager.py                ← CollectorManager, trigger_poll()
│   │   ├── base.py
│   │   ├── external_services.py / proxmox_vms.py / swarm.py / kafka.py
│   │   ├── vm_hosts.py / unifi.py / pbs.py / truenas.py / fortigate.py
│   │   ├── docker_agent01.py / docker_hosts.py
│   │   ├── elastic.py / network_ssh.py / windows.py
│   ├── db/
│   │   ├── base.py / models.py / migrations.py / migrate_sqlite.py / queries.py
│   │   ├── result_store.py           ← Large tool result storage (2h TTL)
│   │   ├── entity_history.py / entity_maintenance.py / drift_events.py
│   │   ├── infra_inventory.py        ← Host discovery registry
│   │   ├── credential_profiles.py    ← Named shared auth sets
│   │   ├── ssh_capabilities.py / ssh_log.py
│   │   ├── audit_log.py / vm_action_log.py
│   │   ├── agent_actions.py / agent_attempts.py / agent_blackouts.py
│   │   ├── subagent_runs.py / subtask_proposals.py
│   │   ├── known_facts.py / metric_samples.py / notifications.py
│   │   ├── llm_traces.py / llm_trace_retention.py / external_ai_calls.py
│   │   ├── runbooks.py / card_templates.py / display_aliases.py
│   │   ├── skill_candidates.py / skill_executions.py
│   │   ├── test_definitions.py / test_runs.py / vm_exec_allowlist.py
│   └── routers/                      ← FastAPI routers (one per concern)
│       agent.py, agent_actions_api.py, agent_blackouts_api.py, alerts.py,
│       analysis.py, ansible.py, auth.py, card_templates.py, connections.py,
│       credential_profiles.py, dashboard.py, discovery.py, display_aliases.py,
│       docs.py, elastic.py, entities.py, errors.py, escalations.py,
│       external_ai.py, facts.py, feedback.py, gates.py, ingest.py,
│       kafka_overview.py, layout.py, lock.py, logs.py, maintenance.py,
│       memory.py, notifications.py, runbooks.py, settings.py, skills.py,
│       status.py, tests_api.py, tools.py, users.py, vm_exec_allowlist.py
├── mcp_server/
│   ├── server.py                     ← ALL MCP tool registrations here
│   └── tools/
│       ├── vm.py                     ← vm_exec, kafka_exec, swarm_node_status,
│       │                               swarm_service_force_update, proxmox_vm_power
│       ├── swarm.py / docker_api.py / docker_engine.py
│       ├── kafka.py / kafka_inspect.py
│       ├── elastic.py / log_timeline.py / network.py
│       ├── pbs.py / pbs_health.py
│       ├── container_introspect.py / metric_tools.py / agent_perf.py
│       ├── entity_history_tools.py / result_tools.py / render_tools.py
│       ├── orchestration.py / ingest.py / skill_meta_tools.py
│       └── skills/                   ← Self-improving skill system
├── gui/src/
│   ├── App.jsx                       ← Top-level routing, providers, dashboard host
│   ├── api.js                        ← API client
│   ├── context/                      ← Auth, Options, Agent, Task, Dashboard providers
│   ├── components/                   ← ~60 components — see Glob for full list
│   │   │  Key ones:
│   │   ├── ServiceCards.jsx          ← All infra cards
│   │   ├── DashboardCards.jsx / DashboardLayout.jsx
│   │   ├── Sidebar.jsx / SettingsPage.jsx / OptionsModal.jsx
│   │   ├── ComparePanel.jsx          ← exports SLOT_COLORS
│   │   ├── CardFilterBar.jsx         ← INFRA_SECTION_KEYS filter bar
│   │   ├── VMHostsSection.jsx / WindowsSection.jsx
│   │   ├── EscalationBanner.jsx / LayoutsTab.jsx
│   │   ├── KafkaTab.jsx / LogsPanel.jsx / FactsView.jsx / GatesView.jsx
│   │   ├── PlanConfirmModal.jsx / ExternalAIConfirmModal.jsx
│   │   ├── ClarificationWidget.jsx / SubtaskOfferBanner.jsx / RunbookPopup.jsx
│   │   ├── AgentFeed.jsx / AgentDiagnostics.jsx / TraceView.jsx
│   │   └── SkillsPanel.jsx / SkillsTab.jsx / TestsPanel.jsx
│   ├── hooks/                        ← useLayout.js, useCardTemplate.js
│   ├── schemas/ / styles/ / utils/ / dev/
│   └── index.css                     ← V3a Imperial theme (CSS vars)
├── cc_prompts/                       ← CC prompt queue (see above)
├── scripts/
│   ├── check_sensors.py              ← Sensor stack runner (see Sensor Protocol)
│   ├── gen_build_info.py / rotate_encryption_key.py
│   ├── deathstar-backup.sh / deathstar-verify-bundle.sh
│   └── deploy/                       ← One-shot bootstrap scripts
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── .ruff.toml / .eslintrc.sensors.json / .gitleaks.toml
├── Makefile                          ← `make check` / `make check-agent`
├── .github/workflows/                ← build.yml + sensors.yml
└── VERSION                           ← Single source of version truth
```

---

## Key Environment Variables

Location: `/opt/hp1-agent/docker/.env` (chmod 600, Ansible-managed — never edit manually)

```
SETTINGS_ENCRYPTION_KEY=<fernet-key>   # Encrypts connection credentials in DB
ADMIN_USER=admin
ADMIN_PASSWORD=<password>
KAFKA_UNDER_REPLICATED_THRESHOLD=1     # Tolerate 1 under-rep partition before DEGRADED
DATABASE_URL=postgresql+asyncpg://...
```

**Never print `SETTINGS_ENCRYPTION_KEY` to terminal.** Write directly:
```bash
python3 -c "
from cryptography.fernet import Fernet
key = Fernet.generate_key().decode()
with open('/opt/hp1-agent/docker/.env', 'r') as f: content = f.read()
import re; content = re.sub(r'SETTINGS_ENCRYPTION_KEY=.*', f'SETTINGS_ENCRYPTION_KEY={key}', content)
with open('/opt/hp1-agent/docker/.env', 'w') as f: f.write(content)
print('Done')
"
```

---

## Platform → Dashboard Section Mapping

| Section | Platforms |
|---|---|
| COMPUTE | proxmox, pbs |
| NETWORK | fortigate, fortiswitch, opnsense, cisco, juniper, aruba, unifi, pihole, technitium, nginx, caddy, traefik |
| STORAGE | truenas, pbs, synology, syncthing |
| SECURITY | security_onion, wazuh, grafana, kibana |

---

## Infrastructure (Current State)

### Swarm cluster — SERVICE TEST cluster
```
3 managers: manager-01 (199.21), manager-02 (199.22), manager-03 (199.23)
3 workers:  worker-01 (199.31), worker-02 (199.32), worker-03 (199.33) ← worker-03 currently Down
```
- Agent runs on agent-01 (199.10) — NOT in the swarm
- All 6 + agent-01 registered as vm_host connections

### Kafka
- 3-broker KRaft cluster on workers (kafka_broker-1/2/3 Swarm services)
- `hp1-logs` topic: 3 partitions, RF=3, min.insync.replicas=2
- Current: 2/3 brokers (broker-3 not scheduled — worker-03 Down)

### Connections as universal registry
The connections DB is the single source of truth. Adding a connection:
- Creates a card in the correct dashboard section
- Starts appearing in collector results
- Shows as a source filter in Logs tab

### Proxmox token fields — split at `!`
`terraform@pve!terraform-token` → `user=terraform@pve`, `token_name=terraform-token`

---

## Absolute Rules (Claude Code must follow)

- **All tool functions sync** — no async/await in mcp_server/tools/
- **Return format**: `{"status": "ok"|"error"|"degraded", "data": ..., "timestamp": ..., "message": ...}`
- **Always** run `git push` after every commit
- **Never** hardcode IPs, passwords, or API keys in Python files
- **Never** add `async` to tool functions or skill execute()
- **Never** import dangerous modules in skills (os.system, eval, exec)
- **Never** edit docker/.env — Ansible-managed
- `CardFilterBar.jsx` and `ServiceCards.jsx` must stay in sync — new platform types need explicit addition to `INFRA_SECTION_KEYS`
- `get_connection_for_platform()` uses `LIMIT 1` — known limitation for multi-connection scenarios
- Always use CSS vars (`var(--accent)`) — never hardcode colours

### Subprocess policy
- **NEVER** use subprocess where LLM output or user input reaches the command
- subprocess IS allowed for fully hardcoded internal plumbing
- Always `subprocess.run()` with `shell=False`, explicit arg lists

### MCP tool registration pattern (server.py only)
```python
@mcp.tool()
def tool_name(param: str) -> dict:
    """Description shown to the LLM."""
    from mcp_server.tools.module import function
    return function(param)
```

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

---

## Auth System

Roles: `sith_lord` (full admin) | `imperial_officer` (ops) | `stormtrooper` (monitoring) | `droid` (read-only API)

Auth flow:
1. Login → JWT from users table (bcrypt) → falls back to env var
2. API calls → JWT decode → SHA256 hash lookup in api_tokens → 401

`/metrics` is auth-protected (v2.45.21+). `CORS_ALLOW_ALL=1` is logged as a
security warning on startup.

### Optional TLS reverse proxy (v2.45.29+)

nginx-fronted HTTPS with secure cookies — opt-in, off by default. See
`docker/docker-compose.yml` for the `nginx` profile and `api/security/` for
secure-cookie behaviour. When enabled, the agent listens behind nginx and
issues `Secure; HttpOnly; SameSite=Strict` cookies.

---

## Agent Architecture

4 agent types routed by task classifier in `api/agents/router.py`:

| Type | When | Key tools |
|---|---|---|
| observe/status | status checks, read-only | swarm_status, kafka_broker_status, vm_exec |
| investigate/research | why/diagnose/logs | elastic_search_logs, kafka_exec, entity_history |
| execute/action | fix/restart/deploy | plan_action required for destructive ops |
| build | skill management | skill_create, skill_regenerate |

Each turn flows through a step pipeline (`api/agents/step_*.py`) wrapped by
`orchestrator.py` and set up by `pipeline.py`:
`step_state → step_facts → step_llm → step_tools → step_synth → step_guard → step_persist`.
Gates (`gates.py`, `gate_rules.py`, `gate_detection.py`) and the fabrication
detector (`fabrication_detector.py` + `fact_age_rejection.py`) reject
hallucinated or stale facts before they reach the user.

### Facts pipeline (v2.45.23+)

Collectors (`elastic`, `network_ssh`, `vm_hosts`) and the agent observation path
(`step_persist`, `step_facts.drain_run_facts`) write into
`api/db/known_facts_current` (with rolling history in `known_facts_history`).
The agent reads these as authoritative facts for the current turn — the
fabrication detector cross-checks LLM claims against this store and rejects
unsupported or stale assertions.

Key agent tools:
- `vm_exec(host, command)` — SSH to vm_host connection, allowlisted commands
- `kafka_exec(broker_label, command)` — SSH to worker, exec in kafka container
- `swarm_node_status()` — docker node ls from a manager (read-only)
- `swarm_service_force_update(service_name)` — docker service update --force (needs plan_action)
- `proxmox_vm_power(vm_label, action)` — start/stop/reboot via Proxmox API (needs plan_action)

**Pre-flight bypass:** Remediation tasks (fix/restart/recover) skip `pre_kafka_check` —
that check is for precautionary ops, not for fixing known-degraded components.

**Blocked tool rule:** When a tool is unavailable, agent outputs exact manual SSH
command instead of escalating.

**External AI escalation:** When the local agent can't make progress, it can
escalate to an external model via `external_ai_client.py` — gated by user
confirmation (`ExternalAIConfirmModal.jsx`).

---

## Naming Convention

| Pattern | Resolves to |
|---|---|
| Agent Pattern `{short}-agent-{n:02d}` | DS-agent-01 |
| Database `{short}-postgres` | DS-postgres |
| Memory Store `{short}-muninndb` | DS-muninndb |

---

## Validation Commands

```bash
python -m py_compile api/main.py
python -m py_compile mcp_server/server.py
make check-agent                                  # sensor stack — failures only with HINTs
curl -s http://192.168.199.10:8000/api/health
docker logs hp1_agent --tail 50
```

---

## Sensor Protocol

Three-layer linting stack for CI + local + agent workflows. Source files:
`scripts/check_sensors.py`, `Makefile`, `.ruff.toml`, `.eslintrc.sensors.json`,
`.gitleaks.toml`, `.github/workflows/sensors.yml`.

### Tools

| Sensor | What it catches | Config |
|---|---|---|
| ruff | Python complexity (C901), too-many-args (PLR0913), long lines (E501), pyflakes errors (F) | `.ruff.toml` |
| bandit | Hardcoded secrets, unsafe subprocess, SQL injection, weak crypto | inline (`-r api mcp_server scripts`) |
| gitleaks | JWT tokens, Fernet keys, API tokens — repo-wide scan | `.gitleaks.toml` |
| eslint | JS/JSX complexity, max-lines, max-params, no-unused-vars | `.eslintrc.sensors.json` (loaded via generated flat-config wrapper) |
| mypy | Static type errors in `api/`, `mcp_server/`, `scripts/` | inline (`--ignore-missing-imports`) |

### Calibrated thresholds (v2.46.0)

| Threshold | Setting | Codebase peak | Note |
|---|---|---|---|
| ruff `max-complexity` | 80 | 95 (`api/main.py:lifespan`) | catches outliers; tighten as refactors land |
| ruff `max-args` | 20 | ~17 | headroom; consolidate via dataclass |
| ruff `line-length` | 250 | — | soft style threshold; CI blocker only above 250 |
| eslint `complexity` | 100 | 97 (`VMHostsSection:VMCard`) | "sleeping" sensor — set just above peak |
| eslint `max-lines` | 4000 | 3553 (`OptionsModal.jsx`) | tighten as files are split |
| eslint `max-params` | 15 | ~10 | headroom |
| eslint `no-unused-vars` | warn | 17 hits | warn-only until cleanup; tighten to error |

Initial run with this config produces 5 violations across the existing codebase.
The intent: **catch new outliers**, then progressively tighten as code improves.

### Targets

| Command | Purpose |
|---|---|
| `make check` | Full human-readable run, every tool's native output. |
| `make check-agent` | Agent-optimized: failures only, one per line, with HINTs. Delegates to `scripts/check_sensors.py`. |
| `python scripts/check_sensors.py --only ruff` | Run a single sensor (`--list` to see options). |
| `make sensors-install` | Install Python sensors (ruff, bandit, mypy) via pip. gitleaks/eslint installed separately. |

### Output format (agent mode)

```
[TOOL] file:line - rule message
  HINT: ...
```

`HINT` is calibrated per-rule and points to existing code patterns:
- C901 → `api/agents/step_*.py` pipeline split pattern
- PLR0913 → dataclass consolidation (e.g. `StepState`)
- bandit B105/B106 → `api/connections.py` Fernet-encrypted credentials
- gitleaks fernet/jwt → `/opt/hp1-agent/docker/.env` (Ansible-managed)
- eslint complexity → component/hook extraction (see `DashboardLayout.jsx`)

Exit codes: `0` clean, `1` failures present (or runtime tool error), `2` bad CLI args.

### CI

`.github/workflows/sensors.yml` triggers on PR + push to `main`. Runs `make check`,
posts a failure summary as a PR comment (updates the previous comment instead of
spamming), and fails the workflow on any sensor error. The full report is also
uploaded as the `sensor-report` workflow artifact.

### Adding a new HINT

Edit the per-tool dict at the top of `scripts/check_sensors.py`
(`RUFF_HINTS`, `BANDIT_HINTS`, `GITLEAKS_HINTS`, `ESLINT_HINTS`, `MYPY_HINTS`).
Keep hints short, point to a file, and reference an existing pattern.

---

## Pre-Commit Checklist
1. No hardcoded IPs/passwords/secrets in Python?
2. `python -m py_compile <changed files>` — valid syntax?
3. `make check-agent` clean? (or no new failures vs. baseline)
4. New platform types added to `INFRA_SECTION_KEYS` in CardFilterBar.jsx?
5. No hardcoded `localhost` URLs in GUI?
6. Conventional commit message (`feat|fix|refactor|docs(scope): message`)?
7. VERSION file bumped?
