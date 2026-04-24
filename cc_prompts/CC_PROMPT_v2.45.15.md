# CC PROMPT — v2.45.15 — fix(tests): clarification_answer + orch-escalate rework + UI Results polish

## What this does

Four test definition fixes from failure analysis + one UI polish:

**A. action-upgrade-01 and action-rollback-01 clarification_answer**
These default to "" → "cancel". Agent correctly exits on cancel via audit_log.
Fix: provide the service name so agent receives a real answer and can proceed.

**B. orch-escalate-01 broken by design**
Task: "audit and escalate any kafka broker issues found" + expect_status="escalated"
But Kafka is healthy → agent correctly doesn't escalate → test fails.
Fix: change task to FORCE an escalation call regardless of health, change
expect_status="success", remove expect_tools constraint.

**C. research-precheck-01 and research-kafkacheck-01 routing**
These route to STATUS agent (kafka keyword) → status agent uses kafka_broker_status.
Fix: prepend "investigate:" to task to hard-route to research via RESEARCH_STARTERS.
(v2.45.14 also adds pre_kafka_check to INVESTIGATE_AGENT_TOOLS so once routed
correctly, the tool is available.)

**D. ResultsTab UI: step label fix + suite filter**
The results row shows `{r.step_count}s` which looks like seconds. Fix to `{r.step_count} steps`.
Add a suite filter dropdown to the Results tab header.

Version bump: 2.45.14 → 2.45.15.

---

## Change 1 — `api/db/test_definitions.py`

CC: Change ONLY the listed fields. Do not touch anything else.

### action-upgrade-01 — add clarification_answer
Find `TestCase(id="action-upgrade-01"`. Add field:
```python
clarification_answer="workload-stack_workload",
```

### action-rollback-01 — add clarification_answer
Find `TestCase(id="action-rollback-01"`. Add field:
```python
clarification_answer="kafka-stack_kafka1",
```

### orch-escalate-01 — task + expect changes
Find `TestCase(id="orch-escalate-01"`.

Old task:
```python
task="audit and escalate any kafka broker issues found",
expect_tools=["escalate"], expect_status="escalated",
max_steps=10, timeout_s=60, soft=True,
```

New task + fields:
```python
task="use the escalate tool to report the current kafka broker health status to the operator — call escalate with a summary of broker status",
expect_tools=["escalate"],
expect_status="success",
max_steps=10, timeout_s=120, soft=True,
```

### research-precheck-01 — task only
Old:
```python
task="use the pre_kafka_check tool to verify kafka cluster readiness and report the result",
```
New:
```python
task="investigate: use the pre_kafka_check tool to verify kafka cluster readiness and report the result",
```

### research-kafkacheck-01 — task only
Old:
```python
task="use the pre_kafka_check tool to get the kafka pre-flight status check result",
```
New:
```python
task="investigate: use the pre_kafka_check tool to get the kafka pre-flight status check result",
```

---

## Change 2 — `gui/src/components/TestsPanel.jsx` — ResultsTab polish

### Fix step label
In the results row (inside ResultsTab expand section), find:
```jsx
<Mono style={{ color: 'var(--text-3)' }}>{r.step_count}s</Mono>
```
Replace with:
```jsx
<Mono style={{ color: 'var(--text-3)' }}>{r.step_count} steps</Mono>
```

### Add suite filter to ResultsTab header
In `ResultsTab`, add `suites` state and fetch, then add a filter select:

After the existing state declarations, add:
```jsx
const [suiteFilter, setSuiteFilter] = useState('')
const [suites, setSuites]           = useState([])
```

In the `load` useCallback, also fetch suites:
```jsx
api('/api/tests/suites').then(r => r.json()).then(d => setSuites(d.suites || [])).catch(() => {})
```

Filter the `runs` list before rendering:
```jsx
const visibleRuns = suiteFilter
  ? runs.filter(r => r.suite_id === suiteFilter || r.suite_name === suiteFilter)
  : runs
```

In the header row div, add a suite filter select before the refresh button:
```jsx
<select value={suiteFilter} onChange={e => setSuiteFilter(e.target.value)}
  style={{ fontFamily:'var(--font-mono)', fontSize:9, padding:'3px 7px',
    background:'var(--bg-1)', border:'1px solid var(--border)',
    color:'var(--text-2)', borderRadius:2 }}>
  <option value="">all suites</option>
  {suites.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
</select>
```

Replace `runs.map(run => (` with `visibleRuns.map(run => (` in the run list render.

---

## Version bump

Update `VERSION`: `2.45.14` → `2.45.15`

---

## Commit

```
git add -A
git commit -m "fix(tests): v2.45.15 clarification_answer + escalate rework + precheck routing + Results UI polish"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
