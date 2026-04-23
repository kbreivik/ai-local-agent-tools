# CC PROMPT — v2.43.7 — feat(ui): Facts card on dashboard under Platform Core section

## What this does

The Facts tab exists under MONITOR but has no presence on the dashboard.
Add a FACTS card as a third item in the `PlatformCoreCards` 2-column grid,
occupying its own row below the existing PLATFORM CORE + COLLECTORS cards.

Data source: `GET /api/facts/summary` → `{total, by_tier, pending_conflicts,
recently_changed, last_refresh}`. Already used by the Facts tab. Add one
small `useEffect` to PlatformCoreCards to fetch this.

Card shows:
- Total fact count
- Confident facts count (tier very_high + high, confidence ≥ 0.7)
- Pending conflicts (if any, shown in amber/red)
- Last refresh timestamp
- Top 3 recently changed fact keys
- Click → navigates to Facts tab

Version bump: 2.43.6 → 2.43.7.

---

## Change — `gui/src/App.jsx` — add Facts card to PlatformCoreCards

### Step 1: add factsStats state to PlatformCoreCards

Inside `PlatformCoreCards`, near the existing `useState` declarations, add:

```js
const [factsStats, setFactsStats] = useState(null)
```

### Step 2: fetch facts summary

Inside the existing `useEffect` that calls `fetchStatus()` and `fetchMemoryHealth()`,
add a facts summary fetch alongside the others:

```js
const BASE = import.meta.env.VITE_API_BASE ?? ''
fetch(`${BASE}/api/facts/summary`, { headers: authHeaders() })
  .then(r => r.ok ? r.json() : null)
  .then(d => { if (d) setFactsStats(d) })
  .catch(() => {})
```

### Step 3: add the FACTS card

In the `return (...)` of `PlatformCoreCards`, locate the closing `</div>` of the
2-column grid (right after the COLLECTORS `</div>`):

```jsx
      </div>  {/* COLLECTORS */}
    </div>    {/* 2-col grid */}
```

Change the grid from `1fr 1fr` to keep facts on its own row:

Replace:
```jsx
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
```

With:
```jsx
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
```
(same — facts card will span both columns using gridColumn)

After the closing `</div>` of the COLLECTORS card and before the closing `</div>`
of the outer grid, insert the FACTS card:

```jsx
      {/* FACTS */}
      {factsStats && (() => {
        const total      = factsStats.total ?? 0
        const confident  = (factsStats.by_tier?.very_high ?? 0) + (factsStats.by_tier?.high ?? 0)
        const conflicts  = factsStats.pending_conflicts ?? 0
        const changed    = (factsStats.recently_changed || []).slice(0, 3)
        const lastRefresh = factsStats.last_refresh
        const factsHealth = conflicts > 0 ? 'amber' : total > 0 ? 'green' : 'grey'
        const factsHealthDot = factsHealth === 'green' ? 'var(--green)' : factsHealth === 'amber' ? 'var(--amber)' : 'var(--text-3)'
        const ago = (iso) => {
          if (!iso) return ''
          const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
          if (s < 60) return `${s}s ago`
          if (s < 3600) return `${Math.round(s / 60)}m ago`
          return `${Math.round(s / 3600)}h ago`
        }
        return (
          <div
            onClick={() => onTab?.('Facts')}
            style={{
              gridColumn: '1 / -1',   // span full width
              background: 'var(--bg-2)', border: '1px solid var(--border)',
              borderLeft: `3px solid ${factsHealthDot}`,
              borderRadius: 2, padding: '8px 10px', cursor: 'pointer',
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-3)'}
            onMouseLeave={e => e.currentTarget.style.background = 'var(--bg-2)'}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 11, color: 'var(--text-1)', letterSpacing: 0.5 }}>
                FACTS & KNOWLEDGE
              </div>
              <span style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
                {lastRefresh ? `refreshed ${ago(lastRefresh)}` : ''}
              </span>
            </div>
            <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 16, fontWeight: 700, color: 'var(--text-1)', lineHeight: 1 }}>
                  {total.toLocaleString()}
                </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: 1 }}>total facts</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 16, fontWeight: 700, color: 'var(--green)', lineHeight: 1 }}>
                  {confident.toLocaleString()}
                </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: 1 }}>confident ≥0.7</span>
              </div>
              {conflicts > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 16, fontWeight: 700, color: 'var(--amber)', lineHeight: 1 }}>
                    {conflicts}
                  </span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--amber)', textTransform: 'uppercase', letterSpacing: 1 }}>conflicts</span>
                </div>
              )}
              {changed.length > 0 && (
                <div style={{ flex: 1, minWidth: 200 }}>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 3 }}>recently changed</div>
                  {changed.map((c, i) => (
                    <div key={i} style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--text-2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {typeof c === 'string' ? c : c.fact_key || JSON.stringify(c)}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )
      })()}
```

---

## Verification

After deploy, open the Dashboard. Under the PLATFORM CORE + COLLECTORS cards,
a FACTS & KNOWLEDGE card should appear spanning full width showing:
- Total fact count (should be ~100+)
- Confident count
- Any conflicts
- Recently changed fact keys
- Clicking it navigates to the Facts tab

---

## Version bump

Update `VERSION`: `2.43.6` → `2.43.7`

---

## Commit

```
git add -A
git commit -m "feat(ui): v2.43.7 Facts & Knowledge card on dashboard under Platform Core section"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
