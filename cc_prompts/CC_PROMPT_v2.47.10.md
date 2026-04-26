# CC PROMPT — v2.47.10 — fix(ci): exclude version line from REFERENCE.md drift check

## What this does
Fixes the CI failure introduced when v2.47.7 shipped REFERENCE.md drift
verification. Every version bump from v2.47.8 onwards has been failing
the `Check REFERENCE.md is up-to-date` step.

**Diagnosis**: `scripts/gen_reference.py:_strip_ts` strips the
`**Generated:**` timestamp before diffing the regenerated body against
the committed copy, but does NOT strip `**Version:**`. When `VERSION` is
bumped (every release), the rendered Version line changes but the
committed REFERENCE.md still shows the old version. Diff fails → exit 1
→ workflow fails.

Sequence that exposed it:
1. v2.47.7 shipped → CC ran `make reference` → committed REFERENCE.md with `**Version:** v2.47.7`
2. v2.47.8 bumped VERSION to 2.47.8 → CI's `make reference-check` regenerated body with `**Version:** v2.47.8` → diff failed
3. v2.47.9 bumped VERSION to 2.47.9 → same failure repeated
4. Every subsequent version bump will fail until this is fixed

**Fix**: also strip the `**Version:**` line in `_strip_ts`. The rendered
REFERENCE.md still shows the version stamp for human readers; only the
diff comparison ignores it. Two-line change.

Also regenerate `docs/REFERENCE.md` so the committed copy reflects the
current state at v2.47.10 (the previous committed copy is from v2.47.7
and is now several versions stale).

Version bump: 2.47.9 → 2.47.10

---

## Change 1 — `scripts/gen_reference.py` — strip `**Version:**` line

CC: open `scripts/gen_reference.py`. Find `_strip_ts` inside `main()`
(it's a nested function inside the `if args.check:` block, around line
480 of the file). Current code:

```python
        # Strip the "Generated:" timestamp line — that's expected to drift run-to-run
        def _strip_ts(s: str) -> str:
            return re.sub(r"\*\*Generated:\*\*[^\n]+", "**Generated:** -", s)
```

Replace with:

```python
        # Strip lines expected to drift between commits — the timestamp moves
        # every regeneration, the version moves every VERSION bump. Comparing
        # them to the committed copy would force a manual `make reference`
        # commit on every version bump, defeating the point of CI verification.
        def _strip_ts(s: str) -> str:
            s = re.sub(r"\*\*Generated:\*\*[^\n]+", "**Generated:** -", s)
            s = re.sub(r"\*\*Version:\*\*[^\n]+", "**Version:** -", s)
            return s
```

CC: this is a surgical change inside `main()`. The function is nested
(defined inside `if args.check:`). Match indentation exactly. Both
`re.sub` lines are at the same indent.

---

## Change 2 — regenerate `docs/REFERENCE.md`

After Change 1 lands, regenerate the committed REFERENCE.md so it
matches what the generator currently produces:

```bash
make reference
```

This will:
- Read `VERSION` → "2.47.10" (after the version bump in this prompt)
- Re-walk `api/routers/*.py` for routes (no functional changes since v2.47.7 in routes — should be same set)
- Re-walk `api/metrics.py` for counters (no new counters since v2.47.7)
- Re-regex `api/` for WS broadcasts (no new broadcasts since v2.47.7)
- Re-render templates (`docs/reference_templates/*.md` unchanged)
- Write `docs/REFERENCE.md` with current state

The DB schema section will still be empty in CC's environment (no
Postgres reachable). That's expected — operator regenerates that
section on agent-01 separately when there are schema migrations.

Verify locally:

```bash
# Should pass after regeneration
make reference-check
# Expected output: [gen_reference] OK — REFERENCE.md is up-to-date.

# Confirm the version line is current
grep -E "^\*\*Version:\*\*" docs/REFERENCE.md
# Expected: **Version:** v2.47.10  •  **Generated:** ...
```

---

## Verify

```bash
# 1. Strip fix is in place
grep -n "Version:.*[^\\\\n]" scripts/gen_reference.py
# Expected: line showing the new Version regex inside _strip_ts

# 2. Compile cleanly
python -m py_compile scripts/gen_reference.py

# 3. Reference-check passes
make reference-check

# 4. Committed REFERENCE.md has v2.47.10
head -10 docs/REFERENCE.md | grep "Version"
# Expected: **Version:** v2.47.10  •  **Generated:** ...
```

---

## Version bump

Update `VERSION`: `2.47.9` → `2.47.10`

CC: bump VERSION FIRST, then regenerate REFERENCE.md so the regenerated
file picks up "2.47.10" as the current version.

Order of operations:
1. Apply Change 1 to `scripts/gen_reference.py`
2. Update `VERSION` to `2.47.10`
3. Run `make reference` to regenerate `docs/REFERENCE.md`
4. Run `make reference-check` to confirm it passes

---

## Commit

```
git add -A
git commit -m "fix(ci): v2.47.10 exclude version line from REFERENCE.md drift check"
git push origin main
```

After this lands, GitHub Actions sensors workflow should go green again.
Future version bumps will no longer require manual REFERENCE.md
regeneration to pass CI — the file is allowed to lag the version
stamp, only structural changes (new routes, new WS events, new
counters) require a regeneration commit.

Operator should still run `make reference` periodically on agent-01
to refresh the DB schema section after migrations, but CI no longer
fails when they don't.
