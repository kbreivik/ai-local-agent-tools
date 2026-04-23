# CC PROMPT — v2.44.3 — fix(tests): add tests/__init__.py + tests/integration/__init__.py so API can import TEST_CASES

## What this does

`GET /api/tests/cases` returns 500 because `from tests.integration.test_agent
import TEST_CASES` fails — `tests/` and `tests/integration/` have no
`__init__.py`, so Python doesn't treat them as packages when running inside
the FastAPI container (the test runner works from CLI because it adds the
root to sys.path directly).

Fix: add two empty `__init__.py` files.

Version bump: 2.44.2 → 2.44.3.

---

## Change 1 — create `tests/__init__.py`

```python
```
(empty file)

---

## Change 2 — create `tests/integration/__init__.py`

```python
```
(empty file)

---

## Verification

After deploy, `GET /api/tests/cases` should return 200 with `total: 34` (or
however many TEST_CASES are defined). Library tab in Tests panel should
populate with all test cases.

---

## Version bump

Update `VERSION`: `2.44.2` → `2.44.3`

---

## Commit

```
git add -A
git commit -m "fix(tests): v2.44.3 add tests/__init__.py files so API can import TEST_CASES"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
