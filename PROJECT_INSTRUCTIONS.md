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

### Database access pattern — CRITICAL

**The codebase uses sync psycopg2 for DB access, NOT async SQLAlchemy.**
Every existing DB module follows this pattern. Match it exactly when adding a new table.

Reference modules: `api/db/known_facts.py`, `api/db/test_runs.py`, `api/db/agent_actions.py`, `api/db/agent_attempts.py`, `api/db/gate_macros.py`. ~15 modules follow this convention.

Canonical shape:

```python
from api.connections import _get_conn

def _conn():
    return _get_conn()

def _is_pg() -> bool:
    return "postgres" in os.environ.get("DATABASE_URL", "")

def init_my_table() -> bool:
    """Create table + indexes. Idempotent. Sync. Best-effort."""
    if not _is_pg():
        return True
    try:
        conn = _conn()
        if conn is None:
            return False
        conn.autocommit = True
        cur = conn.cursor()
        # CRITICAL: split DDL on ';' and execute each statement individually.
        # asyncpg/psycopg2 do NOT run multi-statement strings cleanly.
        for stmt in _DDL_PG.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                cur.execute(stmt)
        cur.close()
        conn.close()
        return True
    except Exception as e:
        log.warning("my_table init failed: %s", e)
        return False
```

**Schema init wiring**: `init_*` is called sync (no `await`) from `_init_db_tables()` in `api/main.py`:

```python
try:
    from api.db.my_table import init_my_table
    init_my_table()
except Exception as e:
    _log.debug("my_table init skipped: %s", e)
```

**Async SQLAlchemy is the wrong pattern here.** asyncpg rejects multi-statement queries by default — DDL with multiple `CREATE TABLE` / `CREATE INDEX` wrapped in a single `text(_DDL)` will fail silently. Table never gets created, read endpoints 500 when they query the missing table. Lesson learned in v2.47.18 → v2.47.19.

**Endpoints stay async**: FastAPI route handlers in `api/routers/*.py` are typically `async def`. Inside them, sync DB helper calls go WITHOUT `await`:

```python
@router.get("/things")
async def list_things(_: str = Depends(get_current_user)):
    from api.db.things import list_things
    return {"things": list_things()}   # sync call, no await
```

**Sentinel return values, not raises**: every DB helper returns `[]`, `{}`, `None`, or a sentinel dict on failure — never raises into the caller. The endpoint stays simple, no try/except needed. See `api/db/test_runs.py:get_run` for a representative example.

**SQLAlchemy async (`from api.db.base import get_engine`) DOES exist** and is used in some legacy places (e.g. one-off migrations in `api/main.py` lifespan), but it is NOT the pattern for new tables. New DB modules use psycopg2 sync.

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

### CI build failure — broken `:latest` image recovery
**Symptom**: Container restart-loops with exit code 127 (command not found).
GUI unreachable. `docker logs hp1_agent` shows entrypoint binary missing.

**Diagnosis** (single command):
```bash
sudo docker images | grep hp1-ai-agent
```

If `:latest` image size is significantly smaller than tagged versions
(e.g. 279MB vs 783MB), the CI build pushed a partial/broken artifact
even though the Actions run reported "Success". GHCR may have the same
broken image; pulling fresh won't help.

**Recovery** (60 seconds):
```bash
cd /opt/hp1-agent/docker
sudo cp docker-compose.yml docker-compose.yml.bak
# Pin to last-known-good tagged version (check sizes via docker images)
sudo sed -i 's|hp1-ai-agent:latest|hp1-ai-agent:<good-version>|' docker-compose.yml
sudo docker compose --env-file .env up -d hp1_agent
sleep 10
curl -s http://localhost:8000/api/health | jq .version
```

**Permanent fix**: bump VERSION (no code changes needed) and push to
trigger a fresh CI build. The new build typically succeeds. Once it
completes and GHCR shows the expected size, pin compose to the new
explicit version.

**Going forward**: prefer pinning compose to explicit `:X.Y.Z` over
`:latest`. The `:latest` tag offers no protection against this class of
failure. Each successful CC deploy can update the pin as part of its
verification step.

**Lesson learned**: Don't trust `:latest` blindly. Image listing on
agent-01 (`docker images`) is the source of truth for what versions
actually pulled cleanly. CI "Success" means the steps ran without
error — it does not guarantee a complete artifact was published.

### Transient PyPI dependency conflicts in Docker builds
**Symptom**: A previously-working Docker build suddenly fails (or in
older Dockerfiles, silently produces a tiny image) with pip resolution
errors. Often happens when a major dependency (transformers, pydantic,
sqlalchemy) ships a new version with tighter pins.

**Root cause**: requirements.txt without upper-bound pins allows pip
to pick the latest version of every dep. When an upstream package
ships a new release with stricter constraints (e.g. transformers 5.6.2
adding `tokenizers<=0.23.0`), the resolver fails because we already
have a newer version (e.g. 0.23.1) selected from requirements.txt's
floor-only pin.

**Diagnosis**: search the failed pip install log for `looking at
multiple versions` or `depends on X<=Y`. The package right before that
line is the conflicting dep.

**Fix patterns** (in order of preference):
1. **Add `--no-deps` to the runtime `pip install`** — the builder
   stage already resolved deps via `pip wheel -r requirements.txt`.
   Re-running the resolver at runtime install adds no value, only
   conflict surface. This is the standard pattern in the repo since
   v2.47.22.
2. **Pin the offending package to a major version** in the Dockerfile
   (e.g. `transformers<5.0`) — surgical and explicit.
3. **Pin in requirements.txt** with both lower and upper bounds — only
   if multiple Dockerfile-side pins would compound.

**Why this is sneaky in CI**: PyPI is mutable. The same source code +
same Dockerfile can produce different builds on different days because
upstream packages publish new versions between runs. Without `--no-deps`
in the runtime install, this class of failure can recur any time a
deeply-pinned dependency releases a tighter version.

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
- **Safe-deploy / fail-safe Docker update** (designed in chat 2026-04-27, not yet implemented). Two parts:
  1. CI smoke test before `:latest` tag: image-size check (reject if <600MB), Python import sanity, 20s container spin-up + healthcheck. Broken artifacts never get the `:latest` tag. Caught by v2.47.19's 279MB image incident.
  2. `scripts/safe-deploy.sh` on agent-01: capture current image hash, pull new + start, poll `/api/health` for 120s, retag old + restart on timeout. Catches runtime failures CI can't see (DB schema mismatches, env var changes).
  - Skipped for now: `:edge` vs `:stable` tag separation (hygiene only); manual approval gate (negative ROI for homelab cadence); Swarm conversion (over-engineering for single-node hp1_agent)

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
4. **If introducing a new DB table or function: read an existing similar module (`known_facts.py`, `test_runs.py`, `agent_actions.py`) FIRST and match its conventions verbatim. Sync psycopg2, not async SQLAlchemy. Split DDL on `;`. Sentinel return values on failure.**
5. **If introducing a new settings-driven variable: confirm all 4 layers are in the prompt (backend `SETTINGS_KEYS`, frontend `DEFAULTS`, frontend `SERVER_KEYS`, frontend render in `OptionsModal.jsx`). Backend-only is invisible to the operator.**
6. Write prompt as `CC_PROMPT_v{next}.md`
7. Append PENDING row to INDEX.md
8. Stop. Do NOT execute. CC owns execution.
