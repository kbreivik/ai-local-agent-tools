// FactDiffViewer — v2.35.0.1
// Renders a before/after diff for a fact's value change. Designed to be
// extensible via the `valueType` prop so future diff renderers for things
// like switch configs, firewall rules, or VM configs can plug in with a
// custom renderer without changing callers.
//
// Supported modes (auto-detected unless overridden):
//   - string  → character-ish (token-aware) diff
//   - number  → "prior → new (Δ)"
//   - array   → added / removed / unchanged markers
//   - object  → recursive tree diff with added/removed/modified keys
//   - mixed/unknown → JSON.stringify + string diff fallback

import React from 'react'

const COL_ADDED   = 'var(--cyan)'
const COL_REMOVED = 'var(--accent)'
const COL_MOD     = 'var(--amber)'
const COL_MUTED   = 'var(--text-3)'

function isPlainObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v)
}

function detectMode(prior, next) {
  if (typeof prior === 'string' && typeof next === 'string') return 'string'
  if (typeof prior === 'number' && typeof next === 'number') return 'number'
  if (Array.isArray(prior) && Array.isArray(next)) return 'array'
  if (isPlainObject(prior) && isPlainObject(next)) return 'object'
  return 'fallback'
}

// ── String diff — LCS-based token span diff ──────────────────────────────────

function tokenise(s) {
  // Split into runs of [word] or [non-word] — human-readable for IPs, paths.
  return String(s).split(/(\W+)/).filter(t => t.length > 0)
}

function lcsDiff(a, b) {
  // Longest-common-subsequence diff over token arrays.
  // Returns [{type: 'equal'|'add'|'del', value}] spans.
  const m = a.length, n = b.length
  const dp = Array.from({length: m + 1}, () => new Array(n + 1).fill(0))
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      if (a[i] === b[j]) dp[i][j] = dp[i+1][j+1] + 1
      else dp[i][j] = Math.max(dp[i+1][j], dp[i][j+1])
    }
  }
  const out = []
  let i = 0, j = 0
  while (i < m && j < n) {
    if (a[i] === b[j]) { out.push({type: 'equal', value: a[i]}); i++; j++ }
    else if (dp[i+1][j] >= dp[i][j+1]) { out.push({type: 'del', value: a[i]}); i++ }
    else { out.push({type: 'add', value: b[j]}); j++ }
  }
  while (i < m) { out.push({type: 'del', value: a[i++]}) }
  while (j < n) { out.push({type: 'add', value: b[j++]}) }
  return out
}

function StringDiff({ prior, next }) {
  const spans = lcsDiff(tokenise(prior), tokenise(next))
  return (
    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, lineHeight: 1.5, wordBreak: 'break-all' }}>
      {spans.map((s, i) => {
        if (s.type === 'equal') return <span key={i} style={{ color: 'var(--text-2)' }}>{s.value}</span>
        if (s.type === 'add')   return <span key={i} style={{ background: 'rgba(0,200,238,0.2)', color: COL_ADDED }}>{s.value}</span>
        return <span key={i} style={{ background: 'rgba(160,24,40,0.2)', color: COL_REMOVED, textDecoration: 'line-through' }}>{s.value}</span>
      })}
    </div>
  )
}

// ── Number diff ──────────────────────────────────────────────────────────────

function NumberDiff({ prior, next }) {
  const delta = next - prior
  const sign = delta > 0 ? '+' : ''
  return (
    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-2)' }}>
      <span style={{ color: COL_REMOVED }}>{prior}</span>
      <span style={{ color: COL_MUTED, margin: '0 6px' }}>→</span>
      <span style={{ color: COL_ADDED }}>{next}</span>
      <span style={{ color: COL_MUTED, marginLeft: 8, fontSize: 10 }}>
        Δ {sign}{delta}
      </span>
    </div>
  )
}

// ── Array diff ───────────────────────────────────────────────────────────────

function ArrayDiff({ prior, next }) {
  const pSet = new Set(prior.map(v => JSON.stringify(v)))
  const nSet = new Set(next.map(v => JSON.stringify(v)))
  const removed = prior.filter(v => !nSet.has(JSON.stringify(v)))
  const added   = next.filter(v => !pSet.has(JSON.stringify(v)))
  const kept    = prior.filter(v => nSet.has(JSON.stringify(v)))
  return (
    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>
      {removed.map((v, i) => (
        <div key={'r' + i} style={{ color: COL_REMOVED }}>- {JSON.stringify(v)}</div>
      ))}
      {added.map((v, i) => (
        <div key={'a' + i} style={{ color: COL_ADDED }}>+ {JSON.stringify(v)}</div>
      ))}
      {kept.map((v, i) => (
        <div key={'k' + i} style={{ color: COL_MUTED }}>  {JSON.stringify(v)}</div>
      ))}
    </div>
  )
}

// ── Object tree diff ─────────────────────────────────────────────────────────

function ObjectDiff({ prior, next, path = '' }) {
  const keys = Array.from(new Set([...Object.keys(prior), ...Object.keys(next)])).sort()
  return (
    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, paddingLeft: path ? 12 : 0 }}>
      {keys.map(k => {
        const inPrior = k in prior
        const inNext  = k in next
        const pv = prior[k], nv = next[k]
        const keyPath = path ? `${path}.${k}` : k
        if (!inPrior) {
          return <div key={keyPath} style={{ color: COL_ADDED }}>+ {k}: {JSON.stringify(nv)}</div>
        }
        if (!inNext) {
          return <div key={keyPath} style={{ color: COL_REMOVED }}>- {k}: {JSON.stringify(pv)}</div>
        }
        if (JSON.stringify(pv) === JSON.stringify(nv)) {
          return <div key={keyPath} style={{ color: COL_MUTED }}>  {k}: {JSON.stringify(pv)}</div>
        }
        if (isPlainObject(pv) && isPlainObject(nv)) {
          return (
            <div key={keyPath}>
              <div style={{ color: COL_MOD }}>~ {k}:</div>
              <ObjectDiff prior={pv} next={nv} path={keyPath} />
            </div>
          )
        }
        return (
          <div key={keyPath} style={{ color: COL_MOD }}>
            ~ {k}: <span style={{ color: COL_REMOVED, textDecoration: 'line-through' }}>{JSON.stringify(pv)}</span>
            {' '}
            <span style={{ color: COL_ADDED }}>{JSON.stringify(nv)}</span>
          </div>
        )
      })}
    </div>
  )
}

// ── Main component ──────────────────────────────────────────────────────────

export default function FactDiffViewer({
  priorValue, newValue,
  priorTimestamp, newTimestamp,
  source, actor,
  valueType = 'auto',
}) {
  const mode = valueType === 'auto' ? detectMode(priorValue, newValue) : valueType
  const header = `Changed${newTimestamp ? ` at ${newTimestamp}` : ''}${source ? ` by ${source}` : ''}`

  let body
  if (mode === 'string')      body = <StringDiff prior={String(priorValue ?? '')} next={String(newValue ?? '')} />
  else if (mode === 'number') body = <NumberDiff prior={Number(priorValue)} next={Number(newValue)} />
  else if (mode === 'array')  body = <ArrayDiff  prior={priorValue || []}    next={newValue || []} />
  else if (mode === 'object') body = <ObjectDiff prior={priorValue || {}}    next={newValue || {}} />
  else {
    body = <StringDiff prior={JSON.stringify(priorValue)} next={JSON.stringify(newValue)} />
  }

  return (
    <div style={{
      background: 'var(--bg-2)', border: '1px solid var(--border)',
      borderRadius: 2, padding: 10, marginTop: 6,
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 8, letterSpacing: 1,
        color: 'var(--text-3)', textTransform: 'uppercase', marginBottom: 6,
      }}>
        {header}{actor ? ` · actor=${actor}` : ''}
      </div>
      {body}
    </div>
  )
}
