/**
 * LayoutsTab — Settings tab for managing dashboard layouts.
 * Template gallery, per-user prefs, import/export, reset.
 */
import React, { useState, useEffect } from 'react'
import { authHeaders } from '../api'
import { DEFAULT_LAYOUT } from '../hooks/useLayout'
import CardTemplateEditor from './CardTemplateEditor'
import { CONTAINER_SCHEMA, SWARM_SERVICE_SCHEMA, DEFAULT_TEMPLATES, CONTAINER_FIELD_RENDERERS, SWARM_FIELD_RENDERERS } from '../schemas/cardSchemas'

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

// ── Card template preview ─────────────────────────────────────────────────────

function CardTemplatePreviewFull({ schema, renderers, template, cardType }) {
  // Mini fake data for preview rendering
  const FAKE = {
    container: {
      name: 'hp1_agent', image: 'ghcr.io/kbreivik/hp1-ai-agent:2.28.9',
      running_version: '2.28.9', built_at: '2026-04-15T12:00:00Z',
      uptime: '3d 14h', dot: 'green', ports: ['8000→8000/tcp'],
      networks: ['hp1_net'], ip_addresses: ['172.20.0.5'],
    },
    swarm_service: {
      name: 'kafka_broker-1', image: 'apache/kafka:3.7.0',
      running_replicas: 1, desired_replicas: 1, uptime: '5d 2h', dot: 'green',
    },
  }
  const fake = FAKE[cardType] || FAKE.container

  const S = {
    label: { color: 'var(--text-3)', fontSize: 9 },
    value: { fontFamily: 'var(--font-mono)', color: 'var(--text-2)', fontSize: 9 },
    row: { display: 'flex', justifyContent: 'space-between', fontSize: 9, marginBottom: 2 },
  }

  const renderSection = (phase) => {
    const fields = template[phase] || []
    const schemaMap = Object.fromEntries(schema.map(f => [f.key, f]))
    // Also include locked fields
    const locked = schema.filter(f => f.locked && !fields.includes(f.key)).map(f => f.key)
    const all = phase === 'expanded' ? [...fields, ...locked]
      : [...fields, ...locked.filter(k => k !== 'actions')]

    return all.map(key => {
      const renderer = renderers[key]
      if (!renderer) return null
      const fn = phase === 'header_sub' ? renderer.renderHeaderSub
               : phase === 'collapsed' ? renderer.renderCollapsed
               : renderer.renderExpanded
      if (!fn) return null
      try {
        const result = fn({ data: fake, state: {} })
        if (!result) return null
        return <React.Fragment key={key}>{result}</React.Fragment>
      } catch { return null }
    })
  }

  const headerSub = (() => {
    const renderer = renderers[(template.header_sub || [])[0]]
    if (!renderer?.renderHeaderSub) return null
    try { return renderer.renderHeaderSub({ data: fake, state: {} }) } catch { return null }
  })()

  return (
    <div style={{ display: 'flex', gap: 12 }}>
      {/* Collapsed preview */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 8, fontFamily: 'var(--font-mono)', color: 'var(--text-3)',
          letterSpacing: 0.5, marginBottom: 4 }}>COLLAPSED</div>
        <div style={{ border: '1px solid var(--border)', borderRadius: 2, padding: '8px 10px',
          background: 'var(--bg-2)' }}>
          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 2 }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--green)', flexShrink: 0 }} />
            <span style={{ fontSize: 11, color: 'var(--text-1)', fontWeight: 600 }}>{fake.name}</span>
            <span style={{ fontSize: 9, color: 'var(--text-3)' }}>▸</span>
          </div>
          {headerSub && (
            <div style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', marginBottom: 3 }}>
              {headerSub}
            </div>
          )}
          {renderSection('collapsed')}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 4, marginTop: 3 }}>
            <span style={{ fontSize: 9, color: 'var(--amber)', opacity: 0.65 }}>⌘</span>
            <span style={{ fontSize: 9, color: 'var(--cyan)' }}>›</span>
          </div>
        </div>
      </div>

      {/* Expanded preview */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 8, fontFamily: 'var(--font-mono)', color: 'var(--text-3)',
          letterSpacing: 0.5, marginBottom: 4 }}>EXPANDED</div>
        <div style={{ border: '1px solid var(--accent)', borderRadius: 2, padding: '10px',
          background: 'var(--bg-2)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 4 }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--green)', flexShrink: 0 }} />
            <span style={{ fontSize: 11, color: 'var(--text-1)', fontWeight: 600 }}>{fake.name}</span>
            <span style={{ fontSize: 9, color: 'var(--text-3)' }}>▾</span>
          </div>
          {renderSection('expanded')}
        </div>
      </div>
    </div>
  )
}

function CardTemplatesSection() {
  const [activeCardType, setActiveCardType] = useState(null)
  const [saving, setSaving] = useState(false)
  const [savedMsg, setSavedMsg] = useState('')
  const [templates, setTemplates] = useState({})

  const CARD_TYPES = [
    { key: 'container',     label: 'Container',       schema: CONTAINER_SCHEMA,     renderers: CONTAINER_FIELD_RENDERERS },
    { key: 'swarm_service', label: 'Swarm Service',   schema: SWARM_SERVICE_SCHEMA,  renderers: SWARM_FIELD_RENDERERS    },
  ]

  const fetchTemplates = () => {
    const BASE = import.meta.env.VITE_API_BASE ?? ''
    fetch(`${BASE}/api/card-templates/defaults`, { headers: authHeaders() })
      .then(r => r.ok ? r.json() : {})
      .then(d => setTemplates(d))
      .catch(() => {})
  }

  useEffect(() => { fetchTemplates() }, [])

  const saveTemplate = async (cardType, template) => {
    const BASE = import.meta.env.VITE_API_BASE ?? ''
    setSaving(true); setSavedMsg('')
    try {
      const r = await fetch(`${BASE}/api/card-templates/type/${cardType}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ template }),
      })
      if (r.ok) {
        setSavedMsg(`${cardType} saved`)
        setActiveCardType(null)
        fetchTemplates()
        const { invalidateCardTypeCache } = await import('../hooks/useCardTemplate')
        invalidateCardTypeCache(cardType)
      } else setSavedMsg('Save failed')
    } catch (e) { setSavedMsg('Save failed: ' + e.message) }
    setSaving(false)
  }

  return (
    <div style={{ marginTop: 24, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
      <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 700,
        color: 'var(--text-2)', letterSpacing: 1, marginBottom: 6 }}>
        CARD TEMPLATES
      </div>
      <p style={{ fontSize: 9, color: 'var(--text-3)', marginBottom: 10 }}>
        Drag fields between sections to change which information shows on collapsed vs expanded cards.
        Per-connection overrides can be set via the ◈ button in Settings → Connections.
      </p>

      {/* Card type pills */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
        {CARD_TYPES.map(({ key, label }) => (
          <button key={key}
            onClick={() => setActiveCardType(activeCardType === key ? null : key)}
            style={{ fontSize: 9, padding: '4px 12px', borderRadius: 2, cursor: 'pointer',
              fontFamily: 'var(--font-mono)', letterSpacing: 0.5,
              background: activeCardType === key ? 'var(--accent-dim)' : 'var(--bg-3)',
              color: activeCardType === key ? 'var(--accent)' : 'var(--text-3)',
              border: `1px solid ${activeCardType === key ? 'var(--accent)' : 'var(--border)'}` }}>
            {label.toUpperCase()}
          </button>
        ))}
      </div>

      {savedMsg && (
        <div style={{ fontSize: 9, color: savedMsg.includes('failed') ? 'var(--red)' : 'var(--green)',
          marginBottom: 8 }}>
          {savedMsg.includes('failed') ? '✕' : '✓'} {savedMsg}
        </div>
      )}

      {/* Live preview — always visible for the active type */}
      {activeCardType && (() => {
        const ct = CARD_TYPES.find(c => c.key === activeCardType)
        const tmpl = templates[activeCardType] || DEFAULT_TEMPLATES[activeCardType] || {}
        return (
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 8, fontFamily: 'var(--font-mono)', color: 'var(--text-3)',
              letterSpacing: 0.5, marginBottom: 6 }}>LIVE PREVIEW</div>
            <CardTemplatePreviewFull
              schema={ct.schema} renderers={ct.renderers}
              template={tmpl} cardType={activeCardType}
            />
          </div>
        )
      })()}

      {/* DnD editor */}
      {activeCardType && (() => {
        const ct = CARD_TYPES.find(c => c.key === activeCardType)
        return (
          <CardTemplateEditor
            key={activeCardType}
            cardType={activeCardType}
            schema={ct.schema}
            initialTemplate={templates[activeCardType] || DEFAULT_TEMPLATES[activeCardType] || {}}
            title={`${ct.label} — drag fields between sections`}
            onSave={(tmpl) => saveTemplate(activeCardType, tmpl)}
            onCancel={() => setActiveCardType(null)}
          />
        )
      })()}
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

      {/* Card Templates */}
      <CardTemplatesSection />
    </div>
  )
}
