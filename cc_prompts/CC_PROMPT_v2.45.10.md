# CC PROMPT — v2.45.10 — fix(tests): pass pre-filtered cases to run_all_tests — suite test_ids dead code

## Root cause

`_run_tests_bg` builds `cases_to_run` (filtered by both `categories` and `test_ids`)
but then calls `run_all_tests(categories=categories or None, ...)` — which does its
OWN filtering from `TEST_CASES` using only `categories`. The pre-filtered list is
discarded. `test_ids` filtering is dead code.

Result: smoke-mem-on-fast (7 tests) and safety-mem-on-critical (7 tests) both run
all 38 tests. Score and pass counts are meaningless for suite-based runs.

Fix: add `cases: list | None = None` param to `run_all_tests`. When provided,
use it instead of re-building from TEST_CASES. Pass `cases_to_run` from
`_run_tests_bg`.

Two-file change.

Version bump: 2.45.9 → 2.45.10.

---

## Change 1 — `tests/integration/test_agent.py`

Find:
```python
async def run_all_tests(
    categories: list[str] | None,
    http: httpx.AsyncClient,
    args=None,
    token: str = "",
) -> list[TestResult]:
    cases = TEST_CASES
    if categories:
        cases = [tc for tc in TEST_CASES if tc.category in categories]
```

Replace with:
```python
async def run_all_tests(
    categories: list[str] | None,
    http: httpx.AsyncClient,
    args=None,
    token: str = "",
    cases: list | None = None,
) -> list[TestResult]:
    if cases is not None:
        pass  # use caller-supplied pre-filtered list
    elif categories:
        cases = [tc for tc in TEST_CASES if tc.category in categories]
    else:
        cases = list(TEST_CASES)
```

---

## Change 2 — `api/routers/tests_api.py`

Find the `run_all_tests` call in `_run_tests_bg`:
```python
        async with httpx.AsyncClient(timeout=30.0, headers=_auth_headers) as http:
            results = await run_all_tests(
                categories=categories or None,
                http=http,
                args=None,
                token=_fresh_token,
            )
```

Replace with:
```python
        async with httpx.AsyncClient(timeout=30.0, headers=_auth_headers) as http:
            results = await run_all_tests(
                categories=categories or None,
                http=http,
                args=None,
                token=_fresh_token,
                cases=cases_to_run if (test_ids or (categories and len(categories) < 6)) else None,
            )
```

This passes the pre-filtered list when:
- test_ids are specified (suite by explicit IDs), or
- categories are a subset (not all 6 categories)

When categories is all 6 or None, passes None so run_all_tests uses its default
full-set logic (same behaviour as before for full baseline runs).

---

## Version bump

Update `VERSION`: `2.45.9` → `2.45.10`

---

## Commit

```
git add -A
git commit -m "fix(tests): v2.45.10 pass pre-filtered cases to run_all_tests — suite test_ids was dead code"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
