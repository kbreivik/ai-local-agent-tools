# Phase v2.35 — Facts, not just tools

## Status

**Locked spec.** All open questions resolved. Five CC prompts drafted:
v2.35.0 → v2.35.4. Executable via `run_queue.sh`.

---

## Phase goal

Shift the agent from "rediscover the world on every task" to "start from
facts, verify only what's uncertain." Introduce a persistent, weighted,
contradiction-aware knowledge store (`known_facts`) and wire the agent
loop to consult it at preflight, during tool execution, and at synthesis.

## Work items

| Prompt | Theme |
|---|---|
| v2.35.0 | known_facts schema + collector writers + `/api/facts` endpoint + Settings group + Prometheus |
| v2.35.0.1 | Facts UI tab + Dashboard status widget + diff viewer |
| v2.35.1 | Entity preflight: three-tier extractor + Preflight Panel + blocking disambiguation |
| v2.35.2 | In-run cross-tool contradiction detection + agent_observation writer |
| v2.35.3 | Fact-age rejection (Medium mode) on tool results |
| v2.35.4 | Runbook-based TRIAGE — augment mode |

v2.35.0.1 is a small GUI-only bump, run immediately after v2.35.0 lands.
The GUI was flagged as due for a refresh; we'll accept whatever shape CC
produces for v2.35.0.1 and iterate later if needed.

---

## Locked design decisions

### Fact keys

- Convention: `prod.<platform>.<entity>.<attribute>`
- Lowercase, dotted, stable across sources
- Examples:
  - `prod.kafka.broker.3.host` → `"192.168.199.33"`
  - `prod.swarm.service.kafka_broker-3.placement` → `["ds-docker-worker-03"]`
  - `prod.proxmox.vm.hp1-prod-worker-03.status` → `"running"`
  - `prod.container.f3ef70283135.service_name` → `"logstash_logstash"`
- Multi-valued facts use JSONB arrays, not multi-row

### Storage — three-table model

```sql
known_facts_current           -- 1 row per (fact_key, source), the live value
known_facts_history           -- append-only, only when value CHANGED
known_facts_conflicts         -- rows where collector disagrees with a locked fact
known_facts_locks             -- admin-asserted "don't overwrite" on specific keys
known_facts_permissions       -- user + role grants for admin ops
known_facts_refresh_schedule  -- per-key-pattern expected poll cadence
```

History is append-only but deduplicated: only insert a history row when
the value actually changes vs the previous current value. Proxmox status
polled every 60s for 30 VMs that never change = 0 history rows, not 43k.

Each current row has a `change_detected` boolean flipped true for 24h
after the most recent history write. Dashboard widgets use this for
"infrastructure changed recently" signal.

### Confidence scoring — 5-level ladder

```
0.9 – 1.0   Very High    Manual (fresh, non-decayed) or multi-collector agreement
0.7 – 0.89  High         Single collector, recently verified       ← INJECTION THRESHOLD
0.5 – 0.69  Medium       Collector aging, or agent observation with no contradiction
0.3 – 0.49  Low          Stale, or observation contradicted
0.0 – 0.29  Reject       Heavily stale or collector-contradicted
```

All thresholds and source weights live in Settings group
"Facts & Knowledge" with a live Preview panel showing computed confidence
on real rows given current settings.

### Source weights (defaults, tunable in Settings)

| Source | Weight | Half-life (hours) |
|---|---|---|
| `manual` | 1.0 | ∞ (decay only, see below) |
| `proxmox_collector` | 0.9 | 168 (7d) |
| `swarm_collector` | 0.9 | 168 |
| `docker_agent_collector` | 0.85 | 168 |
| `pbs_collector` | 0.85 | 168 |
| `kafka_collector` | 0.8 | 168 |
| `fortiswitch_collector` | 0.85 | 168 |
| `agent_observation` | 0.5 | 24 (1d) |
| `rag_extraction` | 0.4 | 720 (30d) |

### Manual fact lifecycle

Manual facts persist forever by default. They decay gently via the
confidence formula only — they never disappear:

- First 30 days: confidence = 0.9 base × source_weight 1.0 = 1.0
- Days 30-60: base slowly decays to 0.7
- Days 60+: base decays below 0.7 → stops being injected into prompts
- Operator sees a "refresh suggested" UI pill on stale manual facts
- Clicking refresh re-asserts the fact (updates `last_verified`) — no new row
- Hard expiry never happens; facts only fade, never disappear

### Refresh cadence per platform (defaults, tunable)

| Pattern | Cadence | Reason |
|---|---|---|
| `prod.proxmox.vm.*.status` | 60s | Changes fast |
| `prod.swarm.service.*.placement` | 30s | Orchestrator moves |
| `prod.kafka.broker.*.host` | 3600s | Rarely changes |
| `prod.container.*.ip` | 300s | DHCP rare |
| `prod.container.*.id` | on-change | Event-driven |
| `prod.manual.*` | 24h | Reminder only |
| default | 300s | Fallback for unmatched keys |

These live in `known_facts_refresh_schedule` and drive the
"fact is stale" UI badge and the confidence age decay.

### Permissions — user + role model

Two tables for granting admin ops on facts:

```sql
known_facts_permissions (
    grantee_type TEXT CHECK (grantee_type IN ('user','role')),
    grantee_id   TEXT,                     -- username or role name
    action       TEXT,                     -- 'lock', 'unlock', 'manual_write', 'delete'
    fact_pattern TEXT,                     -- 'prod.*' or 'prod.kafka.*' or exact key
    granted_at   TIMESTAMPTZ,
    granted_by   TEXT,
    expires_at   TIMESTAMPTZ               -- NULL = forever
);
```

- `sith_lord` has full permission on all patterns (implicit grant, not a row)
- Other roles/users inherit nothing by default
- Permissions can be granted per-user OR per-role
- User-level grants OVERRIDE role-level (user can be explicitly revoked)
- Expires_at supports one-off grants (e.g. "imperial_officer can lock
  prod.kafka.* for 24 hours")
- All admin ops log to `connection_audit_log` or a new `facts_audit_log`

### Conflict resolution UI — permission-gated

When a collector poll produces a value that contradicts a LOCKED fact:

1. Poll value is NOT written to `known_facts_current` (lock wins)
2. Row written to `known_facts_conflicts` with both values + timestamps
3. Banner appears on Dashboard: "1 fact conflict pending admin review"
4. Click → modal showing locked value, collector value, evidence,
   source reliability; three buttons:
   - **Keep lock** (dismiss conflict, log who/when)
   - **Accept collector value** (update lock or remove it, log who/when)
   - **Edit lock** (admin types a new value, log who/when)
5. All three actions require a user with `unlock` permission on the
   fact_pattern. Lower-permission users see the banner but click opens
   a read-only view.

### Dashboard status widget

First-class widget in the Dashboard, not buried in Logs:

- Title: "FACTS & KNOWLEDGE"
- Total facts, breakdown by confidence tier
- Last collector refresh time + stale-count (facts past their cadence)
- Pending admin reviews (conflict count, red if >0)
- Recently changed facts (top 3, last 1h)
- Click → full Facts view

### Diff viewer — v2.35.0.1+

For any fact with a history chain, the Facts tab shows a diff viewer:

- Left: prior value, timestamp, source, user (if manual)
- Right: current value
- Character-level diff for strings, structured diff for JSON
- Forward/back buttons to walk the history
- Extensible: same component will later diff switch/firewall configs
  and Linux/Windows firewall rules if those collectors ship

### Entity extraction — three-tier pipeline

```
Task string → Preflight Resolver
  Tier 1: regex extraction (patterns for known entity name shapes)
  Tier 2: keyword-to-DB lookup (action verbs + time-window hints → DB queries)
  Tier 3: LLM fallback (only if Tier 1+2 found nothing meaningful)
```

Tier 2 examples:
- "the broker we just restarted" → keyword `restart` + hint `just` (≤30min)
  → SELECT FROM agent_actions WHERE action='restart' AND ts > now()-'30min'
- "the container failing in ES" → keyword `failing` + `ES` → entity_history
  transitions + elastic_search_logs errors last 1h

Result sets:
- 1 match → auto-proceed, PREFLIGHT FACTS injected
- 2-10 matches → **blocking UI disambiguation modal**
- >10 matches → show top 10 by recency, ask for narrowing
- 0 matches → Tier 3 LLM fallback, bounded to 200 tokens

### Preflight Panel — always visible

A panel in the agent-run UI showing:
- Classifier output: agent type, reason
- Extracted entities (Tier 1 + 2 findings)
- Time-window hints resolved
- Candidate matches (if any ambiguity)
- Facts being injected into PREFLIGHT FACTS section
- Buttons: `[PROCEED]` `[EDIT TASK]` `[CANCEL]`

Collapsed when zero ambiguity + zero surprises. Expanded when anything
needs user attention. Auto-cancel after 5 min idle in blocking state.

### Fact-age rejection — Medium mode

When a tool result reports a value that contradicts a `known_facts_current`
row with confidence ≥0.85 AND verified within last N minutes (default 5):

- Tool result stored as normal, BUT the contradicting value is stripped
- Agent sees: `{ok: true, value_for_X: "[REJECTED_BY_FACT_AGE]", _rejected_by_fact_age: {tool_value, known_value, source, last_verified, confidence}}`
- Agent cannot cite the rejected value. Can cite `known_value` from context.
- Harness injects: `[harness] Tool X reported a value for Y that was rejected because it contradicts a recent collector fact. If you believe the fact is stale, call the verification tool Z.`
- Aggression level ("soft" / "medium" / "hard") is a Settings toggle

### Runbook-based TRIAGE — augment-first rollout

```
Setting: runbookInjectionMode ∈ {off, augment, replace, replace+shrink}
```

- **off** — pre-v2.35.4 behaviour, prompt unchanged
- **augment** (default for v2.35.4) — classifier picks a runbook by
  keyword match; runbook body injected AFTER existing prompt section
  with header `═══ ACTIVE RUNBOOK: <name> ═══`
- **replace** — runbook replaces the matching prompt section entirely
- **replace+shrink** — RESEARCH_PROMPT becomes thin framework, all
  playbook content lives in DB runbooks

Rollout plan:
- v2.35.4 ships `augment` as default
- 2-3 weeks of trace diffs comparing augment-on vs augment-off
- If quality holds or improves: flip to `replace`, wait 2 more weeks
- If `replace` holds: flip to `replace+shrink`, delete embedded content
- If ANY stage regresses: back off, diagnose via trace viewer, fix

Classifier: v1 uses simple keyword matching against
`runbooks.triage_keywords`. If that proves insufficient, v2.35.5 can add
embedding-based semantic match.

Runbooks are DB-editable (UI in v2.35.4) so prompt-layer tweaks don't
need code deploys.

### Rollout progress

- v2.35.4 ships `runbookInjectionMode=augment` as default
- Observation window: 2-3 weeks of trace data compared against
  `augment=off` control runs
- Success criteria for promotion to `replace`:
  - No degradation in final_answer quality (measured by
    completion status: % completed vs failed/capped)
  - No increase in `tool_signature_errors` or `fabrication_detected`
  - No increase in halluc_guard_exhausted runs
  - Positive or neutral change in average tool-calls-to-diagnosis
- Promotion to `replace+shrink` requires 2 more weeks at `replace`
- Rollback: setting flip only, no code change

---

## Settings → Facts & Knowledge (new group)

All defaults tunable via GUI, persisted to `settings` table.

**Fact weights & thresholds**
- `factInjectionThreshold` — 0.7
- `factInjectionMaxRows` — 40
- `factSourceWeight_manual` — 1.0
- `factSourceWeight_collectors` — 0.9 (uniform, per-collector overrides below)
- `factSourceWeight_proxmox` — 0.9
- `factSourceWeight_swarm` — 0.9
- `factSourceWeight_docker_agent` — 0.85
- `factSourceWeight_pbs` — 0.85
- `factSourceWeight_kafka` — 0.8
- `factSourceWeight_fortiswitch` — 0.85
- `factSourceWeight_agent` — 0.5
- `factSourceWeight_rag` — 0.4

**Decay**
- `factHalfLifeHours_collector` — 168 (7d)
- `factHalfLifeHours_agent` — 24 (1d)
- `factHalfLifeHours_manual_phase1` — 720 (30d, full confidence)
- `factHalfLifeHours_manual_phase2` — 1440 (60d, decay to 0.7)
- `factVerifyCountCap` — 10

**Refresh cadences** (per-pattern, editable table in UI)
- Defaults as per "Refresh cadence per platform" section above

**Age rejection**
- `factAgeRejectionMode` — `medium` (off / soft / medium / hard)
- `factAgeRejectionMaxAgeMin` — 5
- `factAgeRejectionMinConfidence` — 0.85

**Runbook injection**
- `runbookInjectionMode` — `augment` (off / augment / replace / replace+shrink)
- `runbookClassifierMode` — `keyword` (keyword / semantic / llm)

**Preflight**
- `preflightPanelMode` — `always_visible` (always / on_ambiguity / off)
- `preflightDisambiguationTimeout` — 300 (seconds before auto-cancel)
- `preflightLLMFallbackEnabled` — true
- `preflightLLMFallbackMaxTokens` — 200

**Settings Preview panel** shows live computed confidence for 10 sample
facts given current settings. Edit a weight or half-life → preview
updates → operator sees immediate impact before saving.

---

## Prometheus metrics

```
deathstar_known_facts_total                           # gauge
deathstar_known_facts_confident_total                 # gauge, confidence >= factInjectionThreshold
deathstar_known_facts_conflicts_total                 # gauge, pending admin review
deathstar_facts_upserted_total{source, action}        # counter: action in {insert, update, history, contradiction}
deathstar_facts_contradictions_total{source_a, source_b}  # counter
deathstar_facts_lock_events_total{action}             # counter: action in {created, removed, enforced, overridden}
deathstar_facts_refresh_stale_total{platform}         # gauge, facts past expected cadence
deathstar_facts_age_rejections_total{source}          # counter
deathstar_preflight_resolutions_total{outcome}        # counter: outcome in {regex, keyword_db, llm_fallback, ambiguous, zero_hit, direct}
deathstar_preflight_disambiguation_outcome_total{result}  # counter: auto_proceed, user_picked, cancelled, timeout
deathstar_runbook_matches_total{runbook_name, mode}   # counter
deathstar_runbook_selection_decisions_total{classifier_mode, outcome}
```

---

## Non-goals (deferred past v2.35)

- Fact-based priority queue for the skill auto-promoter
- Fact garbage collection / compaction
- Export-to-CSV of known_facts for audit
- Replay mode using known_facts snapshots
- Cross-repo shared fact store (multi-DEATHSTAR federation)
- Real-time WebSocket push of fact changes to Dashboard
- Semantic similarity classifier for runbook selection (v2.35.5+)
- Config-file diff (switch/firewall/OS firewall) — data infrastructure
  exists after v2.35.0.1 diff viewer, but collectors not implemented
