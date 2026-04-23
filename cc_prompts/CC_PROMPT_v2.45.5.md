# CC PROMPT — v2.45.5 — fix(tests): increase timeouts for Qwen3-30B local hardware

## What this does

Timeouts in test_definitions.py were written for a faster model/cloud inference.
Qwen3-Coder-30B on local LM Studio takes 20-25s per LLM step. Observed run data
shows tests working correctly but hitting the wall 5-30s too late.

Actual observed durations from last smoke run vs current limits:

| Test | Actual | Current limit | New limit |
|---|---|---|---|
| research-versions-01 | 67s | 60s | 150s |
| research-resolve-01 | 76s | 60s | 150s |
| research-elastic-logs-01 | 63s | 60s | 150s |
| research-elastic-search-01 | 59s | 50s | 150s |
| research-elastic-pattern-01 | 54s | 50s | 150s |
| research-kafka-logs-01 | 52s | 50s | 150s |
| research-elastic-index-01 | n/a | 50s | 150s (same class) |
| clarify-01 | 41s | 40s | 90s |
| clarify-02 | 56s | 45s | 90s |
| clarify-03 | 45s | 40s | 90s |
| clarify-04 | 42s | 40s | 90s |
| action-upgrade-01 | ~80s | 80s | 150s |
| action-rollback-01 | 53s | 80s | 150s |
| action-drain-01 | 56s | 60s | 150s |
| action-activate-01 | 64s | 60s | 150s |
| action-checkpoint-01 | 70s | 60s | 150s |
| action-kafka-restart-01 | n/a | 80s | 150s |
| safety-stop-01 | 28s | 25s | 55s |
| safety-no-plan-01 | n/a | 60s | 90s |
| safety-max-steps-01 | n/a | 45s | 90s |
| orch-audit-01 | 30s | 25s | 75s |
| orch-correlate-01 | 43s | 30s | 90s |

Also increase stop_after_seconds where it feeds into a tight timeout:
- clarify-02: 30 → 60 (let model finish one more step before cancelling)
- action-rollback-01: 50 → 90
- action-drain-01: 40 → 90
- action-activate-01: 40 → 90

safety-stop-01 stop_after stays at 5 (intentional — testing stop responsiveness)
but timeout increases to 55 to allow one LLM inference to complete after signal.

Version bump: 2.45.4 → 2.45.5.

---

## Change — `api/db/test_definitions.py`

CC: Apply all changes to the TEST_CASES list. Make only the fields listed —
do not touch any other fields on any test case. Double-check each id before
editing.

### research tests — all 50s/60s timeouts → 150s

```python
# research-versions-01
timeout_s=60  →  timeout_s=150

# research-resolve-01
timeout_s=60  →  timeout_s=150

# research-precheck-01  (already 120, leave it)

# research-kafkacheck-01  (already 90, leave it)

# research-elastic-logs-01
timeout_s=60  →  timeout_s=150

# research-elastic-search-01
timeout_s=50  →  timeout_s=150

# research-elastic-pattern-01
timeout_s=50  →  timeout_s=150

# research-kafka-logs-01
timeout_s=50  →  timeout_s=150

# research-elastic-index-01
timeout_s=50  →  timeout_s=150
```

### clarification tests — 40/45s → 90s, clarify-02 stop_after 30→60

```python
# clarify-01
timeout_s=40  →  timeout_s=90

# clarify-02
stop_after_seconds=30, timeout_s=45  →  stop_after_seconds=60, timeout_s=90

# clarify-03
timeout_s=40  →  timeout_s=90

# clarify-04
timeout_s=40  →  timeout_s=90
```

### action tests — tight timeouts → 150s, bump stop_after to match

```python
# action-upgrade-01
timeout_s=80  →  timeout_s=150

# action-rollback-01
stop_after_seconds=50, timeout_s=80  →  stop_after_seconds=90, timeout_s=150

# action-drain-01
stop_after_seconds=40, timeout_s=60  →  stop_after_seconds=90, timeout_s=150

# action-activate-01
stop_after_seconds=40, timeout_s=60  →  stop_after_seconds=90, timeout_s=150

# action-checkpoint-01
timeout_s=60  →  timeout_s=150

# action-kafka-restart-01
timeout_s=80  →  timeout_s=150
```

### safety tests — targeted increases only

```python
# safety-no-plan-01
stop_after_seconds=45, timeout_s=60  →  stop_after_seconds=45, timeout_s=90

# safety-max-steps-01
timeout_s=45  →  timeout_s=90

# safety-stop-01  (stop_after stays 5 — intentional)
timeout_s=25  →  timeout_s=55
```

### orchestration tests — very tight limits → sensible for local inference

```python
# orch-audit-01
max_steps=5, timeout_s=25  →  max_steps=8, timeout_s=75

# orch-correlate-01
max_steps=6, timeout_s=30  →  max_steps=8, timeout_s=90
```

---

## Version bump

Update `VERSION`: `2.45.4` → `2.45.5`

---

## Commit

```
git add -A
git commit -m "fix(tests): v2.45.5 increase timeouts for Qwen3-30B local inference speed"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
