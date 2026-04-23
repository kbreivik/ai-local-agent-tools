# CC PROMPT — v2.44.4 — fix(docker): include tests/integration/ in container — remove blanket `tests` exclusion from .dockerignore

## What this does

`.dockerignore` line 22 has a blanket `tests` exclusion that prevents the
entire `tests/` directory from being copied into the container image.

`/api/routers/tests_api.py` imports `from tests.integration.test_agent import TEST_CASES`
at runtime, which fails with 500 because `/app/tests/` does not exist in the
container.

The blanket exclusion was added to keep the image lean (CI-only tests
shouldn't bloat production). The correct fix is to narrow it:
- Keep excluding the pure pytest unit tests (`tests/test_*.py`, `tests/conftest.py`, etc.)
- Include `tests/integration/` which is needed at runtime by the API

Also exclude `tests/baseline.txt` and `tests/failures.txt` (large CI artefacts).

Version bump: 2.44.3 → 2.44.4.

---

## Change — `.dockerignore`

Replace the blanket `tests` line:

```
# Repo-only content
cc_prompts
tests
*.md
!VERSION
```

With a narrowed exclusion that keeps `tests/integration/`:

```
# Repo-only content
cc_prompts
tests/test_*.py
tests/conftest.py
tests/baseline.txt
tests/failures.txt
tests/fix_prompt.txt
*.md
!VERSION
```

This keeps `tests/__init__.py`, `tests/integration/__init__.py`, and
`tests/integration/test_agent.py` in the image so the API can import
`TEST_CASES` at runtime, while still excluding the large pytest unit test
files that are only needed in CI.

---

## Verification

After deploy:

```bash
# Should return 200 with total > 30
curl -s http://192.168.199.10:8000/api/tests/cases | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('total'), d.get('cases',[])[0].get('id'))"
```

Tests → Library tab should populate with all test cases.

---

## Version bump

Update `VERSION`: `2.44.3` → `2.44.4`

---

## Commit

```
git add -A
git commit -m "fix(docker): v2.44.4 narrow .dockerignore — include tests/integration/ in container image"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
