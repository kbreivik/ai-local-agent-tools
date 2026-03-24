# Versioning & Build Info Design

**Date:** 2026-03-24
**Status:** Approved

## Summary

Add a single `VERSION` file as the source of truth for the app version. GitHub Actions generates `build_info.json` at build time containing git SHA, branch, build date, and run number. The backend exposes this via `/api/health`. The frontend SubBar version badge shows a hover tooltip (aligned grid, monospace values) with all build metadata.

---

## Architecture

```
VERSION                          ← "1.10.0" — only file a human edits
api/build_info.json              ← written by CI, baked into image (gitignored)
scripts/gen_build_info.py        ← writes build_info.json, runnable locally or in CI
api/constants.py                 ← reads VERSION at import time
gui/package.json                 ← version field updated by CI step before build
.github/workflows/build.yml      ← on push to main + on tag
```

**Data flow:**
1. Developer edits `VERSION` → commits → pushes to main
2. GitHub Actions reads `VERSION`, runs `gen_build_info.py`, builds Docker image with OCI labels, tags `ghcr.io/kbreivik/hp1-ai-agent:{version}-{short_sha}`
3. CI writes the final image tag to `$GITHUB_OUTPUT` for downstream Ansible consumption
4. Backend reads `build_info.json` at startup → exposes via `/api/health`
5. Frontend polls `/api/health` → SubBar shows badge + hover tooltip

---

## Components

### 1. `VERSION` (new file, repo root)

Plain text file containing only the semver string:
```
1.10.0
```

### 2. `api/build_info.json` (new file, generated — gitignored)

Written by `scripts/gen_build_info.py` during CI or locally. Schema:
```json
{
  "version": "1.10.0",
  "commit": "abc1234",
  "branch": "main",
  "built_at": "2026-03-24T06:15:00Z",
  "build_number": "142"
}
```

- `build_number` is always a string (`"142"`, `"local"`) — treat as opaque/display-only
- `branch` and `commit` fall back to `"unknown"` if git is unavailable
- The `version` field is **always written** to `build_info.json`. It is stripped only from the `/api/health` `build_info` sub-key (version already appears at the top level of the health response). The file on disk always contains it.

**Local build ordering:** Run `python scripts/gen_build_info.py` before `docker build`. `VERSION` lives at the repo root and is included in the Docker build context by the existing `COPY . .` directive (`WORKDIR /app`). `api/build_info.json` is picked up the same way if present. If absent, the Dockerfile generates a stub (see Component 9).

### 3. `scripts/gen_build_info.py` (new file)

Reads `VERSION`, queries git for SHA and branch, reads `GITHUB_RUN_NUMBER` env var, writes `api/build_info.json`. No arguments needed.

**Git failure handling:** All git subprocess calls are wrapped in try/except. `subprocess.CalledProcessError` and `FileNotFoundError` both fall back to `"unknown"`. The script always exits with code 0 — it never fails the CI step; a missing git binary produces a valid stub file.

**Detached HEAD on tag push:** When `git rev-parse --abbrev-ref HEAD` returns `"HEAD"` (detached), the script reads `GITHUB_REF_NAME` env var instead. On a tag-triggered run this will be the tag name (e.g., `v1.10.0`), not a branch name — the `branch` field in the tooltip will display the tag string in that case. This is expected and acceptable.

### 4. `api/constants.py` (modified)

```python
# Before
APP_VERSION = "1.9.0"

# After
APP_VERSION = Path(__file__).parent.parent.joinpath("VERSION").read_text().strip()
```

**In-container path:** The Dockerfile uses `WORKDIR /app` and `COPY . .`, placing `constants.py` at `/app/api/constants.py` and `VERSION` at `/app/VERSION`. The `parent.parent` traversal (`/app/api` → `/app`) resolves correctly.

A startup check in the FastAPI lifespan handler logs a warning and falls back to `"unknown"` if the file is missing.

### 5. `/api/health` endpoint (modified)

The key is **omitted entirely** (not set to null) when `build_info.json` does not exist:

```python
response = {"status": "ok", "version": APP_VERSION}
if build_info:  # only set when build_info.json loaded successfully
    response["build_info"] = {k: v for k, v in build_info.items() if k != "version"}
```

Response with build info:
```json
{
  "status": "ok",
  "version": "1.10.0",
  "build_info": {
    "commit": "abc1234",
    "branch": "main",
    "built_at": "2026-03-24T06:15:00Z",
    "build_number": "142"
  }
}
```

Response without (dev / local build without gen script):
```json
{
  "status": "ok",
  "version": "1.10.0"
}
```

### 6. `gui/src/App.jsx` — SubBar version badge (modified)

Replace the static `v{health.version}` badge with a component that shows a tooltip on hover. Tooltip only renders if `"build_info" in health`.

Tooltip layout (aligned grid, monospace values):
```
commit   abc1234
branch   main
built    2026-03-24 06:15 UTC
build    #142
```

Styles:
- Container: `bg-slate-800 border border-slate-700 rounded`, `w-[210px]`, `p-2`
- Labels: `text-slate-500 text-xs`, left column
- Values: `font-mono text-slate-200 text-xs`, right column
- `branch` value: `text-emerald-400`
- `commit` value: `text-indigo-300`
- Positioning: `absolute right-0 top-full mt-1.5` — anchored to the right edge of the badge, opens downward. Right-aligned prevents viewport overflow since the badge is always in the top-right of the SubBar.
- `built_at` display: the frontend formats the ISO 8601 value from `build_info.built_at` (e.g., `"2026-03-24T06:15:00Z"`) into `"2026-03-24 06:15 UTC"` — parsing and reformatting is the frontend's responsibility.

### 7. `gui/package.json` version sync (CI step)

Before the Docker build, CI runs:
```bash
jq --arg v "$(cat VERSION)" '.version = $v' gui/package.json > /tmp/pkg.json && mv /tmp/pkg.json gui/package.json
```

`jq` is pre-installed on GitHub Actions `ubuntu-latest` runners. This only affects the Docker build context — no commit is made.

### 8. `.github/workflows/build.yml` (new file)

Triggers on push to `main` and on version tags (`v*`).

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0   # full history — needed for branch name on tag pushes
```

Steps:
1. Checkout (`fetch-depth: 0` for correct branch detection)
2. Read `VERSION` → set `IMAGE_TAG=ghcr.io/kbreivik/hp1-ai-agent:{version}-{short_sha}`
3. Sync `gui/package.json` version from `VERSION`
4. Run `python scripts/gen_build_info.py`
5. Build Docker image with OCI labels (below) + tag `$IMAGE_TAG`
6. Push to `ghcr.io/kbreivik/hp1-ai-agent`
7. Write `image_tag=$IMAGE_TAG` to `$GITHUB_OUTPUT`

OCI labels (added to the existing set already in the Dockerfile):
```
org.opencontainers.image.version    ← from VERSION
org.opencontainers.image.revision   ← git SHA
org.opencontainers.image.created    ← UTC timestamp
```

Note: `org.opencontainers.image.source` is already set statically in the Dockerfile as `https://github.com/kbreivik/ai-local-agent-tools` — no change needed.

**Ansible deployment:** The CI output `image_tag` is consumed by the Ansible deployment trigger (manual or webhook). `swarm-stack.yml` uses `${HP1_IMAGE}` which Ansible sets from the CI output. No commit-back to the repo.

### 9. `docker/Dockerfile` (modified)

The existing `COPY . .` already handles `api/build_info.json` when present in the build context. Add a `RUN` fallback after the copy to generate a stub if absent:

```dockerfile
# Fallback: generate stub build_info.json if not present in build context
RUN if [ ! -f api/build_info.json ]; then \
      python -c "import json; json.dump( \
        {'version': open('VERSION').read().strip(), \
         'commit':'unknown','branch':'unknown', \
         'built_at':'unknown','build_number':'unknown'}, \
        open('api/build_info.json','w'))"; \
    fi
```

WORKDIR at this point is `/app`, so `api/build_info.json` resolves to `/app/api/build_info.json` and `VERSION` resolves to `/app/VERSION` — both correct.

### 10. `.gitignore` (modified)

Add:
```
api/build_info.json
```

---

## Error Handling

| Condition | Behaviour |
|-----------|-----------|
| `VERSION` missing | `constants.py` logs warning, falls back to `"unknown"`; FastAPI lifespan emits startup warning |
| `build_info.json` missing at runtime | `/api/health` omits `build_info` key entirely; frontend hides tooltip |
| `gen_build_info.py` run without git | Catches `CalledProcessError`/`FileNotFoundError`, falls back to `"unknown"`, exits 0 |
| Detached HEAD (tag push in CI) | Script reads `GITHUB_REF_NAME` env var as the branch/tag name |
| CI env vars missing (local run) | `build_number` set to `"local"` |

---

## Out of Scope

- Auto-bumping `VERSION` via semantic-release (future work)
- Showing build info in agent logs or CLI
- Version history or changelog endpoint
