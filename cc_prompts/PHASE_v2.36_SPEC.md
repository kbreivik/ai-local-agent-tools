# Phase v2.36.x — External AI Routing

Spec locked 2026-04-20 after v2.35.21 external AI "Test Connection" wiring landed
and revealed that `requireConfirmation`, `autoEscalate`, and `externalProvider`
are UI-only stubs with **zero Python consumers**. This phase turns those stubs
into a real subsystem.

## Goals

1. When the local Qwen3-Coder-Next agent is clearly stuck (budget exhausted,
   fabricated, guard-exhausted, prior-attempts failed, or complex task that
   Qwen historically fails on), route to an external AI (Claude / OpenAI / Grok)
   instead of shipping a garbage final_answer.
2. Make the Test Connection button's promise actually hold: operators can pick
   a provider + model in Settings and the agent loop honours that choice.
3. Log provenance correctly. Today `agent_llm_traces.model` always reads the
   env-default LM Studio model name even when (eventually) a non-LM-Studio
   client is used. Fix at the source.
4. Gate everything behind `requireConfirmation` when set, with a modal that
   reuses the v2.35.1 `awaiting_clarification` pattern.
5. Keep the operator fully in control: hard cap on external calls per op,
   halt-on-failure (no silent local fallback), drop output that fails
   fabrication detection and log it as `rejected_by_gate`.

## Scope decisions (locked)

- **Scope bump**: v2.36.0 new subsystem (`x.1.x` per rationale), not a patch.
- **Default master switch**: `externalRoutingMode=off`. No production
  behaviour change on deploy; operators opt in explicitly.
- **Default output mode**: `REPLACE` (safer than TAKEOVER; covers the core
  "Qwen had the evidence but flubbed synthesis" case).
- **On external-AI failure**: halt with escalation banner + `status=escalation_failed`.
  No silent fallback.
- **Cost cap**: per-op hard cap `routeMaxExternalCallsPerOp=3`. No token-price
  table, no daily-$ cap.
- **Default-on rules** when master switch is flipped:
  `hallucination_or_fabrication`, `budget_exhaustion`. Others default off.
- **Output on gate rejection**: discard external output, fall through to
  existing local `forced_synthesis` path, log `external_ai_calls.outcome=rejected_by_gate`.
- **Gate precedence**: sub-agent spawn (v2.34.0) tried BEFORE external AI.
  External is last resort.
- **Tool access (future TAKEOVER mode)**: same allowlist as operation's
  agent_type; `plan_action` + blast_radius gates still enforced. Not
  implemented in v2.36.0 — REPLACE only.
- **Context handoff (future TAKEOVER mode)**: digest + last N full tool
  results, default N=5.

## Five-prompt breakdown

| Prompt | Theme | Behaviour change |
|---|---|---|
| v2.36.0 | Schema + provenance + registry keys + counters | Only: fix `model=_lm_model()` bug so traces record real served-model |
| v2.36.1 | Router (`should_escalate_to_external_ai`) + 5 rules + tests | None (behind `externalRoutingMode=off`) |
| v2.36.2 | Confirmation gate (`awaiting_external_ai_confirm` + modal + endpoint) | None (no call path yet) |
| v2.36.3 | External AI client + Mode 2 (REPLACE) + gate re-run + halt-on-fail | LIVE: flip switch to route |
| v2.36.4 | UI: Triggers subsection + provenance render + "Recent external AI calls" + collapsible major sections | Cosmetic / observability |

## Settings registry additions (all in group "External AI Routing")

```python
# Master switch + routing
"externalRoutingMode":                 {"default": "off",   "type": "str"},   # off | manual | auto
"externalRoutingOutputMode":           {"default": "replace","type": "str"},  # replace (v2.36.3); advise/takeover/advise_then_takeover future
"routeMaxExternalCallsPerOp":          {"default": 3,       "type": "int"},
"externalRoutingConfirmTimeoutSec":    {"default": 300,     "type": "int"},

# Rule toggles + thresholds
"routeOnGateFailure":                  {"default": True,    "type": "bool"},   # hallucination_guard_exhausted OR fabrication_detected_count>=2
"routeOnBudgetExhaustion":             {"default": True,    "type": "bool"},
"routeOnConsecutiveFailures":          {"default": False,   "type": "bool"},
"routeOnConsecutiveFailuresThreshold": {"default": 3,       "type": "int"},
"routeOnPriorAttemptsGte":             {"default": False,   "type": "bool"},
"routeOnPriorAttemptsThreshold":       {"default": 3,       "type": "int"},
"routeOnComplexityPrefilter":          {"default": False,   "type": "bool"},
"routeOnComplexityKeywords":           {"default": "correlate,root cause,why,diagnose", "type": "str"},  # CSV
"routeOnComplexityMinPriorAttempts":   {"default": 2,       "type": "int"},

# Context handoff (used by future TAKEOVER; written now for schema stability)
"externalContextLastNToolResults":     {"default": 5,       "type": "int"},
```

## Schema additions

**`agent_llm_traces.provider`** (TEXT NOT NULL DEFAULT 'lm_studio')
- New column, backfill existing rows to `'lm_studio'`
- Index on `(provider, timestamp DESC)` for "recent external calls" queries

**`external_ai_calls`** (new table)

```sql
CREATE TABLE IF NOT EXISTS external_ai_calls (
    id                BIGSERIAL PRIMARY KEY,
    operation_id      TEXT NOT NULL,
    step_index        INTEGER,
    provider          TEXT NOT NULL,          -- claude | openai | grok
    model             TEXT NOT NULL,          -- whatever provider returned
    rule_fired        TEXT NOT NULL,          -- one of the 5 rule keys OR 'manual'
    confirmation      TEXT NOT NULL,          -- auto | confirmed | skipped
    output_mode       TEXT NOT NULL,          -- replace (v2.36.3); advise/takeover future
    latency_ms        INTEGER,
    input_tokens      INTEGER,
    output_tokens     INTEGER,
    outcome           TEXT NOT NULL,          -- success | rejected_by_gate | provider_error | timeout | user_cancelled
    error             TEXT,
    gates_fired       JSONB,                  -- which harness gates fired on this response
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_external_ai_calls_op ON external_ai_calls (operation_id);
CREATE INDEX IF NOT EXISTS idx_external_ai_calls_ts ON external_ai_calls (created_at DESC);
```

Retention: same 7-day policy as `agent_llm_traces`. Nightly purge in
`api/db/llm_trace_retention.py` extended to cover this table.

## Prometheus counters

```
deathstar_external_ai_calls_total{provider, outcome}
deathstar_external_ai_rule_fired_total{rule}
deathstar_external_ai_latency_seconds{provider} (histogram)
deathstar_external_ai_confirmation_outcome_total{outcome}  # confirmed|timed_out|cancelled
deathstar_external_ai_gate_rejection_total{gate}           # which harness gate caught it
```

## Rule firing order (in `should_escalate_to_external_ai`)

Checked in this order; first match wins:

1. **gate_failure** — `hallucination_guard_exhausted` OR `fabrication_detected_count>=2`
2. **budget_exhaustion** — hit tool budget without emitting DIAGNOSIS
3. **consecutive_failures** — N tool calls in a row returned `status=error`
4. **prior_attempts** — scope entity has ≥N failed attempts in agent_attempts (last 7d)
5. **complexity_prefilter** — fires at step 0 (before any tool calls): classifier=investigate AND task matches any configured keyword AND entity has ≥M prior failed attempts

Per-op cap is enforced as a hard AND: even if a rule matches, if
`external_calls_this_op >= routeMaxExternalCallsPerOp`, return `{escalate: False, reason: 'cap_exceeded'}`.

Sub-agent precedence: if the parent has not yet offered/spawned a sub-agent
and sub-agent would be viable, rules 2-5 wait one turn. Rule 1 (gate failure)
bypasses sub-agent precedence because gates firing means the agent cannot be
trusted to propose a useful subtask.

## File touch list (for reviewers)

```
api/db/llm_traces.py                 — add provider column + backfill migration (v2.36.0)
api/db/external_ai_calls.py          — new table + CRUD helpers (v2.36.0)
api/db/llm_trace_retention.py        — extend purge to cover external_ai_calls (v2.36.0)
api/routers/settings.py              — new registry keys (v2.36.0)
api/metrics.py                       — new counters (v2.36.0)
api/routers/agent.py                 — pass response.model (not _lm_model()) (v2.36.0)
api/logger.py                        — log_llm_step already has model kwarg (no change)
api/agents/external_routing.py       — NEW: should_escalate_to_external_ai (v2.36.1)
tests/test_external_routing.py       — NEW: 5 rule scenarios + cap (v2.36.1)
api/routers/agent.py                 — NEW endpoint /api/agent/operations/{id}/confirm-external (v2.36.2)
api/confirmation.py                  — new await path awaiting_external_ai_confirm (v2.36.2)
gui/src/components/ExternalAIConfirmModal.jsx — NEW (v2.36.2)
api/agents/external_ai_client.py     — NEW: per-provider adapter + REPLACE mode (v2.36.3)
api/routers/agent.py                 — wire router into terminal seams (v2.36.3)
tests/test_external_ai_replace_mode.py — NEW (v2.36.3)
gui/src/components/OptionsModal.jsx  — AIServicesTab Escalation Policy section rewrite (v2.36.4)
gui/src/components/Sidebar.jsx       — collapsible major sections (v2.36.4)
gui/src/components/TraceView.jsx     — provider/model display + external_ai_routed gate row (v2.36.4)
gui/src/components/ExternalAICallsTable.jsx — NEW: Logs subtab (v2.36.4)
```

## Out of scope for v2.36.x (noted for future phases)

- Mode 1 ADVISE, Mode 3 TAKEOVER, Mode 4 ADVISE_THEN_TAKEOVER — v2.37.x
- Token-price table + per-hour + daily-$ cap — v2.37.x
- Semantic/LLM-driven complexity classifier (v2.36.1 does keyword only) — v2.37.x
