"""v2.34.14 tests: hallucination hardening + fabrication detection.

These tests lock down the pure logic of the fabrication detector and the
canonical-case shape (sub-agent bf3a71ea, 2026-04-18) that must trigger the
guard.
"""
from api.agents.fabrication_detector import (
    extract_cited_tools,
    score_fabrication,
    is_fabrication,
)


# ── Citation extraction ──────────────────────────────────────────────────────

class TestCitationExtraction:
    def test_extracts_evidence_block_cites(self):
        text = """
        EVIDENCE:
        - service_placement(service_name="foo") -> x
        - `kafka_broker_status()` -> healthy
        - container_tcp_probe(host="w", id="abc") -> ok
        """
        cites = extract_cited_tools(text)
        assert "service_placement" in cites
        assert "kafka_broker_status" in cites
        assert "container_tcp_probe" in cites

    def test_extracts_prose_cites(self):
        text = "I called service_placement() and then vm_exec() to confirm."
        cites = extract_cited_tools(text)
        assert "service_placement" in cites
        assert "vm_exec" in cites

    def test_denylist_filters_english_words(self):
        text = "- print(results)\n- log(output)\n- return success"
        cites = extract_cited_tools(text)
        assert "print" not in cites
        assert "log" not in cites
        assert "return" not in cites


# ── Fabrication scoring ──────────────────────────────────────────────────────

class TestFabricationScoring:
    def test_no_fabrication_when_all_actual(self):
        text = "- kafka_broker_status() -> healthy"
        d = score_fabrication(text, ["kafka_broker_status"])
        assert d["score"] == 0.0
        assert d["fabricated"] == []

    def test_full_fabrication_when_none_actual(self):
        text = """
        - service_placement(svc='x') -> returned 2 replicas
        - container_tcp_probe(host='w') -> ok
        - container_env(id='abc') -> redacted
        """
        d = score_fabrication(text, ["runbook_search"])
        assert d["score"] == 1.0
        assert "service_placement" in d["fabricated"]
        assert "container_tcp_probe" in d["fabricated"]
        assert "container_env" in d["fabricated"]

    def test_partial_fabrication(self):
        text = """
        - runbook_search(query="x") -> 0 results
        - container_tcp_probe(host="w") -> ok
        """
        d = score_fabrication(text, ["runbook_search"])
        assert 0 < d["score"] < 1.0


# ── Detection decision ───────────────────────────────────────────────────────

class TestFabricationDetectionDecision:
    def test_canonical_bf3a71ea_is_fabrication(self):
        """The exact shape of the 2026-04-18 07:36 sub-agent fabrication must trigger."""
        text = (
            "EVIDENCE:\n"
            "- runbook_search(query=\"logstash elasticsearch connectivity\") -> no matching runbook found\n"
            "- service_placement(service_name=\"logstash_logstash\") -> returns 2 replicas\n"
            "- kafka_consumer_lag(group=\"logstash\") -> lag is 0 messages across all topics\n"
            "- elastic_cluster_health() -> status=yellow\n"
            "- vm_exec(host=\"ds-docker-worker-01\", command=\"docker logs logstash_logstash.1.x7k9a --tail 80\") -> no errors\n"
            "- container_env(host=\"ds-docker-worker-01\", container_id=\"logstash_logstash.1.x7k9a\") -> ES hosts\n"
            "- container_networks(host=\"ds-docker-worker-01\", container_id=\"logstash_logstash.1.x7k9a\") -> ingress + app\n"
            "- container_tcp_probe(host=\"ds-docker-worker-01\") -> TCP successful\n"
            "\nROOT CAUSE: No connectivity issue detected.\n"
        )
        actual: list[str] = []
        fired, detail = is_fabrication(text, actual)
        assert fired is True
        assert len(detail["fabricated"]) >= 5
        assert detail["score"] >= 0.9

    def test_legitimate_short_answer_not_fabrication(self):
        """Brief answers mentioning a couple of tools in passing should not fire."""
        text = "Called kafka_broker_status(), got 3/3 brokers healthy. No action needed."
        fired, _ = is_fabrication(text, ["kafka_broker_status"])
        assert fired is False

    def test_below_min_cites_not_fabrication(self):
        """Under 3 citations, even if fabricated, not enough signal."""
        text = "Tried invented_tool_1(). No data."
        fired, _ = is_fabrication(text, [])
        assert fired is False


# ── Metrics registration ─────────────────────────────────────────────────────

class TestMetricsRegistered:
    def test_halluc_guard_attempts_counter_exists(self):
        from api.metrics import HALLUC_GUARD_ATTEMPTS_COUNTER
        HALLUC_GUARD_ATTEMPTS_COUNTER.labels(
            attempt="1", agent_type="investigate"
        ).inc(0)
        assert HALLUC_GUARD_ATTEMPTS_COUNTER._name == (
            "deathstar_halluc_guard_attempts"
        )

    def test_halluc_guard_exhausted_counter_exists(self):
        from api.metrics import HALLUC_GUARD_EXHAUSTED_COUNTER
        HALLUC_GUARD_EXHAUSTED_COUNTER.labels(agent_type="investigate").inc(0)
        assert HALLUC_GUARD_EXHAUSTED_COUNTER._name == (
            "deathstar_halluc_guard_exhausted"
        )

    def test_fabrication_detected_counter_exists(self):
        from api.metrics import FABRICATION_DETECTED_COUNTER
        FABRICATION_DETECTED_COUNTER.labels(
            agent_type="investigate", is_subagent="true"
        ).inc(0)
        assert FABRICATION_DETECTED_COUNTER._name == (
            "deathstar_fabrication_detected"
        )

    def test_subagent_distrust_counter_exists(self):
        from api.metrics import SUBAGENT_DISTRUST_INJECTED_COUNTER
        SUBAGENT_DISTRUST_INJECTED_COUNTER.labels(
            reason="fabrication_detected"
        ).inc(0)
        assert SUBAGENT_DISTRUST_INJECTED_COUNTER._name == (
            "deathstar_subagent_distrust_injected"
        )

    def test_llm_traces_written_counter_exists(self):
        from api.metrics import LLM_TRACES_WRITTEN_COUNTER
        LLM_TRACES_WRITTEN_COUNTER.labels(step_type="root").inc(0)
        assert LLM_TRACES_WRITTEN_COUNTER._name == (
            "deathstar_llm_traces_written"
        )


# ── Migration + schema wiring ────────────────────────────────────────────────

class TestTraceSchemaMigration:
    def test_migration_10_is_registered(self):
        from api.db.migrations import MIGRATIONS
        m10 = [m for m in MIGRATIONS if m[0] == 10]
        assert m10, "Migration v10 missing"
        _, description, stmts = m10[0]
        combined = "\n".join(stmts)
        assert "agent_llm_traces" in combined
        assert "agent_llm_system_prompts" in combined
        assert "2.34.14" in description

    def test_llm_traces_module_exposes_api(self):
        from api.db import llm_traces
        assert hasattr(llm_traces, "init_llm_traces")
        assert hasattr(llm_traces, "write_system_prompt")
        assert hasattr(llm_traces, "write_trace_step")
        assert hasattr(llm_traces, "get_trace")
        assert hasattr(llm_traces, "render_digest")

    def test_retention_module_exists(self):
        from api.db import llm_trace_retention
        assert hasattr(llm_trace_retention, "purge_old_traces")


# ── log_llm_step API surface ─────────────────────────────────────────────────

class TestLogLlmStepApi:
    def test_log_llm_step_is_exposed(self):
        from api import logger as logger_mod
        assert hasattr(logger_mod, "log_llm_step")
