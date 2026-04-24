# CC PROMPT — v2.45.12 — fix(tests): suppress collector alerts during test runs

## Root cause

During test runs the test runner executes up to 20 steps × N tests worth of
agent calls, many of which use `vm_exec` (SSH) and `swarm_node_status` on all
6 worker/manager VMs simultaneously. This SSH load causes:

1. `network_ssh: unconfigured → error` — the FortiSwitch SSH collector tries to
   poll during a test run, finds connections exhausted/timing out, and fires a
   dashboard alert via `check_transition`.

2. `vm_hosts: degraded → healthy` — worker VMs go briefly degraded under SSH
   load, then recover, firing a second alert.

These are test-run artefacts — real state changes caused by the test load, but
not real production incidents. They clutter the alert feed and alarm the operator.

Fix: expose a module-level flag `test_run_active` from `api/routers/tests_api.py`
and check it in `api/alerts.py::check_transition`. While a test run is active,
skip non-critical alert transitions (severity < "critical" / sev < 3).
Critical alerts (error, critical) still fire so genuine production failures
are not silenced.

Version bump: 2.45.11 → 2.45.12.

---

## Change 1 — `api/routers/tests_api.py`

Replace the existing `_running` global with a named export:

Find:
```python
_running = False
```

Replace with:
```python
_running = False

# Exported flag — checked by api/alerts.py to suppress collector noise
# during test runs (SSH load from agents causes false vm_hosts/network_ssh alerts)
test_run_active = False
```

Find the two places where `_running` is set (at the start and end of
`_run_tests_bg`) and add mirrored assignments to `test_run_active`:

```python
# At the top of _run_tests_bg (after global _running):
    global _running, test_run_active
    _running = True
    test_run_active = True
```

```python
# In the finally block:
    finally:
        _running = False
        test_run_active = False
```

---

## Change 2 — `api/alerts.py`

In `check_transition`, add a suppression check after the `if prev is None: return`
guard:

Find:
```python
    if prev is None:
        return  # First poll — no transition yet

    prev_sev = _sev(prev)
    curr_sev = _sev(current_health)

    if curr_sev == prev_sev:
        return  # No change
```

Replace with:
```python
    if prev is None:
        return  # First poll — no transition yet

    prev_sev = _sev(prev)
    curr_sev = _sev(current_health)

    if curr_sev == prev_sev:
        return  # No change

    # Suppress non-critical collector noise while a test run is active.
    # (SSH load from test agents causes transient vm_hosts/network_ssh transitions
    # that are artefacts of the test, not real production incidents.)
    # Critical alerts (sev >= 3: error/critical) always fire.
    if curr_sev < 3:
        try:
            from api.routers.tests_api import test_run_active as _tra
            if _tra:
                log.debug(
                    "ALERT suppressed during test run: %s %s → %s",
                    component, prev, current_health,
                )
                return
        except ImportError:
            pass
```

---

## Version bump

Update `VERSION`: `2.45.11` → `2.45.12`

---

## Commit

```
git add -A
git commit -m "fix(tests): v2.45.12 suppress non-critical collector alerts during test runs"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
