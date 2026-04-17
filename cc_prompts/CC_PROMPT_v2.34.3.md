# CC PROMPT — v2.34.3 — fix(ui): pull-bar labels + self-recreate instructions

Two small UX fixes on the in-card pull progress block (v2.33.10 / v2.33.16).

## Issue 1 — header still says "DOWNLOADING" during extract + recreate phases

In v2.33.10's `ContainerCardExpanded` pull progress block, the header badge
reads the status value verbatim:

```
◐ STARTING    ↓ DOWNLOADING    ⊡ EXTRACTING    ⟳ RECREATING    ✓ DONE    ✕ ERROR
```

Screenshot from live use shows the header stuck on `↓ DOWNLOADING 70%` while
the message below reads `Extracting · 250.9 MB / 310.9 MB · 17 layers`. The
header and the message line are out of sync because the `status` field in the
pull-job state transitions slower than the `phase` field — `status` stays on
`downloading` until all layers are pulled, even though individual layers are
already extracting.

Fix: the header should always reflect the **current user-visible action**, not
the coarse status. Replace the status-based switch with a phase-derived label
that collapses all non-terminal states into a single "UPDATING" umbrella with
a phase subtitle:

## Issue 2 — "Agent recreation triggered" needs explicit browser refresh instructions

When the agent container recreates itself (self-update path), the frontend
shows:

```
✓ DONE
Agent recreation triggered — it will be back shortly
```

Users don't reliably know to hard-refresh. The websocket reconnects but cached
JS bundles and auth cookie cache can leave the UI in a half-alive state. Add
explicit `Ctrl+Shift+R` + re-login instructions to the self-recreate message.

Version bump: 2.34.2 → 2.34.3

---

## Change 1 — gui/src/components/ServiceCards.jsx — header label

Locate the pull-progress block in `ContainerCardExpanded` (currently around
the `{pullJob && (` JSX). Find the existing header switch:

```jsx
<span>
  {pullJob.status === 'starting'    && '◐ STARTING'}
  {pullJob.status === 'downloading' && '↓ DOWNLOADING'}
  {pullJob.status === 'extracting'  && '⊡ EXTRACTING'}
  {pullJob.status === 'recreating'  && '⟳ RECREATING'}
  {pullJob.status === 'done'        && '✓ DONE'}
  {pullJob.status === 'error'       && '✕ ERROR'}
</span>
```

Replace with a single "UPDATING" umbrella for all in-flight states. Keep the
per-phase subtitle as the existing message line below the bar:

```jsx
<span>
  {(pullJob.status === 'starting' ||
    pullJob.status === 'downloading' ||
    pullJob.status === 'extracting' ||
    pullJob.status === 'recreating') && '⟳ UPDATING'}
  {pullJob.status === 'done'  && '✓ DONE'}
  {pullJob.status === 'error' && '✕ ERROR'}
</span>
```

The phase-band colour logic (cyan / amber / green / red) can stay as-is.
The existing message line (`Extracting · 250.9 MB / 310.9 MB · 17 layers`)
already tells the user what stage it's in — the header just needs to stop
lying when those disagree.

## Change 2 — same file — self-recreate instructions

Find the two `_update_pull_job(..., message=...)` call sites in
`api/routers/dashboard.py` that emit on self-container completion:

```python
if _is_self_container(container):
    _restart_self_container()
    _update_pull_job(
        job_id, status="done", phase="done",
        message="Agent recreation triggered — it will be back shortly",
        completed_at=_time.time(), percent=100,
    )
```

The **message** is all that the frontend shows below the bar — we need more
than "it will be back shortly". Replace the message text:

```python
    _update_pull_job(
        job_id, status="done", phase="done",
        message=(
            "Agent recreation triggered. Wait ~30s, then "
            "hard-refresh this page (Ctrl+Shift+R) and log in again."
        ),
        completed_at=_time.time(), percent=100,
    )
```

Also set a new field `is_self_recreate: True` in the job state so the
frontend can render a dedicated visual treatment:

```python
    _update_pull_job(
        job_id, status="done", phase="done",
        message=(
            "Agent recreation triggered. Wait ~30s, then "
            "hard-refresh this page (Ctrl+Shift+R) and log in again."
        ),
        is_self_recreate=True,
        completed_at=_time.time(), percent=100,
    )
```

The non-self (`container.restart()`) branch stays with "Pull + restart complete".

## Change 3 — gui/src/components/ServiceCards.jsx — emphasise the refresh message

In the pull-progress block, below the existing message line, add a conditional
amber callout when `is_self_recreate` is true:

```jsx
<div style={{ color: 'var(--text-2)', fontSize: 9, lineHeight: 1.4 }}>
  {pullJob.message || pullJob.phase || '…'}
</div>
{pullJob.is_self_recreate && pullJob.status === 'done' && (
  <div style={{
    marginTop: 6, padding: '5px 8px',
    background: 'var(--amber-dim)',
    border: '1px solid var(--amber)',
    borderRadius: 2,
    fontFamily: 'var(--font-mono)', fontSize: 9,
    color: 'var(--amber)', lineHeight: 1.35,
  }}>
    ⚠ Hard-refresh now: <b>Ctrl+Shift+R</b> (macOS: <b>⌘+Shift+R</b>) then log in again.
  </div>
)}
```

Place it between the existing message line and the DISMISS button.

## Change 4 — tests

`tests/test_pull_self_recreate_message.py`:

```python
def test_self_recreate_message_contains_refresh_instructions():
    from api.routers import dashboard as d
    d._PULL_JOBS.clear()
    jid = d._new_pull_job("hp1_agent", None)
    d._update_pull_job(
        jid, status="done", phase="done",
        message="Agent recreation triggered. Wait ~30s, then "
                "hard-refresh this page (Ctrl+Shift+R) and log in again.",
        is_self_recreate=True,
        completed_at=123.0, percent=100,
    )
    job = d._PULL_JOBS[jid]
    assert job["percent"] == 100
    assert job["is_self_recreate"] is True
    assert "Ctrl+Shift+R" in job["message"]
    assert "log in" in job["message"].lower()

def test_non_self_recreate_has_no_flag():
    from api.routers import dashboard as d
    d._PULL_JOBS.clear()
    jid = d._new_pull_job("kafka_broker-1", None)
    d._update_pull_job(
        jid, status="done", phase="done",
        message="Pull + restart complete",
        completed_at=123.0, percent=100,
    )
    assert d._PULL_JOBS[jid].get("is_self_recreate") in (None, False)
```

## Version bump
Update `VERSION`: 2.34.2 → 2.34.3

## Commit
```
git add -A
git commit -m "fix(ui): v2.34.3 pull-bar shows UPDATING header + self-recreate needs hard-refresh"
git push origin main
```

## How to test after push
1. Redeploy.
2. Trigger a pull on any non-self container (e.g. kafka_broker-1). Header
   should cycle `⟳ UPDATING` through all stages, then `✓ DONE`, with the
   phase visible only in the message line below.
3. Trigger the self-update flow on hp1_agent. When the bar reaches 100%,
   the amber callout with `Ctrl+Shift+R` + log-in-again instructions must
   appear below the message.
4. Hit Ctrl+Shift+R → log in → verify the agent reconnects cleanly.
5. Regression: the DISMISS button still clears the pull-job state.
