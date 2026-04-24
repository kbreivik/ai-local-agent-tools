# CC PROMPT — v2.45.8 — fix(tests): elastic-pattern task rewording + clarify-02 timeout

## What this does

Two targeted test_definitions.py fixes from the full-mem-off-baseline run analysis.

**Fix 1: research-elastic-pattern-01**
Task says "call elastic_log_pattern to show..." but the model interprets "call" as
"find a skill named elastic_log_pattern" → calls skill_search first, never finds it
as a skill, then uses generic ES tools. The word "call" triggers skill lookup.
Fix: reword to "use the elastic_log_pattern tool" — makes it clear it's a built-in
tool, not a skill, matching RESEARCH_PROMPT constraint 5 correctly.

**Fix 2: clarify-02 timeout**
Agent correctly called clarifying_question() in 4 steps but the LLM inference
itself took 91s for that single step. Timeout is 90s. Bump to 180s.

Version bump: 2.45.7 → 2.45.8.

---

## Change — `api/db/test_definitions.py`

### research-elastic-pattern-01 — task wording only

Find:
```python
TestCase(id="research-elastic-pattern-01", category="research",
    task="call elastic_log_pattern to show log entry patterns for the nginx service from elasticsearch",
```

Replace task field with:
```python
    task="use the elastic_log_pattern tool to retrieve log entry patterns for the nginx service from elasticsearch",
```

### clarify-02 — timeout only

Find:
```python
TestCase(id="clarify-02", category="clarification",
    ...timeout_s=90...
```

Change:
```python
timeout_s=90  →  timeout_s=180
```

---

## Version bump

Update `VERSION`: `2.45.7` → `2.45.8`

---

## Commit

```
git add -A
git commit -m "fix(tests): v2.45.8 elastic-pattern task reword + clarify-02 timeout 90→180s"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
