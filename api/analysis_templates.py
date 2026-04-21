"""Analysis templates registry — v2.38.0.

Each template is a parameterized SQL query operators can run via
/api/admin/analysis/run. Parameter values are bound through psycopg's
%s placeholders (cursor.execute(sql, params)) — never string-formatted
into the SQL body. SQL injection is not possible through this path.

Tables read (existing, no schema changes):
  operations, tool_calls, agent_llm_traces, agent_llm_system_prompts,
  agent_escalations, external_ai_calls, agent_attempts,
  known_facts_current, known_facts_history

Row caps are enforced by appending `LIMIT %s` to every query with the
template's row_cap value. Results marked truncated=True when the query
returns row_cap rows (may mean more exist).
"""

TEMPLATES: dict[str, dict] = {

    # ─── 1. Operation full context ─────────────────────────────────────
    "operation_full_context": {
        "title": "Operation — full context",
        "description": (
            "Joins operation row + tool_calls + agent_llm_traces steps + "
            "system prompt + agent_escalations + external_ai_calls for a "
            "single operation_id. One row returned with nested JSON "
            "arrays — the go-to query for deep-diving a single run."
        ),
        "params": [
            {"name": "operation_id", "type": "uuid", "required": True,
             "description": "operations.id (UUID). Found in Logs → Operations or URL."},
        ],
        "row_cap": 1,
        "sql": """
            SELECT
                row_to_json(o)                                              AS operation,
                COALESCE((
                    SELECT jsonb_agg(to_jsonb(tc) ORDER BY tc.timestamp)
                    FROM tool_calls tc
                    WHERE tc.operation_id = o.id
                ), '[]'::jsonb)                                             AS tool_calls,
                COALESCE((
                    SELECT jsonb_agg(jsonb_build_object(
                        'step_index',   t.step_index,
                        'agent_type',   t.agent_type,
                        'model',        t.model,
                        'provider',     t.provider,
                        'finish_reason', t.finish_reason,
                        'input_tokens', t.input_tokens,
                        'output_tokens', t.output_tokens
                    ) ORDER BY t.step_index)
                    FROM agent_llm_traces t
                    WHERE t.operation_id = o.id::text
                ), '[]'::jsonb)                                             AS trace_steps,
                (
                    SELECT sp.prompt_text
                    FROM agent_llm_system_prompts sp
                    WHERE sp.operation_id = o.id::text
                    LIMIT 1
                )                                                           AS system_prompt,
                COALESCE((
                    SELECT jsonb_agg(to_jsonb(e) ORDER BY e.created_at)
                    FROM agent_escalations e
                    WHERE e.operation_id = o.id::text
                ), '[]'::jsonb)                                             AS escalations,
                COALESCE((
                    SELECT jsonb_agg(to_jsonb(x) ORDER BY x.created_at)
                    FROM external_ai_calls x
                    WHERE x.operation_id = o.id::text
                ), '[]'::jsonb)                                             AS external_ai_calls
            FROM operations o
            WHERE o.id = %(operation_id)s
            LIMIT %(row_cap)s
        """,
    },

    # ─── 2. Session — all operations ───────────────────────────────────
    "session_all_operations": {
        "title": "Session — all operations",
        "description": (
            "All operations rows sharing a session_id (includes parent + "
            "any sub-agent runs). Ordered by started_at. Useful when a "
            "task spawned sub-agents and you want to see the full tree."
        ),
        "params": [
            {"name": "session_id", "type": "text", "required": True,
             "description": "operations.session_id (e.g. '9a23e276')."},
        ],
        "row_cap": 100,
        "sql": """
            SELECT
                o.id,
                o.session_id,
                o.parent_session_id,
                o.label                                  AS task,
                o.status,
                o.started_at,
                o.completed_at,
                o.total_duration_ms,
                o.model_used,
                o.triggered_by,
                o.owner_user,
                LENGTH(COALESCE(o.final_answer, ''))     AS final_answer_len,
                (
                    SELECT t.agent_type
                    FROM agent_llm_traces t
                    WHERE t.operation_id = o.id::text
                      AND t.agent_type IS NOT NULL
                    ORDER BY t.step_index ASC
                    LIMIT 1
                )                                        AS agent_type,
                (
                    SELECT COUNT(*) FROM tool_calls tc WHERE tc.operation_id = o.id
                )                                        AS tool_call_count
            FROM operations o
            WHERE o.session_id = %(session_id)s
               OR o.parent_session_id = %(session_id)s
            ORDER BY o.started_at ASC
            LIMIT %(row_cap)s
        """,
    },

    # ─── 3. Recent failures ────────────────────────────────────────────
    "recent_failures": {
        "title": "Recent failures / capped / escalated",
        "description": (
            "Operations from the last N hours that didn't complete cleanly. "
            "Filters by agent_type if specified. Ordered by most recent "
            "first. Quick triage query for 'what broke today?'."
        ),
        "params": [
            {"name": "hours", "type": "int", "required": False, "default": 24,
             "min": 1, "max": 720,
             "description": "Look-back window in hours (1-720)."},
            {"name": "agent_type", "type": "text", "required": False, "default": "any",
             "description": "observe / investigate / execute / build / any"},
        ],
        "row_cap": 200,
        "sql": """
            SELECT
                o.id,
                o.session_id,
                o.label                                  AS task,
                o.status,
                o.started_at,
                o.total_duration_ms,
                o.model_used,
                COALESCE((
                    SELECT t.agent_type
                    FROM agent_llm_traces t
                    WHERE t.operation_id = o.id::text
                      AND t.agent_type IS NOT NULL
                    ORDER BY t.step_index ASC
                    LIMIT 1
                ), 'observe')                            AS agent_type,
                LEFT(COALESCE(o.final_answer, ''), 200)  AS final_answer_head,
                (
                    SELECT COUNT(*) FROM tool_calls tc
                    WHERE tc.operation_id = o.id AND tc.status <> 'ok'
                )                                        AS failed_tool_call_count,
                (
                    SELECT COUNT(*) FROM agent_escalations e
                    WHERE e.operation_id = o.id::text
                )                                        AS escalation_count
            FROM operations o
            WHERE o.status IN ('failed', 'capped', 'escalated', 'error',
                               'escalation_failed', 'cancelled')
              AND o.started_at > NOW() - (%(hours)s || ' hours')::INTERVAL
              AND (%(agent_type)s = 'any' OR COALESCE((
                    SELECT t.agent_type
                    FROM agent_llm_traces t
                    WHERE t.operation_id = o.id::text
                      AND t.agent_type IS NOT NULL
                    ORDER BY t.step_index ASC
                    LIMIT 1
              ), 'observe') = %(agent_type)s)
            ORDER BY o.started_at DESC
            LIMIT %(row_cap)s
        """,
    },

    # ─── 4. Tool error frequency ───────────────────────────────────────
    "tool_error_frequency": {
        "title": "Tool error frequency",
        "description": (
            "Groups tool_calls where status != 'ok' by (tool_name, "
            "error_detail) across the look-back window. Shows which "
            "tools are failing most often and their top error messages."
        ),
        "params": [
            {"name": "hours", "type": "int", "required": False, "default": 24,
             "min": 1, "max": 720,
             "description": "Look-back window in hours (1-720)."},
        ],
        "row_cap": 100,
        "sql": """
            SELECT
                tc.tool_name,
                tc.status,
                LEFT(COALESCE(tc.error_detail, ''), 200) AS error_head,
                COUNT(*)                                 AS occurrences,
                MAX(tc.timestamp)                        AS last_seen,
                COUNT(DISTINCT tc.operation_id)          AS distinct_operations
            FROM tool_calls tc
            WHERE tc.status <> 'ok'
              AND tc.timestamp > NOW() - (%(hours)s || ' hours')::INTERVAL
            GROUP BY tc.tool_name, tc.status, LEFT(COALESCE(tc.error_detail, ''), 200)
            ORDER BY occurrences DESC
            LIMIT %(row_cap)s
        """,
    },

    # ─── 5. Escalations detail ─────────────────────────────────────────
    "escalations_detail": {
        "title": "Escalations — detail for operation",
        "description": (
            "All agent_escalations + external_ai_calls rows for a single "
            "operation_id. Use to verify both tables got written when an "
            "external AI escalation fires."
        ),
        "params": [
            {"name": "operation_id", "type": "text", "required": True,
             "description": "operations.id (UUID as text)."},
        ],
        "row_cap": 100,
        "sql": """
            SELECT
                'escalation' AS kind,
                e.id,
                e.created_at AS ts,
                e.severity,
                e.reason,
                e.acknowledged,
                e.acknowledged_at,
                e.acknowledged_by,
                NULL::TEXT   AS provider,
                NULL::TEXT   AS model,
                NULL::TEXT   AS rule_fired,
                NULL::TEXT   AS outcome,
                NULL::TEXT   AS error_message,
                NULL::REAL   AS est_cost_usd
            FROM agent_escalations e
            WHERE e.operation_id = %(operation_id)s
            UNION ALL
            SELECT
                'external_ai_call' AS kind,
                x.id::TEXT,
                x.created_at AS ts,
                NULL, NULL,
                NULL::BOOLEAN, NULL, NULL,
                x.provider,
                x.model,
                x.rule_fired,
                x.outcome,
                LEFT(COALESCE(x.error_message, ''), 300) AS error_message,
                x.est_cost_usd
            FROM external_ai_calls x
            WHERE x.operation_id = %(operation_id)s
            ORDER BY ts ASC
            LIMIT %(row_cap)s
        """,
    },

    # ─── 6. Entity recent attempts ─────────────────────────────────────
    "entity_recent_attempts": {
        "title": "Entity — recent attempts",
        "description": (
            "agent_attempts history for a specific entity over the last "
            "N days. Shows outcome, tool sequence, diagnosis markers."
        ),
        "params": [
            {"name": "entity_id", "type": "text", "required": True,
             "description": "Canonical entity_id (e.g. 'proxmox:hp1-agent:9200')."},
            {"name": "days", "type": "int", "required": False, "default": 7,
             "min": 1, "max": 90,
             "description": "Look-back window in days."},
        ],
        "row_cap": 100,
        "sql": """
            SELECT
                a.id,
                a.operation_id,
                a.entity_id,
                a.agent_type,
                a.outcome,
                a.diagnosis,
                a.tool_sequence,
                a.started_at,
                a.completed_at,
                a.total_duration_ms
            FROM agent_attempts a
            WHERE a.entity_id = %(entity_id)s
              AND a.started_at > NOW() - (%(days)s || ' days')::INTERVAL
            ORDER BY a.started_at DESC
            LIMIT %(row_cap)s
        """,
    },

    # ─── 7. Fact history ───────────────────────────────────────────────
    "fact_history": {
        "title": "Fact — current value + history",
        "description": (
            "All known_facts_current rows (one per source) for a fact_key, "
            "plus full known_facts_history. Use to see how a fact has "
            "changed over time across collectors."
        ),
        "params": [
            {"name": "fact_key", "type": "text", "required": True,
             "description": "Fact key, e.g. 'prod.swarm.service.kafka_broker-3.placement'."},
        ],
        "row_cap": 500,
        "sql": """
            SELECT
                'current' AS kind,
                NULL::INT AS history_id,
                c.fact_key,
                c.source,
                c.value,
                c.confidence,
                c.verify_count,
                c.contradiction_count,
                c.observed_at,
                c.updated_at,
                NULL::TIMESTAMPTZ AS superseded_at
            FROM known_facts_current c
            WHERE c.fact_key = %(fact_key)s
            UNION ALL
            SELECT
                'history' AS kind,
                h.id,
                h.fact_key,
                h.source,
                h.value,
                h.confidence,
                NULL::INT, NULL::INT,
                h.observed_at,
                NULL::TIMESTAMPTZ,
                h.superseded_at
            FROM known_facts_history h
            WHERE h.fact_key = %(fact_key)s
            ORDER BY observed_at DESC
            LIMIT %(row_cap)s
        """,
    },
}


def get_template(tid: str) -> dict | None:
    """Return the template dict or None."""
    return TEMPLATES.get(tid)


def list_templates() -> list[dict]:
    """Return sanitised template metadata (no raw SQL in response)."""
    return [
        {
            "id": tid,
            "title": tpl["title"],
            "description": tpl["description"],
            "params": tpl["params"],
            "row_cap": tpl["row_cap"],
        }
        for tid, tpl in TEMPLATES.items()
    ]


def validate_params(tpl: dict, raw: dict) -> dict:
    """Coerce + validate params against the template schema.

    Raises ValueError on missing required / bad type / out-of-range.
    Returns a dict with every declared param populated (defaults filled).
    Ignores unknown keys in `raw` — extra params are silently dropped.
    """
    import uuid
    out: dict = {}
    for pspec in tpl["params"]:
        name = pspec["name"]
        typ  = pspec.get("type", "text")
        required = pspec.get("required", False)
        val = raw.get(name)
        if val is None or val == "":
            if required:
                raise ValueError(f"Missing required param: {name}")
            val = pspec.get("default")
        if val is None:
            out[name] = None
            continue
        if typ == "int":
            try:
                ival = int(val)
            except (TypeError, ValueError):
                raise ValueError(f"Param {name} must be an integer, got {val!r}")
            if "min" in pspec and ival < pspec["min"]:
                raise ValueError(f"Param {name} must be >= {pspec['min']}")
            if "max" in pspec and ival > pspec["max"]:
                raise ValueError(f"Param {name} must be <= {pspec['max']}")
            out[name] = ival
        elif typ == "uuid":
            try:
                out[name] = str(uuid.UUID(str(val)))
            except (TypeError, ValueError):
                raise ValueError(f"Param {name} must be a UUID, got {val!r}")
        else:  # text / default
            s = str(val).strip()
            if required and not s:
                raise ValueError(f"Param {name} must not be empty")
            out[name] = s
    # row_cap is always present and bounded independently
    row_cap = int(tpl.get("row_cap", 500))
    out["row_cap"] = max(1, min(row_cap, 10000))
    return out
