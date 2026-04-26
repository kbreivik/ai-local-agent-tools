Pre-baked SQL blocks for the questions that come up most often. Copy whole
blocks; the queries use only column names that exist in the live schema
(verified against `## 1. Database schema` above).

All queries assume PG with: `docker exec -i hp1-postgres psql -U hp1 -d hp1_agent`

## Q1 — Latest test runs

```sql
SELECT
    suite_name,
    started_at,
    score_pct,
    weighted_pct,
    passed,
    failed,
    finished_at - started_at AS duration
FROM test_runs
ORDER BY started_at DESC
LIMIT 10;
```

## Q2 — Failed tests in the most recent run of a suite

```sql
SELECT
    test_id, agent_type, timed_out, duration_s,
    LEFT(clarification_question, 60)  AS q,
    LEFT(clarification_answer_used, 30) AS a,
    plan_steps_count, plan_approved,
    LEFT(failures::text, 100)         AS failures
FROM test_run_results
WHERE run_id = (
    SELECT id FROM test_runs
    WHERE suite_name = 'full-mem-on-baseline'
    ORDER BY started_at DESC LIMIT 1
)
AND passed = false
ORDER BY test_id;
```

## Q3 — Compare yesterday vs latest run of a suite (delta)

```sql
WITH prev AS (
    SELECT test_id, passed FROM test_run_results
    WHERE run_id = (
        SELECT id FROM test_runs
        WHERE suite_name = 'full-mem-on-baseline'
        AND started_at < (SELECT MAX(started_at) FROM test_runs WHERE suite_name = 'full-mem-on-baseline')
        ORDER BY started_at DESC LIMIT 1
    )
),
latest AS (
    SELECT test_id, passed FROM test_run_results
    WHERE run_id = (SELECT id FROM test_runs WHERE suite_name = 'full-mem-on-baseline'
                    ORDER BY started_at DESC LIMIT 1)
)
SELECT COALESCE(p.test_id, l.test_id) AS test_id,
       p.passed AS prev, l.passed AS latest,
       CASE WHEN p.passed=true  AND l.passed=false THEN 'REGRESSED'
            WHEN p.passed=false AND l.passed=true  THEN 'FIXED' END AS delta
FROM prev p FULL OUTER JOIN latest l USING (test_id)
WHERE p.passed IS DISTINCT FROM l.passed
ORDER BY delta, test_id;
```

## Q4 — Did harness rescues fire? (per failing test)

```sql
SELECT
    LEFT(o.label, 35)                                           AS task,
    COUNT(*) FILTER (WHERE ol.content LIKE '[harness]%')        AS harness,
    COUNT(*) FILTER (WHERE ol.content LIKE '[clarify→plan]%')   AS clar_plan,
    COUNT(*) FILTER (WHERE ol.type    = 'step')                 AS step_lines,
    COUNT(*) FILTER (WHERE ol.type    = 'tool')                 AS tool_calls,
    COUNT(*)                                                    AS total
FROM operations o
LEFT JOIN operation_log ol ON ol.session_id = o.session_id
WHERE o.started_at > NOW() - INTERVAL '6 hours'
GROUP BY o.label, o.session_id
HAVING COUNT(*) FILTER (WHERE ol.type = 'step') > 0
ORDER BY o.started_at DESC
LIMIT 20;
```

## Q5 — Full step trace for a single test run

```sql
SELECT
    ol.timestamp, LEFT(ol.type, 8) AS type, LEFT(ol.content, 110) AS content
FROM operation_log ol
JOIN operations o ON o.session_id = ol.session_id
WHERE o.label = '<paste task text here>'
  AND o.started_at > NOW() - INTERVAL '24 hours'
ORDER BY ol.timestamp;
```

## Q6 — Facts coverage by source

```sql
SELECT source, COUNT(*) AS facts, MAX(last_verified) AS most_recent
FROM known_facts_current
GROUP BY source
ORDER BY facts DESC;
```

## Q7 — agent_attempts.summary populated ratio (last 7 days)

```sql
SELECT
    COUNT(*) FILTER (WHERE summary IS NOT NULL AND summary <> '') AS populated,
    COUNT(*)                                                      AS total,
    ROUND(100.0 * COUNT(*) FILTER (WHERE summary IS NOT NULL AND summary <> '')
          / NULLIF(COUNT(*), 0), 1) AS pct
FROM agent_attempts
WHERE created_at > NOW() - INTERVAL '7 days';
```

## Q8 — Operations that ended with zero substantive tool calls

```sql
SELECT
    LEFT(o.label, 50) AS task, o.status, o.started_at::time AS t,
    COUNT(tc.id) AS tool_calls
FROM operations o
LEFT JOIN tool_calls tc ON tc.operation_id = o.id
WHERE o.started_at > NOW() - INTERVAL '6 hours'
GROUP BY o.id, o.label, o.status, o.started_at
HAVING COUNT(tc.id) = 0
ORDER BY o.started_at DESC LIMIT 20;
```

## Q9 — External AI call outcomes (recent)

```sql
SELECT
    eac.provider, eac.model, eac.rule_fired, eac.outcome,
    eac.latency_ms, eac.input_tokens, eac.output_tokens,
    LEFT(eac.error_message, 80) AS err
FROM external_ai_calls eac
ORDER BY eac.id DESC LIMIT 20;
```
