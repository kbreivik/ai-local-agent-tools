# Build-Number Version Check — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the "new version available" indicator fire when a new CI build is published even if the semver version hasn't changed, by including the build number in the image tag and extending the comparison logic.

**Architecture:** CI tags images as `{version}-{buildnum}-{sha}` (e.g. `1.10.1-24-5ccd951`). Frontend adds `parseBuildNum()` and `compareBuildTag()` to `versionCheck.js` — when semver parts are equal it falls through to compare build numbers. `ServiceCards._computeContainerSub` switches from `compareSemver` to `compareBuildTag`.

**Tech Stack:** GitHub Actions, React 19 + Vite. No test framework — `npm run build` is the verification gate.

---

## File Map

| File | Change |
|---|---|
| `.github/workflows/build.yml` | Add `github.run_number` to the SHA-suffixed image tag |
| `gui/src/utils/versionCheck.js` | Add `parseBuildNum()` + export `compareBuildTag()` |
| `gui/src/components/ServiceCards.jsx` | Import `compareBuildTag`, use in `_computeContainerSub` |

---

## Task 1 — Add build number to CI image tag

**File:** `.github/workflows/build.yml`

### Context

Current tag step (lines ~32–37):
```yaml
- name: Set image tag
  id: tag
  run: |
    SHORT_SHA=$(git rev-parse --short HEAD)
    VERSION=$(cat VERSION)
    echo "image_tag=${{ env.IMAGE_NAME }}:${VERSION}-${SHORT_SHA}" >> $GITHUB_OUTPUT
    echo "version_tag=${{ env.IMAGE_NAME }}:${VERSION}" >> $GITHUB_OUTPUT
    echo "latest_tag=${{ env.IMAGE_NAME }}:latest" >> $GITHUB_OUTPUT
```

`image_tag` currently produces `1.10.1-5ccd951`. We want `1.10.1-24-5ccd951` (build number between version and sha).

### Steps

- [ ] **Step 1: Add build number to image_tag**

Replace the `Set image tag` step `run:` block with:

```yaml
    SHORT_SHA=$(git rev-parse --short HEAD)
    VERSION=$(cat VERSION)
    BUILD_NUM=${{ github.run_number }}
    echo "image_tag=${{ env.IMAGE_NAME }}:${VERSION}-${BUILD_NUM}-${SHORT_SHA}" >> $GITHUB_OUTPUT
    echo "version_tag=${{ env.IMAGE_NAME }}:${VERSION}" >> $GITHUB_OUTPUT
    echo "latest_tag=${{ env.IMAGE_NAME }}:latest" >> $GITHUB_OUTPUT
```

The `version_tag` (e.g. `1.10.1`) and `latest_tag` are unchanged — those still get pushed. Only the unique per-build tag gains the build number.

- [ ] **Step 2: Commit**

```bash
cd D:/claude_code/FAJK/HP1-AI-Agent-v1/.worktrees/build-tag-version
git add .github/workflows/build.yml
git commit -m "feat(ci): include build number in image tag (version-buildnum-sha)"
```

---

## Task 2 — Add compareBuildTag to versionCheck.js

**File:** `D:/claude_code/FAJK/HP1-AI-Agent-v1/.worktrees/build-tag-version/gui/src/utils/versionCheck.js`

### Context

Current `compareSemver` parses 3 semver parts only. Tags like `1.10.1-24-5ccd951` parse as `[1, 10, 1]` — the build number suffix is ignored, so same-version different-build tags compare as `'current'`.

New logic: if semver parts are equal AND both tags contain a build number in `{version}-{buildnum}-{sha}` format, compare build numbers. Result `'patch'` means "newer build available" (reuses existing yellow `⬆` badge path).

### Steps

- [ ] **Step 1: Add parseBuildNum and compareBuildTag to versionCheck.js**

After the closing `}` of `compareSemver` (line 87), append:

```js
/**
 * Extract the build number from a "{major}.{minor}.{patch}-{buildnum}-{sha}" tag.
 * Returns the build number as an integer, or null if the tag doesn't match.
 */
function parseBuildNum(tag) {
  if (!tag) return null
  const m = tag.match(/^\d+\.\d+\.\d+-(\d+)-[0-9a-f]+$/)
  return m ? parseInt(m[1], 10) : null
}

/**
 * Like compareSemver but also detects newer builds when version parts are equal.
 * If both tags are in "{version}-{buildnum}-{sha}" format and versions are equal,
 * a higher build number returns 'patch' (shown as yellow ⬆ badge).
 */
export function compareBuildTag(current, latest) {
  const base = compareSemver(current, latest)
  if (base !== 'current') return base

  const curBuild = parseBuildNum(current)
  const latBuild = parseBuildNum(latest)
  if (curBuild === null || latBuild === null) return 'current'
  if (latBuild > curBuild) return 'patch'
  if (latBuild < curBuild) return 'ahead'
  return 'current'
}
```

- [ ] **Step 2: Verify build**

```bash
cd D:/claude_code/FAJK/HP1-AI-Agent-v1/.worktrees/build-tag-version/gui && npm run build
```

Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
cd D:/claude_code/FAJK/HP1-AI-Agent-v1/.worktrees/build-tag-version
git add gui/src/utils/versionCheck.js
git commit -m "feat(versioncheck): add compareBuildTag to detect newer builds at same semver"
```

---

## Task 3 — Use compareBuildTag in ServiceCards

**File:** `D:/claude_code/FAJK/HP1-AI-Agent-v1/.worktrees/build-tag-version/gui/src/components/ServiceCards.jsx`

### Context

Line 13 currently imports only `compareSemver`:
```js
import { compareSemver } from '../utils/versionCheck'
```

`_computeContainerSub` (line ~666) calls `compareSemver(c.running_version, latestTag)`. When the running tag is `1.10.1-23-5ccd951` and the latest is `1.10.1-24-abcdef`, `compareSemver` returns `'current'` — no badge. `compareBuildTag` returns `'patch'` — yellow ⬆ badge.

### Steps

- [ ] **Step 1: Update the import**

Change line 13 from:
```js
import { compareSemver } from '../utils/versionCheck'
```
to:
```js
import { compareSemver, compareBuildTag } from '../utils/versionCheck'
```

- [ ] **Step 2: Update _computeContainerSub to use compareBuildTag**

Find `_computeContainerSub` (line ~666). It contains:
```js
const severity = compareSemver(c.running_version, latestTag)
```
Change to:
```js
const severity = compareBuildTag(c.running_version, latestTag)
```

- [ ] **Step 3: Verify build**

```bash
cd D:/claude_code/FAJK/HP1-AI-Agent-v1/.worktrees/build-tag-version/gui && npm run build
```

Expected: 0 errors.

- [ ] **Step 4: Commit**

```bash
cd D:/claude_code/FAJK/HP1-AI-Agent-v1/.worktrees/build-tag-version
git add gui/src/components/ServiceCards.jsx
git commit -m "feat(servicecards): use compareBuildTag to detect newer builds at same semver"
```

---

## Result

After deploy:
- CI tags each build as `1.10.1-{run_number}-{sha}`, e.g. `1.10.1-25-abc1234`
- Running container has tag `1.10.1-24-5ccd951`
- Next merge triggers build #25 → new tag `1.10.1-25-xyz`
- `compareBuildTag('1.10.1-24-5ccd951', '1.10.1-25-xyz')` → `'patch'` → yellow ⬆ badge appears
