"""Agent harness package.

Shared constants live here so both the runtime (api.routers.agent) and
tests can import them without pulling the full router surface.
"""

# v2.34.8 — Meta tools do NOT count toward "substantive investigation".
# An agent that only calls tools in this set has gathered no real
# infrastructure data — so emitting a final_answer would be a hallucination.
META_TOOLS = frozenset({
    "audit_log",         # audit trail write — not data
    "runbook_search",    # index lookup — not data
    "memory_recall",     # prior-context pull
    "propose_subtask",   # delegation — parent did no work itself
    "engram_activate",   # memory context activation
    "plan_action",       # plan gate — no infra data
})

# v2.34.8 — minimum substantive (non-META) tool calls required before the
# harness will accept a final_answer from each agent type. Below this, the
# hallucination guard rejects the answer and forces a retry.
MIN_SUBSTANTIVE_BY_TYPE = {
    "observe":     1,
    "status":      1,    # alias
    "investigate": 2,
    "research":    2,    # alias
    "execute":     2,    # plan + verify at minimum
    "action":      2,    # alias
    "build":       1,
}
