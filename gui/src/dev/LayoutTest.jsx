/**
 * LayoutTest — dev-only layout verification overlay.
 * Access at: http://localhost:5173/?test=layout
 *
 * Measures real DOM widths and validates layout invariants.
 * Only mounts when import.meta.env.DEV && ?test=layout in URL.
 */
import { useState, useCallback } from 'react'

const PANEL_EXPECTED  = 360
const TOLERANCE       = 4   // px

function measure() {
  const results = []

  // 1. Duplicate CommandPanel check
  const panels = document.querySelectorAll('[data-component="CommandPanel"]')
  results.push({
    name:     'No duplicate CommandPanel (≤1 mounted)',
    pass:     panels.length <= 1,
    measured: `${panels.length} instance(s)`,
    expected: '≤ 1',
  })

  // 2. Panel column width
  const panelCol = document.querySelector('[data-testid="commands-panel-col"]')
  const mainCol  = document.querySelector('[data-testid="main-content"]')

  if (!panelCol || !mainCol) {
    results.push({ name: 'Grid columns found in DOM', pass: false, measured: 'missing', expected: 'both present' })
    return results
  }

  const panelW = panelCol.getBoundingClientRect().width
  const mainW  = mainCol.getBoundingClientRect().width
  const totalW = window.innerWidth

  // 3. Panel column: 0 or PANEL_EXPECTED
  const panelIsZero   = panelW <= TOLERANCE
  const panelIs360    = Math.abs(panelW - PANEL_EXPECTED) <= TOLERANCE
  results.push({
    name:     'Panel column: 0px (closed) or 360px (open)',
    pass:     panelIsZero || panelIs360,
    measured: `${Math.round(panelW)}px`,
    expected: `0px or ${PANEL_EXPECTED}px`,
  })

  // 4. Main content fills remainder
  const expectedMain = totalW - panelW
  results.push({
    name:     'Main content fills remaining width',
    pass:     Math.abs(mainW - expectedMain) <= TOLERANCE,
    measured: `${Math.round(mainW)}px`,
    expected: `${Math.round(expectedMain)}px (window ${totalW}px − panel ${Math.round(panelW)}px)`,
  })

  // 5. When panel is 0px: main fills full window width
  if (panelIsZero) {
    results.push({
      name:     'Panel closed → main equals full window width',
      pass:     Math.abs(mainW - totalW) <= TOLERANCE,
      measured: `${Math.round(mainW)}px`,
      expected: `${totalW}px`,
    })
  }

  // 6. When panel is 360px: main = window - 360
  if (panelIs360) {
    results.push({
      name:     'Panel open → main equals window − 360px',
      pass:     Math.abs(mainW - (totalW - PANEL_EXPECTED)) <= TOLERANCE,
      measured: `${Math.round(mainW)}px`,
      expected: `${totalW - PANEL_EXPECTED}px`,
    })
  }

  // 7. Output tab badge element check
  const outputBadge = document.querySelector('[data-testid="output-badge"]')
  results.push({
    name:     'Output tab badge element present in DOM',
    pass:     outputBadge !== null,
    measured: outputBadge ? 'found' : 'not found',
    expected: 'present',
  })

  return results
}

export default function LayoutTest() {
  const [results, setResults] = useState([])
  const [ran, setRan] = useState(false)

  const run = useCallback(() => {
    setResults(measure())
    setRan(true)
  }, [])

  const passed = results.filter(r => r.pass).length
  const failed = results.filter(r => !r.pass).length

  return (
    <div
      style={{
        position: 'fixed',
        bottom: 12,
        left: 12,
        zIndex: 9999,
        background: '#0f172a',
        border: '1px solid #334155',
        borderRadius: 8,
        padding: '12px 16px',
        minWidth: 420,
        maxWidth: 560,
        fontFamily: 'monospace',
        fontSize: 11,
        color: '#94a3b8',
        boxShadow: '0 4px 24px rgba(0,0,0,0.6)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ color: '#38bdf8', fontWeight: 700, fontSize: 12 }}>LAYOUT TEST</span>
        <span style={{ color: '#475569', fontSize: 10 }}>dev only — ?test=layout</span>
        <button
          onClick={run}
          style={{
            marginLeft: 'auto',
            background: '#1e40af',
            color: '#bfdbfe',
            border: 'none',
            borderRadius: 4,
            padding: '2px 8px',
            cursor: 'pointer',
            fontSize: 11,
          }}
        >
          ▶ Run
        </button>
      </div>

      {ran && (
        <>
          <div style={{ marginBottom: 6, color: failed > 0 ? '#f87171' : '#4ade80', fontWeight: 700 }}>
            {passed}/{results.length} passed {failed > 0 ? `— ${failed} FAILED` : '✓'}
          </div>
          {results.map((r, i) => (
            <div key={i} style={{ display: 'flex', gap: 6, marginBottom: 3 }}>
              <span style={{ color: r.pass ? '#4ade80' : '#f87171', width: 14, shrink: 0 }}>
                {r.pass ? '✓' : '✗'}
              </span>
              <span style={{ flex: 1, color: r.pass ? '#64748b' : '#fca5a5' }}>{r.name}</span>
              {!r.pass && (
                <span style={{ color: '#f87171', whiteSpace: 'nowrap' }}>
                  got {r.measured} / want {r.expected}
                </span>
              )}
            </div>
          ))}
          <div style={{ marginTop: 8, color: '#475569', fontSize: 10 }}>
            Tip: toggle panel, then re-run to test open/closed states
          </div>
        </>
      )}

      {!ran && (
        <div style={{ color: '#475569' }}>Click ▶ Run to measure layout</div>
      )}
    </div>
  )
}
