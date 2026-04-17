# CC PROMPT — v2.34.11 — fix(agents): classifier hard-routes investigative starters to research

## Evidence

Live trace 2026-04-17 17:46 (session 2f2dae36) and 2026-04-17 18:48 (session
5107bfa7). Both ran the same task:

```
Investigate why Logstash is not writing to Elasticsearch. Check Kafka broker
reachability from Logstash, including a network probe (nc -zv) to broker 3
on port 9094, and correlate with consumer lag and cluster health.
```

Both were classified as **Observe** (8-call budget) instead of **Investigate**
(16-call budget). Both hit the tool-call ceiling at 8/8 and were force-summarised
mid-diagnosis. The second run in particular got within one tool call of the
root cause (overlay netns routing) before budget exhaustion and had to
hand-off with "ACTION NEEDED: Investigate Logstash Kafka input configuration...".

## Why the classifier did this

In `api/agents/router.py::classify_task` the token scoring came out:

  status_score   = 5   ("check", "network", "port", "health", "lag")
  research_score = 3   ("investigate", "why", "correlate")
  action_score   = 0

`top = 5` → status wins, returns `'status'` → routed to Observe.

The task literally starts with the word **Investigate**. `QUESTION_STARTERS`
already includes `investigate`/`diagnose`/`troubleshoot`/`analyse`/`analyze`,
but that set is only used to prevent action-routing, not to boost research
routing. A task that OPENS with an investigative verb should hard-route to
research regardless of how many status keywords appear downstream —
otherwise any sufficiently detailed investigation prompt (which will mention
network, ports, health, etc.) loses to its own evidence list.

## Fix — investigative-starter hard route

Add a small frozenset of "research intent" starters and short-circuit
`classify_task` when the first word matches AND no action keyword is present
(so "diagnose and restart X" still routes to action, not research).

Version bump: 2.34.10 → 2.34.11

---

## Change 1 — api/agents/router.py

Add new constant after `QUESTION_STARTERS` (around line ~490, near the top of
the keyword blocks):

```python
# Investigative intent starters — when a task OPENS with one of these verbs,
# it is a research/diagnosis task by intent, even if its body mentions many
# status-flavoured nouns (health, port, network, lag, etc). Used by
# classify_task() to short-circuit the keyword tally.
_RESEARCH_STARTERS = frozenset({
    "investigate", "diagnose", "troubleshoot",
    "analyse", "analyze", "correlate",
    "why",
    "deepdive",
})

# Bigram forms equivalent to a research starter. Checked when first_word on
# its own is insufficient (e.g. "deep dive", "find out why").
_RESEARCH_STARTER_BIGRAMS = frozenset({
    "deep dive",
    "find out",    # "find out why X" — first word "find" alone is a
                   # QUESTION_STARTER, but "find out" signals research
    "root cause",
    "what caused",
})
```

Then inside `classify_task`, place the short-circuit immediately after the
build check and before the status/action/research tally:

```python
    # Build intent: any task mentioning skill management words → route to build
    build_score = len(tokens & BUILD_KEYWORDS)
    if build_score > 0:
        return 'build'

    # v2.34.11: Investigative-starter short-circuit.
    # If the task OPENS with a research-intent verb AND carries no action verb,
    # it is a research task regardless of how many status nouns follow.
    first_word = words[0] if words else ""
    first_bigram = bigrams[0] if bigrams else ""
    action_score_early = len(tokens & ACTION_KEYWORDS)
    if action_score_early == 0 and (
        first_word in _RESEARCH_STARTERS
        or first_bigram in _RESEARCH_STARTER_BIGRAMS
    ):
        return 'research'

    status_score   = len(tokens & STATUS_KEYWORDS)
    action_score   = len(tokens & ACTION_KEYWORDS)
    research_score = len(tokens & RESEARCH_KEYWORDS)
```

Leave the rest of the function unchanged. The existing QUESTION_STARTERS
logic and tie-breaking still apply to tasks whose first word is a neutral
starter like "what", "show", "list", "is", "are".

## Change 2 — Prometheus counter

Add to `api/metrics.py`:

```python
CLASSIFIER_DECISIONS_COUNTER = Counter(
    "deathstar_agent_classifier_decisions_total",
    "Task classifier routing decisions by agent type and trigger",
    ["agent_type", "trigger"],
    # trigger values: 'build_keyword', 'research_starter', 'research_bigram',
    #                 'action_keyword', 'keyword_score', 'ambiguous'
)
```

Instrument each return path in `classify_task` to increment the counter with
the triggering reason. Counter must not change the return value.

## Change 3 — tests

New file `tests/test_task_classifier.py` — this subsystem has no existing
test coverage; add regression coverage anchored on today's traces:

```python
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
```

## Version bump

Update `VERSION`: `2.34.10` → `2.34.11`

## Commit

```
git add -A
git commit -m "fix(agents): v2.34.11 classifier hard-routes investigative starters to research"
git push origin main
```

## How to test after push

1. Redeploy `hp1_agent`.
2. Re-run the exact prompt from sessions 2f2dae36 / 5107bfa7:
   > Investigate why Logstash is not writing to Elasticsearch. Check Kafka
   > broker reachability from Logstash, including a network probe (nc -zv)
   > to broker 3 on port 9094, and correlate with consumer lag and cluster
   > health.
3. Confirm in the trace header: `Agent: Investigate` (NOT Observe).
4. Budget ceiling should show 16, not 8. The agent should have room to
   probe overlay-internal reachability (`docker exec ... bash -c
   '</dev/tcp/192.168.199.33/9094'`) without hitting forced summary.
5. Prometheus: `deathstar_agent_classifier_decisions_total{agent_type="research",trigger="research_starter"}` increments.
6. Regression spot-checks in the UI:
   - `"what is the cluster status"` → classifies as observe (status) as before
   - `"restart kafka_broker-3"` → action as before
   - `"create a skill to list VMs"` → build as before
7. Run the new test suite: `pytest tests/test_task_classifier.py -v` — all green.
