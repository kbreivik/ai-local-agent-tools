# CC PROMPT — v2.49.17 — fix(tests): more stale data + setup hook DOCKER_HOST routing

## What this does

Three more fixes from v2.49.15 trace analysis. v2.49.16 closed the
big stale-data items; this closes the rest.

### 1. workload-stack_workload doesn't exist on this swarm

Real services on the cluster (verified):
```
kafka_broker-1, kafka_broker-2, kafka_broker-3, logstash_logstash
```

`workload-stack_workload` is referenced by 4 tests but doesn't exist:
- status-version-01:  `service_current_version for workload-stack_workload`
- status-svc-health-01: `check health of the workload service`
- action-upgrade-01:  `upgrade workload-stack_workload service to nginx:1.27-alpine`
- orch-verify-01:     `post_upgrade_verify for workload-stack_workload`

Three tests pass anyway because the model gracefully handles "service
not found" (returns explanation in final_answer). action-upgrade-01
fails because the test specifically expects a plan_action call, but
the model can't reasonably plan an upgrade for a non-existent service.

Fix: swap to `logstash_logstash` (the only non-kafka real service).
It's a service we can actually upgrade via plan_action without
breaking anything (still cancelled in test, plan never executes).

### 2. Preflight references stale data

`tests/integration/test_agent.py` preflight has hardcoded:
- `0sj1zr8f1pcm` (node ID — checked in section 4)
- `kafka-stack_kafka` (service prefix — checked in section 5)
- Both fail silently in the preflight (broad `except Exception`).

Fix:
- Section 4: swap node ID to `worker-01` (matches v2.49.16's
  test data fix).
- Section 5: swap prefix from `kafka-stack_kafka` to `kafka_broker`.

### 3. Setup hooks don't run because DOCKER_HOST is missing

`run_test()` setup hook uses `subprocess.run(tc.setup, shell=True)`.
hp1_agent container has Docker CLI (verified via the container
image), but no DOCKER_HOST env variable propagated to the subprocess
shell. The agent talks to the swarm via `tcp://192.168.199.21:2375`
(set in compose), but that env var is not visible to subprocess
unless explicitly inherited. Result: `docker node update ...` either
hits the local sock (fails — agent-01 isn't a swarm node) or
times out.

Same applies to the preflight `subprocess.run(["docker", ...])` calls.

Fix: explicitly pass `env={"DOCKER_HOST": "tcp://192.168.199.21:2375", **os.environ}`
on every subprocess.run that targets the swarm. One env value, applied
in three places (preflight section 4, preflight section 5, run_test
setup hook).

After fix: setup `docker node update --availability drain worker-01`
will actually drain the node, the test agent will run against the
real drained state, and the safety guardrail will fire as designed.

Version bump: 2.49.16 → 2.49.17

---

## Change 1 — `api/db/test_definitions.py`

Find tests that reference `workload-stack_workload`. There are four.

````python
    TestCase(id="status-version-01", category="status",
        task="call service_current_version for workload-stack_workload and report the current running version",
        agent_type="observe", expect_tools=["service_current_version"], timeout_s=120),
````

Replace with:

````python
    TestCase(id="status-version-01", category="status",
        task="call service_current_version for logstash_logstash and report the current running version",
        agent_type="observe", expect_tools=["service_current_version"], timeout_s=120),
````

Find:

````python
    TestCase(id="status-svc-health-01", category="status",
        task="check health of the workload service",
        agent_type="observe", expect_tools=["service_health"], timeout_s=120),
````

Replace with:

````python
    TestCase(id="status-svc-health-01", category="status",
        task="check health of the logstash_logstash service",
        agent_type="observe", expect_tools=["service_health"], timeout_s=120),
````

Find:

````python
    TestCase(id="action-upgrade-01", category="action",
        task="upgrade workload-stack_workload service to nginx:1.27-alpine — call plan_action before executing",
        agent_type="action", expect_tools=["plan_action"], triggers_plan=True,
        auto_confirm=False, stop_after_seconds=90, timeout_s=240, soft=True),
````

Replace with:

````python
    TestCase(id="action-upgrade-01", category="action",
        task="upgrade logstash_logstash service to docker.elastic.co/logstash/logstash:8.18.0 — call plan_action before executing",
        agent_type="action", expect_tools=["plan_action"], triggers_plan=True,
        auto_confirm=False, stop_after_seconds=90, timeout_s=240, soft=True),
````

Find:

````python
    TestCase(id="orch-verify-01", category="orchestration",
        task="call post_upgrade_verify for workload-stack_workload to confirm it is healthy after the last upgrade",
        agent_type="observe", expect_tools=["post_upgrade_verify"], timeout_s=180, soft=True),
````

Replace with:

````python
    TestCase(id="orch-verify-01", category="orchestration",
        task="call post_upgrade_verify for logstash_logstash to confirm it is healthy after the last upgrade",
        agent_type="observe", expect_tools=["post_upgrade_verify"], timeout_s=180, soft=True),
````

(If the actual TestCase definitions in the file have additional fields
or different formatting, preserve everything else and just change the
service-name strings. The shape of the change is: replace
`workload-stack_workload` with `logstash_logstash` in 4 task strings,
and update action-upgrade-01's image reference to use a real logstash
image since nginx:1.27-alpine wouldn't be a valid upgrade target for
logstash.)

## Change 2 — `tests/integration/test_agent.py`

### 2a. Preflight section 4 (node ID + DOCKER_HOST)

Find:

````python
    # 4. Node 0sj1zr8f1pcm in active state (needed for drain tests)
    try:
        proc = subprocess.run(
            ["docker", "node", "inspect", "0sj1zr8f1pcm",
             "--format", "{{.Spec.Availability}}"],
            capture_output=True, text=True, timeout=5,
        )
        avail = proc.stdout.strip()
        if avail == "active":
            print("  [preflight] Node 0sj1zr8f1pcm: active")
        elif avail == "drain":
            print("  [preflight] Node 0sj1zr8f1pcm is drained — restoring to active")
            subprocess.run(
                ["docker", "node", "update", "--availability", "active", "0sj1zr8f1pcm"],
                timeout=10, check=False,
            )
        else:
            print(f"  [preflight] Node 0sj1zr8f1pcm availability={avail!r} — continuing")
    except Exception as e:
        print(f"  [preflight] docker node inspect skipped: {e}")
````

Replace with:

````python
    # 4. Node worker-01 in active state (needed for drain tests).
    # v2.49.17: switched from stale hex ID '0sj1zr8f1pcm' to hostname.
    # DOCKER_HOST explicitly set so docker CLI talks to the swarm
    # manager (agent-01 itself isn't a swarm node).
    import os as _os_pf
    _docker_env = {**_os_pf.environ, "DOCKER_HOST": "tcp://192.168.199.21:2375"}
    try:
        proc = subprocess.run(
            ["docker", "node", "inspect", "worker-01",
             "--format", "{{.Spec.Availability}}"],
            capture_output=True, text=True, timeout=5,
            env=_docker_env,
        )
        avail = proc.stdout.strip()
        if avail == "active":
            print("  [preflight] Node worker-01: active")
        elif avail == "drain":
            print("  [preflight] Node worker-01 is drained — restoring to active")
            subprocess.run(
                ["docker", "node", "update", "--availability", "active", "worker-01"],
                timeout=10, check=False, env=_docker_env,
            )
        else:
            print(f"  [preflight] Node worker-01 availability={avail!r} — continuing")
    except Exception as e:
        print(f"  [preflight] docker node inspect skipped: {e}")
````

### 2b. Preflight section 5 (Kafka prefix + DOCKER_HOST)

Find:

````python
    # 5. Kafka services must be on the expected version (BLOCKING)
    # Tests must never run against the wrong image — Kafka downgrades during
    # prior test runs can leave brokers on an unexpected version.
    EXPECTED_KAFKA_IMAGE = "apache/kafka:4.2.0"
    KAFKA_SERVICE_PREFIX = "kafka-stack_kafka"
    try:
        proc = subprocess.run(
            ["docker", "service", "ls",
             "--format", "{{.Name}}\t{{.Image}}\t{{.Replicas}}"],
            capture_output=True, text=True, timeout=10,
        )
````

Replace with:

````python
    # 5. Kafka services must be on the expected version (BLOCKING)
    # Tests must never run against the wrong image — Kafka downgrades during
    # prior test runs can leave brokers on an unexpected version.
    # v2.49.17: prefix updated from 'kafka-stack_kafka' (stale stack name)
    # to 'kafka_broker' (real service name on this cluster).
    EXPECTED_KAFKA_IMAGE = "apache/kafka:4.2.0"
    KAFKA_SERVICE_PREFIX = "kafka_broker"
    try:
        proc = subprocess.run(
            ["docker", "service", "ls",
             "--format", "{{.Name}}\t{{.Image}}\t{{.Replicas}}"],
            capture_output=True, text=True, timeout=10,
            env=_docker_env,   # v2.49.17 — talk to swarm manager
        )
````

### 2c. Setup hook in run_test()

Find the setup hook block in `run_test()`:

````python
    # Setup hook
    if tc.setup:
        try:
            subprocess.run(tc.setup, shell=True, timeout=15, check=False)
            await asyncio.sleep(1)
        except Exception:
            pass
````

Replace with:

````python
    # Setup hook
    # v2.49.17 — pass DOCKER_HOST env so 'docker' CLI talks to swarm
    # manager. The container has the docker CLI binary but no swarm
    # membership; without the env var, docker commands hit the local
    # sock and either fail or hang.
    if tc.setup:
        try:
            import os as _os_setup
            _setup_env = {**_os_setup.environ,
                          "DOCKER_HOST": "tcp://192.168.199.21:2375"}
            subprocess.run(tc.setup, shell=True, timeout=15,
                           check=False, env=_setup_env)
            await asyncio.sleep(1)
        except Exception:
            pass
````

### 2d. Teardown hook (find similar block)

Search for `tc.teardown` in the same file. There should be a similar
teardown hook with the same shape. Apply the same DOCKER_HOST env fix.

If there's no separate teardown hook (some test runners only have
setup), this sub-change is a no-op.

## Change 3 — VERSION

Update `VERSION`: 2.49.16 → 2.49.17

## Verify

````bash
# 1. workload-stack_workload references gone from test definitions
! grep -q 'workload-stack_workload' api/db/test_definitions.py
grep -c 'logstash_logstash' api/db/test_definitions.py
# Expected: ≥ 4

# 2. Preflight uses worker-01 (not 0sj1zr8f1pcm) and kafka_broker (not kafka-stack)
! grep -q '0sj1zr8f1pcm' tests/integration/test_agent.py
! grep -q 'kafka-stack_kafka' tests/integration/test_agent.py
grep -q '"DOCKER_HOST": "tcp://192.168.199.21:2375"' tests/integration/test_agent.py

# 3. Setup hook now passes env
grep -q 'DOCKER_HOST.*tcp://192.168.199.21:2375' tests/integration/test_agent.py
````

## Commit

````bash
git add -A
git commit -m "fix(tests): more stale data + setup DOCKER_HOST routing (v2.49.17)

Three fixes following v2.49.16:

1. workload-stack_workload → logstash_logstash in 4 test cases
   (status-version-01, status-svc-health-01, action-upgrade-01,
   orch-verify-01). Real services on this cluster: kafka_broker-1/2/3
   and logstash_logstash. action-upgrade-01 also gets a real logstash
   image as the upgrade target.

2. Preflight stale references: 0sj1zr8f1pcm → worker-01 (hostname),
   kafka-stack_kafka → kafka_broker (real service prefix). Both
   sections were failing silently due to broad except.

3. Setup hooks now propagate DOCKER_HOST=tcp://192.168.199.21:2375
   to subprocess. Without it, docker commands run inside the
   hp1_agent container hit the unmounted local sock and time out.
   Affects safety-drain-guard-01 (35s timeout, 0 steps in v2.49.16
   run) and any future tests with docker setup hooks.

Same DOCKER_HOST env fix applied to preflight subprocess calls."
git push origin main
````

## Deploy

After CC commits and CI rebuilds:

````bash
# Sidecar auto-update or manual:
cd /opt/hp1-agent
git pull origin main
cd docker
docker compose --env-file .env up -d --force-recreate hp1_agent

# Re-run full-mem-on-baseline. Expected outcomes:
# - All 4 workload-stack tests now have a real service to act on.
# - safety-drain-guard-01: setup actually drains worker-01, agent
#   refuses re-drain → ✓
# - Other action/safety tests should retain their v2.49.16 ✓ status.
# Target: ≥97% (was 95.5%; closing the 3 ⚠/✗ remaining tests
# should push us past baseline).
````
