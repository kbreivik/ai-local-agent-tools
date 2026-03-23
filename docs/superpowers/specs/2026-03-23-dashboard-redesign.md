# HP1 AI Agent Dashboard Redesign — Design Spec

**Date:** 2026-03-23
**Status:** Approved

---

## Goal

Redesign the HP1 AI Agent dashboard to provide full infrastructure visibility: all containers (by host), Docker Swarm services, Proxmox VMs, external services, and storage — with immediate visual emphasis on anything unhealthy.

---

## Navigation

### Change
Add a **Tools** dropdown to the existing top navigation bar. Move **Tests** and **Ingest** out of the top-level nav and into this dropdown.

### Before
Dashboard · Cluster · Commands · Skills · Logs · Memory · Ingest · Output · Tests · admin · Sign out

### After
Dashboard · Cluster · Commands · Skills · Logs · Memory · Output · **Tools ▾** · admin · Sign out

**Tools dropdown contains:** Tests · Ingest

### Implementation notes
- Dropdown opens on click (not hover); closes on outside click
- The Tools item shows active state when the current route is `/tests` or `/ingest`
- No other nav items change

---

## Dashboard — Services Page

The main dashboard replaces the existing services section with four labelled card sections. Cards are globally single-open: opening any card closes the previously open one (across all sections).

---

### Polling

The frontend polls all four data endpoints every **30 seconds** (hardcoded; not user-configurable). Each section polls its own endpoint independently. A loading spinner appears on first load only; subsequent polls update data silently.

---

### Section 1: Containers · agent-01

All Docker containers on agent-01, enumerated via `GET /containers/json` (list API — `State` is a plain string here, not an object). The backend normalises this into `ContainerCard` objects.

**Card face (collapsed):**
- Health dot
- Container name (`Names[0]` stripped of leading `/`)
- Image name + tag (`Image` field, truncated with ellipsis)
- `{host_ip}:{host_port}` — first published port, or `—` if none
- Uptime: pass through the `Status` string from Docker list API as-is (e.g. `"Up 3 hours"`)
- Last-pull badge (see Last-Pull Timestamp section below)

**Card expanded:**
- Uptime + last-pull stats row
- Port mappings: all entries from `Ports[]` in `{host_port}→{container_port}` format, one line
- Volume fill bars: one bar per mount in `Mounts[]` where `Type == "volume"`. Label = `Name`, value = used/total from `docker system df -v` matched by volume name. If usage unavailable, show name only with no bar.
- Actions: **Pull Latest** · **View Logs** · **Restart** · **Stop** · ✕ close

**Section subtitle:** `192.168.199.10 · {N} running`

---

### Section 2: Containers · Swarm

All Docker Swarm services, enumerated via `GET /services` on the Docker Swarm API.

**Card face (collapsed):**
- Health dot
- Service name
- Image name + tag
- Ports: `:port` format (no host IP — Swarm routes internally), first published port
- `{healthy}/{total} replicas · since {date}` (uptime derived from service `CreatedAt` field)
- Last-pull badge

**Card expanded:**
- Replica count (healthy/total) + last-pull stats row
- Port mappings: all published ports, `{published}→{target}` format
- Volume fill bars (same logic as Section 1)
- Actions: **Pull Latest** · **View Logs** · **Scale** · ✕ close
- **Scale action:** renders an inline number stepper (−/+/input) below the actions row when clicked. Confirm button submits. Stepper dismisses on confirm or ✕.

**Section subtitle:** `{N} managers · {N} workers · {N} services` — manager/worker counts come from `GET /nodes` on the Swarm API, included in the `/swarm` response.

---

### Section 3: VMs · Proxmox Cluster

All VMs across all three Proxmox nodes, fetched from the Proxmox API per node.

**Card face (collapsed):**
- Health dot
- VM name (`name` field)
- `VM {vmid} · {node}` (e.g. `VM 9200 · Pmox1`)
- IP address: from a static map in the backend config (keyed by vmid) matching the Ansible inventory. Not fetched dynamically.
- `{vcpus} vCPU · {maxmem_gb} GB RAM`
- Status badge

**Card expanded:**
- CPU % + RAM used/total stats row (from Proxmox `GET /nodes/{node}/qemu/{vmid}/status/current`)
- Disk fill bar(s): guest filesystem usage via QEMU guest agent `GET /nodes/{node}/qemu/{vmid}/agent/get-fsinfo`. One bar per filesystem entry. Label = mountpoint (e.g. `/`), value = used/total bytes. If guest agent is unavailable, omit disk bars.
- Actions depend on VM status:
  - Running: **Open Console** · **View in Proxmox** · **Reboot** · ✕ close
  - Stopped: **Start VM** · **View in Proxmox** · ✕ close
- **Open Console**: opens `https://{proxmox_host}:8006/?console=kvm&vmid={vmid}&node={node}&novnc=1` in a new browser tab
- **View in Proxmox**: opens `https://{proxmox_host}:8006/#v1:0:18:4:::::::` in a new tab

**Section subtitle:** `Pmox1 · Pmox2 · Pmox3 · {N} VMs` (node names are static) + error count if any

---

### Section 4: External Services

Configured external endpoints. Reachability is tested by the backend on each poll.

**Services and their Open UI URLs:**

| Service | Open UI? | URL |
|---------|----------|-----|
| LM Studio | No | — |
| Proxmox API | Yes | `https://{proxmox_host}:8006` |
| TrueNAS | Yes | `https://{truenas_host}` |
| FortiGate | Yes | `https://{fortigate_host}` |

**Card face (collapsed):**
- Health dot
- Service name
- Service type (e.g. `OpenAI-compat API`, `Proxmox cluster API`)
- `host:port`
- Summary line (model name for LM Studio; node/VM count for Proxmox; storage used for TrueNAS; "authenticated" for FortiGate)
- Latency badge

**Card expanded:**
- Latency + status stats row
- Storage fill bar (TrueNAS only): `{share_name}`, used/total
- Actions: **Test Connection** · **Open UI** (where applicable) · ✕ close
- **Test Connection**: fires a single probe and updates the latency/status inline; shows a spinner while in flight

**Section subtitle:** `{N} configured · {N} reachable`

---

## Last-Pull Timestamp

Docker does not record pull timestamps natively. The backend stores pull timestamps as follows:

- On each poll, compare each container/service's image digest (`ImageID`) to the last recorded digest stored in the `status_snapshots` table (`component = 'image:{image_name}'`).
- If the digest has changed (or no record exists), write a new snapshot row with `timestamp = now()`.
- The "last pull" badge shows the age of the most recent snapshot for that image.
- On first run (no snapshot exists), badge shows `unknown`.

**Badge colour thresholds:**
- Green: pulled within the last 24 hours
- Amber: pulled 1–7 days ago
- Red: pulled more than 7 days ago, or `unknown`

---

## Health Dot Logic

### Containers (Section 1)

The Docker list API (`GET /containers/json`) returns `State` as a plain string. Health check status requires a separate `GET /containers/{id}/json` call (inspect). The backend fetches inspect data for each container and merges it.

| Dot colour | Condition |
|-----------|-----------|
| Green | `State == "running"` AND (`Health.Status == "healthy"` OR no health check configured) |
| Amber | `State == "running"` AND `Health.Status` is `"starting"` or `"unhealthy"` |
| Red | `State` is `"exited"`, `"dead"`, or `"created"` |

For Swarm services: green if `RunningTasks == DesiredTasks`; amber if `RunningTasks > 0 && RunningTasks < DesiredTasks`; red if `RunningTasks == 0`.

### VMs (Section 3)

| Dot colour | Condition |
|-----------|-----------|
| Green | `status == "running"` |
| Amber | `status == "paused"` or disk usage >70% |
| Red | `status == "stopped"` |
| Grey | Proxmox API unreachable; status unknown |

### External Services (Section 4)

| Dot colour | Condition |
|-----------|-----------|
| Green | Reachable, latency < 100 ms |
| Amber | Reachable, latency 100–500 ms |
| Red | Unreachable (timeout or connection refused) |

---

## Problem Tag Strings

Canonical `⚠ {reason}` strings shown on problem card faces:

| Condition | Tag text |
|-----------|----------|
| Container exited/dead | `exited` |
| Container health check failing | `health check failing` |
| Swarm: 0 replicas | `no replicas running` |
| Swarm: partial replicas | `{N}/{M} replicas` |
| VM stopped | `stopped` |
| VM paused | `paused` |
| VM disk >70% | `disk {N}% full` |
| External: unreachable | `unreachable` |
| External: high latency | `high latency ({N} ms)` |

---

## Card States — Visual Tokens

| State | Background | Border | Dot |
|-------|-----------|--------|-----|
| Healthy | `#131325` | `#1e1e3a` | green `#22c55e` with glow |
| Warning | `#161008` | `#3a2a0a` | amber `#f59e0b` with glow |
| Error | `#130808` | `#3a0e0e` | red `#ef4444` with glow |
| Unknown | `#131325` | `#222222` | grey `#444444` |

Amber is `#f59e0b` throughout (no "yellow" usage).

---

## Alert Bar

Shown below the top nav bar only when at least one problem exists across any section.

Format: `⚠  {summary}` with a red pill badge showing total issue count.

Summary string: comma-separated list of the first **3** problem items sorted by severity descending (red errors first, then amber warnings; within the same severity, ordered by section: agent-01 → Swarm → VMs → External). If more than 3 issues exist, append ` · +{N} more`.

Example: `elasticsearch health check failing · worker-03 stopped · elastic-01 disk 76% full · +2 more`

---

## Actions — Behavior

All mutating actions (Pull Latest, Restart, Stop, Start VM, Scale, Reboot) behave as follows:

1. Button shows a spinner and becomes disabled while in flight
2. On success: data re-polls immediately; success toast shown
3. On failure: error toast shown with message from API response; button re-enables

**Confirmation dialogs** (shown before firing the request):
- **Stop container**: "Stop {name}? This will terminate the container." — Confirm / Cancel
- **Restart container**: "Restart {name}?" — Confirm / Cancel
- **Reboot VM**: "Reboot {name}? The VM will be temporarily unreachable." — Confirm / Cancel
- All other actions (Pull Latest, Start VM, Scale, View Logs): no confirmation required

---

## API Endpoints (New — Backend)

All endpoints are authenticated via the existing session/token mechanism.

```
GET /api/dashboard/containers/agent01
  Response: { containers: [ContainerCard] }

GET /api/dashboard/containers/swarm
  Response: { services: [SwarmServiceCard] }

GET /api/dashboard/vms
  Response: { vms: [VMCard] }

GET /api/dashboard/external
  Response: { services: [ExternalServiceCard] }

POST /api/dashboard/containers/{id}/pull
  # Pulls the image used by container {id}, then recreates the container.
  # If multiple containers share the image, only this container is recreated.
POST /api/dashboard/containers/{id}/restart
POST /api/dashboard/containers/{id}/stop
POST /api/dashboard/services/{name}/pull
POST /api/dashboard/services/{name}/scale   body: { replicas: N }
POST /api/dashboard/vms/{node}/{vmid}/start
POST /api/dashboard/vms/{node}/{vmid}/reboot
POST /api/dashboard/external/{name}/probe
  # {name} is a fixed snake_case slug: lm_studio | proxmox | truenas | fortigate
  Response: { latency_ms: N, reachable: bool }
```

All POST actions return `{ ok: true }` on success or `{ ok: false, error: "message" }` on failure.

**View Logs** uses the existing `/api/logs` endpoint filtered by container name. Opens in the Logs page (navigation), not a modal. No new endpoint required.

**Card open while action in-flight:** if the user opens a different card while an action is in-flight on another card, the original card closes normally. The in-flight request continues; the toast appears when it completes regardless of which card is open.

**Scale (POST /services/{name}/scale):** UI updates replica count on next poll (30s), not optimistically.

---

## Response Schemas

```typescript
ContainerCard {
  id: string                // Docker container ID (short)
  name: string              // container name, no leading slash
  image: string             // image:tag
  state: "running"|"exited"|"dead"|"created"
  health: "healthy"|"unhealthy"|"starting"|"none"
  ip_port: string           // "192.168.199.10:8000" or ""
  uptime: string            // raw Docker Status string, e.g. "Up 3 hours"
  ports: string[]           // ["8000→8000", "5173→5173"]
  volumes: VolumeUsage[]
  last_pull_at: string|null // ISO timestamp or null
  dot: "green"|"amber"|"red"
  problem: string|null      // canonical tag text or null
}

SwarmServiceCard {
  id: string
  name: string
  image: string
  ports: string[]
  replicas_running: number
  replicas_desired: number
  created_at: string        // ISO timestamp (service CreatedAt)
  volumes: VolumeUsage[]
  last_pull_at: string|null
  dot: "green"|"amber"|"red"
  problem: string|null
  // included once in the /swarm response, not per card:
  // swarm_managers: number
  // swarm_workers: number
}

VMCard {
  vmid: number
  name: string
  node: string              // "Pmox1" | "Pmox2" | "Pmox3"
  status: "running"|"stopped"|"paused"
  ip: string                // from static map
  vcpus: number
  maxmem_gb: number
  cpu_pct: number|null      // null if stopped
  mem_used_gb: number|null
  disks: DiskUsage[]        // from guest agent; empty if unavailable
  dot: "green"|"amber"|"red"|"grey"
  problem: string|null
}

ExternalServiceCard {
  name: string              // display name, e.g. "LM Studio"
  slug: string              // snake_case, e.g. "lm_studio"
  service_type: string      // e.g. "OpenAI-compat API"
  host_port: string         // e.g. "192.168.1.5:8006"
  summary: string           // one-line human description
  latency_ms: number|null   // null if unreachable
  reachable: boolean
  open_ui_url: string|null  // null if no UI
  storage: VolumeUsage|null // TrueNAS only
  dot: "green"|"amber"|"red"
  problem: string|null
}

VolumeUsage {
  name: string
  used_bytes: number|null
  total_bytes: number|null
}

DiskUsage {
  mountpoint: string        // e.g. "/"
  used_bytes: number
  total_bytes: number
}
```

---

## Out of Scope

- Editing service configuration from the dashboard
- Historical charts / time-series graphs
- Alerting / notifications (push/email)
- Drag-to-reorder cards
- Configurable poll interval
- Filebeat or any other Swarm services not currently deployed

---

## Constraints

- Must match existing HP1 dark theme (`#0d0d1a` background, `#7c6af7` accent)
- Cards follow existing component patterns in the frontend codebase
- No new frontend dependencies
- Backend API changes are additive only (no breaking changes to existing endpoints)
- Confirmation dialogs reuse the existing modal/dialog component
