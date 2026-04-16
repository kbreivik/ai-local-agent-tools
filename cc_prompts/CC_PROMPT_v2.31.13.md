# CC PROMPT — v2.31.13 — fix(ci): unbreak CI — lockfile sync + workflow version step + undo v2.31.12 mistakes

## What this does
CI has been failing since v2.31.11 and nothing has published new images. Two
real bugs and one self-inflicted one from v2.31.12:

1. **v2.31.11 added test deps to `gui/package.json`** (`vitest`,
   `@testing-library/react`, `@testing-library/jest-dom`, `jsdom`) without
   running `npm install` to update `gui/package-lock.json`. `npm ci` in the
   Docker build then fails because the lockfile has no entries for the new
   deps.
2. **Workflow's "Sync package.json version" step** mutates
   `gui/package.json.version` from `1.10.8` to the VERSION value (e.g.
   `2.31.13`) but leaves `gui/package-lock.json.version` at `1.10.8`.
   `npm ci` refuses to proceed when these disagree. This has been latent
   since the sync step was added — it only started biting now because the
   other bug above also reached `npm ci`.
3. **v2.31.12 added a duplicate Dockerfile at repo root** and a wrong
   `Step 5.5` in `cc_prompts/QUEUE_RUNNER.md` telling CC to build and push
   locally. The real build mechanism is `.github/workflows/build.yml`
   which references `docker/Dockerfile`. The root duplicate and the
   queue-runner step are dead code and need to go.

Five changes, all small.

---

## Change 1 — regenerate `gui/package-lock.json`

Run npm install in `gui/` on the dev machine to rewrite the lockfile with
entries for the new test deps.

```bash
cd D:\claude_code\ai-local-agent-tools\gui
npm install
```

This updates `package-lock.json` in-place to include `vitest`,
`@testing-library/react`, `@testing-library/jest-dom`, `jsdom`, and all
their transitive deps. No changes to `package.json` expected — only the
lockfile grows.

Verify:
```bash
grep -c '"vitest"' package-lock.json    # > 0
grep -c '"jsdom"'  package-lock.json    # > 0
```

If either returns `0`, re-check: you may need to delete `node_modules/` first
or explicitly run `npm install vitest @testing-library/react @testing-library/jest-dom jsdom`.

---

## Change 2 — fix the "Sync package.json version" step in `.github/workflows/build.yml`

Open `.github/workflows/build.yml`. Find this step:

```yaml
      - name: Sync package.json version
        run: |
          jq --arg v "$(cat VERSION)" '.version = $v' gui/package.json > /tmp/pkg.json
          mv /tmp/pkg.json gui/package.json
```

Replace with:

```yaml
      - name: Sync package.json + lockfile version
        working-directory: gui
        run: |
          VER="$(cat ../VERSION)"
          # npm version updates BOTH package.json and package-lock.json atomically.
          # --no-git-tag-version prevents it from making a commit/tag.
          # --allow-same-version lets it succeed if already at target (idempotent).
          npm version --no-git-tag-version --allow-same-version "$VER"
```

Why this matters: `npm ci` refuses when `package.json.version` ≠
`package-lock.json.version`. The previous `jq` approach touched only
`package.json`, causing the mismatch. `npm version` updates both in one shot.

---

## Change 3 — delete the duplicate `Dockerfile` at repo root

```bash
cd D:\claude_code\ai-local-agent-tools
git rm Dockerfile
```

The canonical Dockerfile is `docker/Dockerfile` — that's what the workflow
uses (`file: docker/Dockerfile`). The root duplicate was a v2.31.12 mistake
and serves no purpose.

Leave `.dockerignore` in place — it applies to the build context and is
useful regardless of which Dockerfile is picked.
Leave `.gitattributes` in place — LF enforcement on `*.sh` is still wanted.

---

## Change 4 — revert QUEUE_RUNNER.md Step 5.5

Open `cc_prompts/QUEUE_RUNNER.md`. Find the `### Step 5.5 — Build and push
Docker image` section (added in v2.31.12) and remove it entirely — from the
`### Step 5.5` header down to and not including the `### Step 6 — Mark DONE
in INDEX.md` header. After removal the file should read:

```markdown
(... Step 5 unchanged ...)

### Step 6 — Mark DONE in INDEX.md
(... unchanged ...)
```

Reason: CC should NOT build and push locally. The GitHub Actions workflow
builds and pushes on every push to `main`. Having CC do it from the dev
machine would duplicate work at best and (without Docker Desktop + GHCR
login on the dev machine) fail every prompt at worst.

---

## Change 5 — verify the first-build clause in v2.31.12 prompt is inert

The v2.31.12 prompt also told CC to run a one-time docker build at the end.
CC was smart enough to skip or fail on that without breaking the commit —
but if anything like a `d2l/` or dangling partial-build directory was left
in the workspace, remove it:

```bash
cd D:\claude_code\ai-local-agent-tools
git status --porcelain | head -20
```

If anything unexpected shows up (e.g. accidentally-committed build outputs),
`git clean -fd` them before committing v2.31.13. Untracked build artefacts
should not enter the commit.

---

## Commit

```
git add -A
git commit -m "fix(ci): v2.31.13 unbreak CI — lockfile sync + workflow version step + undo duplicates"
git push origin main
```

Pushing this commit triggers `build.yml`. Watch the resulting run at:
https://github.com/kbreivik/ai-local-agent-tools/actions

---

## How to test

1. **GitHub Actions run goes green** — the push should trigger build #553+.
   Expected duration: 2-3 minutes (real build time, not a 20-second early
   failure). Expected outcome: `Build and push` step succeeds, produces
   three tags:
   - `ghcr.io/kbreivik/hp1-ai-agent:2.31.13`
   - `ghcr.io/kbreivik/hp1-ai-agent:2.31.13-<buildnum>-<sha>`
   - `ghcr.io/kbreivik/hp1-ai-agent:latest`

2. **Pull and verify on agent-01**:
   ```bash
   docker pull ghcr.io/kbreivik/hp1-ai-agent:2.31.13
   docker pull ghcr.io/kbreivik/hp1-ai-agent:latest
   docker inspect --format '{{index .RepoDigests 0}}' ghcr.io/kbreivik/hp1-ai-agent:2.31.13
   docker inspect --format '{{index .RepoDigests 0}}' ghcr.io/kbreivik/hp1-ai-agent:latest
   # Same digest — confirms :latest is the same image as :2.31.13
   ```

3. **Deploy**:
   ```bash
   cd /opt/hp1-agent/docker
   docker compose pull hp1_agent
   docker compose up -d hp1_agent
   sleep 8
   curl -s http://192.168.199.10:8000/api/health | python3 -m json.tool | head -8
   # Expect: "version": "2.31.13"
   ```

4. **Walk through the stacked changes** (v2.31.3 through v2.31.11 are all now
   live because the image snapshot includes them all):

   - **v2.31.3 live output** — hard-refresh UI, DevTools Network WS should
     show `ws://.../ws/output` (no `?token=`), status 101. Run an observe
     task, Output panel streams.
   - **v2.31.6 Recent Actions tab** — Logs → Actions has rows.
   - **v2.31.8 caps** —
     `docker exec hp1_agent python -c "from api.routers.agent import _AGENT_MAX_WALL_CLOCK_S; print(_AGENT_MAX_WALL_CLOCK_S)"` → `600`.
   - **v2.31.10 blackouts** —
     `curl -s -b /tmp/hp1.cookies http://192.168.199.10:8000/api/agent/blackouts` → `{"blackouts": []}`.
   - **v2.31.11 regression tests** —
     `docker exec -w /app hp1_agent python -m pytest tests/test_tool_safety.py -v` → all pass.

5. **Subsequent prompts auto-build via CI, no local docker needed**.

---

## Notes

- The `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24` env var in the workflow is a
  temporary GitHub deprecation shim — leave it alone.
- If Change 1 leaves the lockfile with a very large diff (>1000 lines), that's
  normal — npm re-resolves transitive deps when new direct deps are added.
- If Change 2 fails because `npm version` refuses to bump to the same value
  that's already there, the `--allow-same-version` flag should prevent that.
  If it still errors, replace the `npm version` call with
  `npm pkg set version="$VER"` followed by
  `npm install --package-lock-only --ignore-scripts` — same effect.
