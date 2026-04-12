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
| CC_PROMPT_v2.15.1.md | v2.15.1 | Copy connection + bulk create (IP range + name pattern) | PENDING |
| CC_PROMPT_v2.15.2.md | v2.15.2 | Kafka: KRaft controller fix + under-replicated threshold | PENDING |
| CC_PROMPT_v2.15.3.md | v2.15.3 | kafka_exec agent tool + vm_exec allowlist expansion | PENDING |

---

## Version bump rationale

| Bump | Meaning |
|---|---|
| x.x.1 | Fix, tuning, small addition |
| x.1.x | New subsystem, architectural change, multi-file feature |

---

## Phase summaries

**v2.15.0** — `credential_profiles` table (id, name, auth_type, encrypted credentials).
Connections reference a profile by ID. One "ubuntu-ssh-key" profile serves all 6 workers.
Profile picker dropdown in the vm_host connection form. `resolve_credentials_for_connection()`
priority: own creds → linked profile → shared_credentials fallback.

**v2.15.1** — Copy button on each connection row (pre-fills form, excludes credentials).
Bulk add mode: name pattern with `%N%` counter (configurable start + zero-pad), IP range
expander (start → end, up to 256 IPs), credential profile picker, role selector, preview
table before save, sequential create with per-row success/failure report.

**v2.15.2** — `controller_id: None` instead of `-1` for KRaft clusters (kafka-python
can't detect KRaft controller — None signals "unknown" not "absent").
`KAFKA_UNDER_REPLICATED_THRESHOLD` env var (default 0 = current behaviour).
`KAFKA_UNDER_REPLICATED_GRACE` env var. Per-partition ISR detail in topic_data.

**v2.15.3** — `kafka_exec(broker_label, command)` MCP tool: SSH to a worker, find kafka
container, exec CLI command. Blocks destructive operations. Added to OBSERVE/INVESTIGATE/
EXECUTE_SWARM allowlists. STATUS_PROMPT examples for topic describe + leader election.

---

## Deployment order for v2.15.x

1. Run queue through v2.15.1 (credential profiles + bulk create)
2. Use bulk create to add all 6 worker nodes (managers too) as vm_host connections
   — assign the ubuntu-ssh-key credential profile created in v2.15.0
3. Run v2.15.2 (Kafka fix) — set KAFKA_UNDER_REPLICATED_THRESHOLD=1 in .env
4. Run v2.15.3 (kafka_exec) — agent can now investigate and fix Kafka directly
5. Have agent run: kafka_exec("ds-docker-worker-01", "kafka-leader-election.sh ...")

---

## Key file paths

```
api/db/credential_profiles.py      — profiles table + CRUD (v2.15.0)
api/routers/credential_profiles.py — REST API (v2.15.0)
api/collectors/vm_hosts.py          — _resolve_credentials (updated v2.15.0)
api/collectors/kafka.py             — KRaft fix + threshold (v2.15.2)
mcp_server/tools/vm.py              — vm_exec allowlist + kafka_exec (v2.15.3)
mcp_server/server.py                — tool registration
api/agents/router.py                — allowlists + STATUS_PROMPT
gui/src/components/OptionsModal.jsx — ConnectionsTab, ProfileForm, BulkForm
```
