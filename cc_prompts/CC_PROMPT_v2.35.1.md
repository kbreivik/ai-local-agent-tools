# CC PROMPT — v2.35.1 — feat(agents): entity preflight + three-tier extractor + Preflight Panel + PREFLIGHT FACTS injection

## What this does

First behaviour change of the v2.35 phase. Before the agent loop runs,
a new preflight step resolves entity references in the task string
against `known_facts` + `infra_inventory` + `agent_actions`, and injects
matched facts into the system prompt. If references are ambiguous, a
blocking UI disambiguation modal is shown to the user.

Version bump: 2.35.0.1 → 2.35.1 (new subsystem, agent hot-path change).

Design ref: `cc_prompts/PHASE_v2.35_SPEC.md` → "Entity extraction —
three-tier pipeline" and "Preflight Panel — always visible".

---

## Change 1 — three-tier preflight resolver

New file `api/agents/preflight.py`.

```python
"""
Preflight resolver: figure out what the user's task is actually about,
before the agent loop starts.

Pipeline:
  Tier 1: regex extraction → explicit entity names
  Tier 2: keyword + time-window DB lookup → action-verb resolution
  Tier 3: LLM fallback → natural-language extraction (bounded)

Output is a PreflightResult with:
  - candidates:    list of resolved entities (0..N)
  - ambiguous:     true when candidates > 1 and human disambiguation needed
  - preflight_facts: list of known_facts to inject into system prompt
  - trace:         explanation of how each piece was resolved (for Preflight Panel)
"""

from dataclasses import dataclass, field
import re

@dataclass
class PreflightCandidate:
    entity_id:   str              # e.g. "kafka_broker-3"
    entity_type: str              # e.g. "swarm_service"
    source:     str               # 'regex' | 'keyword_db' | 'llm_fallback'
    confidence: float             # 0..1
    evidence:   str               # human-readable "why"
    metadata:   dict = field(default_factory=dict)


@dataclass
class PreflightResult:
    task:            str
    agent_type:      str
    candidates:      list
    ambiguous:       bool
    preflight_facts: list         # known_facts rows ready to inject
    trace:           list          # step-by-step resolution log
    tier_used:       str           # final tier that produced candidates
    clarifying_needed: bool


# ── Tier 1: regex ─────────────────────────────────────────────────────

ENTITY_PATTERNS = [
    (r'\bkafka_broker-\d+\b',            'kafka_broker'),
    (r'\bds-docker-(?:manager|worker)-\d+\b', 'swarm_node'),
    (r'\bhp1-prod-\w+\b',                'proxmox_vm'),
    (r'\blogstash(?:_\w+)?\b',           'swarm_service'),
    (r'\belasticsearch(?:_\w+)?\b',      'swarm_service'),
    (r'\b(?:nginx|caddy|traefik)(?:_\w+)?\b', 'swarm_service'),
    # Container short ID (12 hex chars at word boundary, standalone)
    (r'\b[0-9a-f]{12}\b',                'container_id'),
    # VM/host FQDN-ish
    (r'\b[a-z][a-z0-9]+(?:-[a-z0-9]+){1,4}\b', 'generic_host'),
]


def tier1_regex_extract(task: str) -> list:
    hits = []
    for pattern, kind in ENTITY_PATTERNS:
        for m in re.finditer(pattern, task, re.IGNORECASE):
            hits.append(PreflightCandidate(
                entity_id=m.group(0),
                entity_type=kind,
                source='regex',
                confidence=0.9,
                evidence=f"regex match on pattern for {kind}",
            ))
    # Deduplicate by entity_id, keeping highest-specificity match (more specific patterns first in list)
    seen, out = set(), []
    for c in hits:
        key = (c.entity_id.lower(), c.entity_type)
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


# ── Tier 2: keyword + time-window DB lookup ───────────────────────────

# Keyword → (DB query function, implicit time window)
KEYWORD_RESOLVERS = {
    'restarted':   ('_lookup_recent_restart_actions', None),
    'restart':     ('_lookup_recent_restart_actions', None),
    'rebooted':    ('_lookup_recent_reboot_actions', None),
    'reboot':      ('_lookup_recent_reboot_actions', None),
    'upgraded':    ('_lookup_recent_upgrade_actions', None),
    'upgrade':     ('_lookup_recent_upgrade_actions', None),
    'degraded':    ('_lookup_degraded_entities', None),
    'failing':     ('_lookup_failing_entities', None),
    'offline':     ('_lookup_offline_entities', None),
    'broken':      ('_lookup_recent_errors', None),
    'crashed':     ('_lookup_recent_crashes', None),
    'alerting':    ('_lookup_alerting_entities', None),
    'deployed':    ('_lookup_recent_deployments', None),
    'scaled':      ('_lookup_recent_scale_events', None),
}

# Time-window hints (modifies the lookup's default window)
TIME_HINTS = {
    'just':       30,        # minutes
    'moments ago':10,
    'recently':   120,
    'today':      1440,      # today = 24h ish
    'yesterday':  2880,
    'last hour':  60,
    'last night': 720,       # 12h ish
    'this morning': 360,
}

# DB-editable keyword corpus: table populated by init, overridable via Settings
def load_keyword_corpus() -> dict:
    """Merge hardcoded defaults with DB-editable rows from
       known_facts_keywords table (seeded from KEYWORD_RESOLVERS on init)."""

def tier2_keyword_db(task: str, trace: list) -> list:
    task_lower = task.lower()
    corpus = load_keyword_corpus()

    # Extract matching time-window hints
    time_window_min = None
    for hint, minutes in TIME_HINTS.items():
        if hint in task_lower:
            time_window_min = min(time_window_min or minutes, minutes)
            trace.append(f"time-hint '{hint}' → window {minutes}min")

    # Find triggered keyword resolvers
    triggered = []
    for kw, (resolver_name, default_win) in corpus.items():
        if re.search(rf'\b{re.escape(kw)}\b', task_lower):
            window = time_window_min or default_win or 60  # default 1h
            triggered.append((kw, resolver_name, window))

    if not triggered:
        return []

    # Execute resolvers
    candidates = []
    for kw, resolver_name, window in triggered:
        trace.append(f"keyword '{kw}' → resolver {resolver_name}(window={window}min)")
        resolver = KEYWORD_RESOLVER_FUNCS.get(resolver_name)
        if not resolver:
            continue
        hits = resolver(window_min=window)
        for h in hits:
            candidates.append(PreflightCandidate(
                entity_id=h['entity_id'],
                entity_type=h['entity_type'],
                source='keyword_db',
                confidence=0.75,
                evidence=f"{kw} in last {window}min",
                metadata={'keyword': kw, 'window_min': window, **h},
            ))
    return candidates


# ── Resolver implementations ──────────────────────────────────────────

def _lookup_recent_restart_actions(window_min: int = 60) -> list[dict]:
    """Query agent_actions + vm_action_log for restart ops in last N min."""

def _lookup_recent_reboot_actions(window_min: int = 60) -> list[dict]:
    """VM reboots via proxmox_vm_power, swarm restarts, container restarts."""

def _lookup_recent_upgrade_actions(window_min: int = 1440) -> list[dict]:
    """Image pulls + service updates in last N min."""

def _lookup_degraded_entities(window_min: int = 60) -> list[dict]:
    """entity_history transitions to Degraded status."""

def _lookup_failing_entities(window_min: int = 60) -> list[dict]:
    """entity_history: status Failed or similar, or alert_transitions."""

def _lookup_offline_entities(window_min: int = 60) -> list[dict]:
    """entity_history: status Down or missing from most recent snapshot."""

def _lookup_recent_errors(window_min: int = 60) -> list[dict]:
    """elastic_search_logs level=error + entity correlation."""

def _lookup_recent_crashes(window_min: int = 60) -> list[dict]:
    """Similar to errors, scoped to crash signatures (OOM, SIGKILL, exit 137)."""

def _lookup_alerting_entities(window_min: int = 60) -> list[dict]:
    """alerts table, status=firing."""

def _lookup_recent_deployments(window_min: int = 1440) -> list[dict]:
    """agent_actions action=deploy OR image pulls."""

def _lookup_recent_scale_events(window_min: int = 60) -> list[dict]:
    """Swarm replica count changes, scrub from entity_history or a scaler log."""

KEYWORD_RESOLVER_FUNCS = {
    '_lookup_recent_restart_actions': _lookup_recent_restart_actions,
    '_lookup_recent_reboot_actions':  _lookup_recent_reboot_actions,
    '_lookup_recent_upgrade_actions': _lookup_recent_upgrade_actions,
    '_lookup_degraded_entities':      _lookup_degraded_entities,
    '_lookup_failing_entities':       _lookup_failing_entities,
    '_lookup_offline_entities':       _lookup_offline_entities,
    '_lookup_recent_errors':          _lookup_recent_errors,
    '_lookup_recent_crashes':         _lookup_recent_crashes,
    '_lookup_alerting_entities':      _lookup_alerting_entities,
    '_lookup_recent_deployments':     _lookup_recent_deployments,
    '_lookup_recent_scale_events':    _lookup_recent_scale_events,
}


# ── Tier 3: LLM fallback ──────────────────────────────────────────────

async def tier3_llm_fallback(task: str, trace: list) -> list:
    """
    Last-resort extraction via LM Studio. Bounded to ~200 tokens.
    Used only when Tier 1+2 found nothing meaningful.

    Prompt:
      "List named infrastructure entities mentioned in this sentence.
       Return JSON array of strings only, no explanation. If none, [].
       Sentence: <task>"

    Only fires if preflightLLMFallbackEnabled=True.
    """
    settings = _get_facts_settings()
    if not settings.get('preflightLLMFallbackEnabled', True):
        return []

    max_tokens = settings.get('preflightLLMFallbackMaxTokens', 200)
    trace.append(f"tier3 LLM fallback (max_tokens={max_tokens})")

    # Existing LM Studio client
    raw = await _llm_extract_entities(task, max_tokens)
    try:
        names = json.loads(raw)
        assert isinstance(names, list)
    except Exception:
        trace.append(f"tier3 LLM response unparseable: {raw[:80]}")
        return []

    hits = []
    for n in names:
        if not isinstance(n, str) or not n.strip():
            continue
        hits.append(PreflightCandidate(
            entity_id=n.strip(),
            entity_type='unknown',
            source='llm_fallback',
            confidence=0.5,
            evidence='LLM extraction from natural language',
        ))
    return hits


# ── Entry point ───────────────────────────────────────────────────────

async def preflight_resolve(task: str, agent_type: str) -> PreflightResult:
    trace = [f"task: {task[:80]}", f"agent_type: {agent_type}"]

    # Tier 1
    t1 = tier1_regex_extract(task)
    trace.append(f"tier1: {len(t1)} regex matches")

    # Tier 2
    t2 = tier2_keyword_db(task, trace)
    trace.append(f"tier2: {len(t2)} keyword-DB matches")

    candidates = t1 + t2
    tier_used = 'tier1+2'

    # Tier 3 only if tier 1+2 were shallow
    if len(candidates) == 0 and len(task) >= 50:
        t3 = await tier3_llm_fallback(task, trace)
        trace.append(f"tier3: {len(t3)} LLM candidates")
        candidates = t3
        tier_used = 'tier3'

    # Resolve each candidate against infra_inventory + known_facts
    resolved, preflight_facts = resolve_against_inventory(candidates, trace)

    # Determine ambiguity: >1 distinct entity matching a vague candidate
    ambiguous = any(len(r['matches']) > 1 for r in resolved)

    return PreflightResult(
        task=task,
        agent_type=agent_type,
        candidates=resolved,
        ambiguous=ambiguous,
        preflight_facts=preflight_facts,
        trace=trace,
        tier_used=tier_used,
        clarifying_needed=ambiguous,
    )


def resolve_against_inventory(candidates: list, trace: list) -> tuple[list, list]:
    """
    For each candidate, find matches in infra_inventory + known_facts.
    Returns (resolved_list, preflight_facts_to_inject).

    resolved_list shape:
      [{candidate: <PreflightCandidate>,
        matches: [{entity_id, display_name, metadata}, ...]}]
    """
    resolved = []
    facts_to_inject = []
    for c in candidates:
        matches = lookup_inventory(c.entity_id, c.entity_type)
        trace.append(f"'{c.entity_id}': {len(matches)} inventory matches")

        # For unambiguous matches, attach their known_facts
        if len(matches) == 1:
            m = matches[0]
            fact_rows = get_confident_facts_for_entity(m['entity_id'])
            facts_to_inject.extend(fact_rows)
            trace.append(f"'{c.entity_id}' → {m['entity_id']}: {len(fact_rows)} facts")

        resolved.append({'candidate': c, 'matches': matches})
    return resolved, facts_to_inject
```

## Change 2 — keyword corpus DB table

Extend `api/db/known_facts.py` with a keyword corpus table seeded from
the hardcoded defaults in Change 1. DB-editable via Settings UI.

```sql
CREATE TABLE IF NOT EXISTS known_facts_keywords (
    keyword        TEXT PRIMARY KEY,
    resolver_name  TEXT NOT NULL,
    default_window_min INT,
    description    TEXT NOT NULL DEFAULT '',
    active         BOOLEAN NOT NULL DEFAULT TRUE,
    added_by       TEXT NOT NULL DEFAULT 'system',
    added_at       TIMESTAMPTZ DEFAULT NOW()
);
```

On init, insert the hardcoded `KEYWORD_RESOLVERS` entries with
`ON CONFLICT DO NOTHING`. `load_keyword_corpus()` reads active rows.

Endpoint `GET /api/facts/keywords` and `POST /api/facts/keywords` for
management UI. Writes require sith_lord role. Adds `auto-propose`
flow: when Tier 3 LLM fires successfully, any extracted entities that
were NOT caught by Tier 1/2 trigger a "suggested new keyword" row in
a new `known_facts_keyword_suggestions` table for admin review.

## Change 3 — wire preflight into agent loop

In `api/routers/agent.py` (or wherever the agent task endpoint lives),
before spawning the main agent loop:

```python
from api.agents.preflight import preflight_resolve

@router.post("/api/agent/run")
async def run_agent(body: dict, ...):
    task = body["task"]
    agent_type = classify_task(task)

    # NEW: preflight resolution
    preflight = await preflight_resolve(task, agent_type)

    # If ambiguous, DO NOT start the agent loop. Return a
    # "clarifying_needed" response with the candidates list.
    if preflight.clarifying_needed:
        # Write a pending operation row so the UI can resume after user picks
        op_id = create_operation_row(
            task=task,
            status='awaiting_clarification',
            metadata={'preflight': preflight.as_dict()},
        )
        return {
            'operation_id': op_id,
            'status': 'awaiting_clarification',
            'preflight': preflight.as_dict(),
            'candidates': [_serialize_candidate(c) for c in preflight.candidates],
        }

    # Otherwise, proceed with agent loop. Inject preflight facts into prompt.
    system_prompt = build_system_prompt(agent_type,
                                         preflight_facts=preflight.preflight_facts,
                                         preflight_trace=preflight.trace)
    ...
```

Add a resume endpoint:

```python
@router.post("/api/agent/operations/{op_id}/clarify")
async def clarify_operation(op_id: str, body: dict, user=Depends(get_current_user)):
    """
    Body: {selected_entity_id: str} or {refined_task: str}
    Resumes a paused operation with the user's picked entity or rewritten task.
    """
    op = get_operation(op_id)
    if op['status'] != 'awaiting_clarification':
        raise HTTPException(409, 'Operation is not awaiting clarification')

    if 'refined_task' in body:
        # User rewrote the task. Re-run preflight from scratch.
        resolution = await preflight_resolve(body['refined_task'], op['agent_type'])
        ...
    elif 'selected_entity_id' in body:
        # User picked one of the candidates. Pin it and proceed.
        ...
    else:
        raise HTTPException(400, 'Must provide selected_entity_id or refined_task')

    update_operation_status(op_id, 'running')
    # Spawn agent loop as normal
    ...
```

Timeout: if a clarification-pending op is idle for
`preflightDisambiguationTimeout` seconds (default 300), auto-cancel.
Background task checks every 60s, marks stale ops as `status=cancelled`,
reason=`clarification_timeout`.

## Change 4 — PREFLIGHT FACTS prompt section

In `api/agents/router.py`, extend the system-prompt builder to take
an optional `preflight_facts` list and a `preflight_trace`.

Insert BEFORE the existing `RELEVANT PAST OUTCOMES` section:

```
═══ PREFLIGHT FACTS (confidence ≥ {factInjectionThreshold}, verified within refresh cadence) ═══
prod.kafka.broker.3.host             = "192.168.199.33"  (source: proxmox_collector, age: 3min, conf: 0.92)
prod.kafka.broker.3.port             = 9094              (source: kafka_collector, age: 3min, conf: 0.88)
prod.swarm.service.kafka_broker-3.placement = ["ds-docker-worker-03"]  (source: swarm_collector, age: 30s, conf: 0.95)
prod.proxmox.vm.hp1-prod-worker-03.status   = "running"  (source: proxmox_collector, age: 45s, conf: 0.92)

These facts come from infrastructure collectors. Cite them in your
EVIDENCE block. Do NOT call a tool to re-verify unless you suspect
the fact is stale or you need a value not listed above.

═══ PREFLIGHT TRACE ═══
(short bullets — how the candidates were resolved)
```

Capped at `factInjectionMaxRows` entries (default 40). Sorted by
confidence descending.

If `preflightPanelMode=off`, skip the section entirely (pre-v2.35.1
behaviour).

If `preflight_facts` is empty but a trace exists, still emit a short
trace-only section so the agent (and operator via `/trace`) knows
preflight ran but found nothing.

## Change 5 — Preflight Panel (UI)

New file `gui/src/components/PreflightPanel.jsx`.

Appears above the agent feed in the Commands view whenever an
operation is `awaiting_clarification` OR when `preflightPanelMode` is
`always_visible` and an operation is starting.

Structure:

```
┌─ PREFLIGHT ─────────────────────────────────────────┐
│ Classifier:     research                            │
│ Extracted:      ["broker"]  ← ambiguous             │
│ Time window:    "just" → last 30 min                │
│ Keywords:       ["restarted"]                       │
│ Facts to inject: 4                                  │
│                                                     │
│ Candidate matches (3):                              │
│   ○ 1. kafka_broker-3  (restart 4min ago by sith)   │
│   ○ 2. nginx_ingress   (restart 19min ago, auto)    │
│   ○ 3. elasticsearch_data-2 (restart 28min ago)     │
│                                                     │
│ [ Pick candidate #___ ]  [ Edit task ]  [ Cancel ]  │
└─────────────────────────────────────────────────────┘
```

Collapsed (one-line) when no ambiguity + no surprises + setting is
`always_visible`. Expanded when choice needed.

Auto-cancel countdown visible in expanded state ("auto-cancel in
4:32"). Timer is client-side visual; backend enforces via its own
timeout.

## Change 6 — settings + Prometheus

Wire the Settings group keys from v2.35.0 that govern preflight behaviour:

- `preflightPanelMode`
- `preflightDisambiguationTimeout`
- `preflightLLMFallbackEnabled`
- `preflightLLMFallbackMaxTokens`
- `factInjectionThreshold`
- `factInjectionMaxRows`

Add Prometheus metrics:

```python
PREFLIGHT_RESOLUTIONS_COUNTER = Counter(
    "deathstar_preflight_resolutions_total",
    "Preflight resolution outcomes",
    ["outcome"],   # direct | regex | keyword_db | llm_fallback | ambiguous | zero_hit
)

PREFLIGHT_DISAMBIGUATION_OUTCOME_COUNTER = Counter(
    "deathstar_preflight_disambiguation_outcome_total",
    "How users resolved an ambiguous preflight",
    ["result"],    # auto_proceed | user_picked | cancelled | timeout
)

PREFLIGHT_FACTS_INJECTED = Histogram(
    "deathstar_preflight_facts_injected_count",
    "Facts injected per preflight",
    buckets=(0, 1, 2, 5, 10, 20, 40, 100),
)
```

## Change 7 — tests

`tests/test_preflight.py`:

- Tier 1: `"restart kafka_broker-3"` → 1 candidate `kafka_broker-3`
- Tier 2: `"the broker we just restarted"` → queries agent_actions,
  fixture 1 match → 1 candidate
- Tier 2 ambiguous: fixture 3 restart actions in last 30min → 3
  candidates, ambiguous=True
- Tier 3: `"a really vague task about that thing"` with LLM mock →
  tier 3 fires, returns [] or stubbed names
- `preflight_facts` populated for unambiguous single match
- Timeout: a stale pending op is auto-cancelled

`tests/test_preflight_prompt_injection.py`:

- Given a preflight with 3 facts, system_prompt contains PREFLIGHT FACTS
  section with each fact as a line
- `preflightPanelMode=off` → section absent

## Change 8 — Prompt snapshots update

Running v2.35.1 changes the baseline rendered prompts. Regenerate the
snapshots:

```
pytest tests/test_prompt_snapshots.py --update-snapshots
git add tests/snapshots/prompts/
```

The diffs should show ONLY the new PREFLIGHT FACTS section template.
If anything else changed, that's a regression to investigate.

## Commit

```
git add -A
git commit -m "feat(agents): v2.35.1 entity preflight + three-tier extractor + Preflight Panel + PREFLIGHT FACTS"
git push origin main
```

## Test after deploy

1. Fire the canonical Logstash investigate task — preflight runs, but
   "Logstash" is unambiguous (one service), so no clarifier. PREFLIGHT
   FACTS section visible in `/trace`, listing broker 3 host + port and
   service placement.
2. Fire `"restart the broker we just rebooted"` with NO recent restart
   actions → tier 2 returns 0 candidates, tier 3 may fire, depending on
   fallback setting.
3. Manually insert 3 synthetic restart actions into `agent_actions` via
   psql with `ts > now() - '30 min'`. Fire the same task → 3 candidates
   appear, Preflight Panel opens, user picks #1 → operation proceeds.
4. Preflight Panel timeout: fire ambiguous task, walk away for 5+ min →
   operation auto-cancelled, Prometheus counter increments on `timeout`.
5. `/metrics | grep preflight_` shows all three new metric families
   incrementing.

## Non-goals

- Multi-language tasks (English only for now; the keyword corpus is
  English).
- Speech-to-text input + preflight (out of scope).
- Preflight for sub-agent tasks (sub-agents inherit parent context;
  no separate preflight pass).

## Risk register

- Tier 3 LLM fallback adds latency (~1-3s) to task startup. Most tasks
  shouldn't hit it. Monitor via `preflight_resolutions_total{outcome=llm_fallback}`.
- Keyword corpus evolution is a long-term project. v2.35.1 ships with
  ~15 defaults + auto-propose suggestions flow.
- Blocking the agent on ambiguity is a new UX pattern. If operators
  find it disruptive, setting `preflightPanelMode=on_ambiguity` or
  tuning the timeout gives them escape hatches.
