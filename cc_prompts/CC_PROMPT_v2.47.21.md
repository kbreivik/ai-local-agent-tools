# CC PROMPT — v2.47.21 — fix(docker): pip install failures silently masked by `|| true` (smoking gun for v2.47.19/20 broken images)

## What this does

Root cause of v2.47.19 and v2.47.20 producing 279MB images: the
runtime stage's `pip install` is failing partway, but the failure is
masked by a `|| true` at the end of the RUN chain. BuildKit reports
"Success", broken image gets pushed.

Layer-size diff between v2.47.18 (works, 783MB) and v2.47.20 (broken,
279MB) confirmed via `docker history`:

| Layer                                  | v2.47.18  | v2.47.20  |
| -------------------------------------- | --------- | --------- |
| `COPY /wheels /wheels`                 | 115MB     | 115MB     |
| `RUN pip install /wheels/*.whl ...`    | **512MB** | **7.99MB**|

Same wheels copied in (~115MB layer), but pip only expanded ~8MB of
installed packages in v2.47.20 vs 512MB in v2.47.18. Pip is failing
after installing a tiny subset.

The current Dockerfile RUN line:

```dockerfile
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels && \
    python -c "import torch" 2>/dev/null && echo "ERROR: torch installed" && exit 1 || true
```

Shell parses this as one chain: `A && B && C && D && E || true`. The
`|| true` was intended to handle the torch-absent case (we WANT torch
not installed, so `python -c "import torch"` exits non-zero, which
triggers `|| true`). But shell evaluates left-to-right — `|| true` ALSO
catches `pip install` failures, `rm -rf` failures, anything in the
chain. Silent build success on broken pip install.

This prompt:
1. Splits the chain so `pip install` failures fail the build loudly
2. Moves the torch-check to its own RUN with proper guard
3. Adds `no-cache: true` + `pull: true` to build.yml as defense in
   depth (forces fresh base + no implicit cache reuse)

We don't yet know WHY pip started failing between v2.47.18 (5h ago)
and v2.47.19 (3h ago). Possibilities: python:3.13-slim sub-version
refresh, transient network issue during wheel build, dependency
conflict in a requirements update. After this prompt lands, the next
broken build will print the actual pip error in CI logs — making
diagnosis trivial.

Version bump: 2.47.20 → 2.47.21

---

## Change 1 — `docker/Dockerfile` — split silent-failure RUN line

CC: open `docker/Dockerfile`. Find this section (around line 50-55):

```dockerfile
# Install Python wheels from builder (all deps, no pip at runtime)
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels && \
    python -c "import torch" 2>/dev/null && echo "ERROR: torch installed" && exit 1 || true
```

Replace with:

```dockerfile
# Install Python wheels from builder (all deps, no pip at runtime)
COPY --from=builder /wheels /wheels
# v2.47.21 — split previous chain. The old line had `|| true` at the end
# to handle the torch-absent case, but shell short-circuit semantics
# meant `|| true` ALSO swallowed pip install failures — building broken
# images that report "Success". v2.47.19 and v2.47.20 hit this exact
# trap (8MB installed instead of 512MB; pip silently failed partway).
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
# Sanity-check: torch must NOT have been pulled in. The negation
# inverts the condition cleanly without short-circuit pitfalls.
RUN if python -c "import torch" 2>/dev/null; then \
        echo "ERROR: torch installed unexpectedly — check requirements.txt" && exit 1; \
    fi
```

CC: keep the surrounding `COPY --from=builder /wheels /wheels` line
unchanged. Only the next RUN line gets split into two RUNs. Comments
explain the rationale; do NOT remove them — they prevent future
regressions.

---

## Change 2 — `.github/workflows/build.yml` — force no-cache + fresh base pull

CC: open `.github/workflows/build.yml`. Find the "Build and push" step:

```yaml
      - name: Build and push
        uses: docker/build-push-action@v6
        with:
          context: .
          file: docker/Dockerfile
          push: true
          tags: |
```

Add `no-cache: true` and `pull: true` between `push: true` and `tags:`:

```yaml
      - name: Build and push
        uses: docker/build-push-action@v6
        with:
          context: .
          file: docker/Dockerfile
          push: true
          # v2.47.21: force no-cache + pull. Defense in depth alongside
          # the Dockerfile silent-failure fix. v2.47.19 and v2.47.20 both
          # produced 279MB images (vs v2.47.18's 783MB) due to BuildKit
          # potentially reusing a cached broken layer. no-cache=true
          # forces every layer to rebuild; pull=true forces a fresh
          # base image pull. Adds ~2 min per build but eliminates an
          # entire class of CI flake.
          no-cache: true
          pull: true
          tags: |
```

CC: keep all other settings (`tags`, `labels`) exactly as they were.
Only the new comment + 2 yaml keys are added.

---

## Change 3 — `VERSION` — bump

CC: open `D:\claude_code\ai-local-agent-tools\VERSION`. Replace
`2.47.20` with `2.47.21`.

---

## Verify

```bash
# 1. Dockerfile fix landed
grep -A 2 "Install Python wheels from builder" docker/Dockerfile
# Expected: shows the new comment + COPY + split RUN structure

grep -B 1 "torch installed unexpectedly" docker/Dockerfile
# Expected: the new RUN block with `if` guard

grep -c "|| true" docker/Dockerfile
# Expected: 0 (the silent-failure pattern is gone from this RUN line.
# Other `|| true` uses in Dockerfile are fine; the bug was specifically
# the chain we split).

# 2. build.yml fix
grep -A 1 "no-cache: true" .github/workflows/build.yml
# Expected: shows no-cache + pull lines

# 3. VERSION
cat VERSION
# Expected: 2.47.21
```

After CI completes (will take 2-3 min now, not 30s):

```bash
ssh agent-01
sudo docker pull ghcr.io/kbreivik/hp1-ai-agent:2.47.21
sudo docker images | grep 2.47.21
# Expected: ~783MB. If it's 279MB or smaller, the build failed loudly
# this time — read the CI logs for the actual pip error and report
# back. Now we'll know exactly what's wrong because the silent mask
# is gone.

# If size is correct:
cd /opt/hp1-agent/docker
sudo sed -i 's|hp1-ai-agent:2.47.18|hp1-ai-agent:2.47.21|' docker-compose.yml
sudo docker compose --env-file .env up -d hp1_agent
sleep 10
curl -s http://localhost:8000/api/health | jq .version
# Expected: "2.47.21"

# Validate gate_macros endpoints (the whole point of v2.47.19's source change)
TOKEN=$(...)
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/tests/macros | jq
# Expected: {"macros": []}
```

---

## What this does NOT do

- **Does NOT diagnose why pip started failing.** Without seeing the
  actual pip error (which the silent mask was hiding), we can't
  pinpoint the exact cause. Most likely candidates:
  - python:3.13-slim sub-version refresh between v2.47.18 build and
    v2.47.19 build
  - A specific wheel in /wheels having a metadata conflict
  - Network blip during a download `pip install` was implicitly making
- **Does NOT modify requirements.txt.** Best practice would be to pin
  pip's behavior with `pip install --no-deps` since wheels are
  already-resolved, but that's a follow-up if v2.47.21 still has
  issues.
- **Does NOT cap wheels age or version.** A future failure could
  recur if pip's resolver behavior changes. If v2.47.21 builds
  cleanly and then a future build fails again, escalate to pinning
  `--no-deps` or per-wheel install.

If v2.47.21 is still 279MB, the CI logs will now show the actual
error. Report back with the failing pip line and we write v2.47.22
with the targeted fix.

---

## Version bump

Update `VERSION`: `2.47.20` → `2.47.21`

---

## Commit

```bash
git add -A
git commit -m "fix(docker+ci): v2.47.21 silent pip-install failure mask + force no-cache build"
git push origin main
```
