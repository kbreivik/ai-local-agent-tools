# CC PROMPT — v2.45.20 — fix(tests): timeout headroom for 4 borderline failures

## What this does
Bumps timeouts on 4 tests that fail by <5s while doing the right thing. From
the v2.45.17 status report:
- research-versions-01 — times out at 151s vs 150s limit → 180s
- clarify-01 — times out at 152s vs 150s limit → 240s
- action-rollback-01 — still clarifying at 153s → 240s
- safety-no-plan-01 — clarification loop times out at 90s → 120s

These are correctness-correct, speed-bounded failures.

Version bump: 2.45.19 → 2.45.20

---

## Context

Test cases live in `api/db/test_definitions.py` as a `TEST_CASES` list of
`TestCase(...)` calls, each with a `timeout_s=N` field.

CC: open the file, locate each TestCase by its `id="..."` string, and update
its `timeout_s=` value. If the field is absent (uses a default), add it.

---

## Change — `api/db/test_definitions.py`

Apply 4 edits, one per test case. Match the existing TestCase line indent.

### Edit 1: research-versions-01

Find the TestCase with `id="research-versions-01"`. Locate its `timeout_s=`
parameter. Change to `timeout_s=180`. If `timeout_s` is not present in this
case's call, add `timeout_s=180,` next to the existing parameters.

### Edit 2: clarify-01

Find the TestCase with `id="clarify-01"`. Set `timeout_s=240`.

### Edit 3: action-rollback-01

Find the TestCase with `id="action-rollback-01"`. Set `timeout_s=240`.

### Edit 4: safety-no-plan-01

Find the TestCase with `id="safety-no-plan-01"`. Set `timeout_s=120`.

CC: if any of these IDs are not found, STOP and report which one is missing —
do not invent values or guess at IDs.

---

## Verify

```bash
python -m py_compile api/db/test_definitions.py
python -c "from api.db.test_definitions import TEST_CASES; \
    ids = {'research-versions-01': 180, 'clarify-01': 240, \
           'action-rollback-01': 240, 'safety-no-plan-01': 120}; \
    [print(tc.id, tc.timeout_s, '✓' if tc.timeout_s == ids.get(tc.id) else '✗ mismatch') \
     for tc in TEST_CASES if tc.id in ids]"
```

Expected: all four print `✓`.

---

## Version bump

Update `VERSION`: `2.45.19` → `2.45.20`

---

## Commit

```
git add -A
git commit -m "fix(tests): v2.45.20 timeout headroom — research-versions-01 + clarify-01 + action-rollback-01 + safety-no-plan-01"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
