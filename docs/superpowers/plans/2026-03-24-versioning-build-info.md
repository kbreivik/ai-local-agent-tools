# Versioning & Build Info Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `VERSION` file as the single source of truth for the app version, generate build metadata (git SHA, branch, build date, build number) in CI, expose it via `/api/health`, and show it in a hover tooltip on the SubBar version badge.

**Architecture:** A `VERSION` file at the repo root drives everything — `constants.py` reads it at import, CI writes `api/build_info.json` before building the Docker image, the Dockerfile bakes it in with a fallback stub for local builds. The backend exposes build info via `/api/health`; the React SubBar wraps the version badge in a hover tooltip component.

**Tech Stack:** Python 3.13, FastAPI, React 19 + Tailwind CSS 4, Docker (BuildKit), GitHub Actions, GHCR.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `VERSION` | Create | Single source of truth — semver string only |
| `scripts/gen_build_info.py` | Create | Writes `api/build_info.json` from git + env vars |
| `api/build_info.json` | Generated (gitignored) | Build metadata baked into Docker image |
| `api/constants.py` | Modify | Read `APP_VERSION` from `VERSION` file |
| `api/main.py` | Modify | Load build_info at startup; add to `/api/health` |
| `gui/src/App.jsx` | Modify | Replace static version badge with hover tooltip |
| `docker/Dockerfile` | Modify | Add stub fallback for `build_info.json` |
| `.gitignore` | Modify | Ignore `api/build_info.json` |
| `.github/workflows/build.yml` | Create | CI pipeline: build, tag, push to GHCR |

---

## Task 1: VERSION file + constants.py

**Files:**
- Create: `VERSION`
- Modify: `api/constants.py`

- [ ] **Step 1: Create `VERSION` file at repo root**

```
1.9.0
```

(Keep current version — no bump yet.)

- [ ] **Step 2: Update `api/constants.py` to read from `VERSION`**

Replace:
```python
APP_VERSION = "1.9.0"
```
With:
```python
from pathlib import Path as _Path

def _read_version() -> str:
    try:
        return _Path(__file__).parent.parent.joinpath("VERSION").read_text().strip()
    except OSError:
        import logging as _logging
        _logging.getLogger(__name__).warning("VERSION file not found — defaulting to 'unknown'")
        return "unknown"

APP_VERSION = _read_version()
```

- [ ] **Step 3: Verify app still starts**

```bash
cd /path/to/HP1-AI-Agent-v1
python -c "from api.constants import APP_VERSION; print(APP_VERSION)"
```

Expected: `1.9.0`

- [ ] **Step 4: Commit**

```bash
git add VERSION api/constants.py
git commit -m "feat(version): add VERSION file as single source of truth"
git push
```

---

## Task 2: gen_build_info.py script

**Files:**
- Create: `scripts/gen_build_info.py`

- [ ] **Step 1: Create `scripts/` directory if absent**

```bash
mkdir -p scripts
```

- [ ] **Step 2: Write `scripts/gen_build_info.py`**

```python
#!/usr/bin/env python3
"""Generate api/build_info.json from git metadata and CI environment variables.

Run before `docker build` or locally:
    python scripts/gen_build_info.py

Outputs api/build_info.json with: version, commit, branch, built_at, build_number.
All git/env failures fall back to "unknown". Script always exits 0.
"""
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
VERSION_FILE = REPO_ROOT / "VERSION"
OUTPUT_FILE = REPO_ROOT / "api" / "build_info.json"


def _run_git(*args) -> str:
    """Run a git command and return stdout. Returns 'unknown' on any failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True, text=True, check=True, cwd=REPO_ROOT
        )
        return result.stdout.strip() or "unknown"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _get_branch() -> str:
    """Get branch name. Falls back to GITHUB_REF_NAME on detached HEAD."""
    branch = _run_git("rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":
        # Detached HEAD — happens on tag pushes in CI
        branch = os.environ.get("GITHUB_REF_NAME", "unknown")
    return branch


def main():
    version = "unknown"
    try:
        version = VERSION_FILE.read_text().strip()
    except OSError:
        pass

    build_info = {
        "version": version,
        "commit": _run_git("rev-parse", "--short", "HEAD"),
        "branch": _get_branch(),
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "build_number": os.environ.get("GITHUB_RUN_NUMBER", "local"),
    }

    OUTPUT_FILE.write_text(json.dumps(build_info, indent=2))
    print(f"Written: {OUTPUT_FILE}")
    print(json.dumps(build_info, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the script locally and verify output**

```bash
python scripts/gen_build_info.py
cat api/build_info.json
```

Expected: JSON with `version`, `commit` (7-char sha), `branch`, `built_at`, `build_number: "local"`.

- [ ] **Step 4: Add `api/build_info.json` to `.gitignore`**

Append to `.gitignore`:
```
api/build_info.json
```

- [ ] **Step 5: Commit**

```bash
git add scripts/gen_build_info.py .gitignore
git commit -m "feat(version): add gen_build_info.py script"
git push
```

---

## Task 3: Backend — load build_info + extend /api/health

**Files:**
- Modify: `api/main.py` (health endpoint at line ~167, lifespan at line ~53)

- [ ] **Step 1: Add build_info loader to `api/main.py`**

After the existing imports (around line 30), add:

```python
import json as _json

def _load_build_info() -> dict | None:
    """Load api/build_info.json if present. Returns None if absent.

    In the container: main.py is at /app/api/main.py and build_info.json
    is at /app/api/build_info.json — so Path(__file__).parent is correct.
    Locally: same relative layout (api/main.py → api/build_info.json).
    """
    path = Path(__file__).parent / "build_info.json"
    try:
        return _json.loads(path.read_text())
    except (OSError, _json.JSONDecodeError):
        return None

_BUILD_INFO = _load_build_info()
```

- [ ] **Step 2: Add startup log in the lifespan handler**

Inside the `lifespan` context manager, after `await init_db()`, add:

```python
import logging as _logging
_log = _logging.getLogger(__name__)
if _BUILD_INFO:
    _log.info("Build info: v%s commit=%s branch=%s build=#%s",
              _BUILD_INFO.get("version"), _BUILD_INFO.get("commit"),
              _BUILD_INFO.get("branch"), _BUILD_INFO.get("build_number"))
else:
    _log.warning("build_info.json not found — run scripts/gen_build_info.py before docker build")
```

- [ ] **Step 3: Extend the `/api/health` endpoint**

Find the health endpoint (line ~167):
```python
@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "service": APP_NAME,
        "version": APP_VERSION,
        "deploy_mode": os.environ.get("HP1_DEPLOY_MODE", "bare-metal"),
        "ws_clients": manager.active_count,
        "network": _get_host_ips(),
    }
```

Replace with:
```python
@app.get("/api/health")
async def health():
    response = {
        "status": "ok",
        "service": APP_NAME,
        "version": APP_VERSION,
        "deploy_mode": os.environ.get("HP1_DEPLOY_MODE", "bare-metal"),
        "ws_clients": manager.active_count,
        "network": _get_host_ips(),
    }
    if _BUILD_INFO:
        response["build_info"] = {k: v for k, v in _BUILD_INFO.items() if k != "version"}
    return response
```

- [ ] **Step 4: Verify health endpoint response**

```bash
python -c "
import asyncio, httpx
async def check():
    async with httpx.AsyncClient() as c:
        r = await c.get('http://localhost:8000/api/health')
        import json; print(json.dumps(r.json(), indent=2))
asyncio.run(check())
"
```

Expected: response includes `build_info` with `commit`, `branch`, `built_at`, `build_number` (no `version` key inside `build_info`).

- [ ] **Step 5: Commit**

```bash
git add api/main.py
git commit -m "feat(version): expose build_info in /api/health endpoint"
git push
```

---

## Task 4: Frontend — version badge hover tooltip

**Files:**
- Modify: `gui/src/App.jsx` (version badge at line ~305)

- [ ] **Step 1: Locate the current version badge in `App.jsx`**

Find (around line 305):
```jsx
{health?.version && (
  <div className="flex items-center px-3 border-l border-gray-200 h-8">
    <span className="text-gray-400 text-xs font-mono">v{health.version}</span>
  </div>
)}
```

- [ ] **Step 2: Replace the entire block identified in Step 1 with the tooltip component below**

Delete the old block and insert:
```jsx
{health?.version && (
  <div className="relative flex items-center px-3 border-l border-gray-200 h-8 group">
    <span className="text-gray-400 text-xs font-mono cursor-default select-none">
      v{health.version}
    </span>
    {health?.build_info && (
      <div className="absolute right-0 top-full mt-1.5 z-50 hidden group-hover:block">
        <div className="bg-slate-800 border border-slate-700 rounded px-2.5 py-2 w-[210px] shadow-lg">
          <div className="grid gap-x-3 gap-y-0.5" style={{ gridTemplateColumns: 'auto 1fr' }}>
            <span className="text-slate-500 text-xs">commit</span>
            <span className="font-mono text-indigo-300 text-xs">{health.build_info.commit}</span>
            <span className="text-slate-500 text-xs">branch</span>
            <span className="font-mono text-emerald-400 text-xs">{health.build_info.branch}</span>
            <span className="text-slate-500 text-xs">built</span>
            <span className="font-mono text-slate-200 text-xs">
              {health.build_info.built_at !== 'unknown'
                ? health.build_info.built_at.replace('T', ' ').replace('Z', ' UTC')
                : 'unknown'}
            </span>
            <span className="text-slate-500 text-xs">build</span>
            <span className="font-mono text-slate-200 text-xs">
              {health.build_info.build_number === 'local'
                ? 'local'
                : `#${health.build_info.build_number}`}
            </span>
          </div>
        </div>
      </div>
    )}
  </div>
)}
```

- [ ] **Step 3: Test in browser**

Start dev server:
```bash
cd gui && npm run dev
```

Open `http://localhost:5173`, hover over the version badge in the SubBar.

Expected: tooltip appears with commit (indigo), branch (green), built (white), build (white). If `build_info` is absent (no JSON file), no tooltip, badge still shows.

- [ ] **Step 4: Commit**

```bash
git add gui/src/App.jsx
git commit -m "feat(version): add hover tooltip to SubBar version badge"
git push
```

---

## Task 5: Dockerfile — build_info.json fallback stub

**Files:**
- Modify: `docker/Dockerfile`

- [ ] **Step 1: Add stub fallback after `COPY . .` in the runtime stage**

In `docker/Dockerfile`, find the line `COPY . .` in the final runtime stage (around line 46). After it, add:

```dockerfile
# Generate build_info.json stub if not present in build context (local builds without CI)
RUN if [ ! -f api/build_info.json ]; then \
      python -c "import json; json.dump( \
        {'version': open('VERSION').read().strip(), \
         'commit':'unknown','branch':'unknown', \
         'built_at':'unknown','build_number':'unknown'}, \
        open('api/build_info.json','w'))"; \
    fi
```

Note: `WORKDIR` at this point is `/app`. `VERSION` and `api/` are both under `/app` from `COPY . .`.

- [ ] **Step 2: Test local Docker build**

```bash
# Build without running gen_build_info.py first (should use stub)
docker build -f docker/Dockerfile -t hp1-ai-agent:local-test .
docker run --rm hp1-ai-agent:local-test cat /app/api/build_info.json
```

Expected: JSON with `version` from `VERSION` file, all other fields `"unknown"`.

- [ ] **Step 3: Test local Docker build with gen_build_info.py**

```bash
python scripts/gen_build_info.py
docker build -f docker/Dockerfile -t hp1-ai-agent:local-test .
docker run --rm hp1-ai-agent:local-test cat /app/api/build_info.json
```

Expected: JSON with real git SHA, branch, `build_number: "local"`.

- [ ] **Step 4: Commit**

```bash
git add docker/Dockerfile
git commit -m "feat(version): add build_info.json stub fallback in Dockerfile"
git push
```

---

## Task 6: GitHub Actions CI workflow

**Files:**
- Create: `.github/workflows/build.yml`

- [ ] **Step 1: Create `.github/workflows/` directory if absent and verify GITHUB_TOKEN has packages:write**

```bash
mkdir -p .github/workflows
```

In the GitHub repo settings → Actions → General, ensure "Read and write permissions" is enabled for `GITHUB_TOKEN` (required for GHCR push).

- [ ] **Step 2: Write `.github/workflows/build.yml`**

```yaml
name: Build & Push

on:
  push:
    branches: [main]
    tags: ['v*']

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ghcr.io/kbreivik/hp1-ai-agent

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0   # full history — needed for branch name on tag pushes

      - name: Read VERSION
        id: version
        run: echo "version=$(cat VERSION)" >> $GITHUB_OUTPUT

      - name: Set image tag
        id: tag
        run: |
          SHORT_SHA=$(git rev-parse --short HEAD)
          VERSION=$(cat VERSION)
          echo "image_tag=${{ env.IMAGE_NAME }}:${VERSION}-${SHORT_SHA}" >> $GITHUB_OUTPUT
          echo "version_tag=${{ env.IMAGE_NAME }}:${VERSION}" >> $GITHUB_OUTPUT

      - name: Sync package.json version
        run: |
          jq --arg v "$(cat VERSION)" '.version = $v' gui/package.json > /tmp/pkg.json
          mv /tmp/pkg.json gui/package.json

      - name: Generate build_info.json
        run: python scripts/gen_build_info.py

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          file: docker/Dockerfile
          push: true
          tags: |
            ${{ steps.tag.outputs.image_tag }}
            ${{ steps.tag.outputs.version_tag }}
          labels: |
            org.opencontainers.image.version=${{ steps.version.outputs.version }}
            org.opencontainers.image.revision=${{ github.sha }}
            org.opencontainers.image.created=${{ github.event.head_commit.timestamp }}

      - name: Output image tag
        run: echo "image_tag=${{ steps.tag.outputs.image_tag }}" >> $GITHUB_OUTPUT
        id: output
```

- [ ] **Step 3: Verify the workflow file is valid YAML**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/build.yml'))" && echo "YAML OK"
```

Expected: `YAML OK`

- [ ] **Step 4: Commit and push — CI will trigger**

```bash
git add .github/workflows/build.yml
git commit -m "feat(ci): add GitHub Actions build and push workflow"
git push
```

- [ ] **Step 5: Monitor the CI run**

Open `https://github.com/kbreivik/ai-local-agent-tools/actions` — the "Build & Push" workflow should appear and run. Watch each step complete: checkout → read VERSION → set tag → sync package.json → gen_build_info → login → build-push.

- [ ] **Step 6: Confirm image published to GHCR**

Open `https://github.com/kbreivik?tab=packages` and verify `hp1-ai-agent` package is listed with the new tags (`{version}-{sha}` and `{version}`).

---

## Task 7: End-to-end verification

- [ ] **Step 1: Pull the CI-built image and inspect build_info**

```bash
docker pull ghcr.io/kbreivik/hp1-ai-agent:<version>-<sha>
docker run --rm ghcr.io/kbreivik/hp1-ai-agent:<version>-<sha> cat /app/api/build_info.json
```

Expected: real commit SHA, branch `main`, UTC timestamp, numeric build number (not `"local"`).

- [ ] **Step 2: Confirm OCI labels on the image**

```bash
docker inspect ghcr.io/kbreivik/hp1-ai-agent:<version>-<sha> | python -c "
import json, sys
data = json.load(sys.stdin)
labels = data[0]['Config']['Labels']
for k, v in labels.items():
    if 'opencontainers' in k:
        print(k, '=', v)
"
```

Expected: `image.version`, `image.revision`, `image.created` all populated.

- [ ] **Step 3: Start the agent and check the health endpoint**

```bash
curl -s http://localhost:8000/api/health | python -m json.tool
```

Expected: response contains `build_info` with `commit`, `branch`, `built_at`, `build_number` — no `version` key inside `build_info`.

- [ ] **Step 4: Check tooltip in browser**

Open the dashboard, hover over the version badge in the SubBar.

Expected:
```
commit   <sha>        ← indigo
branch   main         ← green
built    2026-03-24 06:15 UTC
build    #142
```

- [ ] **Step 5: Final commit if any fixes needed**

```bash
git add -p
git commit -m "fix(version): <description of any fixes>"
git push
```
