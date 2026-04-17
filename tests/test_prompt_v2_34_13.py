"""v2.34.13 prompt retargeting regression."""
import pytest
from api.agents.router import RESEARCH_PROMPT, STATUS_PROMPT, ACTION_PROMPT


class TestResearchPromptRetargeted:
    def test_overlay_first_block_precedes_kafka_triage(self):
        """The new CONTAINER INTROSPECT FIRST block must come BEFORE KAFKA TRIAGE."""
        idx_overlay = RESEARCH_PROMPT.find("CONTAINER INTROSPECT FIRST")
        idx_triage  = RESEARCH_PROMPT.find("═══ KAFKA TRIAGE ORDER ═══")
        assert idx_overlay >= 0, "CONTAINER INTROSPECT FIRST section missing"
        assert idx_triage >= 0
        assert idx_overlay < idx_triage, (
            "overlay-first block must precede KAFKA TRIAGE — "
            "placement matters for LLM attention"
        )

    def test_overlay_diagnosis_mentions_all_five_tools(self):
        for tool in [
            "container_discover_by_service",
            "container_networks",
            "container_tcp_probe",
            "container_config_read",
            "container_env",
        ]:
            assert tool in RESEARCH_PROMPT, f"{tool} missing from RESEARCH_PROMPT"

    def test_consumer_lag_path_uses_container_discover(self):
        # NOTE: "CONSUMER LAG PATH" appears both as a forward reference in
        # KAFKA TRIAGE STEP 0 and as the actual path header. Use [-1] to
        # capture the body after the header.
        lag_block = RESEARCH_PROMPT.split("CONSUMER LAG PATH")[-1].split("BROKER MISSING")[0]
        assert "container_discover_by_service" in lag_block
        # And no longer tells the LLM to run docker ps via vm_exec for this step
        assert "docker ps --filter name=" not in lag_block

    def test_concrete_trigger_phrase_present(self):
        # The "when to run overlay diagnosis" trigger
        assert "Disconnecting from node" in RESEARCH_PROMPT
        assert "overlay" in RESEARCH_PROMPT.lower()


class TestStatusPromptRetargeted:
    def test_observe_mentions_container_tools(self):
        for tool in ["container_discover_by_service", "container_tcp_probe",
                     "container_config_read"]:
            assert tool in STATUS_PROMPT


class TestActionPromptRetargeted:
    def test_execute_post_action_verify_uses_container_tools(self):
        assert "POST-ACTION VERIFICATION" in ACTION_PROMPT or \
               "container_tcp_probe" in ACTION_PROMPT
