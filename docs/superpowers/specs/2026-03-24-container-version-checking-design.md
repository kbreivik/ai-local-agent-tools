# Container Version Checking Design

## Goal

Show running image version and available GHCR updates on container cards in the agent-01 dashboard section, with a version selector drawer to choose which version to pull before confirming.

## Architecture

**Backend**: `docker_agent01.py` reads `org.opencontainers.image.version` and `org.opencontainers.image.created` image labels from each container and adds `running_version` and `built_at` fields to the card data. A new endpoint `GET /api/dashboard/containers/{id}/tags` fetches available GHCR tags on demand using the `GHCR_TOKEN` env var (a backend-only secret, never exposed to the frontend).

**Frontend**: `ServiceCards.jsx` calls the tags endpoint when a GHCR container card is expanded, stores `{ [containerId]: latestTag }` in `ServiceCards` component state, and uses `compareSemver()` to derive update severity. Subtitle line and expanded card reflect the result.

## Utilities

### `compareSemver(current, latest)`

Already exists in `utils/versionCheck.js`. Contract:
- Inputs: two semver strings. Both are normalized before comparison — strip a leading `v` if present (e.g. `v1.10.0` → `1.10.0`).
- Returns: `'current'` | `'patch'` | `'minor'` | `'major'` | `'ahead'` | `'unknown'`
- Returns `'unknown'` if either input is null, empty, or not parseable as `major.minor.patch`.

## Components

### Backend — `docker_agent01.py`

Add to the per-container card:
- `running_version` — value of `org.opencontainers.image.version` label, normalized (strip leading `v`), or `null`
- `built_at` — value of `org.opencontainers.image.created` label, or `null`

Read from `c.image.labels` (available via Docker SDK without extra API calls). Set both to `null` for non-GHCR images (i.e. image string does not start with `ghcr.io/`).

### Backend — new endpoint `GET /api/dashboard/containers/{id}/tags`

Path: `/api/dashboard/containers/{id}/tags`
`{id}` is the 12-character `short_id` as returned in `c.short_id` by the collector.
Auth: same JWT bearer token as all other dashboard endpoints. `GHCR_TOKEN` is a backend env var — it is never returned to the client.

Logic:
1. Load the latest `docker_agent01` snapshot. Find container where `c["id"] == id`.
2. If not found → HTTP 404 `{ error: "container not found" }`.
3. If not a GHCR image → HTTP 200 `{ tags: [], error: "not a ghcr image" }`.
4. Parse: strip `ghcr.io/` prefix, strip tag/digest → `owner/repo` (e.g. `kbreivik/hp1-ai-agent`).
5. Fetch tags from GHCR v2 API (`GET https://ghcr.io/v2/{owner}/{repo}/tags/list?n=100`). Follow `Link: <url>; rel="next"` pagination headers for up to 3 pages or until 20 semver tags are collected.
6. Filter to strict semver (`^\d+\.\d+\.\d+$`), sort descending by version tuple, return top 20.
7. Cache in module-level `dict[image_bare → (tags, fetched_at)]` with 10-minute TTL.
8. On GHCR auth failure (token missing, GHCR returns 401/403) → HTTP 503 `{ error: "ghcr auth failed" }`.
9. On GHCR network error → HTTP 502 `{ error: "ghcr unreachable" }`.
10. Response on success: `{ tags: [str] }` — `tags[0]` is the highest available semver. May be empty if no semver tags exist.

### Backend — pull endpoint extension

`POST /api/dashboard/containers/{id}/pull` is extended with an optional `tag` query parameter:

```
POST /api/dashboard/containers/{id}/pull?tag=v1.11.0
```

When `tag` is provided, the backend pulls `{image_name}:{tag}` from GHCR (not the default `:latest`), then restarts the container using the new image. When omitted, behaviour is unchanged.

### Frontend — `knownLatest` state

`ServiceCards` holds `knownLatest` as `useState({})` — a map of `{ [containerId]: string }` (latest tag string).

**Update rule**: `knownLatest` is only _added to_ — entries are never cleared during normal polling. An entry is only evicted when the container it refers to disappears from the containers list (i.e. the container was removed). This prevents the subtitle badge and expanded card info from flickering on every 30-second `load()` call.

An open expanded card that already has tags loaded does not re-fetch on `load()`. Tags are re-fetched on the next manual open after a pull completes (`onAction()` calls `load()`, but the card collapses on action, so the next open triggers a fresh fetch).

### Frontend — collapsed card subtitle

For GHCR containers, the `sub` label passed to `InfraCard` is computed as:

```js
const imageName = c.image.split('/').pop().split(':')[0]
const latestTag = knownLatest[c.id]
const severity = (latestTag && c.running_version)
  ? compareSemver(c.running_version, latestTag)
  : null

const sub = (severity === 'major')
  ? { text: `${imageName}: not latest`, cls: 'text-[#b04020]' }
  : (severity === 'minor' || severity === 'patch')
  ? { text: `${imageName}: not latest`, cls: 'text-[#92601a]' }
  : c.image   // unchanged string
```

`knownLatest[c.id]` is only set after the user has expanded that card at least once. Before that, the subtitle shows the raw image string (no badge).

### Frontend — expanded card

`ContainerCardExpanded` receives two new props: `knownLatest` (the map) and `onTagsLoaded(id, latestTag)` callback.

On mount for GHCR containers, call `GET /api/dashboard/containers/{id}/tags`. Show a spinner in the version section while loading.

Version info rows (rendered below the stats divider, only for GHCR containers with `running_version` set):

```
Running    1.10.0
Built      2026-03-20
Status     [⬆ 1.11.0 minor]   ← amber  |  [✓ latest] ← green
```

Below the status row, behaviour by case:

| Case | UI |
|------|----|
| Minor/patch update | Amber button `⬆ Update Available — Choose Version` → opens drawer |
| Major update | Red button, otherwise identical drawer |
| Up to date | Green `✓ latest` badge + plain `↓ Re-pull Image` button |
| `tags` empty (no semver tags) | Grey `no versioned tags found` text + `↓ Pull Latest` fallback |
| 404 / 503 / 502 from tags endpoint | Grey `version check unavailable` text + `↓ Pull Latest` fallback |
| `running_version` is null | Version section hidden, existing PullBadge + `↓ Pull Latest` unchanged |

**Drawer** (opened by update button):
- `<select>` populated from `tags`; running version entry suffixed with `← running`
- `↓ Pull {selectedTag}` → calls `POST /containers/{id}/pull?tag={selectedTag}` → `onAction()` → drawer closes
- `✕` to cancel

## Data Flow

```
docker_agent01.py poll (every 30s)
  └─ reads image labels → running_version (v-stripped), built_at per container
  └─ stored in status_snapshots["docker_agent01"]

Frontend load() (every 30s)
  └─ fetches /api/dashboard/containers → cards with running_version, built_at
  └─ knownLatest entries for removed containers are evicted

User expands a GHCR container card
  └─ GET /api/dashboard/containers/{id}/tags (cached 10min on backend)
  └─ returns { tags }
  └─ onTagsLoaded(id, tags[0]) → knownLatest[id] = tags[0]
  └─ severity = compareSemver(running_version, tags[0])
  └─ collapsed subtitle updates to "not latest" if outdated

User selects version and confirms pull
  └─ POST /api/dashboard/containers/{id}/pull?tag=v1.11.0
  └─ onAction() → card collapses → load() fires
  └─ next expand triggers fresh tags fetch
```

## Scope

- Only `docker_agent01` containers (agent-01 section). Swarm services are out of scope.
- Only GHCR images (`ghcr.io/…`). Docker Hub / local images keep existing PullBadge behaviour.
- Dot color is health-only — no change for version status.
- No auto-update. Existing `↓ Pull Latest` is replaced by the version selector drawer for GHCR images; kept as fallback for error states.

## Error Handling

| Condition | HTTP | Frontend |
|-----------|------|----------|
| Container not in snapshot | 404 | Grey "version check unavailable", `↓ Pull Latest` fallback |
| Not a GHCR image | 200 `{ tags: [] }` | Version section hidden, legacy UI |
| GHCR token missing / auth fail | 503 | Grey "version check unavailable", `↓ Pull Latest` fallback |
| GHCR network error | 502 | Grey "version check unavailable", `↓ Pull Latest` fallback |
| No semver tags found | 200 `{ tags: [] }` | Grey "no versioned tags found", `↓ Pull Latest` fallback |
| `running_version` null (label missing) | — | Version section hidden, legacy PullBadge |
