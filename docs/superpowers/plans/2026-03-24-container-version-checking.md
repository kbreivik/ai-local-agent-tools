# Container Version Checking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the running image version and available GHCR updates on agent-01 container cards, with an inline version-selector drawer to pick and pull a specific version.

**Architecture:** `docker_agent01.py` reads `org.opencontainers.image.version` / `org.opencontainers.image.created` labels and adds them to each container card. A new GET endpoint fetches available GHCR tags on demand (cached 10 min, backend-authenticated). The pull endpoint is extended with an optional `?tag=` query param. The frontend stores `knownLatest` per container in `ServiceCards` state, renders a subtitle change (`not latest`) and an expand-on-click version drawer in `ContainerCardExpanded`.

**Tech Stack:** Python 3.11, FastAPI, httpx, docker SDK, React 18, Tailwind CSS, existing `compareSemver()` from `utils/versionCheck.js`.

**Spec:** `docs/superpowers/specs/2026-03-24-container-version-checking-design.md`

---

## File Map

| File | Change |
|------|--------|
| `api/collectors/docker_agent01.py` | Read image labels → `running_version`, `built_at` per card |
| `api/routers/dashboard.py` | Add `GET /containers/{id}/tags` + extend pull with `?tag=` |
| `tests/test_collectors_docker_agent01.py` | Tests for label reading |
| `tests/test_routers_dashboard.py` | Tests for tags endpoint + pull-with-tag |
| `gui/src/api.js` | Add `fetchContainerTags(id)` |
| `gui/src/components/ServiceCards.jsx` | `knownLatest` state, subtitle, `ContainerCardExpanded` version section + drawer |

---

## Task 1: Collector — read image version labels

**Files:**
- Modify: `api/collectors/docker_agent01.py:44-85` (the per-container loop)
- Test: `tests/test_collectors_docker_agent01.py`

### Background

`docker_agent01.py` loops over containers and builds a card dict. `c.image.labels` is a dict of OCI labels available from the Docker SDK without an extra API call. We only extract these for GHCR images.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_collectors_docker_agent01.py`:

```python
def test_ghcr_container_exposes_running_version_and_built_at():
    """GHCR image with OCI labels → running_version and built_at in card."""
    from api.collectors.docker_agent01 import DockerAgent01Collector
    collector = DockerAgent01Collector()

    mock_container = MagicMock()
    mock_container.id = "abc123def456"
    mock_container.short_id = "abc123"
    mock_container.attrs = {
        "Name": "/hp1_agent",
        "Config": {"Image": "ghcr.io/kbreivik/hp1-ai-agent:latest"},
        "State": {"Status": "running", "Health": None},
        "HostConfig": {},
        "Mounts": [],
        "NetworkSettings": {"Ports": {}},
        "Status": "Up 1 hour",
    }
    mock_container.image.id = "sha256:abc"
    mock_container.image.labels = {
        "org.opencontainers.image.version": "v1.10.0",
        "org.opencontainers.image.created": "2026-03-20T12:00:00Z",
    }

    mock_client = MagicMock()
    mock_client.containers.list.return_value = [mock_container]
    mock_client.df.return_value = {"Volumes": []}

    with patch("docker.DockerClient", return_value=mock_client), \
         patch("api.collectors.docker_agent01._load_last_digests", return_value={}), \
         patch("api.collectors.docker_agent01._check_digest", return_value=None):
        result = asyncio.run(collector.poll())

    card = result["containers"][0]
    assert card["running_version"] == "1.10.0"        # leading v stripped
    assert card["built_at"] == "2026-03-20T12:00:00Z"


def test_non_ghcr_container_has_null_version_fields():
    """Non-GHCR image → running_version and built_at are None regardless of labels."""
    from api.collectors.docker_agent01 import DockerAgent01Collector
    collector = DockerAgent01Collector()

    mock_container = MagicMock()
    mock_container.id = "def456abc123"
    mock_container.short_id = "def456"
    mock_container.attrs = {
        "Name": "/muninndb",
        "Config": {"Image": "postgres:16"},
        "State": {"Status": "running", "Health": None},
        "HostConfig": {},
        "Mounts": [],
        "NetworkSettings": {"Ports": {}},
        "Status": "Up 2 days",
    }
    mock_container.image.id = "sha256:def"
    mock_container.image.labels = {
        "org.opencontainers.image.version": "16.0",
    }

    mock_client = MagicMock()
    mock_client.containers.list.return_value = [mock_container]
    mock_client.df.return_value = {"Volumes": []}

    with patch("docker.DockerClient", return_value=mock_client), \
         patch("api.collectors.docker_agent01._load_last_digests", return_value={}), \
         patch("api.collectors.docker_agent01._check_digest", return_value=None):
        result = asyncio.run(collector.poll())

    card = result["containers"][0]
    assert card["running_version"] is None
    assert card["built_at"] is None


def test_ghcr_container_missing_labels_has_null_version():
    """GHCR image with no OCI labels → running_version is None, no crash."""
    from api.collectors.docker_agent01 import DockerAgent01Collector
    collector = DockerAgent01Collector()

    mock_container = MagicMock()
    mock_container.id = "aaa111bbb222"
    mock_container.short_id = "aaa111"
    mock_container.attrs = {
        "Name": "/hp1_agent",
        "Config": {"Image": "ghcr.io/kbreivik/hp1-ai-agent:latest"},
        "State": {"Status": "running", "Health": None},
        "HostConfig": {},
        "Mounts": [],
        "NetworkSettings": {"Ports": {}},
        "Status": "Up 5 minutes",
    }
    mock_container.image.id = "sha256:aaa"
    mock_container.image.labels = {}    # no labels

    mock_client = MagicMock()
    mock_client.containers.list.return_value = [mock_container]
    mock_client.df.return_value = {"Volumes": []}

    with patch("docker.DockerClient", return_value=mock_client), \
         patch("api.collectors.docker_agent01._load_last_digests", return_value={}), \
         patch("api.collectors.docker_agent01._check_digest", return_value=None):
        result = asyncio.run(collector.poll())

    card = result["containers"][0]
    assert card["running_version"] is None
    assert card["built_at"] is None
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd D:/claude_code/FAJK/HP1-AI-Agent-v1
python -m pytest tests/test_collectors_docker_agent01.py::test_ghcr_container_exposes_running_version_and_built_at -v
```

Expected: `FAILED` — `KeyError: 'running_version'` (field doesn't exist yet)

- [ ] **Step 3: Implement label reading in the collector**

In `api/collectors/docker_agent01.py`, inside `_collect_sync`, find the loop that builds `cards`. After line `image = attrs.get("Config", {}).get("Image", "")`, add:

```python
                # OCI image labels — only extracted for GHCR images
                running_version = None
                built_at = None
                if image.startswith("ghcr.io/"):
                    try:
                        labels = c.image.labels or {}
                    except Exception:
                        labels = {}
                    raw_ver = labels.get("org.opencontainers.image.version", "")
                    if raw_ver:
                        running_version = raw_ver.lstrip("v")
                    built_at = labels.get("org.opencontainers.image.created") or None
```

Then in the `cards.append({...})` call, add these two fields after `"last_pull_at": last_pull_at,`:

```python
                    "running_version": running_version,
                    "built_at": built_at,
```

- [ ] **Step 4: Run all three new tests**

```bash
python -m pytest tests/test_collectors_docker_agent01.py -v
```

Expected: all tests pass (including the 2 existing ones)

- [ ] **Step 5: Commit**

```bash
git add api/collectors/docker_agent01.py tests/test_collectors_docker_agent01.py
git commit -m "feat(collector): add running_version and built_at from OCI image labels"
```

---

## Task 2: Backend — GET /containers/{id}/tags endpoint

**Files:**
- Modify: `api/routers/dashboard.py`
- Test: `tests/test_routers_dashboard.py`

### Background

This endpoint loads the latest `docker_agent01` snapshot from the DB, finds the container by `short_id`, then fetches GHCR tag list via the registry v2 API. GHCR auth uses `GHCR_TOKEN` env var (set in `.env`, never returned to client). Results are cached 10 min in a module-level dict.

**Existing code to be aware of:**
- `import asyncio` is already at line 7 — no change needed
- `import os` is already at line 9 — no change needed
- `from fastapi import APIRouter, Depends` at line 11 — Step 5 merges `HTTPException` into this line
- `_parse_state(snap)` helper already exists at lines 22–32 — already used by other endpoints, no reimplementation needed
- The file currently references `log` in `_do_self_update` but never imports `logging`. We fix this as a dependency of adding our own log calls.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_routers_dashboard.py`:

```python
# ── /containers/{id}/tags ─────────────────────────────────────────────────────

import api.routers.dashboard as _dash

@pytest.fixture(autouse=True)
def _clear_ghcr_cache():
    """Clear the module-level GHCR tag cache before and after each test.
    Without this, a successful tags fetch populates the cache, and subsequent
    503/502 tests hit the cache before reaching the token check or httpx.get.
    """
    _dash._GHCR_TAG_CACHE.clear()
    yield
    _dash._GHCR_TAG_CACHE.clear()


def test_container_tags_requires_auth():
    r = _tc.get("/api/dashboard/containers/abc123/tags")
    assert r.status_code == 401


def test_container_tags_returns_sorted_semver_tags(client):
    """Returns descending semver tags from GHCR for a GHCR container."""
    snap = _agent01_snap()
    # Make the test container a GHCR image
    import json
    state = json.loads(snap["state"])
    state["containers"][0]["image"] = "ghcr.io/kbreivik/hp1-ai-agent:latest"
    snap["state"] = json.dumps(state)

    fake_ghcr_response = {
        "tags": ["latest", "1.11.0", "1.10.0", "1.9.2", "sha-abc123"]
    }

    import os
    with patch("api.routers.dashboard.q.get_latest_snapshot", new=AsyncMock(return_value=snap)), \
         patch.dict(os.environ, {"GHCR_TOKEN": "test-token"}), \
         patch("httpx.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = fake_ghcr_response
        mock_resp.headers = {}
        mock_get.return_value = mock_resp
        r = client.get("/api/dashboard/containers/abc123/tags")

    assert r.status_code == 200
    body = r.json()
    assert "tags" in body
    assert body["tags"] == ["1.11.0", "1.10.0", "1.9.2"]  # sorted desc, no non-semver


def test_container_tags_returns_404_for_unknown_container(client):
    """Container not found in snapshot → 404."""
    with patch("api.routers.dashboard.q.get_latest_snapshot", new=AsyncMock(return_value=_agent01_snap())):
        r = client.get("/api/dashboard/containers/notexist/tags")
    assert r.status_code == 404


def test_container_tags_returns_empty_for_non_ghcr_image(client):
    """Non-GHCR image → 200 with empty tags list."""
    with patch("api.routers.dashboard.q.get_latest_snapshot", new=AsyncMock(return_value=_agent01_snap())):
        # abc123 has image "hp1-ai-agent:latest" (not ghcr.io/…) in _agent01_snap
        r = client.get("/api/dashboard/containers/abc123/tags")
    assert r.status_code == 200
    assert r.json()["tags"] == []


def test_container_tags_returns_503_when_token_missing(client):
    """No GHCR_TOKEN (empty string) → 503."""
    snap = _agent01_snap()
    import json, os
    state = json.loads(snap["state"])
    state["containers"][0]["image"] = "ghcr.io/kbreivik/hp1-ai-agent:latest"
    snap["state"] = json.dumps(state)

    # Override GHCR_TOKEN to empty string. The implementation does `if not token:`
    # which treats both missing and empty as "not configured".
    with patch("api.routers.dashboard.q.get_latest_snapshot", new=AsyncMock(return_value=snap)), \
         patch.dict(os.environ, {"GHCR_TOKEN": ""}):
        r = client.get("/api/dashboard/containers/abc123/tags")
    assert r.status_code == 503


def test_container_tags_returns_502_on_ghcr_network_error(client):
    """GHCR unreachable (network error) → 502."""
    snap = _agent01_snap()
    import json, os
    state = json.loads(snap["state"])
    state["containers"][0]["image"] = "ghcr.io/kbreivik/hp1-ai-agent:latest"
    snap["state"] = json.dumps(state)

    with patch("api.routers.dashboard.q.get_latest_snapshot", new=AsyncMock(return_value=snap)), \
         patch.dict(os.environ, {"GHCR_TOKEN": "test-token"}), \
         patch("httpx.get", side_effect=Exception("connection refused")):
        r = client.get("/api/dashboard/containers/abc123/tags")
    assert r.status_code == 502


def test_container_tags_returns_503_when_ghcr_rejects_token(client):
    """Token present but GHCR returns 401 → 503."""
    snap = _agent01_snap()
    import json, os
    state = json.loads(snap["state"])
    state["containers"][0]["image"] = "ghcr.io/kbreivik/hp1-ai-agent:latest"
    snap["state"] = json.dumps(state)

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.ok = False

    with patch("api.routers.dashboard.q.get_latest_snapshot", new=AsyncMock(return_value=snap)), \
         patch.dict(os.environ, {"GHCR_TOKEN": "bad-token"}), \
         patch("httpx.get", return_value=mock_resp):
        r = client.get("/api/dashboard/containers/abc123/tags")
    assert r.status_code == 503
```

- [ ] **Step 2: Run to verify they fail**

```bash
python -m pytest tests/test_routers_dashboard.py::test_container_tags_returns_404_for_unknown_container -v
```

Expected: `FAILED` — 404 or 422 (endpoint doesn't exist yet)

- [ ] **Step 3: Add logging import and module-level cache to dashboard.py**

At the top of `api/routers/dashboard.py`, add after the existing imports:

```python
import logging
import re
import time as _time

log = logging.getLogger(__name__)

_GHCR_TAG_CACHE: dict = {}   # { image_bare: (tags, fetched_at) }
_GHCR_TAG_TTL = 600          # 10 minutes
```

- [ ] **Step 4: Add `_fetch_ghcr_tags` helper to dashboard.py**

Add before the `# ── Action endpoints` section:

```python
def _fetch_ghcr_tags(image_bare: str) -> list[str]:
    """Fetch semver tags from GHCR for a bare image name (e.g. ghcr.io/user/repo).
    Returns sorted-descending list of strict semver tags, up to 20.
    Raises RuntimeError on auth failure, IOError on network failure.
    Results cached for _GHCR_TAG_TTL seconds.
    """
    import httpx

    cached = _GHCR_TAG_CACHE.get(image_bare)
    if cached and (_time.monotonic() - cached[1]) < _GHCR_TAG_TTL:
        return cached[0]

    token = os.environ.get("GHCR_TOKEN", "")
    if not token:
        raise RuntimeError("GHCR_TOKEN not configured")

    repo = image_bare[len("ghcr.io/"):]   # kbreivik/hp1-ai-agent
    headers = {"Authorization": f"Bearer {token}"}
    semver_re = re.compile(r"^\d+\.\d+\.\d+$")
    all_tags: list[str] = []
    url = f"https://ghcr.io/v2/{repo}/tags/list?n=100"

    for _ in range(3):
        try:
            r = httpx.get(url, headers=headers, timeout=10, follow_redirects=True)
        except Exception as exc:
            raise IOError(f"GHCR unreachable: {exc}") from exc

        if r.status_code in (401, 403):
            raise RuntimeError(f"GHCR auth failed: HTTP {r.status_code}")
        if not r.ok:
            raise IOError(f"GHCR error: HTTP {r.status_code}")

        all_tags.extend(r.json().get("tags") or [])

        if len([t for t in all_tags if semver_re.match(t)]) >= 20:
            break

        # Follow Link header pagination
        next_url = None
        for part in r.headers.get("link", "").split(","):
            part = part.strip()
            if 'rel="next"' in part:
                next_url = part.split(";")[0].strip().strip("<>")
                break
        if not next_url:
            break
        url = next_url

    semver_tags = [t for t in all_tags if semver_re.match(t)]
    semver_tags.sort(key=lambda v: tuple(int(x) for x in v.split(".")), reverse=True)
    result = semver_tags[:20]
    _GHCR_TAG_CACHE[image_bare] = (result, _time.monotonic())
    return result
```

- [ ] **Step 5: Add `GET /containers/{id}/tags` endpoint to dashboard.py**

First, merge `HTTPException` into the existing top-of-file FastAPI import:

```python
# Change this line (around line 11):
from fastapi import APIRouter, Depends
# To:
from fastapi import APIRouter, Depends, HTTPException
```

Then add the endpoint after the `get_external` endpoint and before `# ── Action endpoints`:

```python
# ── GET /containers/{id}/tags ─────────────────────────────────────────────────

@router.get("/containers/{container_id}/tags")
async def get_container_tags(container_id: str, user: str = Depends(get_current_user)):
    """Available GHCR semver tags for a GHCR-hosted container image.

    Returns { tags: [...] } sorted descending. Cached 10 min on the backend.
    Returns empty tags list for non-GHCR images (not an error).
    """
    async with get_engine().connect() as conn:
        snap = await q.get_latest_snapshot(conn, "docker_agent01")

    state = _parse_state(snap)
    containers = state.get("containers", [])
    container = next((c for c in containers if c["id"] == container_id), None)

    if container is None:
        raise HTTPException(status_code=404, detail="container not found")

    image = container.get("image", "")
    if not image.startswith("ghcr.io/"):
        return {"tags": [], "error": "not a ghcr image"}

    bare = image.split("@")[0].split(":")[0]   # ghcr.io/kbreivik/hp1-ai-agent

    try:
        tags = await asyncio.to_thread(_fetch_ghcr_tags, bare)
        return {"tags": tags}
    except RuntimeError as exc:
        log.warning("GHCR auth error for %s: %s", bare, exc)
        raise HTTPException(status_code=503, detail=str(exc))
    except IOError as exc:
        log.warning("GHCR network error for %s: %s", bare, exc)
        raise HTTPException(status_code=502, detail=str(exc))
```

- [ ] **Step 6: Run the new tests**

```bash
python -m pytest tests/test_routers_dashboard.py -v -k "tags"
```

Expected: all 7 `test_container_tags_*` tests pass

- [ ] **Step 7: Run the full test suite to check for regressions**

```bash
python -m pytest tests/test_routers_dashboard.py tests/test_collectors_docker_agent01.py -v
```

Expected: all tests pass

- [ ] **Step 8: Commit**

```bash
git add api/routers/dashboard.py tests/test_routers_dashboard.py
git commit -m "feat(dashboard): add GET /containers/{id}/tags endpoint for GHCR version lookup"
```

---

## Task 3: Backend — pull endpoint accepts optional `?tag=` param

**Files:**
- Modify: `api/routers/dashboard.py:161-175` (`pull_container` + `_do_pull`)
- Test: `tests/test_routers_dashboard.py`

### Background

When `?tag=1.11.0` is passed, the backend pulls `{image_bare}:1.11.0` from GHCR, then re-tags it as the container's current image name (e.g. `:latest`) so the existing `container.restart()` picks up the new image. Without a tag the behaviour is unchanged.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_routers_dashboard.py`:

```python
def test_pull_container_with_tag(client):
    """POST /containers/{id}/pull?tag=1.11.0 pulls versioned image, re-tags it, and restarts."""
    with patch("docker.DockerClient") as mock_dc:
        mock_container = MagicMock()
        mock_container.attrs = {"Config": {"Image": "ghcr.io/kbreivik/hp1-ai-agent:latest"}}
        mock_pulled_image = MagicMock()
        mock_dc.return_value.containers.get.return_value = mock_container
        mock_dc.return_value.images.pull.return_value = mock_pulled_image

        r = client.post("/api/dashboard/containers/abc123/pull?tag=1.11.0")

    assert r.status_code == 200
    assert r.json()["ok"] is True

    # Versioned image was pulled (ghcr.io/kbreivik/hp1-ai-agent:1.11.0)
    pull_calls = mock_dc.return_value.images.pull.call_args_list
    assert any("1.11.0" in str(call) for call in pull_calls), \
        f"Expected versioned pull, got: {pull_calls}"

    # Re-tagged as :latest (the container's current image tag)
    mock_pulled_image.tag.assert_called_once()
    tag_args = mock_pulled_image.tag.call_args
    assert "latest" in str(tag_args), \
        f"Expected re-tag to :latest, got: {tag_args}"

    # Container was restarted
    mock_container.restart.assert_called_once()
```

- [ ] **Step 2: Run to verify it fails**

```bash
python -m pytest tests/test_routers_dashboard.py::test_pull_container_with_tag -v
```

Expected: `FAILED` — either assertion error (tag not passed) or missing assert

- [ ] **Step 3: Update `pull_container` and `_do_pull` in dashboard.py**

Replace the existing `pull_container` endpoint and `_do_pull` function:

```python
@router.post("/containers/{container_id}/pull")
async def pull_container(
    container_id: str,
    tag: str | None = None,
    user: str = Depends(get_current_user),
):
    return await asyncio.to_thread(_do_pull, container_id, tag)


def _do_pull(container_id: str, tag: str | None = None) -> dict:
    try:
        client = _docker_client()
        container = client.containers.get(container_id)
        image_name = container.attrs["Config"]["Image"]

        if tag:
            # Pull the versioned image, then re-tag it as the container's current image
            # so container.restart() uses the new version.
            bare = image_name.split("@")[0].split(":")[0]
            versioned = f"{bare}:{tag}"
            pulled = client.images.pull(versioned)
            current_tag = image_name.split(":")[-1] if ":" in image_name else "latest"
            pulled.tag(bare, tag=current_tag)
        else:
            client.images.pull(image_name)

        container.restart()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
```

- [ ] **Step 4: Run the new test plus existing pull tests**

```bash
python -m pytest tests/test_routers_dashboard.py -v -k "pull"
```

Expected: `test_pull_container_with_tag` and any existing pull tests all pass

- [ ] **Step 5: Commit**

```bash
git add api/routers/dashboard.py tests/test_routers_dashboard.py
git commit -m "feat(dashboard): extend pull endpoint with optional ?tag= for versioned pulls"
```

---

## Task 4: Frontend — add `fetchContainerTags` to api.js

**Files:**
- Modify: `gui/src/api.js:280-312` (Dashboard section)

### Background

`api.js` exports all backend calls. The tags endpoint is a GET that returns `{ tags }`. The pull with tag reuses the existing `dashboardAction` (it builds the URL including the query string — no changes needed there).

- [ ] **Step 1: Add `fetchContainerTags` to the Dashboard section of `gui/src/api.js`**

After `fetchDashboardExternal`, add:

```js
export async function fetchContainerTags(containerId) {
  const r = await fetch(`${BASE}/api/dashboard/containers/${containerId}/tags`, {
    headers: { ...authHeaders() },
  })
  if (!r.ok) return { tags: [], error: `HTTP ${r.status}` }
  return r.json()
}
```

- [ ] **Step 2: Verify the dev server still compiles**

```bash
cd gui && npm run build 2>&1 | tail -5
```

Expected: build succeeds, no errors

- [ ] **Step 3: Commit**

```bash
git add gui/src/api.js
git commit -m "feat(api): add fetchContainerTags for GHCR version lookup"
```

---

## Task 5: Frontend — `knownLatest` state + subtitle in ServiceCards

**Files:**
- Modify: `gui/src/components/ServiceCards.jsx`

### Background

`ServiceCards` is the top-level component. It holds polling state and renders the four sections. We add `knownLatest` (a `{ [containerId]: string }` map of latest semver tag) and an `onTagsLoaded` callback that `ContainerCardExpanded` will call after fetching tags.

The subtitle (`sub` prop of `InfraCard`) currently takes a string. We change it to accept either a string or `{ text, cls }` object so we can colour it amber/red.

`compareSemver` from `utils/versionCheck.js` is imported here for the first time in this file.

- [ ] **Step 1: Add imports to ServiceCards.jsx**

At the top of `gui/src/components/ServiceCards.jsx`, add to the existing import line:

```js
import { fetchContainerTags } from '../api'
import { compareSemver } from '../utils/versionCheck'
```

- [ ] **Step 2: Update `InfraCard` to support coloured subtitle**

The current `InfraCard` `sub` line is:

```jsx
{sub && <div className="text-[10px] text-[#3a3a5a] font-mono truncate mb-0.5">{sub}</div>}
```

Replace with:

```jsx
{sub && (
  typeof sub === 'object'
    ? <div className={`text-[10px] font-mono truncate mb-0.5 ${sub.cls}`}>{sub.text}</div>
    : <div className="text-[10px] text-[#3a3a5a] font-mono truncate mb-0.5">{sub}</div>
)}
```

- [ ] **Step 3: Add `knownLatest` state and `onTagsLoaded` to `ServiceCards`**

Inside `export default function ServiceCards`, add after the existing `useState` calls:

```js
const [knownLatest, setKnownLatest] = useState({})

const onTagsLoaded = useCallback((containerId, latestTag) => {
  setKnownLatest(prev => ({ ...prev, [containerId]: latestTag }))
}, [])
```

- [ ] **Step 4: Evict removed containers from `knownLatest` on load**

In the `load` callback, find this exact line (around line 531 in `ServiceCards.jsx`):

```js
if (c.status === 'fulfilled') setContainers(c.value)
```

Replace it with:

```js
if (c.status === 'fulfilled') {
  setContainers(c.value)
  const currentIds = new Set((c.value?.containers || []).map(x => x.id))
  setKnownLatest(prev =>
    Object.fromEntries(Object.entries(prev).filter(([id]) => currentIds.has(id)))
  )
}
```

- [ ] **Step 5: Add a `_computeContainerSub` helper (just above the `ServiceCards` export)**

```js
function _computeContainerSub(c, knownLatest) {
  const latestTag = knownLatest[c.id]
  if (!latestTag || !c.running_version) return c.image
  const severity = compareSemver(c.running_version, latestTag)
  const imageName = c.image.split('/').pop().split(':')[0]
  if (severity === 'major') return { text: `${imageName}: not latest`, cls: 'text-[#b04020]' }
  if (severity === 'minor' || severity === 'patch') return { text: `${imageName}: not latest`, cls: 'text-[#92601a]' }
  return c.image
}
```

- [ ] **Step 6: Use `_computeContainerSub` and pass new props in the agent-01 section**

In the `{/* Containers · agent-01 */}` section, change each `InfraCard` render:

```jsx
<InfraCard
  key={c.id} cardKey={`c-${c.id}`} openKey={openKey} setOpenKey={setOpenKey}
  dot={c.dot} name={c.name}
  sub={_computeContainerSub(c, knownLatest)}
  net={c.ip_port}
  collapsed={<ContainerCardCollapsed c={c} />}
  expanded={<ContainerCardExpanded
    c={c} isSwarm={false} onAction={load} confirm={confirm} showToast={showToast}
    onTagsLoaded={onTagsLoaded}
  />}
/>
```

- [ ] **Step 7: Verify build still compiles**

```bash
cd gui && npm run build 2>&1 | tail -5
```

Expected: no errors

- [ ] **Step 8: Commit**

```bash
git add gui/src/components/ServiceCards.jsx
git commit -m "feat(ui): add knownLatest state and subtitle version indicator for GHCR containers"
```

---

## Task 6: Frontend — ContainerCardExpanded version section + drawer

**Files:**
- Modify: `gui/src/components/ServiceCards.jsx` (`ContainerCardExpanded`)

### Background

When a container card is expanded, `ContainerCardExpanded` now:
1. Fetches tags on mount (if GHCR image)
2. Calls `onTagsLoaded(c.id, tags[0])` so `ServiceCards` can update the subtitle
3. Renders a version info section (Running, Built, Status) below the stats divider
4. Shows an amber/red "Update Available" button that toggles an inline drawer with a version `<select>` and a "Pull vX.X.X" confirm button
5. Falls back gracefully on errors

The `ContainerCardExpanded` component signature gains one new prop: `onTagsLoaded`.

**Spec deviation (intentional):** The spec says `ContainerCardExpanded` receives a `knownLatest` prop (the full map). In this plan, the expanded card does NOT receive that prop — it maintains its own local `tags` state after fetching, and calls `onTagsLoaded(id, tags[0])` to push the latest tag up to `ServiceCards`. This achieves the same result with less prop threading: `ServiceCards` still has `knownLatest` for subtitle computation; the expanded card has `tags` for the drawer. The `knownLatest` map is not needed inside the expanded card itself.

- [ ] **Step 1: Add version state to `ContainerCardExpanded`**

At the top of `function ContainerCardExpanded({ c, isSwarm, onAction, confirm, showToast, onTagsLoaded })`, add new state after the existing `useState` calls:

```js
const [tags, setTags]             = useState([])
const [tagsLoading, setTagsLoading] = useState(false)
const [tagsError, setTagsError]   = useState(null)
const [drawerOpen, setDrawerOpen] = useState(false)
const [selectedTag, setSelectedTag] = useState('')
```

- [ ] **Step 2: Add tags-fetch effect**

After the existing `useEffect(() => () => { mounted.current = false }, [])`, add:

```js
useEffect(() => {
  if (isSwarm || !c.image?.startsWith('ghcr.io/')) return
  setTagsLoading(true)
  fetchContainerTags(c.id)
    .then(data => {
      if (!mounted.current) return
      setTagsLoading(false)
      if (data.error && !data.tags?.length) {
        setTagsError(data.error)
        return
      }
      const t = data.tags || []
      setTags(t)
      setTagsError(null)
      if (t[0]) {
        setSelectedTag(t[0])
        onTagsLoaded?.(c.id, t[0])
      }
    })
    .catch(err => {
      if (!mounted.current) return
      setTagsLoading(false)
      setTagsError(err?.message || 'fetch failed')
    })
}, [c.id, c.image, isSwarm])  // eslint-disable-line react-hooks/exhaustive-deps
```

- [ ] **Step 3: Add the version section + drawer to the render**

Note: No `_stripV` helper is needed. `compareSemver` in `versionCheck.js` already normalizes both inputs (strips leading `v`) internally. The collector also already strips `v` from `running_version` before storing it.

Inside the `ContainerCardExpanded` return, after `{c.volumes?.length > 0 && <Divider />}` and before the `<Actions>` block, add the version section for GHCR containers:

```jsx
{!isSwarm && c.image?.startsWith('ghcr.io/') && (() => {
  const severity = (c.running_version && tags[0])
    ? compareSemver(c.running_version, tags[0])
    : null
  const hasUpdate = severity === 'major' || severity === 'minor' || severity === 'patch'

  return (
    <>
      <Divider />
      {/* Running version info rows */}
      {c.running_version && (
        <div className="flex justify-between text-[9px] mb-0.5">
          <span className="text-gray-700">Running</span>
          <span className="text-gray-500 font-mono">{c.running_version}</span>
        </div>
      )}
      {c.built_at && (
        <div className="flex justify-between text-[9px] mb-0.5">
          <span className="text-gray-700">Built</span>
          <span className="text-gray-500 font-mono">{c.built_at.slice(0, 10)}</span>
        </div>
      )}
      {/* Status badge */}
      <div className="flex justify-between text-[9px] mb-1.5">
        <span className="text-gray-700">Status</span>
        {tagsLoading
          ? <span className="text-gray-700">…</span>
          : tagsError
          ? <span className="text-gray-700">version check unavailable</span>
          : !tags.length
          ? <span className="text-gray-700">no versioned tags</span>
          : severity === 'current'
          ? <span className="text-[9px] px-1.5 py-px rounded bg-[#0d1f0d] text-green-400 border border-[#1a3a1a]">✓ latest</span>
          : hasUpdate
          ? <span className={`text-[9px] px-1.5 py-px rounded border ${severity === 'major' ? 'bg-[#1a0808] text-red-400 border-[#3a1010]' : 'bg-[#2a1e05] text-amber-400 border-[#3d2d0a]'}`}>
              ⬆ {tags[0]} {severity}
            </span>
          : null
        }
      </div>

      {/* Update drawer trigger — only when update available */}
      {hasUpdate && !tagsError && (
        <>
          <ActionBtn
            key="update"
            label={drawerOpen ? '✕ Cancel Update' : `⬆ Update Available — Choose Version`}
            variant={severity === 'major' ? 'urgent' : 'primary'}
            onClick={() => setDrawerOpen(o => !o)}
          />
          {drawerOpen && (
            <div className="mt-1 mb-2 bg-[#0a0a15] border border-[#2a2440] rounded-md p-2">
              <div className="text-[9px] text-gray-700 mb-1.5">Select version to pull:</div>
              <select
                className="w-full bg-[#0d0d1a] border border-[#2a2a4a] text-gray-300 rounded text-[10px] px-1.5 py-1 mb-1.5"
                value={selectedTag}
                onChange={e => setSelectedTag(e.target.value)}
              >
                {tags.map(t => (
                  <option key={t} value={t}>
                    {t}{t === c.running_version || `v${t}` === `v${c.running_version}` ? ' ← running' : ''}
                  </option>
                ))}
              </select>
              <ActionBtn
                key="pull-versioned"
                label={`↓ Pull ${selectedTag}`}
                variant="primary"
                loading={loading['pull-versioned']}
                onClick={() => {
                  act('pull-versioned', `containers/${c.id}/pull?tag=${selectedTag}`, null, null)
                  setDrawerOpen(false)
                }}
              />
            </div>
          )}
        </>
      )}

      {/* Re-pull when up to date */}
      {!hasUpdate && !tagsError && tags.length > 0 && severity === 'current' && (
        <ActionBtn
          key="repull"
          label="↓ Re-pull Image"
          loading={loading.pull}
          onClick={() => act('pull', `containers/${c.id}/pull`, null, null)}
        />
      )}

      {/* Fallback pull when version check unavailable, no tags, or severity is ahead/unknown */}
      {(tagsError || (!tagsLoading && !tags.length) || severity === 'ahead' || severity === 'unknown') && (
        <ActionBtn
          key="pull"
          label="↓ Pull Latest"
          variant={pullColor}
          loading={loading.pull}
          onClick={() => act('pull', pullPath, null, null)}
        />
      )}
    </>
  )
})()}
```

- [ ] **Step 4: For GHCR containers, remove the original `↓ Pull Latest` button**

In the `<Actions buttons={[...]} />` block, the original pull button is:

```jsx
<ActionBtn key="pull" label="↓ Pull Latest" variant={pullColor} loading={loading.pull} onClick={() => act('pull', pullPath, null, null)} />,
```

For GHCR containers this is now handled inside the version section. Wrap the pull button in a condition:

```jsx
!c.image?.startsWith('ghcr.io/') && !isSwarm && (
  <ActionBtn key="pull" label="↓ Pull Latest" variant={pullColor} loading={loading.pull} onClick={() => act('pull', pullPath, null, null)} />
),
```

- [ ] **Step 5: Build and verify**

```bash
cd gui && npm run build 2>&1 | tail -10
```

Expected: no errors

- [ ] **Step 6: Manual smoke test**

Start the dev server and open the dashboard:

```bash
cd gui && npm run dev
```

1. Open `http://localhost:5173` and log in
2. Go to the Containers · agent-01 section
3. Click the `hp1_agent` card — expanded view should show Running / Built / Status rows
4. If GHCR_TOKEN is set in the agent's env and a newer version exists: amber "Update Available" button appears
5. Click "Update Available" — version selector drawer opens, shows available tags with running version marked
6. If no update: green "✓ latest" badge and "↓ Re-pull Image" button shown

- [ ] **Step 7: Commit**

```bash
git add gui/src/components/ServiceCards.jsx
git commit -m "feat(ui): add version section and update drawer to container card expanded view"
```

---

## Task 7: Push and verify CI

- [ ] **Step 1: Push all commits**

```bash
cd D:/claude_code/FAJK/HP1-AI-Agent-v1 && git push
```

- [ ] **Step 2: Run the full backend test suite one final time**

```bash
python -m pytest tests/test_collectors_docker_agent01.py tests/test_routers_dashboard.py -v
```

Expected: all tests pass, no failures

- [ ] **Step 3: Wait for CI and confirm green**

Check GitHub Actions for the `build` workflow. Expected: green.

- [ ] **Step 4: After CI builds the new image, deploy**

```bash
# Run from ansible2
cd ~/hp1-infra && git pull && ansible-playbook playbooks/hp1_upgrade.yml
```

Expected: playbook completes, agent restarts with new image, health endpoint returns 200.
