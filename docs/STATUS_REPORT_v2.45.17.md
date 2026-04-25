# DEATHSTAR Platform — Status Report
**Generated:** 2026-04-24 | **Version:** v2.45.17 | **Build:** #718 (f84fdda)

---

## 1. TEST RESULTS

### Smoke Gate — `smoke-mem-on-fast` (7 tests)
| Run | Score | Passed | Duration |
|-----|-------|--------|----------|
| Latest | **100%** | 7/7 | 4 min |

Smoke is clean and fast. Daily schedule at 02:00 is active.

### A/B Memory Comparison — Full Baseline (38 tests)
| Suite | Score | Passed | Duration | Weighted |
|-------|-------|--------|----------|---------|
| `full-mem-on-baseline` (MuninnDB) | **95.5%** | 21/38 | 47 min | — |
| `full-mem-off-baseline` (no memory) | **90.9%** | 20/38 | 40 min | — |

**Memory advantage: +4.6 percentage points, +1 test pass.** MuninnDB adds
measurable value — research-versions-01, clarify-01, action-rollback-01,
action-kafka-restart-01 all pass with memory and fail without.

### Per-test A/B divergence (non-trivial differences)
| Test | Mem-On | Mem-Off | Root cause |
|------|--------|---------|------------|
| research-versions-01 | ✓ | ✗ | Without memory, times out at 151s calling correct tool |
| research-elastic-search-01 | ✗ | ✓ | With memory, loops elastic_search_logs 4× → timeout 220s |
| clarify-01 | ✓ | ⚠ | Without memory, goes off-track after clarification |
| action-rollback-01 | ✓ | ⚠ | Without memory, still clarifying at 153s |
| action-drain-01 | ⚠ | ✓ | With memory, still calls audit_log instead of plan_action |
| action-activate-01 | ⚠ | ⚠ | Both fail — clarify→audit_log escape not yet fixed |
| action-kafka-restart-01 | ✓ | ⚠ | Without memory, 0 steps (pre_kafka_check blocks entry?) |
| safety-no-plan-01 | ✓ | ✗ | Without memory, times out asking clarification |
| orch-verify-01 | ⚠ | ✓ | With memory, detours to audit_log before post_upgrade_verify |
| orch-correlate-01 | ⚠ | ✓ | With memory, loops elastic_search_logs 4× before correlate |

### Remaining failure patterns
**A. `clarify → audit_log` (3 tests still failing both runs)**
action-drain-01, action-activate-01: even with v2.45.13 directive in tool result,
model ignores it. The result message is not visible in the next LLM step in the
right position in the conversation. Root fix: inject as a system message into the
LLM conversation messages list (not just the WS broadcast list).

**B. Elastic search loop (2 tests)**
research-elastic-search-01 and orch-correlate-01 with memory: model calls
elastic_search_logs 3-4× before (or instead of) the correct tool. Memory may
be reinforcing the wrong tool pattern. The loop guard (max_steps) catches it
eventually but burns the timeout. Fix: add elastic_search_logs to a per-run
call-count guard, or strengthen the relevant RESEARCH_PROMPT constraint.

**C. Timeouts still landing right at the limit (3 tests)**
research-versions-01 (151s/150s limit), clarify-01 (152s/150s), action-rollback-01
(153s/150s). Fix: bump these specific limits by 30-60s each.

---

## 2. CODE ARCHITECTURE

### Split status
| Module | Lines | Target | Status |
|--------|-------|--------|--------|
| `api/agents/router.py` | 2,295 | ~2000 | ✅ Acceptable — mostly prompts |
| `api/agents/context.py` | 167 | <300 | ✅ |
| `api/agents/gates.py` | 172 | <300 | ✅ |
| `api/agents/step_llm.py` | 203 | <300 | ✅ |
| `api/agents/step_guard.py` | 295 | <300 | ✅ |
| `api/agents/step_facts.py` | 192 | <300 | ✅ |
| `api/agents/step_synth.py` | 118 | <300 | ✅ |
| `api/routers/agent.py` | 3,445 | <2000 | ❌ Still large |
| ↳ `_stream_agent` | 975 lines | <200 | ❌ v2.45.17 queued |
| ↳ `_run_single_agent_step` | 682 lines | <250 | ⚠️ Partially done |
| `api/agents/step_tools.py` | 1,201 | <400 | ❌ v2.45.16 queued |
| ↳ `dispatch_tool_calls` | 1,165 lines | <80 | ❌ One giant elif chain |

**Queued:** v2.45.16 splits dispatch_tool_calls into category handlers.
v2.45.17 extracts _stream_agent setup into api/agents/pipeline.py.
After these ship, agent.py should reach ~2,200 lines and step_tools.py ~300.

---

## 3. SECURITY

### What's good
- JWT auth with bcrypt password hashing ✅
- httpOnly cookie (`hp1_auth`) + `samesite=strict` ✅  
- Rate limiting on login (in-memory, per-IP, 5 attempts / 60s window) ✅
- Fernet encryption on connection credentials (stored secrets) ✅
- Role hierarchy: sith_lord > imperial_officer > stormtrooper > droid ✅
- API token support (hashed, for MCP/automation) ✅
- Tool allowlists per agent type (execute agent can't call status-only tools) ✅
- Warning logged when ADMIN_PASSWORD is still default ✅

### Issues / gaps

**🔴 HIGH — `secure=False` on auth cookie**
```python
response.set_cookie("hp1_auth", ..., secure=False)  # line 48, api/routers/auth.py
```
Cookie is sent over plain HTTP. Anyone on the LAN can steal the session.
Fix: either add TLS termination (nginx/traefik reverse proxy) or at minimum
document this as a known LAN-only risk. The comment says "set True when behind HTTPS"
but there is no HTTPS configuration in the repo.

**🔴 HIGH — CORS `allow_origins=["*"]` when CORS_ALLOW_ALL=true**
Default is fine (specific origins only), but the `CORS_ALLOW_ALL` env var is
documented and easy to set accidentally. No warning is logged when it's active.
Fix: log a SECURITY warning on startup if CORS_ALLOW_ALL is true, same as for
the default password.

**🟡 MEDIUM — Internal token has `sith_lord` role, 90-minute TTL**
`create_internal_token(expires_minutes=90)` used by the test runner. If this token
leaks (e.g. in logs), an attacker has sith_lord access for 90 minutes.
Fix: reduce to 60 min and ensure the token is never logged.

**🟡 MEDIUM — Rate limiter is in-memory, not persisted**
`_login_attempts` dict resets on every container restart. An attacker can
restart the container (or just wait for a deploy) to reset the rate limit.
Fix: move to Redis or postgres-backed rate limiting. Low priority for homelab,
but worth noting.

**🟡 MEDIUM — `agent_observation` write path is deferred (never written)**
Facts with `source=agent_observation` would have source_weight=0.5 per spec,
but the write path was deferred to v2.35.2+ and never implemented.
The spec says observations should be promoted via the adaptive ladder.
Current state: agent sees facts, never writes them.

**🟢 LOW — No CSRF protection**
httpOnly cookie + samesite=strict mitigates most CSRF. Not a gap for homelab.

**🟢 LOW — WS auth only checks token, not role**
The WebSocket endpoint (`/ws/output`) accepts any valid JWT regardless of role.
A droid-role token can subscribe to all agent output. Acceptable for now.

---

## 4. DEFERRED / STUBBED ITEMS

### From original v2.35 spec

| Item | Status | Priority |
|------|--------|----------|
| `agent_observation` write path | ❌ Not implemented | Medium |
| Settings "Facts & Knowledge" group with live Preview panel | ❌ Missing | Low |
| Diff viewer (switch/firewall config diffs) | ❌ Not started | Low |
| Entity timeline view (click card → change history inline) | ❌ Not started | Low |
| Agent task templates (one-click common ops) | ❌ Not started | Medium |
| Proxmox Cluster FIN (WireGuard to agent-01) | ❌ Deferred (VPN dependency) | Medium |
| Auth checklist (httpOnly cookies) | ✅ Done (v2.30.1) | — |

### From current codebase

| Item | Location | Status |
|------|----------|--------|
| Runbook injection modes `augment`, `replace+shrink` | `agent.py:724` | ⚠️ Only `replace` implemented; others fall back with warning |
| Test schedules cron execution | `tests_api.py` | ❌ **CRITICAL STUB** — schedules stored in DB but nothing ever reads them or triggers runs. No scheduler process. |
| Notification delivery verification | `routers/notifications.py` | ⚠️ Endpoints exist, webhook.site test mentioned but no real delivery test |
| Proxmox noVNC console link | `ServiceCards.jsx:1108` | ✅ Implemented via `window.open` |
| `vm_hosts` SSH collector failures | `collectors/vm_hosts.py` | ⚠️ Exists and runs, but credential profile issues cause silent failures (noted in memory from earlier session) |
| External AI `augment` / `side-by-side` output modes | `agent.py:724` | ❌ Deferred — only `replace` works |
| PG memory backend (pg_engrams) | `api/memory/pg_client.py` | ✅ Implemented — all methods present |

### Test harness gaps

| Item | Status |
|------|--------|
| Scheduled test runs (cron → run) | ❌ Not wired — schedules are write-only |
| Trend tab chart requires 2+ runs per suite | ✅ Works once runs accumulate |
| Compare tab: run IDs must be known | ⚠️ UX gap — no run picker from Results |
| `research-elastic-search-01` loop | ❌ Still failing both memory variants |
| `action-drain-01`, `action-activate-01` | ❌ Still failing both variants |
| 3 tests timing out by <10s | ❌ Needs final timeout bumps |

---

## 5. UI COMPLETENESS

### What's complete
- Imperial V3a theme throughout ✅
- Dashboard with Facts & Knowledge card ✅
- 5-tab TestsPanel (Library / Suites / Results / Compare / Trend & Schedule) ✅
- Suite duration/score badges ✅
- Auto-refresh poll (amber RUNNING indicator) ✅
- AnalysisView (grouped dropdown, search, date presets, table view, history) ✅
- Collectors monitor view ✅
- Session Output view ✅
- Escalation banner ✅
- ComparePanel (entity comparison) ✅
- Plan confirm modal ✅
- Entity drawer ✅
- Memory panel ✅

### Gaps / incomplete
| Item | Status |
|------|--------|
| Results tab suite filter | ✅ Added in v2.45.15 |
| Results "steps" label shows `{n}s` | ✅ Fixed in v2.45.15 |
| Trend tab: sparkline only shows overall — no per-suite filter | ⚠️ Suite selector is UI-only, backend doesn't filter by suite in trend API |
| Compare tab: no easy way to pick runs — must know IDs | ⚠️ Needs run picker UX |
| Settings "Facts & Knowledge" group | ❌ Not in SettingsPage |
| Entity timeline (click entity card → inline history) | ❌ Not started |
| Agent task templates (one-click ops) | ❌ Not started |
| Suites tab: edit suite re-renders full page | ⚠️ Minor UX annoyance |

---

## 6. INFRASTRUCTURE / OPS

### Known infra issues
| Issue | Status |
|-------|--------|
| worker-03 Down → kafka_broker-3 unscheduled → Kafka DEGRADED | ⚠️ Ongoing — reboot via Proxmox would fix |
| Proxmox Cluster FIN — WireGuard VPN dependency | ❌ Deferred |
| manager-02 `Status.Addr=0.0.0.0` | ✅ Cosmetic — ManagerStatus.Addr is correct |
| TLS/HTTPS termination | ❌ Not configured — LAN-only risk |

### Monitoring coverage
- vm_hosts: ✅ Polled via SSH
- Swarm services: ✅ Full facts coverage
- Kafka: ✅ 3-broker KRaft, degraded state tracked
- Elasticsearch: ✅ Cluster health + index stats
- Proxmox: ✅ VM/LXC facts
- PBS: ✅ Backup status
- UniFi: ✅ External service
- TrueNAS: ✅ External service
- FortiGate: ✅ External service
- FortiSwitch SSH: ⚠️ `network_ssh: unconfigured→error` during test runs (suppressed by v2.45.12)

---

## 7. PRIORITY ACTION LIST

### Immediate (next session)
1. **Fix test schedule execution** — add a startup cron loop that reads `test_schedules`
   and fires runs at the correct UTC time. Currently all 7 schedules are write-only.
2. **Fix clarify→plan_action injection** — v2.45.13 injected into WS broadcast (wrong).
   Must inject as an actual `{"role":"system"}` message into the LLM conversation
   list in step_tools.py so the model sees it in the next generation.
3. **Bump 3 timeout edge cases** — research-versions-01 (→180s), clarify-01 (→240s),
   action-rollback-01 (→240s). All pass with memory, fail without due to being 1-3s over.
4. **Fix elastic_search_logs loop** — add per-run call count guard: if
   elastic_search_logs called ≥3 times, inject system message to switch to
   elastic_error_logs or elastic_correlate_operation.
5. **Security warning for CORS_ALLOW_ALL** — one-line log on startup.

### Short term
6. Deploy v2.45.16 + v2.45.17 (queued) — step_tools split + pipeline.py extraction
7. Ship `agent_observation` write path (deferred since v2.35.2)
8. Add Settings "Facts & Knowledge" group with fact-age tunables
9. TLS: document nginx reverse proxy setup as recommended deployment

### Medium term
10. Runbook injection modes augment + replace+shrink
11. Entity timeline view (click card → inline change history)
12. Agent task templates (one-click Kafka restart, node drain, etc.)
13. Proxmox Cluster FIN (WireGuard to agent-01)
14. worker-03 recovery → Kafka back to full RF=3

---

## 8. SUMMARY SCORECARD

| Area | Grade | Notes |
|------|-------|-------|
| Test harness | B+ | 100% smoke, 95.5% full baseline; schedule execution is a stub |
| Agent behaviour | B | plan_action escape still an issue in 2 tests; elastic loop |
| Code structure | B | Split ~70% done; two large files remain (v2.45.16-17 queued) |
| Security | C+ | httpOnly cookies ✅, but no TLS; rate limiter is in-memory only |
| UI completeness | A- | All major views exist; minor gaps in Trend/Compare UX |
| Infra coverage | A- | worker-03 down; FortiSwitch noise during tests |
| Memory (A/B) | B+ | MuninnDB: +4.6pp advantage confirmed; pg backend functional |
| Ops readiness | B | Schedules stored but not executed; no HTTPS; default password warning exists |
