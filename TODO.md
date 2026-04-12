# DEATHSTAR — TODO
*State at end of session — v2.14.0 live*

---

## 🔴 Immediate

Nothing pending.

---

## 🟡 Known issues

### Kafka degraded
`kafka_cluster` shows DEGRADED. Likely a broker connectivity issue —
not a code bug. Check Kafka bootstrap servers and broker health directly.

### Swarm CRITICAL
`swarm` shows CRITICAL. Logstash service still running 0/1 replicas.
Resource/config issue on swarm workers — not a code bug.

### Prox Cluster FIN — VPN dependency
Connection routed via `netsh portproxy` on Windows dev PC
(192.168.199.51:18006 → 10.10.11.11:8006).
Unavailable when OpenVPN is disconnected.
Permanent fix: run WireGuard/OpenVPN directly on agent-01.

---

## 🟢 Implemented — live as of v2.14.0

### Queue v2.8.0 – v2.14.0 (automated via cc_prompts queue runner)

| Version | Feature | Commit |
|---|---|---|
| v2.8.0 | Semantic tool routing + thinking memory + feedback pre-ranking | 69b4e7d |
| v2.8.1 | LLM temperature profiles + /no_think for cheap steps | 6bd67ea |
| v2.9.0 | entity_changes + entity_events DB tables + image digest tracking | 8b08f17 |
| v2.9.1 | entity_history() + entity_events() agent tools + GUI badge | 467f949 |
| v2.10.0 | Lightweight coordinator pattern between agent steps | e7791ff |
| v2.10.1 | Alert health-transition badge + FortiGate filter bar + snapshot TTL | 47d0dc5 |
| v2.11.0 | Multi-connection collectors (get_all_connections_for_platform) | 2aeba18 |
| v2.11.1 | PBS collector — real implementation with PBSAPIToken auth | e5292dc |
| v2.12.0 | httpOnly cookie auth + slowapi login rate limiting | 7c84014 |
| v2.12.1 | SSH capability map security dashboard | 5a503e6 |
| v2.13.0 | Spec-first skill generation + environment discovery + fingerprints | c558eb6 |
| v2.13.1 | skill_execute dispatcher + 3-layer validation | 81e86f2 |
| v2.14.0 | Email + webhook notification system | ca4273e |

### Pre-queue (v2.6.x – v2.7.x)

| Version | Feature |
|---|---|
| v2.6.2 | test_connection() delegates to _probe_connection() |
| v2.6.3 | TrueNAS rich card + CardFilterBar fix |
| v2.6.4 | FortiGate rich card |
| v2.6.5 | Dynamic postgres row + section wiring |
| v2.6.6 | PBS snapshot count + debug endpoint fix |
| v2.7.0 | Multiple Proxmox connections → multiple COMPUTE cards |
| v2.7.1 | Per-cluster Proxmox filter bars |
| v2.7.2 | Generic ConnectionFilterBar + UniFi filtering |
| v2.7.3 | Compare per-entity chat suggestions |

---

## 🔵 Deferred / next ideas

### Test v2.12.0 auth fully
- Verify httpOnly cookie present in DevTools (Application → Cookies → hp1_auth → HttpOnly flag)
- Verify localStorage no longer has hp1_auth_token
- Test logout clears cookie
- Test rate limiting (6 bad logins → 429)
- Test API scripts still work with Authorization: Bearer header

### Test v2.14.0 notifications
- Add an email or webhook channel in Settings → Notifications
- Trigger a critical alert and verify delivery
- Check notification_log for sent/failed records

### v2.15.x ideas (discuss before writing prompts)
- Dashboard entity timeline view — click entity → see change/event history inline
- Agent task templates — pre-built tasks for common ops (disk cleanup, prune images, etc.)
- Proxmox VM console link — open noVNC directly from the VM card
- Multi-agent parallel execution — two sub-agents running simultaneously on different hosts
- Result store viewer — browse stored result refs in the Logs tab

---

## 🏗 Architecture reference

### CC prompt queue system
All future changes go through cc_prompts/ queue:
```bash
# Write new prompts in cc_prompts/CC_PROMPT_vX.Y.Z.md
# Update INDEX.md with PENDING status
# Run from Git Bash:
bash cc_prompts/run_queue.sh --dry-run   # preview
bash cc_prompts/run_queue.sh --one       # supervised
bash cc_prompts/run_queue.sh             # full auto
```

### Deploy after CC push
```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env \
  up -d hp1_agent
docker logs hp1_agent --tail 30
```

### Entity ID format
- `proxmox:{name}:{vmid}` — e.g. `proxmox:graylog:119`
- `cluster:proxmox:Pmox Cluster KB`
- `unifi:device:{mac}`
- `pbs:{label}:{datastore}`
- `truenas:pool:{name}`
- `fortigate:iface:{name}`
- `swarm:service:{name}`
- `external_services:{slug}`

### Key paths
```
api/routers/agent.py         — agent loop, safety gates
api/agents/router.py         — classifier, allowlists, prompts
api/agents/orchestrator.py   — coordinator, step planner
api/db/entity_history.py     — change + event tables
api/db/result_store.py       — large result refs
api/db/ssh_log.py            — SSH audit log
api/db/ssh_capabilities.py   — credential→host map
api/db/notifications.py      — notification channels/rules
api/notifications.py         — SMTP + webhook delivery
api/collectors/              — all platform collectors
mcp_server/tools/            — built-in tools
plugins/                     — per-platform plugins
cc_prompts/                  — improvement queue
```
