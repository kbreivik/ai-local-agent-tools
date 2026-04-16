# CC PROMPT — v2.31.19 — chore(ci): paths-ignore cc_prompts/** so DONE-mark chores don't trigger builds

## What this does
Every version CC processes creates two commits in sequence:

1. **Code commit** — the actual feature/fix + VERSION bump (touches `api/`,
   `gui/`, `requirements.txt`, `VERSION`, etc.)
2. **Chore commit** — `chore: mark vX.Y.Z DONE in prompt queue` which only
   touches `cc_prompts/INDEX.md`

Both currently trigger the `Build & Push` workflow. The chore commit arrives
~30-60s after the code commit, which starts a new build; the `concurrency:
cancel-in-progress: true` block then kills the code commit's build mid-run
and lets the chore build finish. Net result is the same image (chore commit
contains the same code), but the Actions page fills with red "cancelled"
entries and "3 errors and 1 warning" annotation noise.

Since the chore commit contains no code or VERSION change, its build is
redundant. Skip it with `paths-ignore`.

One workflow edit. No version bump needed from the DEATHSTAR runtime side —
the VERSION file stays at 2.31.18 (last real code change). This is a pure
CI tidy-up.

Actually — bump VERSION anyway to 2.31.19 so the next CI run has a unique
tag. The image content will be identical to 2.31.18 but with a new label,
which is fine.

---

## Change 1 — `.github/workflows/build.yml`

Open `.github/workflows/build.yml`. Find the `on:` trigger block near the
top:

```yaml
on:
  push:
    branches: [main, 'v2/**']
    tags: ['v*']
```

Replace with:

```yaml
on:
  push:
    branches: [main, 'v2/**']
    tags: ['v*']
    # Skip builds for commits that ONLY touch the prompt queue bookkeeping
    # (DONE-mark chore commits from run_queue.sh). These commits contain the
    # same source tree as the preceding code commit — rebuilding produces an
    # identical image. Skipping avoids the cancel-in-progress churn.
    #
    # Note: paths-ignore ONLY skips if every changed path in the commit
    # matches. Commits that touch cc_prompts/ AND anything else still run.
    paths-ignore:
      - 'cc_prompts/**'
      - '*.md'
      - 'docs/**'
```

Including `*.md` and `docs/**` as well: pure documentation edits (README
tweaks, WINDOWS_SETUP.md fixes) don't change the runtime image either.
Keep the scope tight — only patterns that provably can't affect the built
container. Don't ignore `VERSION`, `Dockerfile`, `docker/**`,
`requirements.txt`, `api/**`, `gui/**`, `mcp_server/**`, `scripts/**`.

---

## Change 2 — bump VERSION

The last real code change shipped as 2.31.18 (docs only — doesn't actually
modify the image, but CC still bumped VERSION per the workflow convention).
For v2.31.19, bump VERSION to `2.31.19` so CI produces a uniquely-tagged
image even though the content is identical to 2.31.18.

```
# VERSION file contents:
2.31.19
```

---

## Change 3 — gui/package.json version alignment

CI's "Sync package.json + lockfile version" step will run `npm version
--allow-same-version "2.31.19"` which updates both `gui/package.json` and
`gui/package-lock.json` in-lockstep. No manual edit needed — it happens
during the build. But if CC wants to also update those files locally to
avoid a dirty-diff on first pull, that's fine. Not required.

---

## Commit

```
git add -A
git commit -m "chore(ci): v2.31.19 paths-ignore cc_prompts/** + docs/** to skip redundant builds"
git push origin main
```

This commit WILL trigger a build (it touches `VERSION` and
`.github/workflows/build.yml`, neither of which is in the ignore list —
good, we want the new workflow config applied). The follow-up `chore: mark
v2.31.19 DONE` will NOT trigger a build, because it only touches
`cc_prompts/INDEX.md`.

---

## How to test

1. **After this build's DONE-mark chore commit**, check
   https://github.com/kbreivik/ai-local-agent-tools/actions — there should
   be NO new workflow run listed for the chore commit (not even a skipped
   one — paths-ignore means GitHub doesn't create the run at all).

2. **Next real code prompt (v2.31.20+)**: verify only ONE run appears per
   version — the code commit's build. It should run to completion (~2m 16s)
   without cancellation.

3. **Sanity: a docs-only edit still skips**. Try editing `README.md` in a
   small commit; workflow should not trigger. If you want to force a build
   on a docs commit for some reason (rare), add `[force build]` to the
   commit message — GitHub doesn't honour that by default, so the escape
   hatch is to touch any non-ignored file (e.g. `echo " " >> VERSION` then
   revert) or run the workflow manually from the Actions UI.

4. **GitHub Actions Annotations page**: after one more queue iteration, the
   "3 errors and 1 warning" annotation noise on the Actions index view
   should be gone. Errors were all "operation was cancelled" — with no
   cancellations, no error annotations.

---

## Notes

- **Why `paths-ignore` over a `paths` include list**: safer default. If we
  add a new source directory in the future, `paths-ignore` continues
  building. A `paths` include list would silently miss new dirs.
- **Edge case**: if the queue runner's scope grows (e.g. someday it also
  touches `docs/` or the root README), those won't trigger rebuilds either
  — intentional. If a doc change IS image-relevant (e.g. embedded in the
  runtime), move the doc out of `docs/` or rename it.
- **Not in scope**: fixing the Node.js 20 deprecation warning. That's about
  third-party actions (`actions/checkout@v4.2.2`, `docker/build-push-action@v6`,
  `docker/login-action@v3.3.0`) needing to bump to versions that use Node 24
  internally. Not ours to fix — wait for upstream, or pin newer tags when
  available. Handled silently by GitHub's `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24`
  shim for now.
