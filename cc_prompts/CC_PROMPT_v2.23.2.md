# CC PROMPT — v2.23.2 — Fix task classifier, kubectl hallucination, escalation UI bugs

## What this does
Five targeted fixes: (1) Task classifier: "Find out why... give me fix steps" was routing
to the action agent (because "fix" is an action keyword and "Find" is not a question
starter) — fix by adding "find" to QUESTION_STARTERS and making "root cause" + "fix steps"
bigrams research signals that override action routing. (2) Add explicit "Docker Swarm, NOT
Kubernetes" guard to RESEARCH_PROMPT and STATUS_PROMPT — prevents kubectl hallucination.
(3) Fix ToolLine double-⚠ for escalate: remove emoji prefix from TOOL_HUMAN['escalate'].
(4) Show `degraded` tool results as `— degraded` not `failed`. (5) Deduplicate halt events:
the frontend processes `halt` twice when coordinator escalates.
Version bump: 2.23.1 → 2.23.2

---

## Change 1 — api/agents/router.py: Fix task classifier

### 1a. Add "find" and related words to QUESTION_STARTERS

Find:
```python
QUESTION_STARTERS = frozenset({
    "what", "where", "how", "which", "is", "are", "show", "list",
    "who", "when", "why", "can", "could", "does", "do",
})
```

Replace with:
```python
QUESTION_STARTERS = frozenset({
    "what", "where", "how", "which", "is", "are", "show", "list",
    "who", "when", "why", "can", "could", "does", "do",
    # Investigative starters — treat as questions even with action words present
    "find", "look", "check", "identify", "determine", "explain",
    "investigate", "diagnose", "troubleshoot", "analyse", "analyze",
})
```

### 1b. Add "root cause" and "fix steps" to RESEARCH_KEYWORDS

Find the RESEARCH_KEYWORDS frozenset. Add these bigrams:
```python
    "root cause", "fix steps", "cause and fix", "what's causing",
    "why is it", "why are", "find out why",
```

These should be inserted inside the existing `RESEARCH_KEYWORDS = frozenset({...})`.

---

## Change 2 — api/agents/router.py: Add Docker Swarm guard to prompts

### 2a. Find the STATUS_PROMPT constant

It starts with something like:
```python
STATUS_PROMPT = """You are a read-only infrastructure status agent for a Docker Swarm + Kafka cluster.
```

After the first line of STATUS_PROMPT (the role description line), insert this block at
the very start of the prompt body, before any RULES section:

```
ENVIRONMENT — READ BEFORE ANY TOOL CALL:
This platform runs Docker Swarm (NOT Kubernetes). Critical constraints:
- kubectl does NOT exist. Never suggest kubectl commands.
- Containers are managed as Swarm services (docker service ls, docker service ps).
- Worker nodes are VM hosts accessible via vm_exec() SSH tool.
- Kafka brokers run as Swarm services (kafka_broker-1, kafka_broker-2, kafka_broker-3).
- Use vm_exec(), kafka_exec(), swarm_node_status(), service_placement() — not kubectl.

```

### 2b. Find the RESEARCH_PROMPT constant (which INVESTIGATE_PROMPT aliases)

It starts with something like:
```python
RESEARCH_PROMPT = """You are an infrastructure research and log analysis agent for a Docker Swarm + Kafka cluster.
```

After the role description line, insert the same ENVIRONMENT block:

```
ENVIRONMENT — READ BEFORE ANY TOOL CALL:
This platform runs Docker Swarm (NOT Kubernetes). Critical constraints:
- kubectl does NOT exist. Never suggest kubectl commands.
- Containers are managed as Swarm services (docker service ls, docker service ps).
- Worker nodes are VM hosts accessible via vm_exec() SSH tool.
- Kafka brokers run as Swarm services (kafka_broker-1, kafka_broker-2, kafka_broker-3).
- Use vm_exec(), kafka_exec(), swarm_node_status(), service_placement() — not kubectl.
- For Kafka investigation: use kafka_broker_status, kafka_exec, service_placement, vm_exec.
- Minimum investigation depth: call at least 4 tools before synthesizing a final answer.
  If kafka_broker_status shows degraded, follow up with service_placement, vm_exec on
  the affected worker, and kafka_exec to inspect broker logs before concluding.

```

### 2c. Find the ACTION_PROMPT constant (which EXECUTE_PROMPT aliases)

Similarly insert after the role description line:

```
ENVIRONMENT — READ BEFORE ANY TOOL CALL:
This platform runs Docker Swarm (NOT Kubernetes). Critical constraints:
- kubectl does NOT exist. Never suggest kubectl commands.
- Use swarm_service_force_update(), proxmox_vm_power(), vm_exec() for operations.

```

---

## Change 3 — gui/src/components/AgentFeed.jsx: Fix escalate double-⚠ and degraded label

### 3a. Remove emoji prefix from TOOL_HUMAN['escalate']

Find:
```javascript
  escalate:                    '⚠ Escalating',
```

Replace with:
```javascript
  escalate:                    'Escalating',
```

### 3b. Fix ToolLine to distinguish degraded from error

Find the `ToolLine` function:
```javascript
function ToolLine({ item }) {
  const isErr = item.status === 'error' || item.status === 'degraded' || item.status === 'failed'
  const human = humanizeTool(item.toolName)
  return (
    <div style={{
      fontSize: 11, lineHeight: 1.6,
      color: isErr ? '#d97706' : '#6b7280',
      display: 'flex', alignItems: 'baseline', gap: 5,
    }}>
      <span style={{ flexShrink: 0, fontSize: 10 }}>{isErr ? '⚠' : '✓'}</span>
      <span>{human}{isErr ? ' failed' : ''}</span>
    </div>
  )
}
```

Replace with:
```javascript
function ToolLine({ item }) {
  const isErr      = item.status === 'error' || item.status === 'failed'
  const isDegraded = item.status === 'degraded'
  const isEscalated = item.status === 'escalated' || item.toolName === 'escalate'
  const human = humanizeTool(item.toolName)

  let icon, suffix, color
  if (isErr) {
    icon = '⚠'; suffix = ' failed'; color = '#d97706'
  } else if (isDegraded) {
    icon = '⚠'; suffix = ' — degraded'; color = '#ca8a04'
  } else if (isEscalated) {
    icon = '⚠'; suffix = ' — human review required'; color = '#f59e0b'
  } else {
    icon = '✓'; suffix = ''; color = '#6b7280'
  }

  return (
    <div style={{
      fontSize: 11, lineHeight: 1.6, color,
      display: 'flex', alignItems: 'baseline', gap: 5,
    }}>
      <span style={{ flexShrink: 0, fontSize: 10 }}>{icon}</span>
      <span>{human}{suffix}</span>
    </div>
  )
}
```

---

## Change 4 — gui/src/context/AgentOutputContext.jsx: Deduplicate halt events

The `halt` WS event is processed and adds a feed line. But escalation also fires additional
events. Add a guard to prevent duplicate escalation lines.

Find the halt handler in the `onMsg` function:
```javascript
      } else if (t === 'halt') {
        setFeedLines(prev => [...prev, { type: 'tool', toolName: 'escalate', status: 'error', content: msg.content }])
```

Replace with:
```javascript
      } else if (t === 'halt') {
        // Deduplicate: only add if no escalate line already present
        setFeedLines(prev => {
          const alreadyEscalated = prev.some(l => l.type === 'tool' && l.toolName === 'escalate')
          if (alreadyEscalated) return prev
          return [...prev, { type: 'tool', toolName: 'escalate', status: 'escalated', content: msg.content }]
        })
```

Also update the tool event handler to use 'escalated' status when toolName is 'escalate':
```javascript
      if (t === 'tool') {
        const toolName = msg.tool   || ''
        const status   = msg.status || 'ok'
        // Skip audit_log and blocked calls in the inline feed
        if (toolName !== 'audit_log' && status !== 'blocked') {
          setFeedLines(prev => [...prev, { type: 'tool', toolName, status, content: msg.content }])
        }
```

Replace the status assignment line to normalise 'escalated' status:
```javascript
      if (t === 'tool') {
        const toolName = msg.tool   || ''
        const rawStatus = msg.status || 'ok'
        // Map 'escalated' status to its own category (not 'error')
        const status = rawStatus === 'escalated' ? 'escalated' : rawStatus
        // Skip audit_log and blocked calls in the inline feed
        if (toolName !== 'audit_log' && status !== 'blocked') {
          setFeedLines(prev => {
            // Deduplicate escalate entries
            if (toolName === 'escalate') {
              const alreadyEscalated = prev.some(l => l.type === 'tool' && l.toolName === 'escalate')
              if (alreadyEscalated) return prev
            }
            return [...prev, { type: 'tool', toolName, status, content: msg.content }]
          })
        }
```

---

## Version bump

Update `VERSION`: `2.23.1` → `2.23.2`

---

## Commit

```
git add -A
git commit -m "fix(agent): classifier routing, kubectl hallucination, escalation UI bugs"
git push origin main
```
