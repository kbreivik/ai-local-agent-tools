import pytest
from api.agents.router import classify_task


class TestInvestigativeStarters:
    """v2.34.11 regression: tasks opening with investigative verbs must
    route to research regardless of downstream status keywords."""

    def test_investigate_why_logstash_routes_to_research(self):
        # The exact prompt that produced sessions 2f2dae36 + 5107bfa7 and
        # mis-routed to observe in both.
        task = (
            "Investigate why Logstash is not writing to Elasticsearch. "
            "Check Kafka broker reachability from Logstash, including a "
            "network probe (nc -zv) to broker 3 on port 9094, and "
            "correlate with consumer lag and cluster health."
        )
        assert classify_task(task) == "research"

    @pytest.mark.parametrize("starter", [
        "Investigate", "Diagnose", "Troubleshoot", "Analyse", "Analyze",
        "Correlate", "Why",
    ])
    def test_single_word_starter_wins_over_status_body(self, starter):
        # Every one of these starters MUST beat a status-heavy body.
        task = f"{starter} the cluster health and broker status"
        assert classify_task(task) == "research"

    def test_deep_dive_bigram_routes_to_research(self):
        assert classify_task("deep dive kafka lag on logstash") == "research"

    def test_find_out_bigram_routes_to_research(self):
        # "find" on its own is a QUESTION_STARTER but ambiguous. "find out"
        # specifically is research intent.
        assert classify_task("find out why broker 3 keeps disconnecting") == "research"

    def test_root_cause_opener_routes_to_research(self):
        assert classify_task("root cause analysis for kafka consumer lag") == "research"


class TestResearchStarterDoesNotOverrideAction:
    """Safety: if an action verb is present, research-starter short-circuit
    must NOT fire. Action tasks still beat research when action keywords exist.
    """

    def test_investigate_and_restart_is_action(self):
        # "restart" is an action keyword; investigate-starter should NOT
        # hijack this to research.
        task = "investigate the broker state and restart kafka_broker-3"
        assert classify_task(task) == "action"

    def test_diagnose_and_fix_is_action(self):
        assert classify_task("diagnose and fix the logstash pipeline") == "action"


class TestExistingBehaviourPreserved:
    """Regression: non-research starters keep their old routing."""

    def test_what_is_the_status_routes_to_status(self):
        assert classify_task("what is the status of kafka brokers") == "status"

    def test_show_me_services_routes_to_status(self):
        assert classify_task("show me the running services") == "status"

    def test_restart_kafka_routes_to_action(self):
        assert classify_task("restart kafka_broker-3") == "action"

    def test_create_skill_routes_to_build(self):
        assert classify_task("create a skill to list Proxmox VMs") == "build"

    def test_empty_task_is_ambiguous(self):
        assert classify_task("") == "ambiguous"

    def test_garbage_task_is_ambiguous(self):
        # No keywords from any set — classic ambiguous case.
        assert classify_task("xyzzy") == "ambiguous"
