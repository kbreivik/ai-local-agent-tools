# DEATHSTAR — Claude Code Guide
## Version: 2.15.10

Self-hosted infrastructure monitoring and AI agent orchestration platform.
FastMCP + FastAPI backend, React (Vite) frontend, Docker Swarm deployment.

---

## Core Facts

| Item | Value |
|---|---|
| Repo | github.com/kbreivik/ai-local-agent-tools (public, MIT) |
| Current version | v2.15.10 |
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
  INDEX.md              ← queue table + phase summaries (source of truth)
  QUEUE_RUNNER.md       ← project context injected into every CC run
  run_queue.sh          ← queue runner (Git Bash)
  CC_PROMPT_vX.Y.Z.md  ← one file per version bump
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
bash cc_prompts/run_queue.sh          # all pending, streams output live
bash cc_prompts/run_queue.sh --one    # one at a time
bash cc_prompts/run_queue.sh --dry-run
```
CC implements the prompt, commits, pushes, then updates `INDEX.md`
changing `PENDING` → `DONE (SHA)` and commits that too.
Runner verifies git hash changed before moving to next prompt.

### Version bump convention
| Bump | When |
|---|---|
| `x.x.1` | Fix, tuning, small addition |
| `x.1.x` | New subsystem, multi-file architectural change |

### After CC pushes a commit
```bash
# Pull and restart on agent-01
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent

# Verify
curl -s http://192.168.199.10:8000/api/health
docker logs hp1_agent --tail 50
```

---

## Architecture

```
ai-local-agent-tools/
├── api/
│   ├── main.py                 ← App entry, startup, router mounts
│   ├── auth.py                 ← JWT + API token fallback
│   ├── connections.py          ← Connections DB, Fernet encryption
│   ├── agents/
│   │   └── router.py           ← Task classifier, tool allowlists, system prompts
│   ├── collectors/
│   │   ├── manager.py          ← CollectorManager, trigger_poll()
│   │   ├── external_services.py
│   │   ├── proxmox_vms.py
│   │   ├── swarm.py
│   │   ├── kafka.py
│   │   ├── vm_hosts.py
│   │   ├── unifi.py
│   │   ├── pbs.py
│   │   └── truenas.py
│   ├── db/
│   │   ├── result_store.py     ← Large tool result storage (2h TTL)
│   │   ├── entity_history.py   ← Change tracking + event log
│   │   ├── infra_inventory.py  ← Host discovery registry
│   │   ├── credential_profiles.py ← Named shared auth sets
│   │   └── ssh_capabilities.py
│   └── routers/
│       ├── agent.py            ← POST /api/agent/run, WebSocket agent loop
│       ├── connections.py      ← CRUD + auto-trigger collector poll
│       ├── users.py            ← User + API token CRUD
│       ├── layout.py           ← Layout templates endpoint
│       ├── escalations.py      ← Agent escalation table + endpoints
│       └── credential_profiles.py
├── mcp_server/
│   ├── server.py               ← ALL MCP tool registrations here
│   └── tools/
│       ├── vm.py               ← vm_exec, kafka_exec, swarm_node_status,
│       │                           swarm_service_force_update, proxmox_vm_power
│       └── skills/             ← Self-improving skill system
├── gui/src/
│   ├── App.jsx                 ← Sidebar nav, routing, DashboardView, DrillDownBar
│   ├── components/
│   │   ├── ServiceCards.jsx    ← All infra cards (VM, container, external, UniFi, etc.)
│   │   ├── Sidebar.jsx         ← Navigation + user menu + footer
│   │   ├── SettingsPage.jsx    ← All settings tabs
│   │   ├── OptionsModal.jsx    ← Connections form, ProfileForm, BulkForm
│   │   ├── ComparePanel.jsx    ← Right-side compare panel, exports SLOT_COLORS
│   │   ├── VMHostsSection.jsx  ← VM_HOSTS dashboard section
│   │   ├── EscalationBanner.jsx ← Persistent amber banner for agent escalations
│   │   ├── LayoutsTab.jsx      ← Layout templates + current layout management
│   │   └── CardFilterBar.jsx   ← INFRA_SECTION_KEYS filter bar
│   ├── hooks/useLayout.js      ← Layout state management
│   └── index.css               ← V3a Imperial theme (CSS vars)
├── cc_prompts/                 ← CC prompt queue (see above)
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
└── VERSION                     ← Single source of version truth
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

---

## Agent Architecture

4 agent types routed by task classifier in `api/agents/router.py`:

| Type | When | Key tools |
|---|---|---|
| observe/status | status checks, read-only | swarm_status, kafka_broker_status, vm_exec |
| investigate/research | why/diagnose/logs | elastic_search_logs, kafka_exec, entity_history |
| execute/action | fix/restart/deploy | plan_action required for destructive ops |
| build | skill management | skill_create, skill_regenerate |

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
curl -s http://192.168.199.10:8000/api/health
docker logs hp1_agent --tail 50
```

## Pre-Commit Checklist
1. No hardcoded IPs/passwords/secrets in Python?
2. `python -m py_compile <changed files>` — valid syntax?
3. New platform types added to `INFRA_SECTION_KEYS` in CardFilterBar.jsx?
4. No hardcoded `localhost` URLs in GUI?
5. Conventional commit message (`feat|fix|refactor|docs(scope): message`)?
6. VERSION file bumped?
