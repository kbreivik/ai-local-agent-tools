# CC PROMPT — v2.45.28 — feat(ui): Trend tab suite filter + Compare tab run-picker filter

## What this does
Two small UI gaps from the v2.45.17 audit, bundled because each is short:

1. **Trend tab — no per-suite filter.** The backend `/api/tests/trend`
   accepts `?suite_id=`, but the frontend only fetches `/api/tests/trend`
   without the param. Add a suite dropdown that re-fetches on change.

2. **Compare tab — no run-list filter.** The 4 run-pickers each show ALL
   recent runs, making selection painful when there are many. Add a
   per-picker "filter by suite" dropdown that narrows each picker's list to
   runs from one suite. Adds a top-level "filter all 4 by this suite"
   shortcut.

Version bump: 2.45.27 → 2.45.28

---

## Context

`gui/src/components/TestsPanel.jsx` already loads `suites` in TrendTab and
CompareTab; both have `suites` state populated. The wiring is what's missing.

Current TrendTab fetch (no suite_id):

```javascript
const load = useCallback(() => {
  api('/api/tests/trend').then(r => r.json()).then(d => setTrend(d.trend || [])).catch(() => {})
  api('/api/tests/suites').then(r => r.json()).then(d => setSuites(d.suites || [])).catch(() => {})
  api('/api/tests/schedules').then(r => r.json()).then(d => setSchedules(d.schedules || [])).catch(() => {})
}, [])
```

Current CompareTab pickers (all 4 see all runs):

```jsx
{[0,1,2,3].map(i => (
  <select key={i} value={selIds[i]} onChange={e => setSelIds(s => {...})}>
    <option value="">— run {i+1} —</option>
    {allRuns.map(r => <option key={r.id} value={r.id}>...</option>)}
  </select>
))}
```

---

## Change 1 — TrendTab: add suite filter dropdown

In `gui/src/components/TestsPanel.jsx`, find the `TrendTab` function. The
existing `const load = useCallback(...)` and `const [trend, ...]` declarations.

Add a new state slot near the existing state hooks:

```javascript
  const [trendSuiteFilter, setTrendSuiteFilter] = useState('')
```

Replace the existing `load` callback with one that takes `trendSuiteFilter`
into account:

```javascript
  const load = useCallback(() => {
    const trendUrl = trendSuiteFilter
      ? `/api/tests/trend?suite_id=${encodeURIComponent(trendSuiteFilter)}`
      : '/api/tests/trend'
    api(trendUrl).then(r => r.json()).then(d => setTrend(d.trend || [])).catch(() => {})
    api('/api/tests/suites').then(r => r.json()).then(d => setSuites(d.suites || [])).catch(() => {})
    api('/api/tests/schedules').then(r => r.json()).then(d => setSchedules(d.schedules || [])).catch(() => {})
  }, [trendSuiteFilter])
```

Find the existing `<Label>SCORE OVER TIME</Label>` line. Right above it,
insert a header row containing the dropdown:

```jsx
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <Label>SCORE OVER TIME</Label>
        <select
          value={trendSuiteFilter}
          onChange={e => setTrendSuiteFilter(e.target.value)}
          style={{
            fontFamily: 'var(--font-mono)', fontSize: 9,
            padding: '3px 7px', background: 'var(--bg-1)',
            border: '1px solid var(--border)', color: 'var(--text-2)',
            borderRadius: 2, marginLeft: 'auto',
          }}
        >
          <option value="">all suites</option>
          {suites.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </div>
```

CC: when wrapping the existing `<Label>` with this header row, REMOVE the
original standalone `<Label>SCORE OVER TIME</Label>` line — it is now inside
the wrapper. The header div replaces it.

---

## Change 2 — CompareTab: add per-picker suite filter

In the same file, find `function CompareTab()`. Add new state at the top:

```javascript
  const [pickerSuites, setPickerSuites] = useState(['','','',''])  // suite_id per picker
  const [allSuitesList, setAllSuitesList] = useState([])
```

In the existing `useEffect` that loads `allRuns`, also load suites:

```javascript
  useEffect(() => {
    api('/api/tests/runs?limit=100').then(r => r.json()).then(d => setAllRuns(d.runs || [])).catch(() => {})
    api('/api/tests/suites').then(r => r.json()).then(d => setAllSuitesList(d.suites || [])).catch(() => {})
  }, [])
```

Find the existing run-picker block (4 `<select>` elements via
`{[0,1,2,3].map(i => ...)}`). Replace that entire `[0,1,2,3].map(...)` block
with one that pairs each picker with a suite-filter dropdown:

```jsx
        {[0,1,2,3].map(i => {
          const filterSuite = pickerSuites[i]
          const filteredRuns = filterSuite
            ? allRuns.filter(r => r.suite_id === filterSuite || r.suite_name === filterSuite)
            : allRuns
          return (
            <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <select
                value={filterSuite}
                onChange={e => setPickerSuites(p => { const n=[...p]; n[i]=e.target.value; return n })}
                style={{
                  fontFamily: 'var(--font-mono)', fontSize: 8,
                  padding: '2px 5px', background: 'var(--bg-1)',
                  border: '1px solid var(--border)', color: 'var(--text-3)',
                  borderRadius: 2, maxWidth: 200,
                }}
              >
                <option value="">all suites</option>
                {allSuitesList.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
              <select
                value={selIds[i]}
                onChange={e => setSelIds(s => { const n=[...s]; n[i]=e.target.value; return n })}
                style={{
                  fontFamily: 'var(--font-mono)', fontSize: 9,
                  padding: '3px 7px', background: 'var(--bg-1)',
                  border: '1px solid var(--border)', color: 'var(--text-2)',
                  borderRadius: 2, maxWidth: 220,
                }}
              >
                <option value="">— run {i+1} —</option>
                {filteredRuns.map(r => (
                  <option key={r.id} value={r.id}>
                    {ago(r.started_at)} {r.suite_name || 'ad-hoc'} {r.score_pct?.toFixed(0)}%
                  </option>
                ))}
              </select>
            </div>
          )
        })}
```

Add a "filter all 4" shortcut button to the same row, right before the
`compare` button:

```jsx
        <select
          onChange={e => {
            const sid = e.target.value
            setPickerSuites([sid, sid, sid, sid])
          }}
          style={{
            fontFamily: 'var(--font-mono)', fontSize: 8,
            padding: '2px 5px', background: 'var(--bg-1)',
            border: '1px solid var(--border)', color: 'var(--text-3)',
            borderRadius: 2,
          }}
        >
          <option value="">filter all 4…</option>
          {allSuitesList.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
```

CC: place the "filter all 4" select between the 4 picker columns and the
existing `<Btn onClick={load} accent ...>compare</Btn>` button. The row's
flex layout already wraps, so the existing flex/gap settings will accommodate
the extra control.

---

## Verify

```bash
cd gui && npm run build 2>&1 | tail -20
```

Expected: build succeeds. After deploy:
- Trend tab shows a "all suites" dropdown next to "SCORE OVER TIME" — picking
  a suite re-fetches and redraws the line for that suite only.
- Compare tab shows a small filter dropdown above each of the 4 run pickers.
  Picking a suite narrows that picker's list. The "filter all 4" shortcut
  applies the suite to all 4 pickers in one click.

---

## Version bump

Update `VERSION`: `2.45.27` → `2.45.28`

---

## Commit

```
git add -A
git commit -m "feat(ui): v2.45.28 Trend tab suite filter + Compare tab run-picker filters"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
