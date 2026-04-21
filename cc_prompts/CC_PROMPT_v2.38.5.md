# CC PROMPT — v2.38.5 — Logs sub-pages: dates + UUIDs everywhere

## What this does

Kent's report after v2.38.3/4 landed: "date and time is needed in logs
sub pages, like escalations, and some db uuid reference is also
missing some places".

### Background

Six Logs sub-pages, three different timestamp-formatting conventions,
four different approaches to showing (or hiding) UUIDs:

| Sub-page | Timestamp | IDs currently shown |
|---|---|---|
| Tool Calls (`TcRow`) | time only | none |
| Operations (`OpsView`) | time only | v2.38.1 click-to-copy on `op.id` in row + Identifiers block in detail |
| Escalations (`EscView`) | time only (via `e.timestamp` → correctly populated by v2.37.1 endpoint mapping) | none — though API returns `id`, `session_id`, `operation_id`, `severity` |
| Session Output (`SessionOutputView`) header | time only | 8-char slice of `sessionId` with `…` suffix, NOT clickable |
| External AI Calls (`ExternalAICallsView`) | date + time ✓ (uses `toLocaleString`) | none — `id`, `operation_id`, `step_index` all in API response |
| Agent Actions (`AgentActionsTab`) | date + time + seconds, 24h ✓ (own `fmtTs`) | none in row — operation_id exists in API payload |

`AgentActionsTab`'s `fmtTs` is the right gold standard for the whole
Logs surface — 24h clock with full date, no AM/PM ambiguity, second
resolution for forensic log correlation.

`OpsView`'s v2.38.1 click-to-copy pattern is the right gold standard
for ID pills — 8-char truncated display, hover title showing full
UUID, click to copy, green ✓ flash for 1.5s.

Both patterns stay as-is. This prompt extracts them into shared
modules and adopts them across the remaining sub-pages. No backend
changes — all UUIDs are already in the API responses (verified in
`api/routers/logs.py::get_escalations` v2.37.1, `api/db/queries.py::
get_tool_calls`, `api/db/external_ai_calls.py::list_recent_external_calls`).

### Scope

1. **NEW** `gui/src/utils/fmtTs.js` — shared time formatters.
2. **NEW** `gui/src/components/CopyableId.jsx` — shared click-to-copy
   ID pill, extracted from v2.38.1 `LogTable::copyId` with the same
   UX (prefix+full-uuid title, green ✓ flash).
3. **EDIT** `gui/src/components/LogTable.jsx`:
   a. `fmtTs` calls shared formatter.
   b. `TcRow` gains an `ID` column + `Session` column.
   c. `EscView` gains columns: `Severity`, `Session`, `Operation`, `ID`
      (and keeps Time / Reason / Status / Resolve).
   d. `SessionOutputView` header replaces the truncated-with-ellipsis
      display with a full CopyableId.
   e. `OpsView` — call sites refactored to use shared CopyableId so
      the pattern is consistent (cosmetic; no behaviour change).
4. **EDIT** `gui/src/components/ExternalAICallsView.jsx`:
   a. `fmtTs` upgraded to the shared formatter (adds seconds).
   b. `ID` column added before `When`.
   c. `Operation` pill added under `Provider / Model`.
5. **EDIT** `gui/src/components/AgentActionsTab.jsx`:
   a. Replace local `fmtTs` with import of shared one (identical
      output — cosmetic refactor, keeps existing users unbroken).

Version bump: 2.38.4 → 2.38.5 (`.x.5` — UI polish patch, no schema).

---

## Change 1 — NEW `gui/src/utils/fmtTs.js`

```javascript
/**
 * Shared time formatters for Logs sub-pages + anywhere else a
 * timestamp renders. v2.38.5 replaces three inconsistent local
 * implementations (time-only toLocaleTimeString, mixed toLocaleString,
 * AgentActionsTab's full datetime) with one gold-standard output:
 * 24-hour "YYYY-MM-DD HH:MM:SS".
 *
 * No locale-dependent month names. No AM/PM. Forensic-grade second
 * resolution for log correlation.
 */

/**
 * "2026-04-21 14:32:08" — the primary format for every timestamp cell
 * in the Logs tab. Returns 'N/A' on null/undefined/invalid input so
 * callers don't need to defend against bad data.
 */
export function fmtDateTime(iso) {
  if (!iso) return 'N/A'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return 'N/A'
  // Use toLocaleString with a fixed, browser-independent format
  const yyyy = d.getFullYear()
  const mm   = String(d.getMonth() + 1).padStart(2, '0')
  const dd   = String(d.getDate()).padStart(2, '0')
  const hh   = String(d.getHours()).padStart(2, '0')
  const mi   = String(d.getMinutes()).padStart(2, '0')
  const ss   = String(d.getSeconds()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}:${ss}`
}

/**
 * "2026-04-21" — date only. Useful for column headers or grouping.
 */
export function fmtDate(iso) {
  if (!iso) return 'N/A'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return 'N/A'
  const yyyy = d.getFullYear()
  const mm   = String(d.getMonth() + 1).padStart(2, '0')
  const dd   = String(d.getDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}`
}

/**
 * "14:32:08" — time only, 24h, seconds included. Used in compact
 * rows where date is redundant (e.g. within-session raw output
 * feeds where every line is from the same day).
 */
export function fmtTime(iso) {
  if (!iso) return 'N/A'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return 'N/A'
  const hh   = String(d.getHours()).padStart(2, '0')
  const mi   = String(d.getMinutes()).padStart(2, '0')
  const ss   = String(d.getSeconds()).padStart(2, '0')
  return `${hh}:${mi}:${ss}`
}
```

---

## Change 2 — NEW `gui/src/components/CopyableId.jsx`

```javascript
import { useCallback, useState } from 'react'

/**
 * CopyableId — v2.38.5 shared click-to-copy ID pill.
 *
 * Extracted verbatim from v2.38.1's LogTable::copyId pattern so every
 * UUID field in the Logs sub-pages has the same UX:
 *   - 8-char truncated display (configurable)
 *   - hover title showing full UUID + "Click to copy"
 *   - click → clipboard.writeText with execCommand fallback
 *   - green ✓ flash for 1.5s on success
 *   - renders "—" in a muted style when value is null/empty
 *
 * Props:
 *   value:     string | number | null — the full ID to copy
 *   prefixLen: number — characters to display (default 8)
 *   label:     optional string shown inside the pill instead of the
 *              truncated value (e.g. "sess: a1b2c3d4"). If set,
 *              it's ALWAYS rendered — it does NOT fall back to showing
 *              the truncated value when label is truthy.
 *   dim:       boolean — render in muted colour (e.g. secondary IDs
 *              in a row where another ID is primary)
 *
 * Styling uses Tailwind classes that already exist in the bundle; no
 * new CSS. Matches the v2.38.1 pattern exactly so Operations view is
 * visually consistent.
 */
export default function CopyableId({
  value, prefixLen = 8, label = '', dim = false,
}) {
  const [copied, setCopied] = useState(false)

  const onClick = useCallback(async (e) => {
    if (e) e.stopPropagation()
    if (value == null || value === '') return
    const full = String(value)
    try {
      await navigator.clipboard.writeText(full)
    } catch {
      // Fallback for non-HTTPS / old browsers (copied from v2.38.1)
      const ta = document.createElement('textarea')
      ta.value = full
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      try { document.execCommand('copy') } catch {}
      document.body.removeChild(ta)
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }, [value])

  if (value == null || value === '') {
    return <span className="text-slate-700">—</span>
  }

  const full = String(value)
  const display = label || full.slice(0, prefixLen)
  const colour = dim ? 'text-slate-500 hover:text-slate-400'
                     : 'text-blue-300 hover:text-blue-200'

  return (
    <button
      onClick={onClick}
      title={copied ? 'Copied!' : `Click to copy: ${full}`}
      className={`font-mono text-xs ${colour}`}
      style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer' }}
    >
      {display}
      {copied && <span className="ml-1 text-green-400">✓</span>}
    </button>
  )
}
```

---

## Change 3 — `gui/src/components/LogTable.jsx`

### 3a — Replace local `fmtTs` at top of file

Find (top of file, after imports):

```javascript
const fmtTs = (ts) => {
  if (!ts) return 'N/A'
  const d = new Date(ts)
  return isNaN(d.getTime()) ? 'N/A' : d.toLocaleTimeString()
}
```

Replace with:

```javascript
import { fmtDateTime, fmtTime } from '../utils/fmtTs'
import CopyableId from './CopyableId'

// Keep the `fmtTs` name for minimal diff across the file — but now
// returns the v2.38.5 full "YYYY-MM-DD HH:MM:SS" format.
const fmtTs = fmtDateTime
```

Add those two imports alongside the existing imports at the top of
the file (above the `const FEEDBACK_ICON` line).

### 3b — `TcRow` gains `ID` + `Session` columns

Find the `TcRow` function — the `<tr>` with the tool-call columns.

Current:
```javascript
<tr className="border-b border-slate-800 hover:bg-slate-800 cursor-pointer text-xs" onClick={onClick}>
  <td className="px-2 py-1.5 text-slate-400 whitespace-nowrap">{ts}</td>
  <td className="px-2 py-1.5 text-blue-300 font-mono whitespace-nowrap">{log.tool_name}</td>
  <td className="px-2 py-1.5 text-slate-400 truncate max-w-[120px]">
    {Object.keys(params).length
      ? Object.entries(params).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(' ')
      : '—'}
  </td>
  <td className="px-2 py-1.5"><Badge status={log.status} /></td>
  <td className="px-2 py-1.5 text-slate-500 whitespace-nowrap">
    {log.duration_ms != null ? `${log.duration_ms}ms` : '—'}
  </td>
  <td className="px-2 py-1.5 text-slate-600 truncate max-w-[100px]" title={log.model_used}>
    {log.model_used?.split('/').pop() ?? '—'}
  </td>
</tr>
{expanded && (
  <tr className="bg-slate-900">
    <td colSpan={6} className="px-3 py-2">
```

Replace with:

```javascript
<tr className="border-b border-slate-800 hover:bg-slate-800 cursor-pointer text-xs" onClick={onClick}>
  <td className="px-2 py-1.5 text-slate-400 whitespace-nowrap">{ts}</td>
  <td className="px-2 py-1.5 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
    <CopyableId value={log.id} />
  </td>
  <td className="px-2 py-1.5 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
    <CopyableId value={log.session_id} dim />
  </td>
  <td className="px-2 py-1.5 text-blue-300 font-mono whitespace-nowrap">{log.tool_name}</td>
  <td className="px-2 py-1.5 text-slate-400 truncate max-w-[120px]">
    {Object.keys(params).length
      ? Object.entries(params).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(' ')
      : '—'}
  </td>
  <td className="px-2 py-1.5"><Badge status={log.status} /></td>
  <td className="px-2 py-1.5 text-slate-500 whitespace-nowrap">
    {log.duration_ms != null ? `${log.duration_ms}ms` : '—'}
  </td>
  <td className="px-2 py-1.5 text-slate-600 truncate max-w-[100px]" title={log.model_used}>
    {log.model_used?.split('/').pop() ?? '—'}
  </td>
</tr>
{expanded && (
  <tr className="bg-slate-900">
    <td colSpan={8} className="px-3 py-2">
```

Note: `colSpan` changes from `6` to `8` because we added two columns.

### 3c — Update `ToolCallsView` table headers

Find in `ToolCallsView`:

```javascript
<tr>{['Time','Tool','Params','Status','Duration','Model'].map(h => (
```

Replace with:

```javascript
<tr>{['Time','ID','Session','Tool','Params','Status','Duration','Model'].map(h => (
```

### 3d — `EscView` full upgrade

Find the entire `EscView` function. Replace with:

```javascript
export function EscView({ refreshTick }) {
  const [escs, setEscs]     = useState([])
  const [loading, setLoading] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    fetchEscalations(50).then(d => setEscs(d.escalations ?? [])).catch(() => {}).finally(() => setLoading(false))
  }, [])

  useEffect(load, [load, refreshTick])

  const resolve = async (id) => {
    await resolveEscalation(id).catch(() => {})
    load()
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center px-3 py-1.5 border-b border-slate-700 shrink-0">
        <span className="text-xs text-slate-500 uppercase font-bold">Escalations</span>
        <button onClick={load} className="ml-auto text-xs text-slate-500 hover:text-slate-300">↺</button>
      </div>
      <div className="flex-1 overflow-auto">
        {loading && <p className="text-xs text-slate-500 p-3 animate-pulse">Loading…</p>}
        {!loading && escs.length === 0 && <p className="text-xs text-slate-600 p-3">No escalations.</p>}
        {escs.length > 0 && (
          <table className="w-full border-collapse text-xs">
            <thead className="sticky top-0 bg-slate-900 border-b border-slate-700">
              <tr>{['Time','Severity','Reason','Session','Operation','Escalation ID','Status',''].map(h => (
                <th key={h} className="px-2 py-1.5 text-left text-slate-500 font-semibold uppercase text-xs whitespace-nowrap">{h}</th>
              ))}</tr>
            </thead>
            <tbody>
              {escs.map(e => (
                <tr key={e.id} className="border-b border-slate-800 hover:bg-slate-800">
                  <td className="px-2 py-1.5 text-slate-400 whitespace-nowrap font-mono">
                    {fmtTs(e.timestamp)}
                  </td>
                  <td className="px-2 py-1.5 whitespace-nowrap">
                    <Badge status={
                      e.severity === 'critical' ? 'failed'
                      : e.severity === 'warning' ? 'degraded'
                      : 'ok'
                    } />
                  </td>
                  <td className="px-2 py-1.5 text-slate-300 truncate max-w-[260px]" title={e.reason}>{e.reason}</td>
                  <td className="px-2 py-1.5 whitespace-nowrap">
                    <CopyableId value={e.session_id} dim />
                  </td>
                  <td className="px-2 py-1.5 whitespace-nowrap">
                    <CopyableId value={e.operation_id} dim />
                  </td>
                  <td className="px-2 py-1.5 whitespace-nowrap">
                    <CopyableId value={e.id} />
                  </td>
                  <td className="px-2 py-1.5">
                    <Badge status={e.resolved ? 'ok' : 'escalated'} />
                  </td>
                  <td className="px-2 py-1.5">
                    {!e.resolved && (
                      <button onClick={() => resolve(e.id)}
                        className="text-xs px-2 py-0.5 bg-slate-700 hover:bg-slate-600 rounded text-slate-300">
                        Resolve
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
```

The severity-to-status mapping in the Badge is cosmetic — red for
`critical`, amber for `warning`, green for anything else. Matches the
existing `STATUS_STYLE` palette without introducing a new one.

### 3e — `SessionOutputView` header: full clickable session ID

Find in `SessionOutputView` header:

```javascript
<span style={{ fontSize: 9, color: '#334155', fontFamily: 'var(--font-mono)' }}>
  {sessionId?.substring(0, 8)}\u2026
</span>
```

Replace with:

```javascript
<span style={{ fontSize: 9, fontFamily: 'var(--font-mono)' }}>
  <CopyableId value={sessionId} />
</span>
```

### 3f — `SessionOutputView` row timestamps: full date+time

Find inside the lines render:

```javascript
const ts = line.timestamp ? new Date(line.timestamp).toLocaleTimeString() : ''
```

Replace with:

```javascript
// v2.38.5: full "YYYY-MM-DD HH:MM:SS" — the row already has space in
// the left column because previous width was only for HH:MM:SS. Widen
// the left-column width so the date fits without wrapping.
const ts = line.timestamp ? fmtTs(line.timestamp) : ''
```

Then find the span rendering the timestamp:

```javascript
<span style={{ color: '#334155', flexShrink: 0, width: 58, fontSize: 9 }}>{ts}</span>
```

Replace with:

```javascript
<span style={{ color: '#334155', flexShrink: 0, width: 140, fontSize: 9 }}>{ts}</span>
```

Width bumped from 58px (time only) to 140px (full "YYYY-MM-DD HH:MM:SS"
at 9px mono font needs about 132px; 140px gives breathing room).

### 3g — `OpsView` refactor to shared CopyableId

Optional, cosmetic. The two call sites that render ID pills in OpsView
(one in the row, one in the detail Identifiers block) both duplicate
the copyId pattern. Replace them with CopyableId for consistency.

Find in the row:

```javascript
<button
  onClick={(e) => copyId(op.id, e)}
  title={copiedId === op.id ? 'Copied!' : `Click to copy: ${op.id || '(none)'}`}
  className="font-mono text-xs text-blue-300 hover:text-blue-200"
  style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer' }}
>
  {(op.id || '').slice(0, 8)}
  {copiedId === op.id && (
    <span className="ml-1 text-green-400">✓</span>
  )}
</button>
```

Replace with:

```javascript
<span onClick={(e) => e.stopPropagation()}>
  <CopyableId value={op.id} />
</span>
```

Find in the expanded Identifiers block, the Operation ID:

```javascript
<button
  onClick={(e) => copyId(detail.operation.id, e)}
  title={copiedId === detail.operation.id ? 'Copied!' : 'Click to copy'}
  className="font-mono text-blue-300 hover:text-blue-200"
  style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer' }}
>
  {detail.operation.id || '—'}
  {copiedId === detail.operation.id && (
    <span className="ml-2 text-green-400">✓ copied</span>
  )}
</button>
```

Replace with:

```javascript
<CopyableId value={detail.operation.id} prefixLen={36} />
```

(prefixLen=36 means the full UUID is displayed in the Identifiers
block — it's the "here's the full value" surface, unlike the 8-char
row pill.)

Same replacement for Session ID:

```javascript
<button
  onClick={(e) => copyId(detail.operation.session_id, e)}
  title={copiedId === detail.operation.session_id ? 'Copied!' : 'Click to copy'}
  className="font-mono text-blue-300 hover:text-blue-200"
  style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer' }}
>
  {detail.operation.session_id}
  {copiedId === detail.operation.session_id && (
    <span className="ml-2 text-green-400">✓ copied</span>
  )}
</button>
```

Replace with:

```javascript
<CopyableId value={detail.operation.session_id} prefixLen={36} />
```

Finally, remove the now-unused `copiedId` state and `copyId` callback
from the top of `OpsView`:

```javascript
// v2.38.1: flash "✓ copied" for 1.5s after click-to-copy on an ID pill.
const [copiedId, setCopiedId] = useState('')

// v2.38.1: click handler for the ID column and detail-row ID pills.
// Copies the full UUID, flashes a confirmation, falls back to
// document.execCommand on older browsers without clipboard API.
const copyId = useCallback(async (id, e) => {
  if (e) { e.stopPropagation() }
  if (!id) return
  try {
    await navigator.clipboard.writeText(id)
  } catch {
    // Fallback for non-HTTPS or old browsers
    const ta = document.createElement('textarea')
    ta.value = id
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    try { document.execCommand('copy') } catch {}
    document.body.removeChild(ta)
  }
  setCopiedId(id)
  setTimeout(() => setCopiedId(c => (c === id ? '' : c)), 1500)
}, [])
```

Remove this entire block. CopyableId owns the state now.

Also remove the `useCallback` import if it's no longer used elsewhere
in this file. (Check: the file also uses `useCallback` in `load`
inside `ToolCallsView`, `OpsView`, and `EscView`, so keep the import.)

---

## Change 4 — `gui/src/components/ExternalAICallsView.jsx`

### 4a — Add imports + replace `toLocaleString`

Find top of file:

```javascript
import React, { useState, useEffect } from 'react'

/**
 * v2.36.4 — Recent external AI calls table.
```

Replace with:

```javascript
import React, { useState, useEffect } from 'react'
import { fmtDateTime } from '../utils/fmtTs'
import CopyableId from './CopyableId'

/**
 * v2.36.4 — Recent external AI calls table.
 * v2.38.5 — gains ID + Operation columns; uses shared fmtDateTime so
 * timestamps show full YYYY-MM-DD HH:MM:SS like the other Logs tabs.
```

Find:

```javascript
<td className="py-2 text-xs text-gray-400">
  {new Date(r.created_at).toLocaleString()}
</td>
```

Replace with:

```javascript
<td className="py-2 text-xs text-gray-400 font-mono whitespace-nowrap">
  {fmtDateTime(r.created_at)}
</td>
```

### 4b — Add ID column + Operation pill

Find the thead row:

```javascript
<tr>
  <th className="text-left py-2">When</th>
  <th className="text-left">Provider / Model</th>
  <th className="text-left">Rule</th>
  <th className="text-left">Outcome</th>
  <th className="text-right">Latency</th>
  <th className="text-right">Tokens in/out</th>
  <th className="text-right">Est. $</th>
</tr>
```

Replace with:

```javascript
<tr>
  <th className="text-left py-2">When</th>
  <th className="text-left">ID</th>
  <th className="text-left">Provider / Model</th>
  <th className="text-left">Operation</th>
  <th className="text-left">Rule</th>
  <th className="text-left">Outcome</th>
  <th className="text-right">Latency</th>
  <th className="text-right">Tokens in/out</th>
  <th className="text-right">Est. $</th>
</tr>
```

Find the tbody row body. The current structure is:

```javascript
<tr key={r.id} className="border-b border-white/5 hover:bg-white/5">
  <td className="py-2 text-xs text-gray-400 font-mono whitespace-nowrap">
    {fmtDateTime(r.created_at)}
  </td>
  <td className="text-xs">
    <b className="text-[var(--cyan)]">{r.provider}</b> / {r.model}
  </td>
  <td className="text-xs"><code>{r.rule_fired}</code></td>
  ...
```

Update to insert the two new columns in the right positions:

```javascript
<tr key={r.id} className="border-b border-white/5 hover:bg-white/5">
  <td className="py-2 text-xs text-gray-400 font-mono whitespace-nowrap">
    {fmtDateTime(r.created_at)}
  </td>
  <td className="text-xs">
    <CopyableId value={r.id} prefixLen={8} />
  </td>
  <td className="text-xs">
    <b className="text-[var(--cyan)]">{r.provider}</b> / {r.model}
  </td>
  <td className="text-xs">
    <CopyableId value={r.operation_id} dim />
  </td>
  <td className="text-xs"><code>{r.rule_fired}</code></td>
  ...
```

Note: `r.id` in the external_ai_calls table is SERIAL (integer), not
UUID. CopyableId accepts numbers too — `String(value)` handles the
conversion.

---

## Change 5 — `gui/src/components/AgentActionsTab.jsx`

Cosmetic refactor. The local `fmtTs` in this file is exactly what the
new shared formatter does — just import the shared one to avoid drift.

Find at top of file:

```javascript
function fmtTs(iso) {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    return d.toLocaleString(undefined, {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      hour12: false,
    })
  } catch { return iso }
}
```

Replace with:

```javascript
import { fmtDateTime as fmtTs } from '../utils/fmtTs'
```

Add the import alongside the existing React import at the top of the
file. Delete the local `fmtTs` function body.

Note: the shared `fmtDateTime` returns `'N/A'` on null; the old local
`fmtTs` returned `'—'`. If any grid in AgentActionsTab depends on the
`—` (for visual consistency with other `—` cells), wrap the call site:

```javascript
{row.timestamp ? fmtTs(row.timestamp) : '—'}
```

Only one call site exists in AgentActionsTab (in the row render) —
audit it when applying the edit. If `row.timestamp` is always present
for audit events, no wrap needed.

---

## Change 6 — `VERSION`

```
2.38.5
```

---

## Change 7 — Tests

### NEW `tests/test_logs_subpages_id_coverage.py`

Structural guards — no runtime. Scans the frontend source files for
the required v2.38.5 surface.

```python
"""v2.38.5 — Logs sub-pages must expose DB UUIDs and full date+time.

Structural tests only; these are JSX source-file scans, not runtime
component tests (DEATHSTAR has no JSX test harness today).
"""
from __future__ import annotations

import pathlib

REPO_ROOT = pathlib.Path(__file__).parent.parent
GUI = REPO_ROOT / "gui" / "src"


def _read(rel: str) -> str:
    return (GUI / rel).read_text(encoding="utf-8")


def test_shared_fmtTs_util_exists():
    src = _read("utils/fmtTs.js")
    assert "export function fmtDateTime" in src
    assert "export function fmtDate" in src
    assert "export function fmtTime" in src
    # fmtDateTime must produce ISO-style output; loose but decisive
    # check: uses manual padStart to avoid locale dependence.
    assert "padStart(2, '0')" in src, (
        "fmtDateTime must build its own string — toLocaleTimeString "
        "is not locale-stable across browsers and breaks log "
        "correlation."
    )


def test_copyable_id_component_exists():
    src = _read("components/CopyableId.jsx")
    assert "export default function CopyableId" in src
    assert "navigator.clipboard.writeText" in src
    # execCommand fallback must be present (copied verbatim from
    # v2.38.1 — needed on non-HTTPS environments).
    assert "document.execCommand" in src, (
        "CopyableId must keep the execCommand fallback for non-HTTPS "
        "access (the GUI runs bare HTTP on 192.168.199.10)."
    )


def test_logtable_uses_shared_utils():
    src = _read("components/LogTable.jsx")
    assert "from '../utils/fmtTs'" in src
    assert "from './CopyableId'" in src
    # Old time-only formatter must be gone
    assert "toLocaleTimeString" not in src, (
        "LogTable.jsx should no longer call toLocaleTimeString — "
        "v2.38.5 routes every timestamp through fmtDateTime."
    )


def test_escview_shows_ids():
    """EscView must surface session_id, operation_id, and escalation id."""
    src = _read("components/LogTable.jsx")
    # Extract the EscView function body (from 'function EscView' or
    # 'export function EscView' to the next 'function' at column 0 or
    # 'export function').
    start = src.find("export function EscView")
    assert start >= 0, "EscView function not found"
    # End: either the next top-level 'export function' or EOF.
    end = src.find("export function", start + 1)
    if end < 0:
        end = len(src)
    body = src[start:end]

    # All three escalation ID surfaces must be rendered
    assert "e.session_id" in body, "EscView must render session_id"
    assert "e.operation_id" in body, "EscView must render operation_id"
    # Escalation row id IS referenced as key (`key={e.id}`); in
    # addition it must be in a CopyableId cell — check for the cell.
    assert "CopyableId value={e.id}" in body or \
           'CopyableId value={e.id}' in body, (
               "EscView must render the escalation id as a CopyableId "
               "pill, not just as the React key."
           )
    # Severity column must exist
    assert "e.severity" in body, "EscView must render severity"
    # Headers
    assert "'Escalation ID'" in body or '"Escalation ID"' in body
    assert "'Severity'" in body or '"Severity"' in body


def test_toolcall_row_shows_ids():
    """TcRow gained ID + Session columns in v2.38.5."""
    src = _read("components/LogTable.jsx")
    start = src.find("function TcRow")
    assert start >= 0
    end = src.find("function CorrelationView", start)
    assert end > start
    body = src[start:end]
    assert "CopyableId value={log.id}" in body
    assert "CopyableId value={log.session_id}" in body


def test_toolcalls_view_headers_updated():
    """Headers list must include the two new columns."""
    src = _read("components/LogTable.jsx")
    assert "'Time','ID','Session'" in src or \
           '"Time","ID","Session"' in src, (
               "ToolCallsView header row must list Time, ID, Session "
               "in the first three positions."
           )


def test_external_ai_calls_view_shows_ids():
    src = _read("components/ExternalAICallsView.jsx")
    assert "from '../utils/fmtTs'" in src
    assert "from './CopyableId'" in src
    assert "fmtDateTime(r.created_at)" in src
    assert "CopyableId value={r.id}" in src
    assert "CopyableId value={r.operation_id}" in src


def test_session_output_header_uses_copyable_id():
    """SessionOutputView header: truncated-with-ellipsis replaced by CopyableId."""
    src = _read("components/LogTable.jsx")
    # Old 'substring(0, 8)\u2026' pattern must be gone
    assert "sessionId?.substring(0, 8)" not in src, (
        "SessionOutputView header must not show the truncated "
        "session_id with an ellipsis — use CopyableId instead so "
        "the full id can be copied."
    )
    assert "<CopyableId value={sessionId}" in src


def test_agent_actions_tab_uses_shared_fmtTs():
    src = _read("components/AgentActionsTab.jsx")
    # Must import the shared util
    assert "from '../utils/fmtTs'" in src
    # The local fmtTs definition must be gone (its body contained
    # the tell-tale `hour12: false` option).
    # After refactor, that literal appears ONLY in utils/fmtTs.js —
    # not in AgentActionsTab.
    assert "hour12: false" not in src, (
        "AgentActionsTab must not define its own fmtTs — it should "
        "import the shared utility instead."
    )
```

---

## Verify

```bash
# Files created
test -f gui/src/utils/fmtTs.js        && echo "fmtTs.js exists"
test -f gui/src/components/CopyableId.jsx && echo "CopyableId.jsx exists"

# Shared util used where expected
grep -l "from '../utils/fmtTs'" gui/src/components/   # should list at least 3 files

# Time-only formatter gone from LogTable.jsx
! grep -q "toLocaleTimeString" gui/src/components/LogTable.jsx && echo "time-only gone"

# CopyableId usage count
grep -c "CopyableId" gui/src/components/LogTable.jsx              # >= 7
grep -c "CopyableId" gui/src/components/ExternalAICallsView.jsx   # >= 3

# Run tests
pytest tests/test_logs_subpages_id_coverage.py -v

# Run earlier v2.38.x tests to confirm nothing else broke
pytest tests/test_external_ai_client_decrypts_key.py -v
pytest tests/test_external_ai_route_failure_ux.py -v
pytest tests/test_command_panel_scroll_structure.py -v

# Vite build succeeds
cd gui && npm run build && cd -
```

---

## Commit

```bash
git add -A
git commit -m "fix(ui): v2.38.5 Logs sub-pages gain full date+time and DB UUID refs

Kent's followup after v2.38.3/4 landed: 'date and time is needed in
logs sub pages, like escalations, and some db uuid reference is also
missing some places'. Survey of Logs sub-pages found six views with
three different timestamp-formatting conventions and four different
approaches to surfacing UUIDs.

Consolidation:
- NEW gui/src/utils/fmtTs.js — shared fmtDateTime / fmtDate / fmtTime.
  Primary output is locale-independent 'YYYY-MM-DD HH:MM:SS' (24h,
  second resolution) built manually to avoid toLocaleTimeString
  inconsistency across browsers.
- NEW gui/src/components/CopyableId.jsx — shared click-to-copy ID pill
  extracted verbatim from v2.38.1's LogTable::copyId pattern. Includes
  the execCommand fallback for non-HTTPS access (the GUI runs on bare
  HTTP at 192.168.199.10).

Patches:
- LogTable.jsx::fmtTs — now an alias for fmtDateTime. Every timestamp
  cell in Tool Calls / Operations / Escalations / Session Output shows
  full date+time instead of just time-of-day, which was ambiguous
  across midnight rollovers.
- TcRow (Tool Calls) — gains ID + Session columns. Both use
  CopyableId. Backend api.db.queries.get_tool_calls already joined
  session_id via the operations table; we just weren't rendering it.
- EscView (Escalations) — new columns Severity / Session / Operation /
  Escalation ID. Severity uses the same Badge palette mapped from
  agent_escalations.severity (critical→failed red, warning→degraded
  amber). This was the worst-offender sub-page: previously had no IDs
  at all despite all four being returned by the v2.37.1 endpoint
  mapping in api/routers/logs.py::get_escalations.
- SessionOutputView header — truncated 'sessionId?.substring(0,8)…'
  replaced with a CopyableId pill showing the full ID on click. Row
  timestamp column widened 58px→140px to fit the new date+time format.
- OpsView — two existing copyId call sites refactored to use the
  shared CopyableId for consistency; the per-component copiedId state
  and copyId callback are removed (CopyableId owns them now). This is
  cosmetic — the v2.38.1 UX survives unchanged.
- ExternalAICallsView — gains ID + Operation columns; timestamp now
  uses fmtDateTime (adds seconds).
- AgentActionsTab — local fmtTs (functionally identical to the new
  shared one) replaced with an import so future tweaks land in one
  place.

Backend unchanged. All UUIDs were already in the API payloads, just
not displayed. Verified in api/routers/logs.py::get_escalations
(v2.37.1) for escalations, api/db/queries.py::get_tool_calls for
tool calls, and api/db/external_ai_calls.py::list_recent_external_calls
for external AI.

Tests: tests/test_logs_subpages_id_coverage.py (8 structural guards).
Scans JSX source files for the shared-util imports, CopyableId usage
at each of the new surfaces, and absence of the old time-only
toLocaleTimeString / substring-with-ellipsis patterns. Kent's repo
has no JSX test harness; these source-file scans catch regressions
via pytest.

No schema changes. No new Settings keys. No new deps. Builds with
the existing Vite setup."
git push origin main
```

---

## Deploy + smoke

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

Smoke plan (hard-refresh first):

1. **Operations** view — unchanged visually, but the ID pill should
   still flash ✓ green when clicked (regression guard against the
   CopyableId refactor).
2. **Tool Calls** view — new ID and Session columns appear between
   Time and Tool. Click the ID → clipboard has the tool_call UUID.
   Click the Session → clipboard has the session UUID.
3. **Escalations** view — should now show for each row: full
   date+time, severity pill (red/amber), session pill, operation pill,
   escalation-id pill. The Resolve button still works on
   non-acknowledged rows.
4. **Session Output** — open from any operation's Raw Output toggle.
   Header shows `[RAW OUTPUT]` next to a clickable session-id pill
   instead of "a1b2c3d4…". Row timestamps show `2026-04-21 14:32:08`
   instead of just `14:32:08`.
5. **External AI Calls** view — if there's a row from the v2.38.3/4
   smoke earlier, it should now display ID + Operation columns, and
   the timestamp should include seconds.
6. **Agent Actions** view — visually unchanged (cosmetic refactor
   only). Regression guard against the import swap.

---

## Scope guard — DO NOT TOUCH

- Any backend file under `api/`.
- `api/routers/logs.py::get_escalations` — v2.37.1 mapping already
  delivers the right field names; frontend change is sufficient.
- `OpsView` sorting / flashing / deep-link logic — only the ID pill
  rendering is refactored.
- `AgentFeed`, `OutputPanel`, `DashboardLayout`, any Dashboard card —
  out of scope.
- CSS theming (`index.css`) — CopyableId uses Tailwind classes
  already in the bundle.
- `gui/src/api.js` — no endpoint changes.

---

## Followups (not v2.38.5)

- v2.38.6 could add a lightweight operation_id → Logs Operations
  deep-link from the Escalations and External AI Calls rows (click
  operation pill → jump to Operations view with that session
  highlighted — the `highlightSessionId` prop on OpsView already
  supports this pattern).
- The `escalations` SQLAlchemy table in `api/db/models.py` is dead
  code since v2.37.1 rewired to `agent_escalations`. v2.38.7 or later
  could drop the model + the matching `create_escalation` /
  `resolve_escalation` / `count_unresolved_escalations` helpers in
  `api/db/queries.py`. Not touching here — dead code removal is a
  separate concern and the `count_unresolved_escalations` helper is
  still referenced in `q.get_stats()`.
- Consider a copy-all-identifiers button on the Operations detail
  Identifiers block: one click → `{op_id: ..., session_id: ...}` as
  JSON on clipboard, handy for pasting into an Analysis template
  that needs both.
