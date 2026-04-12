# CC PROMPT — v2.12.1 — Security Dashboard: SSH capability map UI

## What this does

The `ssh_capabilities` table (built in Phase 2 / v2.6.x) tracks every credential→host
pair that has been tested via SSH, with success rates, latency, and new-host alerts.
This adds a UI for it in the Settings → Access tab or a new Security section.

Version bump: 2.12.0 → 2.12.1 (GUI only on top of existing DB layer, x.x.1)

---

## Change 1 — gui/src/components/SettingsPage.jsx — add SSH Capabilities tab

Find the Settings tab list. Add a new tab: "SSH Access".

The tab content should show:

### Summary bar (top)
Fetch `GET /api/logs/ssh/capabilities/summary` and display:
- Total credential→host pairs verified
- Active in last 24h
- Stale (verified but no success >24h) — amber badge
- New host alerts — red badge if > 0

### Alert banner (if new_host_alerts > 0)
```jsx
{summary.new_host_alerts > 0 && (
  <div style={{
    padding: '8px 12px', marginBottom: 12,
    background: 'rgba(204,40,40,0.1)', border: '1px solid var(--red)',
    borderRadius: 2, fontFamily: 'var(--font-mono)', fontSize: 10,
    color: 'var(--red)',
  }}>
    ⚠ {summary.new_host_alerts} credential(s) gained access to new host(s).
    Review below — expected if you added new connections, investigate if not.
  </div>
)}
```

### Capability table
Fetch `GET /api/logs/ssh/capabilities?verified_only=false&days=30` and render a table:

| Credential label | Host | Username | Last success | Success rate | Avg latency | Alert |
|---|---|---|---|---|---|---|
| hp1-ai-agent-lab | 192.168.199.10 | ubuntu | 2m ago | 98% | 145ms | — |
| manager-01 | 192.168.199.31 | ubuntu | 5m ago | 100% | 220ms | 🆕 NEW |

Colour coding:
- Success rate < 80% → amber
- Success rate < 50% → red
- new_host_alert = true → red "🆕 NEW" badge, row highlighted
- last_success > 24h → amber "stale" label

### New host alerts section (below table)
Fetch `GET /api/logs/ssh/capabilities/alerts` — list each alert with:
- Which credential, which host, when first seen
- "Mark reviewed" button → calls a new endpoint to clear the alert flag

---

## Change 2 — api/routers/logs.py — add mark-reviewed endpoint

```python
@router.post("/ssh/capabilities/alerts/{connection_id}/reviewed")
async def mark_capability_reviewed(
    connection_id: str,
    target_host: str = Query(...),
    _: str = Depends(get_current_user),
):
    """Clear the new_host_alert flag after operator review."""
    if not _is_pg():
        return {"status": "error", "message": "Postgres required"}
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE ssh_capabilities
            SET new_host_alert = false
            WHERE connection_id = %s AND target_host = %s
        """, (connection_id, target_host))
        conn.commit(); cur.close(); conn.close()
        return {"status": "ok", "message": "Alert cleared"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

---

## Change 3 — gui: SSH log viewer (lightweight)

Below the capability table, add a collapsible "Recent SSH attempts" log viewer.
Fetch `GET /api/logs/ssh?limit=50` and render a compact table:
- Timestamp | Host | User | Outcome | Duration | Triggered by

Outcome badge colours:
- success → green dot
- auth_fail → red "AUTH FAIL"
- timeout → amber "TIMEOUT"
- refused → red "REFUSED"
- error → red "ERROR"

This gives operators a full audit trail of SSH activity without needing
to query Postgres directly.

---

## Version bump

Update VERSION: `2.12.0` → `2.12.1`

---

## Commit

```bash
git add -A
git commit -m "feat(gui): v2.12.1 SSH capability map security dashboard

- Settings → SSH Access tab: credential→host pair map with success rates
- Summary bar: verified pairs, active 24h, stale, new-host alert count
- New host alert banner + per-row NEW badge for unexpected access
- POST /api/logs/ssh/capabilities/alerts/{id}/reviewed: clear alert flag
- Recent SSH attempts log viewer (outcome, latency, triggered_by)"
git push origin main
```
