# CC PROMPT — v2.24.5 — Fix exit-137 diagnosis rule: require dmesg before concluding OOM

## What this does
The investigate agent twice misdiagnosed exit code 137 as OOM, when it was actually Docker
Swarm's normal container lifecycle SIGKILL. `free -m` only shows current memory — it cannot
confirm a past OOM kill. `dmesg` is the only reliable source. This prompt replaces the
misleading exit-137 rule in RESEARCH_PROMPT with a mandatory dmesg-first verification step,
and explicitly documents that Swarm leaves exit-137 records for every container replacement.
Version bump: v2.24.4 → v2.24.5

## Change 1 — api/agents/router.py

In `RESEARCH_PROMPT`, find this block:

```
For container crash loops (exit codes found via docker ps):
  - exit code 255 = JVM crash or startup failure (check docker logs for OOM/config error)
  - exit code 143 = SIGTERM (graceful shutdown — usually Swarm orchestration)
  - exit code 137 = SIGKILL (OOM kill — check free -m on the node first)
  If you see exit 137: call vm_exec(host="<node>", command="free -m") FIRST to check
  available memory — this is likely the root cause.
```

Replace it with:

```
For container crash loops (exit codes found via docker ps):
  - exit code 255 = JVM crash or startup failure (check docker logs for OOM/config error)
  - exit code 143 = SIGTERM (graceful shutdown — Swarm orchestration or manual stop)
  - exit code 137 = SIGKILL — DO NOT ASSUME OOM. See rule below.

EXIT CODE 137 — MANDATORY VERIFICATION RULE:
Exit 137 = SIGKILL. In Docker Swarm this has two very different causes:
  CAUSE A — Swarm lifecycle (normal, NOT a problem):
    Swarm sends SIGKILL to the old task container every time a service restarts,
    force-updates, or converges. Every container replacement leaves an exited-137
    record in `docker ps -a`. This is completely normal orchestration behaviour.
  CAUSE B — Kernel OOM killer:
    The Linux kernel kills the process when the node runs out of memory.
    This is a real problem that needs fixing.
The ONLY way to distinguish them is `dmesg`. You MUST run this before concluding OOM:
  vm_exec(host="<node>", command="dmesg | grep -iE 'oom|killed process|out of memory' | tail -20")
  → Lines like "oom-kill event" or "Killed process <pid> (java)" = confirmed OOM (CAUSE B)
  → Empty output = NOT an OOM kill — this is Swarm lifecycle (CAUSE A), not a memory problem
Only AFTER dmesg confirms OOM should you call vm_exec(free -m) to assess current pressure.
NEVER report "OOM kill" or recommend heap reduction based on exit 137 alone.
NEVER treat multiple exited-137 containers as evidence of OOM — that is expected Swarm state.
```

## Version bump
Update VERSION file: v2.24.4 → v2.24.5

## Commit
```
git add -A
git commit -m "fix(agent): require dmesg before concluding OOM from exit code 137 (v2.24.5)"
git push origin main
```
