/**
 * TemplateCardRenderer — renders card fields for a given phase using schema + template.
 *
 * Props:
 *   data       — card data object (container, swarm service, etc.)
 *   schema     — CONTAINER_SCHEMA or SWARM_SERVICE_SCHEMA
 *   renderers  — CONTAINER_FIELD_RENDERERS or SWARM_FIELD_RENDERERS
 *   template   — effective template {collapsed, expanded, entity_only, header_sub, hidden}
 *   phase      — 'collapsed' | 'expanded' | 'header_sub'
 *   state      — extra rendering state (tags, loading, callbacks, etc.)
 */
import React from 'react'

export default function TemplateCardRenderer({ data, schema, renderers, template, phase, state = {} }) {
  if (!data || !schema || !renderers || !template) return null

  // Build schema map for O(1) lookup
  const schemaMap = Object.fromEntries(schema.map(f => [f.key, f]))

  // Get fields for this phase from template
  const templateFields = template[phase] || []

  // Also render locked fields for this phase (problem, actions) — they're always included
  // even if not in the template's explicit list, but only if they have a renderer for this phase
  const lockedFields = schema
    .filter(f => f.locked && !templateFields.includes(f.key))
    .map(f => f.key)

  const allFields = phase === 'expanded'
    ? [...templateFields, ...lockedFields]   // actions always last
    : [...templateFields, ...lockedFields.filter(k => k !== 'actions')]

  return (
    <>
      {allFields.map(fieldKey => {
        const field = schemaMap[fieldKey]
        if (!field) return null

        const renderer = renderers[fieldKey]
        if (!renderer) return null

        // Select render function based on phase
        const renderFn = phase === 'expanded'
          ? renderer.renderExpanded
          : phase === 'collapsed'
          ? renderer.renderCollapsed
          : renderer.renderHeaderSub  // for phase === 'header_sub'

        if (!renderFn) return null

        let rendered = null
        try {
          rendered = renderFn({ data, state })
        } catch (e) {
          console.warn(`TemplateCardRenderer: error rendering field ${fieldKey}:`, e)
          return null
        }

        return rendered
          ? <React.Fragment key={fieldKey}>{rendered}</React.Fragment>
          : null
      })}
    </>
  )
}
