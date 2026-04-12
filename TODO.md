# DEATHSTAR — TODO
*State at end of session — v2.7.3 live*

---

## 🔴 Immediate (send to CC before closing)

Nothing pending.

---

## 🟡 Known issues

### Logstash 0/1 replicas
Swarm service `logstash_logstash` consistently shows 1 issue (0/1 replicas).
Not a code bug — Logstash container resource/config issue on the swarm workers.

### Prox Cluster FIN — VPN dependency
Connection routed via `netsh portproxy` on the Windows dev PC (192.168.199.51:18006 → 10.10.11.11:8006).
Cluster is unavailable when OpenVPN is disconnected on that PC.
Permanent fix: run WireGuard/OpenVPN client directly on agent-01.

---

## 🟢 Implemented — live as of v2.7.3

| Feature | Build | Status |
|---|---|---|
| test_connection() delegates to _probe_connection() | v2.6.2 | Live |
| TrueNAS Section+InfraCard rich card | v2.6.3 | Live |
| CardFilterBar fix — unifi/pbs/truenas keys added | v2.6.3 | Live |
| FortiGate Section+InfraCard rich card | v2.6.4 | Live |
| hp1_postgres → hp1-postgres (dev compose) | v2.6.5 | Live |
| Postgres row in PLATFORM CORE dynamic (from container) | v2.6.5 | Live |
| NETWORK/STORAGE activeFilters wired for new sections | v2.6.5 | Live |
| PBS snapshot count per datastore | v2.6.6 | Live |
| PBS debug endpoint path fixed (/system/tasks) | v2.6.6 | Live |
| Multiple Proxmox connections → multiple COMPUTE cluster cards | v2.7.0 | Live |
| Per-cluster Proxmox filter bars with own node chips | v2.7.1 | Live |
| Generic ConnectionFilterBar component | v2.7.2 | Live |
| UniFi type/status/name filter bar | v2.7.2 | Live |
| Compare per-entity chat suggestions | v2.7.3 | Live |

---

## 🔵 Deferred / planned — no prompt written yet

### Logs tab: alert enrichment banner
Backend `alerts.py` ships `prev_health`, `health`, `severity`, `connection_label`
on every alert. Frontend `AlertsPanel` in `App.jsx` shows basic alert rows but
doesn't display the health transition (e.g. "healthy → degraded").
Small change: add `prev_health → health` transition badge to each alert row.

### Auth: JWT token → httpOnly cookie
Currently JWT stored in `localStorage` — XSS accessible.
Swap to `httpOnly` cookie with `SameSite=Strict`.
All `authHeaders()` calls in `api.js` would be removed (cookie sent automatically).
Also add rate limiting on `/api/auth/login` via `slowapi`.

### Multiple connections per platform — collector support
`get_connection_for_platform()` still uses `LIMIT 1` for all platforms
except Proxmox (which now uses `get_all_connections_for_platform()`).
PBS, UniFi, TrueNAS, FortiGate collectors all need the same treatment
if a second connection of that type is added.

### status_snapshots retention
No cleanup policy — table grows unbounded.
Add a scheduled task (or pg_cron job) to delete rows older than 30 days.

### FortiGate ConnectionFilterBar
Wire `ConnectionFilterBar` into the FortiGate InfraCard section using:
```js
const FG_FILTER_FIELDS = [{ key: 'type', label: 'type' }]
```
Small addition — same pattern as UniFi.

### EAP-TLS / 802.1X FortiSwitch config
Separate homelab work, not in codebase.
Skill: `/mnt/skills/user/fortiswitch/SKILL.md`

---

## 🏗 Architecture notes for next session

### Card design standard — Section+InfraCard is the reference
All rich connection cards use `Section` (cluster header) + `InfraCard` children
from `ServiceCards.jsx`. Never use custom inline layouts in `App.jsx`.

### Adding a new platform (6-step checklist)
1. `external_services.py` — add to `PLATFORM_HEALTH`
2. `base.py` — add to `PLATFORM_SECTION`
3. `api/collectors/{platform}.py` — subclass `BaseCollector`
4. `SettingsPage.jsx` — add to `PLATFORM_AUTH`
5. `CardFilterBar.jsx` — add to `INFRA_SECTION_KEYS`
6. `ServiceCards.jsx` — add state + effect + Section+InfraCard block

### Per-cluster filter pattern (v2.7.1)
Multiple connections of same platform → multiple Section cards, each with
independent filter state keyed by `connection_id`.
See Proxmox implementation in `ServiceCards.jsx` as reference.

### Generic filter bar (v2.7.2)
`ConnectionFilterBar` + `applyConnectionFilters()` in `ServiceCards.jsx`.
Pass a `fields` array of `{ key, label }` — chips derived from actual items.
Fields with only 1 distinct value are hidden automatically.

### Key API endpoints
- `GET /api/status/collectors/{component}/data` — last collected state
- `GET /api/status/collectors/{component}/debug` — raw PBS/Proxmox API probe
- `GET /api/connections?platform={platform}` — all connections for a platform
- `POST /api/connections/{id}/test` — test connection (delegates to _probe_connection)

### Entity ID format
- `proxmox:{name}:{vmid}` — e.g. `proxmox:graylog:119`
- `cluster:proxmox:Pmox Cluster KB`
- `unifi:device:{mac}`
- `pbs:datastore:{name}`
- `truenas:pool:{name}`
- `fortigate:iface:{name}`
- `docker:{name}` / `swarm:{name}`
- `external_services:{slug}`
- `connection:{id}`

### Compare state (App.jsx)
- `compareMode`, `compareSet`, `compareChats`, `bcTargets`
- `addToCompare(entity)` — use this name
- `SLOT_COLORS` exported from `ComparePanel.jsx`
- Suggestions: `getEntitySuggestions(entity)` in `ComparePanel.jsx`

### CI/CD — every CC prompt must end with
```bash
git add -A
git commit -m "type(scope): description"
git push origin main
# After CI green:
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env \
  up -d hp1_agent
```

### VPN relay for Prox Cluster FIN
- Windows portproxy: `192.168.199.51:18006` → `10.10.11.11:8006`
- Connection stored in DB as host=`192.168.199.51`, port=`18006`
- Add/remove relay: `netsh interface portproxy add/delete v4tov4 ...`

---

## 📁 CC Prompt output files

| File | Purpose |
|---|---|
| `CC_PROMPT_v2.6.2.md` | test_connection() delegates to _probe_connection |
| `CC_PROMPT_v2.6.3.md` | TrueNAS rich card + CardFilterBar fix |
| `CC_PROMPT_v2.6.4.md` | FortiGate rich card |
| `CC_PROMPT_v2.6.5.md` | hp1_postgres cleanup + dynamic postgres + section wiring |
| `CC_PROMPT_v2.6.6.md` | PBS snapshot count + debug endpoint fix |
| `CC_PROMPT_v2.7.0.md` | Multiple Proxmox connections → multiple COMPUTE cards |
| `CC_PROMPT_v2.7.1.md` | Per-cluster Proxmox filter bars |
| `CC_PROMPT_v2.7.2.md` | Generic ConnectionFilterBar + UniFi filtering |
| `CC_PROMPT_v2.7.3.md` | Compare per-entity chat suggestions |
