# HANDOFF — 2026-04-13T14:45:00+02:00

## Git state
```
feb929d fix(ui): v2.22.2 VMCard const id temporal dead zone crash
b7680bd chore: mark v2.22.1 DONE in prompt queue
1ac7d64 feat(ux): v2.22.1 skeleton loading + WebSocket-driven dashboard refresh
0012bd8 chore: mark v2.22.0 DONE in prompt queue
676fa82 feat(perf): v2.22.0 dashboard summary endpoint + DashboardDataContext
```
```
 M cc_prompts/QUEUE_STATE.json
 M cc_prompts/QUEUE_STATUS.md
 M cc_prompts/logs/20260413_143107_CC_PROMPT_v2.22.1.log
```

## Agent state
v2.22.2 build 412 standalone
Skills registered: 0

## Active plan
No active plans with pending status.

## What was accomplished this session
- **Diagnosed and fixed blank-page crash** in production GUI
- `gui/src/components/VMHostsSection.jsx` — moved `const id` declaration before useEffect hooks that reference it (TDZ fix)
- `VERSION` — bumped 2.22.1 → 2.22.2
- `api/users.py` — reset admin password in users table to match env var (runtime fix, not code change)
- Docker image rebuilt and deployed on agent-01 (build 412, commit feb929d)

## Decisions made
- Moved variable declaration rather than restructuring — minimal change to fix the crash
- Did not add a top-level React error boundary — that's a separate improvement (see report below)

## Dead ends
- Spent significant time checking auth/JWT issues (hostname-derived secret invalidation on container restart) — turned out login worked fine; the blank page was a React crash, not an auth problem
- Checked for circular imports, Tailwind CSS compilation issues, missing endpoints — none were the cause
- Initial confusion caused by container being rebuilt mid-investigation (v2.21.1 → v2.21.2 → v2.22.1) while debugging

## Active issues
- `Failed to decrypt value — key may have changed` on startup — SETTINGS_ENCRYPTION_KEY may have changed since connections were stored; non-fatal but credentials show as empty
- `JWT_SECRET not set` — still using hostname-derived fallback; sessions break on every container restart
- Filebeat stale alert: ongoing — not a blocker
- No top-level React error boundary — any crash above ServiceCardsErrorBoundary blanks the entire page silently

## Exact next action
Write the incident report and error-handling improvement recommendations (user requested this session).

## Context files for next session
- `gui/src/components/VMHostsSection.jsx` — the fixed file
- `gui/src/App.jsx` — needs a top-level error boundary wrapping the whole tree
- `gui/src/context/DashboardDataContext.jsx` — new in v2.22.0, central data provider
- `state/plans/` — no active plans
