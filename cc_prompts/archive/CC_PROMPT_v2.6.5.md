# CC PROMPT — v2.6.5 — Remove hp1_postgres, fix DS-postgres health, wire new sections

## Changes

Three related fixes in one commit.

---

## Fix 1 — docker/docker-compose.yml

The dev-profile postgres service still uses the old underscore naming.

File: `docker/docker-compose.yml`

Change the container name in the `postgres` service (under `profiles: ["dev"]`):

```yaml
# Before
container_name: hp1_postgres

# After
container_name: hp1-postgres
```

This aligns the dev container name with the production container name in
`agent-compose.yml` (`container_name: hp1-postgres`).

---

## Fix 2 — App.jsx: make DS-postgres row dynamic

File: `gui/src/App.jsx` — `PlatformCoreCards()` function

Currently the postgres row is hardcoded always-green and never checks the actual
container state:

```jsx
// REMOVE this hardcoded row:
{_row('var(--green)', 'DS-postgres', 'HEALTHY', 'green', 'pg16')}
```

Replace with a dynamic check that reads from the docker_agent01 collector.

### Step 1: Add container fetch to PlatformCoreCards

Inside `PlatformCoreCards()`, add container data alongside the existing fetches:

```jsx
function PlatformCoreCards() {
  const [health, setHealth] = useState(null)
  const [statusData, setStatusData] = useState(null)
  const [memHealth, setMemHealth] = useState(null)
  const [containers, setContainers] = useState([])   // ADD THIS

  useEffect(() => {
    const load = () => {
      fetchHealth().then(setHealth).catch(() => {})
      fetchStatus().then(setStatusData).catch(() => {})
      fetchMemoryHealth().then(setMemHealth).catch(() => {})
      fetchDashboardContainers().then(d => setContainers(d?.containers || [])).catch(() => {})  // ADD THIS
    }
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [])
```

### Step 2: Derive postgres status from containers

Add this derived value below the existing `muninnEngrams` line:

```jsx
  // Find postgres container dynamically — matches hp1-postgres, hp1_postgres, DS-postgres, etc.
  const pgContainer = containers.find(c =>
    c.name?.toLowerCase().includes('postgres') && !c.name?.toLowerCase().includes('pgadmin')
  )
  const pgDot    = pgContainer ? pgContainer.dot : 'grey'
  const pgHealth = pgContainer
    ? (pgContainer.dot === 'green' ? 'HEALTHY' : pgContainer.dot === 'amber' ? 'DEGRADED' : 'ERROR')
    : 'UNKNOWN'
  const pgLabel  = pgContainer?.name || 'postgres'
  const pgVersion = pgContainer?.image?.match(/pg(\d+)/i)?.[1]
    ? `pg${pgContainer.image.match(/pg(\d+)/i)[1]}`
    : pgContainer ? 'running' : ''
```

### Step 3: Replace the hardcoded row

```jsx
// Replace:
{_row('var(--green)', 'DS-postgres', 'HEALTHY', 'green', 'pg16')}

// With:
{_row(_healthDot(pgDot === 'green' ? 'healthy' : pgDot === 'amber' ? 'degraded' : pgDot === 'red' ? 'error' : 'unknown'), pgLabel, pgHealth, pgDot === 'green' ? 'green' : pgDot === 'amber' ? 'amber' : pgDot === 'red' ? 'red' : 'grey', pgVersion)}
```

---

## Fix 3 — App.jsx: wire FortiGate and TrueNAS into section activeFilters

File: `gui/src/App.jsx` — `DashboardView()` function

The NETWORK and STORAGE sections pass `activeFilters` to `ServiceCards` but are
missing the new platform keys added in v2.6.3 and v2.6.4.

### NETWORK section

```jsx
// Before:
<ServiceCards activeFilters={['unifi']} .../>

// After:
<ServiceCards activeFilters={['unifi', 'fortigate']} .../>
```

### STORAGE section

```jsx
// Before:
<ServiceCards activeFilters={['pbs']} .../>

// After:
<ServiceCards activeFilters={['pbs', 'truenas']} .../>
```

---

## Commit & deploy

```bash
git add -A
git commit -m "fix(platform): remove hp1_postgres, dynamic postgres health, wire new sections

- docker-compose.yml: rename container hp1_postgres → hp1-postgres (dev profile)
- App.jsx PlatformCoreCards: postgres row now reads actual container state from
  docker_agent01 collector instead of hardcoded always-green
- App.jsx DashboardView: NETWORK section adds fortigate, STORAGE adds truenas
  to ServiceCards activeFilters so new rich cards render in their sections"
git push origin main
# After CI green:
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env \
  up -d hp1_agent
```
