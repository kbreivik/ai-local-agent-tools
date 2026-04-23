# CC PROMPT — v2.44.6 — fix(tests): fix get_test_cases field names — timeout_s not timeout, etc.

## What this does

`GET /api/tests/cases` returns 500 because the handler accesses fields using the
old test_agent.py `TestCase` field names, which differ from the new
`api/db/test_definitions.py` `TestCase` field names:

| Handler accesses | Actual field name |
|---|---|
| `tc.timeout` | `tc.timeout_s` |
| `tc.expected_tools` | `tc.expect_tools` |
| `tc.expected_agent_type` | `tc.agent_type` |

One-function fix in `api/routers/tests_api.py`.

Version bump: 2.44.5 → 2.44.6.

---

## Change — `api/routers/tests_api.py`

Find the `get_test_cases()` function body. Replace the dict comprehension:

```python
    return {
        "cases": [
            {
                "id":            tc.id,
                "category":      tc.category,
                "task":          tc.task,
                "soft":          tc.soft,
                "critical":      tc.critical,
                "timeout":       tc.timeout,
                "expected_tools": tc.expected_tools,
                "expected_agent_type": tc.expected_agent_type,
            }
            for tc in TEST_CASES
        ],
        "total": len(TEST_CASES),
    }
```

With corrected field names:

```python
    return {
        "cases": [
            {
                "id":                   tc.id,
                "category":             tc.category,
                "task":                 tc.task,
                "soft":                 tc.soft,
                "critical":             tc.critical,
                "timeout_s":            tc.timeout_s,
                "expect_tools":         tc.expect_tools,
                "forbid_tools":         tc.forbid_tools,
                "agent_type":           tc.agent_type,
                "triggers_plan":        tc.triggers_plan,
                "triggers_clarification": tc.triggers_clarification,
                "max_steps":            tc.max_steps,
            }
            for tc in TEST_CASES
        ],
        "total": len(TEST_CASES),
    }
```

---

## Verification

```bash
curl -s http://192.168.199.10:8000/api/tests/cases | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print('total:', d.get('total'), '| first:', d.get('cases',[])[0].get('id'))"
```
Expected: `total: 38 | first: status-swarm-01`

---

## Version bump

Update `VERSION`: `2.44.5` → `2.44.6`

---

## Commit

```
git add -A
git commit -m "fix(tests): v2.44.6 correct get_test_cases field names (timeout_s, expect_tools, agent_type)"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
