# CC PROMPT — v2.45.11 — fix(tests): task wording + timeouts for 8 remaining failures

## What this does

Analysis of 3 recent runs identified 8 tests with fixable failures:

**A. Wrong tool called (task wording too vague or "call X" triggers skill lookup):**

| Test | Observed tools | Expected | Fix |
|---|---|---|---|
| research-versions-01 | audit_log | service_version_history | name the tool explicitly |
| research-precheck-01 | pre_kafka_check × 2, then plan_action | pre_kafka_check + done | remove "upgrade" keyword → triggers execute agent |
| research-kafkacheck-01 | kafka_broker_status, kafka_exec | pre_kafka_check | "call" → skill search; change to "use the X tool" |
| research-elastic-logs-01 | elastic_search_logs × loop | elastic_error_logs | name the tool explicitly |
| orch-correlate-01 | elastic_search_logs × loop | elastic_correlate_operation | name the tool explicitly |

**B. Timeouts still too tight:**

| Test | Observed | Limit | New limit |
|---|---|---|---|
| status-kafka-02 | 122s | 90s | 180s |
| clarify-03 | 150s | 150s | 240s |
| orch-correlate-01 | 99-113s | 90s | 180s |
| action-upgrade-01 | 150s | 150s | 240s |
| action-kafka-restart-01 | 0s (never started) | 150s | 240s + fix |

Also action-kafka-restart-01 shows 0 steps / 0 duration — pre_kafka_check is
being called before this test (as part of the test runner's setup) and may be
returning degraded, blocking the task before it starts. Add explicit task wording.

Version bump: 2.45.10 → 2.45.11.

---

## Change — `api/db/test_definitions.py`

CC: Change ONLY the listed fields on the listed test cases. Touch nothing else.

### research-versions-01 — task only
Old:
```python
task="show kafka version history for available rollback targets",
```
New:
```python
task="use service_version_history to show available kafka rollback targets",
```

### research-precheck-01 — task only
Old:
```python
task="call pre_kafka_check to verify the kafka cluster is healthy and safe before any upgrade",
```
New:
```python
task="use the pre_kafka_check tool to verify kafka cluster readiness and report the result",
```

### research-kafkacheck-01 — task only
Old:
```python
task="call pre_kafka_check to verify kafka pre-flight status",
```
New:
```python
task="use the pre_kafka_check tool to get the kafka pre-flight status check result",
```

### research-elastic-logs-01 — task only
Old:
```python
task="search elasticsearch for error log entries in the last hour",
```
New:
```python
task="use elastic_error_logs to retrieve error-level log entries from the last hour",
```

### orch-correlate-01 — task + max_steps + timeout_s
Old task:
```python
task="correlate the last operation with elasticsearch logs",
```
New task:
```python
task="use elastic_correlate_operation to correlate the last agent operation with elasticsearch logs",
```
Old limits:
```python
max_steps=8, timeout_s=90
```
New limits:
```python
max_steps=12, timeout_s=180
```

### status-kafka-02 — timeout_s only
```python
timeout_s=90  →  timeout_s=180
```

### clarify-03 — timeout_s only
```python
timeout_s=150  →  timeout_s=240
```

### action-upgrade-01 — task + timeout_s
Old task:
```python
task="upgrade workload-stack_workload to nginx:1.27-alpine",
```
New task:
```python
task="upgrade workload-stack_workload service to nginx:1.27-alpine — call plan_action before executing",
```
Old timeout:
```python
timeout_s=150
```
New timeout:
```python
timeout_s=240
```

### action-kafka-restart-01 — task + timeout_s
Old task:
```python
task="perform a rolling restart of kafka brokers",
```
New task:
```python
task="perform a rolling restart of kafka brokers — use plan_action to propose the restart plan before executing kafka_rolling_restart_safe",
```
Old timeout:
```python
timeout_s=150
```
New timeout:
```python
timeout_s=240
```

---

## Version bump

Update `VERSION`: `2.45.10` → `2.45.11`

---

## Commit

```
git add -A
git commit -m "fix(tests): v2.45.11 task wording + timeouts for 8 remaining failures"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
