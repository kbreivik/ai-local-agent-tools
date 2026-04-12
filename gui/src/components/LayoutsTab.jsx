/**
 * LayoutsTab — Settings tab for managing dashboard layouts.
 * Template gallery, per-user prefs, import/export, reset.
 */
import { useState, useEffect } from 'react'
import { authHeaders } from '../api'
import { DEFAULT_LAYOUT } from '../hooks/useLayout'

const BASE = import.meta.env.VITE_API_BASE ?? ''

// Mini ASCII preview of a layout
function LayoutPreview({ layout }) {
  const rows = layout?.rows || []
  return (
    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 8, lineHeight: 1.6, color: 'var(--text-3)' }}>
      {rows.map((row, i) => {
        const collapsed = layout.collapsed || []
        const isConstrained = row.heightMode === 'constrained'
        return (
          <div key={i} style={{ display: 'flex', gap: 2, alignItems: 'center' }}>
            {row.tiles.map((t, j) => {
              const isCollapsed = collapsed.includes(t)
              return (
                <span key={j} style={{
                  flex: row.flex?.[j] ?? 1,
                  padding: '1px 3px',
                  background: isCollapsed ? 'var(--bg-3)' : 'var(--bg-4)',
                  border: '1px solid var(--border)',
                  borderRadius: 1,
                  textAlign: 'center',
                  color: isCollapsed ? 'var(--text-3)' : 'var(--text-2)',
                  opacity: isCollapsed ? 0.5 : 1,
                }}>
                  {t.slice(0, 4)}
                </span>
              )
            })}
            {isConstrained && <span style={{ fontSize: 7, color: 'var(--cyan)', flexShrink: 0 }} title="Constrained height">⊡</span>}
          </div>
        )
      })}
    </div>
  )
}

export default function LayoutsTab({ layout = {}, dirty, saveLayout, applyTemplate, setLayout }) {
  const [templates, setTemplates] = useState([])
  const [loadingTemplates, setLoadingTemplates] = useState(true)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    fetch(`${BASE}/api/layout/templates`, { headers: { ...authHeaders() } })
      .then(r => r.json())
      .then(d => { setTemplates(d.data || []); setLoadingTemplates(false) })
      .catch(() => setLoadingTemplates(false))
  }, [])

  const flash = (text) => { setMsg(text); setTimeout(() => setMsg(''), 2000) }

  const handleApplyTemplate = (tpl) => {
    applyTemplate?.(tpl.layout)
    saveLayout?.(tpl.layout)
    flash(`Applied "${tpl.name}" layout`)
  }

  const handleExport = () => {
    const blob = new Blob([JSON.stringify(layout, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `layout-${layout.template || 'custom'}.json`
    a.click()
    URL.revokeObjectURL(url)
    flash('Exported')
  }

  const handleImport = () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.json'
    input.onchange = (e) => {
      const file = e.target.files[0]
      if (!file) return
      const reader = new FileReader()
      reader.onload = (ev) => {
        try {
          const imported = JSON.parse(ev.target.result)
          if (!imported.rows) throw new Error('Invalid layout')
          applyTemplate(imported)
          saveLayout(imported)
          flash('Imported successfully')
        } catch {
          flash('Invalid layout file')
        }
      }
      reader.readAsText(file)
    }
    input.click()
  }

  const handleReset = () => {
    applyTemplate?.(DEFAULT_LAYOUT)
    saveLayout?.(DEFAULT_LAYOUT)
    flash('Reset to default')
  }

  const handleSaveAsTemplate = () => {
    const name = prompt('Template name:')
    if (!name) return
    const templateLayout = { ...layout, template: name, shared: false }
    setLayout?.(templateLayout)
    saveLayout?.(templateLayout)
    flash(`Saved as "${name}"`)
  }

  const _btn = (accent) => ({
    padding: '4px 10px', fontSize: 10, fontFamily: 'var(--font-mono)',
    background: accent ? 'var(--accent-dim)' : 'var(--bg-3)',
    color: accent ? 'var(--accent)' : 'var(--text-2)',
    border: `1px solid ${accent ? 'var(--accent)' : 'var(--border)'}`,
    borderRadius: 2, cursor: 'pointer',
  })

  return (
    <div>
      {msg && (
        <div style={{ marginBottom: 12, padding: '4px 10px', fontSize: 10, fontFamily: 'var(--font-mono)',
                       background: msg.includes('Invalid') ? 'var(--red-dim)' : 'var(--green-dim)',
                       color: msg.includes('Invalid') ? 'var(--red)' : 'var(--green)',
                       borderRadius: 2 }}>{msg}</div>
      )}

      {/* Template gallery */}
      <div style={{ marginBottom: 20 }}>
        <h3 style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 12, color: 'var(--text-1)', marginBottom: 8 }}>
          TEMPLATES
        </h3>
        {loadingTemplates && (
          <div style={{ fontSize: 10, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>Loading…</div>
        )}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
          {templates.map((tpl, i) => (
            <div key={i} onClick={() => handleApplyTemplate(tpl)} style={{
              padding: 8, background: 'var(--bg-2)', border: '1px solid var(--border)',
              borderRadius: 2, cursor: 'pointer', transition: 'border-color 0.15s',
            }} onMouseOver={e => e.currentTarget.style.borderColor = 'var(--accent)'}
               onMouseOut={e => e.currentTarget.style.borderColor = 'var(--border)'}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 10, color: 'var(--text-1)' }}>{tpl.name}</span>
                <span style={{ fontSize: 7, fontFamily: 'var(--font-mono)', padding: '1px 4px',
                               background: tpl.system ? 'var(--accent-dim)' : 'var(--cyan-dim)',
                               color: tpl.system ? 'var(--accent)' : 'var(--cyan)',
                               borderRadius: 2 }}>{tpl.system ? 'SYSTEM' : 'USER'}</span>
              </div>
              <div style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', marginBottom: 6 }}>
                {tpl.description}
              </div>
              <LayoutPreview layout={tpl.layout} />
            </div>
          ))}
        </div>
      </div>

      {/* Current layout info */}
      <div style={{ marginBottom: 20 }}>
        <h3 style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 12, color: 'var(--text-1)', marginBottom: 8 }}>
          CURRENT LAYOUT
        </h3>
        <div style={{ padding: 8, background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 2, marginBottom: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 11, color: 'var(--text-1)' }}>
              {layout.template || 'Custom'}
            </span>
            {dirty && <span className="ds-layout-dirty-dot" title="Unsaved changes" />}
          </div>
          <LayoutPreview layout={layout} />
        </div>
      </div>

      {/* Actions row */}
      <div style={{ marginBottom: 20 }}>
        <h3 style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 12, color: 'var(--text-1)', marginBottom: 8 }}>
          ACTIONS
        </h3>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button onClick={() => { saveLayout?.(); flash('Saved') }} style={_btn(dirty)}>
            {dirty && <span className="ds-layout-dirty-dot" style={{ marginRight: 4 }} />}
            SAVE
          </button>
          <button onClick={handleSaveAsTemplate} style={_btn(false)}>SAVE AS TEMPLATE</button>
          <button onClick={handleExport} style={_btn(false)}>EXPORT JSON</button>
          <button onClick={handleImport} style={_btn(false)}>IMPORT JSON</button>
          <button onClick={handleReset} style={_btn(false)}>RESET TO DEFAULT</button>
        </div>
      </div>

      {/* Per-user prefs */}
      <div>
        <h3 style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 12, color: 'var(--text-1)', marginBottom: 8 }}>
          PREFERENCES
        </h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-2)', cursor: 'pointer' }}>
            <input type="checkbox" checked={layout?.prefs?.drill_persist ?? true}
              onChange={e => {
                const l = { ...layout, prefs: { ...layout?.prefs, drill_persist: e.target.checked } }
                applyTemplate?.(l)
              }} />
            Persist drill filter between sessions
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-2)', cursor: 'pointer' }}>
            <input type="checkbox" checked={layout?.prefs?.compare_on_load ?? false}
              onChange={e => {
                const l = { ...layout, prefs: { ...layout?.prefs, compare_on_load: e.target.checked } }
                applyTemplate?.(l)
              }} />
            Enable compare mode on load
          </label>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-2)' }}>
            <span>Card density:</span>
            {['compact', 'normal', 'comfortable'].map(d => (
              <button key={d} onClick={() => {
                const l = { ...layout, prefs: { ...layout?.prefs, density: d } }
                applyTemplate?.(l)
              }} style={{
                padding: '2px 6px', fontSize: 9, fontFamily: 'var(--font-mono)',
                background: layout?.prefs?.density === d ? 'var(--accent-dim)' : 'transparent',
                color: layout?.prefs?.density === d ? 'var(--accent)' : 'var(--text-3)',
                border: `1px solid ${layout?.prefs?.density === d ? 'var(--accent)' : 'var(--border)'}`,
                borderRadius: 2, cursor: 'pointer',
              }}>{d}</button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
