# CC PROMPT — v2.34.13 — fix(agents): retarget prompts to prefer container_introspect over raw docker exec

## Evidence

Session 26cdd92b (20:08), 2bd88acb (20:22 approx), and a69fd96d (20:45) all
ran the same Logstash investigate task. After v2.34.12 shipped five
`container_*` tools (blast_radius=none, correctly registered, in all
relevant allowlists, mentioned in `RESEARCH_PROMPT` CONTAINER INTROSPECTION
block), the agent **still made zero calls to any of them**.

Prometheus confirms:

  deathstar_container_introspect_total                 (HELP/TYPE only, no series)
  deathstar_agent_tool_calls_total{agent_type="research",tool="vm_exec"} 9.0

Trace for session a69fd96d (v2.34.12 deployed, 16-call investigate):

  0.  runbook_search             (ok)
  1.  kafka_broker_status        (ok)
  2.  kafka_consumer_lag()       (TypeError: missing 'group')
  3.  elastic_cluster_health     (ok)
  4.  kafka_consumer_lag(group=) (degraded)
  5.  service_placement          (ok)  ← has {containers} info, unused by caller
  6.  elastic_kafka_logs         (0 events)
  7.  vm_exec docker ps          ← could have been container_discover_by_service
  8.  vm_exec docker logs *      ← wildcard guess (failed)
  9.  vm_exec docker logs <id>   (ok, got timeout logs)
  10. vm_exec nc from host       (succeeded — wrong netns for the question asked)
  11. vm_exec docker exec nc     ← should have been container_tcp_probe
  12. vm_exec docker exec curl   (BLOCKED by allowlist)
  13. vm_exec docker exec bash -c 'echo > /dev/tcp'  (BLOCKED — '>' metachar)
  14. vm_exec docker exec bash -c 'cat < /dev/tcp'   (BLOCKED — '<' metachar)
  15. vm_exec docker exec cat logstash.yml           (BLOCKED by allowlist)

All five container_introspect tools were available. None were chosen.

## Root cause: the prompt actively steers toward vm_exec

`RESEARCH_PROMPT` is ~600 lines. The KAFKA TRIAGE section sits at the top
and gives step-by-step prescriptive instructions naming vm_exec and
kafka_exec verbatim:

    CONSUMER LAG PATH (when message contains "consumer lag"):
      Step 2: vm_exec(host="<worker>", command="docker logs <container> --tail 100")
      ...

    BROKER MISSING PATH:
      Step 4: vm_exec(host=<vm_host_label>, command="docker ps --filter name=kafka")
      Step 5: kafka_exec(broker_label="<node-label>", ...)

The CONTAINER INTROSPECTION block I added lives ~400 lines further down,
after the STORAGE / NETWORK / COMPUTE / SECURITY branch guidance. By the
time the LLM reaches it, the playbook it read at the top has already
committed it to vm_exec + docker-ps + docker-logs as "the investigate
pattern". When the investigation hits novel ground in steps 11-15, the
agent improvises with more docker-exec shells because the top-of-prompt
playbook never retargeted.

The LLM is following the prompt faithfully. The prompt is wrong.

This prompt makes three surgical edits to retarget. No new code, no new
tools, no schema changes.

Version bump: 2.34.12 → 2.34.13

---

## Change 1 — RESEARCH_PROMPT: insert OVERLAY-FIRST guidance at TOP of KAFKA TRIAGE

In `api/agents/router.py`, find the block starting with:

    ═══ KAFKA TRIAGE ORDER ═══
    1. kafka_topic_inspect (no args, or topic=X for focused) — FIRST call for any

Insert a new section BEFORE that block (so it reads before KAFKA TRIAGE):

```text
═══ CONTAINER INTROSPECT FIRST — BEFORE RAW docker exec ═══
Whenever an investigation would lead you to call vm_exec with a
"docker exec <id> <something>" body, STOP and check which of these
tools does the same job with typed arguments and no metachar filter:

  docker exec <id> cat <path>              → container_config_read(host, id, path)
  docker exec <id> env                     → container_env(host, id)
  docker exec <id> nc -zv H P              → container_tcp_probe(host, id, H, P)
  docker exec <id> bash -c '</dev/tcp/H/P' → container_tcp_probe(host, id, H, P)
  docker inspect <id> --format '{{...}}'   → container_networks(host, id)
  docker ps --filter name=X --format ...   → container_discover_by_service(X)

Reasons to prefer them:
- Arguments are validated per-tool, so none of these hit the vm_exec
  allowlist / metachar filter (no '&&', '|', '>', '<', '$()' surprises).
- Return is structured JSON, not raw stdout — easier to cite in
  EVIDENCE and feed to the next step.
- container_tcp_probe uses `</dev/tcp/>` in bash — it works even when
  nc, ncat, curl are not installed in the target image.
- container_discover_by_service does service_placement + docker ps in
  ONE call, returning {node, vm_host_label, container_id, container_name}
  per running replica. It replaces the "service_placement → vm_exec
  docker ps → parse ID" sequence that currently eats 2-3 tool calls
  before you can look inside a container.

Use vm_exec for what it is good at: arbitrary host-level commands
(ss, netstat, dmesg, journalctl, docker logs --tail, `docker system df`)
that have no container-introspect equivalent.

OVERLAY-LAYER DIAGNOSIS (canonical sequence for "client inside
container A cannot reach service on container B"):

  1. container_discover_by_service("<client-service>")
  2. container_discover_by_service("<server-service>")
  3. container_networks(host, <client_id>) AND container_networks(host, <server_id>)
     → compare overlay network names; shared overlay = fast path
  4. container_tcp_probe(host, <client_id>, <target_host_or_ip>, <port>)
     → DEFINITIVE answer about reachability from client's netns
  5. If (4) FAILS but `nc -zv` from the worker host succeeds: host is
     reachable but the overlay-to-host hairpin (published-port NAT on
     the same node) is broken. Workaround: reschedule the client to
     a different node; proper fix: attach client to server's overlay
     and use internal listener names.

CONCRETE TRIGGER — "consumer lag growing + brokers report healthy +
container logs show `Disconnecting from node N due to socket connection
setup timeout`" = RUN THE OVERLAY-LAYER DIAGNOSIS. Do not burn your
budget on `docker exec nc/curl/cat` shells. Do not accept
`nc -zv from host` as evidence that the CLIENT can reach the server —
only container_tcp_probe from inside the client's netns answers that.
```

This block goes IMMEDIATELY before `═══ KAFKA TRIAGE ORDER ═══`, no other
edits in that region.

## Change 2 — RESEARCH_PROMPT: replace inline vm_exec steps in KAFKA TRIAGE

In the existing CONSUMER LAG PATH block, change:

```text
  Step 1: service_placement("logstash_logstash") — confirm running + which node
  Step 2: vm_exec(host="<worker>", command="docker logs <container> --tail 100")
          → look for: ES connection refused, bulk errors, 429, pipeline errors
```

to:

```text
  Step 1: container_discover_by_service("logstash_logstash")
          → returns {node, vm_host_label, container_id, container_name} per replica.
          Use the container_id and vm_host_label for every subsequent step.
  Step 2: vm_exec(host=<vm_host_label>,
                  command="docker logs <container_id> --tail 100")
          → look for: ES connection refused, bulk errors, 429, pipeline errors,
            "Disconnecting from node N due to socket connection setup timeout"
          (Note: docker logs is intentionally vm_exec, not a container_* tool —
           stdout stream doesn't map cleanly to a typed API.)
```

In BROKER MISSING PATH, change:

```text
  Step 3: service_placement(service_name="kafka_broker-N") → node + vm_host_label
  Step 4: vm_exec(host=<vm_host_label>, command="docker ps --filter name=kafka")
```

to:

```text
  Step 3: container_discover_by_service("kafka_broker-N")
          → returns {node, vm_host_label, container_id, container_name} in one call.
          Replaces the service_placement + docker ps pair.
  Step 4: (skipped — container_id already in hand from Step 3)
```

(Renumber remaining steps as needed. Keep kafka_exec at the end of the chain
for deep broker-side API calls.)

## Change 3 — RESEARCH_PROMPT: tighten the existing CONTAINER INTROSPECTION block

The existing `═══ CONTAINER INTROSPECTION (v2.34.12) ═══` block stays, but
move it UP so it sits immediately after the new CONTAINER INTROSPECT FIRST
section (Change 1). Rationale: a single prominent pair at the top of KAFKA
TRIAGE, before any platform-specific branch guidance.

Also replace the closing line of the block:

```text
  4. container_config_read(...) / container_env(...) — only if needed to
     identify what address the client is actually trying to reach
```

with:

```text
  4. container_config_read(host, id, path) — when the client logs
     point at a specific hostname or port that isn't what you expect:
        /usr/share/logstash/pipeline/*.conf
        /etc/kafka/server.properties
        /opt/*/config/*.yml
     to confirm what the client is configured to reach.
  5. container_env(host, id, grep_pattern="KAFKA") — when the config
     is env-driven (most apache/kafka and confluentinc images):
     look for KAFKA_BOOTSTRAP_SERVERS, KAFKA_ADVERTISED_LISTENERS,
     ELASTICSEARCH_HOSTS.
```

## Change 4 — STATUS_PROMPT: minimal echo

In the existing `STATUS_PROMPT`, find the CONTAINER INTROSPECTION block
added by v2.34.12 and replace its body with:

```text
CONTAINER INTROSPECTION (v2.34.12):
For "is X running inside container Y" or "can container A reach container B"
questions, call container_discover_by_service (get IDs), then
container_tcp_probe (in-netns reachability) or container_config_read
(read config file). These return structured data in one call and avoid
the vm_exec allowlist/metachar filter. See investigate-agent prompt for
the full overlay-diagnosis pattern.
```

Observe is read-only + short-budget so it does not need the long overlay
pattern — just a clear "prefer these five tools over raw docker exec".

## Change 5 — ACTION_PROMPT: verify-step helpers

In the existing `ACTION_PROMPT`, replace the single line:

```text
For post-action verification, container_config_read and container_tcp_probe
are available (read-only).
```

with:

```text
POST-ACTION VERIFICATION (v2.34.12):
After a destructive operation, verify the fix with the read-only
container_* tools (no plan_action needed):

  container_tcp_probe(host, id, target_host, target_port)
    → confirm client-side reachability restored after network changes
  container_config_read(host, id, path)
    → confirm config written / unchanged after a service update
  container_networks(host, id)
    → confirm container attached to expected overlays after redeploy

Prefer these over re-running service_health alone — they answer "does
the client actually work now" rather than "is the container up".
```

## Change 6 — beef up container_introspect docstrings (first line)

In `mcp_server/tools/container_introspect.py`, each tool's docstring first
line is what the tool_registry surfaces as the OpenAI description. Change
the first lines to lead with the problem they solve, not a generic verb:

```python
def container_config_read(...):
    """Read a config file from inside a container — use instead of blocked
    'docker exec <id> cat <path>' (validated path allowlist, no shell)."""

def container_env(...):
    """Dump environment variables from inside a container — use instead of
    'docker exec <id> env' (secrets redacted automatically)."""

def container_networks(...):
    """List overlay networks and published ports for a container — use
    instead of 'docker inspect --format' to diagnose overlay mismatch."""

def container_tcp_probe(...):
    """Probe TCP reachability from INSIDE the container netns — definitive
    for overlay-layer routing questions. Uses bash </dev/tcp/>, so it works
    even when nc, ncat, curl are not installed in the image."""

def container_discover_by_service(...):
    """Swarm service name → [{node, vm_host_label, container_id,
    container_name}]. Replaces service_placement + docker ps chain."""
```

Keep the rest of each docstring intact (Args sections, body, etc.).

## Change 7 — tests

New file `tests/test_prompt_v2_34_13.py`:

```python
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
        lag_block = RESEARCH_PROMPT.split("CONSUMER LAG PATH")[1].split("BROKER MISSING")[0]
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
```

## Change 8 — Prometheus counter (optional but recommended)

In `api/metrics.py`, add:

```python
PROMPT_TOOL_MENTION_COUNTER = Counter(
    "deathstar_prompt_tool_mention_total",
    "Tool names mentioned in system prompts per agent type — "
    "a smoke test for prompt-retarget regressions",
    ["agent_type", "tool"],
)
```

On startup (in `api/main.py` lifespan hook, or similar early init), scan
each prompt once and increment:

```python
from api.agents.router import OBSERVE_PROMPT, INVESTIGATE_PROMPT, ACTION_PROMPT
from api.metrics import PROMPT_TOOL_MENTION_COUNTER

for agent_type, prompt in [
    ("observe", OBSERVE_PROMPT),
    ("investigate", INVESTIGATE_PROMPT),
    ("execute", ACTION_PROMPT),
]:
    for tool in ["container_config_read", "container_env",
                 "container_networks", "container_tcp_probe",
                 "container_discover_by_service", "vm_exec"]:
        if tool in prompt:
            PROMPT_TOOL_MENTION_COUNTER.labels(agent_type=agent_type, tool=tool).inc()
```

This becomes a trivial dashboard signal: if a future prompt refactor drops
the container_* tools, the counter goes to zero for that tool and is easy
to spot.

## Version bump

Update `VERSION`: `2.34.12` → `2.34.13`

## Commit

```
git add -A
git commit -m "fix(agents): v2.34.13 retarget prompts to prefer container_introspect over raw docker exec"
git push origin main
```

## How to test after push

1. Redeploy hp1_agent, pull new image.
2. Confirm via `/api/health`: version 2.34.13.
3. Re-run the exact Logstash prompt used in sessions 26cdd92b / a69fd96d:
   > Investigate why Logstash is not writing to Elasticsearch. Check Kafka
   > broker reachability from Logstash, including a network probe (nc -zv)
   > to broker 3 on port 9094, and correlate with consumer lag and cluster
   > health.
4. Expected observable changes in the trace:
   - `container_discover_by_service` called at least once (likely early,
     replacing the docker-ps step)
   - `container_tcp_probe` called at least once, from inside Logstash's
     netns, against broker 3 port 9094 — and the result is `reachable=false`
   - `container_networks` called at least twice (Logstash + broker-3) to
     expose the overlay mismatch
   - Zero BLOCKED `docker exec ... cat/curl/nc/bash -c` entries
   - Final answer names "Docker overlay hairpin NAT on worker-03" or an
     equivalent overlay/netns diagnosis — NOT "Verify broker 3 is listening"
5. Prometheus checks after the run:
   - `deathstar_container_introspect_total{tool="container_tcp_probe",outcome="ok"}` >= 1
   - `deathstar_container_introspect_total{tool="container_discover_by_service",outcome="ok"}` >= 1
   - `deathstar_agent_tool_calls_total{tool="vm_exec"}` strictly less than the
     a69fd96d baseline of 9 for an equivalent-depth run
   - `deathstar_prompt_tool_mention_total{agent_type="investigate",tool="container_tcp_probe"}` == 1
6. Run the new test suite: `pytest tests/test_prompt_v2_34_13.py -v`.

## Non-goals / deferred

- Not changing the semantic-rank path (`rank_tools_for_task`) — it is not
  wired into the agent loop today. If/when it gets wired, the boosted
  docstrings from Change 6 will help there too.
- Not re-organising `RESEARCH_PROMPT` overall. The existing sections stay;
  we add two blocks and tweak two in-place step lists. A full prompt
  refactor is deferred to v2.35.x (doc-coauthored, not one-shot CC).
- Not adding more container_* tools (e.g. container_logs_stream,
  container_exec_shell) — the five we have cover the high-frequency
  patterns. Add more only when a concrete trace shows the gap.
