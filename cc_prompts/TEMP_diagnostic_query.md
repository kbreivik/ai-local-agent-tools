# Diagnostic queries for v2.47.6 baseline analysis

Run on agent-01:

```bash
docker exec -i hp1-postgres psql -U hp1 -d hp1_agent <<'SQL'

\echo '=== A. Rescue counters from Prometheus (via metrics endpoint not DB) ==='
\echo '   Check via: curl http://localhost:8000/metrics | grep -E "harness_plan_nudges|no_evidence_rebuke|clarify_ceiling"'

\echo ''
\echo '=== B. Operations from latest mem-on baseline run ==='
\echo '    run_id = ac672755 superseded; latest is from 08:59 today'
SELECT
    o.id              AS op_id,
    o.task            AS task,
    o.status,
    o.started_at::time AS t,
    o.parent_session_id IS NOT NULL AS sub
FROM operations o
WHERE o.started_at > '2026-04-26 08:55:00'
  AND o.started_at < '2026-04-26 09:50:00'
  AND o.task IN (
      'restore node 0sj1zr8f1pcm to active',
      'drain node 0sj1zr8f1pcm for maintenance',
      'rollback kafka-stack_kafka1 to previous version',
      'upgrade workload-stack_workload service to nginx:1.27-alpine — call plan_action before executing',
      'show elasticsearch index statistics',
      'is elasticsearch healthy?'
  )
ORDER BY o.started_at;

\echo ''
\echo '=== C. Tool calls per op for the 6 failing tests ==='
SELECT
    LEFT(tc.tool_name, 40)             AS tool,
    COUNT(*) FILTER (WHERE o.task LIKE '%restore node%')      AS act_act,
    COUNT(*) FILTER (WHERE o.task LIKE '%drain node%')        AS act_drn,
    COUNT(*) FILTER (WHERE o.task LIKE '%rollback%')          AS act_rb,
    COUNT(*) FILTER (WHERE o.task LIKE '%upgrade workload%')  AS act_up,
    COUNT(*) FILTER (WHERE o.task LIKE '%index stat%')        AS res_idx,
    COUNT(*) FILTER (WHERE o.task LIKE '%is elasticsearch%')  AS stat_el
FROM operations o
JOIN tool_calls tc ON tc.operation_id = o.id
WHERE o.started_at > '2026-04-26 08:55:00'
  AND o.started_at < '2026-04-26 09:50:00'
  AND o.task IN (
      'restore node 0sj1zr8f1pcm to active',
      'drain node 0sj1zr8f1pcm for maintenance',
      'rollback kafka-stack_kafka1 to previous version',
      'upgrade workload-stack_workload service to nginx:1.27-alpine — call plan_action before executing',
      'show elasticsearch index statistics',
      'is elasticsearch healthy?'
  )
GROUP BY 1
ORDER BY 1;

\echo ''
\echo '=== D. Final answers for the 6 failures (first 200 chars) ==='
SELECT
    LEFT(o.task, 50)         AS task,
    o.status,
    LEFT(o.final_answer, 200) AS final_answer
FROM operations o
WHERE o.started_at > '2026-04-26 08:55:00'
  AND o.started_at < '2026-04-26 09:50:00'
  AND o.task IN (
      'restore node 0sj1zr8f1pcm to active',
      'drain node 0sj1zr8f1pcm for maintenance',
      'rollback kafka-stack_kafka1 to previous version',
      'upgrade workload-stack_workload service to nginx:1.27-alpine — call plan_action before executing',
      'show elasticsearch index statistics',
      'is elasticsearch healthy?'
  )
ORDER BY o.started_at;

\echo ''
\echo '=== E. Step counts per op (how many LLM rounds happened?) ==='
SELECT
    LEFT(o.task, 50)              AS task,
    COUNT(DISTINCT lt.step_index) AS llm_steps
FROM operations o
LEFT JOIN agent_llm_traces lt ON lt.operation_id = o.id
WHERE o.started_at > '2026-04-26 08:55:00'
  AND o.started_at < '2026-04-26 09:50:00'
  AND o.task IN (
      'restore node 0sj1zr8f1pcm to active',
      'drain node 0sj1zr8f1pcm for maintenance',
      'rollback kafka-stack_kafka1 to previous version',
      'upgrade workload-stack_workload service to nginx:1.27-alpine — call plan_action before executing',
      'show elasticsearch index statistics',
      'is elasticsearch healthy?'
  )
GROUP BY 1
ORDER BY 1;

SQL
```

Then check Prometheus rescue counters separately:

```bash
curl -s http://localhost:8000/metrics 2>&1 | grep -E "harness_plan_nudges|no_evidence_rebuke|clarify_ceiling"
```

Expected if rescues fired correctly:
- `deathstar_harness_plan_nudges_total{agent_type="action"} ≥ 3` (the 3 clarify-then-text-exit cases)
- `deathstar_harness_no_evidence_rebuke_total{agent_type="status"} ≥ 2` (status-elastic-01 + research-elastic-index-01)
