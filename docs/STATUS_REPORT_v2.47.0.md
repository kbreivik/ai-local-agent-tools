# DEATHSTAR Platform — Status Report
**Generated:** 2026-04-25 | **Version:** v2.47.0 | **Build:** #737 (61a430d)
**Previous report:** docs/STATUS_REPORT_v2.45.17.md (v2.45.17, 2026-04-24)

---

## 0. Summary

Since v2.45.17 the codebase shipped 16 queue-driven prompts (v2.45.18 → v2.45.33),
two operator-driven minor bumps (v2.46.0 sensor stack, v2.47.0 sensor cleanup),
and the new **three-layer sensor stack** (ruff/bandit/gitleaks/eslint/mypy +
agent-mode runner + GitHub Action). Major fixes: clarify→plan_action message
injection (v2.45.18), schedule executor wired up (v2.45.19), nginx TLS reverse
proxy + secure cookies (v2.45.29), `agent_observation` write path live (v2.45.25),
elastic + network_ssh + vm_hosts fact writes (v2.45.23/30), and deterministic
clarification/plan handling (v2.45.32). Code split partially regressed: `pipeline.py`
landed cleanly but `step_tools.py` and `preflight.py` grew well past v2.45.17
targets. Sensor stack runs clean against the v2.47.0 baseline. Live test/DB
metrics could not be pulled from this environment — see §2/§5/§6 for the data
gaps.

---

## 1. What shipped since v2.45.17

`git log f84fdda..HEAD --oneline` (23 commits). Grouped by theme:

### Agent / orchestration fixes
| Version | Subject |
|---------|---------|
| v2.45.18 | inject clarify→plan_action system message into LLM messages list |
| v2.45.27 | sliding-window zero-ratio guard — catches loop patterns the consecutive guard misses |
| v2.45.31 | skip auto-prepended observe step when task names plan_action explicitly |

### Test harness / determinism
| Version | Subject |
|---------|---------|
| v2.45.19 | schedule executor — read test_schedules and fire runs at cron times |
| v2.45.20 | timeout headroom — research-versions-01 + clarify-01 + action-rollback-01 + safety-no-plan-01 |
| v2.45.32 | deterministic clarification/plan handling + per-test trace + memory restore |

### Facts pipeline
| Version | Subject |
|---------|---------|
| v2.45.23 | elastic + network_ssh collectors write to known_facts_current |
| v2.45.25 | agent_observation write path — drain state.run_facts to known_facts_current |
| v2.45.30 | vm_hosts services dict iteration + extraction visibility logging |

### Security
| Version | Subject |
|---------|---------|
| v2.45.21 | protect /metrics with auth + warn on CORS_ALLOW_ALL |
| v2.45.29 | nginx TLS reverse proxy + secure cookie behind HTTPS (opt-in) |

### UI / settings
| Version | Subject |
|---------|---------|
| v2.45.22 | wire PreflightPanel — preflight_needed handler + Commands view import |
| v2.45.24 | Facts & Knowledge settings tab |
| v2.45.26 | runbookInjectionMode default — align with implemented behaviour (replace) |
| v2.45.28 | Trend tab suite filter + Compare tab run-picker filters |

### Sensor stack (v2.46.x + v2.47.0)
| Commit / version | Subject |
|------------------|---------|
| v2.46.0 (8a70589) | three-layer sensor stack (ruff/bandit/gitleaks/eslint/mypy) |
| 9182685 | docs(claude): refresh CLAUDE.md to current state |
| 07d69a6 | fix(sensors): calibrate bandit/gitleaks/mypy after first CI run |
| f346017 | fix(sensors): bandit YAML format + scoped gitleaks rules |
| 62d4435 | docs(claude): add agent workflow rule to Sensor Protocol |
| v2.47.0 (61a430d) | clear 5 sensor violations from v2.46.0 baseline |

**Operator-driven bumps:** v2.46.0 and v2.47.0 are manual minor bumps (not via
the CC queue) carrying the queue-driven v2.45.32 + v2.45.33 fixes plus the
sensor stack. The CC queue is currently at `261/262 done` per
`cc_prompts/QUEUE_STATUS.md` (this prompt is the 262nd).

---

## 2. Test results

**Source: not pulled.** The test_runs / test_run_results queries in the prompt
require either a running local Postgres (port 5433 closed locally), an SSH
session into agent-01 (`Permission denied (publickey)` from this env), or
authenticated calls to `/api/tests/runs` (returns `Not authenticated`).

There are no JSON fallback files on disk — `reports/` only contains
`test_cycles.html` (last touched 2026-04-17, before the v2.45.32 deterministic
test changes). No `tests/results/*.json` or similar in the working tree.

**Status:** No A/B baseline reported in this audit. **Re-baseline needed**
after v2.45.32 deterministic-handling + v2.45.33 last_reasoning fixes
deployed (build #737 is now serving v2.47.0). Suggested next action: run
`smoke-mem-on-fast`, `full-mem-on-baseline`, `full-mem-off-baseline` and
re-pull these tables for the v2.47.x report.

What we do know from git: tests-related fixes that should move the score up
since v2.45.17:

- v2.45.18 should fix the two `clarify → audit_log` failures
  (`action-drain-01`, `action-activate-01`).
- v2.45.20 should clear the three "1-3s over the timeout" failures
  (research-versions-01, clarify-01, action-rollback-01) that were noted in
  v2.45.17 §1.
- v2.45.27 sliding-window zero-ratio guard targets the elastic_search_logs
  loop pattern (`research-elastic-search-01`, `orch-correlate-01`).
- v2.45.32 deterministic clarification/plan handling plus per-test trace
  output should make the A/B comparison itself more stable run-to-run.

Whether each prediction holds is exactly what the next baseline run answers.

---

## 3. Sensor stack

`make check-agent` (run via `python scripts/check_sensors.py` from this env):

```
# skipped: bandit (not installed — pip install bandit)
# skipped: gitleaks (not installed — see github.com/gitleaks/gitleaks)
EXIT: 0
```

**Status: Clean** for the tools available locally (ruff, eslint, mypy).
bandit and gitleaks are wired in CI (`.github/workflows/sensors.yml`) but not
installed in this dev shell. The v2.47.0 cleanup commit (61a430d) cleared the
five violations remaining from the v2.46.0 baseline, so CI should also be
green at HEAD. Calibrated thresholds are documented in `CLAUDE.md` §Sensor
Protocol — the headline numbers (max-complexity 80, max-lines 4000, etc.)
catch new outliers without flagging existing peaks.

---

## 4. Code architecture

`wc -l` on the agent loop split modules at HEAD:

| Module | v2.45.17 | v2.47.0 | Δ | Target | Status |
|--------|----------|---------|---|--------|--------|
| `api/routers/agent.py` | 3,445 | **3,180** | −265 | <2,000 | ❌ Still large |
| `api/agents/pipeline.py` | (n/a) | **446** | new | <300 | ⚠️ Above target on first pass |
| `api/agents/orchestrator.py` | (n/a) | **525** | new | <400 | ⚠️ Just over |
| `api/agents/context.py` | 167 | 167 | 0 | <300 | ✅ |
| `api/agents/gates.py` | 172 | 172 | 0 | <300 | ✅ |
| `api/agents/step_state.py` | (n/a) | 96 | new | <150 | ✅ |
| `api/agents/step_llm.py` | 203 | 203 | 0 | <300 | ✅ |
| `api/agents/step_guard.py` | 295 | 295 | 0 | <300 | ✅ |
| `api/agents/step_facts.py` | 192 | **254** | +62 | <300 | ✅ |
| `api/agents/step_synth.py` | 118 | 118 | 0 | <300 | ✅ |
| `api/agents/step_tools.py` | 1,201 | **1,438** | +237 | <400 | ❌ Grew, not shrank |
| `api/agents/step_persist.py` | (n/a) | 91 | new | <150 | ✅ |
| `api/agents/preflight.py` | (n/a) | **1,148** | new | <500 | ❌ Materially over target |
| `api/agents/external_router.py` | (n/a) | 266 | new | <300 | ✅ |
| `api/agents/external_ai_client.py` | (n/a) | 414 | new | <500 | ✅ |
| `api/agents/router.py` | 2,295 | 2,295 | 0 | ~2,000 | ✅ Mostly prompts |
| `api/main.py` | n/a | 819 | — | — | watch (lifespan complexity 95) |
| `api/maintenance.py` | n/a | 155 | — | — | ✅ |
| `api/scheduler.py` | n/a | 129 | — | — | ✅ |

**Observations:**

- `pipeline.py` (v2.45.17) extraction landed but at 446 lines is already above
  the original <300 target. Worth a follow-up split.
- `step_tools.py` **grew by 237 lines** despite the v2.45.16 dispatcher split.
  Subsequent fact/clarification logic appears to be re-accumulating in this
  file. This is the standout regression.
- `preflight.py` at **1,148 lines** is the largest agent module after `router.py`.
  It didn't exist at v2.45.17. Likely a candidate for the next architectural
  prompt — split by check category (kafka, swarm, vm, network) following the
  step_*.py pattern.
- `orchestrator.py` (525) and `pipeline.py` (446) together suggest the
  `_stream_agent` extraction is partial; common helpers may want to move into
  a third module.

Headline conclusion: **the split is ~60% done, with two new offenders
(step_tools.py regression + preflight.py size) that warrant queue prompts
before the next minor bump.**

---

## 5. Facts coverage

**Source: not pulled.** `known_facts_current` query needs DB access (see §2).

What we know from the git log + code:

| Source | Expected status (per shipped code) | Confirmed live? |
|--------|------------------------------------|-----------------|
| proxmox | writing (v2.39.x) | unverified |
| pbs | writing (v2.39.x) | unverified |
| swarm | writing (v2.39.x) | unverified |
| docker_agent | writing (v2.39.x) | unverified |
| kafka | writing (v2.39.x) | unverified |
| elastic | writing (v2.45.23) | unverified |
| network_ssh | writing (v2.45.23) | unverified |
| vm_hosts | writing (v2.45.30 — services dict iteration fix) | unverified |
| unifi | writing (v2.39.x) | unverified |
| fortigate | writing (v2.39.x) | unverified |
| **agent_observation** | writing (v2.45.25 drain path) | unverified |
| fortiswitch | **not writing** (TODO §Open ideas) | confirmed gap |
| external_services | **not writing** (TODO §Open ideas) | confirmed gap |

The v2.45.17 report flagged `agent_observation` as "deferred since v2.35.2 —
never implemented." That gap closed at v2.45.25 (`660d30b feat(facts):
agent_observation write path — drain state.run_facts to known_facts_current`).
Whether facts are actually accumulating with `source=agent_observation` is the
exact thing the next DB pull should answer.

`vm_hosts` was reported as "silent failures from credential profile issues" at
v2.45.17. v2.45.30 specifically targets a services-dict iteration bug + adds
extraction visibility logging — should be measurable in the source distribution.

---

## 6. agent_attempts summary

**Source: not pulled.** Same DB-access constraint as §2/§5.

The v2.45.33 fix moved `last_reasoning` so `record_attempt` populates
`agent_attempts.summary` (pre-fix the column was always empty).
Verification query is documented in this prompt for whoever runs the next
audit. Pre-fix expectation: `populated = 0`. Post-fix expectation (for runs
after v2.45.33 deployed, i.e. build #737 onwards): most rows populated.

The fix is in HEAD per the v2.45.32 commit (ec59672). The report row stays
**unverified** until the DB is queryable.

---

## 7. Working-tree state

`git status --porcelain`:

```
 M ROADMAP.md
 M TODO.md
 M cc_prompts/INDEX.md
 M cc_prompts/QUEUE_STATE.json
 M cc_prompts/QUEUE_STATUS.md
?? .claude/scheduled_tasks.lock
?? cc_prompts/CC_PROMPT_v2.47.1.md
?? cc_prompts/logs/20260425_195906_CC_PROMPT_v2.47.1.log
```

`git diff --stat HEAD`: 5 files changed, +282 / −1,221 (net rewrite of
`ROADMAP.md` and `TODO.md` by the operator — both shrunk substantially).

Nothing in the agent/code paths is uncommitted. The queue-runner files are
the runtime delta from this prompt's invocation. ROADMAP.md and TODO.md
edits are the operator's recent rewrites and are not part of this report's
scope (per the prompt's explicit DO-NOT list).

---

## 8. Open items

Pulled from `TODO.md`:

**Operational (🟡):**
- Kafka DEGRADED — `worker-03` Down → broker-3 unscheduled. Reboot via Proxmox
  is the fix (no code change). Same status as v2.45.17.
- Proxmox Cluster FIN — VPN dependency on dev PC. Same as v2.45.17.

**Open ideas (🔵):**
- Real notification delivery test (SMTP + webhook end-to-end)
- Auth hardening verification checklist (HttpOnly + Secure cookie under
  `HP1_BEHIND_HTTPS=true`, rate-limit smoke, API token bearer)
- Multi-connection scope audit (`get_connection_for_platform` LIMIT 1 sites)
- Multi-agent parallel execution (sub-agent concurrency design)
- `runbookInjectionMode=augment` real implementation
- External AI output modes — `augment` / `side-by-side` real implementation
- Entity timeline view (data live, UI surface missing)
- Agent task templates — expand library
- FortiSwitch + `external_services` known_facts writes (last 2 collectors)

---

## 9. Scorecard

| Area | v2.45.17 | v2.47.0 | Notes |
|------|----------|---------|-------|
| Test harness | B+ | **B?** | Schedule executor wired (v2.45.19) ✅. A/B re-baseline needed before grade can move. |
| Agent behaviour | B | **B+?** | clarify→plan_action injection (v2.45.18), zero-ratio loop guard (v2.45.27), deterministic clarify (v2.45.32) all queued — verification pending. |
| Code structure | B | **C+** | `pipeline.py` extraction landed but `step_tools.py` regrew +237 LOC and `preflight.py` arrived at 1,148 LOC. Net regression on file-size discipline. |
| Security | C+ | **B−** | TLS reverse proxy (v2.45.29, opt-in) + secure cookies under HTTPS + `/metrics` auth (v2.45.21) + CORS warn — addresses two HIGH items from v2.45.17. Still no enforced TLS, rate limiter still in-memory. |
| UI completeness | A− | **A−** | Trend per-suite filter + Compare run picker (v2.45.28) closed v2.45.17's UX gaps. Facts & Knowledge settings tab (v2.45.24) closed the missing settings group. |
| Fact coverage | (n/a) | **B?** | All write paths shipped (elastic+network_ssh v2.45.23, agent_observation v2.45.25, vm_hosts fix v2.45.30). Live confirmation pending §5. FortiSwitch + external_services gaps remain. |
| Infra coverage | A− | A− | Unchanged. worker-03 still Down, FortiSwitch noise still suppressed. |
| Memory (A/B) | B+ | **unknown** | No re-baseline since v2.45.17. |
| Ops readiness | B | **B+** | Scheduled test runs live (v2.45.19). Sensor stack + CI gating new (v2.46.0). TLS still opt-in. |
| **Sensor stack (new)** | — | **A** | Three-layer (ruff/bandit/gitleaks/eslint/mypy), agent-mode output, GitHub Action with sticky PR comment, calibrated thresholds, agent self-correct rule in CLAUDE.md. Clean at v2.47.0. |

**Overall:** **B+ (was B).** Notable forward motion in security (TLS + cookie
work), facts pipeline (3 collectors + agent_observation), test determinism,
and the entirely new sensor stack. Drag from code structure: the
`step_tools.py` regrowth and `preflight.py` size mean the architectural-split
narrative has paused. Two big unknowns (test A/B + facts/agent_attempts DB
state) are blocking a confident grade — first job for the v2.47.x cycle
should be to re-baseline both.
