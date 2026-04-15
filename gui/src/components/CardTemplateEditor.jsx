/**
 * CardTemplateEditor — drag-and-drop card layout editor.
 *
 * Props:
 *   cardType       — 'container' | 'swarm_service' | 'proxmox_vm'
 *   schema         — CONTAINER_SCHEMA or SWARM_SERVICE_SCHEMA
 *   initialTemplate — template to start from (type default or connection override)
 *   onSave(template) — called when user saves
 *   onCancel        — called on cancel
 *   title           — optional override title
 */
import { useState, useCallback } from 'react'
import {
  DndContext, closestCenter, KeyboardSensor, PointerSensor, useSensor, useSensors,
} from '@dnd-kit/core'
import {
  arrayMove, SortableContext, sortableKeyboardCoordinates,
  useSortable, verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { CONTAINER_SCHEMA, SWARM_SERVICE_SCHEMA, DEFAULT_TEMPLATES } from '../schemas/cardSchemas'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

const SECTION_META = {
  header_sub:  { label: 'Line 2 (below name)',    limit: 1,    color: 'var(--cyan)',  hint: 'Shown below card name when collapsed. Max 1 field.' },
  collapsed:   { label: 'Collapsed (summary)',    limit: 10,   color: 'var(--green)', hint: 'Visible when card is collapsed. Max 10 fields.' },
  expanded:    { label: 'Expanded (detail)',       limit: null, color: 'var(--amber)', hint: 'Visible when card is expanded.' },
  entity_only: { label: 'Entity Drawer only',     limit: null, color: 'var(--text-3)', hint: 'Only shown in the entity detail drawer, not on the card.' },
  hidden:      { label: 'Hidden',                 limit: null, color: 'var(--text-3)', hint: 'Not displayed anywhere.' },
}

const SECTIONS_ORDER = ['header_sub', 'collapsed', 'expanded', 'entity_only', 'hidden']

function SortableField({ id, label, locked, sectionColor }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id, disabled: locked })
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    display: 'flex', alignItems: 'center', gap: 6,
    padding: '4px 8px', borderRadius: 2, marginBottom: 3,
    background: locked ? 'var(--bg-3)' : 'var(--bg-2)',
    border: `1px solid ${locked ? 'var(--border)' : sectionColor}22`,
    cursor: locked ? 'default' : 'grab',
    userSelect: 'none',
    fontSize: 10,
  }
  return (
    <div ref={setNodeRef} style={style} {...attributes} {...(locked ? {} : listeners)}>
      {!locked && (
        <span style={{ color: 'var(--text-3)', fontSize: 9, flexShrink: 0 }}>⣿</span>
      )}
      {locked && (
        <span style={{ color: 'var(--text-3)', fontSize: 8, flexShrink: 0 }}>🔒</span>
      )}
      <span style={{ color: locked ? 'var(--text-3)' : 'var(--text-1)' }}>{label}</span>
      {locked && (
        <span style={{ fontSize: 8, color: 'var(--text-3)', marginLeft: 4 }}>fixed</span>
      )}
    </div>
  )
}

function DropZone({ section, fields, schema, onDragOver, isOver }) {
  const meta = SECTION_META[section]
  const schemaMap = Object.fromEntries(schema.map(f => [f.key, f]))
  const atLimit = meta.limit != null && fields.length >= meta.limit

  return (
    <div style={{
      border: `1px solid ${isOver ? meta.color : 'var(--border)'}`,
      borderRadius: 2, padding: '8px 10px', background: isOver ? `${meta.color}08` : 'var(--bg-1)',
      transition: 'border-color 0.1s, background 0.1s', minHeight: 50,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <span style={{ fontSize: 8, fontFamily: 'var(--font-mono)', letterSpacing: 0.5,
          color: meta.color, fontWeight: 700 }}>
          {meta.label.toUpperCase()}
        </span>
        {meta.limit != null && (
          <span style={{ fontSize: 8, color: atLimit ? 'var(--amber)' : 'var(--text-3)' }}>
            {fields.length}/{meta.limit}
          </span>
        )}
        <span style={{ fontSize: 8, color: 'var(--text-3)', marginLeft: 4 }}>{meta.hint}</span>
      </div>
      <SortableContext
        items={fields.map(f => `${section}:${f}`)}
        strategy={verticalListSortingStrategy}
      >
        {fields.length === 0 && (
          <div style={{ fontSize: 9, color: 'var(--text-3)', fontStyle: 'italic', padding: '4px 0' }}>
            Drop fields here
          </div>
        )}
        {fields.map(key => {
          const field = schemaMap[key]
          return field ? (
            <SortableField
              key={`${section}:${key}`}
              id={`${section}:${key}`}
              label={field.label}
              locked={field.locked}
              sectionColor={meta.color}
            />
          ) : null
        })}
      </SortableContext>
    </div>
  )
}

function MiniCardPreview({ template, schema }) {
  const schemaMap = Object.fromEntries(schema.map(f => [f.key, f]))
  const headerSub = (template.header_sub || []).map(k => schemaMap[k]?.label).filter(Boolean)
  const collapsed  = (template.collapsed  || []).map(k => schemaMap[k]?.label).filter(Boolean)

  return (
    <div style={{
      border: '1px solid var(--border)', borderRadius: 2, padding: '6px 10px',
      background: 'var(--bg-2)', width: 180, flexShrink: 0,
    }}>
      <div style={{ fontSize: 8, fontFamily: 'var(--font-mono)', color: 'var(--text-3)',
        letterSpacing: 0.5, marginBottom: 6 }}>PREVIEW — COLLAPSED</div>

      {/* Card header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 2 }}>
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--green)', flexShrink: 0 }} />
        <span style={{ fontSize: 10, color: 'var(--text-1)', fontWeight: 600 }}>container-name</span>
        <span style={{ fontSize: 8, color: 'var(--text-3)' }}>▸</span>
      </div>

      {/* Header sub */}
      {headerSub.map((l, i) => (
        <div key={i} style={{ fontSize: 8, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', marginBottom: 2 }}>
          {l.toLowerCase()}_value
        </div>
      ))}

      {/* Collapsed fields */}
      {collapsed.slice(0, 5).map((l, i) => (
        <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 8,
          marginBottom: 1, fontFamily: 'var(--font-mono)' }}>
          <span style={{ color: 'var(--text-3)' }}>{l}</span>
          <span style={{ color: 'var(--text-2)' }}>value</span>
        </div>
      ))}
      {collapsed.length > 5 && (
        <div style={{ fontSize: 7, color: 'var(--text-3)', fontStyle: 'italic' }}>
          +{collapsed.length - 5} more
        </div>
      )}
      {collapsed.length === 0 && headerSub.length === 0 && (
        <div style={{ fontSize: 8, color: 'var(--text-3)', fontStyle: 'italic' }}>
          empty collapsed state
        </div>
      )}

      {/* buttons placeholder */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 4, marginTop: 4 }}>
        <span style={{ fontSize: 8, color: 'var(--amber)', opacity: 0.6 }}>⌘</span>
        <span style={{ fontSize: 8, color: 'var(--cyan)', opacity: 0.6 }}>›</span>
      </div>
    </div>
  )
}

export default function CardTemplateEditor({ cardType, schema, initialTemplate, onSave, onCancel, title, readOnly = false }) {
  // Build initial state: {section: [fieldKeys]}
  const _buildInitial = (t) => {
    const allKeys = schema.map(f => f.key)
    const placed = new Set()
    const sections = {}
    for (const sec of SECTIONS_ORDER) {
      sections[sec] = (t[sec] || []).filter(k => allKeys.includes(k))
      sections[sec].forEach(k => placed.add(k))
    }
    // Any unplaced fields go to hidden
    const unplaced = allKeys.filter(k => !placed.has(k))
    sections.hidden = [...sections.hidden, ...unplaced]
    return sections
  }

  const [sections, setSections] = useState(() => _buildInitial(initialTemplate || DEFAULT_TEMPLATES[cardType] || {}))
  const [activeId, setActiveId] = useState(null)
  const [overSection, setOverSection] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const schemaMap = Object.fromEntries(schema.map(f => [f.key, f]))

  // Parse composite ID: "section:fieldKey"
  const parseId = (id) => {
    const idx = id.indexOf(':')
    return { section: id.slice(0, idx), key: id.slice(idx + 1) }
  }

  const handleDragStart = ({ active }) => setActiveId(active.id)
  const handleDragOver = ({ over }) => {
    if (!over) { setOverSection(null); return }
    // over.id can be "section:key" (over a field) or a section container droppable
    const { section } = parseId(over.id)
    setOverSection(section)
  }

  const handleDragEnd = ({ active, over }) => {
    setActiveId(null)
    setOverSection(null)
    if (!over) return

    const { section: fromSec, key: fieldKey } = parseId(active.id)
    const { section: toSec, key: toKey }       = parseId(over.id)

    const field = schemaMap[fieldKey]
    if (!field || field.locked) return  // don't move locked fields

    const toMeta = SECTION_META[toSec]
    const currentInDest = sections[toSec] || []

    // Check limit (exclude the field itself if it's already in the dest section)
    const countAfterAdd = fromSec === toSec ? currentInDest.length : currentInDest.length + 1
    if (toMeta.limit != null && countAfterAdd > toMeta.limit) return

    setSections(prev => {
      const next = { ...prev }
      // Remove from source
      next[fromSec] = (next[fromSec] || []).filter(k => k !== fieldKey)
      // Add to dest
      if (fromSec === toSec) {
        // Reorder within same section
        const oldIdx = next[fromSec].indexOf(fieldKey)
        const newIdx = next[toSec].indexOf(toKey)
        next[fromSec] = arrayMove(next[fromSec], oldIdx === -1 ? 0 : oldIdx, newIdx === -1 ? 0 : newIdx)
      } else {
        // Move to new section
        const insertIdx = toKey && toKey !== fieldKey ? next[toSec].indexOf(toKey) : next[toSec].length
        const dest = [...next[toSec]]
        dest.splice(insertIdx === -1 ? dest.length : insertIdx, 0, fieldKey)
        next[toSec] = dest
      }
      return next
    })
  }

  const handleSave = async () => {
    // Build template from sections state
    const template = {}
    for (const sec of SECTIONS_ORDER) {
      template[sec] = sections[sec] || []
    }
    if (onSave) {
      setSaving(true)
      try { await onSave(template) }
      catch (e) { setSaveMsg('Save failed: ' + e.message) }
      setSaving(false)
    }
  }

  const handleReset = () => {
    const defaultTmpl = DEFAULT_TEMPLATES[cardType] || {}
    setSections(_buildInitial(defaultTmpl))
    setSaveMsg('')
  }

  return (
    <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
      {/* Editor area */}
      <div style={{ flex: 1 }}>
        {title && (
          <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', fontWeight: 700,
            color: 'var(--text-1)', letterSpacing: 0.5, marginBottom: 10 }}>
            {title}
          </div>
        )}

        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragStart={handleDragStart}
          onDragOver={handleDragOver}
          onDragEnd={handleDragEnd}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {SECTIONS_ORDER.map(section => (
              <DropZone
                key={section}
                section={section}
                fields={sections[section] || []}
                schema={schema}
                isOver={overSection === section}
              />
            ))}
          </div>
        </DndContext>

        {!readOnly && (
          <div style={{ display: 'flex', gap: 8, marginTop: 12, alignItems: 'center' }}>
            <button onClick={handleSave} disabled={saving}
              style={{ fontSize: 10, padding: '5px 14px', borderRadius: 2,
                background: 'var(--accent)', color: '#fff', border: 'none', cursor: 'pointer',
                opacity: saving ? 0.6 : 1, fontWeight: 600 }}>
              {saving ? 'Saving…' : 'Save Template'}
            </button>
            <button onClick={handleReset}
              style={{ fontSize: 10, padding: '5px 12px', borderRadius: 2,
                background: 'var(--bg-3)', color: 'var(--text-2)', border: '1px solid var(--border)',
                cursor: 'pointer' }}>
              Reset to Default
            </button>
            {onCancel && (
              <button onClick={onCancel}
                style={{ fontSize: 10, padding: '5px 12px', borderRadius: 2,
                  background: 'none', color: 'var(--text-3)', border: 'none', cursor: 'pointer' }}>
                Cancel
              </button>
            )}
            {saveMsg && <span style={{ fontSize: 9, color: 'var(--red)' }}>{saveMsg}</span>}
          </div>
        )}
      </div>

      {/* Live preview sidebar */}
      <div style={{ flexShrink: 0 }}>
        <div style={{ fontSize: 8, fontFamily: 'var(--font-mono)', color: 'var(--text-3)',
          letterSpacing: 0.5, marginBottom: 6 }}>PREVIEW</div>
        <MiniCardPreview
          template={{
            header_sub: sections.header_sub || [],
            collapsed:  sections.collapsed  || [],
          }}
          schema={schema}
        />
      </div>
    </div>
  )
}
