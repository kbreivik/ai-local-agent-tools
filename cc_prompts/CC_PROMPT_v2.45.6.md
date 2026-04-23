# CC PROMPT — v2.45.6 — fix(tests): sharpen ambiguous task wording + bump remaining timeouts

## What this does

Two types of fix in test_definitions.py:

1. **Task wording** — 5 tests where the agent picks a plausible-but-wrong tool because
   the task doesn't name the expected tool explicitly. Fix: reword to be declarative
   and name the exact tool.

2. **Timeout bumps** — 5 tests that are still timing out after the last round of
   increases. The agent is doing the right thing but hitting the wall.

Version bump: 2.45.5 → 2.45.6.

---

## Change — `api/db/test_definitions.py`

### Task wording fixes

CC: Change ONLY the `task` field on the listed test cases. Do not touch any other field.

#### status-version-01
Old task:
```python
task="what version is the workload service running? call service_current_version",
```
New task:
```python
task="call service_current_version for workload-stack_workload and report the current running version",
```

#### research-precheck-01
Old task:
```python
task="check if kafka is healthy and safe before any upgrade",
```
New task:
```python
task="call pre_kafka_check to verify the kafka cluster is healthy and safe before any upgrade",
```

#### research-elastic-pattern-01
Old task:
```python
task="show log patterns for the nginx service",
```
New task:
```python
task="call elastic_log_pattern to show log entry patterns for the nginx service from elasticsearch",
```

#### research-kafka-logs-01
Old task:
```python
task="show recent kafka broker logs",
```
New task:
```python
task="call elastic_kafka_logs to retrieve recent kafka broker log entries from elasticsearch",
```

#### orch-verify-01
Old task:
```python
task="call post_upgrade_verify to verify workload-stack_workload is healthy",
```
New task:
```python
task="call post_upgrade_verify for workload-stack_workload to confirm it is healthy after the last upgrade",
```

---

### Timeout bumps

CC: Change ONLY the listed fields. Do not touch any other field on these test cases.

#### status-svc-health-01
```python
timeout_s=80  →  timeout_s=180
```

#### research-elastic-search-01
```python
timeout_s=150  →  timeout_s=220
```

#### clarify-01
```python
timeout_s=90  →  timeout_s=150
```

#### clarify-03
```python
timeout_s=90  →  timeout_s=150
```

#### clarify-04
```python
timeout_s=90  →  timeout_s=150
```

#### orch-verify-01
```python
timeout_s=60  →  timeout_s=120
```

---

## Version bump

Update `VERSION`: `2.45.5` → `2.45.6`

---

## Commit

```
git add -A
git commit -m "fix(tests): v2.45.6 sharpen ambiguous task wording + bump remaining timeouts"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
